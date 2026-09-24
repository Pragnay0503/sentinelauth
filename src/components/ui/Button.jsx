import React from 'react';
import { Loader2 } from 'lucide-react';

/**
 * SentinelAuth Design System: Button
 * Radius: 4px (interactive controls only)
 * Focus ring: Signal Amber with Void offset
 * Loading state: Replaces label with accessible spinner
 */
export function Button({
  children,
  variant = 'primary', // 'primary' | 'secondary' | 'danger' | 'ghost'
  size = 'md',          // 'sm' | 'md' | 'lg'
  isLoading = false,
  disabled = false,
  icon: Icon = null,
  iconPosition = 'left',
  className = '',
  type = 'button',
  ...props
}) {
  const baseStyles =
    'inline-flex items-center justify-center font-sans tracking-tight transition-all duration-150 rounded-[4px] cursor-pointer ' +
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2D6A9F] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B0F14] ' +
    'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none ' +
    'min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 select-none';

  const variantStyles = {
    primary:
      'bg-[#2D6A9F] text-[#FFFFFF] font-semibold hover:bg-[#367DBB] active:bg-[#245782] border border-transparent shadow-none',
    secondary:
      'bg-transparent text-[#E4E7EB] border border-[#232B38] hover:bg-[#141A22] hover:border-[#8A93A3]/60 active:bg-[#202937]',
    danger:
      'bg-[#C0392B] text-[#E4E7EB] font-semibold hover:bg-[#A93226] active:bg-[#922B21] border border-transparent',
    ghost:
      'bg-transparent text-[#8A93A3] hover:text-[#E4E7EB] hover:bg-[#141A22] border border-transparent',
  };

  const sizeStyles = {
    sm: 'h-8 px-3 text-xs gap-1.5',
    md: 'h-10 px-4 text-xs font-semibold gap-2',
    lg: 'h-12 px-6 text-sm font-semibold gap-2.5',
  };

  return (
    <button
      type={type}
      disabled={disabled || isLoading}
      aria-busy={isLoading}
      className={`${baseStyles} ${variantStyles[variant] || variantStyles.primary} ${sizeStyles[size] || sizeStyles.md} ${className}`}
      {...props}
    >
      {isLoading ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin text-current" aria-hidden="true" />
          <span className="sr-only">Loading...</span>
        </>
      ) : (
        <>
          {Icon && iconPosition === 'left' && (
            <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />
          )}
          <span>{children}</span>
          {Icon && iconPosition === 'right' && (
            <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />
          )}
        </>
      )}
    </button>
  );
}

export default Button;
