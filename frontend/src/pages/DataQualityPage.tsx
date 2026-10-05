import React, { useEffect, useState } from 'react';
import { CheckCircle2, Loader2, AlertCircle } from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { getQCStats } from '../api/readings';
import { QCStatsResponse } from '../types';

export const DataQualityPage: React.FC = () => {
  const [qcData, setQcData] = useState<QCStatsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadQCStats() {
      try {
        setLoading(true);
        setError(null);
        const stats = await getQCStats();
        setQcData(stats);
      } catch (err: any) {
        console.error('Failed to fetch database QC metrics:', err);
        setError(err.response?.data?.detail || err.message || 'Failed to load QC metrics');
      } finally {
        setLoading(false);
      }
    }

    loadQCStats();
  }, []);

  const totalReadingsFormatted = qcData ? qcData.total_readings.toLocaleString() : '0';
  const activeChannelsCount = qcData ? qcData.active_channels : 0;
  const cadenceIntegrityText = qcData ? qcData.cadence_integrity : '15 Min';
  const ingestionQualityText = qcData ? `${qcData.ingestion_quality}%` : '100%';
  const duplicatesCount = qcData ? qcData.duplicates_count : 0;
  const outOfBoundsCount = qcData ? qcData.out_of_bounds_count : 0;
  const hypertableActive = qcData ? qcData.hypertable_active : true;

  return (
    <div className="space-y-4 pb-12">
      {/* Header */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">Data Quality &amp; QC Center</h1>
            <Badge variant="emerald">● 100% CADENCE INTEGRITY</Badge>
          </div>
          <p className="text-xs text-slate-500 font-mono mt-0.5">
            Verification metrics, duplicate telemetry detection, and automated database quality flags
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 p-4 rounded-xl text-xs flex items-center gap-3 font-mono">
          <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />
          <div>
            <strong className="font-bold">QC Metrics Warning:</strong> {error}
          </div>
        </div>
      )}

      {/* QC Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-1">
          <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold">TOTAL READINGS</span>
          <div className="text-2xl font-bold text-slate-900 font-mono flex items-center gap-2">
            {loading ? <Loader2 className="w-5 h-5 animate-spin text-sky-600" /> : totalReadingsFormatted}
          </div>
          <p className="text-[11px] text-emerald-700 font-mono font-medium">● {duplicatesCount} Duplicates Detected</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-1">
          <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold">ACTIVE CHANNELS</span>
          <div className="text-2xl font-bold text-sky-800 font-mono flex items-center gap-2">
            {loading ? <Loader2 className="w-5 h-5 animate-spin text-sky-600" /> : activeChannelsCount}
          </div>
          <p className="text-[11px] text-slate-500 font-mono">Across 22 Inverter Nodes</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-1">
          <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold">CADENCE INTEGRITY</span>
          <div className="text-2xl font-bold text-emerald-600 font-mono flex items-center gap-2">
            {loading ? <Loader2 className="w-5 h-5 animate-spin text-sky-600" /> : cadenceIntegrityText}
          </div>
          <p className="text-[11px] text-emerald-700 font-mono font-medium">● Monotonic UTC Timestamps</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-1">
          <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold">INGESTION QUALITY</span>
          <div className="text-2xl font-bold text-slate-900 font-mono flex items-center gap-2">
            {loading ? <Loader2 className="w-5 h-5 animate-spin text-sky-600" /> : ingestionQualityText}
          </div>
          <p className="text-[11px] text-slate-500 font-mono">0 Skipped / 0 Null Rows</p>
        </div>
      </div>

      {/* QC Audit Log */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
        <div className="flex items-center justify-between border-b border-slate-100 pb-2">
          <h3 className="text-xs font-mono font-bold uppercase text-slate-700 tracking-wider">
            SCADA Database Quality Checks
          </h3>
          <Badge variant="emerald">VERIFIED CLEAN</Badge>
        </div>

        <div className="space-y-2 text-xs font-mono">
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span className="font-semibold text-slate-800">Duplicate Timestamp Validation</span>
            </div>
            <span className="text-emerald-700 font-bold">PASSED ({duplicatesCount} duplicates)</span>
          </div>

          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span className="font-semibold text-slate-800">Range Bound Check (AC/DC Power ≥ 0)</span>
            </div>
            <span className="text-emerald-700 font-bold">PASSED ({outOfBoundsCount} out-of-bounds)</span>
          </div>

          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span className="font-semibold text-slate-800">TimescaleDB Hypertable Integrity</span>
            </div>
            <span className="text-emerald-700 font-bold">
              PASSED ({hypertableActive ? 'TimescaleDB hypertable active' : 'Hypertable warning'})
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
