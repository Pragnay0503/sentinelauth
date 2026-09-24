import React, { useRef } from 'react';

/**
 * SentinelAuth Design System: Tabs
 * Underline-indicator style with active amber border.
 * Keyboard-navigable (Arrow keys move focus, Enter/Space selects).
 * Responsive: Converts to horizontally-scrollable pill row on mobile (<640px).
 */
export function Tabs({
  tabs = [],
  activeTab,
  onChange,
  className = '',
  ariaLabel = 'Navigation Tabs',
}) {
  const tabListRef = useRef(null);

  const handleKeyDown = (e, index) => {
    if (!tabs || tabs.length === 0) return;
    let nextIndex = index;

    if (e.key === 'ArrowRight') {
      e.preventDefault();
      nextIndex = (index + 1) % tabs.length;
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      nextIndex = (index - 1 + tabs.length) % tabs.length;
    } else if (e.key === 'Home') {
      e.preventDefault();
      nextIndex = 0;
    } else if (e.key === 'End') {
      e.preventDefault();
      nextIndex = tabs.length - 1;
    }

    if (nextIndex !== index) {
      const targetTab = tabs[nextIndex];
      onChange(targetTab.id);
      const buttons = tabListRef.current?.querySelectorAll('[role="tab"]');
      if (buttons && buttons[nextIndex]) {
        buttons[nextIndex].focus();
      }
    }
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      ref={tabListRef}
      className={`flex items-center gap-1 overflow-x-auto no-scrollbar border-b border-[#232B38] bg-transparent ${className}`}
    >
      {tabs.map((tab, idx) => {
        const isActive = tab.id === activeTab;
        const Icon = tab.icon;

        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            id={`tab-${tab.id}`}
            aria-controls={`tabpanel-${tab.id}`}
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => handleKeyDown(e, idx)}
            className={`group relative flex items-center gap-2 whitespace-nowrap px-3 sm:px-4 py-2.5 text-xs font-medium transition-all duration-150 cursor-pointer min-h-[44px] shrink-0 outline-none select-none rounded-[4px] sm:rounded-none ' +
              'focus-visible:ring-2 focus-visible:ring-[#D9A441] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B0F14] ' +
              ${
                isActive
                  ? 'text-[#D9A441] font-semibold bg-[#D9A441]/10 sm:bg-transparent'
                  : 'text-[#8A93A3] hover:text-[#E4E7EB] hover:bg-[#141A22]'
              }`}
          >
            {Icon && (
              <Icon
                className={`w-3.5 h-3.5 shrink-0 transition-colors ${
                  isActive ? 'text-[#D9A441]' : 'text-[#8A93A3] group-hover:text-[#E4E7EB]'
                }`}
                aria-hidden="true"
              />
            )}
            <span>{tab.label}</span>

            {tab.badge !== undefined && tab.badge !== null && (
              <span
                className={`ml-1 px-1.5 py-0.2 text-[10px] font-mono font-bold rounded-[4px] border ${
                  isActive
                    ? 'bg-[#D9A441]/20 text-[#D9A441] border-[#D9A441]/40'
                    : 'bg-[#141A22] text-[#8A93A3] border-[#232B38]'
                }`}
              >
                {tab.badge}
              </span>
            )}

            {/* Desktop / Tablet Underline Indicator */}
            {isActive && (
              <span
                className="hidden sm:block absolute bottom-0 left-0 right-0 h-[2px] bg-[#D9A441]"
                aria-hidden="true"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

export default Tabs;
