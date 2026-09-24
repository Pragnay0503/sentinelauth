import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';

const AuthContext = createContext(null);

const API_BASE = 'http://localhost:8000';

/**
 * AuthProvider
 * - Stores JWT access token in React state only (never localStorage/sessionStorage).
 * - On mount, attempts a silent token refresh via the httpOnly refresh-token cookie.
 * - Attaches "Authorization: Bearer <token>" on every authenticated API call.
 * - Clears the session and redirects to login on any 401 response.
 * - Provides login(), logout(), changePassword(), authFetch(), and refreshSession().
 */
export function AuthProvider({ children }) {
  const [accessToken, setAccessToken] = useState(null);
  const [csrfToken, setCsrfToken] = useState(null);
  const [user, setUser] = useState(null);
  // true while we attempt silent refresh on mount
  const [isLoading, setIsLoading] = useState(true);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [inactivityNotice, setInactivityNotice] = useState(null);
  const [logoutToast, setLogoutToast] = useState(null);

  // Ref so callbacks always see the latest token without stale closures
  const accessTokenRef = useRef(null);
  useEffect(() => {
    accessTokenRef.current = accessToken;
  }, [accessToken]);

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  const _clearSession = useCallback(() => {
    setAccessToken(null);
    setCsrfToken(null);
    setUser(null);
    setMustChangePassword(false);
    accessTokenRef.current = null;
  }, []);

  const _applySession = useCallback((data) => {
    setAccessToken(data.access_token);
    accessTokenRef.current = data.access_token;
    if (data.csrf_token) setCsrfToken(data.csrf_token);
    if (data.user) setUser(data.user);
    setMustChangePassword(!!data.must_change_password);
  }, []);

  // ---------------------------------------------------------------------------
  // Silent refresh — sends the httpOnly refresh-token cookie to get a new access token
  // ---------------------------------------------------------------------------
  const _silentRefresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) return false;
      const data = await res.json();
      if (data.access_token) {
        _applySession(data);
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, [_applySession]);

  // On mount: attempt silent refresh so a page reload doesn't force re-login
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await _silentRefresh();
      if (!cancelled) setIsLoading(false);
    })();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // authFetch — authenticated fetch wrapper used by all API calls
  // ---------------------------------------------------------------------------
  const authFetch = useCallback(
    async (url, options = {}) => {
      const token = accessTokenRef.current;
      const headers = { ...(options.headers || {}) };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch(url, { ...options, headers, credentials: 'include' });

      if (response.status === 401) {
        // One silent retry before giving up
        const refreshed = await _silentRefresh();
        if (refreshed) {
          headers['Authorization'] = `Bearer ${accessTokenRef.current}`;
          return fetch(url, { ...options, headers, credentials: 'include' });
        }
        _clearSession();
        setInactivityNotice('Your session has expired. Please log in again.');
      }

      return response;
    },
    [_silentRefresh, _clearSession]
  );

  // ---------------------------------------------------------------------------
  // login(username, password, stationId)
  // ---------------------------------------------------------------------------
  const login = useCallback(async (username, password, stationId) => {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: username.trim(),
        password,
        station_id: stationId || undefined,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Login failed (HTTP ${res.status})`);
    }

    const data = await res.json();
    _applySession(data);
    return { user: data.user, mustChangePassword: !!data.must_change_password };
  }, [_applySession]);

  // ---------------------------------------------------------------------------
  // logout — revokes server-side, clears cookies, clears local state
  // ---------------------------------------------------------------------------
  const logout = useCallback(async () => {
    try {
      const token = accessTokenRef.current;
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch {
      // best-effort
    } finally {
      _clearSession();
      setLogoutToast('You have been logged out successfully.');
    }
  }, [_clearSession]);

  // ---------------------------------------------------------------------------
  // changePassword — posts old+new password, applies fresh tokens from response
  // ---------------------------------------------------------------------------
  const changePassword = useCallback(async (currentPassword, newPassword) => {
    const token = accessTokenRef.current;
    const res = await fetch(`${API_BASE}/api/auth/change-password`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Password change failed.');
    }

    const data = await res.json();
    _applySession(data);
    return data;
  }, [_applySession]);

  // ---------------------------------------------------------------------------
  // refreshSession — public helper called by inactivity timer etc.
  // ---------------------------------------------------------------------------
  const refreshSession = useCallback(async () => {
    const ok = await _silentRefresh();
    return ok ? accessTokenRef.current : null;
  }, [_silentRefresh]);

  // ---------------------------------------------------------------------------
  // Context value
  // ---------------------------------------------------------------------------
  const value = {
    user,
    accessToken,
    csrfToken,
    isAuthenticated: !!accessToken,
    isLoading,
    inactivityNotice,
    clearInactivityNotice: () => setInactivityNotice(null),
    logoutToast,
    clearLogoutToast: () => setLogoutToast(null),
    mustChangePassword,
    setMustChangePassword,
    login,
    logout,
    changePassword,
    refreshSession,
    authFetch,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export default AuthContext;

