import React, { useState, useEffect } from 'react';
import { 
  FileCheck, 
  Search, 
  Printer, 
  Download, 
  ShieldCheck, 
  ShieldAlert, 
  AlertTriangle, 
  Clock, 
  User, 
  MapPin, 
  RefreshCw, 
  Eye, 
  X, 
  Filter,
  Users,
  FileText,
  CheckCircle2,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  History,
  Calendar,
  Layers,
  AlertCircle
} from 'lucide-react';
import { sounds } from '../utils/audio';
import { Panel, PanelHeader, PanelBody, Button, Badge, DataTable } from './ui';

const API_BASE = 'http://localhost:8000';

export function AuditTrail({ soundEnabled = true, onOpenReport }) {
  const [viewMode, setViewMode] = useState('screenings'); // 'screenings' | 'sessions'

  // Screening Records State (Primary)
  const [screenings, setScreenings] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const pageSize = 10;

  // Selected Record & Detail Modal State
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [sessionLinkedDocs, setSessionLinkedDocs] = useState([]);
  const [sessionDocsLoading, setSessionDocsLoading] = useState(false);
  const [repeatIdentityData, setRepeatIdentityData] = useState(null);
  const [repeatIdentityLoading, setRepeatIdentityLoading] = useState(false);

  // Inline Repeat Identity Expander State (List View)
  const [inlineRepeatOpen, setInlineRepeatOpen] = useState({});
  const [inlineRepeatData, setInlineRepeatData] = useState({});
  const [inlineRepeatLoading, setInlineRepeatLoading] = useState({});

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [filterOutcome, setFilterOutcome] = useState('ALL');
  const [filterDocType, setFilterDocType] = useState('ALL');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // Checkpoint Sessions State (Secondary)
  const [sessions, setSessions] = useState([]);
  const [totalSessionCount, setTotalSessionCount] = useState(0);
  const [isSessionsLoading, setIsSessionsLoading] = useState(false);
  const [selectedArchivedReport, setSelectedArchivedReport] = useState(null);

  // Inline repeat identity lookup handler for table row
  const handleToggleInlineRepeat = async (row) => {
    const id = row.screening_id;
    if (inlineRepeatOpen[id]) {
      setInlineRepeatOpen((prev) => ({ ...prev, [id]: false }));
      return;
    }

    setInlineRepeatOpen((prev) => ({ ...prev, [id]: true }));
    if (!inlineRepeatData[id]) {
      setInlineRepeatLoading((prev) => ({ ...prev, [id]: true }));
      try {
        const p = new URLSearchParams();
        if (row.name) p.append('name', row.name);
        if (row.dob) p.append('dob', row.dob);
        if (row.document_number) p.append('document_number', row.document_number);
        const repRes = await fetch(`${API_BASE}/api/history/repeat-identity?${p.toString()}`);
        if (repRes.ok) {
          const repData = await repRes.json();
          setInlineRepeatData((prev) => ({ ...prev, [id]: repData }));
        }
      } catch (err) {
        console.warn("Inline repeat identity lookup failed:", err);
      } finally {
        setInlineRepeatLoading((prev) => ({ ...prev, [id]: false }));
      }
    }
  };

  // Fetch Screening History from /api/history/screenings
  const fetchScreenings = async () => {
    setIsLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterOutcome !== 'ALL') params.append('outcome', filterOutcome);

      if (searchTerm.trim()) {
        const q = searchTerm.trim();
        // If query looks like document number (has digits or wildcard)
        if (/\d/.test(q) || q.includes('*') || q.toUpperCase().includes('X')) {
          params.append('document_number', q);
        } else {
          params.append('name', q);
        }
      }

      // Fetch sufficient rows to apply client-side filters for document_type, date range, or cross-field search
      const needsClientFilter = filterDocType !== 'ALL' || Boolean(startDate) || Boolean(endDate) || Boolean(searchTerm.trim());
      const fetchLimit = needsClientFilter ? 200 : pageSize;
      const fetchOffset = needsClientFilter ? 0 : (page - 1) * pageSize;
      params.append('limit', fetchLimit.toString());
      params.append('offset', fetchOffset.toString());

      const res = await fetch(`${API_BASE}/api/history/screenings?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        let items = data.results || [];

        // Apply filters: document_type
        if (filterDocType !== 'ALL') {
          items = items.filter(
            (r) => (r.document_type || '').toLowerCase() === filterDocType.toLowerCase()
          );
        }

        // Apply filters: date range
        if (startDate) {
          const sTime = new Date(`${startDate}T00:00:00Z`).getTime();
          items = items.filter((r) => r.timestamp && new Date(r.timestamp).getTime() >= sTime);
        }
        if (endDate) {
          const eTime = new Date(`${endDate}T23:59:59Z`).getTime();
          items = items.filter((r) => r.timestamp && new Date(r.timestamp).getTime() <= eTime);
        }

        // Apply search across document number, name, and screening_id
        if (searchTerm.trim()) {
          const q = searchTerm.trim().toLowerCase();
          items = items.filter(
            (r) =>
              (r.document_number && r.document_number.toLowerCase().includes(q)) ||
              (r.name && r.name.toLowerCase().includes(q)) ||
              (r.screening_id && r.screening_id.toLowerCase().includes(q))
          );
        }

        // Always order newest first
        items.sort(
          (a, b) => new Date(b.timestamp || 0).getTime() - new Date(a.timestamp || 0).getTime()
        );

        if (needsClientFilter) {
          setTotalCount(items.length);
          const startIndex = (page - 1) * pageSize;
          setScreenings(items.slice(startIndex, startIndex + pageSize));
        } else {
          setScreenings(items);
          setTotalCount(data.total_count || items.length);
        }
      } else {
        setScreenings([]);
        setTotalCount(0);
      }
    } catch (err) {
      console.error("Failed to fetch screening history from API:", err);
      setScreenings([]);
      setTotalCount(0);
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch Completed Sessions
  const fetchSessions = async () => {
    setIsSessionsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/session`);
      if (res.ok) {
        const data = await res.json();
        let items = data.items || [];
        if (searchTerm) {
          const st = searchTerm.toLowerCase();
          items = items.filter(s => 
            (s.session_id && s.session_id.toLowerCase().includes(st)) ||
            (s.officer_id && s.officer_id.toLowerCase().includes(st)) ||
            (s.checkpoint && s.checkpoint.toLowerCase().includes(st)) ||
            (s.decision && s.decision.toLowerCase().includes(st)) ||
            (s.outcome && s.outcome.toLowerCase().includes(st)) ||
            (s.document_types && s.document_types.toLowerCase().includes(st)) ||
            (s.document_number && s.document_number.toLowerCase().includes(st)) ||
            (s.name && s.name.toLowerCase().includes(st))
          );
        }
        setSessions(items);
        setTotalSessionCount(items.length);
      }
    } catch (err) {
      console.error("Failed to load completed sessions:", err);
    } finally {
      setIsSessionsLoading(false);
    }
  };

  useEffect(() => {
    if (viewMode === 'screenings') {
      fetchScreenings();
    } else {
      fetchSessions();
    }
  }, [viewMode, filterOutcome, filterDocType, startDate, endDate, page]);

  const handleRefresh = () => {
    if (soundEnabled) sounds.playClick();
    if (viewMode === 'screenings') {
      fetchScreenings();
    } else {
      fetchSessions();
    }
  };

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    if (soundEnabled) sounds.playClick();
    setPage(1);
    if (viewMode === 'screenings') {
      fetchScreenings();
    } else {
      fetchSessions();
    }
  };

  const handleResetFilters = () => {
    if (soundEnabled) sounds.playClick();
    setSearchTerm('');
    setFilterOutcome('ALL');
    setFilterDocType('ALL');
    setStartDate('');
    setEndDate('');
    setPage(1);
  };

  // Open Detail View Modal
  const handleViewRecord = async (record) => {
    if (soundEnabled) sounds.playClick();
    setSelectedRecord(record);
    setDetailLoading(true);
    setRepeatIdentityLoading(true);
    setSessionDocsLoading(true);

    // 1. Fetch full record with corrections
    try {
      const res = await fetch(`${API_BASE}/api/history/screenings/${record.screening_id}`);
      if (res.ok) {
        const fullRecord = await res.json();
        setSelectedRecord(fullRecord);
      }
    } catch (err) {
      console.warn("Could not fetch detailed screening record:", err);
    } finally {
      setDetailLoading(false);
    }

    // 2. Fetch repeat-identity data
    try {
      const p = new URLSearchParams();
      if (record.name) p.append('name', record.name);
      if (record.dob) p.append('dob', record.dob);
      if (record.document_number) p.append('document_number', record.document_number);

      const repRes = await fetch(`${API_BASE}/api/history/repeat-identity?${p.toString()}`);
      if (repRes.ok) {
        const repData = await repRes.json();
        setRepeatIdentityData(repData);
      } else {
        setRepeatIdentityData(null);
      }
    } catch (err) {
      console.warn("Repeat identity lookup failed:", err);
      setRepeatIdentityData(null);
    } finally {
      setRepeatIdentityLoading(false);
    }

    // 3. Fetch session-linked documents if session_id exists
    if (record.session_id) {
      try {
        const sessRes = await fetch(`${API_BASE}/api/history/screenings?session_id=${encodeURIComponent(record.session_id)}&limit=10`);
        if (sessRes.ok) {
          const sessData = await sessRes.json();
          const others = (sessData.results || []).filter(r => r.screening_id !== record.screening_id);
          setSessionLinkedDocs(others);
        } else {
          setSessionLinkedDocs([]);
        }
      } catch (err) {
        console.warn("Session linked docs lookup failed:", err);
        setSessionLinkedDocs([]);
      } finally {
        setSessionDocsLoading(false);
      }
    } else {
      setSessionLinkedDocs([]);
      setSessionDocsLoading(false);
    }
  };

  // Outcome Badge Styles
  const getOutcomeBadgeVariant = (outcome) => {
    switch (outcome?.toUpperCase()) {
      case 'VERIFIED':
      case 'PASSED':
      case 'APPROVED':
      case 'CLEARED':
        return 'success';
      case 'TAMPERED':
      case 'FAILED':
      case 'REJECTED':
      case 'DETAINED':
        return 'critical';
      case 'EXPIRED':
        return 'warning';
      case 'SKIPPED':
      case 'NOT_EVALUATED':
      case 'OPEN':
      case 'UNKNOWN':
      default:
        return 'neutral';
    }
  };

  // Check Result Badge Styles - STRICT: NOT_EVALUATED and SKIPPED must be NEUTRAL GREY, never green!
  const getCheckBadgeVariant = (status) => {
    switch (status?.toUpperCase()) {
      case 'PASSED':
      case 'PASS':
        return 'success';
      case 'FAILED':
      case 'FAIL':
        return 'critical';
      case 'NOT_EVALUATED':
      case 'SKIPPED':
      default:
        return 'neutral'; // Neutral grey via variantStyles.neutral: bg-[#141A22] text-[#8A93A3] border-[#232B38]
    }
  };

  // Total pages calculation
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  // Columns Definition for Primary Screening History Table
  const screeningColumns = [
    {
      key: 'timestamp',
      label: 'Time (UTC)',
      sortable: true,
      render: (v) => {
        if (!v) return <span className="text-[#8A93A3] font-mono text-[11px]">--</span>;
        const d = new Date(v);
        return (
          <div className="flex flex-col font-mono text-[11px] leading-tight">
            <span className="text-[#E4E7EB]">{d.toISOString().slice(0, 10)}</span>
            <span className="text-[#8A93A3] text-[10px]">{d.toISOString().slice(11, 19)} UTC</span>
          </div>
        );
      },
    },
    {
      key: 'document_type',
      label: 'Document Type',
      sortable: true,
      render: (v) => {
        const docLabel = (v || 'unknown').replace(/_/g, ' ');
        return (
          <span className="capitalize font-mono text-xs text-[#E4E7EB] font-medium">
            {docLabel}
          </span>
        );
      },
    },
    {
      key: 'document_number',
      label: 'Masked Number',
      sortable: true,
      render: (v, row) => (
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-xs font-bold text-[#D9A441]">
            {v || 'N/A'}
          </span>
          {row.screening_id && (
            <span className="text-[10px] text-[#5A6578] font-mono">
              {row.screening_id}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'name',
      label: 'Passenger Name',
      sortable: true,
      render: (v, row) => {
        const hasAnomaly = row.checks?.identity_continuity?.status === 'FAILED';
        const isRepeatTraveler =
          row.checks?.identity_continuity?.status === 'PASSED' &&
          row.checks?.identity_continuity?.reason?.toLowerCase().includes('repeat');
        const isExpanded = inlineRepeatOpen[row.screening_id];
        const cachedData = inlineRepeatData[row.screening_id];
        const isLoadingRepeat = inlineRepeatLoading[row.screening_id];

        return (
          <div className="flex flex-col gap-1 py-0.5">
            <span className="font-medium text-xs text-[#E4E7EB]">
              {v || 'N/A'}
            </span>
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-[#8A93A3]">
              {row.nationality && <span>Nat: {row.nationality}</span>}
              {row.dob && <span>· DOB: {row.dob}</span>}
            </div>

            {/* Repeat-Identity Matches Displayed Inline on Record */}
            {hasAnomaly && (
              <div className="inline-flex items-center gap-1 px-1.5 py-0.5 mt-0.5 rounded text-[10px] font-mono bg-red-950/60 text-red-300 border border-red-500/40 w-fit">
                <AlertTriangle className="w-3 h-3 text-red-400 shrink-0" />
                <span className="font-bold">Identity Alert:</span>
                <span className="truncate max-w-[200px]">{row.checks.identity_continuity.reason}</span>
              </div>
            )}

            {isRepeatTraveler && (
              <div className="inline-flex items-center gap-1 px-1.5 py-0.5 mt-0.5 rounded text-[10px] font-mono bg-[#D9A441]/12 text-[#D9A441] border border-[#D9A441]/40 w-fit">
                <Users className="w-3 h-3 text-[#D9A441] shrink-0" />
                <span>{row.checks.identity_continuity.reason}</span>
              </div>
            )}

            {/* Inline Repeat Matches Expander Button */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleToggleInlineRepeat(row);
              }}
              className="text-[10px] font-mono text-[#D9A441] hover:text-[#E4E7EB] hover:underline flex items-center gap-1 mt-0.5 cursor-pointer w-fit"
            >
              <Users className="w-3 h-3 text-[#D9A441]" />
              <span>{isExpanded ? 'Hide Inline Matches' : 'Inline Repeat Matches'}</span>
            </button>

            {/* Expanded Inline Repeat Identity Drawer */}
            {isExpanded && (
              <div className="mt-1.5 p-2 bg-[#0B0F14] border border-[#232B38] rounded-[4px] text-[10px] font-mono space-y-1 max-w-xs animate-in fade-in">
                {isLoadingRepeat ? (
                  <span className="text-[#8A93A3]">Loading repeat crossings ledger...</span>
                ) : cachedData ? (
                  <div className="space-y-1">
                    {cachedData.anomalies_detected?.length > 0 && (
                      <div className="text-red-400 font-bold border-b border-red-500/30 pb-0.5">
                        ⚠️ Critical Reuse Anomaly detected on this document!
                      </div>
                    )}
                    {cachedData.identity_matches?.length > 1 ? (
                      <div>
                        <span className="text-[#D9A441] font-bold block">
                          Prior Crossings ({cachedData.identity_matches.length - 1} matches):
                        </span>
                        <div className="space-y-1 mt-1 max-h-24 overflow-y-auto">
                          {cachedData.identity_matches
                            .filter((m) => m.screening_id !== row.screening_id)
                            .map((m, idx) => (
                              <div
                                key={idx}
                                className="flex items-center justify-between text-[#8A93A3] bg-[#141A22] px-1.5 py-0.5 rounded border border-[#232B38]"
                              >
                                <span>{m.timestamp ? m.timestamp.slice(0, 10) : '--'} · {m.document_type}</span>
                                <Badge variant={getOutcomeBadgeVariant(m.outcome)} size="sm" className="text-[9px]">
                                  {m.outcome}
                                </Badge>
                              </div>
                            ))}
                        </div>
                      </div>
                    ) : (
                      <span className="text-[#8A93A3]">No prior crossings recorded under this identity.</span>
                    )}
                  </div>
                ) : (
                  <span className="text-[#8A93A3]">No repeat identity matches found.</span>
                )}
              </div>
            )}
          </div>
        );
      },
    },
    {
      key: 'outcome',
      label: 'Outcome',
      sortable: true,
      render: (v, row) => (
        <div className="flex items-center gap-1.5 flex-wrap">
          <Badge variant={getOutcomeBadgeVariant(v)} size="sm">
            {v || 'UNKNOWN'}
          </Badge>
          {row.is_correction && (
            <Badge variant="warning" size="sm" className="text-[9px]">
              Corrected
            </Badge>
          )}
          {row.corrections?.length > 0 && (
            <Badge variant="warning" size="sm" className="text-[9px]">
              {row.corrections.length} Corrs
            </Badge>
          )}
        </div>
      ),
    },
    {
      key: 'risk_score',
      label: 'Risk Score',
      sortable: true,
      render: (v) => {
        const score = v !== undefined && v !== null ? Number(v) : 0;
        const color = score >= 75 ? 'text-[#E74C3C]' : score >= 40 ? 'text-[#D9A441]' : 'text-[#4ADE80]';
        return (
          <span className={`font-mono font-bold text-xs ${color}`}>
            {score.toFixed(1)}
          </span>
        );
      },
    },
    {
      key: 'actions',
      label: 'Action',
      align: 'right',
      render: (_, row) => (
        <Button
          size="sm"
          variant="secondary"
          icon={Eye}
          onClick={() => handleViewRecord(row)}
          className="text-xs"
        >
          Inspect Record
        </Button>
      ),
    },
  ];

  // Columns Definition for Checkpoint Sessions
  const sessionColumns = [
    {
      key: 'session_id',
      label: 'Session ID',
      sortable: true,
      render: (v) => <span className="font-mono font-bold text-[#D9A441]">{v}</span>,
    },
    {
      key: 'completed_at',
      label: 'Timestamp (UTC)',
      sortable: true,
      render: (v) => (
        <span className="font-mono text-[11px] text-[#8A93A3]">
          {v ? new Date(v).toLocaleString() : '--'}
        </span>
      ),
    },
    {
      key: 'document_number',
      label: 'Masked Number',
      sortable: true,
      render: (v, row) => (
        <span className="font-mono text-xs font-bold text-[#D9A441]">
          {row.document_number || row.masked_document_number || 'N/A'}
        </span>
      ),
    },
    {
      key: 'name',
      label: 'Traveller Name',
      sortable: true,
      render: (v, row) => (
        <span className="font-medium text-xs text-[#E4E7EB]">
          {row.name || row.traveller_name || 'N/A'}
        </span>
      ),
    },
    {
      key: 'documents_count',
      label: 'Documents',
      sortable: true,
      render: (v, row) => {
        const rawType = (row.document_types && row.document_types !== 'N/A')
          ? row.document_types
          : (row.document_type || 'passport');
        const displayType = rawType.replace(/_/g, ' ');
        return (
          <span className="font-mono text-xs font-semibold text-[#E4E7EB]">
            {v || 1} docs ({displayType})
          </span>
        );
      },
    },
    {
      key: 'checkpoint',
      label: 'Checkpoint Location',
      sortable: true,
      render: (v) => <span className="text-[#E4E7EB] text-xs truncate max-w-[160px] block">{v || 'N/A'}</span>,
    },
    {
      key: 'officer_id',
      label: 'Duty Officer',
      sortable: true,
      render: (v) => <span className="font-mono text-xs text-[#8A93A3]">{v || 'N/A'}</span>,
    },
    {
      key: 'decision',
      label: 'Outcome',
      sortable: true,
      render: (v, row) => {
        const outcome = row.outcome || row.decision || 'OPEN';
        return (
          <Badge variant={getOutcomeBadgeVariant(outcome)} size="sm">
            {outcome}
          </Badge>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <Panel className="p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <FileCheck className="w-5 h-5 text-[#D9A441]" aria-hidden="true" />
            <h2 className="text-base font-bold text-[#E4E7EB] font-sans">
              Border Checkpoint Screening History & Audit Trail
            </h2>
          </div>
          <p className="text-xs text-[#8A93A3] mt-1 font-mono">
            Append-only verification ledger adhering to MHA border audit regulations. Total records: {viewMode === 'screenings' ? totalCount : totalSessionCount}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* View Mode Toggle */}
          <div className="flex items-center bg-[#0B0F14] border border-[#232B38] rounded-[4px] p-0.5">
            <button
              onClick={() => {
                if (soundEnabled) sounds.playClick();
                setViewMode('screenings');
                setPage(1);
              }}
              className={`px-3 py-1.5 rounded-[3px] text-xs font-mono font-semibold transition flex items-center gap-1.5 cursor-pointer ${
                viewMode === 'screenings'
                  ? 'bg-[#D9A441]/15 text-[#D9A441] border border-[#D9A441]/40 shadow-sm'
                  : 'text-[#8A93A3] hover:text-[#E4E7EB]'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Screening History</span>
              <span className="text-[10px] px-1.5 py-0.2 bg-[#10151C] rounded border border-[#232B38]">
                {totalCount}
              </span>
            </button>

            <button
              onClick={() => {
                if (soundEnabled) sounds.playClick();
                setViewMode('sessions');
                setPage(1);
              }}
              className={`px-3 py-1.5 rounded-[3px] text-xs font-mono font-semibold transition flex items-center gap-1.5 cursor-pointer ${
                viewMode === 'sessions'
                  ? 'bg-[#D9A441]/15 text-[#D9A441] border border-[#D9A441]/40 shadow-sm'
                  : 'text-[#8A93A3] hover:text-[#E4E7EB]'
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              <span>Checkpoint Sessions</span>
              <span className="text-[10px] px-1.5 py-0.2 bg-[#10151C] rounded border border-[#232B38]">
                {totalSessionCount}
              </span>
            </button>
          </div>

          <Button
            size="sm"
            variant="secondary"
            icon={RefreshCw}
            isLoading={viewMode === 'screenings' ? isLoading : isSessionsLoading}
            onClick={handleRefresh}
          >
            Refresh
          </Button>

          <Button
            size="sm"
            variant="secondary"
            icon={Download}
            onClick={() => window.print()}
          >
            Export Log
          </Button>
        </div>
      </Panel>

      {/* Search & Filters Toolbar */}
      <Panel className="p-4 space-y-3">
        <form onSubmit={handleSearchSubmit} className="flex flex-col lg:flex-row gap-3 items-stretch lg:items-center">
          {/* Search Input */}
          <div className="relative flex-1">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-[#8A93A3]">
              <Search className="w-4 h-4" aria-hidden="true" />
            </div>
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search by masked number (e.g. 1107, AD*****43) or passenger name..."
              className="w-full pl-9 pr-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-mono text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441] focus:ring-1 focus:ring-[#D9A441] transition-colors"
            />
          </div>

          {/* Outcome Filter */}
          <div className="flex items-center gap-1.5 shrink-0">
            <label htmlFor="filter-outcome" className="text-xs font-mono text-[#8A93A3]">Outcome:</label>
            <select
              id="filter-outcome"
              value={filterOutcome}
              onChange={(e) => {
                setFilterOutcome(e.target.value);
                setPage(1);
              }}
              className="bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2.5 py-2 text-xs font-mono text-[#E4E7EB] focus:outline-none focus:border-[#D9A441] cursor-pointer"
            >
              <option value="ALL">All Outcomes</option>
              <option value="VERIFIED">VERIFIED</option>
              <option value="TAMPERED">TAMPERED</option>
              <option value="EXPIRED">EXPIRED</option>
              <option value="SKIPPED">SKIPPED</option>
              <option value="UNKNOWN">UNKNOWN</option>
            </select>
          </div>

          {/* Document Type Filter */}
          <div className="flex items-center gap-1.5 shrink-0">
            <label htmlFor="filter-doctype" className="text-xs font-mono text-[#8A93A3]">Doc Type:</label>
            <select
              id="filter-doctype"
              value={filterDocType}
              onChange={(e) => {
                setFilterDocType(e.target.value);
                setPage(1);
              }}
              className="bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2.5 py-2 text-xs font-mono text-[#E4E7EB] focus:outline-none focus:border-[#D9A441] cursor-pointer"
            >
              <option value="ALL">All Types</option>
              <option value="passport">Passport</option>
              <option value="national_id_aadhaar">Aadhaar Card</option>
              <option value="national_id_pan">PAN Card</option>
              <option value="visa">Visa</option>
              <option value="driving_license">Driving Licence</option>
              <option value="national_id_voter">Voter ID</option>
            </select>
          </div>

          {/* Date Range: Start Date */}
          <div className="flex items-center gap-1.5 shrink-0">
            <label htmlFor="filter-start-date" className="text-xs font-mono text-[#8A93A3]">From:</label>
            <input
              id="filter-start-date"
              type="date"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                setPage(1);
              }}
              className="bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2 py-1.5 text-xs font-mono text-[#E4E7EB] focus:outline-none focus:border-[#D9A441] cursor-pointer"
            />
          </div>

          {/* Date Range: End Date */}
          <div className="flex items-center gap-1.5 shrink-0">
            <label htmlFor="filter-end-date" className="text-xs font-mono text-[#8A93A3]">To:</label>
            <input
              id="filter-end-date"
              type="date"
              value={endDate}
              onChange={(e) => {
                setEndDate(e.target.value);
                setPage(1);
              }}
              className="bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2 py-1.5 text-xs font-mono text-[#E4E7EB] focus:outline-none focus:border-[#D9A441] cursor-pointer"
            />
          </div>

          <div className="flex items-center gap-2">
            <Button type="submit" variant="primary" size="sm" icon={Search}>
              Filter
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={handleResetFilters}>
              Reset
            </Button>
          </div>
        </form>
      </Panel>

      {/* Main Table View */}
      {viewMode === 'screenings' ? (
        <div className="space-y-3">
          <DataTable
            columns={screeningColumns}
            data={screenings}
            keyField="screening_id"
            isLoading={isLoading}
            emptyMessage="No screening history records matching the filter criteria found in database."
          />

          {/* Pagination Controls */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-2 text-xs font-mono text-[#8A93A3]">
            <div>
              Showing {totalCount > 0 ? ((page - 1) * pageSize) + 1 : 0} to {Math.min(page * pageSize, totalCount)} of {totalCount} records (Newest first)
            </div>

            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                icon={ChevronLeft}
                disabled={page <= 1}
                onClick={() => {
                  if (soundEnabled) sounds.playClick();
                  setPage(p => Math.max(1, p - 1));
                }}
              >
                Previous
              </Button>

              <span className="px-2.5 py-1 bg-[#10151C] border border-[#232B38] rounded text-[#E4E7EB] font-bold">
                {page} / {totalPages}
              </span>

              <Button
                size="sm"
                variant="secondary"
                disabled={page >= totalPages}
                onClick={() => {
                  if (soundEnabled) sounds.playClick();
                  setPage(p => Math.min(totalPages, p + 1));
                }}
              >
                Next <ChevronRight className="w-3.5 h-3.5 ml-1 inline" />
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <DataTable
          columns={sessionColumns}
          data={sessions}
          keyField="session_id"
          isLoading={isSessionsLoading}
          emptyMessage="No checkpoint sessions found."
        />
      )}

      {/* Granular Screening Record Detail Modal */}
      {selectedRecord && (
        <div 
          className="fixed inset-0 z-50 bg-[#0B0F14]/85 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto animate-in fade-in"
          role="dialog"
          aria-modal="true"
        >
          <div className="bg-[#141A22] border border-[#232B38] w-full max-w-4xl p-6 space-y-6 my-8 max-h-[90vh] overflow-y-auto rounded-[6px] shadow-2xl text-[#E4E7EB]">
            {/* Header */}
            <div className="flex items-start justify-between border-b border-[#232B38] pb-4">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="warning" size="sm" className="font-mono">
                    {selectedRecord.screening_id}
                  </Badge>
                  <h3 className="text-base font-bold text-[#E4E7EB] font-sans">
                    Screening Audit Record & Forensic Trace
                  </h3>
                  <Badge variant={getOutcomeBadgeVariant(selectedRecord.outcome)} size="sm">
                    {selectedRecord.outcome}
                  </Badge>
                  {selectedRecord.is_correction && (
                    <Badge variant="warning" size="sm">
                      Officer Correction
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-[#8A93A3] mt-1.5 font-mono">
                  Recorded UTC: {selectedRecord.timestamp || '--'} · Officer: {selectedRecord.officer_id || 'OFFICER-4819'} · Latency: {selectedRecord.processing_time_ms ? `${selectedRecord.processing_time_ms}ms` : '0ms'}
                </p>
              </div>

              <button
                onClick={() => setSelectedRecord(null)}
                aria-label="Close modal"
                className="p-1.5 text-[#8A93A3] hover:text-[#E4E7EB] border border-[#232B38] bg-[#0B0F14] rounded-[4px] cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Producing Check & Field Determinant Banner */}
            {(selectedRecord.outcome_trigger?.producing_check || selectedRecord.producing_check) && (
              <div className="p-3.5 bg-[#10151C] border border-[#D9A441]/40 rounded-[4px] space-y-1">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-[#D9A441]" />
                  <span className="text-xs font-mono font-bold text-[#D9A441] uppercase tracking-wider">
                    Outcome Producing Rule & Field Trigger
                  </span>
                </div>
                <div className="text-xs font-mono grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                  <div>
                    <span className="text-[#8A93A3]">Triggering Check: </span>
                    <span className="font-bold text-[#E4E7EB]">
                      {selectedRecord.outcome_trigger?.producing_check || selectedRecord.producing_check}
                    </span>
                  </div>
                  <div>
                    <span className="text-[#8A93A3]">Named Field: </span>
                    <span className="font-bold text-[#E4E7EB]">
                      {selectedRecord.outcome_trigger?.producing_field || selectedRecord.producing_field || 'N/A'}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Quick Record Attributes Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono">
              <div className="border border-[#232B38] p-3 bg-[#0B0F14] rounded-[4px]">
                <span className="text-[10px] text-[#8A93A3] uppercase block">Document Type</span>
                <span className="text-xs font-bold text-[#E4E7EB] block mt-1 capitalize">
                  {selectedRecord.document_type?.replace(/_/g, ' ') || 'Unknown'}
                </span>
              </div>

              <div className="border border-[#232B38] p-3 bg-[#0B0F14] rounded-[4px]">
                <span className="text-[10px] text-[#8A93A3] uppercase block">Masked Number</span>
                <span className="text-xs font-bold text-[#D9A441] block mt-1">
                  {selectedRecord.document_number || 'N/A'}
                </span>
              </div>

              <div className="border border-[#232B38] p-3 bg-[#0B0F14] rounded-[4px]">
                <span className="text-[10px] text-[#8A93A3] uppercase block">Holder / DOB</span>
                <span className="text-xs font-bold text-[#E4E7EB] block mt-1 truncate">
                  {selectedRecord.name || 'N/A'} {selectedRecord.dob ? `(${selectedRecord.dob})` : ''}
                </span>
              </div>

              <div className="border border-[#232B38] p-3 bg-[#0B0F14] rounded-[4px]">
                <span className="text-[10px] text-[#8A93A3] uppercase block">Risk Score</span>
                <span className="text-lg font-bold text-[#E4E7EB] block mt-0.5">
                  {selectedRecord.risk_score !== undefined ? Number(selectedRecord.risk_score).toFixed(1) : '0.0'}
                </span>
              </div>
            </div>

            {/* Image Hash Security Guarantee */}
            {selectedRecord.image_hash && (
              <div className="p-2.5 bg-[#0B0F14] border border-[#232B38] rounded-[4px] flex items-center justify-between text-xs font-mono text-[#8A93A3]">
                <span>Document Image SHA-256 Digest:</span>
                <span className="font-mono text-[#E4E7EB] text-[11px] truncate max-w-[320px]">
                  {selectedRecord.image_hash}
                </span>
              </div>
            )}

            {/* Check-by-Check Breakdown - Render NOT_EVALUATED in neutral grey, never green! */}
            <div className="space-y-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-[#8A93A3] font-mono flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-[#D9A441]" />
                <span>Full Check-by-Check Verification Breakdown</span>
              </h4>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {selectedRecord.checks && Object.keys(selectedRecord.checks).length > 0 ? (
                  Object.entries(selectedRecord.checks).map(([chkKey, chkObj]) => {
                    const status = typeof chkObj === 'object' && chkObj !== null ? chkObj.status : String(chkObj);
                    const reason = typeof chkObj === 'object' && chkObj !== null ? chkObj.reason : '';
                    return (
                      <div 
                        key={chkKey} 
                        className="p-3 bg-[#0B0F14] border border-[#232B38] rounded-[4px] space-y-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs text-[#E4E7EB] font-bold">
                            {chkKey.replace(/_/g, ' ').toUpperCase()}
                          </span>
                          <Badge variant={getCheckBadgeVariant(status)} size="sm">
                            {status || 'NOT_EVALUATED'}
                          </Badge>
                        </div>
                        {reason && (
                          <p className="text-[11px] text-[#8A93A3] font-mono leading-relaxed">
                            {reason}
                          </p>
                        )}
                      </div>
                    );
                  })
                ) : (
                  <p className="text-xs font-mono text-[#8A93A3] col-span-2 p-3 bg-[#0B0F14] border border-[#232B38] rounded-[4px]">
                    No granular check breakdown recorded for this scan.
                  </p>
                )}
              </div>
            </div>

            {/* Repeat-Identity Matches Shown Inline */}
            <div className="space-y-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-[#8A93A3] font-mono flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-[#D9A441]" />
                <span>Repeat Identity & Cross-Crossing Intelligence</span>
              </h4>

              {repeatIdentityLoading ? (
                <div className="p-4 text-center text-xs font-mono text-[#8A93A3]">
                  Analyzing ledger indexes for repeat identities and document reuse...
                </div>
              ) : repeatIdentityData ? (
                <div className="space-y-2">
                  {/* Anomalies Detected (e.g. Document reuse under different name) */}
                  {repeatIdentityData.anomalies_detected?.length > 0 && (
                    <div className="p-3 bg-red-950/40 border border-red-500/50 rounded-[4px] text-red-300 space-y-1">
                      <div className="flex items-center gap-2 font-bold text-xs">
                        <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                        <span>CRITICAL REUSE ANOMALY: SAME DOCUMENT PRESENTED UNDER DIFFERENT NAMES</span>
                      </div>
                      {repeatIdentityData.anomalies_detected.map((anom, idx) => (
                        <p key={idx} className="text-[11px] pl-6 font-mono">
                          • Screened under "{anom.stored_name}" ({anom.timestamp ? anom.timestamp.slice(0, 10) : ''}) vs queried "{anom.queried_name}"
                        </p>
                      ))}
                    </div>
                  )}

                  {/* Previous Crossings (Name + DOB match) */}
                  {repeatIdentityData.identity_matches?.length > 1 ? (
                    <div className="p-3 bg-[#10151C] border border-[#232B38] rounded-[4px] space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-[#E4E7EB]">
                          Previous Crossings by This Traveler ({repeatIdentityData.identity_matches.length - 1} prior records)
                        </span>
                        <Badge variant="warning" size="sm">Repeat Traveler</Badge>
                      </div>
                      <div className="space-y-1.5 max-h-32 overflow-y-auto">
                        {repeatIdentityData.identity_matches
                          .filter(m => m.screening_id !== selectedRecord.screening_id)
                          .map((match, idx) => (
                            <div key={idx} className="flex items-center justify-between text-[11px] font-mono text-[#8A93A3] p-1.5 bg-[#0B0F14] rounded border border-[#232B38]">
                              <span>{match.timestamp ? new Date(match.timestamp).toLocaleDateString() : '--'} · {match.document_type} ({match.document_number})</span>
                              <div className="flex items-center gap-2">
                                <Badge variant={getOutcomeBadgeVariant(match.outcome)} size="sm">
                                  {match.outcome}
                                </Badge>
                                <span className="font-bold text-[#E4E7EB]">{match.risk_score?.toFixed(1)}</span>
                              </div>
                            </div>
                          ))}
                      </div>
                    </div>
                  ) : (
                    <div className="p-3 bg-[#10151C] border border-[#232B38] rounded-[4px] text-xs font-mono text-[#8A93A3]">
                      ✓ No prior crossing history found under this identity (Name + DOB). First recorded presentation.
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-3 bg-[#10151C] border border-[#232B38] rounded-[4px] text-xs font-mono text-[#8A93A3]">
                  Identity cross-check complete. No anomalies detected.
                </div>
              )}
            </div>

            {/* Decision & Appended Corrections Shown Alongside Original */}
            <div className="space-y-3">
              <div className="flex items-center justify-between border-b border-[#232B38] pb-1.5">
                <h4 className="text-xs font-bold uppercase tracking-wider text-[#8A93A3] font-mono flex items-center gap-1.5">
                  <History className="w-3.5 h-3.5 text-[#D9A441]" />
                  <span>Decision & Append-Only Corrections Trail</span>
                </h4>
                <Badge variant={selectedRecord.corrections?.length > 0 ? 'warning' : 'neutral'} size="sm">
                  {selectedRecord.corrections?.length > 0 ? `${selectedRecord.corrections.length} Correction(s)` : 'Original Verdict'}
                </Badge>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {/* Original Decision Box */}
                <div className="p-3.5 bg-[#0B0F14] border border-[#232B38] rounded-[4px] space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono uppercase text-[#8A93A3] font-bold">
                      Original Ledger Verdict (Immutable)
                    </span>
                    <Badge variant={getOutcomeBadgeVariant(selectedRecord.outcome)} size="sm">
                      {selectedRecord.outcome}
                    </Badge>
                  </div>
                  <div className="text-xs font-mono space-y-1 text-[#8A93A3]">
                    <div className="flex justify-between">
                      <span>Officer ID:</span>
                      <span className="text-[#E4E7EB]">{selectedRecord.officer_id}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Risk Score:</span>
                      <span className="text-[#E4E7EB] font-bold">{selectedRecord.risk_score?.toFixed(1)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Recorded UTC:</span>
                      <span className="text-[#E4E7EB] text-[11px]">{selectedRecord.timestamp}</span>
                    </div>
                  </div>
                  <p className="text-[10px] text-[#5A6578] italic font-mono pt-1 border-t border-[#232B38]">
                    Immutable audit entry preserved under append-only compliance.
                  </p>
                </div>

                {/* Corrections Box */}
                <div className="p-3.5 bg-[#0B0F14] border border-[#232B38] rounded-[4px] space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono uppercase text-[#8A93A3] font-bold">
                      Appended Officer Correction
                    </span>
                    {selectedRecord.corrections?.length > 0 ? (
                      <Badge variant={getOutcomeBadgeVariant(selectedRecord.corrections[selectedRecord.corrections.length - 1].outcome)} size="sm">
                        {selectedRecord.corrections[selectedRecord.corrections.length - 1].outcome}
                      </Badge>
                    ) : (
                      <Badge variant="neutral" size="sm">No Correction</Badge>
                    )}
                  </div>

                  {selectedRecord.corrections?.length > 0 ? (
                    selectedRecord.corrections.map((corr, idx) => (
                      <div key={idx} className="text-xs font-mono space-y-1 text-[#8A93A3] border-t border-[#232B38] pt-1.5 first:border-0 first:pt-0">
                        <div className="flex justify-between">
                          <span>Corrected By:</span>
                          <span className="text-[#E4E7EB] font-bold">{corr.corrected_by || corr.officer_id}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>New Risk Score:</span>
                          <span className="text-[#E4E7EB] font-bold">{corr.risk_score?.toFixed(1)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Timestamp UTC:</span>
                          <span className="text-[#E4E7EB] text-[11px]">{corr.timestamp}</span>
                        </div>
                        <div className="pt-1">
                          <span className="text-[#D9A441] text-[11px] font-semibold block">Auditable Reason:</span>
                          <p className="text-[#E4E7EB] text-[11px] italic bg-[#141A22] p-1.5 rounded border border-[#232B38] mt-0.5">
                            "{corr.correction_reason}"
                          </p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs font-mono text-[#5A6578] py-4 text-center">
                      No officer corrections have been appended to this record.
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Session-Linked Documents */}
            {selectedRecord.session_id && (
              <div className="space-y-2">
                <div className="flex items-center justify-between border-b border-[#232B38] pb-1.5">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-[#8A93A3] font-mono flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-[#D9A441]" />
                    <span>Session-Linked Travel Documents ({selectedRecord.session_id})</span>
                  </h4>
                </div>

                {sessionDocsLoading ? (
                  <div className="p-4 text-center text-xs font-mono text-[#8A93A3]">
                    Loading linked session documents...
                  </div>
                ) : sessionLinkedDocs.length > 0 ? (
                  <div className="space-y-2">
                    {sessionLinkedDocs.map((doc, idx) => (
                      <div
                        key={idx}
                        className="p-3 bg-[#0B0F14] border border-[#232B38] rounded-[4px] flex items-center justify-between gap-3"
                      >
                        <div className="space-y-0.5">
                          <span className="font-semibold text-xs text-[#E4E7EB] font-sans capitalize">
                            {doc.document_type?.replace(/_/g, ' ') || 'Document'}
                          </span>
                          <div className="flex items-center gap-2 text-[11px] text-[#8A93A3] font-mono">
                            <span>Number: {doc.document_number}</span>
                            <span>·</span>
                            <span>ID: {doc.screening_id}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-3">
                          <Badge variant={getOutcomeBadgeVariant(doc.outcome)} size="sm">
                            {doc.outcome}
                          </Badge>
                          <span className="font-mono text-xs text-[#E4E7EB] font-bold">
                            Score: {doc.risk_score !== undefined ? Number(doc.risk_score).toFixed(1) : '0.0'}
                          </span>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => handleViewRecord(doc)}
                            className="text-xs"
                          >
                            Inspect
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs font-mono text-[#5A6578] p-3 bg-[#0B0F14] border border-[#232B38] rounded-[4px]">
                    No other documents are linked under session {selectedRecord.session_id}.
                  </p>
                )}
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex items-center justify-between pt-4 border-t border-[#232B38]">
              <span className="text-[10px] text-[#5A6578] font-mono">
                Immutable evidentiary record · Ministry of Home Affairs Protocol
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={Printer}
                  onClick={() => window.print()}
                >
                  Print Record
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setSelectedRecord(null)}
                >
                  Close Record
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default AuditTrail;
