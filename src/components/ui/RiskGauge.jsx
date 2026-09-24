import React from 'react';

/**
 * SentinelAuth Design System: RiskGauge
 * Radial/arc risk-level indicator reusable across single-document and session screening.
 * Tiers: LOW (0-29), MEDIUM (30-59), HIGH (60-79), CRITICAL (80-100)
 */
export function RiskGauge({
  score = 0,
  tier = null,
  size = 'md', // 'sm' | 'md' | 'lg'
  showLabel = true,
  className = '',
}) {
  const normalizedScore = Math.min(100, Math.max(0, Math.round(score)));

  // Auto-derive tier if not explicitly provided
  const derivedTier =
    tier?.toUpperCase() ||
    (normalizedScore >= 80
      ? 'CRITICAL'
      : normalizedScore >= 60
      ? 'HIGH'
      : normalizedScore >= 30
      ? 'MEDIUM'
      : 'LOW');

  const config = {
    LOW: {
      color: '#3F9868',
      textClass: 'text-[#4ADE80]',
      bgClass: 'bg-[#3F9868]/15 border-[#3F9868]/40',
      label: 'LOW RISK',
    },
    MEDIUM: {
      color: '#D9A441',
      textClass: 'text-[#D9A441]',
      bgClass: 'bg-[#D9A441]/15 border-[#D9A441]/40',
      label: 'ELEVATED',
    },
    HIGH: {
      color: '#E67E22',
      textClass: 'text-[#FB923C]',
      bgClass: 'bg-[#E67E22]/15 border-[#E67E22]/40',
      label: 'HIGH RISK',
    },
    CRITICAL: {
      color: '#C0392B',
      textClass: 'text-[#E74C3C]',
      bgClass: 'bg-[#C0392B]/15 border-[#C0392B]/40',
      label: 'CRITICAL',
    },
  }[derivedTier] || {
    color: '#3F9868',
    textClass: 'text-[#4ADE80]',
    bgClass: 'bg-[#3F9868]/15 border-[#3F9868]/40',
    label: 'CLEARED',
  };

  const dimensions = {
    sm: { width: 100, strokeWidth: 8, fontSize: 'text-lg', labelSize: 'text-[9px]' },
    md: { width: 140, strokeWidth: 10, fontSize: 'text-2xl', labelSize: 'text-[10px]' },
    lg: { width: 180, strokeWidth: 12, fontSize: 'text-3xl', labelSize: 'text-xs' },
  }[size] || { width: 140, strokeWidth: 10, fontSize: 'text-2xl', labelSize: 'text-[10px]' };

  // Semi-circle arc SVG math
  const radius = (dimensions.width - dimensions.strokeWidth * 2) / 2;
  const circumference = Math.PI * radius; // 180-degree half-circle
  const strokeDashoffset = circumference - (normalizedScore / 100) * circumference;

  return (
    <div className={`flex flex-col items-center justify-center font-sans ${className}`}>
      <div className="relative flex items-center justify-center" style={{ width: dimensions.width, height: dimensions.width / 1.7 }}>
        <svg
          width={dimensions.width}
          height={dimensions.width / 1.7}
          viewBox={`0 0 ${dimensions.width} ${dimensions.width / 1.7}`}
          className="overflow-visible"
        >
          {/* Background Arc Track */}
          <path
            d={`M ${dimensions.strokeWidth} ${dimensions.width / 1.8} A ${radius} ${radius} 0 0 1 ${
              dimensions.width - dimensions.strokeWidth
            } ${dimensions.width / 1.8}`}
            fill="none"
            stroke="#232B38"
            strokeWidth={dimensions.strokeWidth}
            strokeLinecap="round"
          />

          {/* Dynamic Colored Value Arc */}
          <path
            d={`M ${dimensions.strokeWidth} ${dimensions.width / 1.8} A ${radius} ${radius} 0 0 1 ${
              dimensions.width - dimensions.strokeWidth
            } ${dimensions.width / 1.8}`}
            fill="none"
            stroke={config.color}
            strokeWidth={dimensions.strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            className="transition-all duration-500 ease-out"
          />
        </svg>

        {/* Center Numeric Value */}
        <div className="absolute inset-0 flex flex-col items-center justify-end pb-1">
          <span className={`font-mono font-bold leading-none ${dimensions.fontSize} text-[#E4E7EB]`}>
            {normalizedScore}
            <span className="text-[10px] text-[#8A93A3] font-normal font-sans ml-0.5">/100</span>
          </span>
        </div>
      </div>

      {showLabel && (
        <div className="mt-2 text-center">
          <span
            className={`inline-block px-2 py-0.5 rounded-[4px] font-mono font-bold uppercase tracking-wider border ${config.labelSize} ${config.bgClass} ${config.textClass}`}
          >
            {config.label}
          </span>
        </div>
      )}
    </div>
  );
}

export default RiskGauge;
