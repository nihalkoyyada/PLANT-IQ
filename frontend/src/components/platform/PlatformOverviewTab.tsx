import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  ArrowUpRight,
  Building2,
  CheckCircle2,
  Cpu,
  Database,
  FileCheck2,
  HardDrive,
  History,
  Layers,
  Radio,
  RefreshCw,
  Server,
  ShieldAlert,
  Sun,
  Users,
  Zap,
} from 'lucide-react';
import { getPlatformOverview } from '../../api/platform';
import { formatApiError } from '../../api/client';
import { PlatformOverviewResponse } from '../../types';
import { NavTab } from '../layout/Sidebar';
import { PlatformSubTab } from '../../pages/PlatformAdminPage';

interface PlatformOverviewTabProps {
  onNavigateSubTab?: (subTab: PlatformSubTab) => void;
  onNavigateTab?: (tab: NavTab) => void;
}

export const PlatformOverviewTab: React.FC<PlatformOverviewTabProps> = ({
  onNavigateSubTab,
  onNavigateTab,
}) => {
  const [overview, setOverview] = useState<PlatformOverviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getPlatformOverview();
      setOverview(data);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to load platform overview metrics'));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-16 space-y-3">
        <RefreshCw className="w-8 h-8 text-[#004874] animate-spin" />
        <span className="text-xs font-mono text-slate-500 font-semibold tracking-wide">
          GATHERING PLATFORM TELEMETRY & SYSTEM HEALTH...
        </span>
      </div>
    );
  }

  if (error || !overview) {
    return (
      <div className="p-6 bg-rose-50 border border-rose-200 rounded-xl text-rose-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-rose-600" />
          <span className="text-xs font-semibold">{error || 'Data unavailable'}</span>
        </div>
        <button
          onClick={fetchData}
          className="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold rounded-lg cursor-pointer transition"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Platform Metric Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Total Organizations */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNavigateSubTab?.('orgs')}
          onKeyDown={(e) => e.key === 'Enter' && onNavigateSubTab?.('orgs')}
          className="group relative overflow-hidden bg-gradient-to-br from-purple-50 via-white to-purple-50/40 p-4 rounded-xl border border-purple-200/90 hover:border-purple-500 hover:shadow-md hover:shadow-purple-500/10 transition-all duration-200 cursor-pointer text-left before:absolute before:top-0 before:left-0 before:right-0 before:h-1 before:bg-gradient-to-r before:from-purple-600 before:to-indigo-600"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-mono text-purple-900/80 uppercase font-bold tracking-wide">
              Total Organizations
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-mono text-purple-700 opacity-0 group-hover:opacity-100 transition-opacity font-bold flex items-center">
                View <ArrowUpRight className="w-3 h-3 ml-0.5" />
              </span>
              <div className="w-7 h-7 rounded-lg bg-purple-100 text-purple-700 flex items-center justify-center group-hover:bg-purple-700 group-hover:text-white transition shadow-2xs">
                <Building2 className="w-4 h-4" />
              </div>
            </div>
          </div>
          <div className="text-2xl font-black text-slate-900 group-hover:text-purple-950 transition-colors">
            {overview.total_organizations}
          </div>
          <div className="mt-1 flex items-center gap-2 text-[10px] font-mono text-slate-500">
            <span className="text-emerald-700 font-semibold">{overview.active_organizations} Active</span>
            <span>•</span>
            <span className={overview.suspended_organizations > 0 ? 'text-rose-600 font-bold' : ''}>
              {overview.suspended_organizations} Suspended
            </span>
          </div>
        </div>

        {/* Global Users */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNavigateSubTab?.('users')}
          onKeyDown={(e) => e.key === 'Enter' && onNavigateSubTab?.('users')}
          className="group relative overflow-hidden bg-gradient-to-br from-blue-50 via-white to-sky-50/40 p-4 rounded-xl border border-blue-200/90 hover:border-blue-500 hover:shadow-md hover:shadow-blue-500/10 transition-all duration-200 cursor-pointer text-left before:absolute before:top-0 before:left-0 before:right-0 before:h-1 before:bg-gradient-to-r before:from-blue-600 before:to-sky-500"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-mono text-blue-900/80 uppercase font-bold tracking-wide">
              Global Platform Users
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-mono text-blue-700 opacity-0 group-hover:opacity-100 transition-opacity font-bold flex items-center">
                View <ArrowUpRight className="w-3 h-3 ml-0.5" />
              </span>
              <div className="w-7 h-7 rounded-lg bg-sky-100 text-[#004874] flex items-center justify-center group-hover:bg-[#004874] group-hover:text-white transition shadow-2xs">
                <Users className="w-4 h-4" />
              </div>
            </div>
          </div>
          <div className="text-2xl font-black text-slate-900 group-hover:text-blue-950 transition-colors">
            {overview.total_users}
          </div>
          <p className="mt-1 text-[10px] text-slate-500 font-mono">
            Across all tenant organizations
          </p>
        </div>

        {/* Plants & Assets */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNavigateSubTab?.('plants')}
          onKeyDown={(e) => e.key === 'Enter' && onNavigateSubTab?.('plants')}
          className="group relative overflow-hidden bg-gradient-to-br from-amber-50 via-white to-orange-50/40 p-4 rounded-xl border border-amber-200/90 hover:border-amber-500 hover:shadow-md hover:shadow-amber-500/10 transition-all duration-200 cursor-pointer text-left before:absolute before:top-0 before:left-0 before:right-0 before:h-1 before:bg-gradient-to-r before:from-amber-500 before:to-orange-500"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-mono text-amber-900/80 uppercase font-bold tracking-wide">
              Connected Plants
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-mono text-amber-700 opacity-0 group-hover:opacity-100 transition-opacity font-bold flex items-center">
                View <ArrowUpRight className="w-3 h-3 ml-0.5" />
              </span>
              <div className="w-7 h-7 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center group-hover:bg-amber-600 group-hover:text-white transition shadow-2xs">
                <Sun className="w-4 h-4" />
              </div>
            </div>
          </div>
          <div className="text-2xl font-black text-slate-900 group-hover:text-amber-950 transition-colors">
            {overview.total_plants}
          </div>
          <p className="mt-1 text-[10px] text-slate-500 font-mono">
            {overview.total_devices} inverters & sensors
          </p>
        </div>

        {/* Telemetry Ingestion */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onNavigateSubTab?.('monitoring')}
          onKeyDown={(e) => e.key === 'Enter' && onNavigateSubTab?.('monitoring')}
          className="group relative overflow-hidden bg-gradient-to-br from-emerald-50 via-white to-teal-50/40 p-4 rounded-xl border border-emerald-200/90 hover:border-emerald-500 hover:shadow-md hover:shadow-emerald-500/10 transition-all duration-200 cursor-pointer text-left before:absolute before:top-0 before:left-0 before:right-0 before:h-1 before:bg-gradient-to-r before:from-emerald-500 before:to-teal-500"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-mono text-emerald-900/80 uppercase font-bold tracking-wide">
              Telemetry Stream
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-mono text-emerald-700 opacity-0 group-hover:opacity-100 transition-opacity font-bold flex items-center">
                View <ArrowUpRight className="w-3 h-3 ml-0.5" />
              </span>
              <div className="w-7 h-7 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center group-hover:bg-emerald-600 group-hover:text-white transition shadow-2xs">
                <Activity className="w-4 h-4" />
              </div>
            </div>
          </div>
          <div className="text-2xl font-black text-slate-900 group-hover:text-emerald-950 transition-colors">
            {overview.total_readings.toLocaleString()}
          </div>
          <div className="mt-1 flex items-center gap-1.5 text-[10px] font-mono text-slate-500">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span>{overview.ingestion_health.active_streams} active pipelines</span>
          </div>
        </div>
      </div>

      {/* System Infrastructure Health Grid */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-[#004874]" />
            <h2 className="text-sm font-bold text-slate-900">Infrastructure & Microservice Health</h2>
          </div>
          <span className="text-[10px] font-mono text-slate-400">Live Diagnostics</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {/* API Health */}
          <div className="p-3.5 rounded-lg border border-slate-100 bg-slate-50/60">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-bold text-slate-800">FastAPI ASGI Core</span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 uppercase">
                {overview.system_health.api?.status || 'ONLINE'}
              </span>
            </div>
            <p className="text-[11px] text-slate-500 font-mono">
              Latency: {overview.system_health.api?.latency_ms != null ? `${overview.system_health.api.latency_ms} ms` : 'Live'}
            </p>
            <p className="text-[10px] text-slate-400 truncate mt-0.5">
              {overview.system_health.api?.details}
            </p>
          </div>

          {/* Database Health */}
          <div className="p-3.5 rounded-lg border border-slate-100 bg-slate-50/60">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-bold text-slate-800">TimescaleDB / Postgres</span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 uppercase">
                {overview.system_health.database?.status || 'ONLINE'}
              </span>
            </div>
            <p className="text-[11px] text-slate-500 font-mono">
              Query Latency: {overview.system_health.database?.latency_ms != null ? `${overview.system_health.database.latency_ms} ms` : 'Live'}
            </p>
            <p className="text-[10px] text-slate-400 truncate mt-0.5">
              {overview.system_health.database?.details}
            </p>
          </div>

          {/* Redis Broker */}
          <div className="p-3.5 rounded-lg border border-slate-100 bg-slate-50/60">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-bold text-slate-800">Redis Broker</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                overview.system_health.redis?.status === 'healthy'
                  ? 'bg-emerald-100 text-emerald-800'
                  : 'bg-amber-100 text-amber-800'
              }`}>
                {overview.system_health.redis?.status || 'CONNECTED'}
              </span>
            </div>
            <p className="text-[11px] text-slate-500 font-mono">
              Ping: {overview.system_health.redis?.latency_ms != null ? `${overview.system_health.redis.latency_ms} ms` : 'Live'}
            </p>
            <p className="text-[10px] text-slate-400 truncate mt-0.5">
              {overview.system_health.redis?.details}
            </p>
          </div>

          {/* Celery Background Tasks */}
          <div className="p-3.5 rounded-lg border border-slate-100 bg-slate-50/60">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-bold text-slate-800">Celery Workers</span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 uppercase">
                {overview.system_health.celery?.status || 'ACTIVE'}
              </span>
            </div>
            <p className="text-[11px] text-slate-500 font-mono">
              Beat Schedule: Scheduled Rollups
            </p>
            <p className="text-[10px] text-slate-400 truncate mt-0.5">
              Daily Solar Rollup & Hourly Scans
            </p>
          </div>
        </div>
      </div>

      {/* Two Column Layout: Ingestion Health & Recent Activity */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Ingestion Pipeline Overview */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileCheck2 className="w-4 h-4 text-[#004874]" />
              <h2 className="text-sm font-bold text-slate-900">SCADA Ingestion Health</h2>
            </div>
            <span className="text-[11px] font-mono font-bold text-slate-700">
              {overview.ingestion_health.total_jobs} Total Jobs
            </span>
          </div>

          <div className="grid grid-cols-4 gap-2 text-center">
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
              <div className="text-xs font-mono text-slate-500 uppercase font-semibold">Pending</div>
              <div className="text-base font-bold text-slate-800 mt-1">
                {overview.ingestion_health.pending}
              </div>
            </div>
            <div className="p-3 bg-sky-50 rounded-lg border border-sky-100">
              <div className="text-xs font-mono text-[#004874] uppercase font-semibold">Processing</div>
              <div className="text-base font-bold text-[#004874] mt-1">
                {overview.ingestion_health.processing}
              </div>
            </div>
            <div className="p-3 bg-emerald-50 rounded-lg border border-emerald-100">
              <div className="text-xs font-mono text-emerald-800 uppercase font-semibold">Completed</div>
              <div className="text-base font-bold text-emerald-800 mt-1">
                {overview.ingestion_health.completed}
              </div>
            </div>
            <div className="p-3 bg-rose-50 rounded-lg border border-rose-100">
              <div className="text-xs font-mono text-rose-800 uppercase font-semibold">Failed</div>
              <div className="text-base font-bold text-rose-800 mt-1">
                {overview.ingestion_health.failed}
              </div>
            </div>
          </div>

          {/* Recent Ingestion Pipelines List */}
          <div className="space-y-2 pt-1">
            <div className="flex items-center justify-between text-[11px] font-mono text-slate-500 uppercase font-semibold">
              <span>Recent Ingestion Pipelines</span>
              <span>Status</span>
            </div>
            {(!overview.ingestion_health.recent_jobs || overview.ingestion_health.recent_jobs.length === 0) ? (
              <p className="text-xs text-slate-400 font-mono py-4 text-center">
                No telemetry ingestion jobs recorded
              </p>
            ) : (
              overview.ingestion_health.recent_jobs.map((job) => (
                <div
                  key={job.id}
                  className="p-3 rounded-lg border border-slate-100 hover:bg-slate-50 transition text-xs space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-semibold text-slate-800 truncate">
                        {job.filename}
                      </span>
                      {job.org_name && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-100 text-slate-600 truncate max-w-[160px]">
                          {job.org_name}
                        </span>
                      )}
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase ${
                        job.status === 'completed'
                          ? 'bg-emerald-100 text-emerald-800'
                          : job.status === 'processing'
                          ? 'bg-sky-100 text-sky-800'
                          : job.status === 'failed'
                          ? 'bg-rose-100 text-rose-800'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {job.status}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
                    <span>
                      {(job.readings_inserted || 0).toLocaleString()} readings • {(job.rows_total || 0).toLocaleString()} rows
                    </span>
                    <span>
                      {job.finished_at
                        ? new Date(job.finished_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                        : job.created_at
                        ? new Date(job.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                        : 'Done'}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Recent Platform Administrative Actions */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-[#004874]" />
              <h2 className="text-sm font-bold text-slate-900">Recent Platform Operations</h2>
            </div>
            <span className="text-[10px] font-mono text-slate-400">Audit Stream</span>
          </div>

          <div className="space-y-2">
            {(overview.recent_activity || []).length === 0 ? (
              <p className="text-xs text-slate-400 font-mono py-4 text-center">
                No recent platform operations recorded
              </p>
            ) : (
              (overview.recent_activity || []).map((act) => (
                <div
                  key={act.id}
                  className="flex items-center justify-between p-2.5 rounded-lg border border-slate-100 hover:bg-slate-50 transition text-xs"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold uppercase bg-slate-100 text-slate-700">
                      {act.action}
                    </span>
                    <span className="font-semibold text-slate-800 truncate">
                      {act.actor}
                    </span>
                    <span className="text-slate-400">•</span>
                    <span className="text-slate-500 font-mono text-[11px] truncate">
                      {act.entity}
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-400 shrink-0">
                    {new Date(act.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

