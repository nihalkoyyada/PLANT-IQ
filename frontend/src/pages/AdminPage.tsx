import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  BellRing,
  Building2,
  CheckCircle2,
  History,
  Lock,
  RefreshCw,
  Shield,
  ShieldAlert,
  Sliders,
  Users,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getAdminSummary } from '../api/admin';
import { AdminSummaryResponse, Plant } from '../types';
import { NavTab } from '../components/layout/Sidebar';
import { AdminUsersTab } from '../components/admin/AdminUsersTab';
import { AdminDetectorsTab } from '../components/admin/AdminDetectorsTab';
import { AdminAlertRulesTab } from '../components/admin/AdminAlertRulesTab';
import { AdminAuditViewerTab } from '../components/admin/AdminAuditViewerTab';

interface AdminPageProps {
  plants?: Plant[];
  selectedPlant?: Plant | null;
  onNavigateTab?: (tab: NavTab) => void;
}

export type AdminSubTab = 'users' | 'detectors' | 'rules' | 'audit';

export const AdminPage: React.FC<AdminPageProps> = ({
  plants = [],
  selectedPlant = null,
  onNavigateTab,
}) => {
  const { user } = useAuth();
  const [activeSubTab, setActiveSubTab] = useState<AdminSubTab>('users');
  const [summary, setSummary] = useState<AdminSummaryResponse | null>(null);
  const [isLoadingSummary, setIsLoadingSummary] = useState<boolean>(true);

  const userRole = user?.role?.toLowerCase() || 'viewer';
  const isAuthorized = userRole === 'admin' || userRole === 'super_admin';
  const isSuperAdmin = userRole === 'super_admin';

  const fetchSummary = async () => {
    setIsLoadingSummary(true);
    try {
      const data = await getAdminSummary();
      setSummary(data);
    } catch {
      // Graceful fallback
    } finally {
      setIsLoadingSummary(false);
    }
  };

  useEffect(() => {
    if (isAuthorized) {
      fetchSummary();
    }
  }, [isAuthorized]);

  if (!isAuthorized) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-12 text-center max-w-lg mx-auto mt-12 shadow-xs">
        <div className="w-12 h-12 rounded-full bg-rose-100 text-rose-600 flex items-center justify-center mx-auto mb-4">
          <Lock className="w-6 h-6" />
        </div>
        <h2 className="text-lg font-bold text-slate-800 mb-2">Access Restricted</h2>
        <p className="text-xs text-slate-600 leading-relaxed mb-4">
          The PlantIQ Administration Panel is restricted to Organization Administrators and
          Super Administrators. Your role (<span className="font-mono font-bold text-slate-800">{user?.role}</span>)
          does not possess sufficient privileges to view this screen.
        </p>
        <span className="text-[11px] font-mono text-slate-400">
          Contact your organization IT administrator for elevated access.
        </span>
      </div>
    );
  }

  const navTabs = [
    { id: 'users', label: 'User Management', icon: Users, count: summary?.total_users },
    { id: 'detectors', label: 'Detector Registry', icon: Activity, count: summary?.total_detectors },
    { id: 'rules', label: 'Alert Rules', icon: BellRing, count: summary?.total_alert_rules },
    { id: 'audit', label: 'Audit Log Viewer', icon: History, count: summary?.total_audit_logs },
  ] as const;

  return (
    <div className="space-y-6">
      {/* Top Header Banner */}
      <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-xs flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-[#004874] text-white flex items-center justify-center shadow-xs">
              <Shield className="w-4 h-4" />
            </div>
            <div>
              <h1 className="text-base font-bold text-slate-900 tracking-tight flex items-center gap-2">
                <span>Organization Administration & Controls</span>
                <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded font-bold bg-sky-100 text-sky-800 border border-sky-200">
                  ORGANIZATION ADMIN
                </span>
              </h1>
            </div>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            Manage organization members, calibrate physics and ML anomaly detectors, configure plant alert rules, and review tenant audit records.
          </p>
        </div>

        {/* Action Buttons and Summary Pill Badges */}
        <div className="flex items-center gap-2 flex-wrap">
          {onNavigateTab && (
            <button
              type="button"
              onClick={() => onNavigateTab('dashboard')}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200/90 text-slate-700 rounded-lg text-xs font-semibold transition border border-slate-200 cursor-pointer shadow-xs mr-1"
            >
              <ArrowLeft className="w-3.5 h-3.5 text-slate-600" />
              <span>Back to SCADA</span>
            </button>
          )}

          {summary && (
            <>
              {isSuperAdmin && summary.total_organizations !== undefined && (
                <div className="px-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-center">
                  <div className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Tenants</div>
                  <div className="text-sm font-bold text-slate-800">{summary.total_organizations}</div>
                </div>
              )}
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-center">
                <div className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Users</div>
                <div className="text-sm font-bold text-slate-800">{summary.total_users}</div>
              </div>
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-center">
                <div className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Detectors</div>
                <div className="text-sm font-bold text-slate-800">{summary.total_detectors}</div>
              </div>
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-center">
                <div className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Alert Rules</div>
                <div className="text-sm font-bold text-slate-800">{summary.total_alert_rules}</div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Tabs Selector Navigation */}
      <div className="flex items-center gap-1 border-b border-slate-200 pb-px overflow-x-auto">
        {navTabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeSubTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveSubTab(tab.id as AdminSubTab)}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold rounded-t-lg transition border-b-2 cursor-pointer whitespace-nowrap ${
                isActive
                  ? 'border-[#004874] text-[#004874] bg-sky-50/50'
                  : 'border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-[#004874]' : 'text-slate-400'}`} />
              <span>{tab.label}</span>
              {tab.count !== undefined && (
                <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                  isActive ? 'bg-[#004874] text-white' : 'bg-slate-100 text-slate-600'
                }`}>
                  {tab.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab Panels */}
      <div>
        {activeSubTab === 'users' && <AdminUsersTab />}
        {activeSubTab === 'detectors' && (
          <AdminDetectorsTab plants={plants} selectedPlant={selectedPlant} />
        )}
        {activeSubTab === 'rules' && (
          <AdminAlertRulesTab plants={plants} selectedPlant={selectedPlant} />
        )}
        {activeSubTab === 'audit' && <AdminAuditViewerTab />}
      </div>
    </div>
  );
};

export default AdminPage;
