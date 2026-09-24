import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

/**
 * SentinelAuth Design System: Panel / Card
 * Radius: 0px (structural panels/dividers - no default rounded-everything)
 * Hairline border: #232B38
 * No shadow
 */
export function Panel({
  children,
  header = null,
  title = null,
  subtitle = null,
  icon: Icon = null,
  actions = null,
  collapsible = false,
  defaultCollapsed = false,
  padding = 'md', // 'none' | 'sm' (8px) | 'md' (16px) | 'lg' (24px)
  className = '',
  ...props
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  const paddingStyles = {
    none: 'p-0',
    sm: 'p-2 sm:p-3',
    md: 'p-4',
    lg: 'p-6',
  };

  const hasHeader = Boolean(header || title);

  return (
    <div
      className={`bg-[#141A22] border border-[#232B38] rounded-none shadow-none text-[#E4E7EB] ${className}`}
      {...props}
    >
      {hasHeader && (
        <div className="flex items-center justify-between border-b border-[#232B38] px-4 py-3 bg-[#10151C]">
          {header ? (
            header
          ) : (
            <div className="flex items-center gap-2.5 min-w-0">
              {Icon && <Icon className="w-4 h-4 text-[#D9A441] shrink-0" aria-hidden="true" />}
              <div className="min-w-0">
                <h3 className="text-xs font-bold uppercase tracking-wider text-[#E4E7EB] truncate font-sans">
                  {title}
                </h3>
                {subtitle && (
                  <p className="text-[11px] text-[#8A93A3] truncate font-mono mt-0.5">
                    {subtitle}
                  </p>
                )}
              </div>
            </div>
          )}

          <div className="flex items-center gap-2 shrink-0">
            {actions}
            {collapsible && (
              <button
                type="button"
                onClick={() => setCollapsed(!collapsed)}
                aria-expanded={!collapsed}
                className="p-1 text-[#8A93A3] hover:text-[#E4E7EB] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#D9A441] rounded-[4px] cursor-pointer"
              >
                {collapsed ? (
                  <ChevronDown className="w-4 h-4" />
                ) : (
                  <ChevronUp className="w-4 h-4" />
                )}
              </button>
            )}
          </div>
        </div>
      )}

      {!collapsed && (
        <div className={paddingStyles[padding] || paddingStyles.md}>
          {children}
        </div>
      )}
    </div>
  );
}

export function PanelHeader({ children, className = '' }) {
  return (
    <div className={`flex items-center justify-between border-b border-[#232B38] px-4 py-3 bg-[#10151C] ${className}`}>
      {children}
    </div>
  );
}

export function PanelBody({ children, padding = 'md', className = '' }) {
  const paddingStyles = {
    none: 'p-0',
    sm: 'p-2 sm:p-3',
    md: 'p-4',
    lg: 'p-6',
  };
  return (
    <div className={`${paddingStyles[padding] || paddingStyles.md} ${className}`}>
      {children}
    </div>
  );
}

export default Panel;
