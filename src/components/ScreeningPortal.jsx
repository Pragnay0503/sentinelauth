import React, { useState, useEffect, useRef } from 'react';
import { 
  FileText, 
  Scan, 
  Cpu, 
  Upload, 
  RefreshCw, 
  Eye, 
  CheckCircle2, 
  AlertCircle,
  FileCheck,
  Tag,
  Search,
  Check,
  Sliders,
  AlertTriangle,
  Info,
  ShieldCheck,
  Camera,
  Layers,
  Save,
  ShieldAlert,
  ArrowRight,
  Trash2,
  Image as ImageIcon,
  UserCheck,
  Printer,
  X,
  Sparkles,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  Plus,
  Users,
  CheckCircle,
  MapPin
} from 'lucide-react';
import { ForensicInspector } from './ForensicInspector';
import { LiveFaceScanner } from './LiveFaceScanner';
import { ReportModal } from './ReportModal';
import { QREvidencePanel } from './QREvidencePanel';
import { CHECKPOINT_LOCATIONS } from '../data/locations';
import { sounds } from '../utils/audio';
import { Button, Badge, ConfidenceBadge, Panel, Tabs, ConfidenceBar, RiskGauge, FileDropzone, StatusDot, Toast } from './ui';

const DOCUMENT_TYPES = [
  { id: 'auto', label: '⚡ Auto-Detect Document (Recommended)' },
  { id: 'passport', label: 'Passport (ICAO TD3 / TD1)' },
  { id: 'national_id_aadhaar', label: 'Aadhaar Card (India)' },
  { id: 'national_id_pan', label: 'PAN Card (India)' },
  { id: 'national_id_voter', label: 'Voter ID / EPIC (India)' },
  { id: 'driving_license', label: 'Driving License' },
  { id: 'visa', label: 'Visa (Sticker / Foil)' },
  { id: 'permit', label: 'Residence / Border Permit' },
];

function formatDocTypeBadge(type) {
  if (!type) return '';
  const s = String(type).toLowerCase();
  if (s.includes('passport')) return 'Passport';
  if (s.includes('aadhaar')) return 'Aadhaar';
  if (s.includes('pan')) return 'PAN';
  if (s.includes('driving') || s.includes('dl') || s.includes('license') || s.includes('licence')) return 'Driving Licence';
  if (s.includes('voter')) return 'Voter ID';
  if (s.includes('visa')) return 'Visa';
  return String(type).replace(/_/g, ' ');
}

/**
 * Click-to-expand panel for flags and check results (PART 3):
 * Shows:
 *  1. printed visual value
 *  2. MRZ / QR value compared against
 *  3. which rule fired
 *  4. threshold involved
 * Uses only data already present in the check results.
 */
function WhyExpander({ printedValue, comparedValue, ruleFired, threshold, label = "Why?", defaultOpen = false }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="mt-1 font-mono text-[10px]">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setIsOpen(!isOpen);
        }}
        className="inline-flex items-center gap-1 text-[10px] font-semibold text-blue-400 hover:text-blue-300 underline cursor-pointer select-none"
      >
        <span>{isOpen ? '▾ Hide Audit Evidence' : `▸ ${label}`}</span>
      </button>
      {isOpen && (
        <div className="mt-1.5 p-2 rounded bg-[#0B0F14] border border-[#232B38] space-y-1 text-slate-300">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 text-[10px]">
            <div>
              <span className="text-[#8A93A3]">Printed visual: </span>
              <span className="text-slate-200 font-bold">{printedValue || '—'}</span>
            </div>
            <div>
              <span className="text-[#8A93A3]">MRZ / QR compared: </span>
              <span className="text-slate-200 font-bold">{comparedValue || '—'}</span>
            </div>
          </div>
          <div className="text-[10px]">
            <span className="text-[#8A93A3]">Rule fired: </span>
            <span className="text-blue-300 font-semibold">{ruleFired || 'Standard Compliance Rule'}</span>
          </div>
          {threshold && (
            <div className="text-[10px]">
              <span className="text-[#8A93A3]">Threshold / Standard: </span>
              <span className="text-slate-300">{threshold}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ScreeningPortal({ soundEnabled, activeLocation, currentOfficer = null, onSessionStatusChange = null }) {
  const currentLocationName = CHECKPOINT_LOCATIONS.find(l => l.id === activeLocation)?.name 
    || "Hyderabad RGIA (T1 Int'l Arrival)";

  // Document Ingestion States (No predefined data)
  const [docType, setDocType] = useState('auto');
  const [imagePreview, setImagePreview] = useState(null);
  const [frontFileObj, setFrontFileObj] = useState(null);
  const [frontFileName, setFrontFileName] = useState('');
  
  const [backImagePreview, setBackImagePreview] = useState(null);
  const [backFileObj, setBackFileObj] = useState(null);
  const [backFileName, setBackFileName] = useState('');

  const [selfiePreview, setSelfiePreview] = useState(null);
  const [selfieFileObj, setSelfieFileObj] = useState(null);
  const [selfieFileName, setSelfieFileName] = useState('');

  // Drag-and-drop highlight states
  const [isFrontDragging, setIsFrontDragging] = useState(false);
  const [isBackDragging, setIsBackDragging] = useState(false);
  const [isSelfieDragging, setIsSelfieDragging] = useState(false);

  // Workflow & Processing states
  const [activeWorkspaceTab, setActiveWorkspaceTab] = useState('overview'); // 'overview', 'forensics', 'biometrics'
  const [isProcessing, setIsProcessing] = useState(false);
  const [scanProgress, setScanProgress] = useState(0);
  const [scanStage, setScanStage] = useState('');
  const [errorMsg, setErrorMsg] = useState(null);
  
  // Full Scan Result state
  const [scanResult, setScanResult] = useState(null);
  const [measuredProcessingTimeMs, setMeasuredProcessingTimeMs] = useState(null);
  const [editableFields, setEditableFields] = useState({});
  const [officerDecision, setOfficerDecision] = useState(null); // 'APPROVED', 'FLAGGED', 'DETAINED'
  const [showCertificateModal, setShowCertificateModal] = useState(false);
  const [showPriorRecordModal, setShowPriorRecordModal] = useState(false);
  const [showUnsavedConfirmModal, setShowUnsavedConfirmModal] = useState(false);

  // Model Readiness State (Polled from FastAPI /api/health)
  const [backendStatus, setBackendStatus] = useState({ ready: true, status: 'ready' });

  // Multi-Document Checkpoint Session State (Part A)
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [sessionDocuments, setSessionDocuments] = useState([
    { id: 1, label: 'Document 1', type: 'auto', detectedType: null, status: 'pending', frontFile: null, frontPreview: null, backFile: null, backPreview: null, selfieFile: null, selfiePreview: null, scanResult: null },
    { id: 2, label: 'Document 2', type: 'auto', detectedType: null, status: 'pending', frontFile: null, frontPreview: null, backFile: null, backPreview: null, selfieFile: null, selfiePreview: null, scanResult: null },
    { id: 3, label: 'Document 3', type: 'auto', detectedType: null, status: 'pending', frontFile: null, frontPreview: null, backFile: null, backPreview: null, selfieFile: null, selfiePreview: null, scanResult: null },
  ]);
  const [activeSessionSlotIdx, setActiveSessionSlotIdx] = useState(0);
  const [sessionReport, setSessionReport] = useState(null);
  const [isGeneratingSessionReport, setIsGeneratingSessionReport] = useState(false);
  const [sessionErrorMsg, setSessionErrorMsg] = useState(null);
  const [expandedDocIdx, setExpandedDocIdx] = useState(null);

  // Synchronize active session lifecycle telemetry with Header
  useEffect(() => {
    if (!onSessionStatusChange) return;
    const completedDocs = sessionDocuments.filter(d => d.status === 'completed').length;
    let state = 'new';
    if (sessionReport) {
      state = 'complete';
    } else if (completedDocs > 0) {
      state = 'active';
    }
    onSessionStatusChange({
      state,
      documentCount: completedDocs,
      sessionId: currentSessionId,
    });
  }, [currentSessionId, sessionDocuments, sessionReport, onSessionStatusChange]);

  useEffect(() => {
    const initSession = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({
            officer_id: currentOfficer?.badgeId || 'OFFICER-4819',
            station_id: currentLocationName,
            documents_required: '1'
          })
        });
        if (res.ok) {
          const data = await res.json();
          setCurrentSessionId(data.session_id);
        }
      } catch (err) {
        console.warn("Could not auto-create session:", err);
      }
    };
    initSession();
  }, [currentLocationName, currentOfficer]);

  // Camera capture modal state for inline selfie capture
  const [isInlineCameraOpen, setIsInlineCameraOpen] = useState(false);
  const videoRef = useRef(null);
  const streamRef = useRef(null);

  // Document Camera Capture State (High-Resolution & Live Quality Analysis)
  const [isDocCameraOpen, setIsDocCameraOpen] = useState(false);
  const [docCameraTarget, setDocCameraTarget] = useState('front'); // 'front' | 'back'
  const [docQuality, setDocQuality] = useState({
    status: 'RED', // 'GREEN' | 'AMBER' | 'RED'
    label: 'Initializing camera...',
    sharpness: 0,
    brightness: 0,
    hint: '',
    rejectReason: null
  });
  const [docSensorRes, setDocSensorRes] = useState('');
  const [docCaptureError, setDocCaptureError] = useState(null);

  const docVideoRef = useRef(null);
  const docStreamRef = useRef(null);
  const docQualityIntervalRef = useRef(null);
  const offscreenCanvasRef = useRef(null);

  useEffect(() => {
    const checkBackend = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/health');
        if (res.ok) {
          const info = await res.json();
          setBackendStatus({ ready: true, status: info.model_status || 'ready' });
        }
      } catch (e) {
        setBackendStatus({ ready: false, status: 'offline' });
      }
    };
    checkBackend();
  }, []);

  // Cleanup camera streams and quality analyzer on unmount
  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(t => t.stop());
      }
      if (docStreamRef.current) {
        docStreamRef.current.getTracks().forEach(t => t.stop());
      }
      if (docQualityIntervalRef.current) {
        clearInterval(docQualityIntervalRef.current);
      }
    };
  }, []);

  // -------------------------------------------------------------------------
  // Ingestion Handlers
  // -------------------------------------------------------------------------

  const handleReset = () => {
    if (soundEnabled) sounds.playClick();
    setImagePreview(null);
    setFrontFileObj(null);
    setFrontFileName('');
    setBackImagePreview(null);
    setBackFileObj(null);
    setBackFileName('');
    setSelfiePreview(null);
    setSelfieFileObj(null);
    setSelfieFileName('');
    setScanResult(null);
    setMeasuredProcessingTimeMs(null);
    setEditableFields({});
    setErrorMsg(null);
    setScanProgress(0);
    setScanStage('');
    setOfficerDecision(null);
    setDocType('auto');
    setActiveWorkspaceTab('overview');
  };

  const clearTravellerSessionMemory = () => {
    handleReset();
    setSessionReport(null);
    setSessionErrorMsg(null);
    setExpandedDocIdx(null);
    setActiveSessionSlotIdx(0);
    setSessionDocuments([
      { id: 1, label: 'Document 1', type: 'auto', detectedType: null, status: 'pending', frontFile: null, frontPreview: null, backFile: null, backPreview: null, selfieFile: null, selfiePreview: null, scanResult: null },
      { id: 2, label: 'Document 2', type: 'auto', detectedType: null, status: 'pending', frontFile: null, frontPreview: null, backFile: null, backPreview: null, selfieFile: null, selfiePreview: null, scanResult: null },
      { id: 3, label: 'Document 3', type: 'auto', detectedType: null, status: 'pending', frontFile: null, frontPreview: null, backFile: null, backPreview: null, selfieFile: null, selfiePreview: null, scanResult: null },
    ]);
  };

  const executeResetAndCreateFreshSession = async () => {
    clearTravellerSessionMemory();
    try {
      const res = await fetch('http://localhost:8000/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          officer_id: currentOfficer?.badgeId || 'OFFICER-4819',
          station_id: currentLocationName,
          documents_required: '1'
        })
      });
      if (res.ok) {
        const data = await res.json();
        setCurrentSessionId(data.session_id);
        if (soundEnabled) sounds.playSuccess();
      }
    } catch (e) {
      console.error("Session creation error:", e);
      setSessionErrorMsg("Could not connect to session service: " + e.message);
    }
  };

  const handleStartNewSession = async () => {
    if (soundEnabled) sounds.playClick();
    const completedDocs = sessionDocuments.filter(d => d.status === 'completed').length;

    // Confirmation before clearing: if documents uploaded but no report generated
    if (completedDocs > 0 && !sessionReport) {
      setShowUnsavedConfirmModal(true);
      return;
    }

    // Archive completed session with report to audit log
    if (currentSessionId && sessionReport) {
      try {
        await fetch(`http://localhost:8000/api/session/${currentSessionId}/complete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            decision: officerDecision || sessionReport.session_action || 'CLEARED',
            officer_id: currentOfficer?.badgeId || 'OFFICER-4819',
            checkpoint: currentLocationName,
            status: 'COMPLETE',
            risk_score: sessionReport.session_risk_score,
            risk_tier: sessionReport.session_risk_tier,
            findings: sessionReport.summary || 'Screening report generated and archived.'
          })
        });
      } catch (err) {
        console.warn("Failed to archive session to audit log:", err);
      }
    }

    await executeResetAndCreateFreshSession();
  };

  const handleConfirmDiscard = async () => {
    setShowUnsavedConfirmModal(false);
    if (soundEnabled) sounds.playAlert();

    // Record discarded session to audit log for compliance
    if (currentSessionId) {
      try {
        await fetch(`http://localhost:8000/api/session/${currentSessionId}/complete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            decision: 'DISCARDED',
            officer_id: currentOfficer?.badgeId || 'OFFICER-4819',
            checkpoint: currentLocationName,
            status: 'DISCARDED',
            findings: 'Session discarded by officer with unsaved screening data.'
          })
        });
      } catch (err) {
        console.warn("Failed to record discarded session:", err);
      }
    }

    await executeResetAndCreateFreshSession();
  };

  const handleAddDocumentSlot = () => {
    const nextNum = sessionDocuments.length + 1;
    const newDoc = {
      id: nextNum,
      label: `Document ${nextNum}`,
      type: 'auto',
      detectedType: null,
      status: 'pending',
      frontFile: null,
      frontPreview: null,
      backFile: null,
      backPreview: null,
      selfieFile: null,
      selfiePreview: null,
      scanResult: null
    };
    setSessionDocuments(prev => [...prev, newDoc]);
    setActiveSessionSlotIdx(sessionDocuments.length);
    if (soundEnabled) sounds.playClick();
  };

  const handleSelectSlot = (idx) => {
    setActiveSessionSlotIdx(idx);
    const slot = sessionDocuments[idx];
    if (slot) {
      setImagePreview(slot.frontPreview || null);
      setFrontFileObj(slot.frontFile || null);
      setFrontFileName(slot.frontFile ? slot.frontFile.name : '');
      setBackImagePreview(slot.backPreview || null);
      setBackFileObj(slot.backFile || null);
      setBackFileName(slot.backFile ? slot.backFile.name : '');
      setSelfiePreview(slot.selfiePreview || null);
      setSelfieFileObj(slot.selfieFile || null);
      setSelfieFileName(slot.selfieFile ? slot.selfieFile.name : '');
      setDocType(slot.type || 'auto');
      if (slot.scanResult) {
        setScanResult(slot.scanResult);
      }
    }
    if (soundEnabled) sounds.playClick();
  };

  const handleGenerateSessionReport = async () => {
    const uploadedCount = sessionDocuments.filter(d => d.status === 'completed').length;
    if (uploadedCount < 1) {
      setSessionErrorMsg("Cannot generate report: No documents screened yet. Border control protocol requires at least 1 document.");
      if (soundEnabled) sounds.playAlert();
      return;
    }
    setIsGeneratingSessionReport(true);
    setSessionErrorMsg(null);
    try {
      const res = await fetch(`http://localhost:8000/api/session/${currentSessionId}/report`);
      if (!res.ok) {
        const err = await res.json();
        const msg = (typeof err.detail === 'object' && err.detail !== null)
          ? (err.detail.message || `${err.detail.error || 'Error'}: ${err.detail.detail || ''} (${err.detail.type || ''})`)
          : (err.detail || err.message || "Failed to generate cross-document report.");
        setSessionErrorMsg(msg);
        if (soundEnabled) sounds.playAlert();
        return;
      }
      const data = await res.json();
      // Explicit session scoping assertion: verify report belongs exclusively to current session
      if (data.session_id !== currentSessionId) {
        throw new Error(`Session security mismatch: generated report belongs to '${data.session_id}' rather than active session '${currentSessionId}'.`);
      }
      setSessionReport(data);
      if (soundEnabled) {
        if (data.cross_document_validation?.has_cross_document_mismatch) sounds.playAlert();
        else sounds.playSuccess();
      }
    } catch (e) {
      setSessionErrorMsg(e.message || "Failed to contact session report service.");
      if (soundEnabled) sounds.playAlert();
    } finally {
      setIsGeneratingSessionReport(false);
    }
  };

  const processFrontFile = (file) => {
    if (!file || !file.type.startsWith('image/')) {
      setErrorMsg("Please upload a valid image file (PNG, JPG, JPEG, WEBP).");
      return;
    }
    setFrontFileObj(file);
    setFrontFileName(file.name);
    setImagePreview(URL.createObjectURL(file));
    setScanResult(null);
    setErrorMsg(null);
    if (soundEnabled) sounds.playClick();
  };

  const processBackFile = (file) => {
    if (!file || !file.type.startsWith('image/')) {
      setErrorMsg("Please upload a valid image file for the reverse side.");
      return;
    }
    setBackFileObj(file);
    setBackFileName(file.name);
    setBackImagePreview(URL.createObjectURL(file));
    if (soundEnabled) sounds.playClick();
  };

  const processSelfieFile = (file) => {
    if (!file || !file.type.startsWith('image/')) {
      setErrorMsg("Please upload a valid photo file for the face portrait.");
      return;
    }
    setSelfieFileObj(file);
    setSelfieFileName(file.name);
    setSelfiePreview(URL.createObjectURL(file));
    if (soundEnabled) sounds.playClick();
  };

  // Drag & drop handlers
  const handleFrontDrop = (e) => {
    e.preventDefault();
    setIsFrontDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFrontFile(e.dataTransfer.files[0]);
    }
  };

  const handleBackDrop = (e) => {
    e.preventDefault();
    setIsBackDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processBackFile(e.dataTransfer.files[0]);
    }
  };

  const handleSelfieDrop = (e) => {
    e.preventDefault();
    setIsSelfieDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processSelfieFile(e.dataTransfer.files[0]);
    }
  };

  // Bind stream whenever isInlineCameraOpen changes and video mounts
  useEffect(() => {
    if (isInlineCameraOpen && streamRef.current && videoRef.current) {
      if (videoRef.current.srcObject !== streamRef.current) {
        videoRef.current.srcObject = streamRef.current;
      }
      videoRef.current.play().catch(err => console.warn("Inline video play warning:", err));
    }
  }, [isInlineCameraOpen]);

  // Bind high-resolution stream whenever isDocCameraOpen changes and doc video mounts
  useEffect(() => {
    if (isDocCameraOpen && docStreamRef.current && docVideoRef.current) {
      if (docVideoRef.current.srcObject !== docStreamRef.current) {
        docVideoRef.current.srcObject = docStreamRef.current;
      }
      docVideoRef.current.play().catch(err => console.warn("Doc video play warning:", err));
    }
  }, [isDocCameraOpen]);

  // Document Camera Live Quality Analysis (Throttled ~5fps on lightweight offscreen canvas)
  const analyzeDocFrameQuality = () => {
    const video = docVideoRef.current;
    if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
      return;
    }

    if (!offscreenCanvasRef.current) {
      offscreenCanvasRef.current = document.createElement('canvas');
    }
    const canvas = offscreenCanvasRef.current;
    const w = 320;
    const h = 200;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, w, h);
    const imgData = ctx.getImageData(0, 0, w, h);
    const data = imgData.data;

    // 1. Grayscale & Mean Luminance
    const gray = new Float32Array(w * h);
    let totalLum = 0;
    for (let i = 0, j = 0; i < data.length; i += 4, j++) {
      const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
      gray[j] = lum;
      totalLum += lum;
    }
    const meanLum = totalLum / (w * h);

    // 2. Guide Frame Region (Centered ~70% width, ~60% height)
    const gx1 = Math.floor(w * 0.15);
    const gx2 = Math.floor(w * 0.85);
    const gy1 = Math.floor(h * 0.20);
    const gy2 = Math.floor(h * 0.80);

    // 3. Discrete 3x3 Laplacian: [0, 1, 0; 1, -4, 1; 0, 1, 0]
    let lapSum = 0;
    let lapSqSum = 0;
    let count = 0;

    // Core region (center 40%) vs margin region (outer ring of guide)
    const coreX1 = Math.floor(w * 0.35);
    const coreX2 = Math.floor(w * 0.65);
    const coreY1 = Math.floor(h * 0.35);
    const coreY2 = Math.floor(h * 0.65);

    let coreEnergy = 0;
    let coreCount = 0;
    let marginEnergy = 0;
    let marginCount = 0;

    for (let y = gy1 + 1; y < gy2 - 1; y++) {
      const rowOffset = y * w;
      const rowAbove = (y - 1) * w;
      const rowBelow = (y + 1) * w;

      for (let x = gx1 + 1; x < gx2 - 1; x++) {
        const val = 
          gray[rowAbove + x] +
          gray[rowBelow + x] +
          gray[rowOffset + x - 1] +
          gray[rowOffset + x + 1] -
          4 * gray[rowOffset + x];

        lapSum += val;
        lapSqSum += val * val;
        count++;

        const absVal = Math.abs(val);
        if (x >= coreX1 && x <= coreX2 && y >= coreY1 && y <= coreY2) {
          coreEnergy += absVal;
          coreCount++;
        } else {
          marginEnergy += absVal;
          marginCount++;
        }
      }
    }

    const meanLap = count > 0 ? lapSum / count : 0;
    const variance = count > 0 ? Math.max(0, (lapSqSum / count) - (meanLap * meanLap)) : 0;

    const avgCoreEnergy = coreCount > 0 ? coreEnergy / coreCount : 0;
    const avgMarginEnergy = marginCount > 0 ? marginEnergy / marginCount : 0;
    const needsMoveCloser = avgCoreEnergy > 16 && avgMarginEnergy < 0.22 * avgCoreEnergy;

    // Update sensor resolution label if available
    if (video.videoWidth && video.videoHeight) {
      setDocSensorRes(`${video.videoWidth}×${video.videoHeight}`);
    }

    // Determine Status & Quality Feedback
    let status = 'GREEN';
    let label = 'Ready for capture';
    let hint = '';
    let rejectReason = null;

    if (meanLum < 55) {
      status = 'RED';
      label = 'Too dark — increase lighting';
      rejectReason = `Document too dark (brightness ${Math.round(meanLum)} < 55)`;
    } else if (meanLum > 225) {
      status = 'RED';
      label = 'Too bright / glare detected';
      rejectReason = `Excessive glare (brightness ${Math.round(meanLum)} > 225)`;
    } else if (variance < 50) {
      status = 'RED';
      label = 'Too blurry / hold steady';
      rejectReason = `Image too blurry (sharpness score ${Math.round(variance)} < 50)`;
    } else if (needsMoveCloser) {
      status = 'AMBER';
      label = 'Hold steady';
      hint = 'Move closer';
    } else if (variance < 90) {
      status = 'AMBER';
      label = 'Hold steady — focusing...';
      hint = 'Hold steady';
    } else {
      status = 'GREEN';
      label = 'Ready';
      hint = 'Optimal alignment';
    }

    setDocQuality({
      status,
      label,
      sharpness: Math.round(variance),
      brightness: Math.round(meanLum),
      hint,
      rejectReason
    });
  };

  // Document Camera Controls: Request High-Resolution 1080p+ with environment facingMode
  const startDocCamera = async (target = 'front') => {
    try {
      setDocCaptureError(null);
      setDocCameraTarget(target);
      setDocQuality({
        status: 'RED',
        label: 'Starting HD document camera...',
        sharpness: 0,
        brightness: 0,
        hint: '',
        rejectReason: null
      });

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Camera API is not supported in this browser. Please use localhost or an HTTPS connection.");
      }

      // 1. Request ideal 1920+ resolution and facingMode environment
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 1920, min: 1280 },
            height: { ideal: 1080, min: 720 },
            facingMode: { ideal: 'environment' }
          },
          audio: false
        });
      } catch (err1) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: {
              width: { ideal: 1920 },
              height: { ideal: 1080 }
            },
            audio: false
          });
        } catch (err2) {
          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        }
      }

      docStreamRef.current = stream;
      setIsDocCameraOpen(true);

      if (soundEnabled) sounds.playScan();

      // Start 5fps live quality analysis loop (~200ms)
      if (docQualityIntervalRef.current) clearInterval(docQualityIntervalRef.current);
      docQualityIntervalRef.current = setInterval(analyzeDocFrameQuality, 200);

    } catch (err) {
      console.warn("Document camera access failed:", err);
      let msg = "Document camera access denied or device unavailable. You can upload an image file instead.";
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        msg = "Camera permission denied. Please allow camera access in your browser address bar.";
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        msg = "No camera hardware detected on this device.";
      }
      setErrorMsg(msg);
      setIsDocCameraOpen(false);
    }
  };

  const stopDocCamera = () => {
    if (docQualityIntervalRef.current) {
      clearInterval(docQualityIntervalRef.current);
      docQualityIntervalRef.current = null;
    }
    if (docStreamRef.current) {
      docStreamRef.current.getTracks().forEach(t => t.stop());
      docStreamRef.current = null;
    }
    if (docVideoRef.current) {
      docVideoRef.current.srcObject = null;
    }
    setIsDocCameraOpen(false);
    setDocCaptureError(null);
  };

  // Capture at Full Sensor Resolution & Block Bad Captures
  const captureDocFrame = () => {
    const video = docVideoRef.current;
    if (!video) return;

    // Block bad captures: re-check quality immediately on current frame
    analyzeDocFrameQuality();

    if (docQuality.status === 'RED') {
      const reason = docQuality.rejectReason || "Image quality insufficient for forensic verification.";
      setDocCaptureError(`Capture Rejected: ${reason}. Please stabilize document in guide frame.`);
      if (soundEnabled) sounds.playAlert();
      return;
    }

    setDocCaptureError(null);

    // Full sensor resolution capture (videoWidth x videoHeight), not preview display size!
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 1920;
    canvas.height = video.videoHeight || 1080;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob((blob) => {
      if (blob) {
        const fileName = docCameraTarget === 'front' 
          ? `doc_front_sensor_hd_${Date.now()}.jpg` 
          : `doc_back_sensor_hd_${Date.now()}.jpg`;
        const file = new File([blob], fileName, { type: "image/jpeg" });

        if (docCameraTarget === 'front') {
          processFrontFile(file);
        } else {
          processBackFile(file);
        }

        stopDocCamera();
        if (soundEnabled) sounds.playSuccess();
      }
    }, 'image/jpeg', 0.95);
  };

  // Inline Webcam Controls
  const startInlineCamera = async () => {
    try {
      setErrorMsg(null);

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Camera API is not supported in this browser environment. Ensure you are on http://localhost or HTTPS.");
      }

      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
        });
      } catch (err1) {
        stream = await navigator.mediaDevices.getUserMedia({ video: true });
      }

      streamRef.current = stream;
      setIsInlineCameraOpen(true);

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => {});
      }

      if (soundEnabled) sounds.playScan();
    } catch (err) {
      console.warn("Camera access failed:", err);
      let msg = "Camera access denied or device unavailable. You can upload a photo file instead.";
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        msg = "Camera permission denied. Please allow camera access in your browser address bar, or upload a photo below.";
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        msg = "No camera hardware detected on this device. You can upload a photo file instead.";
      } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
        msg = "Camera is currently in use by another application. Please close other video apps or upload a photo.";
      }
      setErrorMsg(msg);
      setIsInlineCameraOpen(false);
    }
  };

  const stopInlineCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setIsInlineCameraOpen(false);
  };

  const captureInlineFrame = () => {
    if (!videoRef.current) return;
    const canvas = document.createElement('canvas');
    canvas.width = videoRef.current.videoWidth || 640;
    canvas.height = videoRef.current.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
    
    canvas.toBlob((blob) => {
      if (blob) {
        const file = new File([blob], "traveler_live_selfie.jpg", { type: "image/jpeg" });
        setSelfieFileObj(file);
        setSelfieFileName("traveler_live_selfie.jpg");
        setSelfiePreview(URL.createObjectURL(blob));
        stopInlineCamera();
        if (soundEnabled) sounds.playSuccess();
      }
    }, 'image/jpeg', 0.95);
  };

  // -------------------------------------------------------------------------
  // Execution & Full Verification Pipeline
  // -------------------------------------------------------------------------

  const executeFullScan = async () => {
    if (!frontFileObj && !imagePreview) {
      setErrorMsg("Please upload at least the primary identity document (front side) to begin verification.");
      return;
    }

    setIsProcessing(true);
    setErrorMsg(null);
    setScanProgress(10);
    setScanStage("Ingesting document and initializing forensic models...");
    setOfficerDecision(null);
    const scanStartTime = performance.now();
    if (soundEnabled) sounds.playScan();

    try {
      // 1. Prepare front file
      let frontFileToSend = frontFileObj;
      if (!frontFileToSend && imagePreview) {
        const res = await fetch(imagePreview);
        const blob = await res.blob();
        frontFileToSend = new File([blob], "front_document.png", { type: blob.type || "image/png" });
      }

      // 2. Prepare back file
      let backFileToSend = backFileObj;
      if (!backFileToSend && backImagePreview) {
        const resB = await fetch(backImagePreview);
        const blobB = await resB.blob();
        backFileToSend = new File([blobB], "back_document.png", { type: blobB.type || "image/png" });
      }

      // 3. Prepare selfie file
      let selfieToSend = selfieFileObj;
      if (!selfieToSend && selfiePreview) {
        const resS = await fetch(selfiePreview);
        const blobS = await resS.blob();
        selfieToSend = new File([blobS], "selfie_photo.png", { type: blobS.type || "image/png" });
      }

      const formData = new FormData();
      formData.append('file', frontFileToSend);
      if (backFileToSend) {
        formData.append('back_image', backFileToSend);
      }
      if (selfieToSend) {
        formData.append('selfie_image', selfieToSend);
      }
      formData.append('document_type', docType || 'auto');
      formData.append('officer_id', 'OFFICER-4819');

      // Submit asynchronous screening job
      const response = await fetch('http://localhost:8000/api/scan/full', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Screening server error (${response.status}): ${errText}`);
      }

      const data = await response.json();

      let finalReport = null;

      // Handle async background task polling
      if (data.status === 'processing' && data.scan_id) {
        const scanId = data.scan_id;
        let isDone = false;
        let attempts = 0;
        const maxAttempts = 120; // up to 120s

        while (!isDone && attempts < maxAttempts) {
          await new Promise(r => setTimeout(r, 1000));
          attempts++;

          const pollRes = await fetch(`http://localhost:8000/api/scan/${scanId}/status`);
          if (pollRes.ok) {
            const pollData = await pollRes.json();
            if (pollData.progress) {
              setScanProgress(pollData.progress);
            }
            if (pollData.stage) {
              setScanStage(pollData.stage);
            }

            if (pollData.status === 'completed') {
              finalReport = pollData.result;
              isDone = true;
              setScanProgress(100);
              setScanStage("Screening completed successfully.");
              break;
            } else if (pollData.status === 'failed') {
              throw new Error(pollData.error || "Background screening task failed.");
            }
          }
        }

        if (!isDone) {
          throw new Error("Screening job timed out. Server may still be processing.");
        }
      } else {
        // Direct synchronous response fallback
        finalReport = data;
        setScanProgress(100);
        setScanStage("Screening completed.");
      }

      const durationMs = Math.round((performance.now() - scanStartTime) * 10) / 10;
      finalReport._measured_processing_time_ms = durationMs;
      setMeasuredProcessingTimeMs(durationMs);
      setScanResult(finalReport);

      const detectedSubtype = finalReport.ocr?.document_subtype ||
                              finalReport.ocr?.detected_document_subtype ||
                              finalReport.document_type ||
                              finalReport.ocr?.document_type || null;

      // Update current session slot
      setSessionDocuments(prev => {
        const updated = [...prev];
        if (updated[activeSessionSlotIdx]) {
          updated[activeSessionSlotIdx] = {
            ...updated[activeSessionSlotIdx],
            status: 'completed',
            scanResult: finalReport,
            frontFile: frontFileToSend,
            frontPreview: imagePreview,
            backFile: backFileToSend,
            backPreview: backImagePreview,
            selfieFile: selfieToSend,
            selfiePreview: selfiePreview,
            type: docType || updated[activeSessionSlotIdx].type,
            detectedType: detectedSubtype,
          };
        }
        return updated;
      });

      // Sync into backend session
      if (currentSessionId) {
        try {
          const sessForm = new FormData();
          sessForm.append('file', frontFileToSend);
          if (backFileToSend) sessForm.append('back_image', backFileToSend);
          if (selfieToSend) sessForm.append('selfie_image', selfieToSend);
          sessForm.append('document_type', docType || 'auto');
          sessForm.append('document_label', sessionDocuments[activeSessionSlotIdx]?.label || `Document ${activeSessionSlotIdx + 1}`);
          sessForm.append('officer_id', 'OFFICER-4819');
          sessForm.append('sync', 'true');
          fetch(`http://localhost:8000/api/session/${currentSessionId}/document`, {
            method: 'POST',
            body: sessForm,
          }).catch(e => console.warn("Session upload error:", e));
        } catch (e) {
          console.warn("Session upload exception:", e);
        }
      }

      // Pre-fill editable fields map
      const fieldsMap = {};
      if (finalReport.ocr?.extracted_fields) {
        Object.entries(finalReport.ocr.extracted_fields).forEach(([k, fObj]) => {
          fieldsMap[k] = fObj.value;
        });
      }
      setEditableFields(fieldsMap);

      if (finalReport.risk?.risk_tier === 'LOW') {
        if (soundEnabled) sounds.playSuccess();
      } else {
        if (soundEnabled) sounds.playAlert();
      }
    } catch (err) {
      console.error("Full scan error:", err);
      setErrorMsg(err.message || "Screening service failed. Check backend server logs.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleOfficerDecision = (decision) => {
    setOfficerDecision(decision);
    if (soundEnabled) {
      if (decision === 'APPROVED') sounds.playSuccess();
      else sounds.playAlert();
    }
  };

  const getRiskColor = (tier) => {
    switch (tier?.toUpperCase()) {
      case 'CRITICAL':
        return 'text-rose-400 bg-rose-950/80 border-rose-600 shadow-rose-950/50';
      case 'HIGH':
        return 'text-orange-400 bg-orange-950/80 border-orange-600';
      case 'MEDIUM':
        return 'text-amber-300 bg-amber-950/80 border-amber-600';
      default:
        return 'text-emerald-400 bg-emerald-950/80 border-emerald-600 shadow-emerald-950/50';
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Person Intake & Session Header Bar */}
      <Panel className="p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-[#10151C] border border-[#232B38] rounded-[4px] flex items-center justify-center text-[#D9A441] shrink-0">
            <Users className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-sm font-bold text-[#E4E7EB] font-sans">
                Traveler Checkpoint Session
              </h2>
              {currentSessionId && (
                <Badge variant="warning" size="sm">
                  {currentSessionId}
                </Badge>
              )}
              <span className="font-mono text-[10px] text-[#D9A441] bg-[#D9A441]/10 px-2 py-0.5 rounded-[4px] border border-[#D9A441]/30 flex items-center gap-1">
                <MapPin className="w-3 h-3 text-[#D9A441]" />
                <span>{currentLocationName}</span>
              </span>
            </div>
            <p className="text-xs text-[#8A93A3] mt-0.5 font-mono">
              Multi-document protocol: each additional corroborating document increases verification coverage. Cross-document checks activate automatically from the second document.
            </p>
          </div>
        </div>

        {/* Action Controls & Session Counter */}
        <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
          <div className="px-3 py-1.5 rounded-[4px] bg-[#0B0F14] border border-[#232B38] text-xs flex items-center gap-2 font-mono">
            <span className="text-[#8A93A3]">Documents:</span>
            <span className="font-bold text-[#E2E8F0]">
              {sessionDocuments.filter(d => d.status === 'completed').length}
            </span>
            <span className="text-[#5A6578]">·</span>
            <span className="text-[#8A93A3]">Coverage:</span>
            <span className={`font-bold ${
              sessionDocuments.filter(d => d.status === 'completed').length === 0
                ? 'text-[#8A93A3]'
                : sessionDocuments.filter(d => d.status === 'completed').length === 1
                ? 'text-[#D9A441]'
                : 'text-[#4ADE80]'
            }`}>
              {sessionDocuments.filter(d => d.status === 'completed').length === 0
                ? 'none'
                : sessionDocuments.filter(d => d.status === 'completed').length === 1
                ? 'partial'
                : 'strong'}
            </span>
          </div>

          <Button
            size="sm"
            variant="secondary"
            onClick={handleStartNewSession}
            icon={RefreshCw}
            title="Start new traveler checkpoint session"
          >
            Start new check-in
          </Button>
        </div>
      </Panel>

      {/* Session Document Slot Selector Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar">
        {sessionDocuments.map((doc, idx) => {
          const isSelected = activeSessionSlotIdx === idx;
          const isDone = doc.status === 'completed';
          return (
            <button
              key={doc.id}
              onClick={() => handleSelectSlot(idx)}
              className={`px-3.5 py-2 rounded-[4px] text-xs font-medium transition flex items-center gap-2 shrink-0 border cursor-pointer min-h-[44px] ${
                isSelected
                  ? 'bg-[#2D6A9F]/20 text-[#60A5FA] border-[#2D6A9F] font-semibold'
                  : isDone
                  ? 'bg-[#141A22] text-[#4ADE80] border-[#3F9868]/50 hover:bg-[#1B222D]'
                  : 'bg-[#0B0F14] text-[#8A93A3] border-[#232B38] hover:bg-[#141A22]'
              }`}
            >
              <div className={`w-5 h-5 rounded-[2px] flex items-center justify-center text-[10px] font-bold font-mono ${
                isDone ? 'bg-[#3F9868]/20 text-[#4ADE80]' : 'bg-[#10151C] text-[#8A93A3]'
              }`}>
                {isDone ? '✓' : idx + 1}
              </div>
              <span className="font-mono">{doc.label}</span>
              {doc.detectedType && (
                <span className="ml-1 text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-[#10151C] text-[#38BDF8] border border-[#0284C7]/40 uppercase tracking-wider">
                  {formatDocTypeBadge(doc.detectedType)}
                </span>
              )}
              {isDone && <span className="text-[10px] text-[#4ADE80] font-normal">Ready</span>}
            </button>
          );
        })}

        <Button
          size="sm"
          variant="secondary"
          onClick={handleAddDocumentSlot}
          icon={Plus}
          className="border-dashed min-h-[44px]"
        >
          {sessionDocuments.length === 3 ? "Add 4th document" : `Add document ${sessionDocuments.length + 1}`}
        </Button>
      </div>

      {sessionErrorMsg && (
        <Toast
          variant="critical"
          title="Session Validation Error"
          message={sessionErrorMsg}
          onClose={() => setSessionErrorMsg(null)}
        />
      )}

      {/* Main Intake & Screening Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* ==================================================================== */}
        {/* Left 5 Columns: Person Upload & Intake Studio */}
        {/* ==================================================================== */}
        <div className="lg:col-span-5 space-y-4">
          <Panel className="p-4 space-y-4">
            
            {/* Step 1: Document Type Declaration Tabs */}
            <div className="space-y-1.5">
              <label className="text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3] flex items-center justify-between">
                <span>1. Target Document Type</span>
                <span className="text-[#8A93A3] text-[10px] lowercase font-mono">Select or auto-classify</span>
              </label>
              <Tabs
                tabs={DOCUMENT_TYPES.map(d => ({ id: d.id, label: d.label }))}
                activeTab={docType}
                onChange={setDocType}
                ariaLabel="Target Document Type Selector"
              />
            </div>

            {/* Step 2: Primary Front Document Upload */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-200 flex items-center space-x-1.5">
                  <FileText className="w-3.5 h-3.5 text-blue-400" />
                  <span>2. Primary Document (Front Side) *</span>
                </label>
                {frontFileName && (
                  <span className="text-[10px] font-mono text-blue-400 truncate max-w-[150px]">
                    {frontFileName}
                  </span>
                )}
              </div>

              {!imagePreview ? (
                <div
                  onDragOver={(e) => { e.preventDefault(); setIsFrontDragging(true); }}
                  onDragLeave={() => setIsFrontDragging(false)}
                  onDrop={handleFrontDrop}
                  className={`border-2 border-dashed rounded-lg p-5 text-center transition-all cursor-pointer flex flex-col items-center justify-center space-y-2.5 ${
                    isFrontDragging 
                      ? 'border-blue-400 bg-[#162235]' 
                      : 'border-[#384457] hover:border-blue-400/60 bg-[#161B22]'
                  }`}
                >
                  <label className="cursor-pointer flex flex-col items-center space-y-1.5 w-full">
                    <div className="w-9 h-9 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-blue-400">
                      <Upload className="w-4 h-4" />
                    </div>
                    <span className="text-xs font-bold text-slate-200">
                      Click to browse or drag & drop front document
                    </span>
                    <span className="text-[11px] text-slate-400 max-w-xs">
                      Passport bio page, Aadhaar front, PAN card, driving license, or ID
                    </span>
                    <input 
                      type="file" 
                      accept="image/*" 
                      onChange={(e) => e.target.files && processFrontFile(e.target.files[0])} 
                      className="hidden" 
                    />
                  </label>

                  <div className="pt-2 border-t border-[#232B38] w-full flex items-center justify-center">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        startDocCamera('front');
                      }}
                      className="px-3 py-1.5 bg-[#D9A441]/15 hover:bg-[#D9A441]/25 text-[#D9A441] border border-[#D9A441]/40 rounded-[4px] text-xs font-mono font-bold cursor-pointer transition flex items-center gap-1.5 shadow-sm"
                    >
                      <Camera className="w-3.5 h-3.5" />
                      <span>Scan with HD Document Camera</span>
                    </button>
                  </div>
                </div>
              ) : (
                <div className="relative aspect-[16/10] bg-black/70 rounded-xl border border-slate-800 overflow-hidden flex items-center justify-center group">
                  <img 
                    src={imagePreview} 
                    alt="Document Front Preview" 
                    className="max-h-full object-contain rounded-lg p-1"
                  />
                  <div className="absolute inset-0 bg-slate-950/80 backdrop-blur-xs opacity-0 group-hover:opacity-100 flex items-center justify-center space-x-2 transition">
                    <button
                      type="button"
                      onClick={() => startDocCamera('front')}
                      className="px-2.5 py-1.5 bg-[#D9A441] hover:bg-[#C29035] text-slate-950 font-bold rounded-lg text-xs cursor-pointer transition flex items-center space-x-1"
                    >
                      <Camera className="w-3.5 h-3.5" />
                      <span>Camera</span>
                    </button>
                    <label className="px-2.5 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-bold cursor-pointer transition flex items-center space-x-1">
                      <Upload className="w-3.5 h-3.5" />
                      <span>Upload</span>
                      <input 
                        type="file" 
                        accept="image/*" 
                        onChange={(e) => e.target.files && processFrontFile(e.target.files[0])} 
                        className="hidden" 
                      />
                    </label>
                    <button
                      onClick={() => {
                        setImagePreview(null);
                        setFrontFileObj(null);
                        setFrontFileName('');
                        setScanResult(null);
                      }}
                      className="px-2.5 py-1.5 bg-rose-600/80 hover:bg-rose-600 text-white rounded-lg text-xs font-bold cursor-pointer transition flex items-center space-x-1"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Remove</span>
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Step 3: Secondary Document (Back) & Traveler Presentation Photo (Selfie) */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
              
              {/* Reverse side (optional) */}
              <div className="p-3 rounded-lg bg-[#11161F] border border-[#252D3B] space-y-2">
                <div className="flex items-center justify-between text-xs font-medium text-slate-300">
                  <span>Reverse side (optional)</span>
                  {backImagePreview && (
                    <button
                      onClick={() => {
                        setBackImagePreview(null);
                        setBackFileObj(null);
                        setBackFileName('');
                      }}
                      className="text-rose-400 hover:text-rose-300 cursor-pointer"
                      title="Remove back image"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {!backImagePreview ? (
                  <div className={`aspect-[16/10] rounded-lg border border-dashed flex flex-col items-center justify-center p-2 text-center transition ${
                    isBackDragging 
                      ? 'border-cyan-400 bg-cyan-500/10' 
                      : 'border-slate-800 hover:border-slate-700 bg-slate-900/40'
                  }`}>
                    <label
                      onDragOver={(e) => { e.preventDefault(); setIsBackDragging(true); }}
                      onDragLeave={() => setIsBackDragging(false)}
                      onDrop={handleBackDrop}
                      className="cursor-pointer flex flex-col items-center justify-center w-full"
                    >
                      <Upload className="w-4 h-4 text-slate-500 mb-1" />
                      <span className="text-[10px] font-bold text-slate-400">Upload reverse side</span>
                      <span className="text-[9px] text-slate-400 mt-0.5">Aadhaar address / reverse</span>
                      <input 
                        type="file" 
                        accept="image/*" 
                        onChange={(e) => e.target.files && processBackFile(e.target.files[0])} 
                        className="hidden" 
                      />
                    </label>
                    <div className="pt-1.5 mt-1 border-t border-slate-800/80 w-full flex justify-center">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          startDocCamera('back');
                        }}
                        className="px-2 py-0.5 text-[10px] font-mono text-[#D9A441] hover:text-[#E4E7EB] flex items-center gap-1 cursor-pointer"
                      >
                        <Camera className="w-3 h-3" />
                        <span>Use Camera</span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="relative aspect-[16/10] bg-black/50 rounded-lg overflow-hidden flex items-center justify-center border border-slate-800 group">
                    <img src={backImagePreview} alt="Document Back" className="max-h-full object-contain" />
                    <div className="absolute inset-0 bg-slate-950/70 opacity-0 group-hover:opacity-100 flex items-center justify-center space-x-2 transition">
                      <button
                        type="button"
                        onClick={() => startDocCamera('back')}
                        className="px-2 py-1 bg-[#D9A441] text-slate-950 rounded text-[10px] font-bold cursor-pointer"
                      >
                        Camera
                      </button>
                      <label className="px-2 py-1 bg-cyan-600 text-white rounded text-[10px] font-bold cursor-pointer">
                        <span>Change</span>
                        <input 
                          type="file" 
                          accept="image/*" 
                          onChange={(e) => e.target.files && processBackFile(e.target.files[0])} 
                          className="hidden" 
                        />
                      </label>
                    </div>
                  </div>
                )}
              </div>

              {/* Traveler Presentation Photo (Selfie) */}
              <div className="p-3 rounded-lg bg-[#11161F] border border-[#252D3B] space-y-2">
                <div className="flex items-center justify-between text-xs font-medium text-slate-300">
                  <span>Traveler live photo</span>
                  {selfiePreview && (
                    <button
                      type="button"
                      onClick={(e) => {
                        if (e?.preventDefault) e.preventDefault();
                        setSelfiePreview(null);
                        setSelfieFileObj(null);
                        setSelfieFileName('');
                      }}
                      className="text-rose-400 hover:text-rose-300 cursor-pointer"
                      title="Remove face photo"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {!selfiePreview ? (
                  <div className="aspect-[16/10] rounded-lg border border-dashed border-slate-800 bg-slate-900/40 p-2 flex flex-col items-center justify-center gap-1.5">
                    <div className="flex items-center space-x-2">
                      <label className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[10px] font-bold cursor-pointer transition flex items-center space-x-1">
                        <Upload className="w-3 h-3" />
                        <span>Upload</span>
                        <input 
                          type="file" 
                          accept="image/*" 
                          onChange={(e) => {
                            if (e?.preventDefault) e.preventDefault();
                            if (e.target.files?.[0]) processSelfieFile(e.target.files[0]);
                          }} 
                          className="hidden" 
                        />
                      </label>
                      <button
                        type="button"
                        onClick={(e) => {
                          if (e?.preventDefault) e.preventDefault();
                          startInlineCamera();
                        }}
                        className="px-2 py-1 rounded bg-cyan-600/80 hover:bg-cyan-600 text-white text-[10px] font-bold cursor-pointer transition flex items-center space-x-1"
                      >
                        <Camera className="w-3 h-3" />
                        <span>Camera</span>
                      </button>
                    </div>
                    <span className="text-[9px] text-slate-400">For 1:1 facial biometric matching</span>
                  </div>
                ) : (
                  <div className="relative aspect-[16/10] bg-black/50 rounded-lg overflow-hidden flex items-center justify-center border border-slate-800 group">
                    <img src={selfiePreview} alt="Traveler Portrait" className="max-h-full object-contain" />
                    <div className="absolute inset-0 bg-slate-950/70 opacity-0 group-hover:opacity-100 flex items-center justify-center space-x-2 transition">
                      <button
                        type="button"
                        onClick={(e) => {
                          if (e?.preventDefault) e.preventDefault();
                          startInlineCamera();
                        }}
                        className="px-2 py-1 bg-cyan-600 text-white rounded text-[10px] font-bold cursor-pointer"
                      >
                        Retake
                      </button>
                    </div>
                  </div>
                )}
              </div>

            </div>

            {/* Inline Camera Capture Modal/Overlay */}
            {isInlineCameraOpen && (
              <div className="p-3 bg-slate-950 border border-cyan-500/50 rounded-xl space-y-3">
                <div className="flex items-center justify-between text-xs font-mono font-bold text-slate-300">
                  <span className="flex items-center space-x-1.5">
                    <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse"></span>
                    <span>Live presentation camera</span>
                  </span>
                  <button 
                    type="button"
                    onClick={(e) => {
                      if (e?.preventDefault) e.preventDefault();
                      stopInlineCamera();
                    }} 
                    className="text-slate-400 hover:text-white"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="relative aspect-[4/3] bg-black rounded-lg overflow-hidden border border-slate-800">
                  <video 
                    ref={(el) => {
                      videoRef.current = el;
                      if (el && streamRef.current && el.srcObject !== streamRef.current) {
                        el.srcObject = streamRef.current;
                        el.play().catch(err => console.warn("Inline video play error:", err));
                      }
                    }} 
                    autoPlay 
                    playsInline 
                    muted 
                    className="w-full h-full object-cover" 
                  />
                  <div className="absolute inset-0 pointer-events-none border-2 border-cyan-400/40 rounded-lg m-4 flex items-center justify-center">
                    <span className="text-[10px] font-mono text-blue-400/60 bg-black/40 px-2 py-0.5 rounded">
                      Align traveler face inside frame
                    </span>
                  </div>
                </div>
                <div className="flex items-center justify-between space-x-2">
                  <button
                    type="button"
                    onClick={(e) => {
                      if (e?.preventDefault) e.preventDefault();
                      stopInlineCamera();
                      setActiveWorkspaceTab('biometrics');
                    }}
                    className="text-[11px] text-cyan-400 hover:text-cyan-300 flex items-center space-x-1 cursor-pointer font-mono"
                  >
                    <span>Guided Liveness &rarr;</span>
                  </button>
                  <div className="flex items-center space-x-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        if (e?.preventDefault) e.preventDefault();
                        stopInlineCamera();
                      }}
                      className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold cursor-pointer"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        if (e?.preventDefault) e.preventDefault();
                        captureInlineFrame();
                      }}
                      className="px-4 py-1.5 bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold rounded-lg text-xs cursor-pointer flex items-center space-x-1.5"
                    >
                      <Camera className="w-3.5 h-3.5" />
                      <span>Capture face photo</span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Primary Action Button: Execute Verification for Active Slot */}
            <Button
              variant="primary"
              size="lg"
              onClick={executeFullScan}
              disabled={isProcessing || (!frontFileObj && !imagePreview)}
              isLoading={isProcessing}
              icon={ShieldCheck}
              className="w-full text-xs font-bold uppercase tracking-wider"
            >
              {sessionDocuments[activeSessionSlotIdx]?.status === 'completed'
                ? `Re-screen ${sessionDocuments[activeSessionSlotIdx]?.label}`
                : `Screen & verify ${sessionDocuments[activeSessionSlotIdx]?.label || 'document'}`}
            </Button>

            {/* Master Combined Session Report Trigger */}
            <div className="pt-2 border-t border-[#232B38]">
              <Button
                variant={sessionDocuments.filter(d => d.status === 'completed').length >= 1 ? "primary" : "secondary"}
                size="lg"
                onClick={handleGenerateSessionReport}
                disabled={isGeneratingSessionReport || sessionDocuments.filter(d => d.status === 'completed').length < 1}
                isLoading={isGeneratingSessionReport}
                icon={FileCheck}
                className="w-full text-xs font-bold uppercase tracking-wider"
              >
                GENERATE REPORT
              </Button>
            </div>

            {/* Live Progress Bar */}
            {isProcessing && (
              <div className="p-3 bg-slate-900/90 border border-blue-500/40 rounded-xl space-y-2 animate-pulse">
                <div className="flex items-center justify-between text-[11px] font-mono">
                  <span className="text-slate-300 font-medium flex items-center space-x-1.5">
                    <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping inline-block mr-1"></span>
                    <span>{scanStage || "Processing screening pipeline..."}</span>
                  </span>
                  <span className="text-blue-400 font-bold">{scanProgress}%</span>
                </div>
                <div className="w-full bg-slate-950 rounded-full h-1.5 overflow-hidden border border-slate-800">
                  <div 
                    className="bg-gradient-to-r from-cyan-400 via-blue-500 to-indigo-500 h-1.5 rounded-full transition-all duration-300"
                    style={{ width: `${Math.min(100, Math.max(5, scanProgress))}%` }}
                  />
                </div>
              </div>
            )}

            {errorMsg && (
              <div className="p-3 bg-rose-950/50 border border-rose-800/80 rounded-xl text-rose-300 text-xs flex items-start space-x-2">
                <AlertCircle className="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
                <span>{errorMsg}</span>
              </div>
            )}
          </Panel>
        </div>

        {/* ==================================================================== */}
        {/* Right 7 Columns: Verified Output & Intelligence Workspace */}
        {/* ==================================================================== */}
        <div className="lg:col-span-7 space-y-4">
          
          {/* Workspace Tab Navigation */}
          <div className="glass-panel p-2 rounded-2xl border border-slate-800 flex items-center space-x-2">
            <button
              onClick={() => setActiveWorkspaceTab('overview')}
              className={`flex-1 py-2 rounded-xl text-xs font-bold transition flex items-center justify-center space-x-2 cursor-pointer ${
                activeWorkspaceTab === 'overview'
                  ? 'bg-blue-900/30 text-slate-300 border border-blue-500/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Cpu className="w-4 h-4" />
              <span>Risk & extracted fields</span>
            </button>

            <button
              onClick={() => setActiveWorkspaceTab('forensics')}
              className={`flex-1 py-2 rounded-xl text-xs font-bold transition flex items-center justify-center space-x-2 cursor-pointer ${
                activeWorkspaceTab === 'forensics'
                  ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Sliders className="w-4 h-4" />
              <span>Module 3: ELA forensics</span>
            </button>

            <button
              onClick={() => setActiveWorkspaceTab('biometrics')}
              className={`flex-1 py-2 rounded-xl text-xs font-bold transition flex items-center justify-center space-x-2 cursor-pointer ${
                activeWorkspaceTab === 'biometrics'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Camera className="w-4 h-4" />
              <span>Module 4: Biometrics</span>
            </button>
          </div>

          {/* Subview 1: Overview & Verified Fields */}
          {activeWorkspaceTab === 'overview' && (
            <div className="space-y-4">
              
              {/* Combined Multi-Document Session Intelligence Report (Part A) */}
              {sessionReport && (
                <div className="space-y-4">
                  {/* Session Executive Assessment Card */}
                  <Panel className="p-5 border border-[#232B38] bg-[#141A22]">
                    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
                      <div className="flex items-center gap-6">
                        <RiskGauge
                          score={sessionReport.session_risk_score}
                          tier={sessionReport.session_risk_tier}
                          size="md"
                        />

                        <div className="space-y-1.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <Badge variant="neutral" size="sm">
                              Session: {sessionReport.session_id}
                            </Badge>
                            <Badge
                              variant={
                                (sessionReport.coverage || (sessionReport.documents_submitted >= 2 ? 'strong' : 'partial')) === 'strong'
                                  ? 'success'
                                  : 'warning'
                              }
                              size="sm"
                            >
                              Documents: {sessionReport.documents_submitted} · Coverage: {sessionReport.coverage || (sessionReport.documents_submitted >= 2 ? 'strong' : 'partial')}
                            </Badge>
                            <Badge
                              variant={
                                sessionReport.session_risk_tier === 'CRITICAL' || sessionReport.session_risk_tier === 'HIGH'
                                  ? 'critical'
                                  : sessionReport.session_risk_tier === 'MEDIUM'
                                  ? 'warning'
                                  : 'success'
                              }
                              size="sm"
                            >
                              {sessionReport.session_risk_tier}
                            </Badge>
                          </div>

                          <div className="text-base font-bold text-[#E4E7EB] font-sans">
                            {sessionReport.session_action?.replace(/_/g, ' ')}
                          </div>
                          <div className="text-xs text-[#8A93A3] font-sans leading-relaxed max-w-xl">
                            {sessionReport.cross_document_validation?.summary || sessionReport.summary}
                          </div>
                        </div>
                      </div>

                      <div className="border-t sm:border-t-0 sm:border-l border-[#232B38] pt-4 sm:pt-0 sm:pl-6 text-right shrink-0">
                        <div className="text-[11px] font-mono uppercase text-[#8A93A3]">Corroboration Factor</div>
                        <div className="text-xl font-bold font-mono text-[#4ADE80] mt-1">
                          {Math.round((sessionReport.cross_document_validation?.corroboration_factor || 0) * 100)}%
                        </div>
                        <span className="text-[10px] text-[#8A93A3] font-mono block">Multi-Doc Consistency</span>
                      </div>
                    </div>
                  </Panel>

                  {/* Top-Level Cross-Document Consistency Audit Table */}
                  <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center space-x-2">
                        <FileCheck className="w-4 h-4 text-blue-400" />
                        <h3 className="text-xs font-semibold text-slate-200">
                          Cross-document identity consistency audit
                        </h3>
                      </div>
                      <span className={`text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full border ${
                        sessionReport.cross_document_validation?.has_cross_document_mismatch
                          ? 'bg-rose-950/80 text-rose-300 border-rose-600'
                          : sessionReport.documents_submitted < 2
                          ? 'bg-amber-950/80 text-amber-300 border-amber-600'
                          : 'bg-emerald-950/80 text-emerald-300 border-emerald-600'
                      }`}>
                        {sessionReport.cross_document_validation?.has_cross_document_mismatch
                          ? 'Cross-document mismatch detected'
                          : sessionReport.documents_submitted < 2
                          ? 'Single document screened · Partial coverage'
                          : 'All cross-document fields consistent'}
                      </span>
                    </div>

                    {/* Prominent Mismatch Alert Banner */}
                    {sessionReport.cross_document_validation?.has_cross_document_mismatch && (
                      <div className="p-3.5 rounded-xl bg-rose-950/90 border-2 border-rose-500 text-rose-200 space-y-1.5 shadow-lg shadow-rose-950/40">
                        <div className="flex items-center space-x-2 text-xs font-bold font-heading text-rose-300">
                          <ShieldAlert className="w-4 h-4 text-rose-400" />
                          <span>Cross-document identity mismatch flagged</span>
                        </div>
                        {sessionReport.cross_document_validation?.mismatched_fields?.map((fKey, i) => {
                          const fItem = sessionReport.cross_document_validation?.field_consistency?.[fKey];
                          return (
                            <div key={i} className="text-xs font-sans text-rose-200/90 pl-6">
                              {fItem?.message || `'${fKey}' does not match across submitted documents.`}
                            </div>
                          );
                        })}
                        <div className="text-[10px] font-mono text-rose-300/80 pl-6">
                          * Non-dilution floor enforced: Security Risk Score clamped to ≥ 75.0 (HIGH/CRITICAL tier).
                        </div>
                      </div>
                    )}

                    {/* Table of Compared Fields */}
                    <div className="overflow-x-auto rounded-xl border border-slate-800">
                      <table className="w-full text-xs text-left">
                        <thead className="bg-slate-950 text-xs font-medium text-slate-400 border-b border-slate-800">
                          <tr>
                            <th className="p-2.5">Identity field</th>
                            <th className="p-2.5">Submitted values across documents</th>
                            <th className="p-2.5 text-right">Consistency status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/80 bg-slate-900/40 font-mono text-xs">
                          {Object.keys(sessionReport.cross_document_validation?.field_consistency || {}).length === 0 ? (
                            <tr>
                              <td colSpan="3" className="p-4 text-center text-slate-400 font-sans text-xs">
                                Single document screened (partial verification coverage). Upload corroborating documents (e.g. Visa, National ID) to activate cross-document field comparisons.
                              </td>
                            </tr>
                          ) : (
                            Object.entries(sessionReport.cross_document_validation?.field_consistency || {}).map(([fKey, fData], idx) => {
                              const isMismatch = fData.consistent === false;
                              const isInsufficient = fData.consistent === null || fData.status === 'insufficient_corroboration';
                              return (
                                <tr key={idx} className={isMismatch ? 'bg-rose-950/40 border-l-4 border-l-rose-500' : isInsufficient ? 'opacity-80 hover:bg-slate-900/40' : 'hover:bg-slate-900/60'}>
                                  <td className="p-2.5 font-bold capitalize text-slate-200">
                                    {fKey.replace(/_/g, ' ')}
                                  </td>
                                  <td className="p-2.5 space-y-1">
                                    {fData.values && fData.values.length > 0 ? (
                                      fData.values.map((vItem, vIdx) => (
                                        <div key={vIdx} className="flex items-center space-x-2 text-[11px]">
                                          <span className="px-1.5 py-0.2 rounded bg-slate-800 text-slate-300 font-sans font-medium text-[10px]">
                                            {vItem.document || `Doc ${vIdx + 1}`}:
                                          </span>
                                          <span className={isMismatch ? 'text-rose-300 font-bold' : 'text-slate-200'}>
                                            '{vItem.value}'
                                          </span>
                                        </div>
                                      ))
                                    ) : (
                                      <span className="text-[11px] text-slate-500 italic">Not extracted in submitted documents</span>
                                    )}
                                  </td>
                                  <td className="p-2.5 text-right">
                                    {isMismatch ? (
                                      <span className="px-2 py-0.5 rounded bg-rose-900/80 text-rose-300 text-[10px] font-bold border border-rose-700">
                                        Mismatch
                                      </span>
                                    ) : isInsufficient ? (
                                      <span className="px-2 py-0.5 rounded bg-slate-800/80 text-slate-400 text-[10px] font-medium border border-slate-700">
                                        Single Source
                                      </span>
                                    ) : (
                                      <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 text-[10px] font-bold border border-emerald-800">
                                        Verified
                                      </span>
                                    )}
                                  </td>
                                </tr>
                              );
                            })
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Collapsible Per-Document Breakdown Accordion */}
                  <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-3">
                    <h3 className="text-xs font-semibold text-slate-200 flex items-center space-x-2">
                      <Layers className="w-4 h-4 text-blue-400" />
                      <span>Individual Document Forensics ({sessionDocuments.filter(d => d.status === 'completed').length} Uploaded)</span>
                    </h3>

                    <div className="space-y-2">
                      {sessionDocuments.filter(d => d.status === 'completed').map((sDoc, sIdx) => {
                        const isExpanded = expandedDocIdx === sIdx;
                        const docResult = sDoc.scanResult;
                        return (
                          <div key={sIdx} className="rounded-xl border border-slate-800 bg-slate-950/80 overflow-hidden">
                            <button
                              onClick={() => setExpandedDocIdx(isExpanded ? null : sIdx)}
                              className="w-full p-3 flex items-center justify-between text-xs font-mono font-bold text-left hover:bg-slate-900 transition cursor-pointer"
                            >
                              <div className="flex items-center space-x-2">
                                <span className="w-5 h-5 rounded-full bg-blue-900/30 text-slate-300 flex items-center justify-center text-[10px]">
                                  {sIdx + 1}
                                </span>
                                <span className="text-white">{sDoc.label}</span>
                                <span className="text-[10px] font-normal text-slate-400 uppercase">({sDoc.type})</span>
                              </div>
                              <div className="flex items-center space-x-3">
                                {docResult && (
                                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                    docResult.risk?.risk_tier === 'LOW' ? 'bg-emerald-950 text-emerald-400' : 'bg-rose-950 text-rose-400'
                                  }`}>
                                    Risk: {docResult.risk?.risk_score} ({docResult.risk?.risk_tier})
                                  </span>
                                )}
                                {isExpanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                              </div>
                            </button>

                            {isExpanded && docResult && (
                              <div className="p-3 border-t border-slate-800/80 bg-slate-900/40 text-xs space-y-3 font-sans">
                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] font-mono">
                                  <div className="p-2 rounded bg-slate-950 border border-slate-800">
                                    <span className="text-slate-400 block text-[9px]">Holder Name:</span>
                                    <span className="font-bold text-slate-200 truncate block">
                                      {docResult.ocr?.extracted_fields?.name?.value || '--'}
                                    </span>
                                  </div>
                                  <div className="p-2 rounded bg-slate-950 border border-slate-800">
                                    <span className="text-slate-400 block text-[9px]">Date of Birth:</span>
                                    <span className="font-bold text-slate-200">
                                      {docResult.ocr?.extracted_fields?.date_of_birth?.value || '--'}
                                    </span>
                                  </div>
                                  <div className="p-2 rounded bg-slate-950 border border-slate-800">
                                    <span className="text-slate-400 block text-[9px]">Document ID:</span>
                                    <span className="font-bold text-slate-200 truncate block">
                                      {docResult.document_number || docResult.ocr?.extracted_fields?.passport_number?.value || '--'}
                                    </span>
                                  </div>
                                  <div className="p-2 rounded bg-slate-950 border border-slate-800">
                                    <span className="text-slate-400 block text-[9px]">Tampering:</span>
                                    <span className={`font-bold ${docResult.tampering?.is_tampered ? 'text-rose-400' : 'text-emerald-400'}`}>
                                      {Math.round((docResult.tampering?.tampering_score || 0) * 100)}%
                                    </span>
                                  </div>
                                </div>
                                <button
                                  onClick={() => {
                                    setScanResult(docResult);
                                    setActiveWorkspaceTab('forensics');
                                  }}
                                  className="text-[11px] font-mono text-blue-400 hover:text-slate-300 underline cursor-pointer"
                                >
                                  → Inspect Localized ELA Forensics for this Document
                                </button>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* Individual Single Scan Result / Fallback */}
              {!sessionReport && (
                <>
              {/* Prominent Risk Banner or Ready State */}
              {scanResult ? (
                <>
                  {(() => {
                    const warning = scanResult.type_mismatch_warning ||
                                    scanResult.ocr?.type_mismatch_warning ||
                                    scanResult.validation?.type_mismatch_warning ||
                                    (() => {
                                      if (docType && docType !== 'auto') {
                                        const det = scanResult.ocr?.document_subtype ||
                                                    scanResult.ocr?.detected_document_subtype ||
                                                    scanResult.document_type;
                                        if (det && det !== 'unknown' && det !== 'Unknown Document') {
                                          const normSub = docType.toLowerCase().replace(/[^a-z]/g, '');
                                          const normDet = String(det).toLowerCase().replace(/[^a-z]/g, '');
                                          const isSubPass = normSub.includes('passport');
                                          const isDetPass = normDet.includes('passport');
                                          const isSubAadh = normSub.includes('aadhaar');
                                          const isDetAadh = normDet.includes('aadhaar');
                                          const isSubPan = normSub.includes('pan');
                                          const isDetPan = normDet.includes('pan');
                                          const isSubDl = normSub.includes('driving') || normSub.includes('dl');
                                          const isDetDl = normDet.includes('driving') || normDet.includes('dl');

                                          const matches = (isSubPass && isDetPass) || (isSubAadh && isDetAadh) || (isSubPan && isDetPan) || (isSubDl && isDetDl) || (normSub === normDet);
                                          if (!matches) {
                                            const subLabel = isSubPass ? 'Passport' : isSubAadh ? 'Aadhaar' : isSubPan ? 'PAN' : isSubDl ? 'Driving Licence' : docType;
                                            const detLabel = isDetPass ? 'Passport' : isDetAadh ? 'Aadhaar' : isDetPan ? 'PAN' : isDetDl ? 'Driving Licence' : det;
                                            return `Type mismatch — tab set to ${subLabel}, document detected as ${detLabel}. Analysing as ${detLabel}.`;
                                          }
                                        }
                                      }
                                      return null;
                                    })();

                    if (!warning) return null;
                    return (
                      <div className="p-4 rounded-xl border-2 border-amber-500/80 bg-amber-950/60 text-amber-200 flex items-start gap-3 shadow-lg mb-3">
                        <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                        <div className="space-y-0.5">
                          <div className="text-[10px] font-bold font-mono uppercase tracking-wider text-amber-300">
                            Document Classification Warning
                          </div>
                          <div className="text-sm font-semibold text-amber-100 font-mono">
                            {warning}
                          </div>
                        </div>
                      </div>
                    );
                  })()}

                  <Panel className="p-5 border border-[#232B38] bg-[#141A22]">
                    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
                      <div className="flex items-center gap-6">
                        <RiskGauge
                          score={scanResult.risk?.risk_score || 0}
                          tier={scanResult.risk?.risk_tier}
                          size="md"
                        />

                        <div className="space-y-1.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <Badge variant="neutral" size="sm">
                              Scan ID: {scanResult.scan_id?.slice(0, 8).toUpperCase() || 'LIVE'}
                            </Badge>
                            {(() => {
                              const timeMs = measuredProcessingTimeMs || scanResult._measured_processing_time_ms || scanResult.ocr?.timing_stats?.total_ocr_ms || scanResult.processing_time_ms;
                              if (!timeMs) return null;
                              return (
                                <Badge variant="neutral" size="sm" className="font-mono">
                                  ⏱ Processing: {timeMs}ms
                                </Badge>
                              );
                            })()}
                            <Badge
                              variant={
                                scanResult.risk?.risk_tier === 'CRITICAL' || scanResult.risk?.risk_tier === 'HIGH'
                                  ? 'critical'
                                  : scanResult.risk?.risk_tier === 'MEDIUM'
                                  ? 'warning'
                                  : 'success'
                              }
                              size="sm"
                            >
                              {scanResult.risk?.risk_tier}
                            </Badge>
                          </div>

                          <div className="text-base font-bold text-[#E4E7EB] font-sans">
                            {scanResult.risk?.operational_action?.replace(/_/g, ' ')}
                          </div>
                          <div className="text-xs text-[#8A93A3] font-sans leading-relaxed max-w-lg">
                            {scanResult.risk?.recommendation}
                          </div>
                        </div>
                      </div>

                      <div className="border-t sm:border-t-0 sm:border-l border-[#232B38] pt-4 sm:pt-0 sm:pl-6 text-right shrink-0">
                        <div className="text-[11px] font-mono uppercase text-[#8A93A3]">Security Clearance</div>
                        <div className={`text-sm font-bold font-mono mt-1 ${
                          scanResult.risk?.risk_tier === 'CRITICAL' || scanResult.risk?.risk_tier === 'HIGH'
                            ? 'text-[#E74C3C]'
                            : scanResult.risk?.risk_tier === 'MEDIUM'
                            ? 'text-[#D9A441]'
                            : 'text-[#4ADE80]'
                        }`}>
                          {scanResult.risk?.risk_tier === 'CRITICAL' || scanResult.risk?.risk_tier === 'HIGH'
                            ? 'INTERDICT'
                            : scanResult.risk?.risk_tier === 'MEDIUM'
                            ? 'MANUAL REVIEW'
                            : 'PRIMARY PASS'}
                        </div>
                      </div>
                    </div>
                  </Panel>
                </>
              ) : (
                <Panel className="p-8 text-center space-y-3 bg-[#10151C]">
                  <div className="w-12 h-12 border border-[#232B38] bg-[#0B0F14] flex items-center justify-center text-[#8A93A3] mx-auto">
                    <ShieldCheck className="w-6 h-6" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-[#E4E7EB] font-sans">Awaiting Document Upload</h3>
                    <p className="text-xs text-[#8A93A3] mt-1 max-w-md mx-auto font-mono">
                      Upload the traveler's document on the left and click <strong>"Screen & verify document"</strong> to run all 4 modules.
                    </p>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 max-w-lg mx-auto text-[11px] font-mono text-[#8A93A3]">
                    <div className="p-2 border border-[#232B38] bg-[#141A22]">1. Neural OCR</div>
                    <div className="p-2 border border-[#232B38] bg-[#141A22]">2. Rule Validation</div>
                    <div className="p-2 border border-[#232B38] bg-[#141A22]">3. ELA Forensics</div>
                    <div className="p-2 border border-[#232B38] bg-[#141A22]">4. Face Biometrics</div>
                  </div>
                </Panel>
              )}

              {/* Officer Decision Action Controls */}
              {scanResult && (
                <Panel className="p-4 flex flex-wrap items-center justify-between gap-3 bg-[#141A22]">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-[#8A93A3]">Officer Action:</span>
                    {officerDecision && (
                      <Badge
                        variant={
                          officerDecision === 'APPROVED' ? 'success' :
                          officerDecision === 'DETAINED' ? 'critical' :
                          'warning'
                        }
                        size="sm"
                      >
                        {officerDecision} RECORDED
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Button
                      size="sm"
                      variant={officerDecision === 'APPROVED' ? 'primary' : 'secondary'}
                      icon={CheckCircle2}
                      onClick={() => handleOfficerDecision('APPROVED')}
                    >
                      Approve Clearance
                    </Button>

                    <Button
                      size="sm"
                      variant={officerDecision === 'FLAGGED' ? 'primary' : 'secondary'}
                      icon={AlertTriangle}
                      onClick={() => handleOfficerDecision('FLAGGED')}
                    >
                      Flag Secondary
                    </Button>

                    <Button
                      size="sm"
                      variant="danger"
                      icon={ShieldAlert}
                      onClick={() => handleOfficerDecision('DETAINED')}
                    >
                      Detain / Reject
                    </Button>

                    <Button
                      size="sm"
                      variant="secondary"
                      icon={Printer}
                      onClick={() => setShowCertificateModal(true)}
                    >
                      Print Certificate
                    </Button>
                  </div>
                </Panel>
              )}

              {/* Risk Factor Breakdown (if any) */}
              {scanResult?.risk?.factors?.length > 0 && (
                <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-2.5">
                  <div className="text-xs font-semibold text-slate-200 flex items-center space-x-2">
                    <ShieldAlert className="w-4 h-4 text-rose-400" />
                    <span>Contributing risk factors:</span>
                  </div>
                  <div className="space-y-2">
                    {scanResult.risk.factors.map((f, idx) => (
                      <div key={idx} className="p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/90 flex items-start justify-between gap-3 text-xs">
                        <div>
                          <div className="flex items-center space-x-2">
                            <span className="font-bold text-slate-200">{f.title}</span>
                            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-slate-400">{f.category}</span>
                          </div>
                          <p className="text-slate-400 text-[11px] mt-0.5">{f.description}</p>
                        </div>
                        <span className="font-mono font-bold text-rose-400 shrink-0">+{f.points_added} pts</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Historical Mismatch Alert Banner (Requirement 4 & 5) */}
              {scanResult?.historical_check?.mismatches?.length > 0 && (
                <div className="p-4 rounded-2xl bg-rose-950/80 border-2 border-rose-500/90 text-rose-200 shadow-xl shadow-rose-950/50 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start space-x-2.5">
                      <ShieldAlert className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
                      <div>
                        <div className="text-xs font-bold text-rose-300 flex items-center space-x-2">
                          <span>Historical identity mismatch flagged</span>
                          <span className="px-2 py-0.2 rounded bg-rose-900 text-rose-200 text-[10px] border border-rose-600">CRITICAL</span>
                        </div>
                        <p className="text-xs text-rose-200/90 mt-1">
                          Discrepancies found comparing stable identity traits against prior border screenings.
                        </p>
                      </div>
                    </div>
                    {scanResult?.historical_check?.previous_record && (
                      <button
                        onClick={() => setShowPriorRecordModal(true)}
                        className="px-3 py-1.5 bg-rose-500 hover:bg-rose-400 text-slate-950 font-bold rounded-lg text-xs font-mono shrink-0 cursor-pointer flex items-center space-x-1.5 transition shadow-md shadow-rose-600/30"
                      >
                        <Eye className="w-3.5 h-3.5" />
                        <span>Compare past scan</span>
                      </button>
                    )}
                  </div>
                  <div className="space-y-1.5 pt-1">
                    {scanResult.historical_check.mismatches.map((m, idx) => (
                      <div key={idx} className="p-2.5 rounded-xl bg-black/50 border border-rose-600/50 text-xs font-mono flex items-center justify-between gap-2">
                        <span className="text-rose-200 font-semibold">{m.message}</span>
                        <span className="text-[10px] px-2 py-0.5 rounded bg-rose-900/80 text-rose-300 border border-rose-600 shrink-0">
                          {m.flag || "Mismatch"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Side-by-Side Visual vs MRZ Cross-Validation Table (Requirement 1 & 5) */}
              {scanResult?.validation?.field_cross_validation && Object.keys(scanResult.validation.field_cross_validation).length > 0 && (
                <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-bold text-slate-100 font-heading flex items-center space-x-2">
                        <FileCheck className="w-4 h-4 text-blue-400" />
                        <span>MRZ vs. Printed-Field Cross-Validation</span>
                      </h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Cross-referencing optical visual zone against cryptographically checksummed ICAO Machine Readable Zone.
                      </p>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 text-blue-400 border border-slate-800">
                      ICAO 9303 Cross-Audit
                    </span>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs font-mono">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-400 text-[11px]">
                          <th className="pb-2 font-semibold">Field</th>
                          <th className="pb-2 font-semibold">Printed visual</th>
                          <th className="pb-2 font-semibold">MRZ zone</th>
                          <th className="pb-2 font-semibold">MRZ checksum</th>
                          <th className="pb-2 font-semibold">Audit status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {Object.entries(scanResult.validation.field_cross_validation).map(([fKey, item]) => {
                          const isMismatch = item.flag === 'VISUAL_MRZ_Mismatch' || item.flag === 'VISUAL_MRZ_Mismatch_AND_CHECKSUM_INVALID';
                          const isChkFail = item.mrz_checksum_valid === false;
                          const ruleFired = item.flag || (item.match ? 'ICAO 9303 Optical MRZ Consistency Match' : 'Visual vs MRZ Cross-Validation Mismatch');
                          const threshold = `MRZ Check Digit: ${item.mrz_checksum_valid === true ? 'Valid (7-3-1 weight sum modulo 10)' : item.mrz_checksum_valid === false ? 'Check digit calculation failure' : 'Not Evaluated'}`;

                          return (
                            <tr key={fKey} className={`hover:bg-slate-900/40 ${isMismatch ? 'bg-rose-950/30' : ''}`}>
                              <td className="py-2.5 font-bold uppercase text-slate-300 align-top">
                                <div>{fKey.replace(/_/g, ' ')}</div>
                                <WhyExpander
                                  printedValue={item.visual_value || '—'}
                                  comparedValue={item.mrz_value || '—'}
                                  ruleFired={ruleFired}
                                  threshold={threshold}
                                  label="Why?"
                                />
                              </td>
                              <td className={`py-2.5 align-top ${isMismatch ? 'text-rose-400 font-bold underline decoration-rose-500' : 'text-slate-200'}`}>
                                {item.visual_value || '—'}
                              </td>
                              <td className="py-2.5 text-slate-300 font-medium align-top">
                                {item.mrz_value || '—'}
                              </td>
                              <td className="py-2.5 align-top">
                                {item.mrz_checksum_valid === true ? (
                                  <span className="text-emerald-400 font-semibold flex items-center space-x-1">
                                    <CheckCircle2 className="w-3.5 h-3.5" />
                                    <span>VALID</span>
                                  </span>
                                ) : item.mrz_checksum_valid === false ? (
                                  <span className="text-rose-400 font-semibold flex items-center space-x-1">
                                    <AlertCircle className="w-3.5 h-3.5" />
                                    <span>INVALID DIGIT</span>
                                  </span>
                                ) : (
                                  <span className="text-slate-500">N/A</span>
                                )}
                              </td>
                              <td className="py-2.5 align-top">
                                {isMismatch ? (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-600 animate-pulse">
                                    Printed forgery suspected
                                  </span>
                                ) : isChkFail ? (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-600">
                                    MRZ checksum CORRUPT
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-700/50">
                                    MATCH Verified ✓
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Module 1: Printed Fields & QR Evidence Panel */}
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 items-start">
                <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-bold text-slate-100 font-heading">
                        Module 1 — Extracted identity fields
                      </h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Extracted via PaddleOCR neural recognition. High-risk fields are verified against localized ELA and MRZ checksums.
                    </p>
                  </div>
                  {scanResult?.document_type && (
                    <span className="px-2.5 py-1 text-[11px] font-mono font-bold bg-[#161F2C] text-blue-400 rounded-lg border border-cyan-800">
                      Detected: {String(scanResult.document_type).replace(/_/g, ' ').toUpperCase()}
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {Object.keys(editableFields).length === 0 ? (
                    <div className="col-span-2 py-8 text-center text-slate-500 text-xs">
                      No document fields extracted yet. Upload a document and click Execute Screening.
                    </div>
                  ) : (
                    Object.entries(editableFields).map(([key, val]) => {
                      const crossVal = scanResult?.validation?.field_cross_validation?.[key];
                      const forensics = scanResult?.tampering?.field_forensics?.[key];
                      const histMismatch = scanResult?.historical_check?.mismatches?.find(m => m.field === key);
                      const isAltered = crossVal?.flag === 'VISUAL_MRZ_Mismatch' || crossVal?.flag === 'VISUAL_MRZ_Mismatch_AND_CHECKSUM_INVALID';
                      const isTampered = forensics?.likely_tampered;
                      const isFlagged = isAltered || isTampered || histMismatch;
                      const rawConf = scanResult?.ocr?.confidence_scores?.[key] ?? 0.95;

                      const ruleFired = crossVal?.flag || (isTampered ? 'Module 3: Localized ELA Forensics Anomaly' : histMismatch ? 'Cross-Scan Historical Continuity Inconsistency' : 'Document Field Validation Rule');
                      const threshold = isTampered
                        ? `ELA Anomaly Score: ${forensics?.ela_anomaly_score ?? 'N/A'} (threshold ≥ 0.50), Font Consistency: ${forensics?.font_consistency_score ?? 'N/A'} (threshold ≤ 0.50)`
                        : crossVal
                        ? `ICAO 9303 Checksum Valid: ${crossVal.mrz_checksum_valid ? 'Pass' : 'Fail'}`
                        : histMismatch
                        ? `Exact string match against prior screening record (Prior: "${histMismatch.prior_value}")`
                        : 'Format pattern compliance';

                      return (
                        <div 
                          key={key} 
                          className={`space-y-2 p-3 rounded-xl transition ${
                            isFlagged 
                              ? 'bg-rose-950/40 border-2 border-rose-500/80 shadow-lg shadow-rose-950/50 ring-1 ring-rose-500/50' 
                              : 'bg-slate-950/60 border border-slate-800'
                          }`}
                        >
                          <div className="flex items-center justify-between text-[10px] font-mono">
                            <span className={`uppercase font-bold ${isFlagged ? 'text-rose-300' : 'text-slate-400'}`}>
                              {key.replace(/_/g, ' ')}
                            </span>
                            
                            <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
                              <ConfidenceBadge confidence={rawConf} />
                              {isAltered && (
                                <span className="px-1.5 py-0.5 rounded bg-rose-500/30 text-rose-300 border border-rose-500/60 font-bold flex items-center space-x-1">
                                  <AlertTriangle className="w-3 h-3 text-rose-400" />
                                  <span>VISUAL != MRZ</span>
                                </span>
                              )}
                              {isTampered && (
                                <Badge variant="critical" size="sm" icon={Sparkles}>
                                  LOCAL ELA ANOMALY
                                </Badge>
                              )}
                              {histMismatch && (
                                <Badge variant="warning" size="sm">
                                  PRIOR SCAN Mismatch
                                </Badge>
                              )}
                              <ConfidenceBar
                                value={Math.round((scanResult?.ocr?.confidence_scores?.[key] || 0.95) * 100)}
                                size="xs"
                              />
                            </div>
                          </div>

                          {val === 'not applicable for this document type' ? (
                            <div className="w-full rounded-lg px-2.5 py-1.5 text-xs font-mono italic text-slate-400 bg-slate-900/60 border border-slate-800 flex items-center justify-between">
                              <span>not applicable for this document type</span>
                              <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 uppercase font-sans font-semibold">N/A</span>
                            </div>
                          ) : (
                            <input
                              type="text"
                              value={val}
                              onChange={(e) => setEditableFields(prev => ({ ...prev, [key]: e.target.value }))}
                              className={`w-full rounded-lg px-2.5 py-1.5 text-xs font-medium focus:outline-none ${
                                isFlagged
                                  ? 'bg-black/60 border-2 border-rose-500/80 text-rose-100 font-bold'
                                  : 'bg-slate-900 border border-slate-700/80 text-slate-100 focus:border-cyan-500'
                              }`}
                            />
                          )}

                          {/* PART 3: "Why" Expander for flagged fields */}
                          {isFlagged && (
                            <WhyExpander
                              printedValue={crossVal?.visual_value || val || '—'}
                              comparedValue={crossVal?.mrz_value || scanResult?.qr_verification?.decoded_fields?.[key] || (histMismatch ? histMismatch.prior_value : 'N/A')}
                              ruleFired={ruleFired}
                              threshold={threshold}
                              label="Why was this flagged?"
                              defaultOpen={true}
                            />
                          )}

                          {/* Localized ELA Heatmap Crop (Requirement 2 & 5) */}
                          {forensics?.crop_ela_heatmap_b64 && (
                            <div className="pt-2 border-t border-slate-800/80 flex items-center space-x-3">
                              <div className="relative rounded overflow-hidden border border-rose-500/60 bg-black shrink-0 w-24 h-10 flex items-center justify-center">
                                <img 
                                  src={forensics.crop_ela_heatmap_b64} 
                                  alt={`${key} localized ELA heatmap`} 
                                  className="max-h-full max-w-full object-contain" 
                                />
                              </div>
                              <div className="text-[10px] font-mono space-y-0.5">
                                <div className="text-slate-300 flex items-center space-x-1">
                                  <span>Region ELA Anomaly:</span>
                                  <span className={forensics.ela_anomaly_score >= 0.5 ? "text-rose-400 font-black" : "text-emerald-400 font-bold"}>
                                    {forensics.ela_anomaly_score}
                                  </span>
                                </div>
                                <div className="text-slate-400 flex items-center space-x-1">
                                  <span>Font Consistency:</span>
                                  <span className={forensics.font_consistency_score <= 0.5 ? "text-amber-400 font-bold" : "text-slate-300"}>
                                    {forensics.font_consistency_score}
                                  </span>
                                </div>
                                {forensics.likely_tampered && (
                                  <span className="text-rose-400 text-[9px] font-bold block">
                                    ★ Localized digital splicing detected
                                  </span>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* QR Evidence Panel rendered beside printed fields */}
              <QREvidencePanel
                scanResult={scanResult}
                printedFields={editableFields}
              />
            </div>


              {/* Module 2: Validation Checklist */}
              {(() => {
                const detType = (
                  scanResult?.ocr?.document_subtype ||
                  scanResult?.ocr?.detected_document_subtype ||
                  scanResult?.document_type ||
                  ''
                ).toLowerCase();

                const isPass = detType.includes('passport');
                const isAadh = detType.includes('aadhaar');
                const isPan = detType.includes('pan');
                const isDl = detType.includes('driving') || detType.includes('dl') || detType.includes('license') || detType.includes('licence');

                const checksums = scanResult?.checksum_validation || scanResult?.ocr?.checksum_validation || {};
                const details = scanResult?.validation?.details || {};
                const qr_data_res = scanResult?.qr_verification || details?.qr_verification || {};

                return (
                  <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-bold text-slate-100 font-heading">
                        Module 2 — Document standard validation checklist
                      </h3>
                      {detType && (
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-700/50 text-cyan-300 font-semibold uppercase">
                          Detected Standard: {formatDocTypeBadge(detType)}
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                      {isPass ? (
                        <>
                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">MRZ check digits (ICAO 9303)</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                checksums.mrz_checksum_valid === true || details.checksum_valid === true
                                  ? 'text-emerald-400'
                                  : (checksums.mrz_checksum_valid === false || details.checksum_valid === false)
                                    ? 'text-rose-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  (checksums.mrz_checksum_valid === true || details.checksum_valid === true)
                                    ? 'Valid (Passed)'
                                    : (checksums.mrz_checksum_valid === false || details.checksum_valid === false)
                                      ? 'Invalid Checksum'
                                      : 'Not Evaluated'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.passport_number || scanResult.document_number || '—'}
                                comparedValue={scanResult.ocr?.mrz_parsed?.passport_number || 'ICAO 9303 TD3 Zone'}
                                ruleFired={checksums.mrz_checksum_valid === false ? 'MRZ_CHECKSUM_INVALID' : 'ICAO 9303 Modulo 10 Check Digits'}
                                threshold="7-3-1 weight sum modulo 10 on doc number, DOB, and expiry"
                              />
                            )}
                          </div>

                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">Nationality validation</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                details.nationality_valid === true
                                  ? 'text-emerald-400'
                                  : details.nationality_valid === false
                                    ? 'text-rose-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  details.nationality_valid === true
                                    ? 'ICAO Compliant'
                                    : details.nationality_valid === false
                                      ? 'Unrecognized code'
                                      : 'Not Evaluated'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.nationality || '—'}
                                comparedValue={scanResult.ocr?.mrz_parsed?.nationality || 'ISO 3166-1 Table'}
                                ruleFired={details.nationality_valid === false ? 'UNRECOGNIZED_NATIONALITY_CODE' : 'ISO 3166-1 Alpha-3 Compliance'}
                                threshold="Must match valid 3-letter ICAO/ISO country code"
                              />
                            )}
                          </div>

                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">ICAO TD3 format layout</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                checksums.icao_format_valid === true
                                  ? 'text-emerald-400'
                                  : checksums.icao_format_valid === false
                                    ? 'text-rose-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  checksums.icao_format_valid === true
                                    ? 'Valid (2×44 TD3)'
                                    : checksums.icao_format_valid === false
                                      ? 'Non-standard layout'
                                      : 'Not Evaluated'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue="TD3 Geometry (88mm × 125mm)"
                                comparedValue="2 lines × 44 chars MRZ"
                                ruleFired={checksums.icao_format_valid === false ? 'NON_STANDARD_TD3_LAYOUT' : 'Doc 9303 Part 4 Specification'}
                                threshold="Exactly 2 lines of 44 uppercase characters with valid filler characters"
                              />
                            )}
                          </div>

                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">Document expiry check</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                scanResult?.validation?.is_expired === true
                                  ? 'text-rose-400'
                                  : scanResult?.validation?.is_expired === false
                                    ? 'text-emerald-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  scanResult?.validation?.is_expired === true
                                    ? 'Expired'
                                    : scanResult?.validation?.is_expired === false
                                      ? 'VALID / UNExpired'
                                      : 'Not Evaluated'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.expiry_date || '—'}
                                comparedValue={`Current date: ${new Date().toISOString().slice(0, 10)}`}
                                ruleFired={scanResult?.validation?.is_expired ? 'DOCUMENT_EXPIRED' : 'Document Validity Horizon'}
                                threshold="Document expiration date > Current checkpoint date"
                              />
                            )}
                          </div>
                        </>
                      ) : isAadh ? (
                        <>
                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">Verhoeff checksum (12-digit UID)</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                checksums.aadhaar_verhoeff_valid === true || checksums.aadhaar_checksum_valid === true
                                  ? 'text-emerald-400'
                                  : (checksums.aadhaar_verhoeff_valid === false || checksums.aadhaar_checksum_valid === false)
                                    ? 'text-rose-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  (checksums.aadhaar_verhoeff_valid === true || checksums.aadhaar_checksum_valid === true)
                                    ? 'Passed (Verhoeff D8)'
                                    : (checksums.aadhaar_verhoeff_valid === false || checksums.aadhaar_checksum_valid === false)
                                      ? 'Checksum Failed'
                                      : 'Not Evaluated (No Aadhaar number detected)'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.aadhaar_number || scanResult.document_number || '—'}
                                comparedValue="Verhoeff D8 Dihedral Permutation"
                                ruleFired={checksums.aadhaar_verhoeff_valid === false ? 'VERHOEFF_CHECKSUM_INVALID' : 'UIDAI 12-Digit Verhoeff Validation'}
                                threshold="Multiplication over dihedral group D5: d(c, p(i, n)) == 0"
                              />
                            )}
                          </div>

                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">UIDAI QR code verification</span>
                              {(() => {
                                if (!scanResult) {
                                  return <span className="font-mono text-[11px] text-slate-400 italic">Pending</span>;
                                }
                                const isTampered = checksums.uidai_qr_verified === false || checksums.qr_verification === false || qr_data_res?.outcome === 'TAMPERED';
                                const isSigPassed = (checksums.uidai_qr_verified === true || qr_data_res?.signature_verified === true) && qr_data_res?.signature_status === 'PASSED';
                                const isDecodedUnverified = (checksums.uidai_qr_verified === true || qr_data_res?.qr_found || qr_data_res?.raw_payload || qr_data_res?.outcome === 'VERIFIED') && !isSigPassed;

                                if (isTampered) {
                                  return <span className="font-mono text-[11px] font-bold text-rose-400">QR Mismatch / Tampered</span>;
                                }
                                if (isSigPassed) {
                                  return <span className="font-mono text-[11px] font-bold text-emerald-400">Verified QR Data (RSA-2048)</span>;
                                }
                                if (isDecodedUnverified) {
                                  return <span className="font-mono text-[11px] font-bold text-slate-300">QR decoded, signature unverified</span>;
                                }
                                return <span className="font-mono text-[11px] font-bold text-slate-400 italic">Not Evaluated</span>;
                              })()}
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.name || editableFields.aadhaar_number || '—'}
                                comparedValue={qr_data_res?.decoded_fields?.name || qr_data_res?.raw_payload || 'Decoded QR Stream'}
                                ruleFired={qr_data_res?.outcome === 'TAMPERED' ? 'QR_MISMATCH_TAMPERED' : 'UIDAI Secure QR Verification'}
                                threshold="RSA-2048 cryptographic signature & visual field correspondence"
                              />
                            )}
                          </div>

                          <div className="py-2 px-3 rounded bg-[#11161F] border border-[#252D3B] flex items-center justify-between">
                            <span className="text-[#8A93A3]">Document expiry check</span>
                            <span className="font-mono text-[11px] text-slate-400 italic">
                              not applicable for this document type
                            </span>
                          </div>

                          <div className="py-2 px-3 rounded bg-[#11161F] border border-[#252D3B] flex items-center justify-between">
                            <span className="text-[#8A93A3]">MRZ check digits</span>
                            <span className="font-mono text-[11px] text-slate-400 italic">
                              not applicable for this document type
                            </span>
                          </div>
                        </>
                      ) : isPan ? (
                        <>
                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">PAN format validation</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                checksums.pan_format_valid === true
                                  ? 'text-emerald-400'
                                  : checksums.pan_format_valid === false
                                    ? 'text-rose-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  checksums.pan_format_valid === true
                                    ? 'Valid (AAAAA9999A)'
                                    : checksums.pan_format_valid === false
                                      ? 'Invalid Format'
                                      : 'Not Evaluated'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.pan_number || scanResult.document_number || '—'}
                                comparedValue="Format Standard: ^[A-Z]{5}[0-9]{4}[A-Z]$"
                                ruleFired={checksums.pan_format_valid === false ? 'INVALID_PAN_FORMAT' : 'Income Tax Dept Format Rule'}
                                threshold="5 letters (4th status, 5th surname) + 4 digits + 1 check letter"
                              />
                            )}
                          </div>

                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">5th-character surname match</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                checksums.pan_surname_match === true
                                  ? 'text-emerald-400'
                                  : checksums.pan_surname_match === false
                                    ? 'text-rose-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  checksums.pan_surname_match === true
                                    ? 'Matches Surname Initial'
                                    : checksums.pan_surname_match === false
                                      ? 'Mismatch Surname Initial'
                                      : 'Not Evaluated (Holder name unextracted)'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={`Surname: ${editableFields.surname || editableFields.name || '—'}`}
                                comparedValue={`5th PAN character: ${editableFields.pan_number?.[4] || '—'}`}
                                ruleFired={checksums.pan_surname_match === false ? 'PAN_SURNAME_INITIAL_MISMATCH' : 'PAN 5th Character Holder Initial Rule'}
                                threshold="5th character of PAN must match initial of holder surname"
                              />
                            )}
                          </div>

                          <div className="py-2 px-3 rounded bg-[#11161F] border border-[#252D3B] flex items-center justify-between">
                            <span className="text-[#8A93A3]">Document expiry check</span>
                            <span className="font-mono text-[11px] text-slate-400 italic">
                              not applicable for this document type
                            </span>
                          </div>

                          <div className="py-2 px-3 rounded bg-[#11161F] border border-[#252D3B] flex items-center justify-between">
                            <span className="text-[#8A93A3]">MRZ check digits</span>
                            <span className="font-mono text-[11px] text-slate-400 italic">
                              not applicable for this document type
                            </span>
                          </div>
                        </>
                      ) : isDl ? (
                        <>
                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">State RTO format validation</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                checksums.dl_format_valid === true || checksums.rto_format_valid === true
                                  ? 'text-emerald-400'
                                  : (checksums.dl_format_valid === false || checksums.rto_format_valid === false)
                                    ? 'text-rose-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  (checksums.dl_format_valid === true || checksums.rto_format_valid === true)
                                    ? 'Valid State RTO Code'
                                    : (checksums.dl_format_valid === false || checksums.rto_format_valid === false)
                                      ? 'Invalid RTO Format'
                                      : 'Not Evaluated'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.dl_number || scanResult.document_number || '—'}
                                comparedValue="MoRTH Standard DL Specification"
                                ruleFired={checksums.dl_format_valid === false ? 'INVALID_DL_FORMAT' : 'MoRTH DL Syntax Verification'}
                                threshold="2-letter state code + 2-digit RTO + 4-digit year + 7-digit unique number"
                              />
                            )}
                          </div>

                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">Licence expiry check</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                scanResult?.validation?.is_expired === true
                                  ? 'text-rose-400'
                                  : scanResult?.validation?.is_expired === false
                                    ? 'text-emerald-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  scanResult?.validation?.is_expired === true
                                    ? 'Expired'
                                    : scanResult?.validation?.is_expired === false
                                      ? 'VALID / UNExpired'
                                      : 'Not Evaluated'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.expiry_date || '—'}
                                comparedValue={`Current date: ${new Date().toISOString().slice(0, 10)}`}
                                ruleFired={scanResult?.validation?.is_expired ? 'LICENCE_EXPIRED' : 'Licence Validity Period'}
                                threshold="Licence expiration date > Current checkpoint date"
                              />
                            )}
                          </div>

                          <div className="py-2 px-3 rounded bg-[#11161F] border border-[#252D3B] flex items-center justify-between">
                            <span className="text-[#8A93A3]">MRZ check digits</span>
                            <span className="font-mono text-[11px] text-slate-400 italic">
                              not applicable for this document type
                            </span>
                          </div>

                          <div className="py-2 px-3 rounded bg-[#11161F] border border-[#252D3B] flex items-center justify-between">
                            <span className="text-[#8A93A3]">Nationality validation</span>
                            <span className="font-mono text-[11px] text-slate-400 italic">
                              not applicable for this document type
                            </span>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">Document expiry check</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                scanResult?.validation?.is_expired === true
                                  ? 'text-rose-400'
                                  : scanResult?.validation?.is_expired === false
                                    ? 'text-emerald-400'
                                    : 'text-slate-400 italic'
                              }`}>
                                {scanResult ? (
                                  scanResult?.validation?.is_expired === true
                                    ? 'Expired'
                                    : scanResult?.validation?.is_expired === false
                                      ? 'VALID / UNExpired'
                                      : 'Not Evaluated'
                                ) : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={editableFields.expiry_date || '—'}
                                comparedValue={`Current date: ${new Date().toISOString().slice(0, 10)}`}
                                ruleFired={scanResult?.validation?.is_expired ? 'DOCUMENT_EXPIRED' : 'Document Validity Horizon'}
                                threshold="Document expiration date > Current checkpoint date"
                              />
                            )}
                          </div>

                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">Format & checksum algorithm</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                scanResult ? 'text-emerald-400' : 'text-slate-500'
                              }`}>
                                {scanResult ? 'Valid standard format' : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={scanResult.document_type || 'Document structure'}
                                comparedValue="National Registry Standard Format"
                                ruleFired="Standard Document Layout Compliance"
                                threshold="Format meets national regulatory specification"
                              />
                            )}
                          </div>

                          <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[#E4E7EB] font-medium">Logical date coherence (DOB/issue)</span>
                              <span className={`font-mono text-[11px] font-bold ${
                                scanResult ? 'text-emerald-400' : 'text-slate-500'
                              }`}>
                                {scanResult ? 'Coherent' : 'Pending'}
                              </span>
                            </div>
                            {scanResult && (
                              <WhyExpander
                                printedValue={`DOB: ${editableFields.dob || editableFields.date_of_birth || '—'}`}
                                comparedValue={`Issue: ${editableFields.issue_date || '—'}`}
                                ruleFired="Date Chronology & Coherence Verification"
                                threshold="Birth Date < Issue Date < Expiry Date"
                              />
                            )}
                          </div>
                        </>
                      )}

                      {/* Watchlist & sanctions database always runs for all documents */}
                      <div className="p-2.5 rounded bg-[#11161F] border border-[#252D3B] space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-[#E4E7EB] font-medium">Watchlist & sanctions database</span>
                          <span className={`font-mono text-[11px] font-bold ${
                            scanResult?.validation?.is_blacklisted === true
                              ? 'text-rose-400'
                              : scanResult?.validation?.is_blacklisted === false
                                ? 'text-emerald-400'
                                : 'text-slate-400 italic'
                          }`}>
                            {scanResult ? (
                              scanResult?.validation?.is_blacklisted === true
                                ? 'Security hit'
                                : scanResult?.validation?.is_blacklisted === false
                                  ? 'Clear'
                                  : 'Not Evaluated'
                            ) : 'Pending'}
                          </span>
                        </div>
                        {scanResult && (
                          <WhyExpander
                            printedValue={`${editableFields.name || scanResult.holder_name || ''} | ${scanResult.document_number || ''}`}
                            comparedValue="Watchlist Index (Interpol / Sanctions List)"
                            ruleFired={scanResult.validation?.is_blacklisted ? 'SECURITY_WATCHLIST_MATCH' : 'Watchlist Screening Verification'}
                            threshold="Exact match on watchlist token sets, document numbers, or person of interest"
                          />
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* Verification Coverage Panel (Below Module 2) */}
              {(() => {
                const completedDocs = sessionDocuments.filter(d => d.status === 'completed');
                const completedCount = completedDocs.length;
                const hasPassport = completedDocs.some(d => d.type === 'passport');
                const hasVisa = completedDocs.some(d => d.type === 'visa');

                const coverageLevel = completedCount === 0 ? 'none' : completedCount === 1 ? 'partial' : 'strong';
                const coverageBadgeVariant = completedCount === 0 ? 'neutral' : completedCount === 1 ? 'warning' : 'success';

                const coverageChecks = [
                  {
                    id: 'ela_tamper',
                    name: 'Tampering & ELA image forensics',
                    isActive: completedCount >= 1,
                    unavailableReason: 'unavailable (screen at least 1 document)'
                  },
                  {
                    id: 'format_checksum',
                    name: 'Format & checksum algorithms (ICAO / Verhoeff)',
                    isActive: completedCount >= 1,
                    unavailableReason: 'unavailable (screen at least 1 document)'
                  },
                  {
                    id: 'watchlist_interpol',
                    name: 'Interpol & sanctions watchlist screening',
                    isActive: completedCount >= 1,
                    unavailableReason: 'unavailable (screen at least 1 document)'
                  },
                  {
                    id: 'date_coherence',
                    name: 'Logical date validity & expiry check',
                    isActive: completedCount >= 1,
                    unavailableReason: 'unavailable (screen at least 1 document)'
                  },
                  {
                    id: 'cross_dob',
                    name: 'Cross-document DOB consistency',
                    isActive: completedCount >= 2,
                    unavailableReason: 'unavailable (add Visa or National ID)'
                  },
                  {
                    id: 'passport_visa_link',
                    name: 'Passport–visa number linkage',
                    isActive: hasPassport && hasVisa,
                    unavailableReason: !hasPassport ? 'unavailable (add Passport)' : 'unavailable (add Visa)'
                  },
                  {
                    id: 'cross_name',
                    name: 'Cross-document name & identity consistency',
                    isActive: completedCount >= 2,
                    unavailableReason: 'unavailable (add Visa or National ID)'
                  },
                  {
                    id: 'cross_nationality',
                    name: 'Cross-document nationality consistency',
                    isActive: completedCount >= 2,
                    unavailableReason: 'unavailable (add Visa or National ID)'
                  },
                  {
                    id: 'biometric_cross',
                    name: 'Multi-document facial cross-matching',
                    isActive: completedCount >= 2,
                    unavailableReason: 'unavailable (add second photo document)'
                  }
                ];

                const activeCount = coverageChecks.filter(c => c.isActive).length;
                const totalCount = coverageChecks.length;
                const coveragePct = Math.round((activeCount / totalCount) * 100);

                return (
                  <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center space-x-2">
                        <ShieldCheck className="w-4 h-4 text-cyan-400" />
                        <h3 className="text-sm font-bold text-slate-100 font-heading">
                          Verification coverage
                        </h3>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-mono text-slate-400">
                          {activeCount} of {totalCount} checks run ({coveragePct}%)
                        </span>
                        <Badge variant={coverageBadgeVariant} size="sm">
                          Coverage: {coverageLevel}
                        </Badge>
                      </div>
                    </div>

                    <div className="w-full bg-slate-950 rounded-full h-1.5 overflow-hidden border border-slate-800">
                      <div
                        className={`h-1.5 rounded-full transition-all duration-300 ${
                          coverageLevel === 'strong'
                            ? 'bg-emerald-400'
                            : coverageLevel === 'partial'
                            ? 'bg-[#D9A441]'
                            : 'bg-slate-700'
                        }`}
                        style={{ width: `${coveragePct}%` }}
                      />
                    </div>

                    <p className="text-[11px] text-slate-400 font-mono">
                      Checks run vs checks possible for current document set. Multi-document checks activate automatically as corroborating documents are screened.
                    </p>

                    <div className="space-y-1.5 text-xs">
                      {coverageChecks.map((chk) => (
                        <div
                          key={chk.id}
                          className={`py-2 px-3 rounded flex items-center justify-between gap-3 border transition-colors ${
                            chk.isActive
                              ? 'bg-[#11161F] border-[#252D3B]'
                              : 'bg-[#0B0F14]/70 border-[#1B222D]'
                          }`}
                        >
                          <div className="flex items-center space-x-2 min-w-0">
                            {chk.isActive ? (
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                            ) : (
                              <span className="w-3.5 h-3.5 rounded-full border border-slate-600 flex items-center justify-center text-[9px] text-slate-500 shrink-0">
                                ○
                              </span>
                            )}
                            <span className={`font-sans truncate ${chk.isActive ? 'text-slate-200' : 'text-slate-400'}`}>
                              {chk.name}
                              {!chk.isActive && (
                                <span className="text-amber-400/90 font-mono text-[11px] ml-1.5 font-medium">
                                  — {chk.unavailableReason}
                                </span>
                              )}
                            </span>
                          </div>

                          <div className="shrink-0">
                            {chk.isActive ? (
                              <span className="font-mono text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-800/80">
                                Active
                              </span>
                            ) : (
                              <span className="font-mono text-[10px] font-medium px-2 py-0.5 rounded bg-[#161B22] text-slate-500 border border-slate-800">
                                Inactive
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}

              {/* Module 4: Biometrics & S-MAD Morph Analysis Card */}
              <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-slate-100 font-heading flex items-center space-x-2">
                    <Camera className="w-4 h-4 text-cyan-400" />
                    <span>Module 4 — Biometrics & Face Photo Analysis</span>
                  </h3>
                  <button
                    onClick={() => setActiveWorkspaceTab('biometrics')}
                    className="text-xs text-cyan-400 hover:text-cyan-300 font-medium flex items-center space-x-1 cursor-pointer"
                  >
                    <span>Open Camera / Inspector</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs">
                  {/* Row 1: Face Match */}
                  <div className="p-3 rounded-xl bg-[#11161F] border border-[#252D3B] space-y-1">
                    <span className="text-slate-400 text-[10px] uppercase tracking-wider font-bold">1. Face Match</span>
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm font-bold text-slate-200">
                        {scanResult?.biometrics ? `${Math.round((scanResult.biometrics.confidence || 0) * 100)}%` : 'Pending'}
                      </span>
                      <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        scanResult?.biometrics?.match ? 'bg-emerald-950 text-emerald-300 border border-emerald-700' : scanResult?.biometrics ? 'bg-rose-950 text-rose-300 border border-rose-700' : 'bg-slate-900 text-slate-500'
                      }`}>
                        {scanResult?.biometrics?.match ? 'PASS' : scanResult?.biometrics ? 'FAIL' : 'PENDING'}
                      </span>
                    </div>
                  </div>

                  {/* Row 2: Liveness */}
                  <div className="p-3 rounded-xl bg-[#11161F] border border-[#252D3B] space-y-1">
                    <span className="text-slate-400 text-[10px] uppercase tracking-wider font-bold">2. Liveness Detection</span>
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm font-bold text-slate-200">
                        {scanResult?.biometrics ? (scanResult.biometrics.liveness_passed ? 'Verified' : 'Failed') : 'Pending'}
                      </span>
                      <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        scanResult?.biometrics?.liveness_passed ? 'bg-emerald-950 text-emerald-300 border border-emerald-700' : scanResult?.biometrics ? 'bg-rose-950 text-rose-300 border border-rose-700' : 'bg-slate-900 text-slate-500'
                      }`}>
                        {scanResult?.biometrics ? (scanResult.biometrics.liveness_passed ? 'CONFIRMED' : 'SPOOF') : 'PENDING'}
                      </span>
                    </div>
                  </div>

                  {/* Row 3: Morph Suspicion */}
                  <div className="p-3 rounded-xl bg-[#11161F] border border-[#252D3B] space-y-1">
                    <span className="text-slate-400 text-[10px] uppercase tracking-wider font-bold">3. S-MAD Morph Suspicion</span>
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm font-bold text-slate-200">
                        {scanResult?.biometrics?.morph_analysis
                          ? `${scanResult.biometrics.morph_analysis.suspicion_tier.replace('_', ' ')} (${Math.round(scanResult.biometrics.morph_analysis.morph_suspicion_score * 100)}%)`
                          : (scanResult ? 'Normal (0%)' : 'Pending')}
                      </span>
                      <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        scanResult?.biometrics?.morph_analysis?.is_morph_suspected
                          ? (scanResult.biometrics.morph_analysis.suspicion_tier === 'HIGH_SUSPICION' ? 'bg-rose-900 text-rose-200 border border-rose-700' : 'bg-amber-900 text-amber-200 border border-amber-700')
                          : scanResult ? 'bg-emerald-950 text-emerald-300 border border-emerald-700' : 'bg-slate-900 text-slate-500'
                      }`}>
                        {scanResult?.biometrics?.morph_analysis?.is_morph_suspected ? 'SUSPECTED' : scanResult ? 'CLEAN' : 'PENDING'}
                      </span>
                    </div>
                  </div>
                </div>

                {scanResult?.biometrics?.morph_analysis?.is_morph_suspected && (
                  <div className="p-2.5 rounded-xl bg-amber-950/40 border border-amber-800/80 text-xs text-amber-200 flex items-start space-x-2">
                    <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-bold">Face-Morphing Attack Indicators:</span>{' '}
                      {scanResult.biometrics.morph_analysis.morph_flags?.map(f => f.replace(/_/g, ' ').toUpperCase()).join(' • ') || 'Sub-region blend anomalies'}
                    </div>
                  </div>
                )}
              </div>
              </>
              )}
            </div>
          )}

          {/* Subview 2: Forensic Inspector & ELA */}
          {activeWorkspaceTab === 'forensics' && (
            <ForensicInspector 
              selectedDoc={null}
              tamperingResult={scanResult?.tampering}
              originalImage={frontFileObj || imagePreview}
              soundEnabled={soundEnabled}
            />
          )}

          {/* Subview 3: Biometric Face Scanner */}
          {activeWorkspaceTab === 'biometrics' && (
            <LiveFaceScanner 
              selectedDoc={null}
              originalImage={frontFileObj || imagePreview}
              selfieImage={selfiePreview}
              onSelfieChange={(file, url) => {
                setSelfieFileObj(file);
                setSelfiePreview(url);
                setSelfieFileName(file.name || 'camera_selfie.jpg');
              }}
              onVerificationComplete={(bioResult) => {
                if (scanResult) {
                  setScanResult(prev => ({
                    ...prev,
                    biometrics: bioResult
                  }));
                }
              }}
              soundEnabled={soundEnabled}
            />
          )}
        </div>
      </div>

      {/* Printable Certificate Modal */}
      {showCertificateModal && (
        <ReportModal 
          scanResult={scanResult}
          doc={null}
          onClose={() => setShowCertificateModal(false)}
        />
      )}

      {/* Historical Record Comparison Modal (Requirement 4 & 5) */}
      {showPriorRecordModal && scanResult?.historical_check?.previous_record && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
          <div className="bg-slate-900 border border-rose-600/60 rounded-2xl max-w-2xl w-full p-6 space-y-5 shadow-2xl shadow-rose-950/50 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2">
                <ShieldAlert className="w-5 h-5 text-rose-400" />
                <h3 className="text-sm font-bold text-slate-100 font-heading">
                  Historical Screening Audit Comparison
                </h3>
              </div>
              <button 
                onClick={() => setShowPriorRecordModal(false)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs font-mono">
              <div className="grid grid-cols-2 gap-3 p-3 bg-slate-950/80 rounded-xl border border-slate-800">
                <div>
                  <div className="text-[10px] text-slate-400 uppercase font-bold">Current Screening</div>
                  <div className="text-blue-400 font-bold mt-0.5">Scan ID: {scanResult.scan_id || 'LIVE'}</div>
                  <div className="text-slate-300 text-[11px] mt-0.5">Holder: {scanResult.holder_name || '—'}</div>
                  <div className="text-slate-400 text-[10px]">Doc: {scanResult.document_number || '—'}</div>
                </div>
                <div>
                  <div className="text-[10px] text-rose-400 uppercase font-bold">Previous Screening on Record</div>
                  <div className="text-rose-300 font-bold mt-0.5">Scan ID: {scanResult.historical_check.previous_record.id}</div>
                  <div className="text-slate-300 text-[11px] mt-0.5">Date: {scanResult.historical_check.previous_record.timestamp?.slice(0, 10) || 'N/A'}</div>
                  <div className="text-slate-400 text-[10px]">Doc: {scanResult.historical_check.previous_record.document_number || '—'}</div>
                </div>
              </div>

              <div className="space-y-2">
                <div className="text-[11px] font-bold text-slate-200">Conflicting Identity fields:</div>
                {scanResult.historical_check.mismatches?.map((m, idx) => (
                  <div key={idx} className="p-3 rounded-xl bg-rose-950/40 border border-rose-600/60 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-rose-300 uppercase">{m.field?.replace(/_/g, ' ')}</span>
                      <span className="text-[10px] px-2 py-0.5 bg-rose-900 text-rose-200 rounded border border-rose-700 font-bold">Mismatch</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-[11px] pt-1">
                      <div>Current Scan: <span className="text-white font-bold underline">{m.current_value}</span></div>
                      <div>Prior Scan: <span className="text-rose-300 font-bold underline">{m.historical_value}</span></div>
                    </div>
                    <p className="text-[10px] text-slate-400 pt-0.5">{m.message}</p>
                  </div>
                ))}
              </div>

              {scanResult.historical_check.previous_record.fields && (
                <div className="space-y-1.5 pt-2">
                  <div className="text-[11px] font-bold text-slate-300">All Fields from Historical Record:</div>
                  <div className="grid grid-cols-2 gap-2 p-2.5 bg-slate-950 rounded-xl border border-slate-800 text-[10px]">
                    {Object.entries(scanResult.historical_check.previous_record.fields).map(([k, v]) => (
                      <div key={k} className="flex items-center justify-between border-b border-slate-900 pb-1">
                        <span className="text-slate-400 uppercase">{k.replace(/_/g, ' ')}:</span>
                        <span className="text-slate-200 font-semibold">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setShowPriorRecordModal(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-medium cursor-pointer"
              >
                Close Comparison
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Unsaved Screening Data Confirmation Modal */}
      {showUnsavedConfirmModal && (
        <div 
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in"
          role="dialog"
          aria-modal="true"
          aria-labelledby="unsaved-modal-title"
        >
          <div className="bg-[#141A22] border border-[#D9A441]/50 rounded-[6px] max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-[4px] bg-[#D9A441]/10 border border-[#D9A441]/40 flex items-center justify-center text-[#D9A441] shrink-0">
                <AlertTriangle className="w-6 h-6" aria-hidden="true" />
              </div>
              <div className="space-y-1">
                <h3 id="unsaved-modal-title" className="text-sm font-bold text-[#E4E7EB] font-sans">
                  Unsaved Screening Data
                </h3>
                <p className="text-xs text-[#E4E7EB] leading-relaxed">
                  Current session has unsaved screening data. Start a new check-in?
                </p>
                <p className="text-[11px] text-[#8A93A3] font-mono mt-1">
                  You have {sessionDocuments.filter(d => d.status === 'completed').length} processed document(s) in session <span className="text-[#D9A441] font-semibold">{currentSessionId}</span> without generating an archived report.
                </p>
              </div>
            </div>

            <div className="p-3 bg-[#0B0F14] rounded-[4px] border border-[#232B38] text-[11px] text-[#8A93A3] font-mono">
              Continuing will record this session as <span className="text-[#EF4444] font-bold">DISCARDED</span> in the audit trail and wipe all active traveler data from memory.
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowUnsavedConfirmModal(false)}
              >
                Cancel
              </Button>
              <Button
                variant="critical"
                size="sm"
                onClick={handleConfirmDiscard}
              >
                Discard and continue
              </Button>
            </div>
          </div>
        </div>
      )}
      {/* High-Resolution Document Optical Scanner Modal */}
      {isDocCameraOpen && (
        <div 
          className="fixed inset-0 z-50 bg-[#0B0F14]/90 backdrop-blur-md flex items-center justify-center p-3 sm:p-6 overflow-y-auto animate-in fade-in"
          role="dialog"
          aria-modal="true"
        >
          <div className="bg-[#141A22] border border-[#232B38] w-full max-w-4xl p-5 space-y-4 rounded-[6px] shadow-2xl text-[#E4E7EB]">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-[#232B38] pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-[4px] bg-[#D9A441]/10 border border-[#D9A441]/40 flex items-center justify-center text-[#D9A441]">
                  <Camera className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-[#E4E7EB] font-sans flex items-center gap-2">
                    <span>High-Resolution Document Optical Scanner</span>
                    <Badge variant="warning" size="sm" className="font-mono">
                      {docCameraTarget === 'front' ? 'Primary Front' : 'Reverse Side'}
                    </Badge>
                  </h3>
                  <p className="text-[11px] text-[#8A93A3] font-mono mt-0.5">
                    Sensor Capture: {docSensorRes || '1080p+ Full Resolution'} · Auto Focus & Live Quality Gate
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                {/* Live Quality Indicator: Green "Ready", Amber "Hold steady", Red "Too blurry / too dark" */}
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[4px] font-mono text-xs font-bold uppercase tracking-wider ${
                  docQuality.status === 'GREEN'
                    ? 'bg-[#3F9868]/15 text-[#4ADE80] border border-[#3F9868]/40'
                    : docQuality.status === 'AMBER'
                    ? 'bg-[#D9A441]/15 text-[#D9A441] border border-[#D9A441]/40'
                    : 'bg-[#C0392B]/15 text-[#E74C3C] border border-[#C0392B]/40'
                }`}>
                  <span className={`w-2 h-2 rounded-full ${
                    docQuality.status === 'GREEN' ? 'bg-[#4ADE80]' : docQuality.status === 'AMBER' ? 'bg-[#D9A441]' : 'bg-[#E74C3C]'
                  }`} />
                  <span>{docQuality.label}</span>
                </span>

                <button
                  type="button"
                  onClick={stopDocCamera}
                  aria-label="Close document camera"
                  className="p-1.5 text-[#8A93A3] hover:text-[#E4E7EB] border border-[#232B38] bg-[#0B0F14] rounded-[4px] cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Error / Rejection Banner */}
            {docCaptureError && (
              <div className="p-3 bg-red-950/60 border border-red-500/60 rounded-[4px] text-red-300 text-xs font-mono flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 text-red-400" />
                <span>{docCaptureError}</span>
              </div>
            )}

            {/* Viewport with Guide Frame Overlay */}
            <div className="relative aspect-[16/10] bg-black rounded-[4px] overflow-hidden border border-[#232B38] flex items-center justify-center">
              <video
                ref={(el) => {
                  docVideoRef.current = el;
                  if (el && docStreamRef.current && el.srcObject !== docStreamRef.current) {
                    el.srcObject = docStreamRef.current;
                    el.play().catch(err => console.warn("Doc video play error:", err));
                  }
                }}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover"
              />

              {/* Document Guide Frame Overlay (ID-1 / ID-3 Ratio ~1.58:1) */}
              <div className="absolute inset-0 pointer-events-none flex items-center justify-center p-4">
                <div className={`relative w-[90%] sm:w-[75%] aspect-[1.58/1] rounded-lg border-2 transition-all duration-300 ${
                  docQuality.status === 'GREEN'
                    ? 'border-[#4ADE80] shadow-[0_0_25px_rgba(74,222,128,0.35)]'
                    : docQuality.status === 'AMBER'
                    ? 'border-[#D9A441] shadow-[0_0_20px_rgba(217,164,65,0.25)]'
                    : 'border-[#E74C3C] shadow-[0_0_20px_rgba(231,76,60,0.25)]'
                }`}>
                  {/* 4 Corner Reticles */}
                  <div className="absolute -top-1 -left-1 w-6 h-6 border-t-4 border-l-4 border-inherit rounded-tl-md" />
                  <div className="absolute -top-1 -right-1 w-6 h-6 border-t-4 border-r-4 border-inherit rounded-tr-md" />
                  <div className="absolute -bottom-1 -left-1 w-6 h-6 border-b-4 border-l-4 border-inherit rounded-bl-md" />
                  <div className="absolute -bottom-1 -right-1 w-6 h-6 border-b-4 border-r-4 border-inherit rounded-br-md" />

                  {/* Guide Frame Alignment Guidance & Framing Hint */}
                  <div className="absolute inset-0 flex flex-col items-center justify-between p-3">
                    <span className="text-[10px] font-mono font-bold tracking-wider px-2 py-0.5 rounded bg-black/70 backdrop-blur-xs text-[#E4E7EB]">
                      FIT DOCUMENT IN RECTANGLE
                    </span>

                    {/* Hint when edges are far inside the guide frame ("Move closer") */}
                    {docQuality.hint === 'Move closer' && (
                      <div className="px-3 py-1 rounded bg-[#D9A441] text-slate-950 font-bold text-xs font-mono animate-bounce flex items-center gap-1.5 shadow-lg">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        <span>Move closer — fill the guide frame with card</span>
                      </div>
                    )}

                    <span className="text-[10px] font-mono text-[#8A93A3] bg-black/70 px-2 py-0.5 rounded">
                      Passport Bio Page / Aadhaar / PAN / Driving License
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Diagnostic Metrics & Threshold Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 p-2.5 bg-[#0B0F14] border border-[#232B38] rounded-[4px] text-xs font-mono">
              <div className="flex items-center gap-4 text-[11px]">
                <div className="flex items-center gap-1.5">
                  <span className="text-[#8A93A3]">Sharpness (Laplacian):</span>
                  <span className={`font-bold ${docQuality.sharpness >= 90 ? 'text-[#4ADE80]' : docQuality.sharpness >= 50 ? 'text-[#D9A441]' : 'text-[#E74C3C]'}`}>
                    {docQuality.sharpness}
                  </span>
                  <span className="text-[10px] text-[#5A6578]">(Min 50, Target 90+)</span>
                </div>

                <div className="flex items-center gap-1.5">
                  <span className="text-[#8A93A3]">Mean Brightness:</span>
                  <span className={`font-bold ${docQuality.brightness >= 55 && docQuality.brightness <= 225 ? 'text-[#4ADE80]' : 'text-[#E74C3C]'}`}>
                    {docQuality.brightness}
                  </span>
                  <span className="text-[10px] text-[#5A6578]">(55-225 optimal)</span>
                </div>
              </div>

              <div className="text-[10px] text-[#8A93A3]">
                {docQuality.status === 'RED' ? (
                  <span className="text-[#E74C3C] font-semibold">Capture blocked until document is in focus</span>
                ) : (
                  <span className="text-[#4ADE80] font-semibold">Quality verified — ready for full sensor capture</span>
                )}
              </div>
            </div>

            {/* Controls Bar */}
            <div className="flex items-center justify-between pt-2 border-t border-[#232B38]">
              <span className="text-[10px] text-[#5A6578] font-mono">
                1080p+ Full Sensor Capture · Forensic Clarity Guaranteed
              </span>

              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={stopDocCamera}
                >
                  Cancel
                </Button>

                {/* Capture button disabled when quality is RED */}
                <Button
                  type="button"
                  variant={docQuality.status === 'RED' ? 'secondary' : 'primary'}
                  size="sm"
                  icon={Camera}
                  disabled={docQuality.status === 'RED'}
                  onClick={captureDocFrame}
                  title={docQuality.status === 'RED' ? "Stabilize document within guide frame to enable capture" : "Capture document"}
                  className="font-mono uppercase font-bold text-xs"
                >
                  Capture Document
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

