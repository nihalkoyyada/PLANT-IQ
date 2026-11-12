import React, { useEffect, useState, useCallback } from 'react';
import {
  LayoutDashboard,
  Sun,
  Cpu,
  LineChart,
  UploadCloud,
  CheckCircle2,
  ShieldAlert,
  Sliders,
  Users,
  FileText,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { getQCStats } from '../../api/readings';
import { useActiveDatasets } from '../../utils/activeDataset';

export type NavTab = 'dashboard' | 'plants' | 'devices' | 'telemetry' | 'anomalies' | 'copilot' | 'ingestion' | 'quality' | 'admin' | 'platform-admin' | 'detectors' | 'users' | 'reports';

interface SidebarProps {
  activeTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, onSelectTab }) => {
  const { user } = useAuth();
  const { activeDatasets, activeSources, allFilesSummary } = useActiveDatasets();
  const userRole = user?.role?.toLowerCase() || 'viewer';
  const canAccessUpload = userRole === 'admin' || userRole === 'engineer' || userRole === 'super_admin';
  const canAccessUserManagement = userRole === 'admin' || userRole === 'super_admin';
  const [stats, setStats] = useState<{ total_readings: number; active_channels: number } | null>(null);

  const fetchStats = useCallback(() => {
    if (user) {
      getQCStats()
        .then((s) => setStats(s))
        .catch(() => setStats(null));
    }
  }, [user]);

  useEffect(() => {
    fetchStats();
    const handleUpdate = () => {
      fetchStats();
    };
    window.addEventListener('plantiq:datasets-updated', handleUpdate);
    window.addEventListener('plantiq:ingested', handleUpdate);
    return () => {
      window.removeEventListener('plantiq:datasets-updated', handleUpdate);
      window.removeEventListener('plantiq:ingested', handleUpdate);
    };
  }, [fetchStats]);

  // Compute dynamic readings and channels based on active dataset selection
  const pool = activeSources.length > 0 ? activeSources : allFilesSummary;
  const activeSourcesFiltered = pool.filter((s) =>
    activeDatasets.some((name) =>
      name.toLowerCase() === s.original_name.toLowerCase() ||
      s.original_name.toLowerCase().includes(name.toLowerCase()) ||
      name.toLowerCase().includes(s.original_name.toLowerCase())
    )
  );

  const isMerged = activeDatasets.length > 1;

  let displayReadings = stats?.total_readings ?? 0;
  let displayChannels = stats?.active_channels ?? 0;

  if (activeSourcesFiltered.length > 0) {
    displayReadings = activeSourcesFiltered.reduce((sum, s) => sum + (s.readings_count || 0), 0);
    displayChannels = activeSourcesFiltered.reduce((sum, s) => sum + (s.channels_count || 0), 0);
  } else if (activeDatasets.length === 0) {
    displayReadings = stats?.total_readings ?? 0;
    displayChannels = stats?.active_channels ?? 0;
  } else if (stats && stats.total_readings > 0) {
    displayReadings = stats.total_readings;
    displayChannels = stats.active_channels;
  } else {
    displayReadings = 0;
    displayChannels = 0;
  }

  const feedLabel = activeDatasets.length === 0
    ? 'No Active Feed'
    : isMerged
    ? `Merged (${activeDatasets.length} Datasets)`
    : activeDatasets[0] || activeSources[0]?.original_name || allFilesSummary[0]?.original_name || 'Plant_1_Generation_Data.csv';

  // Strictly operational SCADA navigation items.
  // Administrative panels (Admin Panel, Platform Admin) are never in the operational sidebar.
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'plants', label: 'Plants', icon: Sun },
    { id: 'devices', label: 'Devices / Inverters', icon: Cpu },
    { id: 'telemetry', label: 'Telemetry Explorer', icon: LineChart },
    { id: 'anomalies', label: 'Anomaly Inbox', icon: ShieldAlert },
    { id: 'detectors', label: 'Detector Registry', icon: Sliders },
    { id: 'reports', label: 'Reports', icon: FileText },
    ...(canAccessUpload ? [{ id: 'ingestion', label: 'Upload & Mapping', icon: UploadCloud }] : []),
    { id: 'quality', label: 'Data Quality & QC', icon: CheckCircle2 },
    ...(canAccessUserManagement ? [{ id: 'users', label: 'User Management', icon: Users }] : []),
  ];

  return (
    <aside className="hidden md:flex flex-col w-60 bg-white border-r border-slate-200/80 min-h-[calc(100vh-53px)] p-3 space-y-6">
      <div className="space-y-1">
        <div className="px-3 py-1 text-[10px] font-mono font-semibold uppercase text-slate-400 tracking-wider">
          SCADA OPERATIONAL SYSTEM
        </div>

        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectTab(item.id as NavTab)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-semibold transition ${
                isActive
                  ? 'bg-[#004874] text-white shadow-xs'
                  : 'text-slate-600 hover:bg-slate-100/80 hover:text-slate-900'
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-white' : 'text-slate-500'}`} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      <div className="pt-4 border-t border-slate-100 space-y-3 mt-auto">
        <div className={`p-3 rounded-xl border transition-all ${displayReadings > 0 && activeDatasets.length > 0 ? 'bg-sky-50/80 border-sky-100' : 'bg-slate-50 border-slate-200'}`}>
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-1.5">
              <ShieldAlert className={`w-3.5 h-3.5 ${displayReadings > 0 && activeDatasets.length > 0 ? 'text-emerald-600' : 'text-slate-400'}`} />
              <span className="text-xs font-bold text-slate-800">SCADA Ingest</span>
            </div>
            <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded font-semibold uppercase ${
              displayReadings === 0 || activeDatasets.length === 0
                ? 'bg-slate-200 text-slate-600'
                : isMerged
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-sky-100 text-sky-800'
            }`}>
              {displayReadings === 0 || activeDatasets.length === 0 ? 'STANDBY' : isMerged ? 'MERGED' : 'ACTIVE'}
            </span>
          </div>
          <p className="text-[11px] text-slate-700 font-mono font-medium mb-1">
            {displayReadings.toLocaleString()} readings • {displayChannels} channels active
          </p>
          <div className="flex items-center gap-1 text-[10px] text-slate-500 font-mono mb-2" title={feedLabel}>
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${displayReadings > 0 && activeDatasets.length > 0 ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'}`} />
            <span className="truncate">{feedLabel}</span>
          </div>
          <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all duration-300 ${displayReadings > 0 && activeDatasets.length > 0 ? 'bg-emerald-500 w-full' : 'bg-slate-300 w-0'}`} />
          </div>
        </div>

        <div className="px-3 text-[10px] font-mono text-slate-400 flex items-center justify-between">
          <span>PlantIQ v2.4.0</span>
          <span className="text-emerald-600 font-semibold">• ONLINE</span>
        </div>
      </div>
    </aside>
  );
};
