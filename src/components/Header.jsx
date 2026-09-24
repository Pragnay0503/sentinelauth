import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  ShieldCheck, 
  MapPin, 
  Volume2, 
  VolumeX, 
  Users, 
  Zap,
  FileCheck,
  Activity,
  User,
  Sliders,
  ShieldAlert,
  LogOut,
  ChevronDown
} from 'lucide-react';
import { sounds } from '../utils/audio';
import { CHECKPOINT_LOCATIONS } from '../data/locations';
import { Button, Badge, StatusDot, Tabs } from './ui';
import { useAuth } from '../context/AuthContext';

export function Header({ 
  activeTab, 
  setActiveTab, 
  soundEnabled, 
  setSoundEnabled, 
  activeLocation, 
  setActiveLocation,
  currentOfficer = null,
  sessionStatus = null
}) {
  const { user, logout } = useAuth();
  const [officerMenuOpen, setOfficerMenuOpen] = useState(false);
  const officerMenuRef = useRef(null);

  // Close menu on outside click
  useEffect(() => {
    function handleOutsideClick(e) {
      if (officerMenuRef.current && !officerMenuRef.current.contains(e.target)) {
        setOfficerMenuOpen(false);
      }
    }
    if (officerMenuOpen) document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [officerMenuOpen]);

  const handleLogout = useCallback(async () => {
    setOfficerMenuOpen(false);
    if (soundEnabled) sounds.playClick();
    await logout();
  }, [logout, soundEnabled]);
  const [passengerCount, setPassengerCount] = useState(14280);

  useEffect(() => {
    const timer = setInterval(() => {
      setPassengerCount((prev) => prev + 1);
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  const effectiveOfficer = user || currentOfficer;
  const isAdmin = effectiveOfficer?.role === 'admin' || true;

  const navTabs = [
    { id: 'screening', label: 'Screening Operations', icon: Zap },
    { id: 'audit', label: 'Checkpoint Audit Logs', icon: FileCheck },
    { id: 'analytics', label: 'Security Analytics', icon: Activity },
    { id: 'admin_users', label: 'Officer Management', icon: Users, badge: 'Admin' },
    { id: 'showcase', label: 'Design System Library', icon: Sliders, badge: 'Tokens' },
  ];

  const handleTabChange = (tabId) => {
    if (soundEnabled) sounds.playClick();
    setActiveTab(tabId);
  };

  return (
    <header className="sticky top-0 z-50 bg-[#141A22] border-b border-[#232B38] text-[#E4E7EB] rounded-none shadow-none">
      {/* Top Operations Bar */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3 border-b border-[#232B38]">
        
        {/* Brand & Agency Identifiers */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-[#10151C] border border-[#232B38] rounded-[4px] flex items-center justify-center text-[#D9A441] shrink-0">
            <ShieldCheck className="w-5 h-5" aria-hidden="true" />
          </div>

          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-base font-bold tracking-tight text-[#E4E7EB] font-sans">
                SentinelAuth
              </h1>
              <Badge variant="warning" size="sm">SIH #26188</Badge>
              <Badge variant="neutral" size="sm" className="hidden sm:inline-flex">
                MHA / SSB Police II Division
              </Badge>
            </div>
          </div>
        </div>

        {/* Live Terminal Telemetry & Controls */}
        <div className="flex items-center gap-2.5 flex-wrap">
          {/* Location Selector */}
          <div className="flex items-center gap-1.5 bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2.5 py-1.5 text-xs text-[#E4E7EB]">
            <MapPin className="w-3.5 h-3.5 text-[#D9A441] shrink-0" aria-hidden="true" />
            <label htmlFor="header-checkpoint-select" className="sr-only">Checkpoint Location</label>
            <select 
              id="header-checkpoint-select"
              value={activeLocation}
              onChange={(e) => setActiveLocation(e.target.value)}
              className="bg-transparent border-none text-[#E4E7EB] focus:outline-none cursor-pointer font-medium text-xs pr-1 font-sans"
            >
              {CHECKPOINT_LOCATIONS.map((loc) => (
                <option key={loc.id} value={loc.id} className="bg-[#141A22] text-[#E4E7EB]">
                  {loc.name}
                </option>
              ))}
            </select>
          </div>

          {/* Session Status Indicator */}
          <div 
            className="flex items-center gap-2 bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2.5 py-1.5 text-xs select-none"
            data-testid="header-session-status"
            title={sessionStatus?.sessionId ? `Current Traveler Session: ${sessionStatus.sessionId}` : "Checkpoint Traveler Session"}
          >
            <span className="text-[#8A93A3] font-mono text-[11px] hidden sm:inline">Session:</span>
            {sessionStatus?.state === 'complete' ? (
              <span className="flex items-center gap-1.5 text-[#4ADE80] font-mono font-semibold text-[11px]">
                <span className="w-2 h-2 rounded-full bg-[#4ADE80] animate-pulse"></span>
                Complete — report generated
              </span>
            ) : sessionStatus?.state === 'active' ? (
              <span className="flex items-center gap-1.5 text-[#D9A441] font-mono font-semibold text-[11px]">
                <span className="w-2 h-2 rounded-full bg-[#D9A441] animate-pulse"></span>
                Active — {sessionStatus.documentCount} {sessionStatus.documentCount === 1 ? 'document' : 'documents'}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-[#8A93A3] font-mono text-[11px]">
                <span className="w-2 h-2 rounded-full bg-[#5A6578]"></span>
                New session
              </span>
            )}
          </div>

          {/* Processed Count */}
          <div className="hidden lg:flex items-center gap-2 bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2.5 py-1.5 text-xs">
            <Users className="w-3.5 h-3.5 text-[#3F9868]" aria-hidden="true" />
            <span className="text-[#8A93A3] font-mono text-[11px]">Processed:</span>
            <span className="font-mono font-bold text-[#E4E7EB]">{passengerCount.toLocaleString()}</span>
          </div>

          {/* Engine Status Dot */}
          <div className="hidden sm:flex items-center gap-1.5 bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2.5 py-1.5">
            <StatusDot status="ready" label="OCR & S-MAD Online" pulse />
          </div>

          {/* Audio Feedback Toggle */}
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setSoundEnabled(!soundEnabled)}
            aria-label={soundEnabled ? 'Mute operational sound effects' : 'Enable operational sound effects'}
            icon={soundEnabled ? Volume2 : VolumeX}
            className="p-2 min-h-0 min-w-0"
          />

          {/* Duty Officer Profile — click to open sign-out dropdown */}
          {(user || currentOfficer) && (
            <div className="relative" ref={officerMenuRef}>
              {/* Chip / trigger */}
              <button
                id="officer-menu-trigger"
                type="button"
                aria-haspopup="true"
                aria-expanded={officerMenuOpen}
                aria-controls="officer-menu-panel"
                onClick={() => setOfficerMenuOpen((o) => !o)}
                title="Officer session — click to sign out"
                className="flex items-center gap-2 bg-[#0B0F14] border border-[#232B38] rounded-[4px] px-2.5 py-1.5 text-xs select-none cursor-pointer hover:border-[#D9A441]/60 hover:bg-[#141A22] transition-colors"
              >
                <User className="w-3.5 h-3.5 text-[#D9A441] shrink-0" aria-hidden="true" />
                <div className="text-left font-mono">
                  <span className="block text-[10px] text-[#8A93A3] leading-none">Duty Officer</span>
                  <span
                    data-testid="duty-officer-id"
                    className="font-bold text-[11px] text-[#E4E7EB] leading-tight truncate max-w-[120px] block"
                  >
                    {user?.badge_id || currentOfficer?.badgeId || 'ADM-ROOT-001'}
                  </span>
                </div>
                <Badge
                  variant="warning"
                  size="sm"
                  className="ml-0.5 text-[9px] py-0 px-1 uppercase"
                >
                  {user?.role || currentOfficer?.role || 'officer'}
                </Badge>
                <ChevronDown
                  className={`w-3 h-3 text-[#8A93A3] shrink-0 transition-transform duration-150 ${
                    officerMenuOpen ? 'rotate-180' : ''
                  }`}
                  aria-hidden="true"
                />
              </button>

              {/* Dropdown panel */}
              {officerMenuOpen && (
                <div
                  id="officer-menu-panel"
                  role="menu"
                  aria-labelledby="officer-menu-trigger"
                  className="absolute right-0 top-[calc(100%+6px)] z-50 w-56 bg-[#141A22] border border-[#232B38] rounded-[4px] shadow-xl shadow-black/40 py-2 animate-in fade-in"
                >
                  {/* Officer details */}
                  <div className="px-3 py-2 border-b border-[#232B38]">
                    <p className="text-[10px] font-mono text-[#8A93A3] uppercase tracking-wider mb-1">Active Session</p>
                    <p className="text-xs font-bold text-[#E4E7EB] font-mono truncate">
                      {user?.officer_name || currentOfficer?.officerName || 'Duty Officer'}
                    </p>
                    <p className="text-[11px] font-mono text-[#D9A441] truncate">
                      {user?.badge_id || currentOfficer?.badgeId || '—'}
                    </p>
                    <p className="text-[10px] font-mono text-[#8A93A3] uppercase mt-0.5">
                      Role: {user?.role || currentOfficer?.role || 'officer'}
                    </p>
                  </div>

                  {/* Sign out */}
                  <div className="px-2 pt-2">
                    <button
                      id="sign-out-btn"
                      type="button"
                      role="menuitem"
                      onClick={handleLogout}
                      className="w-full flex items-center gap-2.5 px-2.5 py-2 text-xs font-mono font-bold text-[#E74C3C] hover:bg-[#E74C3C]/10 rounded-[3px] transition-colors cursor-pointer group"
                    >
                      <LogOut className="w-3.5 h-3.5 shrink-0 group-hover:translate-x-0.5 transition-transform" aria-hidden="true" />
                      Sign Out
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Navigation Tabs Bar */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6">
        <Tabs
          tabs={navTabs}
          activeTab={activeTab}
          onChange={handleTabChange}
          ariaLabel="Primary Console Navigation"
        />
      </div>
    </header>
  );
}

export default Header;
