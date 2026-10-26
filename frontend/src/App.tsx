import React, { useEffect, useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './pages/LoginPage';
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
import { FloatingCopilot } from './components/copilot/FloatingCopilot';
import { getPlants } from './api/plants';
import { Plant } from './types';
import { CopilotPageContext } from './types/copilot';
import { Activity, Loader2 } from 'lucide-react';

function AppContent() {
  const { isAuthenticated, isLoading, user } = useAuth();
  // Unauthenticated users land directly on the Registration page first
  const [authMode, setAuthMode] = useState<'login' | 'register'>('register');
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [prefilledEmail, setPrefilledEmail] = useState<string>('');
  const [copilotInitialPrompt, setCopilotInitialPrompt] = useState<string | null>(null);
  const [isFloatingCopilotOpen, setIsFloatingCopilotOpen] = useState<boolean>(false);
  const [floatingPrompt, setFloatingPrompt] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<NavTab>(() => {
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
  const canAccessUpload = userRole === 'admin' || userRole === 'engineer';

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

  if (!isAuthenticated) {
    if (authMode === 'register') {
      return (
        <RegisterPage
          onNavigateLogin={() => {
            setSuccessMessage(null);
            setAuthMode('login');
          }}
        />
      );
    }

    return (
      <LoginPage
        onNavigateRegister={() => {
          setSuccessMessage(null);
          setAuthMode('register');
        }}
        successMessage={successMessage}
        initialEmail={prefilledEmail}
      />
    );
  }

  const handleSelectTab = (tab: NavTab) => {
    if (tab === 'ingestion' && !canAccessUpload) {
      setActiveTab('dashboard');
      localStorage.setItem('plantiq_active_tab', 'dashboard');
    } else {
      setActiveTab(tab);
      localStorage.setItem('plantiq_active_tab', tab);
    }
  };

  const handleAskCopilot = (prompt: string, contextualData?: Partial<CopilotPageContext>) => {
    if (contextualData) {
      setPageContext((prev) => ({ ...prev, ...contextualData }));
    }
    setFloatingPrompt(prompt);
    setIsFloatingCopilotOpen(true);
  };

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
        {/* Left Sidebar (Desktop) */}
        <Sidebar activeTab={activeTab} onSelectTab={handleSelectTab} />

        {/* Main Content View */}
        <main className="flex-1 p-4 md:p-6 overflow-y-auto min-w-0">
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
          {activeTab === 'copilot' && (
            <CopilotPage
              selectedPlant={selectedPlant}
              initialPrompt={copilotInitialPrompt}
              onClearInitialPrompt={() => setCopilotInitialPrompt(null)}
            />
          )}
          {activeTab === 'ingestion' && canAccessUpload && <IngestionPage />}
          {activeTab === 'quality' && <DataQualityPage />}
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

      {/* Sticky Bottom Navigation Bar (Mobile) */}
      <MobileNav activeTab={activeTab} onSelectTab={handleSelectTab} />
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
