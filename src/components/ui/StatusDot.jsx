import React from 'react';

/**
 * SentinelAuth Design System: StatusDot
 * Small colored indicator dot used in the status bar for engine readiness.
 * Amber: processing/warming | Green: ready/online | Red: error/offline
 */
export function StatusDot({
  status = 'ready', // 'ready' | 'processing' | 'error' | 'offline'
  label = null,
  pulse = false,
  size = 'md',      // 'sm' | 'md' | 'lg'
  className = '',
}) {
  const configMap = {
    ready: {
      color: 'bg-[#3F9868]',
      text: 'text-[#4ADE80]',
      ring: 'ring-[#3F9868]/30',
      labelDefault: 'Engine Ready',
    },
    processing: {
      color: 'bg-[#D9A441]',
      text: 'text-[#D9A441]',
      ring: 'ring-[#D9A441]/30',
      labelDefault: 'Processing',
    },
    error: {
      color: 'bg-[#C0392B]',
      text: 'text-[#E74C3C]',
      ring: 'ring-[#C0392B]/30',
      labelDefault: 'Error / Offline',
    },
    offline: {
      color: 'bg-[#8A93A3]',
      text: 'text-[#8A93A3]',
      ring: 'ring-[#8A93A3]/30',
      labelDefault: 'Standby',
    },
    };

  const config = configMap[status] || configMap.ready;

  const sizeStyles = {
    sm: 'w-1.5 h-1.5',
    md: 'w-2 h-2',
    lg: 'w-2.5 h-2.5',
  }[size] || 'w-2 h-2';

  const shouldPulse = pulse || status === 'processing';

  return (
    <span className={`inline-flex items-center gap-1.5 font-mono text-[11px] ${className}`}>
      <span className="relative flex items-center justify-center">
        <span
          className={`${sizeStyles} rounded-full ${config.color} ${
            shouldPulse ? 'animate-pulse' : ''
          }`}
          aria-hidden="true"
        />
        {shouldPulse && (
          <span
            className={`absolute -inset-0.5 rounded-full ${config.color} opacity-40 animate-ping`}
            aria-hidden="true"
          />
        )}
      </span>
      {label !== false && (
        <span className={`font-semibold tracking-tight ${config.text}`}>
          {label || config.labelDefault}
        </span>
      )}
    </span>
  );
}

export default StatusDot;
