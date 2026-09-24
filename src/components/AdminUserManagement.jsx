import React, { useState, useEffect, useCallback } from 'react';
import { 
  Users, 
  UserPlus, 
  KeyRound, 
  UserX, 
  UserCheck, 
  Shield, 
  ShieldAlert, 
  Copy, 
  Check, 
  RefreshCw,
  AlertTriangle,
  Clock,
  MapPin,
  X
} from 'lucide-react';
import { Panel, PanelHeader, PanelBody, Button, Badge, StatusDot } from './ui';
import { CHECKPOINT_LOCATIONS } from '../data/locations';
import { useAuth } from '../context/AuthContext';
import { sounds } from '../utils/audio';

export function AdminUserManagement({ soundEnabled = true }) {
  const { accessToken, csrfToken, user: currentUser } = useAuth();

  const [users, setUsers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');
  const [actionSuccessMsg, setActionSuccessMsg] = useState('');

  // Modals state
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [revealedCredentials, setRevealedCredentials] = useState(null);
  const [copied, setCopied] = useState(false);

  // New user form state
  const [newUsername, setNewUsername] = useState('');
  const [newOfficerName, setNewOfficerName] = useState('');
  const [newBadgeId, setNewBadgeId] = useState('');
  const [newRole, setNewRole] = useState('officer');
  const [newStationId, setNewStationId] = useState('hyderabad-rgia');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  // Fetch users list
  const fetchUsers = useCallback(async () => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      const res = await fetch('http://localhost:8000/api/admin/users', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'X-CSRF-Token': csrfToken || ''
        },
        credentials: 'include'
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to fetch users.' }));
        throw new Error(err.detail || `HTTP error ${res.status}`);
      }

      const data = await res.json();
      setUsers(data);
    } catch (err) {
      setErrorMsg(err.message || 'Error loading officers list.');
    } finally {
      setIsLoading(false);
    }
  }, [accessToken, csrfToken]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  // Handle Create User
  const handleCreateUser = async (e) => {
    e.preventDefault();
    setFormError('');
    setIsSubmitting(true);
    if (soundEnabled) sounds.playClick();

    try {
      const res = await fetch('http://localhost:8000/api/admin/users', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${accessToken}`,
          'X-CSRF-Token': csrfToken || ''
        },
        credentials: 'include',
        body: JSON.stringify({
          username: newUsername.trim(),
          officer_name: newOfficerName.trim() || undefined,
          badge_id: newBadgeId.trim() || undefined,
          role: newRole,
          checkpoint_id: newStationId,
          station_id: newStationId
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to create user.' }));
        throw new Error(err.detail || `HTTP error ${res.status}`);
      }

      const data = await res.json();
      setIsSubmitting(false);
      setIsCreateModalOpen(false);

      // Reset form
      setNewUsername('');
      setNewOfficerName('');
      setNewBadgeId('');

      // Show temporary credentials modal
      setRevealedCredentials({
        username: data.user.username,
        badge_id: data.user.badge_id,
        temporary_password: data.temporary_password,
        actionTitle: 'New Officer Provisioned Successfully'
      });

      if (soundEnabled) sounds.playSuccess();
      fetchUsers();
    } catch (err) {
      setIsSubmitting(false);
      if (soundEnabled) sounds.playWarning();
      setFormError(err.message);
    }
  };

  // Handle Reset Password
  const handleResetPassword = async (user) => {
    if (!window.confirm(`Generate a new temporary password for officer ${user.officer_name || user.username} (${user.badge_id})?`)) {
      return;
    }

    if (soundEnabled) sounds.playClick();
    try {
      const res = await fetch(`http://localhost:8000/api/admin/users/${user.id}/reset-password`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'X-CSRF-Token': csrfToken || ''
        },
        credentials: 'include'
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to reset password.' }));
        throw new Error(err.detail || `HTTP error ${res.status}`);
      }

      const data = await res.json();
      setRevealedCredentials({
        username: data.username,
        badge_id: user.badge_id,
        temporary_password: data.temporary_password,
        actionTitle: 'Temporary Password Reset Generated'
      });

      if (soundEnabled) sounds.playSuccess();
      fetchUsers();
    } catch (err) {
      if (soundEnabled) sounds.playWarning();
      alert(`Error: ${err.message}`);
    }
  };

  // Handle Toggle Active
  const handleToggleActive = async (user) => {
    const action = user.active ? 'deactivate' : 'reactivate';
    if (!window.confirm(`Are you sure you want to ${action} ${user.username} (${user.badge_id})?`)) {
      return;
    }

    if (soundEnabled) sounds.playClick();
    try {
      const res = await fetch(`http://localhost:8000/api/admin/users/${user.id}/toggle-active`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'X-CSRF-Token': csrfToken || ''
        },
        credentials: 'include'
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to update user status.' }));
        throw new Error(err.detail || `HTTP error ${res.status}`);
      }

      const data = await res.json();
      setActionSuccessMsg(data.message);
      setTimeout(() => setActionSuccessMsg(''), 4000);
      if (soundEnabled) sounds.playSuccess();
      fetchUsers();
    } catch (err) {
      if (soundEnabled) sounds.playWarning();
      alert(`Error: ${err.message}`);
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <div className="space-y-6">
      {/* Top Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#232B38] pb-4">
        <div>
          <div className="flex items-center gap-2">
            <Shield className="w-5 h-5 text-[#D9A441]" aria-hidden="true" />
            <h2 className="text-lg font-bold text-[#E4E7EB] font-sans">
              Duty Officer Provisioning & Terminal Access
            </h2>
            <Badge variant="warning" size="sm">Admin Only</Badge>
          </div>
          <p className="text-xs text-[#8A93A3] mt-1 font-mono">
            Manage authorized checkpoint operators, provision temporary passcodes, and enforce credential lifecycle.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={fetchUsers}
            icon={RefreshCw}
            disabled={isLoading}
          >
            Refresh Roster
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setFormError('');
              setIsCreateModalOpen(true);
              if (soundEnabled) sounds.playClick();
            }}
            icon={UserPlus}
          >
            Provision Officer
          </Button>
        </div>
      </div>

      {/* Action Success Toast */}
      {actionSuccessMsg && (
        <div className="p-3 border border-[#3F9868] bg-[#3F9868]/15 text-xs font-mono text-[#3F9868] flex items-center gap-2 rounded-[4px]">
          <Check className="w-4 h-4 shrink-0" />
          <span>{actionSuccessMsg}</span>
        </div>
      )}

      {/* Error Alert */}
      {errorMsg && (
        <div className="p-3 border border-[#C0392B] bg-[#C0392B]/15 text-xs font-mono text-[#E74C3C] flex items-center gap-2 rounded-[4px]">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Officers Table Panel */}
      <Panel className="border border-[#232B38] bg-[#141A22] rounded-none shadow-none">
        <PanelHeader className="p-4 border-b border-[#232B38] bg-[#10151C] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-[#D9A441]" />
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-[#E4E7EB]">
              Authorized Checkpoint Personnel ({users.length})
            </span>
          </div>
          <StatusDot status={isLoading ? 'loading' : 'ready'} label={isLoading ? 'Synchronizing...' : 'Live Directory'} />
        </PanelHeader>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse font-mono text-xs">
            <thead>
              <tr className="border-b border-[#232B38] bg-[#0B0F14] text-[11px] text-[#8A93A3] uppercase tracking-wider">
                <th className="py-3 px-4">Officer / Service ID</th>
                <th className="py-3 px-4">Role</th>
                <th className="py-3 px-4">Assigned Port</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">PW Status</th>
                <th className="py-3 px-4">Last Login</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#232B38] text-[#E4E7EB]">
              {users.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-[#8A93A3]">
                    No officers provisioned. Click "Provision Officer" to create an account.
                  </td>
                </tr>
              )}

              {users.map((u) => {
                const loc = CHECKPOINT_LOCATIONS.find((l) => l.id === u.station_id);
                return (
                  <tr key={u.id} className="hover:bg-[#1A222C]/60 transition-colors">
                    <td className="py-3 px-4">
                      <div className="font-sans font-bold text-sm text-[#E4E7EB]">
                        {u.officer_name || u.username}
                      </div>
                      <div className="text-[11px] text-[#8A93A3] font-mono flex items-center gap-1.5">
                        <span>@{u.username}</span>
                        <span>•</span>
                        <span className="text-[#D9A441]">{u.badge_id}</span>
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      <Badge 
                        variant={u.role === 'admin' ? 'warning' : u.role === 'supervisor' ? 'primary' : 'neutral'} 
                        size="sm"
                      >
                        {u.role.toUpperCase()}
                      </Badge>
                    </td>

                    <td className="py-3 px-4 text-xs font-sans">
                      <div className="flex items-center gap-1 text-[#E4E7EB]">
                        <MapPin className="w-3 h-3 text-[#D9A441] shrink-0" />
                        <span className="truncate max-w-[140px]">{loc?.name || u.station_id}</span>
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      {u.active ? (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[2px] text-[10px] bg-[#3F9868]/20 text-[#3F9868] border border-[#3F9868]/30 font-bold">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#3F9868]" />
                          ACTIVE
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[2px] text-[10px] bg-[#C0392B]/20 text-[#E74C3C] border border-[#C0392B]/30 font-bold">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#E74C3C]" />
                          DEACTIVATED
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-4">
                      {u.must_change_password ? (
                        <Badge variant="danger" size="sm">Temp Password</Badge>
                      ) : (
                        <Badge variant="success" size="sm">Verified</Badge>
                      )}
                    </td>

                    <td className="py-3 px-4 text-[11px] text-[#8A93A3]">
                      {u.last_login ? (
                        <div className="flex items-center gap-1">
                          <Clock className="w-3 h-3 text-[#8A93A3]" />
                          <span>{new Date(u.last_login).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                      ) : (
                        <span className="italic text-[#8A93A3]/60">Never</span>
                      )}
                    </td>

                    <td className="py-3 px-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => handleResetPassword(u)}
                          title="Generate fresh temporary password"
                          className="px-2.5 py-1 border border-[#232B38] hover:border-[#D9A441] bg-[#0B0F14] hover:text-[#D9A441] rounded-[2px] text-[11px] font-mono transition-colors"
                        >
                          Reset PW
                        </button>

                        <button
                          type="button"
                          onClick={() => handleToggleActive(u)}
                          disabled={u.id === currentUser?.id}
                          title={u.id === currentUser?.id ? "Cannot deactivate yourself" : (u.active ? "Deactivate officer" : "Reactivate officer")}
                          className={`px-2.5 py-1 border rounded-[2px] text-[11px] font-mono transition-colors ${
                            u.active 
                              ? 'border-[#C0392B]/50 hover:border-[#C0392B] text-[#E74C3C] bg-[#C0392B]/10' 
                              : 'border-[#3F9868]/50 hover:border-[#3F9868] text-[#3F9868] bg-[#3F9868]/10'
                          } ${u.id === currentUser?.id ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
                        >
                          {u.active ? 'Deactivate' : 'Reactivate'}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ------------------------------------------------------------------- */}
      {/* Modal 1: Provision New Officer Form */}
      {/* ------------------------------------------------------------------- */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 bg-[#0B0F14]/85 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-[#141A22] border border-[#232B38] rounded-none shadow-2xl">
            <div className="p-4 border-b border-[#232B38] bg-[#10151C] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <UserPlus className="w-4 h-4 text-[#D9A441]" />
                <h3 className="text-sm font-bold text-[#E4E7EB] font-sans">
                  Provision New Checkpoint Officer
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="text-[#8A93A3] hover:text-[#E4E7EB]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateUser} className="p-5 space-y-3.5">
              {formError && (
                <div className="p-2.5 border border-[#C0392B] bg-[#C0392B]/10 text-xs font-mono text-[#E74C3C]">
                  {formError}
                </div>
              )}

              {/* Username */}
              <div className="space-y-1">
                <label className="block text-xs font-mono font-bold uppercase text-[#8A93A3]">
                  Username (Service Handle) *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. officer_deshmukh"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  className="w-full px-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-mono text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441]"
                />
              </div>

              {/* Officer Full Name */}
              <div className="space-y-1">
                <label className="block text-xs font-mono font-bold uppercase text-[#8A93A3]">
                  Screening Duty Officer Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. Insp. Rohit Deshmukh"
                  value={newOfficerName}
                  onChange={(e) => setNewOfficerName(e.target.value)}
                  className="w-full px-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-sans text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441]"
                />
              </div>

              {/* Badge ID */}
              <div className="space-y-1">
                <label className="block text-xs font-mono font-bold uppercase text-[#8A93A3]">
                  Service Badge ID (Optional - auto-generated if blank)
                </label>
                <input
                  type="text"
                  placeholder="e.g. SSB-IND-5591"
                  value={newBadgeId}
                  onChange={(e) => setNewBadgeId(e.target.value)}
                  className="w-full px-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-mono text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441]"
                />
              </div>

              {/* Role & Station */}
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="block text-xs font-mono font-bold uppercase text-[#8A93A3]">
                    Security Role
                  </label>
                  <select
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value)}
                    className="w-full px-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-sans text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441]"
                  >
                    <option value="officer">Officer (Standard)</option>
                    <option value="supervisor">Supervisor</option>
                    <option value="admin">Administrator</option>
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="block text-xs font-mono font-bold uppercase text-[#8A93A3]">
                    Assigned Port
                  </label>
                  <select
                    value={newStationId}
                    onChange={(e) => setNewStationId(e.target.value)}
                    className="w-full px-3 py-2 bg-[#0B0F14] border border-[#232B38] text-xs font-sans text-[#E4E7EB] rounded-[4px] focus:outline-none focus:border-[#D9A441]"
                  >
                    {CHECKPOINT_LOCATIONS.map((loc) => (
                      <option key={loc.id} value={loc.id}>
                        {loc.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="p-3 bg-[#0B0F14] border border-[#232B38] rounded-[4px] text-[11px] font-mono text-[#8A93A3] space-y-1">
                <span className="text-[#D9A441] font-bold block">Password Security Policy:</span>
                <span>A random temporary password will be generated automatically. It must be changed on the officer's first login.</span>
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => setIsCreateModalOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  isLoading={isSubmitting}
                >
                  Provision & Generate Credentials
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------- */}
      {/* Modal 2: One-Time Temporary Credentials Display */}
      {/* ------------------------------------------------------------------- */}
      {revealedCredentials && (
        <div className="fixed inset-0 z-50 bg-[#0B0F14]/90 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-[#141A22] border border-[#D9A441]/50 rounded-none shadow-2xl space-y-4 p-6">
            <div className="text-center space-y-2">
              <div className="w-12 h-12 mx-auto bg-[#D9A441]/10 border border-[#D9A441] flex items-center justify-center text-[#D9A441]">
                <KeyRound className="w-6 h-6" />
              </div>
              <h3 className="text-base font-bold text-[#E4E7EB] font-sans">
                {revealedCredentials.actionTitle}
              </h3>
              <p className="text-xs text-[#8A93A3]">
                Officer Account: <strong className="text-[#E4E7EB]">{revealedCredentials.username}</strong> ({revealedCredentials.badge_id})
              </p>
            </div>

            {/* Credential Box */}
            <div className="p-4 bg-[#0B0F14] border border-[#D9A441] rounded-[4px] text-center space-y-2">
              <span className="text-[10px] uppercase tracking-wider font-mono text-[#8A93A3] block">
                Plaintext Temporary Passcode (Shown Once)
              </span>
              <div className="text-xl font-mono font-bold tracking-widest text-[#D9A441] select-all py-1">
                {revealedCredentials.temporary_password}
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => copyToClipboard(revealedCredentials.temporary_password)}
                icon={copied ? Check : Copy}
                className="w-full text-xs font-mono"
              >
                {copied ? 'Passcode Copied to Clipboard!' : 'Copy Temporary Passcode'}
              </Button>
            </div>

            {/* Warning Alert */}
            <div className="p-3 border border-[#D9A441]/40 bg-[#D9A441]/10 text-xs font-mono text-[#D9A441] space-y-1">
              <div className="font-bold flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>Security Notice</span>
              </div>
              <p className="text-[11px] text-[#E4E7EB]/90 leading-relaxed">
                Relay this temporary password securely to the officer. It will not be stored in plaintext or displayed again. The officer will be required to change it on their first login.
              </p>
            </div>

            <Button
              type="button"
              variant="primary"
              size="lg"
              onClick={() => setRevealedCredentials(null)}
              className="w-full text-xs font-bold uppercase tracking-wider"
            >
              I Have Recorded This Passcode
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default AdminUserManagement;
