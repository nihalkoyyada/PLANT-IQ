import React, { useEffect, useState, useCallback, useMemo } from 'react';
import {
  FileText,
  Download,
  Plus,
  RefreshCw,
  Clock,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Calendar,
  Building,
  TrendingUp,
  ShieldAlert,
  X,
  Eye,
  Info,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getPlants } from '../api/plants';
import { getReports, generateReport, downloadReport } from '../api/reports';
import { Plant, Report } from '../types';

interface ReportsPageProps {
  onAskCopilot?: (prompt: string) => void;
}

export const ReportsPage: React.FC<ReportsPageProps> = ({ onAskCopilot }) => {
  const { user } = useAuth();
  const [plants, setPlants] = useState<Plant[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [selectedPlantId, setSelectedPlantId] = useState<string>('');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [modalPlantId, setModalPlantId] = useState<string>('');
  const [modalReportType, setModalReportType] = useState<'daily' | 'weekly'>('daily');
  const [modalStartDate, setModalStartDate] = useState<string>('2020-06-17');
  const [modalEndDate, setModalEndDate] = useState<string>('2020-06-17');
  const [modalTitle, setModalTitle] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [modalError, setModalError] = useState<string | null>(null);

  // Details Modal State
  const [viewReport, setViewReport] = useState<Report | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  // Fetch initial plants
  useEffect(() => {
    getPlants()
      .then((data) => {
        setPlants(data);
        if (data.length > 0 && !modalPlantId) {
          setModalPlantId(data[0].id);
        }
      })
      .catch((err) => {
        console.error('Failed to load plants for reports:', err);
      });
  }, []);

  // Fetch reports list
  const fetchReports = useCallback(async () => {
    try {
      setError(null);
      const res = await getReports({
        plant_id: selectedPlantId || undefined,
        report_type: selectedType !== 'all' ? selectedType : undefined,
        status: selectedStatus !== 'all' ? selectedStatus : undefined,
        limit: 50,
      });
      setReports(res.items);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to load reports');
    } finally {
      setIsLoading(false);
    }
  }, [selectedPlantId, selectedType, selectedStatus]);

  useEffect(() => {
    setIsLoading(true);
    fetchReports();
  }, [fetchReports]);

  // Auto-polling when reports are pending or processing
  useEffect(() => {
    const hasActiveReports = reports.some(
      (r) => r.status === 'pending' || r.status === 'processing'
    );
    if (!hasActiveReports) return;

    const timer = setInterval(() => {
      fetchReports();
    }, 3000);

    return () => clearInterval(timer);
  }, [reports, fetchReports]);

  // Synchronize modal end date when type or start date changes
  const handleStartDateChange = (val: string) => {
    setModalStartDate(val);
    if (modalReportType === 'daily') {
      setModalEndDate(val);
    } else {
      const d = new Date(val);
      d.setDate(d.getDate() + 6);
      setModalEndDate(d.toISOString().split('T')[0]);
    }
  };

  const handleReportTypeChange = (type: 'daily' | 'weekly') => {
    setModalReportType(type);
    if (type === 'daily') {
      setModalEndDate(modalStartDate);
    } else {
      const d = new Date(modalStartDate);
      d.setDate(d.getDate() + 6);
      setModalEndDate(d.toISOString().split('T')[0]);
    }
  };

  const handleOpenModal = () => {
    setModalError(null);
    if (plants.length > 0 && !modalPlantId) {
      setModalPlantId(plants[0].id);
    }
    setIsModalOpen(true);
  };

  const handleGenerateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!modalPlantId) {
      setModalError('Please select a target plant');
      return;
    }
    if (!modalStartDate) {
      setModalError('Please choose a valid start date');
      return;
    }

    try {
      setIsSubmitting(true);
      setModalError(null);
      await generateReport({
        plant_id: modalPlantId,
        report_type: modalReportType,
        start_date: modalStartDate,
        end_date: modalEndDate || undefined,
        title: modalTitle.trim() || undefined,
      });
      setIsModalOpen(false);
      setModalTitle('');
      await fetchReports();
    } catch (err: any) {
      setModalError(err?.response?.data?.detail || err?.message || 'Failed to enqueue report');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDownload = async (report: Report) => {
    try {
      setDownloadingId(report.id);
      const safeTitle = (report.title || 'report').toLowerCase().replace(/\s+/g, '_');
      await downloadReport(report.id, `${safeTitle}.pdf`);
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to download report. Please ensure compilation completed.');
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div className="flex-1 p-6 space-y-6 bg-slate-50 min-h-screen">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-5 rounded-xl border border-slate-200/80 shadow-xs">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 rounded-lg bg-[#004874] flex items-center justify-center text-white">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900 tracking-tight">Executive & Operational Reports</h1>
              <p className="text-xs text-slate-500 font-medium">
                Generate and download formal IEC 61724-1 daily and weekly PDF reports with grounded SCADA analytics.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => fetchReports()}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold transition"
            title="Refresh reports"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>

          <button
            onClick={handleOpenModal}
            className="flex items-center gap-2 px-4 py-2 bg-[#004874] hover:bg-[#00385a] text-white rounded-lg text-xs font-bold transition shadow-xs"
          >
            <Plus className="w-4 h-4" />
            <span>Generate Report</span>
          </button>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-white p-4 rounded-xl border border-slate-200/80">
        <div className="flex flex-wrap items-center gap-3">
          {/* Plant Selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Plant:</span>
            <select
              value={selectedPlantId}
              onChange={(e) => setSelectedPlantId(e.target.value)}
              className="text-xs font-medium border border-slate-300 rounded-lg px-2.5 py-1.5 bg-white text-slate-800 focus:outline-hidden focus:ring-2 focus:ring-[#004874]"
            >
              <option value="">All Solar Plants</option>
              {plants.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          {/* Report Type Filter */}
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg">
            {(['all', 'daily', 'weekly'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setSelectedType(t)}
                className={`px-3 py-1 rounded-md text-xs font-semibold capitalize transition ${
                  selectedType === t
                    ? 'bg-white text-slate-900 shadow-xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {t === 'all' ? 'All Types' : `${t} Reports`}
              </button>
            ))}
          </div>

          {/* Status Filter */}
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg">
            {(['all', 'completed', 'processing', 'failed'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSelectedStatus(s)}
                className={`px-3 py-1 rounded-md text-xs font-semibold capitalize transition ${
                  selectedStatus === s
                    ? 'bg-white text-slate-900 shadow-xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {s === 'all' ? 'All Statuses' : s}
              </button>
            ))}
          </div>
        </div>

        <div className="text-xs text-slate-500 font-mono">
          Showing <strong>{reports.length}</strong> reports
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="flex items-center gap-2 p-4 bg-rose-50 border border-rose-200 text-rose-800 rounded-xl text-xs font-medium">
          <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Reports Table / Grid */}
      <div className="bg-white rounded-xl border border-slate-200/80 overflow-hidden shadow-xs">
        {isLoading && reports.length === 0 ? (
          <div className="p-12 text-center space-y-3">
            <Loader2 className="w-8 h-8 text-[#004874] animate-spin mx-auto" />
            <p className="text-xs font-semibold text-slate-600">Loading generated reports catalogue...</p>
          </div>
        ) : reports.length === 0 ? (
          <div className="p-12 text-center space-y-3">
            <FileText className="w-10 h-10 text-slate-300 mx-auto" />
            <h3 className="text-sm font-bold text-slate-800">No reports generated yet</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Compile your first formal daily operational or weekly performance report with real SCADA metrics and downloadable PDF.
            </p>
            <button
              onClick={handleOpenModal}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-[#004874] text-white rounded-lg text-xs font-bold transition hover:bg-[#00385a]"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Generate First Report</span>
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 text-[11px] font-mono font-semibold uppercase text-slate-500 tracking-wider">
                  <th className="py-3 px-4">Report Details</th>
                  <th className="py-3 px-4">Plant & Period</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Key Metrics</th>
                  <th className="py-3 px-4">Generated At</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {reports.map((r) => {
                  const isProcessing = r.status === 'processing' || r.status === 'pending';
                  const isCompleted = r.status === 'completed';
                  const isFailed = r.status === 'failed';
                  const isDownloading = downloadingId === r.id;

                  return (
                    <tr key={r.id} className="hover:bg-slate-50/70 transition">
                      {/* Title & Type */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-start gap-2.5">
                          <div className={`mt-0.5 p-1.5 rounded-md ${
                            r.report_type === 'daily'
                              ? 'bg-sky-100 text-sky-800'
                              : 'bg-indigo-100 text-indigo-800'
                          }`}>
                            <FileText className="w-4 h-4" />
                          </div>
                          <div>
                            <div className="font-bold text-slate-900">{r.title}</div>
                            <div className="flex items-center gap-2 mt-0.5">
                              <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded font-bold uppercase ${
                                r.report_type === 'daily'
                                  ? 'bg-sky-50 text-sky-700 border border-sky-200'
                                  : 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                              }`}>
                                {r.report_type}
                              </span>
                              {r.file_size_bytes && (
                                <span className="text-[11px] text-slate-400 font-mono">
                                  {(r.file_size_bytes / 1024).toFixed(1)} KB
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Plant & Date */}
                      <td className="py-3.5 px-4 font-mono text-[11px]">
                        <div className="font-semibold text-slate-800">{r.plant_name || 'Surya Solar Farm'}</div>
                        <div className="text-slate-500 mt-0.5">
                          {r.start_date} {r.report_type === 'weekly' && `→ ${r.end_date}`}
                        </div>
                      </td>

                      {/* Status */}
                      <td className="py-3.5 px-4">
                        {isCompleted && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                            <span>Completed</span>
                          </span>
                        )}
                        {isProcessing && (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-sky-50 text-sky-700 border border-sky-200">
                            <Loader2 className="w-3 h-3 text-sky-600 animate-spin" />
                            <span>Compiling PDF</span>
                          </span>
                        )}
                        {isFailed && (
                          <span
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200"
                            title={r.error_message || 'Report compilation error'}
                          >
                            <AlertTriangle className="w-3 h-3 text-rose-600" />
                            <span>Failed</span>
                          </span>
                        )}
                      </td>

                      {/* Key Metrics */}
                      <td className="py-3.5 px-4">
                        {r.metrics_summary ? (
                          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
                            {r.metrics_summary.gross_generation_mwh !== undefined && (
                              <span className="bg-slate-100 text-slate-800 px-2 py-0.5 rounded font-bold">
                                {r.metrics_summary.gross_generation_mwh} MWh
                              </span>
                            )}
                            {r.metrics_summary.performance_ratio !== undefined && (
                              <span className="bg-blue-50 text-blue-800 px-2 py-0.5 rounded font-bold">
                                PR {r.metrics_summary.performance_ratio}%
                              </span>
                            )}
                            {r.metrics_summary.has_telemetry_gap && (
                              <span
                                className="bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-bold text-[10px]"
                                title="Telemetry gap detected"
                              >
                                GAP
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-400 font-mono text-[11px]">—</span>
                        )}
                      </td>

                      {/* Generated Time */}
                      <td className="py-3.5 px-4 text-slate-500 font-mono text-[11px]">
                        {new Date(r.created_at).toLocaleString(undefined, {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>

                      {/* Actions */}
                      <td className="py-3.5 px-4 text-right space-x-1.5">
                        <button
                          onClick={() => setViewReport(r)}
                          className="px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold transition inline-flex items-center gap-1"
                          title="View Report Metadata & Metrics"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          <span>View</span>
                        </button>

                        <button
                          onClick={() => handleDownload(r)}
                          disabled={!isCompleted || isDownloading}
                          className={`px-3 py-1.5 rounded-lg text-xs font-bold transition inline-flex items-center gap-1.5 ${
                            isCompleted
                              ? 'bg-[#004874] hover:bg-[#00385a] text-white shadow-xs'
                              : 'bg-slate-200 text-slate-400 cursor-not-allowed'
                          }`}
                        >
                          {isDownloading ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Download className="w-3.5 h-3.5" />
                          )}
                          <span>Download PDF</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Generate Report Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full shadow-2xl border border-slate-200 overflow-hidden">
            <div className="flex items-center justify-between p-5 border-b border-slate-100 bg-slate-50/50">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-[#004874] flex items-center justify-center text-white">
                  <FileText className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-900 text-base">Generate SCADA Report</h3>
                  <p className="text-xs text-slate-500">Compile an executive PDF report grounded on verified telemetry.</p>
                </div>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 transition p-1 rounded-lg hover:bg-slate-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleGenerateSubmit} className="p-6 space-y-4">
              {modalError && (
                <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 rounded-lg text-xs font-medium flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0 text-rose-500" />
                  <span>{modalError}</span>
                </div>
              )}

              {/* Plant Selection */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5 uppercase tracking-wider">
                  Target Solar Plant *
                </label>
                <select
                  value={modalPlantId}
                  onChange={(e) => setModalPlantId(e.target.value)}
                  className="w-full text-xs font-medium border border-slate-300 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-hidden focus:ring-2 focus:ring-[#004874]"
                  required
                >
                  {plants.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.capacity_ac_kw ? (p.capacity_ac_kw / 1000).toFixed(1) : '—'} MW AC)
                    </option>
                  ))}
                </select>
              </div>

              {/* Report Periodicity Toggle */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5 uppercase tracking-wider">
                  Report Type *
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => handleReportTypeChange('daily')}
                    className={`p-3 rounded-xl border text-left transition ${
                      modalReportType === 'daily'
                        ? 'border-[#004874] bg-sky-50/60 ring-2 ring-[#004874]/20'
                        : 'border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    <div className="font-bold text-xs text-slate-900">Daily Operational</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">24-hour diurnal profile & inverter deficit breakdown</div>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleReportTypeChange('weekly')}
                    className={`p-3 rounded-xl border text-left transition ${
                      modalReportType === 'weekly'
                        ? 'border-[#004874] bg-sky-50/60 ring-2 ring-[#004874]/20'
                        : 'border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    <div className="font-bold text-xs text-slate-900">Weekly Performance</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">7-day aggregate PR, CUF trends & loss triage</div>
                  </button>
                </div>
              </div>

              {/* Date Selection */}
              {modalReportType === 'daily' ? (
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider">
                      Target Date *
                    </label>
                    <span className="text-[11px] font-mono text-slate-500">
                      24-hour single-day report (00:00 – 23:59 UTC)
                    </span>
                  </div>
                  <input
                    type="date"
                    value={modalStartDate}
                    onChange={(e) => handleStartDateChange(e.target.value)}
                    className="w-full text-xs font-mono border border-slate-300 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-hidden focus:ring-2 focus:ring-[#004874]"
                    required
                  />
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1.5 uppercase tracking-wider">
                      Start Date *
                    </label>
                    <input
                      type="date"
                      value={modalStartDate}
                      onChange={(e) => handleStartDateChange(e.target.value)}
                      className="w-full text-xs font-mono border border-slate-300 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-hidden focus:ring-2 focus:ring-[#004874]"
                      required
                    />
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider">
                        End Date
                      </label>
                      <span className="text-[10px] font-mono text-sky-700 bg-sky-50 px-1.5 py-0.5 rounded border border-sky-200">
                        7-Day Window
                      </span>
                    </div>
                    <input
                      type="date"
                      value={modalEndDate}
                      onChange={(e) => setModalEndDate(e.target.value)}
                      className="w-full text-xs font-mono border border-slate-300 rounded-lg px-3 py-2 bg-white text-slate-800 focus:outline-hidden focus:ring-2 focus:ring-[#004874]"
                    />
                  </div>
                </div>
              )}

              {/* Custom Title (Optional) */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5 uppercase tracking-wider">
                  Custom Title (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Mid-Summer Degradation & Inverter Triage Report"
                  value={modalTitle}
                  onChange={(e) => setModalTitle(e.target.value)}
                  className="w-full text-xs border border-slate-300 rounded-lg px-3 py-2 bg-white text-slate-800 placeholder-slate-400 focus:outline-hidden focus:ring-2 focus:ring-[#004874]"
                />
              </div>

              {/* Actions */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 border border-slate-200 text-slate-700 rounded-lg text-xs font-semibold hover:bg-slate-50 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex items-center gap-2 px-5 py-2 bg-[#004874] hover:bg-[#00385a] text-white rounded-lg text-xs font-bold transition shadow-xs disabled:opacity-60"
                >
                  {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Generate PDF Report</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Details Modal */}
      {viewReport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl max-w-xl w-full shadow-2xl border border-slate-200 overflow-hidden">
            <div className="flex items-center justify-between p-5 border-b border-slate-100 bg-slate-50/50">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-[#004874] flex items-center justify-center text-white">
                  <FileText className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-900 text-sm">{viewReport.title}</h3>
                  <p className="text-xs text-slate-500 font-mono">ID: {viewReport.id}</p>
                </div>
              </div>
              <button
                onClick={() => setViewReport(null)}
                className="text-slate-400 hover:text-slate-600 transition p-1 rounded-lg hover:bg-slate-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-3 p-3 bg-slate-50 rounded-xl border border-slate-200/80 font-mono text-[11px]">
                <div>
                  <span className="text-slate-400 block uppercase text-[9px] font-semibold">Report Periodicity</span>
                  <span className="font-bold text-slate-800 uppercase">{viewReport.report_type}</span>
                </div>
                <div>
                  <span className="text-slate-400 block uppercase text-[9px] font-semibold">Status</span>
                  <span className="font-bold text-emerald-700 capitalize">{viewReport.status}</span>
                </div>
                <div>
                  <span className="text-slate-400 block uppercase text-[9px] font-semibold">Date Range</span>
                  <span className="text-slate-800">{viewReport.start_date} to {viewReport.end_date}</span>
                </div>
                <div>
                  <span className="text-slate-400 block uppercase text-[9px] font-semibold">File Size</span>
                  <span className="text-slate-800">
                    {viewReport.file_size_bytes ? `${(viewReport.file_size_bytes / 1024).toFixed(1)} KB` : 'N/A'}
                  </span>
                </div>
              </div>

              {viewReport.metrics_summary && (
                <div>
                  <h4 className="font-bold text-slate-900 mb-2 uppercase tracking-wider text-[11px]">
                    Authoritative Telemetry Metrics
                  </h4>
                  <div className="grid grid-cols-3 gap-2.5 font-mono">
                    <div className="p-2.5 bg-sky-50/70 border border-sky-100 rounded-lg">
                      <div className="text-[10px] text-sky-800 font-semibold">Gross Generation</div>
                      <div className="text-base font-bold text-[#004874] mt-0.5">
                        {viewReport.metrics_summary.gross_generation_mwh ?? '—'} MWh
                      </div>
                    </div>
                    <div className="p-2.5 bg-blue-50/70 border border-blue-100 rounded-lg">
                      <div className="text-[10px] text-blue-800 font-semibold">Performance Ratio</div>
                      <div className="text-base font-bold text-slate-900 mt-0.5">
                        {viewReport.metrics_summary.performance_ratio ?? '—'}%
                      </div>
                    </div>
                    <div className="p-2.5 bg-emerald-50/70 border border-emerald-100 rounded-lg">
                      <div className="text-[10px] text-emerald-800 font-semibold">Revenue Generated</div>
                      <div className="text-base font-bold text-emerald-800 mt-0.5">
                        ₹{viewReport.metrics_summary.revenue_generated_inr ? viewReport.metrics_summary.revenue_generated_inr.toLocaleString() : '—'}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {viewReport.error_message && (
                <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 rounded-lg">
                  <div className="font-bold text-rose-800 mb-0.5">Compilation Failure:</div>
                  <p className="font-mono text-[11px]">{viewReport.error_message}</p>
                </div>
              )}

              <div className="flex items-center justify-between pt-3 border-t border-slate-100">
                {onAskCopilot && (
                  <button
                    onClick={() => {
                      onAskCopilot(`Summarize findings from report "${viewReport.title}" (${viewReport.start_date} to ${viewReport.end_date})`);
                      setViewReport(null);
                    }}
                    className="text-[#004874] hover:underline font-bold text-xs"
                  >
                    Ask Copilot about this report →
                  </button>
                )}

                <div className="flex items-center gap-2 ml-auto">
                  <button
                    onClick={() => setViewReport(null)}
                    className="px-3.5 py-1.5 border border-slate-200 text-slate-700 rounded-lg text-xs font-semibold hover:bg-slate-50"
                  >
                    Close
                  </button>
                  {viewReport.status === 'completed' && (
                    <button
                      onClick={() => handleDownload(viewReport)}
                      className="px-3.5 py-1.5 bg-[#004874] text-white rounded-lg text-xs font-bold hover:bg-[#00385a] transition inline-flex items-center gap-1.5"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Download PDF</span>
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

