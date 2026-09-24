import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { ScreeningPortal } from './components/ScreeningPortal';
import { AuditTrail } from './components/AuditTrail';
import { AnalyticsDashboard } from './components/AnalyticsDashboard';
import { DesignSystemShowcase } from './components/DesignSystemShowcase';
import { AdminUserManagement } from './components/AdminUserManagement';
import { ProtectedRoute } from './components/ProtectedRoute';
import { StatusDot, Badge } from './components/ui';
import { Shield } from 'lucide-react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { CHECKPOINT_LOCATIONS } from './data/locations';
import { sounds } from './utils/audio';

function getTabFromUrl() {
  if (typeof window === 'undefined') return 'screening';
  const pathname = window.location.pathname.replace(/^\/+/, '').toLowerCase();
  const params = new URLSearchParams(window.location.search);
  const queryTab = params.get('tab')?.toLowerCase();

  const validTabs = ['screening', 'audit', 'analytics', 'admin_users', 'showcase'];
  if (queryTab && validTabs.includes(queryTab)) return queryTab;
  if (pathname && validTabs.includes(pathname)) return pathname;
  if (pathname === 'admin') return 'admin_users';
  return 'screening';
}

const DEFAULT_OFFICER = {
  badgeId: 'ADM-ROOT-001',
  officerName: 'System Administrator',
  stationId: 'hyderabad-rgia',
  stationName: "Hyderabad RGIA (T1 Int'l Arrival)",
  role: 'admin',
  username: 'admin'
};

function SentinelApp() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState(getTabFromUrl);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [activeLocation, setActiveLocation] = useState('hyderabad-rgia');
  const [currentOfficer, setCurrentOfficer] = useState(DEFAULT_OFFICER);
  const [sessionStatus, setSessionStatus] = useState({
    state: 'new',
    documentCount: 0,
    sessionId: null,
  });

  // Synchronize browser history and URL when activeTab changes
  const handleTabChange = useCallback((tabId) => {
    setActiveTab(tabId);
    const path = tabId === 'screening' ? '/' : `/${tabId}`;
    if (window.location.pathname !== path) {
      window.history.pushState(null, '', path);
    }
  }, []);

  // Listen for browser Back/Forward (popstate) navigation
  useEffect(() => {
    const handlePopState = () => {
      const tab = getTabFromUrl();
      setActiveTab(tab);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  // If initial URL was /login, redirect cleanly to /
  useEffect(() => {
    if (window.location.pathname === '/login') {
      window.history.replaceState(null, '', '/');
      setActiveTab('screening');
    }
  }, []);

  // Synchronize officer details
  useEffect(() => {
    if (user) {
      const loc = CHECKPOINT_LOCATIONS.find((l) => l.id === user.station_id);
      setCurrentOfficer({
        badgeId: user.badge_id || user.username || 'ADM-ROOT-001',
        officerName: user.officer_name || user.username || 'System Administrator',
        stationId: user.station_id || 'hyderabad-rgia',
        stationName: loc?.name || "Hyderabad RGIA (T1 Int'l Arrival)",
        role: user.role || 'admin',
        username: user.username || 'admin'
      });
      if (user.station_id) {
        setActiveLocation(user.station_id);
      }
    }
  }, [user]);

  return (
    <div className="min-h-screen bg-[#0B0F14] text-[#E4E7EB] flex flex-col font-sans selection:bg-[#D9A441] selection:text-[#0B0F14]">
      {/* Header & Main Navigation */}
      <Header
        activeTab={activeTab}
        setActiveTab={handleTabChange}
        soundEnabled={soundEnabled}
        setSoundEnabled={setSoundEnabled}
        activeLocation={activeLocation}
        setActiveLocation={setActiveLocation}
        currentOfficer={currentOfficer}
        sessionStatus={sessionStatus}
      />

      {/* Main View Area - Direct Access to All Modules */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-6">
        {activeTab === 'screening' && (
          <ProtectedRoute>
            <ScreeningPortal 
              soundEnabled={soundEnabled} 
              activeLocation={activeLocation} 
              currentOfficer={currentOfficer}
              onSessionStatusChange={setSessionStatus}
            />
          </ProtectedRoute>
        )}

        {activeTab === 'audit' && (
          <ProtectedRoute>
            <AuditTrail soundEnabled={soundEnabled} />
          </ProtectedRoute>
        )}

        {activeTab === 'analytics' && (
          <ProtectedRoute>
            <AnalyticsDashboard />
          </ProtectedRoute>
        )}

        {activeTab === 'admin_users' && (
          <ProtectedRoute>
            <AdminUserManagement soundEnabled={soundEnabled} />
          </ProtectedRoute>
        )}

        {activeTab === 'showcase' && (
          <ProtectedRoute>
            <DesignSystemShowcase onBackToScreening={() => handleTabChange('screening')} />
          </ProtectedRoute>
        )}
      </main>

      {/* Security Operational Footer */}
      <footer className="border-t border-[#232B38] bg-[#10151C] py-3 text-xs text-[#8A93A3] mt-auto font-mono">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <Shield className="w-4 h-4 text-[#D9A441]" aria-hidden="true" />
            <span className="font-bold text-[#E4E7EB]">SentinelAuth v2.4</span>
            <span className="text-[#232B38]">|</span>
            <span>SIH 2026 Problem ID: <strong>26188</strong></span>
            <span className="text-[#232B38]">|</span>
            <span>Ministry of Home Affairs / SSB Police II Division</span>
          </div>

          <div className="flex items-center gap-3 text-[11px]">
            <StatusDot status="ready" label="PaddleOCR & S-MAD Online" pulse />
          </div>
        </div>
      </footer>
    </div>
  );
}

export function App() {
  return (
    <AuthProvider>
      <SentinelApp />
    </AuthProvider>
  );
}

export default App;
