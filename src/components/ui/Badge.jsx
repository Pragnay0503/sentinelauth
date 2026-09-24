import React from 'react';

/**
 * SentinelAuth Design System: Badge / Pill
 * Radius: 4px (interactive controls/tags only)
 * Variants: neutral, warning (signal amber), critical (alert red), success (verified green)
 */
export function Badge({
  children,
  variant = 'neutral', // 'neutral' | 'warning' | 'critical' | 'success'
  size = 'md',         // 'sm' | 'md'
  icon: Icon = null,
  className = '',
  ...props
}) {
  const baseStyles =
    'inline-flex items-center font-mono font-bold uppercase tracking-wider rounded-[4px] border shrink-0';

  const variantStyles = {
    neutral: 'bg-[#141A22] text-[#8A93A3] border-[#232B38]', // NOT_EVALUATED / SKIPPED / Standby
    skipped: 'bg-[#141A22] text-[#8A93A3] border-[#232B38]',
    warning: 'bg-[#D9A441]/12 text-[#D9A441] border-[#D9A441]/40', // Strictly caution: ELEVATED / warnings / pending
    caution: 'bg-[#D9A441]/12 text-[#D9A441] border-[#D9A441]/40',
    critical: 'bg-[#C0392B]/12 text-[#E74C3C] border-[#C0392B]/40', // TAMPERED / CRITICAL / FAILED only
    danger: 'bg-[#C0392B]/12 text-[#E74C3C] border-[#C0392B]/40',
    success: 'bg-[#3F9868]/12 text-[#4ADE80] border-[#3F9868]/40', // VERIFIED / PASSED only
    primary: 'bg-[#2D6A9F]/20 text-[#60A5FA] border-[#2D6A9F]/40', // Steel blue primary
  };

  const sizeStyles = {
    sm: 'text-[10px] px-1.5 py-0.5 gap-1',
    md: 'text-xs px-2.5 py-1 gap-1.5',
  };

  return (
    <span
      className={`${baseStyles} ${variantStyles[variant] || variantStyles.neutral} ${sizeStyles[size] || sizeStyles.md} ${className}`}
      {...props}
    >
      {Icon && <Icon className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} aria-hidden="true" />}
      <span>{children}</span>
    </span>
  );
}

/**
 * SentinelAuth Design System: ConfidenceBadge
 * Small color-coded confidence badge:
 * - Green (>= 85%): HIGH
 * - Amber (60-84%): MEDIUM
 * - Red (< 60%): LOW
 */
export function ConfidenceBadge({ confidence = 0, className = '' }) {
  const normalized =
    confidence <= 1.0 && confidence > 0
      ? Math.round(confidence * 100)
      : Math.min(100, Math.max(0, Math.round(confidence || 0)));

  const isHigh = normalized >= 85;
  const isMed = normalized >= 60 && normalized < 85;
  const label = isHigh ? 'HIGH' : isMed ? 'MED' : 'LOW';

  return (
    <span
      className={`inline-flex items-center gap-1 font-mono font-bold uppercase rounded-[4px] border px-1.5 py-0.5 text-[9px] shrink-0 ${
        isHigh
          ? 'bg-[#3F9868]/15 text-[#4ADE80] border-[#3F9868]/40'
          : isMed
          ? 'bg-[#D9A441]/15 text-[#D9A441] border-[#D9A441]/40'
          : 'bg-[#C0392B]/15 text-[#E74C3C] border-[#C0392B]/40'
      } ${className}`}
      title={`OCR Field Confidence: ${normalized}% (${label})`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-80" aria-hidden="true" />
      <span>{normalized}%</span>
      <span className="text-[8px] opacity-75 font-sans font-semibold">{label}</span>
    </span>
  );
}

export default Badge;
