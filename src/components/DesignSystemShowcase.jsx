import React, { useState } from 'react';
import {
  Button,
  Badge,
  Panel,
  PanelHeader,
  PanelBody,
  Tabs,
  DataTable,
  ConfidenceBar,
  RiskGauge,
  FileDropzone,
  Toast,
  StatusDot,
} from './ui';
import {
  Shield,
  FileText,
  AlertTriangle,
  CheckCircle2,
  Trash2,
  Download,
  Search,
  Scan,
  Zap,
  Activity,
  Layers,
  ArrowRight,
} from 'lucide-react';

export function DesignSystemShowcase({ onBackToScreening }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [showLoadingBtn, setShowLoadingBtn] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [toastMessage, setToastMessage] = useState('Document successfully verified against MHA database.');
  const [toastVariant, setToastVariant] = useState('success');

  const demoTabs = [
    { id: 'overview', label: 'Overview Console', icon: Layers, badge: '4' },
    { id: 'forensics', label: 'ELA Forensics', icon: Scan, badge: 'Active' },
    { id: 'biometrics', label: 'Face Biometrics', icon: Zap },
    { id: 'audit', label: 'Audit Trail', icon: Activity },
  ];

  const demoTableColumns = [
    { key: 'id', label: 'Scan ID', sortable: true, render: (v) => <span className="font-mono font-bold text-[#D9A441]">{v}</span> },
    { key: 'timestamp', label: 'Timestamp (UTC)', sortable: true, render: (v) => <span className="font-mono text-[11px] text-[#8A93A3]">{v}</span> },
    { key: 'docType', label: 'Document Type', sortable: true, render: (v) => <span className="capitalize">{v}</span> },
    { key: 'holder', label: 'Passenger / Holder', sortable: true },
    { key: 'tier', label: 'Risk Tier', sortable: true, render: (v) => {
        const variant = v === 'CRITICAL' || v === 'HIGH' ? 'critical' : v === 'MEDIUM' ? 'warning' : 'success';
        return <Badge variant={variant} size="sm">{v}</Badge>;
      }
    },
    { key: 'confidence', label: 'OCR Confidence', sortable: true, render: (v) => <ConfidenceBar value={v} /> },
  ];

  const demoTableData = [
    { id: 'SCN-9021', timestamp: '2026-09-12 04:12:08', docType: 'passport', holder: 'Thada Aryan', tier: 'LOW', confidence: 97 },
    { id: 'SCN-9022', timestamp: '2026-09-12 04:18:22', docType: 'national_id_pan', holder: 'Kaja Vardhan', tier: 'LOW', confidence: 92 },
    { id: 'SCN-9023', timestamp: '2026-09-12 04:22:45', docType: 'visa', holder: 'Srija Reddy', tier: 'MEDIUM', confidence: 78 },
    { id: 'SCN-9024', timestamp: '2026-09-12 04:31:10', docType: 'passport', holder: 'Vikram Singh', tier: 'CRITICAL', confidence: 44 },
  ];

  return (
    <div className="space-y-8 max-w-7xl mx-auto py-6 px-4 sm:px-6">
      {/* Top Banner */}
      <div className="border border-[#232B38] bg-[#141A22] p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-[#D9A441] text-[#0B0F14] flex items-center justify-center font-bold font-mono rounded-[4px]">
              SA
            </div>
            <div>
              <h1 className="text-lg font-bold text-[#E4E7EB] font-sans tracking-tight">
                SentinelAuth Design System Showcase
              </h1>
              <p className="text-xs font-mono text-[#8A93A3] mt-0.5">
                Console Operations Palette | IBM Plex Sans + Mono | Breakpoint Verified
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Badge variant="warning" size="md">ISO/IEC 30107-4</Badge>
          <StatusDot status="ready" label="Design Tokens Active" pulse />
          {onBackToScreening && (
            <Button size="sm" variant="secondary" onClick={onBackToScreening}>
              Return to Console
            </Button>
          )}
        </div>
      </div>

      {/* 1. Color Palette Tokens */}
      <Panel title="Design Tokens: Colors & Surfaces" icon={Layers}>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          <div className="border border-[#232B38] bg-[#0B0F14] p-3 text-center">
            <div className="w-full h-8 bg-[#0B0F14] border border-[#232B38] mb-2" />
            <span className="block text-[11px] font-mono font-bold text-[#E4E7EB]">--void</span>
            <span className="block text-[10px] font-mono text-[#8A93A3]">#0B0F14</span>
          </div>

          <div className="border border-[#232B38] bg-[#141A22] p-3 text-center">
            <div className="w-full h-8 bg-[#141A22] border border-[#232B38] mb-2" />
            <span className="block text-[11px] font-mono font-bold text-[#E4E7EB]">--panel</span>
            <span className="block text-[10px] font-mono text-[#8A93A3]">#141A22</span>
          </div>

          <div className="border border-[#232B38] bg-[#141A22] p-3 text-center">
            <div className="w-full h-8 bg-[#232B38] mb-2" />
            <span className="block text-[11px] font-mono font-bold text-[#E4E7EB]">--panel-border</span>
            <span className="block text-[10px] font-mono text-[#8A93A3]">#232B38</span>
          </div>

          <div className="border border-[#232B38] bg-[#141A22] p-3 text-center">
            <div className="w-full h-8 bg-[#D9A441] mb-2 rounded-[4px]" />
            <span className="block text-[11px] font-mono font-bold text-[#D9A441]">--signal-amber</span>
            <span className="block text-[10px] font-mono text-[#8A93A3]">#D9A441</span>
          </div>

          <div className="border border-[#232B38] bg-[#141A22] p-3 text-center">
            <div className="w-full h-8 bg-[#C0392B] mb-2 rounded-[4px]" />
            <span className="block text-[11px] font-mono font-bold text-[#E74C3C]">--alert-red</span>
            <span className="block text-[10px] font-mono text-[#8A93A3]">#C0392B</span>
          </div>

          <div className="border border-[#232B38] bg-[#141A22] p-3 text-center">
            <div className="w-full h-8 bg-[#3F9868] mb-2 rounded-[4px]" />
            <span className="block text-[11px] font-mono font-bold text-[#4ADE80]">--verified-green</span>
            <span className="block text-[10px] font-mono text-[#8A93A3]">#3F9868</span>
          </div>

          <div className="border border-[#232B38] bg-[#141A22] p-3 text-center">
            <div className="w-full h-8 bg-[#E4E7EB] mb-2" />
            <span className="block text-[11px] font-mono font-bold text-[#E4E7EB]">--ink</span>
            <span className="block text-[10px] font-mono text-[#8A93A3]">#E4E7EB</span>
          </div>

          <div className="border border-[#232B38] bg-[#141A22] p-3 text-center">
            <div className="w-full h-8 bg-[#8A93A3] mb-2" />
            <span className="block text-[11px] font-mono font-bold text-[#8A93A3]">--ink-muted</span>
            <span className="block text-[10px] font-mono text-[#8A93A3]">#8A93A3</span>
          </div>
        </div>
      </Panel>

      {/* 2. Button Component */}
      <Panel title="Component: Button (Variants, Sizes, Loading, Focus Ring)" icon={Zap}>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary">Primary Action</Button>
            <Button variant="secondary">Secondary Outline</Button>
            <Button variant="danger" icon={Trash2}>Danger Destructive</Button>
            <Button variant="ghost">Ghost Neutral</Button>
            <Button
              variant="primary"
              isLoading={showLoadingBtn}
              onClick={() => {
                setShowLoadingBtn(true);
                setTimeout(() => setShowLoadingBtn(false), 2000);
              }}
            >
              {showLoadingBtn ? 'Processing' : 'Click for Loading State'}
            </Button>
            <Button variant="primary" disabled>Disabled State</Button>
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-[#232B38]">
            <span className="text-xs font-mono text-[#8A93A3] mr-2">Sizes:</span>
            <Button size="sm" variant="secondary">Size: sm (h-8)</Button>
            <Button size="md" variant="secondary">Size: md (h-10)</Button>
            <Button size="lg" variant="primary">Size: lg (h-12)</Button>
          </div>
        </div>
      </Panel>

      {/* 3. Badge & StatusDot */}
      <Panel title="Component: Badge & StatusDot" icon={Activity}>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Badge variant="neutral">Neutral Tag</Badge>
            <Badge variant="warning" icon={AlertTriangle}>Warning Flag</Badge>
            <Badge variant="critical">Critical Anomaly</Badge>
            <Badge variant="success" icon={CheckCircle2}>Verified</Badge>
          </div>

          <div className="h-6 border-r border-[#232B38]" />

          <div className="flex items-center gap-4">
            <StatusDot status="ready" label="OCR Ready" />
            <StatusDot status="processing" label="S-MAD Analyzing" pulse />
            <StatusDot status="error" label="Connection Failed" />
            <StatusDot status="offline" label="Camera Standby" />
          </div>
        </div>
      </Panel>

      {/* 4. Tabs Component */}
      <Panel title="Component: Tabs (Underline Indicator & Mobile Pill Row)" icon={Layers}>
        <Tabs tabs={demoTabs} activeTab={activeTab} onChange={setActiveTab} />
        <div className="mt-4 p-4 border border-[#232B38] bg-[#10151C] text-xs font-mono text-[#8A93A3]">
          Active Tab Selected: <span className="font-bold text-[#D9A441]">{activeTab}</span>
        </div>
      </Panel>

      {/* 5. RiskGauge & ConfidenceBar */}
      <Panel title="Components: RiskGauge & ConfidenceBar" icon={Shield}>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 items-center">
          <div className="border border-[#232B38] p-4 flex flex-col items-center bg-[#10151C]">
            <span className="text-xs font-mono text-[#8A93A3] mb-2">LOW RISK (12/100)</span>
            <RiskGauge score={12} tier="LOW" size="md" />
          </div>

          <div className="border border-[#232B38] p-4 flex flex-col items-center bg-[#10151C]">
            <span className="text-xs font-mono text-[#8A93A3] mb-2">ELEVATED (42/100)</span>
            <RiskGauge score={42} tier="MEDIUM" size="md" />
          </div>

          <div className="border border-[#232B38] p-4 flex flex-col items-center bg-[#10151C]">
            <span className="text-xs font-mono text-[#8A93A3] mb-2">HIGH RISK (74/100)</span>
            <RiskGauge score={74} tier="HIGH" size="md" />
          </div>

          <div className="border border-[#232B38] p-4 flex flex-col items-center bg-[#10151C]">
            <span className="text-xs font-mono text-[#8A93A3] mb-2">CRITICAL (92/100)</span>
            <RiskGauge score={92} tier="CRITICAL" size="md" />
          </div>
        </div>

        <div className="mt-6 pt-4 border-t border-[#232B38] flex flex-wrap items-center gap-6">
          <div className="space-y-1">
            <span className="text-[11px] font-mono text-[#8A93A3] block">Field Confidence High (&gt;=85%):</span>
            <ConfidenceBar value={96} />
          </div>
          <div className="space-y-1">
            <span className="text-[11px] font-mono text-[#8A93A3] block">Field Confidence Medium (60-84%):</span>
            <ConfidenceBar value={71} />
          </div>
          <div className="space-y-1">
            <span className="text-[11px] font-mono text-[#8A93A3] block">Field Confidence Low (&lt;60%):</span>
            <ConfidenceBar value={38} />
          </div>
        </div>
      </Panel>

      {/* 6. FileDropzone */}
      <Panel title="Component: FileDropzone (Drag & Drop, Preview, Clear)" icon={FileText}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <FileDropzone
            id="showcase-front-doc"
            label="Front Document Photo (Empty State)"
            hint="Click to browse or drop passport, Aadhaar, or PAN card"
            onFileSelect={(file) => setSelectedFile(file)}
          />

          <FileDropzone
            id="showcase-sample-doc"
            label="Document With Selected State"
            file={{ name: 'official_passport_sample.png', size: 1420500 }}
            previewUrl="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='70' viewBox='0 0 100 70'><rect width='100' height='70' fill='%23141A22'/><text x='50' y='40' font-family='monospace' font-size='10' fill='%23D9A441' text-anchor='middle'>PASSPORT</text></svg>"
            onFileSelect={() => {}}
            onClear={() => {}}
          />
        </div>
      </Panel>

      {/* 7. DataTable with Responsive Mobile Stacked Cards */}
      <Panel
        title="Component: DataTable (Sortable Desktop & Tablet | Stacked Cards on Mobile <640px)"
        icon={Activity}
      >
        <p className="text-xs text-[#8A93A3] mb-3 font-mono">
          Resize the window below 640px to see the table automatically transform into accessible stacked cards.
        </p>
        <DataTable columns={demoTableColumns} data={demoTableData} keyField="id" />
      </Panel>

      {/* 8. Toast / Alert */}
      <Panel title="Component: Toast / Alert (Transient & Static Notices)" icon={AlertTriangle}>
        <div className="space-y-3">
          <Toast
            variant="success"
            title="Biometric Clearance Verified"
            message="Facial match confirmed against passport document with 94.2% confidence. Liveness passed."
            onClose={() => {}}
          />
          <Toast
            variant="warning"
            title="Anthropometric Skew Detected"
            message="S-MAD flagged 0.344 suspicion tier on document photo due to duplicate boundary contour correlation."
            onClose={() => {}}
          />
          <Toast
            variant="critical"
            title="Interpol SLTD Watchlist Match"
            message="Traveler matches Wanted Persons list (Reference #INT-2026-9901). Immediate secondary inspection required."
            onClose={() => {}}
          />
        </div>
      </Panel>
    </div>
  );
}

export default DesignSystemShowcase;
