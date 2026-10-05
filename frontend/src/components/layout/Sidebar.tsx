import React, { useEffect, useState } from 'react';
import {
  LayoutDashboard,
  Sun,
  Cpu,
  LineChart,
  UploadCloud,
  CheckCircle2,
  ShieldAlert,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { getQCStats } from '../../api/readings';

export type NavTab = 'dashboard' | 'plants' | 'devices' | 'telemetry' | 'ingestion' | 'quality';

interface SidebarProps {
  activeTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeTab, onSelectTab }) => {
  const { user } = useAuth();
  const userRole = user?.role?.toLowerCase() || 'viewer';
  const canAccessUpload = userRole === 'admin' || userRole === 'engineer';
  const [stats, setStats] = useState<{ total_readings: number; active_channels: number } | null>(null);

  useEffect(() => {
    if (user) {
      getQCStats()
        .then((s) => setStats(s))
        .catch(() => setStats(null));
    }
  }, [user]);

  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'plants', label: 'Plants', icon: Sun },
    { id: 'devices', label: 'Devices / Inverters', icon: Cpu },
    { id: 'telemetry', label: 'Telemetry Explorer', icon: LineChart },
    ...(canAccessUpload ? [{ id: 'ingestion', label: 'Upload & Mapping', icon: UploadCloud }] : []),
    { id: 'quality', label: 'Data Quality & QC', icon: CheckCircle2 },
  ] as const;

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
        <div className="bg-sky-50/80 p-3 rounded-xl border border-sky-100">
          <div className="flex items-center gap-2 mb-1">
            <ShieldAlert className="w-4 h-4 text-emerald-600" />
            <span className="text-xs font-bold text-slate-800">SCADA Ingest</span>
          </div>
          <p className="text-[11px] text-slate-600 font-mono mb-2">
            {stats
              ? `${stats.total_readings.toLocaleString()} readings • ${stats.active_channels} channels active`
              : '0 readings • 0 channels active'}
          </p>
          <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
            <div className="bg-emerald-500 h-full w-full rounded-full" />
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
