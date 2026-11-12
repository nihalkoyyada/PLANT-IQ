import React, { useEffect, useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './pages/LoginPage';
import { PlatformAdminLoginPage } from './pages/PlatformAdminLoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { Header } from './components/layout/Header';
import { Sidebar, NavTab } from './components/layout/Sidebar';
import { MobileNav } from './components/layout/MobileNav';
import { DashboardPage } from './pages/DashboardPage';
import { PlantsPage } from './pages/PlantsPage';
import { DevicesPage } from './pages/DevicesPage';
import { TelemetryPage } from './pages/TelemetryPage';
import { IngestionPage } from './pages/IngestionPage';
import { DataQualityPage } from './pages/DataQualityPage';
import { AnomaliesPage } from './pages/AnomaliesPage';
import { CopilotPage } from './pages/CopilotPage';
import { AdminPage } from './pages/AdminPage';
import { PlatformAdminPage } from './pages/PlatformAdminPage';
import { ReportsPage } from './pages/ReportsPage';
import { AdminDetectorsTab } from './components/admin/AdminDetectorsTab';
import { AdminUsersTab } from './components/admin/AdminUsersTab';
import { FloatingCopilot } from './components/copilot/FloatingCopilot';
import { getPlants } from './api/plants';
import { Plant } from './types';
import { CopilotPageContext } from './types/copilot';
import { Activity, Loader2, Sliders } from 'lucide-react';

export const tabToPath: Record<NavTab, string> = {
  'dashboard': '/dashboard',
  'plants': '/plants',
  'devices': '/devices',
  'telemetry': '/telemetry',
  'anomalies': '/anomalies',
  'detectors': '/detectors',
  'reports': '/reports',
  'copilot': '/copilot',
  'ingestion': '/upload',
  'quality': '/quality',
  'users': '/users',
  'admin': '/admin',
  'platform-admin': '/platform-admin',
};

export const pathToTab: Record<string, NavTab> = {
  '/dashboard': 'dashboard',
  '/plants': 'plants',
  '/devices': 'devices',
  '/telemetry': 'telemetry',
  '/anomalies': 'anomalies',
  '/detectors': 'detectors',
  '/reports': 'reports',
  '/copilot': 'copilot',
  '/upload': 'ingestion',
  '/ingestion': 'ingestion',
  '/quality': 'quality',
  '/users': 'users',
  '/user-management': 'users',
  '/admin': 'admin',
  '/platform-admin': 'platform-admin',
};

function resolveTabFromPath(path: string): NavTab | null {
  const normalized = path.toLowerCase().replace(/\/$/, '') || '/';
  if (normalized === '/' || normalized === '') return 'dashboard';
  if (normalized === '/admin-portal-login') return 'platform-admin';
  return pathToTab[normalized] || null;
}

function AppContent() {
  const { isAuthenticated, isLoading, user } = useAuth();

  // Determine initial auth mode based on URL
  const [authMode, setAuthMode] = useState<'login' | 'register' | 'platform-admin-login'>(() => {
    if (typeof window !== 'undefined') {
      const currentPath = window.location.pathname.toLowerCase().replace(/\/$/, '') || '/';
      if (
        currentPath === '/admin-portal-login' ||
        currentPath === '/admin/login' ||
        currentPath === '/platform-admin'
      ) {
        return 'platform-admin-login';
      }
      if (currentPath === '/register') {
        return 'register';
      }
    }
    return 'login';
  });

  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [prefilledEmail, setPrefilledEmail] = useState<string>('');
  const [copilotInitialPrompt, setCopilotInitialPrompt] = useState<string | null>(null);
  const [isFloatingCopilotOpen, setIsFloatingCopilotOpen] = useState<boolean>(false);
  const [floatingPrompt, setFloatingPrompt] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<NavTab>(() => {
    if (typeof window !== 'undefined') {
      const tabFromUrl = resolveTabFromPath(window.location.pathname);
      if (tabFromUrl) return tabFromUrl;
    }
    const saved = localStorage.getItem('plantiq_active_tab');
    if (saved === 'copilot') return 'dashboard';
    return (saved as NavTab) || 'dashboard';
  });
  const [plants, setPlants] = useState<Plant[]>([]);
  const [selectedPlant, setSelectedPlant] = useState<Plant | null>(null);

  const [pageContext, setPageContext] = useState<CopilotPageContext>({
    route: activeTab,
    plantId: selectedPlant?.id,
    plantName: selectedPlant?.name,
  });

  const userRole = user?.role?.toLowerCase() || 'viewer';
  const canAccessUpload = userRole === 'admin' || userRole === 'engineer' || userRole === 'super_admin';
  const canAccessAdmin = userRole === 'admin' || userRole === 'super_admin';
  const canAccessPlatformAdmin = userRole === 'super_admin';
  const isAdminConsole = activeTab === 'admin' || activeTab === 'platform-admin';

  // Synchronize route & enforce role permissions whenever user or location changes
  useEffect(() => {
    if (!isAuthenticated || !user) return;

    const role = user?.role?.toLowerCase() || 'viewer';
    const currentPath = window.location.pathname.toLowerCase().replace(/\/$/, '') || '/';
    const tabFromUrl = resolveTabFromPath(currentPath);

    // Rule 1: super_admin strictly redirects to /platform-admin upon initial login / portal entry
    if (role === 'super_admin') {
      if (
        currentPath === '/' ||
        currentPath === '/login' ||
        currentPath === '/admin-portal-login' ||
        currentPath === '/admin/login'
      ) {
        setActiveTab('platform-admin');
        window.history.replaceState(null, '', '/platform-admin');
        localStorage.setItem('plantiq_active_tab', 'platform-admin');
        return;
      }
    }

    // Rule 2: Non-super-admins can NEVER access /platform-admin or /admin-portal-login
    if (role !== 'super_admin') {
      if (
        currentPath === '/platform-admin' ||
        currentPath === '/admin-portal-login' ||
        tabFromUrl === 'platform-admin'
      ) {
        const fallback = role === 'admin' ? 'admin' : 'dashboard';
        setActiveTab(fallback);
        window.history.replaceState(null, '', tabToPath[fallback]);
        localStorage.setItem('plantiq_active_tab', fallback);
        return;
      }
    }

    // Rule 3: Engineers and Viewers can NEVER access /admin
    if (role !== 'admin' && role !== 'super_admin' && (currentPath === '/admin' || currentPath === '/users' || currentPath === '/user-management' || tabFromUrl === 'admin' || tabFromUrl === 'users')) {
      setActiveTab('dashboard');
      window.history.replaceState(null, '', '/dashboard');
      localStorage.setItem('plantiq_active_tab', 'dashboard');
      return;
    }

    // Rule 4: Viewers can NEVER access /upload or /ingestion
    if (role === 'viewer' && (currentPath === '/upload' || currentPath === '/ingestion' || tabFromUrl === 'ingestion')) {
      setActiveTab('dashboard');
      window.history.replaceState(null, '', '/dashboard');
      localStorage.setItem('plantiq_active_tab', 'dashboard');
      return;
    }

    // Rule 5: If landing on root or login when authenticated, redirect appropriately
    if (currentPath === '/' || currentPath === '/login' || currentPath === '/admin-portal-login') {
      const defaultTab = role === 'super_admin' ? 'platform-admin' : 'dashboard';
      setActiveTab(defaultTab);
      window.history.replaceState(null, '', tabToPath[defaultTab]);
      localStorage.setItem('plantiq_active_tab', defaultTab);
      return;
    }

    // Rule 6: Adopt permitted URL tab if valid
    if (tabFromUrl) {
      setActiveTab(tabFromUrl);
    }
  }, [isAuthenticated, user]);

  useEffect(() => {
    setPageContext((prev) => ({
      ...prev,
      route: activeTab,
      plantId: selectedPlant?.id || prev.plantId,
      plantName: selectedPlant?.name || prev.plantName,
    }));
  }, [activeTab, selectedPlant]);

  useEffect(() => {
    if (isAuthenticated) {
      getPlants()
        .then((data) => {
          setPlants(data);
          if (data.length > 0) {
            setSelectedPlant(data[0]);
          }
        })
        .catch((err) => {
          console.warn('Could not fetch plants on app start:', err);
        });
    }
  }, [isAuthenticated]);

  const handleSelectTab = (tab: NavTab) => {
    let allowedTab: NavTab = tab;
    if (tab === 'ingestion' && !canAccessUpload) {
      allowedTab = 'dashboard';
    } else if ((tab === 'admin' || tab === 'users') && !canAccessAdmin) {
      allowedTab = 'dashboard';
    } else if (tab === 'platform-admin' && !canAccessPlatformAdmin) {
      allowedTab = 'dashboard';
    }

    setActiveTab(allowedTab);
    localStorage.setItem('plantiq_active_tab', allowedTab);
    const targetUrl = tabToPath[allowedTab] || '/dashboard';
    if (typeof window !== 'undefined' && window.location.pathname !== targetUrl) {
      window.history.pushState(null, '', targetUrl);
    }
  };

  useEffect(() => {
    const handlePopState = () => {
      const currentPath = window.location.pathname.toLowerCase().replace(/\/$/, '') || '/';
      if (!isAuthenticated) {
        if (
          currentPath === '/admin-portal-login' ||
          currentPath === '/admin/login' ||
          currentPath === '/platform-admin'
        ) {
          setAuthMode('platform-admin-login');
        } else if (currentPath === '/register') {
          setAuthMode('register');
        } else {
          setAuthMode('login');
        }
        return;
      }

      const tabFromUrl = resolveTabFromPath(window.location.pathname);
      if (tabFromUrl) {
        handleSelectTab(tabFromUrl);
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [isAuthenticated, canAccessUpload, canAccessAdmin, canAccessPlatformAdmin]);

  const handleAskCopilot = (prompt: string, contextualData?: Partial<CopilotPageContext>) => {
    if (contextualData) {
      setPageContext((prev) => ({ ...prev, ...contextualData }));
    }
    setFloatingPrompt(prompt);
    setIsFloatingCopilotOpen(true);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#f0f4fa] flex flex-col items-center justify-center text-slate-800 font-sans">
        <div className="w-12 h-12 rounded-xl bg-[#004874] flex items-center justify-center mb-4 shadow-lg border border-sky-600/40">
          <Activity className="w-7 h-7 text-sky-300 animate-pulse" />
        </div>
        <div className="flex items-center gap-2 text-sm font-mono text-sky-900 font-semibold">
          <Loader2 className="w-4 h-4 animate-spin text-[#004874]" />
          <span>VERIFYING SCADA SESSION...</span>
        </div>
      </div>
    );
  }

  // Unauthenticated Entry Points
  if (!isAuthenticated) {
    if (authMode === 'register') {
      return (
        <RegisterPage
          onNavigateLogin={() => {
            setSuccessMessage(null);
            setAuthMode('login');
            if (typeof window !== 'undefined') {
              window.history.pushState(null, '', '/login');
            }
          }}
        />
      );
    }

    // Platform Admin Login strictly at /admin-portal-login
    if (authMode === 'platform-admin-login') {
      return (
        <PlatformAdminLoginPage
          onNavigateLogin={() => {
            setSuccessMessage(null);
            setAuthMode('login');
            if (typeof window !== 'undefined') {
              window.history.pushState(null, '', '/login');
            }
          }}
          onLoginSuccess={(role) => {
            if (role === 'super_admin') {
              setActiveTab('platform-admin');
              window.history.replaceState(null, '', '/platform-admin');
              localStorage.setItem('plantiq_active_tab', 'platform-admin');
            }
          }}
          initialEmail={prefilledEmail}
        />
      );
    }

    // SCADA Operational Login for Organization Admin, Engineer, Viewer at /login
    return (
      <LoginPage
        onNavigateRegister={() => {
          setSuccessMessage(null);
          setAuthMode('register');
          if (typeof window !== 'undefined') {
            window.history.pushState(null, '', '/register');
          }
        }}
        onNavigateAdminLogin={() => {
          setSuccessMessage(null);
          setAuthMode('platform-admin-login');
          if (typeof window !== 'undefined') {
            window.history.pushState(null, '', '/admin-portal-login');
          }
        }}
        successMessage={successMessage}
        initialEmail={prefilledEmail}
      />
    );
  }

  // Authenticated Application Shell
  return (
    <div className="min-h-screen bg-white flex flex-col font-sans">
      {/* Top Header */}
      <Header
        plants={plants}
        selectedPlant={selectedPlant}
        onSelectPlant={(plant) => setSelectedPlant(plant)}
        onNavigateTab={handleSelectTab}
      />

      {/* Main Container */}
      <div className="flex-1 flex max-w-[1600px] w-full mx-auto">
        {/* Left Sidebar (Desktop) - Strictly for SCADA Operations; hidden in Admin Consoles */}
        {!isAdminConsole && (
          <Sidebar activeTab={activeTab} onSelectTab={handleSelectTab} />
        )}

        {/* Main Content View */}
        <main className={`flex-1 p-4 md:p-6 overflow-y-auto min-w-0 ${isAdminConsole ? 'w-full' : ''}`}>
          {activeTab === 'dashboard' && (
            <DashboardPage
              onNavigateTab={(tab) => handleSelectTab(tab as NavTab)}
              onAskCopilot={handleAskCopilot}
            />
          )}
          {activeTab === 'plants' && (
            <PlantsPage onNavigateTab={(tab) => handleSelectTab(tab as NavTab)} />
          )}
          {activeTab === 'devices' && <DevicesPage onAskCopilot={handleAskCopilot} />}
          {activeTab === 'telemetry' && <TelemetryPage onAskCopilot={handleAskCopilot} />}
          {activeTab === 'anomalies' && <AnomaliesPage onAskCopilot={handleAskCopilot} />}
          {activeTab === 'reports' && <ReportsPage onAskCopilot={handleAskCopilot} />}
          {activeTab === 'copilot' && (
            <CopilotPage
              selectedPlant={selectedPlant}
              initialPrompt={copilotInitialPrompt}
              onClearInitialPrompt={() => setCopilotInitialPrompt(null)}
            />
          )}
          {activeTab === 'detectors' && (
            <div className="space-y-4">
              <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-xs flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-lg bg-[#004874] text-white flex items-center justify-center shadow-xs">
                      <Sliders className="w-4 h-4" />
                    </div>
                    <div>
                      <h1 className="text-base font-bold text-slate-900 tracking-tight flex items-center gap-2">
                        <span>Detector Registry & Calibrations</span>
                        {userRole === 'admin' || userRole === 'super_admin' ? (
                          <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded font-bold bg-sky-100 text-sky-800 border border-sky-200">
                            FULL CALIBRATION
                          </span>
                        ) : (
                          <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded font-bold bg-amber-100 text-amber-800 border border-amber-200">
                            READ-ONLY CALIBRATION VIEW
                          </span>
                        )}
                      </h1>
                    </div>
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    Inspect and run calibrated anomaly detectors, threshold configurations, canonical signal bindings, and parameter scopes for plant assets.
                  </p>
                </div>
              </div>
              <AdminDetectorsTab plants={plants} selectedPlant={selectedPlant} />
            </div>
          )}
          {activeTab === 'users' && canAccessAdmin && (
            <div className="space-y-4">
              <AdminUsersTab />
            </div>
          )}
          {activeTab === 'ingestion' && canAccessUpload && <IngestionPage />}
          {activeTab === 'quality' && <DataQualityPage />}
          {activeTab === 'admin' && canAccessAdmin && (
            <AdminPage
              plants={plants}
              selectedPlant={selectedPlant}
              onNavigateTab={handleSelectTab}
            />
          )}
          {activeTab === 'platform-admin' && canAccessPlatformAdmin && (
            <PlatformAdminPage onNavigateTab={handleSelectTab} />
          )}
        </main>
      </div>

      {/* Global Floating AI Copilot Widget across authenticated pages */}
      <FloatingCopilot
        selectedPlant={selectedPlant}
        activeTab={activeTab}
        pageContext={pageContext}
        isOpen={isFloatingCopilotOpen}
        onOpenChange={setIsFloatingCopilotOpen}
        initialPrompt={floatingPrompt}
        onClearInitialPrompt={() => setFloatingPrompt(null)}
      />

      {/* Sticky Bottom Navigation Bar (Mobile) - Only for operational pages */}
      {!isAdminConsole && (
        <MobileNav activeTab={activeTab} onSelectTab={handleSelectTab} />
      )}
    </div>
  );
}

export function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}

export default App;
