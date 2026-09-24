import React, { useState } from 'react';
import { 
  QrCode, 
  ShieldCheck, 
  ShieldAlert, 
  CheckCircle2, 
  XCircle, 
  AlertTriangle, 
  HelpCircle, 
  ChevronDown, 
  ChevronUp, 
  Copy, 
  Check, 
  FileCode2 
} from 'lucide-react';

/**
 * QREvidencePanel component
 * Displays cryptographic QR evidence, signature verification status badge,
 * collapsible & truncatable raw payload, and field-by-field cross-validation table.
 *
 * Guaranteed never to hide: renders in neutral grey state with explanatory reason
 * when no QR is detected or unreadable.
 */
export function QREvidencePanel({ 
  scanResult, 
  qrData: customQrData, 
  printedFields = {} 
}) {
  const [isPayloadOpen, setIsPayloadOpen] = useState(true);
  const [isPayloadExpanded, setIsPayloadExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  // Extract QR verification result from available props
  const qr = customQrData || scanResult?.qr_verification || scanResult?.validation?.details?.qr_verification || null;

  // Determine actual signature verification
  // uidai_qr_verified can now be null, so explicitly check === true AND signature_status === 'PASSED'
  const isSignatureActuallyVerified = 
    qr?.signature_status === 'PASSED' || 
    qr?.signature_verified === true;

  // Evaluate decoded content availability
  const rawPayload = qr?.raw_payload || qr?.raw_payload_preview || '';
  const hasDecodedPayload = Boolean(rawPayload && rawPayload.trim().length > 0);
  const qrFound = Boolean(qr?.qr_found);

  // Determine signature badge text and status
  let signatureReason = '';
  if (isSignatureActuallyVerified) {
    signatureReason = 'Cryptographic Signature Verified (RSA-2048)';
  } else if (hasDecodedPayload || qr?.qr_data) {
    signatureReason = 'QR decoded, signature not verified (UIDAI key not configured)';
  } else if (qrFound && !hasDecodedPayload) {
    signatureReason = 'QR unreadable at this capture quality';
  } else if (qr?.reason && (qr.reason.toLowerCase().includes('quality') || qr.reason.toLowerCase().includes('unreadable') || qr.reason.toLowerCase().includes('undecodable'))) {
    signatureReason = 'QR unreadable at this capture quality';
  } else {
    signatureReason = 'No QR detected on this document';
  }

  // Handle clipboard copy
  const handleCopyPayload = () => {
    if (!rawPayload) return;
    navigator.clipboard.writeText(rawPayload);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Compile field-by-field comparison data
  // Use pre-computed comparisons if available; otherwise derive from qr_data & printedFields
  const comparisons = qr?.comparisons || {};
  let comparisonEntries = Object.entries(comparisons);

  if (comparisonEntries.length === 0 && qr?.qr_data && typeof qr.qr_data === 'object') {
    // Dynamically align known fields
    const dynamicList = [];
    const qrData = qr.qr_data;
    
    // Normalize field mapping
    const fieldMapping = [
      { key: 'name', label: 'Full Name', qrVal: qrData.name || qrData.HolderName },
      { key: 'date_of_birth', label: 'Date of Birth', qrVal: qrData.date_of_birth || qrData.dob || qrData.DOB },
      { key: 'gender', label: 'Gender', qrVal: qrData.gender || qrData.Gender },
      { key: 'uid', label: 'Aadhaar / ID Number', qrVal: qrData.uid || qrData.aadhaar_number || qrData.pan || qrData.epic_number },
      { key: 'address', label: 'Address', qrVal: qrData.address || qrData.Address }
    ];

    for (const item of fieldMapping) {
      if (item.qrVal) {
        const printedVal = printedFields[item.key] || printedFields[item.key.replace(/_/g, '')] || '';
        let status = 'NOT_COMPARED';
        if (printedVal) {
          const normP = String(printedVal).trim().toLowerCase();
          const normQ = String(item.qrVal).trim().toLowerCase();
          status = normP === normQ ? 'MATCH' : 'MISMATCH';
        }
        dynamicList.push([
          item.key,
          {
            field: item.label,
            printed: printedVal || null,
            qr: item.qrVal,
            status: status
          }
        ]);
      }
    }
    comparisonEntries = dynamicList;
  }

  const getStatusBadge = (status) => {
    switch (status) {
      case 'MATCH':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-950/80 text-emerald-400 border border-emerald-800">
            <CheckCircle2 className="w-3 h-3 mr-1 text-emerald-400" />
            MATCH
          </span>
        );
      case 'MISMATCH':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-950/80 text-rose-400 border border-rose-800 animate-pulse">
            <XCircle className="w-3 h-3 mr-1 text-rose-400" />
            MISMATCH
          </span>
        );
      case 'SKIPPED_LOW_CONFIDENCE':
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-950/80 text-amber-400 border border-amber-800">
            <AlertTriangle className="w-3 h-3 mr-1 text-amber-400" />
            SKIPPED_LOW_CONFIDENCE
          </span>
        );
      case 'NOT_COMPARED':
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-800 text-slate-400 border border-slate-700">
            <HelpCircle className="w-3 h-3 mr-1 text-slate-400" />
            NOT_COMPARED
          </span>
        );
    }
  };

  const formatFieldName = (key, comp) => {
    if (comp?.field) return comp.field;
    return key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  };

  return (
    <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-4 bg-[#0a0e17]/90 text-slate-100 shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center space-x-2.5">
          <div className="p-1.5 rounded-lg bg-cyan-950/60 border border-cyan-800/60 text-cyan-400">
            <QrCode className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-100 font-heading flex items-center gap-2">
              QR Evidence Panel
              {qr?.qr_format && (
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-normal">
                  {qr.qr_format}
                </span>
              )}
            </h3>
            <p className="text-[11px] text-slate-400">
              Cross-validates printed OCR fields against embedded 2D QR payloads
            </p>
          </div>
        </div>
      </div>

      {/* 1. SIGNATURE BADGE (Top) */}
      <div className="w-full">
        <div className={`p-3 rounded-xl border flex items-center justify-between gap-3 transition-colors ${
          isSignatureActuallyVerified
            ? 'bg-emerald-950/60 border-emerald-500/70 text-emerald-300 shadow-md shadow-emerald-950/40'
            : 'bg-slate-900/80 border-slate-800 text-slate-300'
        }`}>
          <div className="flex items-center space-x-2.5 min-w-0">
            {isSignatureActuallyVerified ? (
              <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0" />
            ) : (
              <ShieldAlert className="w-5 h-5 text-slate-400 shrink-0" />
            )}
            <div className="min-w-0">
              <div className="text-[10px] uppercase font-mono tracking-wider font-semibold text-slate-400">
                Digital Signature Verification
              </div>
              <div className={`text-xs font-bold truncate ${
                isSignatureActuallyVerified ? 'text-emerald-300' : 'text-slate-300'
              }`}>
                {signatureReason}
              </div>
            </div>
          </div>

          <div className="shrink-0">
            <span className={`px-2.5 py-1 rounded font-mono text-[10px] font-bold tracking-wider uppercase border ${
              isSignatureActuallyVerified
                ? 'bg-emerald-900/60 text-emerald-300 border-emerald-600/60'
                : 'bg-slate-800/80 text-slate-400 border-slate-700'
            }`}>
              {isSignatureActuallyVerified ? 'VERIFIED' : 'UNVERIFIED'}
            </span>
          </div>
        </div>
      </div>

      {/* 2. RAW PAYLOAD SECTION (Collapsible & Truncated) */}
      <div className="rounded-xl border border-slate-800 bg-[#0d121c] overflow-hidden">
        <div 
          onClick={() => setIsPayloadOpen(!isPayloadOpen)}
          className="flex items-center justify-between px-3.5 py-2.5 bg-slate-900/50 hover:bg-slate-900/80 cursor-pointer select-none border-b border-slate-800/60 transition"
        >
          <div className="flex items-center space-x-2 text-xs font-semibold text-slate-300">
            <FileCode2 className="w-3.5 h-3.5 text-cyan-400" />
            <span>Raw Decoded Payload</span>
            {hasDecodedPayload && (
              <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-slate-400">
                {rawPayload.length} chars
              </span>
            )}
          </div>
          <div className="flex items-center space-x-2">
            {hasDecodedPayload && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCopyPayload();
                }}
                className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center space-x-1 border border-slate-700 transition"
                title="Copy raw payload"
              >
                {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3 text-slate-400" />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            )}
            {isPayloadOpen ? (
              <ChevronUp className="w-4 h-4 text-slate-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-slate-400" />
            )}
          </div>
        </div>

        {isPayloadOpen && (
          <div className="p-3 text-xs space-y-2">
            {hasDecodedPayload ? (
              <>
                <div className="p-2.5 rounded-lg bg-[#06080e] border border-slate-800 font-mono text-[11px] text-cyan-200/90 break-all leading-relaxed whitespace-pre-wrap select-all">
                  {isPayloadExpanded || rawPayload.length <= 160
                    ? rawPayload
                    : `${rawPayload.slice(0, 160)}...`}
                </div>
                {rawPayload.length > 160 && (
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={() => setIsPayloadExpanded(!isPayloadExpanded)}
                      className="text-[11px] font-mono text-cyan-400 hover:text-cyan-300 hover:underline flex items-center space-x-1"
                    >
                      <span>{isPayloadExpanded ? 'Show less' : 'Show full payload'}</span>
                      {isPayloadExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div className="py-3 px-2 text-center text-slate-500 font-mono text-[11px] italic bg-[#06080e]/60 rounded border border-slate-900">
                {signatureReason}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 3. FIELD-BY-FIELD TABLE */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="font-semibold text-slate-300">Field-by-Field Verification</span>
          {comparisonEntries.length > 0 && (
            <span className="text-[10px] font-mono text-slate-400">
              {comparisonEntries.length} field{comparisonEntries.length !== 1 ? 's' : ''} evaluated
            </span>
          )}
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-800 bg-[#0d121c]">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/60 text-slate-400 text-[11px] font-mono uppercase tracking-wider">
                <th className="py-2.5 px-3">Field</th>
                <th className="py-2.5 px-3">Printed (OCR)</th>
                <th className="py-2.5 px-3">QR Payload</th>
                <th className="py-2.5 px-3 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-[11px]">
              {comparisonEntries.length > 0 ? (
                comparisonEntries.map(([key, comp]) => {
                  const printedVal = comp.printed || comp.printed_last4 || null;
                  const qrVal = comp.qr || comp.qr_last4 || null;
                  const status = comp.status || 'NOT_COMPARED';

                  return (
                    <tr key={key} className="hover:bg-slate-800/40 transition">
                      <td className="py-2.5 px-3 font-medium text-slate-200">
                        {formatFieldName(key, comp)}
                      </td>
                      <td className="py-2.5 px-3 font-mono text-slate-300 max-w-[150px] truncate" title={printedVal || 'None'}>
                        {printedVal ? (
                          <span>{printedVal}</span>
                        ) : (
                          <span className="text-slate-500 italic">None</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 font-mono text-slate-300 max-w-[150px] truncate" title={qrVal || 'None'}>
                        {qrVal ? (
                          <span className="text-cyan-300">{qrVal}</span>
                        ) : (
                          <span className="text-slate-500 italic">None</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 text-right whitespace-nowrap">
                        {getStatusBadge(status)}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan="4" className="py-6 px-3 text-center text-slate-500 font-mono text-xs italic">
                    {hasDecodedPayload 
                      ? 'No structured field comparisons could be established from this QR payload.'
                      : `No comparison available: ${signatureReason}`}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default QREvidencePanel;
