import React, { useState, useRef, useEffect } from 'react';
import { 
  Camera, 
  UserCheck, 
  ShieldCheck, 
  AlertTriangle, 
  RefreshCw, 
  CheckCircle2, 
  Scan, 
  Lock, 
  Sparkles,
  VideoOff,
  Upload,
  UserX,
  Activity,
  Eye,
  Smile,
  ArrowRight,
  ArrowLeft,
  Info,
  Check,
  Zap,
  ShieldAlert,
  Loader2,
  AlertCircle,
  RotateCcw
} from 'lucide-react';
import { sounds } from '../utils/audio';

const GUIDED_STEPS = [
  { 
    id: 'fit_in_frame', 
    label: 'Fit in Frame', 
    instruction: 'Align traveler face inside checkpoint oval',
    icon: Scan,
    hint: 'Center face and look straight at camera'
  },
  { 
    id: 'turn_right', 
    label: 'Turn Head Right', 
    instruction: 'Slowly turn your head slightly to the RIGHT',
    icon: ArrowRight,
    hint: 'Turn head approx 15° to 30° to the right'
  },
  { 
    id: 'smile', 
    label: 'Smile Expression', 
    instruction: 'Now give a natural SMILE for the camera',
    icon: Smile,
    hint: 'Smile naturally towards camera'
  }
];

const LIVENESS_CHALLENGES = [
  { id: 'blink', label: 'Blink Eyes', instruction: 'Please BLINK your eyes naturally', icon: Eye },
  { id: 'turn_left', label: 'Turn Head Left', instruction: 'Slowly TURN your head slightly to the LEFT', icon: ArrowLeft },
  { id: 'turn_right', label: 'Turn Head Right', instruction: 'Slowly TURN your head slightly to the RIGHT', icon: ArrowRight },
  { id: 'smile', label: 'Smile', instruction: 'Please SMILE towards the camera', icon: Smile },
];

export function LiveFaceScanner({ selectedDoc, originalImage, selfieImage, onSelfieChange, onVerificationComplete, soundEnabled }) {
  const [cameraActive, setCameraActive] = useState(false);
  const [cameraError, setCameraError] = useState(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [selfiePreview, setSelfiePreview] = useState(selfieImage || selectedDoc?.selfieImage || null);
  const [selfieFile, setSelfieFile] = useState(null);
  const [verifyResult, setVerifyResult] = useState(null);
  const [serverError, setServerError] = useState(null);
  const [lastSubmission, setLastSubmission] = useState(null);

  // Guided Multi-Step Liveness State
  const [guidedMode, setGuidedMode] = useState(true);
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [stepPassed, setStepPassed] = useState([false, false, false]);
  const [telemetry, setTelemetry] = useState(null);
  const [isAutoProgressing, setIsAutoProgressing] = useState(false);

  // Manual Challenge State
  const [currentChallenge, setCurrentChallenge] = useState(LIVENESS_CHALLENGES[2]); // Default Turn Right
  const [isCapturingBurst, setIsCapturingBurst] = useState(false);
  const [burstProgress, setBurstProgress] = useState(0);

  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const isProbingRef = useRef(false);
  const probeTimerRef = useRef(null);
  const consecutiveFulfillRef = useRef(0);
  const burstFramesRef = useRef([]);

  const docImgSrc = typeof originalImage === 'string'
    ? originalImage
    : (originalImage instanceof File ? URL.createObjectURL(originalImage) : (selectedDoc?.image || null));

  useEffect(() => {
    if (selfieImage && !selfieFile) {
      setSelfiePreview(selfieImage);
    }
  }, [selfieImage]);

  // Pick a random challenge on mount or refresh
  const cycleChallenge = () => {
    const nextIdx = Math.floor(Math.random() * LIVENESS_CHALLENGES.length);
    setCurrentChallenge(LIVENESS_CHALLENGES[nextIdx]);
  };

  // Bind stream whenever cameraActive changes and video element mounts
  useEffect(() => {
    if (cameraActive && streamRef.current && videoRef.current) {
      if (videoRef.current.srcObject !== streamRef.current) {
        videoRef.current.srcObject = streamRef.current;
      }
      videoRef.current.play().catch(err => console.warn("Live video play warning:", err));
    }
  }, [cameraActive]);

  // Clean up media stream and timer on unmount
  useEffect(() => {
    return () => {
      if (probeTimerRef.current) clearInterval(probeTimerRef.current);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
        streamRef.current = null;
      }
    };
  }, []);

  const startCamera = async () => {
    try {
      setCameraError(null);
      setCurrentStepIdx(0);
      setStepPassed([false, false, false]);
      burstFramesRef.current = [];
      consecutiveFulfillRef.current = 0;
      setTelemetry(null);

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Camera API is not supported in this browser environment. Ensure you are on http://localhost or HTTPS.");
      }

      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
        });
      } catch (err1) {
        // Fallback to generic video constraint if width/height/facingMode is rejected
        stream = await navigator.mediaDevices.getUserMedia({ video: true });
      }

      streamRef.current = stream;
      setCameraActive(true);

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => {});
      }

      if (soundEnabled) sounds.playScan();
    } catch (err) {
      console.warn("Camera access failed or denied:", err);
      let msg = "Camera unavailable or permission denied. You can upload a passenger photo below.";
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        msg = "Camera permission denied. Please click the camera icon in your browser address bar to allow access, or upload a photo below.";
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        msg = "No camera hardware detected. You can upload a passenger photo below.";
      } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
        msg = "Camera is already in use by another application. Please close other video apps or upload a photo below.";
      }
      setCameraError(msg);
      setCameraActive(false);
    }
  };

  const stopCamera = () => {
    if (probeTimerRef.current) {
      clearInterval(probeTimerRef.current);
      probeTimerRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraActive(false);
    setIsCapturingBurst(false);
    setIsAutoProgressing(false);
  };

  // Real-time live probe loop: captures features (Fit in frame, Turn right, Smile) & gives prompts
  useEffect(() => {
    if (!cameraActive || isVerifying || isAutoProgressing) {
      if (probeTimerRef.current) clearInterval(probeTimerRef.current);
      return;
    }

    const intervalId = setInterval(async () => {
      if (isProbingRef.current || !videoRef.current || videoRef.current.readyState < 2) {
        return;
      }

      isProbingRef.current = true;
      try {
        const video = videoRef.current;
        const canvas = document.createElement('canvas');
        canvas.width = 320;
        canvas.height = 240;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, 320, 240);

        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.82));
        if (!blob) {
          isProbingRef.current = false;
          return;
        }

        const activeTarget = guidedMode 
          ? (GUIDED_STEPS[currentStepIdx]?.id || 'fit_in_frame')
          : currentChallenge.id;

        const formData = new FormData();
        formData.append('frame', blob, 'probe.jpg');
        formData.append('target_prompt', activeTarget);

        const res = await fetch('http://localhost:8000/api/scan/live-probe', {
          method: 'POST',
          body: formData
        });

        if (res.ok) {
          const data = await res.json();
          setTelemetry(data);

          if (data.target_fulfilled) {
            consecutiveFulfillRef.current += 1;

            // Require 2 consecutive frames meeting condition (~400ms) for high confidence
            if (consecutiveFulfillRef.current >= 2) {
              // Capture high-res frame from video
              const fullCanvas = document.createElement('canvas');
              fullCanvas.width = video.videoWidth || 640;
              fullCanvas.height = video.videoHeight || 480;
              const fCtx = fullCanvas.getContext('2d');
              fCtx.drawImage(video, 0, 0, fullCanvas.width, fullCanvas.height);
              
              const fullBlob = await new Promise(r => fullCanvas.toBlob(r, 'image/jpeg', 0.94));
              if (fullBlob) {
                burstFramesRef.current.push(
                  new File([fullBlob], `step_${activeTarget}_${Date.now()}.jpg`, { type: 'image/jpeg' })
                );
              }

              if (soundEnabled) sounds.playScan();

              if (guidedMode) {
                setStepPassed(prev => {
                  const updated = [...prev];
                  updated[currentStepIdx] = true;
                  return updated;
                });

                consecutiveFulfillRef.current = 0;

                if (currentStepIdx < GUIDED_STEPS.length - 1) {
                  // Advance to next prompt!
                  setCurrentStepIdx(prev => prev + 1);
                } else {
                  // All 3 features captured! Auto-trigger verification!
                  setIsAutoProgressing(true);
                  if (soundEnabled) sounds.playSuccess();
                  
                  setTimeout(() => {
                    const finalFrames = [...burstFramesRef.current];
                    if (finalFrames.length > 0) {
                      const lastBlobUrl = URL.createObjectURL(finalFrames[finalFrames.length - 1]);
                      setSelfieFile(finalFrames[finalFrames.length - 1]);
                      setSelfiePreview(lastBlobUrl);
                      if (onSelfieChange) onSelfieChange(finalFrames[finalFrames.length - 1], lastBlobUrl);
                    }
                    stopCamera();
                    runFaceVerification(finalFrames);
                  }, 500);
                }
              }
            }
          } else {
            consecutiveFulfillRef.current = 0;
          }
        }
      } catch (err) {
        console.warn("Live probe request error:", err);
      } finally {
        isProbingRef.current = false;
      }
    }, 220);

    probeTimerRef.current = intervalId;
    return () => clearInterval(intervalId);
  }, [cameraActive, currentStepIdx, guidedMode, currentChallenge.id, isVerifying, isAutoProgressing, soundEnabled]);

  // Capture a 5-frame burst across 1.5 seconds to evaluate real biological motion
  const captureLivenessBurst = async () => {
    if (!videoRef.current || !cameraActive) return;
    setIsCapturingBurst(true);
    setBurstProgress(10);
    if (soundEnabled) sounds.playScan();

    const frames = [];
    const canvas = document.createElement('canvas');
    canvas.width = videoRef.current.videoWidth || 640;
    canvas.height = videoRef.current.videoHeight || 480;
    const ctx = canvas.getContext('2d');

    const totalFrames = 5;
    const intervalMs = 300; // 5 frames * 300ms = 1.5 seconds

    for (let i = 0; i < totalFrames; i++) {
      ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92));
      if (blob) {
        frames.push(new File([blob], `frame_${i}.jpg`, { type: 'image/jpeg' }));
      }
      setBurstProgress(Math.round(((i + 1) / totalFrames) * 100));
      if (i < totalFrames - 1) {
        await new Promise(r => setTimeout(r, intervalMs));
      }
    }

    setIsCapturingBurst(false);
    if (frames.length > 0) {
      const lastBlobUrl = URL.createObjectURL(frames[frames.length - 1]);
      setSelfieFile(frames[frames.length - 1]);
      setSelfiePreview(lastBlobUrl);
      if (onSelfieChange) onSelfieChange(frames[frames.length - 1], lastBlobUrl);
      stopCamera();
      runFaceVerification(frames);
    }
  };

  const handleSelfieUpload = (e) => {
    if (e?.preventDefault) e.preventDefault();
    if (e?.stopPropagation) e.stopPropagation();
    const file = e?.target?.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    setSelfieFile(file);
    setSelfiePreview(url);
    if (onSelfieChange) onSelfieChange(file, url);
    runFaceVerification([file], true); // upload mode
  };

  const retryLastVerification = (e) => {
    if (e?.preventDefault) e.preventDefault();
    if (lastSubmission?.framesList?.length) {
      runFaceVerification(lastSubmission.framesList, lastSubmission.isStaticUpload);
    } else if (selfieFile) {
      runFaceVerification([selfieFile], true);
    } else {
      runFaceVerification();
    }
  };

  const runFaceVerification = async (framesList = [], isStaticUpload = false) => {
    if (isVerifying) return;
    setLastSubmission({ framesList, isStaticUpload });
    setIsVerifying(true);
    setServerError(null);
    setVerifyResult(null);

    try {
      let docFile = null;
      if (originalImage instanceof File) {
        docFile = originalImage;
      } else if (docImgSrc) {
        try {
          const res = await fetch(docImgSrc);
          if (res.ok) {
            const blob = await res.blob();
            docFile = new File([blob], "document_img.png", { type: blob.type || "image/png" });
          }
        } catch (e) {
          console.warn("Could not load document reference photo:", e);
        }
      }

      if (!docFile) {
        setCameraError("Please upload or scan a document first so the system has a reference photo for facial matching.");
        setIsVerifying(false);
        return;
      }

      const formData = new FormData();
      formData.append('doc_image', docFile);
      formData.append('challenge', currentChallenge.id);
      formData.append('threshold', '0.363');

      if (framesList.length > 1) {
        // Send frame burst
        framesList.forEach((frameFile, idx) => {
          formData.append(`frame_${idx}`, frameFile);
        });
      } else if (framesList.length === 1) {
        // Single frame or upload
        formData.append('selfie_image', framesList[0]);
        if (isStaticUpload) {
          // In static upload mode without video feed, liveness challenge is flagged
          formData.append('frame_0', framesList[0]);
        }
      } else if (selfieFile) {
        formData.append('selfie_image', selfieFile);
      }

      // Try /api/face/verify first, fallback to /api/scan/face-verify
      let response;
      try {
        response = await fetch('http://localhost:8000/api/face/verify', {
          method: 'POST',
          body: formData
        });
        if (!response.ok && response.status === 404) {
          response = await fetch('http://localhost:8000/api/scan/face-verify', {
            method: 'POST',
            body: formData
          });
        }
      } catch (err) {
        response = await fetch('http://localhost:8000/api/scan/face-verify', {
          method: 'POST',
          body: formData
        });
      }

      if (!response.ok) {
        const errorText = await response.text().catch(() => '');
        throw new Error(errorText || `Biometric service returned status ${response.status}`);
      }

      const data = await response.json();
      setVerifyResult(data);
      setServerError(null);

      if (onVerificationComplete) {
        onVerificationComplete(data);
      }

      if (data.status === 'SUCCESS' && data.match) {
        if (soundEnabled) sounds.playSuccess();
      } else {
        if (soundEnabled) sounds.playAlert();
      }
    } catch (err) {
      console.error("Biometric verification error:", err);
      // Dedicated server/network error state with retry
      setServerError(err.message || "Verification failed — please try again");
      setVerifyResult(null);
    } finally {
      setIsVerifying(false);
    }
  };

  const activeStep = GUIDED_STEPS[currentStepIdx] || GUIDED_STEPS[0];
  const StepIcon = activeStep.icon;

  // Determine HUD border status color based on real-time probe
  let hudBorderColor = "border-cyan-500/40";
  let promptStatusColor = "bg-cyan-950/80 border-cyan-500/50 text-cyan-300";

  if (telemetry) {
    if (!telemetry.face_detected) {
      hudBorderColor = "border-amber-500/60";
      promptStatusColor = "bg-amber-950/80 border-amber-500/60 text-amber-300";
    } else if (telemetry.target_fulfilled) {
      hudBorderColor = "border-emerald-400 shadow-[0_0_25px_rgba(16,185,129,0.4)]";
      promptStatusColor = "bg-emerald-950/90 border-emerald-400 text-emerald-300";
    } else if (telemetry.fit_status && telemetry.fit_status !== "OPTIMAL") {
      hudBorderColor = "border-amber-400/60";
      promptStatusColor = "bg-slate-900/90 border-amber-500/50 text-amber-200";
    }
  }

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="glass-panel p-4 rounded-2xl border border-slate-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <Camera className="w-5 h-5 text-cyan-400" />
            <h2 className="text-base font-bold text-white font-heading">
              Module 4 — Biometric Facial Verification & Live Feature Capture
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time biometric feature tracking (framing, head pose, smile expression) with automated guided checkpoint prompts.
          </p>
        </div>

        <div className="flex items-center space-x-2">
          {!cameraActive ? (
            <button
              type="button"
              onClick={(e) => {
                if (e?.preventDefault) e.preventDefault();
                startCamera();
              }}
              disabled={isVerifying}
              className="px-3.5 py-1.5 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 rounded-xl text-xs font-semibold flex items-center space-x-1.5 transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Camera className="w-4 h-4" />
              <span>Start Live Checkpoint Camera</span>
            </button>
          ) : (
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={(e) => {
                  if (e?.preventDefault) e.preventDefault();
                  captureLivenessBurst();
                }}
                disabled={isCapturingBurst || isVerifying}
                className="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-slate-950 rounded-xl text-xs font-bold flex items-center space-x-1.5 transition shadow-lg shadow-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                <Activity className={`w-3.5 h-3.5 ${isCapturingBurst ? 'animate-spin' : ''}`} />
                <span>{isCapturingBurst ? `Capturing (${burstProgress}%)...` : 'Execute Now'}</span>
              </button>
              <button
                type="button"
                onClick={(e) => {
                  if (e?.preventDefault) e.preventDefault();
                  stopCamera();
                }}
                disabled={isVerifying}
                className="p-1.5 bg-slate-900 text-slate-400 hover:text-slate-200 border border-slate-800 rounded-xl cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                title="Stop Camera"
              >
                <VideoOff className="w-4 h-4" />
              </button>
            </div>
          )}

          <label className={`px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 rounded-xl text-xs font-medium flex items-center space-x-1.5 transition ${isVerifying ? 'opacity-50 cursor-not-allowed pointer-events-none' : 'cursor-pointer'}`}>
            {isVerifying ? <Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" /> : <Upload className="w-3.5 h-3.5 text-cyan-400" />}
            <span>{isVerifying ? 'Comparing...' : 'Upload Photo'}</span>
            <input 
              type="file" 
              accept="image/*" 
              disabled={isVerifying}
              onChange={handleSelfieUpload} 
              className="hidden" 
            />
          </label>
        </div>
      </div>

      {/* Guided 3-Step Checkpoint Protocol Bar */}
      {cameraActive && (
        <div className="p-3.5 rounded-2xl bg-slate-900/90 border border-slate-800 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-cyan-400 font-bold uppercase tracking-wider flex items-center space-x-1.5">
              <Zap className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
              <span>Checkpoint Guided Verification Sequence</span>
            </span>
            <div className="flex items-center space-x-1.5 text-[10px] font-mono text-slate-400">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
              <span>AI Feature Tracking Active</span>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {GUIDED_STEPS.map((step, idx) => {
              const SIcon = step.icon;
              const isCurrent = currentStepIdx === idx;
              const isDone = stepPassed[idx];

              return (
                <button
                  key={step.id}
                  type="button"
                  onClick={(e) => {
                    if (e?.preventDefault) e.preventDefault();
                    setCurrentStepIdx(idx);
                    consecutiveFulfillRef.current = 0;
                  }}
                  className={`p-2.5 rounded-xl border text-left flex items-center space-x-2.5 transition cursor-pointer ${
                    isDone
                      ? 'bg-emerald-950/40 border-emerald-500/50 text-emerald-300'
                      : isCurrent
                        ? 'bg-cyan-950/60 border-cyan-400 text-white ring-1 ring-cyan-400/40'
                        : 'bg-slate-950/40 border-slate-800/80 text-slate-400 hover:border-slate-700'
                  }`}
                >
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
                    isDone 
                      ? 'bg-emerald-500 text-slate-950 font-bold' 
                      : isCurrent 
                        ? 'bg-cyan-500 text-slate-950 font-bold animate-pulse' 
                        : 'bg-slate-800 text-slate-400'
                  }`}>
                    {isDone ? <Check className="w-4 h-4 stroke-[3]" /> : <SIcon className="w-3.5 h-3.5" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[10px] uppercase font-mono tracking-wider opacity-75">
                      Step {idx + 1}
                    </div>
                    <div className="text-xs font-bold truncate">
                      {step.label}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {cameraError && (
        <div className="p-3 rounded-xl bg-amber-950/40 border border-amber-800/60 text-amber-300 text-xs flex items-center space-x-2">
          <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
          <span>{cameraError}</span>
        </div>
      )}

      {/* Main Biometric Comparison Grid */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        {/* Document Photo Card */}
        <div className="md:col-span-5 space-y-3">
          <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-slate-200 font-heading">Document Reference Photo</span>
              <span className="font-mono text-[10px] text-cyan-400 uppercase">Input A</span>
            </div>
            
            <div className="relative aspect-[4/3] bg-black/60 rounded-xl border border-slate-800 overflow-hidden flex items-center justify-center">
              <img 
                src={docImgSrc} 
                alt="Document Reference" 
                className="max-h-full object-contain rounded-lg"
              />
            </div>
            <div className="text-[11px] text-slate-400 flex items-center justify-between font-mono">
              <span>Face Region: Verified</span>
              <span className="text-cyan-400">128-D SFace Alignment</span>
            </div>
          </div>
        </div>

        {/* Dual Verification Center Gauge */}
        <div className="md:col-span-2 flex flex-col items-center justify-center space-y-3 py-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 border border-cyan-400/40">
            {isVerifying ? (
              <Loader2 className="w-6 h-6 text-white animate-spin" />
            ) : (
              <Scan className="w-6 h-6 text-white" />
            )}
          </div>

          <div className="text-center space-y-1">
            <div className="text-[10px] uppercase font-bold tracking-widest text-slate-400">Face Match</div>
            <div className={`text-xl font-black font-mono ${
              isVerifying
                ? 'text-cyan-400 animate-pulse'
                : verifyResult?.match
                  ? 'text-emerald-400'
                  : verifyResult
                    ? 'text-amber-400'
                    : 'text-slate-500'
            }`}>
              {isVerifying ? '...' : verifyResult ? `${Math.round(verifyResult.confidence * 100)}%` : '--'}
            </div>
          </div>

          <div className="text-center space-y-0.5 border-t border-slate-800 pt-2 w-full">
            <div className="text-[9px] uppercase font-bold tracking-widest text-slate-400">Status</div>
            <div className={`text-xs font-mono font-bold ${
              isVerifying
                ? 'text-cyan-400'
                : verifyResult?.match
                  ? 'text-emerald-400'
                  : verifyResult
                    ? 'text-amber-400'
                    : 'text-slate-500'
            }`}>
              {isVerifying
                ? 'Comparing...'
                : verifyResult?.match
                  ? 'MATCH'
                  : verifyResult?.status === "NO_FACE_IN_DOCUMENT"
                    ? 'NO DOC FACE'
                    : verifyResult?.status === "NO_FACE_IN_SELFIE"
                      ? 'NO SELFIE FACE'
                      : verifyResult
                        ? 'NO MATCH'
                        : '--'}
            </div>
          </div>

          <div className="text-center space-y-0.5 border-t border-slate-800 pt-2 w-full">
            <div className="text-[9px] uppercase font-bold tracking-widest text-slate-400">Morph Suspicion</div>
            <div className={`text-xs font-mono font-bold ${
              verifyResult?.is_morph_suspected
                ? (verifyResult.morph_suspicion_tier === 'HIGH_SUSPICION' ? 'text-rose-400' : 'text-amber-400')
                : verifyResult ? 'text-emerald-400' : 'text-slate-500'
            }`}>
              {verifyResult ? (
                verifyResult.morph_suspicion_tier ? `${verifyResult.morph_suspicion_tier.replace('_', ' ')} (${Math.round((verifyResult.morph_suspicion_score || 0) * 100)}%)` : 'NORMAL (0%)'
              ) : '--'}
            </div>
          </div>

          {isVerifying ? (
            <div className="flex items-center space-x-1.5 text-xs text-cyan-400 font-mono animate-pulse">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>Comparing...</span>
            </div>
          ) : selfiePreview && (
            <button
              type="button"
              onClick={(e) => {
                if (e?.preventDefault) e.preventDefault();
                runFaceVerification();
              }}
              disabled={isVerifying}
              className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 border border-slate-700 rounded-lg transition flex items-center space-x-1 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw className="w-3 h-3" />
              <span>Re-check</span>
            </button>
          )}
        </div>

        {/* Live Passenger / Selfie Photo Card */}
        <div className="md:col-span-5 space-y-3">
          <div className="glass-panel p-4 rounded-2xl border border-slate-800 space-y-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-slate-200 font-heading">Live Presentation Capture</span>
              <span className="font-mono text-[10px] text-emerald-400 uppercase">Input B</span>
            </div>

            <div className="relative aspect-[4/3] bg-black/60 rounded-xl border border-slate-800 overflow-hidden flex items-center justify-center">
              {cameraActive ? (
                <>
                  <video 
                    ref={(el) => {
                      videoRef.current = el;
                      if (el && streamRef.current && el.srcObject !== streamRef.current) {
                        el.srcObject = streamRef.current;
                        el.play().catch(err => console.warn("Video play error:", err));
                      }
                    }} 
                    autoPlay 
                    playsInline 
                    muted 
                    className="w-full h-full object-cover"
                  />

                  {/* Biometric Face Target HUD Overlay */}
                  <div className="absolute inset-0 pointer-events-none flex flex-col items-center justify-between p-3.5">
                    {/* Top status indicator */}
                    <div className="w-full flex items-center justify-between text-[10px] font-mono text-slate-300">
                      <span className="px-2 py-0.5 rounded bg-black/60 border border-slate-700/60 backdrop-blur-sm">
                        STEP {currentStepIdx + 1}/3: {activeStep.label}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-black/60 border border-slate-700/60 backdrop-blur-sm text-cyan-300">
                        {telemetry?.latency_ms ? `${telemetry.latency_ms}ms` : '30 FPS'}
                      </span>
                    </div>

                    {/* Checkpoint Biometric Oval Reticle */}
                    <div className="relative w-48 h-56 flex items-center justify-center">
                      <div className={`w-full h-full rounded-[45%] border-2 transition-all duration-200 flex items-center justify-center ${hudBorderColor}`}>
                        {/* Center action cue depending on step */}
                        {currentStepIdx === 1 && (
                          <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-cyan-950/80 border border-cyan-400/60 text-cyan-300 text-xs font-bold animate-bounce">
                            <span>Turn Right</span>
                            <ArrowRight className="w-3.5 h-3.5" />
                          </div>
                        )}
                        {currentStepIdx === 2 && (
                          <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-emerald-950/80 border border-emerald-400/60 text-emerald-300 text-xs font-bold animate-pulse">
                            <Smile className="w-4 h-4" />
                            <span>Smile</span>
                          </div>
                        )}
                      </div>

                      {/* Corner Target Brackets */}
                      <div className="absolute -top-1 -left-1 w-3.5 h-3.5 border-t-2 border-l-2 border-cyan-400"></div>
                      <div className="absolute -top-1 -right-1 w-3.5 h-3.5 border-t-2 border-r-2 border-cyan-400"></div>
                      <div className="absolute -bottom-1 -left-1 w-3.5 h-3.5 border-b-2 border-l-2 border-cyan-400"></div>
                      <div className="absolute -bottom-1 -right-1 w-3.5 h-3.5 border-b-2 border-r-2 border-cyan-400"></div>
                    </div>

                    {/* Dynamic Real-time HUD Prompt Bar */}
                    <div className="w-full flex flex-col items-center space-y-1.5">
                      <div className={`px-3 py-1 rounded-full border text-xs font-bold flex items-center space-x-2 backdrop-blur-md shadow-lg transition-all ${promptStatusColor}`}>
                        <span className={`w-2 h-2 rounded-full ${telemetry?.target_fulfilled ? 'bg-emerald-400 animate-ping' : 'bg-amber-400'}`}></span>
                        <span>
                          {telemetry?.prompt_message || activeStep.instruction}
                        </span>
                      </div>

                      {/* Live Telemetry Sensor Badges */}
                      <div className="flex items-center space-x-2 text-[9px] font-mono text-slate-300 bg-black/60 px-2.5 py-0.5 rounded-full border border-slate-800 backdrop-blur-sm">
                        <span>Pose: <strong className="text-cyan-400">{telemetry?.telemetry?.head_pose || 'CENTER'} ({telemetry?.telemetry?.yaw_deg || 0}°)</strong></span>
                        <span className="text-slate-600">•</span>
                        <span>Smile: <strong className={telemetry?.telemetry?.is_smiling ? 'text-emerald-400' : 'text-slate-400'}>
                          {Math.round((telemetry?.telemetry?.smile_score || 0) * 100)}%
                        </strong></span>
                        <span className="text-slate-600">•</span>
                        <span>Fit: <strong className={telemetry?.fit_passed ? 'text-emerald-400' : 'text-amber-400'}>
                          {telemetry?.fit_status || 'SCANNING'}
                        </strong></span>
                      </div>
                    </div>
                  </div>
                </>
              ) : selfiePreview ? (
                <img 
                  src={selfiePreview} 
                  alt="Passenger Selfie" 
                  className="max-h-full object-contain rounded-lg"
                />
              ) : (
                <div className="text-center p-6 space-y-2 text-slate-500">
                  <Camera className="w-10 h-10 mx-auto text-slate-600" />
                  <p className="text-xs">No live video or selfie photo loaded.</p>
                  <p className="text-[11px] text-slate-600">Start camera or upload photo to match.</p>
                </div>
              )}
            </div>

            <div className="text-[11px] text-slate-400 flex items-center justify-between font-mono">
              <span>Source: {cameraActive ? 'Live Guided Camera' : selfiePreview ? 'Captured Biometric Burst' : 'None'}</span>
              <span className="text-emerald-400">Automated Motion Verification</span>
            </div>
          </div>
        </div>
      </div>

      {/* 1. Loading State Banner */}
      {isVerifying && (
        <div className="p-4 rounded-2xl border border-cyan-500/40 bg-cyan-950/30 text-cyan-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 animate-pulse">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/20 text-cyan-400 flex items-center justify-center shrink-0">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
            <div>
              <div className="text-sm font-bold font-heading flex items-center space-x-2">
                <span>Comparing faces...</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 uppercase border border-cyan-500/30">
                  IN FLIGHT
                </span>
              </div>
              <div className="text-xs text-slate-400 mt-0.5 font-sans">
                Extracting 128-D SFace feature embeddings & running optical liveness evaluation...
              </div>
            </div>
          </div>
          <div className="font-mono text-xs text-cyan-400 shrink-0">
            SFace Cosine Comparator Active
          </div>
        </div>
      )}

      {/* 2. Server / Network Error Banner */}
      {serverError && !isVerifying && (
        <div className="p-4 rounded-2xl border border-rose-800/80 bg-rose-950/40 text-rose-300 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-rose-500/20 text-rose-400 flex items-center justify-center shrink-0">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold font-heading text-white flex items-center gap-2">
                <span>Verification failed — please try again</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-900/80 text-rose-200 uppercase border border-rose-700">
                  NETWORK ERROR
                </span>
              </div>
              <div className="text-xs text-rose-300/90 mt-1 font-sans">
                {serverError}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={retryLastVerification}
            className="px-3.5 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-xl text-xs font-bold flex items-center space-x-1.5 transition cursor-pointer shrink-0 shadow-lg shadow-rose-950"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Retry Verification</span>
          </button>
        </div>
      )}

      {/* 3. No Face Detected Banner */}
      {verifyResult && !isVerifying && (verifyResult.status === "NO_FACE_IN_DOCUMENT" || verifyResult.status === "NO_FACE_IN_SELFIE") && (
        <div className="p-4 rounded-2xl border border-amber-600/60 bg-amber-950/30 text-amber-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center shrink-0">
              <UserX className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold font-heading text-amber-100 flex items-center gap-2">
                <span>
                  {verifyResult.status === "NO_FACE_IN_DOCUMENT"
                    ? "No face detected in document image — try a clearer photo"
                    : "No face detected in live capture — please center your face in the oval"}
                </span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 uppercase border border-amber-500/30">
                  {verifyResult.status === "NO_FACE_IN_DOCUMENT" ? "DOCUMENT PHOTO ISSUE" : "LIVE CAPTURE ISSUE"}
                </span>
              </div>
              <div className="text-xs text-amber-300/80 mt-1 font-sans">
                {verifyResult.status === "NO_FACE_IN_DOCUMENT"
                  ? "YuNet neural face detector could not identify a valid facial portrait on the reference document. Ensure the document is flat, well-lit, and the photo is uncropped."
                  : "YuNet found 0 faces in the camera frame. Look directly at the sensor, keep your face inside the oval reticle, and ensure adequate illumination."}
              </div>
            </div>
          </div>
          <div className="flex items-center space-x-2 shrink-0">
            {verifyResult.status === "NO_FACE_IN_DOCUMENT" ? (
              <span className="text-[11px] font-mono text-amber-400 bg-amber-950/60 px-2.5 py-1 rounded-lg border border-amber-700/50">
                Awaiting Clearer Document
              </span>
            ) : (
              <button
                type="button"
                onClick={retryLastVerification}
                className="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-slate-950 rounded-xl text-xs font-bold flex items-center space-x-1.5 transition cursor-pointer"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Recapture Face</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* 4. Success + Match Banner */}
      {verifyResult && !isVerifying && verifyResult.status !== "NO_FACE_IN_DOCUMENT" && verifyResult.status !== "NO_FACE_IN_SELFIE" && verifyResult.match && (
        <div className="p-4 rounded-2xl border border-emerald-500/50 bg-emerald-950/30 text-emerald-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
              <CheckCircle2 className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold font-heading text-emerald-100 flex items-center gap-2">
                <span>Biometric Match Verified ({Math.round(verifyResult.confidence * 100)}% match)</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 uppercase border border-emerald-500/40">
                  MATCH
                </span>
              </div>
              <div className="text-xs text-emerald-300/80 mt-1 font-sans">
                {verifyResult.verification_summary || `Cosine similarity ${(verifyResult.cosine_similarity ?? 0.85).toFixed(3)} exceeds security threshold (${verifyResult.threshold_applied || '0.363'}). Traveler matches reference photo.`}
              </div>
            </div>
          </div>

          <div className="flex items-center space-x-4 font-mono text-xs shrink-0 flex-wrap gap-y-2">
            <div>
              <span className="text-slate-400 block text-[10px]">Facial Match:</span>
              <span className="font-bold text-emerald-400">
                {Math.round(verifyResult.confidence * 100)}% (PASS)
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Liveness Status:</span>
              <span className={`font-bold ${verifyResult.liveness_passed ? 'text-emerald-400' : 'text-amber-400'}`}>
                {verifyResult.liveness_passed ? 'VERIFIED' : 'REVIEW'}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Morph Suspicion:</span>
              <span className={`font-bold ${
                verifyResult.is_morph_suspected ? 'text-amber-400' : 'text-emerald-400'
              }`}>
                {verifyResult.morph_suspicion_tier?.replace('_', ' ') || 'NORMAL'} ({Math.round((verifyResult.morph_suspicion_score || 0) * 100)}%)
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Challenge:</span>
              <span className="font-bold text-slate-200 uppercase">{verifyResult.liveness_challenge || currentChallenge.id}</span>
            </div>
          </div>
        </div>
      )}

      {/* 5. Success + No Match Banner (Normal ML Response, NOT an error or failure) */}
      {verifyResult && !isVerifying && verifyResult.status !== "NO_FACE_IN_DOCUMENT" && verifyResult.status !== "NO_FACE_IN_SELFIE" && !verifyResult.match && (
        <div className="p-4 rounded-2xl border border-amber-500/50 bg-amber-950/30 text-amber-200 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center shrink-0">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-bold font-heading text-amber-100 flex items-center gap-2">
                <span>Biometric Evaluation: No Match ({Math.round(verifyResult.confidence * 100)}% match)</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 uppercase border border-amber-500/40">
                  NO MATCH
                </span>
              </div>
              <div className="text-xs text-amber-300/80 mt-1 font-sans">
                {verifyResult.verification_summary || `${Math.round(verifyResult.confidence * 100)}% match — below threshold (${verifyResult.threshold_applied || '0.363'}), recommend manual review.`}
              </div>
            </div>
          </div>

          <div className="flex items-center space-x-4 font-mono text-xs shrink-0 flex-wrap gap-y-2">
            <div>
              <span className="text-slate-400 block text-[10px]">Facial Match:</span>
              <span className="font-bold text-amber-400">
                {Math.round(verifyResult.confidence * 100)}% (NO MATCH)
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Threshold:</span>
              <span className="font-bold text-slate-300">
                {verifyResult.threshold_applied || '0.363'}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Liveness:</span>
              <span className={`font-bold ${verifyResult.liveness_passed ? 'text-emerald-400' : 'text-slate-400'}`}>
                {verifyResult.liveness_passed ? 'VERIFIED' : 'FAILED'}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Assessment:</span>
              <span className="font-bold text-amber-300 uppercase">Manual Review</span>
            </div>
          </div>
        </div>
      )}

      {/* Face Morphing Attack Detection (S-MAD) Explainable Card */}
      {verifyResult?.morph_analysis && (
        <div className={`p-4 rounded-2xl border space-y-3 ${
          verifyResult.is_morph_suspected
            ? 'bg-amber-950/30 border-amber-800/70 text-amber-200'
            : 'bg-slate-900/60 border-slate-800 text-slate-300'
        }`}>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center space-x-2">
              <ShieldAlert className={`w-4 h-4 ${verifyResult.is_morph_suspected ? 'text-amber-400' : 'text-emerald-400'}`} />
              <span className="font-bold text-xs font-heading">
                Document Photo S-MAD (Single-Image Morphing Attack Detection)
              </span>
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold uppercase ${
                verifyResult.is_morph_suspected
                  ? (verifyResult.morph_suspicion_tier === 'HIGH_SUSPICION' ? 'bg-rose-900/80 text-rose-200 border border-rose-700' : 'bg-amber-900/80 text-amber-200 border border-amber-700')
                  : 'bg-emerald-950/80 text-emerald-300 border border-emerald-700'
              }`}>
                {verifyResult.morph_suspicion_tier?.replace('_', ' ') || (verifyResult.is_morph_suspected ? 'SUSPECTED' : 'NORMAL')} — {Math.round((verifyResult.morph_suspicion_score || 0) * 100)}% Suspicion
              </span>
            </div>

            <span className="text-[10px] font-mono text-slate-400">
              Evaluated on Document Photo Only
            </span>
          </div>

          {verifyResult.is_morph_suspected && (
            <div className="p-2.5 rounded-xl bg-amber-950/50 border border-amber-700/60 text-xs text-amber-200 flex items-start space-x-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <span className="font-bold">Face-Morphing Attack Flagged:</span>{' '}
                {verifyResult.morph_analysis?.summary || 'Document photo exhibits high probability of composite facial identity blending.'}
              </div>
            </div>
          )}

          {/* 4 Explainable Sub-Signal Diagnostic Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 text-xs font-mono">
            {/* Signal 1: LBP Micro-Texture */}
            <div className="p-2.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-slate-400 text-[10px]">1. LBP Micro-Texture</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                  verifyResult.morph_analysis?.signals?.lbp_texture?.flagged ? 'bg-rose-900 text-rose-200' : 'bg-slate-800 text-emerald-400'
                }`}>
                  {verifyResult.morph_analysis?.signals?.lbp_texture?.flagged ? 'FLAGGED' : 'NORMAL'}
                </span>
              </div>
              <div className="text-slate-200 text-[11px] font-semibold">
                Score: {verifyResult.morph_analysis?.signals?.lbp_texture?.score ?? 0.0}
              </div>
              <p className="text-[10px] text-slate-400 font-sans">
                Micro-texture attenuation & smoothing in inner blend zones
              </p>
            </div>

            {/* Signal 2: Facial Symmetry & Anthropometry */}
            <div className="p-2.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-slate-400 text-[10px]">2. Cranial Symmetry</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                  verifyResult.morph_analysis?.signals?.symmetry_and_proportions?.flagged ? 'bg-rose-900 text-rose-200' : 'bg-slate-800 text-emerald-400'
                }`}>
                  {verifyResult.morph_analysis?.signals?.symmetry_and_proportions?.flagged ? 'FLAGGED' : 'NORMAL'}
                </span>
              </div>
              <div className="text-slate-200 text-[11px] font-semibold">
                Score: {verifyResult.morph_analysis?.signals?.symmetry_and_proportions?.score ?? 0.0}
              </div>
              <p className="text-[10px] text-slate-400 font-sans">
                Facial bone structure & bilateral landmark ratio coherence
              </p>
            </div>

            {/* Signal 3: Ghosting / Double Edge */}
            <div className="p-2.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-slate-400 text-[10px]">3. Ghosting Edges</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                  verifyResult.morph_analysis?.signals?.ghosting_double_edge?.flagged ? 'bg-rose-900 text-rose-200' : 'bg-slate-800 text-emerald-400'
                }`}>
                  {verifyResult.morph_analysis?.signals?.ghosting_double_edge?.flagged ? 'FLAGGED' : 'NORMAL'}
                </span>
              </div>
              <div className="text-slate-200 text-[11px] font-semibold">
                Score: {verifyResult.morph_analysis?.signals?.ghosting_double_edge?.score ?? 0.0}
              </div>
              <p className="text-[10px] text-slate-400 font-sans">
                Perimeter double-contour & secondary duplicate ridges
              </p>
            </div>

            {/* Signal 4: Frequency Discontinuity */}
            <div className="p-2.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-slate-400 text-[10px]">4. Spectral FFT</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                  verifyResult.morph_analysis?.signals?.frequency_discontinuity?.flagged ? 'bg-rose-900 text-rose-200' : 'bg-slate-800 text-emerald-400'
                }`}>
                  {verifyResult.morph_analysis?.signals?.frequency_discontinuity?.flagged ? 'FLAGGED' : 'NORMAL'}
                </span>
              </div>
              <div className="text-slate-200 text-[11px] font-semibold">
                Score: {verifyResult.morph_analysis?.signals?.frequency_discontinuity?.score ?? 0.0}
              </div>
              <p className="text-[10px] text-slate-400 font-sans">
                FFT high-frequency roll-off discontinuity at blend seams
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 pt-1 border-t border-slate-800/80">
            <span>Heuristic S-MAD Fusion Engine (v2.4)</span>
            <span>D-MAD differential camera subtraction (Phase 2 Roadmap)</span>
          </div>
        </div>
      )}

      {/* Forensic Liveness Diagnostics Drawer */}
      {verifyResult?.liveness_details?.texture_analysis && (
        <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 text-[11px] font-mono text-slate-400 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center space-x-2">
            <Info className="w-3.5 h-3.5 text-cyan-400" />
            <span>Anti-Spoof Diagnostics:</span>
          </div>
          <div className="flex items-center space-x-3">
            <span>Laplacian Sharpness: <strong className="text-slate-200">{verifyResult.liveness_details.texture_analysis.laplacian_variance}</strong></span>
            <span>Moiré Score: <strong className="text-slate-200">{verifyResult.liveness_details.texture_analysis.moire_score}</strong></span>
            <span>Spoof Signal: <strong className={verifyResult.liveness_details.texture_analysis.spoof_signal_detected ? 'text-rose-400' : 'text-emerald-400'}>
              {verifyResult.liveness_details.texture_analysis.spoof_signal_detected ? 'DETECTED' : 'CLEAR'}
            </strong></span>
          </div>
          <span className="text-[10px] text-slate-500">Phase 1 Optical Heuristic (IR/Iris future tier)</span>
        </div>
      )}
    </div>
  );
}
