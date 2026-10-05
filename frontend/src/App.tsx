import React, { useEffect, useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginPage } from './pages/LoginPage';
import { Header } from './components/layout/Header';
import { Sidebar, NavTab } from './components/layout/Sidebar';
import { MobileNav } from './components/layout/MobileNav';
import { DashboardPage } from './pages/DashboardPage';
import { PlantsPage } from './pages/PlantsPage';
import { DevicesPage } from './pages/DevicesPage';
import { TelemetryPage } from './pages/TelemetryPage';
import { IngestionPage } from './pages/IngestionPage';
import { DataQualityPage } from './pages/DataQualityPage';
import { getPlants } from './api/plants';
import { Plant } from './types';
import { Activity, Loader2 } from 'lucide-react';

function AppContent() {
  const { isAuthenticated, isLoading, user } = useAuth();
  const [activeTab, setActiveTab] = useState<NavTab>(() => {
    const saved = localStorage.getItem('plantiq_active_tab');
    return (saved as NavTab) || 'dashboard';
  });
  const [plants, setPlants] = useState<Plant[]>([]);
  const [selectedPlant, setSelectedPlant] = useState<Plant | null>(null);

  const userRole = user?.role?.toLowerCase() || 'viewer';
  const canAccessUpload = userRole === 'admin' || userRole === 'engineer';

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
    return <LoginPage />;
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

  return (
    <div className="min-h-screen bg-[#f0f4fa] flex flex-col font-sans">
      {/* Top Header */}
      <Header
        plants={plants}
        selectedPlant={selectedPlant}
        onSelectPlant={(plant) => setSelectedPlant(plant)}
      />

      {/* Main Container */}
      <div className="flex-1 flex max-w-[1600px] w-full mx-auto">
        {/* Left Sidebar (Desktop) */}
        <Sidebar activeTab={activeTab} onSelectTab={handleSelectTab} />

        {/* Main Content View */}
        <main className="flex-1 p-4 md:p-6 overflow-y-auto min-w-0">
          {activeTab === 'dashboard' && (
            <DashboardPage onNavigateTab={(tab) => handleSelectTab(tab as NavTab)} />
          )}
          {activeTab === 'plants' && <PlantsPage />}
          {activeTab === 'devices' && <DevicesPage />}
          {activeTab === 'telemetry' && <TelemetryPage />}
          {activeTab === 'ingestion' && canAccessUpload && <IngestionPage />}
          {activeTab === 'quality' && <DataQualityPage />}
        </main>
      </div>

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
