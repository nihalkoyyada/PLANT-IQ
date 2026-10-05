import React from 'react';
import {
  TrendingUp,
  Boxes,
  AlertTriangle,
  Sparkles,
  FileCheck,
  FileText,
} from 'lucide-react';
import { NavTab } from './Sidebar';

interface MobileNavProps {
  activeTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
}

export const MobileNav: React.FC<MobileNavProps> = ({ activeTab, onSelectTab }) => {
  const items = [
    { id: 'dashboard', label: 'Overview', icon: TrendingUp },
    { id: 'devices', label: 'Assets', icon: Boxes },
    { id: 'quality', label: 'Anomalies', icon: AlertTriangle },
    { id: 'ingestion', label: 'Mapping', icon: FileCheck },
    { id: 'telemetry', label: 'Reports', icon: FileText },
  ] as const;

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-white border-t border-slate-200 px-2 py-1.5 flex items-center justify-around shadow-lg">
      {items.map((item) => {
        const Icon = item.icon;
        const isActive = activeTab === item.id;
        return (
          <button
            key={item.id}
            onClick={() => onSelectTab(item.id as NavTab)}
            className={`flex flex-col items-center py-1 px-3 rounded-lg transition ${
              isActive ? 'text-[#004874] font-bold' : 'text-slate-500 font-medium'
            }`}
          >
            <Icon className={`w-5 h-5 ${isActive ? 'text-[#004874]' : 'text-slate-400'}`} />
            <span className="text-[10px] mt-0.5 tracking-tight">{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
};
