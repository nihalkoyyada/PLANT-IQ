import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Database,
  Globe,
  HardDrive,
  Info,
  Loader2,
  Save,
  Shield,
  Sliders,
  X,
} from 'lucide-react';
import { getPlatformSettings, updatePlatformSettings } from '../../api/platform';
import { formatApiError } from '../../api/client';
import { PlatformSettingsResponse } from '../../types';

export const PlatformSettingsTab: React.FC = () => {
  const [settings, setSettings] = useState<PlatformSettingsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Form states
  const [platformName, setPlatformName] = useState<string>('');
  const [maintenanceMode, setMaintenanceMode] = useState<boolean>(false);
  const [retentionDays, setRetentionDays] = useState<number>(365);
  const [sessionTimeout, setSessionTimeout] = useState<number>(120);

  const fetchSettings = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getPlatformSettings();
      setSettings(data);
      setPlatformName(data.platform_name);
      setMaintenanceMode(data.maintenance_mode);
      setRetentionDays(data.telemetry_retention_days);
      setSessionTimeout(data.session_timeout_minutes);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to load platform configuration'));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setError(null);
    try {
      const updated = await updatePlatformSettings({
        platform_name: platformName.trim(),
        maintenance_mode: maintenanceMode,
        telemetry_retention_days: Number(retentionDays),
        session_timeout_minutes: Number(sessionTimeout),
      });
      setSettings(updated);
      setSuccessMsg('Platform configuration updated and applied globally.');
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to update platform settings'));
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="py-16 text-center text-slate-400 font-mono text-xs">
        <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#004874] mb-2" />
        LOADING GLOBAL SAAS CONFIGURATION...
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Toast Feedback */}
      {successMsg && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg flex items-center justify-between text-emerald-800 text-xs">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            <span>{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-700 hover:text-emerald-900 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg flex items-center justify-between text-rose-800 text-xs">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-700 hover:text-rose-900 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Maintenance Mode Alert Banner if active */}
      {maintenanceMode && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl flex items-start gap-3 text-amber-900 text-xs">
          <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <div className="font-bold">Maintenance Mode is Active</div>
            <p className="text-amber-800 mt-0.5 leading-relaxed">
              Platform is currently marked in maintenance mode. Tenant users may receive notifications
              of scheduled servicing. Super Admin access remains uninterrupted.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-6">
        {/* General SaaS Settings */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
            <Globe className="w-4 h-4 text-[#004874]" />
            <h3 className="text-sm font-bold text-slate-900">Platform Identity & Access</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div>
              <label className="block font-semibold text-slate-700 mb-1">Platform Brand Name</label>
              <input
                type="text"
                value={platformName}
                onChange={(e) => setPlatformName(e.target.value)}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#004874]"
              />
              <span className="text-[10px] text-slate-400 font-mono mt-1 block">
                Displayed in tenant navigation headers and emails.
              </span>
            </div>

            <div>
              <label className="block font-semibold text-slate-700 mb-1">Session Inactivity Timeout (Minutes)</label>
              <input
                type="number"
                min={15}
                max={1440}
                value={sessionTimeout}
                onChange={(e) => setSessionTimeout(Number(e.target.value))}
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#004874] font-mono"
              />
              <span className="text-[10px] text-slate-400 font-mono mt-1 block">
                Time before inactive JWT sessions require re-authentication.
              </span>
            </div>
          </div>
        </div>

        {/* Telemetry Storage Policy */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
            <Database className="w-4 h-4 text-[#004874]" />
            <h3 className="text-sm font-bold text-slate-900">TimescaleDB Hypertable Retention Policy</h3>
          </div>

          <div className="text-xs space-y-2">
            <label className="block font-semibold text-slate-700">Telemetry Data Retention (Days)</label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min={30}
                max={3650}
                value={retentionDays}
                onChange={(e) => setRetentionDays(Number(e.target.value))}
                className="w-48 px-3 py-2 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#004874] font-mono"
              />
              <span className="text-slate-500 font-mono text-xs">Days ({(retentionDays / 365).toFixed(1)} Years)</span>
            </div>
            <p className="text-[11px] text-slate-500 leading-relaxed">
              TimescaleDB automated data retention drops chunks older than this threshold to optimize SSD storage and continuous aggregates.
            </p>
          </div>
        </div>

        {/* Maintenance Controls */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
            <Sliders className="w-4 h-4 text-[#004874]" />
            <h3 className="text-sm font-bold text-slate-900">System Servicing & Maintenance</h3>
          </div>

          <div className="flex items-center justify-between p-3.5 bg-slate-50 rounded-lg border border-slate-100 text-xs">
            <div>
              <div className="font-bold text-slate-800">Platform Maintenance Mode</div>
              <p className="text-slate-500 text-[11px] mt-0.5">
                Enable to notify tenant users of scheduled database or model upgrades.
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={maintenanceMode}
                onChange={(e) => setMaintenanceMode(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-slate-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-600"></div>
            </label>
          </div>
        </div>

        {/* System Deployment Info */}
        <div className="bg-slate-50 rounded-xl border border-slate-200 p-4 text-xs font-mono text-slate-600 flex flex-col md:flex-row items-start md:items-center justify-between gap-2">
          <div>
            <span>PlantIQ SaaS Core Version: </span>
            <span className="font-bold text-slate-900">{settings?.version || 'v2.4.0'}</span>
          </div>
          {settings?.updated_at && (
            <div className="text-[11px] text-slate-400">
              Last saved: {new Date(settings.updated_at).toLocaleString()}
            </div>
          )}
        </div>

        {/* Save Button */}
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={isSaving}
            className="flex items-center gap-2 px-5 py-2.5 bg-[#004874] hover:bg-[#00385c] text-white rounded-lg text-xs font-semibold cursor-pointer transition shadow-xs disabled:opacity-50"
          >
            {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            <span>Save Platform Configuration</span>
          </button>
        </div>
      </form>
    </div>
  );
};

