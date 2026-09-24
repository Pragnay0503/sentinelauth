import React, { useEffect } from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react';

/**
 * SentinelAuth Design System: Toast / Alert
 * Used for transient success/error notifications or inline alerts.
 * Hairline border, no shadow, accessible screen-reader announcement.
 * Supports White Mode and Dark Mode.
 */
export function Toast({
  message,
  title = null,
  variant = 'info', // 'success' | 'warning' | 'critical' | 'info'
  onClose = null,
  duration = 5000,
  className = '',
}) {
  useEffect(() => {
    if (!duration || !onClose) return;
    const timer = setTimeout(() => {
      onClose();
    }, duration);
    return () => clearTimeout(timer);
  }, [duration, onClose]);

  const config = {
    success: {
      icon: CheckCircle2,
      border: 'border-[#3F9868]/60',
      bg: 'bg-[#141A22]',
      iconColor: 'text-[#4ADE80]',
      titleColor: 'text-[#4ADE80]',
    },
    warning: {
      icon: AlertTriangle,
      border: 'border-[#D9A441]/60',
      bg: 'bg-[#141A22]',
      iconColor: 'text-[#D9A441]',
      titleColor: 'text-[#D9A441]',
    },
    critical: {
      icon: AlertCircle,
      border: 'border-[#C0392B]/60',
      bg: 'bg-[#141A22]',
      iconColor: 'text-[#E74C3C]',
      titleColor: 'text-[#E74C3C]',
    },
    info: {
      icon: Info,
      border: 'border-[var(--panel-border)]',
      bg: 'bg-[var(--panel)]',
      iconColor: 'text-[var(--ink-muted)]',
      titleColor: 'text-[var(--ink)]',
    },
  }[variant] || config.info;

  const Icon = config.icon;

  return (
    <div
      role="alert"
      aria-live="polite"
      className={`flex items-start gap-3 p-3.5 border ${config.border} ${config.bg} rounded-none shadow-none text-xs text-[var(--ink)] ${className}`}
    >
      <Icon className={`w-4 h-4 shrink-0 mt-0.5 ${config.iconColor}`} aria-hidden="true" />

      <div className="flex-1 min-w-0">
        {title && (
          <h4 className={`font-mono font-bold uppercase tracking-wider text-[11px] mb-0.5 ${config.titleColor}`}>
            {title}
          </h4>
        )}
        <p className="text-xs text-[var(--ink)] leading-relaxed break-words">{message}</p>
      </div>

      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Dismiss notification"
          className="text-[var(--ink-muted)] hover:text-[var(--ink)] p-1 rounded-[4px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal-amber)] cursor-pointer shrink-0"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

export default Toast;
