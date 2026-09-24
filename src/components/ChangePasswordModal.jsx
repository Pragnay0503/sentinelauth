import React, { useState } from 'react';
import { KeyRound, ShieldAlert, CheckCircle2, XCircle, ArrowRight, LogOut } from 'lucide-react';
import { Panel, PanelHeader, PanelBody, Button, Badge } from './ui';
import { useAuth } from '../context/AuthContext';
import { sounds } from '../utils/audio';

export function ChangePasswordModal({ soundEnabled = true, onPasswordChanged }) {
  const { user, changePassword, logout } = useAuth();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // Password rules validation
  const rules = [
    { label: 'Minimum 12 characters', valid: newPassword.length >= 12 },
    { label: 'At least one uppercase letter (A-Z)', valid: /[A-Z]/.test(newPassword) },
    { label: 'At least one lowercase letter (a-z)', valid: /[a-z]/.test(newPassword) },
    { label: 'At least one numeric digit (0-9)', valid: /[0-9]/.test(newPassword) },
    { label: 'At least one special symbol (!@#$%^&*)', valid: /[^A-Za-z0-9]/.test(newPassword) },
    { label: 'Passwords match', valid: newPassword && newPassword === confirmPassword },
  ];

  const allRulesPassed = rules.every((r) => r.valid);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMessage('');

    if (!currentPassword) {
      setErrorMessage('Current / temporary password is required.');
      return;
    }

    if (!allRulesPassed) {
      setErrorMessage('Please satisfy all password security requirements above.');
      return;
    }

    if (currentPassword === newPassword) {
      setErrorMessage('New password cannot be identical to current temporary password.');
      return;
    }

    setIsLoading(true);
    if (soundEnabled) sounds.playClick();

    try {
      await changePassword(currentPassword, newPassword);
      setIsLoading(false);
      if (soundEnabled) sounds.playSuccess();
      if (onPasswordChanged) onPasswordChanged();
    } catch (err) {
      setIsLoading(false);
      if (soundEnabled) sounds.playWarning();
      setErrorMessage(err.message || 'Failed to update password.');
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#0B0F14]/90 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-lg space-y-4">
        {/* Terminal Header Info */}
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 bg-[#D9A441] rounded-[2px]" />
            <span className="font-mono text-xs font-bold tracking-wider uppercase text-[#E4E7EB]">
              Mandatory Security Clearance Initialization
            </span>
          </div>
          <Badge variant="danger" size="sm">Password Change Required</Badge>
        </div>

        <Panel className="border border-[#232B38] bg-[#141A22] rounded-none shadow-2xl">
          <div className="p-6 border-b border-[#232B38] bg-[#10151C] text-center space-y-2">
            <div className="w-12 h-12 mx-auto bg-[#D9A441]/10 border border-[#D9A441]/40 flex items-center justify-center text-[#D9A441]">
              <KeyRound className="w-6 h-6" aria-hidden="true" />
            </div>

            <h2 className="text-base font-bold text-[#E4E7EB] font-sans">
              Set Your New Security Passcode
            </h2>
            <p className="text-xs text-[#8A93A3] max-w-sm mx-auto leading-relaxed">
              Officer <strong className="text-[#E4E7EB]">{user?.officer_name || user?.username}</strong>, you have logged in with an admin-issued temporary password. SentinelAuth security protocol requires creating a personal passcode before console clearance is granted.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            {errorMessage && (
              <div
                role="alert"
                className="p-3 border border-[#C0392B] bg-[#C0392B]/10 text-xs font-mono text-[#E74C3C] flex items-center gap-2"
              >
                <ShieldAlert className="w-4 h-4 shrink-0" />
                <span>{errorMessage}</span>
              </div>
            )}

            {/* Current / Temporary Password */}
            <div className="space-y-1.5">
              <label
                htmlFor="current-temp-password"
                className="block text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]"
              >
                Current / Temporary Password
              </label>
              <input
                id="current-temp-password"
                type="password"
                required
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Enter current or temporary password"
                className="w-full px-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-mono text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441] focus:ring-1 focus:ring-[#D9A441] transition-colors"
              />
            </div>

            {/* New Password */}
            <div className="space-y-1.5">
              <label
                htmlFor="new-password"
                className="block text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]"
              >
                New Personal Passcode (Min 12 Chars)
              </label>
              <input
                id="new-password"
                type="password"
                required
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Must include uppercase, lowercase, number & symbol"
                className="w-full px-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-mono text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441] focus:ring-1 focus:ring-[#D9A441] transition-colors"
              />
            </div>

            {/* Confirm New Password */}
            <div className="space-y-1.5">
              <label
                htmlFor="confirm-password"
                className="block text-xs font-mono font-bold uppercase tracking-wider text-[#8A93A3]"
              >
                Confirm New Passcode
              </label>
              <input
                id="confirm-password"
                type="password"
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter new passcode"
                className="w-full px-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-mono text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441] focus:ring-1 focus:ring-[#D9A441] transition-colors"
              />
            </div>

            {/* Live Password Rules Checklist */}
            <div className="p-3 bg-[#0B0F14] border border-[#232B38] rounded-[4px] space-y-1.5 text-[11px] font-mono">
              <span className="text-[10px] uppercase font-bold text-[#8A93A3] block pb-0.5">
                Passcode Complexity Requirements:
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                {rules.map((rule, idx) => (
                  <div key={idx} className="flex items-center gap-1.5">
                    {rule.valid ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-[#3F9868] shrink-0" />
                    ) : (
                      <XCircle className="w-3.5 h-3.5 text-[#8A93A3] shrink-0" />
                    )}
                    <span className={rule.valid ? 'text-[#3F9868]' : 'text-[#8A93A3]'}>
                      {rule.label}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Action Buttons */}
            <div className="pt-2 flex items-center gap-3">
              <Button
                type="submit"
                variant="primary"
                size="lg"
                isLoading={isLoading}
                disabled={!allRulesPassed || !currentPassword}
                icon={ArrowRight}
                iconPosition="right"
                className="flex-1 text-xs font-bold uppercase tracking-wider"
              >
                Set Passcode & Enter Console
              </Button>

              <Button
                type="button"
                variant="secondary"
                size="lg"
                onClick={() => logout()}
                icon={LogOut}
                className="text-xs font-bold uppercase tracking-wider text-[#8A93A3]"
              >
                Sign Out
              </Button>
            </div>
          </form>
        </Panel>
      </div>
    </div>
  );
}

export default ChangePasswordModal;
