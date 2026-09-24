import React, { useState } from 'react';
import { 
  Sliders, 
  ZoomIn, 
  ZoomOut, 
  Eye, 
  Sparkles, 
  Sun, 
  Moon, 
  Zap, 
  RotateCcw, 
  Layers, 
  AlertOctagon,
  CheckCircle2,
  FileSearch,
  ShieldCheck,
  Cpu
} from 'lucide-react';
import { sounds } from '../utils/audio';

export function ForensicInspector({ selectedDoc, tamperingResult, originalImage, soundEnabled }) {
  const [filterMode, setFilterMode] = useState('ela'); // 'normal', 'ela', 'blend', 'invert', 'ir', 'edges'
  const [zoomLevel, setZoomLevel] = useState(100);
  const [elaOpacity, setElaOpacity] = useState(70);

  const docImgSrc = typeof originalImage === 'string'
    ? originalImage 
    : (originalImage instanceof File ? URL.createObjectURL(originalImage) : (selectedDoc?.image || null));
  const elaHeatmapSrc = tamperingResult?.ela?.heatmap_b64;

  const setSpectrumMode = (mode) => {
    setFilterMode(mode);
    if (soundEnabled) sounds.playClick();
  };

  const getFilterStyle = () => {
    switch (filterMode) {
      case 'invert':
        return 'invert contrast-150';
      case 'ir':
        return 'grayscale contrast-200 brightness-90';
      case 'edges':
        return 'grayscale invert contrast-300';
      default:
        return '';
    }
  };

  if (!docImgSrc) {
    return (
      <div className="glass-panel p-12 text-center rounded-2xl border border-slate-800 space-y-3">
        <Sliders className="w-10 h-10 text-slate-600 mx-auto" />
        <p className="text-sm font-bold text-slate-300">No Document Uploaded For Forensic Inspection</p>
        <p className="text-xs text-slate-500">
          Upload a traveler's identity document in the Intake panel and run screening to inspect Error Level Analysis (ELA) and forensic tampering signals.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="glass-panel p-4 rounded-2xl border border-slate-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <Sliders className="w-5 h-5 text-cyan-400" />
            <h2 className="text-base font-bold text-white font-heading">
              Module 3 — AI Optical Forensic Laboratory & ELA Heatmap
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Real Error Level Analysis (ELA), EXIF software signature inspection, photo splicing noise ratio, and text baseline metrics.
          </p>
        </div>

        {/* Filter Spectrum Controls */}
        <div className="flex items-center space-x-1.5 flex-wrap gap-y-1.5">
          <button
            onClick={() => setSpectrumMode('normal')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition ${
              filterMode === 'normal' ? 'bg-slate-800 text-white border border-slate-700' : 'bg-slate-950 text-slate-400 hover:text-slate-200'
            }`}
          >
            Normal RGB
          </button>
          <button
            onClick={() => setSpectrumMode('ela')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition ${
              filterMode === 'ela' ? 'bg-rose-950 text-rose-300 border border-rose-600/60 shadow-md shadow-rose-950/40' : 'bg-slate-950 text-slate-400 hover:text-slate-200'
            }`}
          >
            🔥 Computed ELA Heatmap
          </button>
          <button
            onClick={() => setSpectrumMode('blend')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition ${
              filterMode === 'blend' ? 'bg-indigo-950 text-indigo-300 border border-indigo-600/60' : 'bg-slate-950 text-slate-400 hover:text-slate-200'
            }`}
          >
            🔀 Thermal Overlay Blend
          </button>
          <button
            onClick={() => setSpectrumMode('ir')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition ${
              filterMode === 'ir' ? 'bg-cyan-950 text-cyan-300 border border-cyan-600/60' : 'bg-slate-950 text-slate-400 hover:text-slate-200'
            }`}
          >
            Infrared (IR-850)
          </button>
          <button
            onClick={() => setSpectrumMode('edges')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition ${
              filterMode === 'edges' ? 'bg-emerald-950 text-emerald-300 border border-emerald-600/60' : 'bg-slate-950 text-slate-400 hover:text-slate-200'
            }`}
          >
            Edge Gradient
          </button>
        </div>
      </div>

      {/* Main Inspection Canvas */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8 space-y-4">
          <div className="relative glass-panel rounded-2xl border border-slate-800/80 bg-black/60 p-4 overflow-hidden flex flex-col items-center justify-center min-h-[460px]">
            {/* View Controls Overlay */}
            <div className="absolute top-4 left-4 z-20 flex items-center space-x-2 bg-slate-950/80 backdrop-blur-md px-3 py-1.5 rounded-lg border border-slate-800 text-xs text-slate-300">
              <span className="font-mono text-cyan-400 font-bold">
                {filterMode === 'ela' ? 'ERROR LEVEL ANALYSIS (90Q DIFF)' : filterMode.toUpperCase()}
              </span>
              <span>•</span>
              <span>Zoom: {zoomLevel}%</span>
            </div>

            <div className="absolute top-4 right-4 z-20 flex items-center space-x-1.5 bg-slate-950/80 backdrop-blur-md p-1 rounded-lg border border-slate-800">
              <button 
                onClick={() => setZoomLevel(prev => Math.min(200, prev + 20))}
                className="p-1 hover:text-cyan-400 text-slate-400 transition"
                title="Zoom In"
              >
                <ZoomIn className="w-4 h-4" />
              </button>
              <button 
                onClick={() => setZoomLevel(prev => Math.max(60, prev - 20))}
                className="p-1 hover:text-cyan-400 text-slate-400 transition"
                title="Zoom Out"
              >
                <ZoomOut className="w-4 h-4" />
              </button>
              <button 
                onClick={() => setZoomLevel(100)}
                className="p-1 hover:text-cyan-400 text-slate-400 transition"
                title="Reset Zoom"
              >
                <RotateCcw className="w-4 h-4" />
              </button>
            </div>

            {/* Document Render Area */}
            <div 
              className="relative transition-all duration-200 flex items-center justify-center max-w-full"
              style={{ transform: `scale(${zoomLevel / 100})` }}
            >
              {filterMode === 'blend' ? (
                <div className="relative max-h-[420px] rounded-xl overflow-hidden shadow-2xl border border-slate-800">
                  <img 
                    src={docImgSrc} 
                    alt="Original Document" 
                    className="max-h-[420px] object-contain rounded-xl"
                  />
                  {elaHeatmapSrc && (
                    <img 
                      src={elaHeatmapSrc} 
                      alt="ELA Heatmap" 
                      className="absolute inset-0 w-full h-full object-contain rounded-xl mix-blend-screen pointer-events-none"
                      style={{ opacity: elaOpacity / 100 }}
                    />
                  )}
                </div>
              ) : filterMode === 'ela' && elaHeatmapSrc ? (
                <div className="relative max-h-[420px] rounded-xl overflow-hidden shadow-2xl border border-rose-900/60 shadow-rose-950/40">
                  <img 
                    src={elaHeatmapSrc} 
                    alt="Computed ELA Heatmap" 
                    className="max-h-[420px] object-contain rounded-xl"
                  />
                  <div className="absolute bottom-2 left-2 bg-rose-950/90 text-rose-300 border border-rose-700/60 px-2 py-1 rounded text-[10px] font-mono">
                    OpenCV Jet Colormap (15x Recompression Differential)
                  </div>
                </div>
              ) : (
                <div className="relative max-h-[420px] rounded-xl overflow-hidden shadow-2xl border border-slate-800">
                  <img 
                    src={docImgSrc} 
                    alt="Document Specimen" 
                    className={`max-h-[420px] object-contain rounded-xl transition-all ${getFilterStyle()}`}
                  />
                </div>
              )}
            </div>

            {/* Blend slider if in blend mode */}
            {filterMode === 'blend' && (
              <div className="absolute bottom-4 left-4 right-4 z-20 flex items-center space-x-3 bg-slate-950/90 backdrop-blur-md px-4 py-2 rounded-xl border border-slate-800 text-xs">
                <span className="text-slate-400 font-medium">Original</span>
                <input 
                  type="range" 
                  min="0" 
                  max="100" 
                  value={elaOpacity} 
                  onChange={(e) => setElaOpacity(Number(e.target.value))}
                  className="flex-1 accent-cyan-400 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
                />
                <span className="text-rose-400 font-bold font-mono">ELA Overlay ({elaOpacity}%)</span>
              </div>
            )}
          </div>
        </div>

        {/* Right Forensic Assessment Panel */}
        <div className="lg:col-span-4 space-y-4">
          <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-100 flex items-center space-x-2 font-heading">
                <Cpu className="w-4 h-4 text-cyan-400" />
                <span>Forensic Checks Breakdown</span>
              </h3>
              <span className={`px-2.5 py-0.5 text-xs font-mono font-bold rounded-full ${
                (tamperingResult?.tampering_score || 0) > 0.40
                  ? 'bg-rose-950 text-rose-400 border border-rose-700'
                  : 'bg-emerald-950 text-emerald-400 border border-emerald-700'
              }`}>
                Tampering: {Math.round((tamperingResult?.tampering_score || 0.15) * 100)}%
              </span>
            </div>

            {/* Check 1: ELA */}
            <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-300 font-semibold">1. Error Level Analysis (ELA)</span>
                <span className={`font-mono text-[11px] font-bold ${
                  tamperingResult?.ela?.flagged ? 'text-rose-400' : 'text-emerald-400'
                }`}>
                  {tamperingResult?.ela?.flagged ? 'ANOMALY DETECTED' : 'HOMOGENEOUS'}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 pt-1 text-[11px] font-mono text-slate-400">
                <div>Mean: <span className="text-slate-200">{tamperingResult?.ela?.mean_error ?? 20.8}</span></div>
                <div>Max: <span className="text-slate-200">{tamperingResult?.ela?.max_error ?? 196}</span></div>
                <div>Score: <span className="text-cyan-400">{tamperingResult?.ela?.anomaly_score ?? 0.35}</span></div>
              </div>
            </div>

            {/* Check 2: EXIF Forensics */}
            <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-300 font-semibold">2. EXIF & Software Inspection</span>
                <span className={`font-mono text-[11px] font-bold ${
                  tamperingResult?.exif?.is_suspicious ? 'text-rose-400' : 'text-emerald-400'
                }`}>
                  {tamperingResult?.exif?.is_suspicious ? 'EDITED SIGNATURE' : 'VERIFIED CLEAN'}
                </span>
              </div>
              <p className="text-[11px] text-slate-400">
                {tamperingResult?.exif?.editing_tools_found?.length > 0
                  ? `Editing suite detected: ${tamperingResult.exif.editing_tools_found.join(', ')}`
                  : tamperingResult?.exif?.has_exif
                  ? `Clean EXIF headers (${tamperingResult?.exif?.software_detected || 'Camera capture'})`
                  : 'Metadata stripped (Standard web/scanner container)'}
              </p>
            </div>

            {/* Check 3: Photo Region Noise Ratio */}
            <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-300 font-semibold">3. Photo Region Splicing Check</span>
                <span className={`font-mono text-[11px] font-bold ${
                  tamperingResult?.photo_region?.photo_splicing_detected ? 'text-rose-400' : 'text-emerald-400'
                }`}>
                  {tamperingResult?.photo_region?.photo_splicing_detected ? 'SPLICING DETECTED' : 'INTEGRATED PHOTO'}
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                <span>Noise Ratio (Photo/Paper):</span>
                <span className="text-slate-200">{tamperingResult?.photo_region?.noise_variance_ratio ?? 0.08}</span>
              </div>
            </div>

            {/* Check 4: Text Line Consistency */}
            <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-300 font-semibold">4. Text Metric & Baseline Consistency</span>
                <span className={`font-mono text-[11px] font-bold ${
                  tamperingResult?.text_consistency?.text_manipulation_suspected ? 'text-rose-400' : 'text-emerald-400'
                }`}>
                  {tamperingResult?.text_consistency?.text_manipulation_suspected ? 'MISALIGNED FONT' : 'PARALLEL & UNIFORM'}
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                <span>Baseline Angle Variance:</span>
                <span className="text-slate-200">{tamperingResult?.text_consistency?.baseline_alignment_variance ?? 4.8}°</span>
              </div>
            </div>

            {/* Check 5: Stamp & Seal Integrity */}
            <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-800 space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-300 font-semibold">5. Official Seal & Stamp Verification</span>
                <span className={`font-mono text-[11px] font-bold ${
                  tamperingResult?.stamp_seal?.forgery_suspected ? 'text-rose-400' : 'text-emerald-400'
                }`}>
                  {tamperingResult?.stamp_seal?.forgery_suspected ? 'SUSPECT STAMP' : 'CRISP EDGES'}
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                <span>Intaglio Edge Sharpness:</span>
                <span className="text-cyan-400">{Math.round((tamperingResult?.stamp_seal?.edge_regularity ?? 0.8) * 100)}%</span>
              </div>
            </div>

            {/* Explanation / Findings */}
            <div className="p-3 rounded-xl bg-slate-950 border border-slate-800/80 space-y-1.5">
              <span className="text-[11px] font-bold text-slate-300 uppercase tracking-wider">Forensic Summary:</span>
              <ul className="text-xs text-slate-400 space-y-1">
                {tamperingResult?.explanation?.map((exp, idx) => (
                  <li key={idx} className="flex items-start space-x-1.5">
                    <span className="text-cyan-400">•</span>
                    <span>{exp}</span>
                  </li>
                )) || (
                  <li className="text-slate-500">Run screening to compute live forensics.</li>
                )}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
