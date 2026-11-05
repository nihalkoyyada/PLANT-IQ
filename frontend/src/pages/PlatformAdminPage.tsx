import React, { useState } from 'react';
import {
  Activity,
  ArrowLeft,
  Building2,
  Globe,
  HardDrive,
  History,
  Lock,
  Server,
  ShieldAlert,
  ShieldCheck,
  Sliders,
  Sun,
  Users,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { NavTab } from '../components/layout/Sidebar';
import { PlatformOverviewTab } from '../components/platform/PlatformOverviewTab';
import { PlatformOrgsTab } from '../components/platform/PlatformOrgsTab';
import { PlatformUsersTab } from '../components/platform/PlatformUsersTab';
import { PlatformPlantsTab } from '../components/platform/PlatformPlantsTab';
import { PlatformMonitoringTab } from '../components/platform/PlatformMonitoringTab';
import { PlatformAuditLogsTab } from '../components/platform/PlatformAuditLogsTab';
import { PlatformSettingsTab } from '../components/platform/PlatformSettingsTab';

export type PlatformSubTab =
  | 'overview'
  | 'orgs'
  | 'users'
  | 'plants'
  | 'monitoring'
  | 'audit'
  | 'settings';

interface PlatformAdminPageProps {
  onNavigateTab?: (tab: NavTab) => void;
}

export const PlatformAdminPage: React.FC<PlatformAdminPageProps> = ({ onNavigateTab }) => {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<PlatformSubTab>('overview');

  const userRole = user?.role?.toLowerCase() || 'viewer';
  const isSuperAdmin = userRole === 'super_admin';

  if (!isSuperAdmin) {
    return (
      <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center max-w-lg mx-auto mt-12 shadow-xs">
        <div className="w-12 h-12 rounded-full bg-rose-100 text-rose-600 flex items-center justify-center mx-auto mb-4">
          <Lock className="w-6 h-6" />
        </div>
        <h2 className="text-base font-bold text-slate-900 mb-2">Platform Access Restricted</h2>
        <p className="text-xs text-slate-600 leading-relaxed mb-4">
          The Platform Super Admin Console is strictly reserved for root platform operators. Your current
          account role (<span className="font-mono font-bold text-slate-900">{user?.role}</span>) is
          not authorized to manage SaaS tenants or inspect global platform infrastructure.
        </p>
        <span className="text-[11px] font-mono text-slate-400">
          Organization Administrators should access the standard Organization Admin Panel.
        </span>
      </div>
    );
  }

  const tabs = [
    { id: 'overview', label: 'Platform Overview', icon: Globe },
    { id: 'orgs', label: 'Organizations', icon: Building2 },
    { id: 'users', label: 'Global Users', icon: Users },
    { id: 'plants', label: 'Plants & Assets', icon: Sun },
    { id: 'monitoring', label: 'Platform Monitoring', icon: Server },
    { id: 'audit', label: 'Global Audit Logs', icon: History },
    { id: 'settings', label: 'Platform Settings', icon: Sliders },
  ] as const;

  return (
    <div className="space-y-6">
      {/* Platform Super Admin Header Banner */}
      <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-xs flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-purple-800 to-indigo-600 text-white flex items-center justify-center shadow-xs">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <div>
              <h1 className="text-base font-bold text-slate-900 tracking-tight flex items-center gap-2">
                <span>PlantIQ Platform Administration Console</span>
                <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded font-bold bg-purple-100 text-purple-800 border border-purple-200">
                  SUPER ADMIN PLATFORM CONSOLE
                </span>
              </h1>
            </div>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            Manage multi-tenant SaaS organizations, provision initial admins, oversee cross-tenant assets, and monitor microservices.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {onNavigateTab && (
            <button
              type="button"
              onClick={() => onNavigateTab('dashboard')}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200/90 text-slate-700 rounded-lg text-xs font-semibold transition border border-slate-200 cursor-pointer shadow-xs"
            >
              <ArrowLeft className="w-3.5 h-3.5 text-slate-600" />
              <span>SCADA Operations</span>
            </button>
          )}

          <div className="px-3 py-1.5 bg-purple-50/60 border border-purple-200/60 rounded-lg text-center">
            <div className="text-[10px] font-mono text-purple-700 uppercase font-semibold">Security Level</div>
            <div className="text-xs font-bold text-purple-900 font-mono">ROOT PLATFORM</div>
          </div>
        </div>
      </div>

      {/* Tabs Selector Navigation */}
      <div className="flex items-center gap-1 border-b border-slate-200 pb-px overflow-x-auto">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as PlatformSubTab)}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold rounded-t-lg transition border-b-2 cursor-pointer whitespace-nowrap ${
                isActive
                  ? 'border-purple-700 text-purple-800 bg-purple-50/50'
                  : 'border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-purple-700' : 'text-slate-400'}`} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab Panels */}
      <div>
        {activeTab === 'overview' && (
          <PlatformOverviewTab
            onNavigateSubTab={(subTab) => setActiveTab(subTab)}
            onNavigateTab={onNavigateTab}
          />
        )}
        {activeTab === 'orgs' && <PlatformOrgsTab />}
        {activeTab === 'users' && <PlatformUsersTab />}
        {activeTab === 'plants' && <PlatformPlantsTab />}
        {activeTab === 'monitoring' && <PlatformMonitoringTab />}
        {activeTab === 'audit' && <PlatformAuditLogsTab />}
        {activeTab === 'settings' && <PlatformSettingsTab />}
      </div>
    </div>
  );
};

export default PlatformAdminPage;
