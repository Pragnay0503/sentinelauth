import React from 'react';

/**
 * SentinelAuth Design System: ConfidenceBar
 * Small horizontal bar displaying a 0-100 confidence value.
 * Used adjacent to every OCR extracted field.
 * Green: >= 85% | Amber: 60-84% | Red: < 60%
 */
export function ConfidenceBar({
  value = 0, // 0 to 100 or 0.0 to 1.0
  showValue = true,
  size = 'sm', // 'xs' | 'sm' | 'md'
  className = '',
}) {
  // Normalize value to 0-100 scale
  const normalized = value <= 1.0 && value > 0 ? Math.round(value * 100) : Math.min(100, Math.max(0, Math.round(value)));

  let barColor = 'bg-[#3F9868]'; // Verified Green
  let textColor = 'text-[#4ADE80]';

  if (normalized < 60) {
    barColor = 'bg-[#C0392B]'; // Alert Red
    textColor = 'text-[#E74C3C]';
  } else if (normalized < 85) {
    barColor = 'bg-[#D9A441]'; // Signal Amber
    textColor = 'text-[#D9A441]';
  }

  const heightStyles = {
    xs: 'h-1 w-12',
    sm: 'h-1.5 w-16',
    md: 'h-2 w-20',
  };

  return (
    <div
      className={`inline-flex items-center gap-2 font-mono ${className}`}
      role="progressbar"
      aria-valuenow={normalized}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Confidence ${normalized}%`}
    >
      <div className={`${heightStyles[size] || heightStyles.sm} bg-[#10151C] border border-[#232B38] overflow-hidden`}>
        <div
          className={`h-full ${barColor} transition-all duration-300`}
          style={{ width: `${normalized}%` }}
        />
      </div>
      {showValue && (
        <span className={`text-[11px] font-bold ${textColor}`}>
          {normalized}%
        </span>
      )}
    </div>
  );
}

export default ConfidenceBar;
