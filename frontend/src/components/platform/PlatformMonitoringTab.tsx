import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Building2,
  CheckCircle2,
  Cpu,
  Database,
  FileCheck2,
  HardDrive,
  Loader2,
  Radio,
  RefreshCw,
  Server,
  Zap,
} from 'lucide-react';
import { getPlatformMonitoring } from '../../api/platform';
import { PlatformMonitoringResponse } from '../../types';

export const PlatformMonitoringTab: React.FC = () => {
  const [data, setData] = useState<PlatformMonitoringResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getPlatformMonitoring();
      setData(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to retrieve system diagnostics');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (isLoading) {
    return (
      <div className="py-16 text-center text-slate-400 font-mono text-xs">
        <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#004874] mb-2" />
        PROBING PLATFORM MICROSERVICES & REDIS BROKER...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-800 text-xs flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-600" />
          <span>{error || 'Monitoring metrics unavailable'}</span>
        </div>
        <button
          onClick={fetchData}
          className="px-3 py-1 bg-rose-600 text-white rounded text-xs font-semibold cursor-pointer"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Header with live refresh */}
      <div className="flex items-center justify-between">
        <div className="space-y-0.5">
          <h2 className="text-sm font-bold text-slate-900 flex items-center gap-2">
            <Server className="w-4 h-4 text-[#004874]" />
            <span>Platform Core & Telemetry Health</span>
          </h2>
          <p className="text-xs text-slate-500">
            Real-time latency diagnostics, hypertable sync, Redis queues, and background ingestion job metrics.
          </p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50 text-xs font-semibold cursor-pointer transition"
        >
          <RefreshCw className="w-3.5 h-3.5 text-[#004874]" />
          <span>Refresh Diagnostics</span>
        </button>
      </div>

      {/* Microservice Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* API */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-semibold uppercase text-slate-500">ASGI Gateway</span>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 uppercase">
              {data.api.status}
            </span>
          </div>
          <div className="text-lg font-bold text-slate-900">
            {data.api.latency_ms ?? 0.5} <span className="text-xs font-normal text-slate-500">ms latency</span>
          </div>
          <p className="text-[11px] text-slate-500 font-mono truncate">{data.api.details}</p>
        </div>

        {/* Database */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-semibold uppercase text-slate-500">Postgres / Timescale</span>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 uppercase">
              {data.database.status}
            </span>
          </div>
          <div className="text-lg font-bold text-slate-900">
            {data.database.latency_ms ?? 1.2} <span className="text-xs font-normal text-slate-500">ms query</span>
          </div>
          <p className="text-[11px] text-slate-500 font-mono truncate">{data.database.details}</p>
        </div>

        {/* Redis */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-semibold uppercase text-slate-500">Redis Broker</span>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                data.redis.status === 'healthy' ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
              }`}
            >
              {data.redis.status}
            </span>
          </div>
          <div className="text-lg font-bold text-slate-900">
            {data.redis.latency_ms ?? 1.0} <span className="text-xs font-normal text-slate-500">ms ping</span>
          </div>
          <p className="text-[11px] text-slate-500 font-mono truncate">{data.redis.details}</p>
        </div>

        {/* Celery */}
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono font-semibold uppercase text-slate-500">Worker Daemon</span>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 uppercase">
              {data.celery.status}
            </span>
          </div>
          <div className="text-lg font-bold text-slate-900">Active</div>
          <p className="text-[11px] text-slate-500 font-mono truncate">{data.celery.details}</p>
        </div>
      </div>

      {/* Ingestion & Failed Jobs Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Failed Background Jobs Card */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600" />
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
                Background Ingestion Incidents
              </h3>
            </div>
            <span className="px-2 py-0.5 bg-slate-100 rounded text-[10px] font-mono font-bold text-slate-700">
              {data.ingestion_pipeline.failed_jobs_count} Failed Jobs
            </span>
          </div>

          {data.ingestion_pipeline.failed_jobs.length === 0 ? (
            <div className="p-6 bg-emerald-50/50 rounded-lg border border-emerald-100 text-center text-xs text-emerald-800">
              <CheckCircle2 className="w-5 h-5 mx-auto mb-1 text-emerald-600" />
              <span>Zero failed background ingestion jobs recorded. Ingestion pipelines operating cleanly.</span>
            </div>
          ) : (
            <div className="space-y-2">
              {data.ingestion_pipeline.failed_jobs.map((job) => (
                <div
                  key={job.id}
                  className="p-3 bg-rose-50/60 rounded-lg border border-rose-100 text-xs text-rose-900 flex items-center justify-between"
                >
                  <div>
                    <span className="font-bold">Job ID: {job.id.slice(0, 8)}...</span>
                    <div className="text-[10px] font-mono text-rose-700 mt-0.5">File ID: {job.file_id}</div>
                  </div>
                  <span className="px-2 py-0.5 bg-rose-200 text-rose-800 rounded font-mono font-bold uppercase text-[9px]">
                    {job.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tenant Ingestion Breakdown */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-[#004874]" />
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
                Organization SCADA Feed Distribution
              </h3>
            </div>
            <span className="text-[10px] font-mono text-slate-400">
              {data.ingestion_pipeline.total_files} Total Uploaded Files
            </span>
          </div>

          <div className="space-y-2 max-h-64 overflow-y-auto">
            {data.organization_health.map((org) => (
              <div
                key={org.id}
                className="p-2.5 rounded-lg border border-slate-100 bg-slate-50/60 flex items-center justify-between text-xs"
              >
                <div>
                  <span className="font-semibold text-slate-800">{org.name}</span>
                  <div className="text-[10px] font-mono text-slate-400">Status: {org.status}</div>
                </div>
                <div className="text-right">
                  <span className="font-bold font-mono text-slate-800">{org.total_files}</span>
                  <span className="text-slate-500 text-[11px] ml-1">files</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

