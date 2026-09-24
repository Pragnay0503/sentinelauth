import React, { useState, useEffect } from 'react';
import { ShieldCheck, Lock, User, MapPin, KeyRound, ArrowRight, AlertTriangle, Clock, Info } from 'lucide-react';
import { Panel, Button, Badge, StatusDot } from './ui';
import { CHECKPOINT_LOCATIONS } from '../data/locations';
import { sounds } from '../utils/audio';
import { useAuth } from '../context/AuthContext';

/**
 * SentinelAuth Design System: LoginScreen
 * Hardened Duty Officer Authentication & Checkpoint Terminal Session Gateway.
 * - Admin-provisioned account entry
 * - 5-attempt rate limiting & 15-minute lockout display
 * - 15-minute terminal inactivity notice
 * - In-memory access token storage (no localStorage/sessionStorage)
 */
export function LoginScreen({ onLogin, soundEnabled = true }) {
  const { login, inactivityNotice, clearInactivityNotice } = useAuth();

  const [usernameInput, setUsernameInput] = useState('');
  const [stationId, setStationId] = useState('hyderabad-rgia');
  const [passcode, setPasscode] = useState('');
  const [rememberSession, setRememberSession] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [authError, setAuthError] = useState('');
  const [isLocked, setIsLocked] = useState(false);


  useEffect(() => {
    if (inactivityNotice) {
      setAuthError(inactivityNotice);
    }
  }, [inactivityNotice]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setAuthError('');
    setIsLocked(false);

    if (!usernameInput.trim()) {
      setAuthError('Officer Username / Badge ID is required.');
      return;
    }

    if (!passcode.trim()) {
      setAuthError('Security passcode is required.');
      return;
    }

    setIsLoading(true);
    if (soundEnabled) sounds.playClick();

    try {
      const { user, mustChangePassword } = await login(usernameInput.trim(), passcode.trim(), stationId);
      setIsLoading(false);
      if (clearInactivityNotice) clearInactivityNotice();

      const selectedLoc = CHECKPOINT_LOCATIONS.find((l) => l.id === (user.station_id || stationId));
      if (onLogin) {
        onLogin({
          badgeId: user.badge_id || usernameInput.trim().toUpperCase(),
          officerName: user.officer_name || usernameInput.trim(),
          stationId: user.station_id || stationId,
          stationName: selectedLoc?.name || 'Border Checkpoint Terminal',
          role: user.role || 'officer',
          mustChangePassword: !!mustChangePassword
        });
      }
      if (soundEnabled) sounds.playSuccess();
    } catch (err) {
      setIsLoading(false);
      if (soundEnabled) sounds.playWarning();
      const errMsg = err.message || 'Authentication failed.';
      setAuthError(errMsg);

      // Detect account lockout response (HTTP 423 or "locked" in message)
      if (errMsg.toLowerCase().includes('locked') || errMsg.includes('423')) {
        setIsLocked(true);
      }
    }
  };

  return (
    <div className="min-h-[85vh] flex items-center justify-center py-8 px-4 sm:px-6">
      <div className="w-full max-w-md space-y-4">
        {/* Terminal Header Info */}
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 bg-[#D9A441] rounded-[2px]" />
            <span className="font-mono text-xs font-bold tracking-wider uppercase text-[#E4E7EB]">
              Terminal Clearance Gateway
            </span>
          </div>
          <StatusDot status="ready" label="Gateway Online" />
        </div>

        {/* Main Authentication Panel */}
        <Panel className="border border-[#232B38] bg-[#141A22] rounded-none shadow-none">
          <div className="p-6 border-b border-[#232B38] bg-[#10151C] text-center space-y-3">
            <div className="w-12 h-12 mx-auto bg-[#141A22] border border-[#232B38] flex items-center justify-center text-[#D9A441]">
              <ShieldCheck className="w-7 h-7" aria-hidden="true" />
            </div>

            <div>
              <h2 className="text-base font-bold text-[#E4E7EB] font-sans tracking-tight">
                SentinelAuth Console Operations
              </h2>
              <p className="text-[11px] font-mono text-[#8A93A3] mt-0.5">
                Ministry of Home Affairs / SSB Police II Division
              </p>
            </div>

            <div className="flex items-center justify-center gap-2 pt-1">
              <Badge variant="warning" size="sm">SIH #26188</Badge>
              <Badge variant="neutral" size="sm">Admin Provisioned</Badge>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            {/* Inactivity Notice Banner */}
            {inactivityNotice && (
              <div
                role="alert"
                className="p-3 border border-[#D9A441] bg-[#D9A441]/10 text-xs font-mono text-[#D9A441] flex items-start justify-between gap-2"
              >
                <div className="flex items-start gap-2">
                  <Clock className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
                  <div>
                    <span className="font-bold block">Session Expired</span>
                    <span className="text-[11px] text-[#E4E7EB]/90">{inactivityNotice}</span>
                  </div>
                </div>
                {clearInactivityNotice && (
                  <button
                    type="button"
                    onClick={clearInactivityNotice}
                    className="text-[10px] uppercase font-bold text-[#D9A441] hover:underline"
                  >
                    Dismiss
                  </button>
                )}
              </div>
            )}

            {/* Lockout Notice Banner */}
            {isLocked && (
              <div
                role="alert"
                className="p-3 border border-[#C0392B] bg-[#C0392B]/15 text-xs font-mono text-[#E74C3C] space-y-2"
              >
                <div className="flex items-center gap-2 font-bold">
                  <Lock className="w-4 h-4 shrink-0" aria-hidden="true" />
                  <span>TERMINAL CLEARANCE SUSPENDED (HTTP 423)</span>
                </div>
                <p className="text-[11px] text-[#E4E7EB]/90 leading-relaxed">
                  Account temporarily locked due to 5 consecutive failed login attempts. Access is restricted for 15 minutes.
                  Subsequent attempts are rejected even with valid credentials until the cooldown window expires.
                </p>
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={() => {
                      setIsLocked(false);
                      setAuthError('');
                    }}
                    className="text-[10px] uppercase font-bold text-[#D9A441] hover:underline cursor-pointer"
                  >
                    Dismiss & Retry with Valid Passcode
                  </button>
                </div>
              </div>
            )}

            {/* General Auth Error */}
            {authError && !isLocked && !inactivityNotice && (
              <div
                role="alert"
                className="p-3 border border-[#C0392B] bg-[#C0392B]/10 text-xs font-mono text-[#E74C3C] flex items-center gap-2"
              >
                <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
                <span>{authError}</span>
              </div>
            )}

            {/* 1. Officer Username / Badge ID Input */}
            <div className="space-y-1.5">
              <label
                htmlFor="officer-username-id"
                className="block text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]"
              >
                Officer Username / Badge ID
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-[#8A93A3]">
                  <User className="w-4 h-4" aria-hidden="true" />
                </div>
                <input
                  id="officer-username-id"
                  name="username"
                  type="text"
                  required
                  autoComplete="username"
                  value={usernameInput}
                  onChange={(e) => {
                    setUsernameInput(e.target.value);
                    if (isLocked) setIsLocked(false);
                    if (authError) setAuthError('');
                  }}
                  placeholder="e.g. demo_officer or badge ID"
                  className="w-full pl-9 pr-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-mono text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441] focus:ring-1 focus:ring-[#D9A441] transition-colors"
                />
              </div>
            </div>

            {/* 2. Checkpoint Station Select */}
            <div className="space-y-1.5">
              <label
                htmlFor="checkpoint-station"
                className="block text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]"
              >
                Assigned Border Checkpoint / Port
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-[#8A93A3]">
                  <MapPin className="w-4 h-4" aria-hidden="true" />
                </div>
                <select
                  id="checkpoint-station"
                  name="stationId"
                  value={stationId}
                  onChange={(e) => setStationId(e.target.value)}
                  className="w-full pl-9 pr-8 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-sans text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441] focus:ring-1 focus:ring-[#D9A441] cursor-pointer appearance-none"
                >
                  {CHECKPOINT_LOCATIONS.map((loc) => (
                    <option key={loc.id} value={loc.id} className="bg-[#141A22] text-[#E4E7EB]">
                      {loc.name} ({loc.type})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* 3. Terminal Passcode */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label
                  htmlFor="terminal-passcode"
                  className="block text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]"
                >
                  Security Passcode / Temp Password
                </label>
                <span className="text-[10px] font-mono text-[#8A93A3]">
                  Admin-Provisioned
                </span>
              </div>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-[#8A93A3]">
                  <KeyRound className="w-4 h-4" aria-hidden="true" />
                </div>
                <input
                  id="terminal-passcode"
                  name="passcode"
                  type="password"
                  required
                  autoComplete="current-password"
                  value={passcode}
                  onChange={(e) => {
                    setPasscode(e.target.value);
                    if (isLocked) setIsLocked(false);
                    if (authError) setAuthError('');
                  }}
                  placeholder="Enter password"
                  className="w-full pl-9 pr-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-mono text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441] focus:ring-1 focus:ring-[#D9A441] transition-colors"
                />
              </div>
            </div>

            {/* Security Notice on Token Persistence */}
            <div className="flex items-center gap-2 pt-1">
              <input
                id="remember-session"
                type="checkbox"
                checked={rememberSession}
                onChange={(e) => setRememberSession(e.target.checked)}
                className="w-4 h-4 border-[#232B38] bg-[#0B0F14] rounded-[2px] text-[#D9A441] focus:ring-[#D9A441] cursor-pointer"
              />
              <label
                htmlFor="remember-session"
                className="text-xs text-[#8A93A3] cursor-pointer select-none font-mono"
              >
                In-memory JWT session (auto-expires after 15m inactivity)
              </label>
            </div>

            {/* Sign In Button */}
            <div className="pt-2">
              <Button
                type="submit"
                variant="primary"
                size="lg"
                isLoading={isLoading}
                disabled={isLocked}
                icon={ArrowRight}
                iconPosition="right"
                className="w-full text-xs font-bold uppercase tracking-wider"
              >
                {isLocked ? 'Terminal Locked (15m Cooldown)' : 'Initialize Duty Session'}
              </Button>
            </div>
          </form>

          {/* Security & Access Guidelines */}
          <div className="border-t border-[#232B38] bg-[#10151C] p-4 space-y-2 text-xs font-mono text-[#8A93A3]">
            <div className="flex items-start gap-2">
              <Info className="w-4 h-4 text-[#D9A441] shrink-0 mt-0.5" />
              <div className="space-y-1">
                <span className="text-[#E4E7EB] font-bold block text-[11px]">
                  Account Provisioning Policy
                </span>
                <p className="text-[10px] leading-relaxed text-[#8A93A3]">
                  Accounts are created exclusively by checkpoint administrators. Newly provisioned officers receive a temporary password and must set their personal passcode on first login.
                </p>
                <p className="text-[10px] text-[#8A93A3]/70 pt-0.5">
                  Initial Terminal Bootstrap: Log in as <code className="text-[#D9A441]">admin</code> using the temporary password generated in the server startup console.
                </p>
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

export default LoginScreen;
