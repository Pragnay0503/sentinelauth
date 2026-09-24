import React from 'react';
import { useAuth } from '../context/AuthContext';
import { LoginScreen } from './LoginScreen';

/**
 * ProtectedRoute
 * Guards routes behind authentication.
 * - While the silent token-refresh is running (isLoading), renders a spinner.
 * - When isAuthenticated is false, renders LoginScreen in place.
 * - When authenticated, renders children normally.
 */
export function ProtectedRoute({ children, onLogin }) {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div
        className="min-h-[70vh] flex flex-col items-center justify-center gap-4"
        aria-label="Authenticating…"
      >
        <div className="w-8 h-8 border-2 border-[#D9A441] border-t-transparent rounded-full animate-spin" />
        <p className="text-xs font-mono text-[#8A93A3] tracking-widest uppercase">
          Verifying session…
        </p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginScreen onLogin={onLogin} />;
  }

  return <>{children}</>;
}

export default ProtectedRoute;

