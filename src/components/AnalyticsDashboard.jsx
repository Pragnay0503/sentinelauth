import React, { useState, useEffect } from 'react';
import { 
  Activity, 
  Clock, 
  ShieldCheck, 
  CheckCircle2, 
  Zap, 
  Info, 
  Layers, 
  FileCheck, 
  AlertTriangle, 
  TrendingUp, 
  Cpu, 
  BarChart3,
  RefreshCw
} from 'lucide-react';
import { Panel, PanelHeader, PanelBody, Button, Badge, StatusDot } from './ui';

export function AnalyticsDashboard() {
  const [stats, setStats] = useState({
    total_scans: 0,
    flagged_scans: 0,
    passed_scans: 0,
    avg_risk_score: 0.0,
    pass_rate_pct: 100.0,
    tiers_breakdown: { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 }
  });
  const [isLoading, setIsLoading] = useState(false);

  const fetchStats = async () => {
    setIsLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/audit/stats');
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch (err) {
      console.error("Failed to load audit stats:", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <Panel className="p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-[#D9A441]" aria-hidden="true" />
            <h2 className="text-base font-bold text-[#E4E7EB] font-sans">
              Border Screening Operational Intelligence & Metrics
            </h2>
          </div>
          <p className="text-xs text-[#8A93A3] mt-1 font-mono">
            Real-time checkpoint statistics, risk tier distributions, and AI module performance telemetry.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <StatusDot status="ready" label="Metrics Telemetry Active" pulse />
          <Button
            size="sm"
            variant="secondary"
            icon={RefreshCw}
            isLoading={isLoading}
            onClick={fetchStats}
          >
            Refresh
          </Button>
        </div>
      </Panel>

      {/* 4 Live Metric Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Panel className="p-4 bg-[#141A22]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]">
              Total Credentials Screened
            </span>
            <div className="p-1.5 border border-[#232B38] bg-[#0B0F14] text-[#D9A441]">
              <FileCheck className="w-4 h-4" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold font-mono text-[#E4E7EB]">
              {stats.total_scans.toLocaleString()}
            </span>
            <span className="text-[11px] text-[#4ADE80] font-mono block mt-1">
              +100% database persistence
            </span>
          </div>
        </Panel>

        <Panel className="p-4 bg-[#141A22]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]">
              Pass Rate (Cleared)
            </span>
            <div className="p-1.5 border border-[#232B38] bg-[#0B0F14] text-[#3F9868]">
              <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold font-mono text-[#4ADE80]">
              {stats.pass_rate_pct.toFixed(1)}%
            </span>
            <span className="text-[11px] text-[#8A93A3] font-mono block mt-1">
              {stats.passed_scans} documents cleared
            </span>
          </div>
        </Panel>

        <Panel className="p-4 bg-[#141A22]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]">
              Flagged / Interdicted
            </span>
            <div className="p-1.5 border border-[#232B38] bg-[#0B0F14] text-[#C0392B]">
              <AlertTriangle className="w-4 h-4" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold font-mono text-[#E74C3C]">
              {stats.flagged_scans}
            </span>
            <span className="text-[11px] text-[#E74C3C] font-mono block mt-1">
              High risk or watchlist matches
            </span>
          </div>
        </Panel>

        <Panel className="p-4 bg-[#141A22]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]">
              Average Risk Score
            </span>
            <div className="p-1.5 border border-[#232B38] bg-[#0B0F14] text-[#D9A441]">
              <TrendingUp className="w-4 h-4" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold font-mono text-[#E4E7EB]">
              {stats.avg_risk_score.toFixed(1)}
              <span className="text-xs text-[#8A93A3] font-normal font-sans ml-1">/100</span>
            </span>
            <span className="text-[11px] text-[#D9A441] font-mono block mt-1">
              Calibrated baseline
            </span>
          </div>
        </Panel>
      </div>

      {/* Risk Tier Distributions & Engine Status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Risk Tier Breakdown */}
        <Panel title="Checkpoint Risk Tier Breakdown" icon={BarChart3}>
          <div className="space-y-4">
            <p className="text-xs text-[#8A93A3] font-mono">
              Distribution of screened credentials across MHA security enforcement risk classifications.
            </p>

            <div className="space-y-3">
              <div>
                <div className="flex items-center justify-between text-xs font-mono mb-1">
                  <span className="text-[#4ADE80] font-bold">LOW RISK (Cleared)</span>
                  <span className="text-[#E4E7EB] font-bold">{stats.tiers_breakdown?.LOW || 0}</span>
                </div>
                <div className="h-2 w-full bg-[#0B0F14] border border-[#232B38] overflow-hidden">
                  <div
                    className="h-full bg-[#3F9868]"
                    style={{
                      width: `${stats.total_scans > 0 ? ((stats.tiers_breakdown?.LOW || 0) / stats.total_scans) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between text-xs font-mono mb-1">
                  <span className="text-[#D9A441] font-bold">MEDIUM (Secondary Review)</span>
                  <span className="text-[#E4E7EB] font-bold">{stats.tiers_breakdown?.MEDIUM || 0}</span>
                </div>
                <div className="h-2 w-full bg-[#0B0F14] border border-[#232B38] overflow-hidden">
                  <div
                    className="h-full bg-[#D9A441]"
                    style={{
                      width: `${stats.total_scans > 0 ? ((stats.tiers_breakdown?.MEDIUM || 0) / stats.total_scans) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between text-xs font-mono mb-1">
                  <span className="text-[#FB923C] font-bold">HIGH RISK (Elevated Suspicion)</span>
                  <span className="text-[#E4E7EB] font-bold">{stats.tiers_breakdown?.HIGH || 0}</span>
                </div>
                <div className="h-2 w-full bg-[#0B0F14] border border-[#232B38] overflow-hidden">
                  <div
                    className="h-full bg-[#E67E22]"
                    style={{
                      width: `${stats.total_scans > 0 ? ((stats.tiers_breakdown?.HIGH || 0) / stats.total_scans) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between text-xs font-mono mb-1">
                  <span className="text-[#E74C3C] font-bold">CRITICAL (Interdiction / Detained)</span>
                  <span className="text-[#E4E7EB] font-bold">{stats.tiers_breakdown?.CRITICAL || 0}</span>
                </div>
                <div className="h-2 w-full bg-[#0B0F14] border border-[#232B38] overflow-hidden">
                  <div
                    className="h-full bg-[#C0392B]"
                    style={{
                      width: `${stats.total_scans > 0 ? ((stats.tiers_breakdown?.CRITICAL || 0) / stats.total_scans) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        </Panel>

        {/* AI & Forensic Subsystem Telemetry */}
        <Panel title="Subsystem Health & Model Architecture" icon={Cpu}>
          <div className="space-y-4 text-xs font-mono">
            <div className="flex items-center justify-between p-2.5 border border-[#232B38] bg-[#10151C]">
              <div>
                <span className="font-bold text-[#E4E7EB] block">Primary Neural OCR Pipeline</span>
                <span className="text-[11px] text-[#8A93A3]">PaddleOCR Mobile + EasyOCR Fallback</span>
              </div>
              <Badge variant="success" size="sm">Online</Badge>
            </div>

            <div className="flex items-center justify-between p-2.5 border border-[#232B38] bg-[#10151C]">
              <div>
                <span className="font-bold text-[#E4E7EB] block">Biometric Face Verification</span>
                <span className="text-[11px] text-[#8A93A3]">YuNet (5-pt Landmark) + SFace (Cosine)</span>
              </div>
              <Badge variant="success" size="sm">Active</Badge>
            </div>

            <div className="flex items-center justify-between p-2.5 border border-[#232B38] bg-[#10151C]">
              <div>
                <span className="font-bold text-[#E4E7EB] block">Single-Image Morph Attack Detection (S-MAD)</span>
                <span className="text-[11px] text-[#8A93A3]">4-Signal Micro-texture + FFT Discontinuity</span>
              </div>
              <Badge variant="warning" size="sm">Calibrated</Badge>
            </div>

            <div className="flex items-center justify-between p-2.5 border border-[#232B38] bg-[#10151C]">
              <div>
                <span className="font-bold text-[#E4E7EB] block">Error Level Analysis (ELA Forensics)</span>
                <span className="text-[11px] text-[#8A93A3]">DCT JPEG Resave Compression Variance</span>
              </div>
              <Badge variant="success" size="sm">Active</Badge>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

export default AnalyticsDashboard;
