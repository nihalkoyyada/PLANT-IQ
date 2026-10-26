import React, { useEffect, useState, useMemo } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Filter,
  Search,
  RefreshCw,
  Bell,
  ArrowLeft,
  ChevronRight,
  Zap,
  DollarSign,
  TrendingDown,
  Layers,
  Send,
  Plus,
  Trash2,
  Info,
  CheckSquare,
  Square,
  Activity,
  FileText,
  AlertCircle,
  ExternalLink,
  Sparkles,
} from 'lucide-react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceArea,
} from 'recharts';
import {
  getAnomalies,
  getAnomalySummary,
  getAnomalyEvidence,
  triageAnomaly,
  bulkTriageAnomalies,
  triggerPlantAnomalyScan,
} from '../api/anomalies';
import {
  getAlertRules,
  createAlertRule,
  deleteAlertRule,
  testAlertRule,
  getAlertDeliveries,
  getEmailDiagnostics,
  EmailDiagnostics,
} from '../api/alertRules';
import { getPlants } from '../api/plants';
import { getDetectors } from '../api/detectors';
import {
  Anomaly,
  AnomalyEvidenceResponse,
  AnomalySeverity,
  AnomalyStatus,
  AnomalySummary,
  AlertRule,
  AlertDelivery,
  Plant,
  Detector,
} from '../types';
import { EmptyState } from '../components/common/EmptyState';

const SEVERITY_COLORS: Record<AnomalySeverity, { bg: string; text: string; border: string; badge: string }> = {
  critical: { bg: 'bg-rose-50', text: 'text-rose-700', border: 'border-rose-200', badge: 'bg-rose-500' },
  high: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', badge: 'bg-amber-500' },
  medium: { bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200', badge: 'bg-yellow-500' },
  low: { bg: 'bg-sky-50', text: 'text-sky-700', border: 'border-sky-200', badge: 'bg-sky-400' },
};

const STATUS_CONFIG: Record<AnomalyStatus, { label: string; badge: string; text: string }> = {
  open: { label: 'Open', badge: 'bg-rose-100 text-rose-800 border-rose-200', text: 'text-rose-600' },
  acknowledged: { label: 'Acknowledged', badge: 'bg-amber-100 text-amber-800 border-amber-200', text: 'text-amber-600' },
  resolved: { label: 'Resolved', badge: 'bg-emerald-100 text-emerald-800 border-emerald-200', text: 'text-emerald-600' },
  false_positive: { label: 'False Positive', badge: 'bg-slate-100 text-slate-700 border-slate-200', text: 'text-slate-500' },
};

export const AnomaliesPage: React.FC<{
  onAskCopilot?: (prompt: string, context?: any) => void;
}> = ({ onAskCopilot }) => {
  // Navigation / View Tabs: 'inbox' | 'detail' | 'alerts'
  const [activeView, setActiveView] = useState<'inbox' | 'detail' | 'alerts'>('inbox');
  const [selectedAnomalyId, setSelectedAnomalyId] = useState<string | null>(null);

  // Data states
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [summary, setSummary] = useState<AnomalySummary | null>(null);
  const [plants, setPlants] = useState<Plant[]>([]);
  const [detectors, setDetectors] = useState<Detector[]>([]);
  const [alertRules, setAlertRules] = useState<AlertRule[]>([]);
  const [deliveries, setDeliveries] = useState<AlertDelivery[]>([]);
  const [evidenceData, setEvidenceData] = useState<AnomalyEvidenceResponse | null>(null);

  // Loading & Action states
  const [loading, setLoading] = useState<boolean>(true);
  const [evidenceLoading, setEvidenceLoading] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterPlant, setFilterPlant] = useState<string>('all');
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<string>('open');
  const [filterDetector, setFilterDetector] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Bulk Selection
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkModalOpen, setBulkModalOpen] = useState<boolean>(false);
  const [bulkTargetStatus, setBulkTargetStatus] = useState<AnomalyStatus>('acknowledged');
  const [bulkNote, setBulkNote] = useState<string>('');

  // Triage single dialog
  const [singleTriageModal, setSingleTriageModal] = useState<boolean>(false);
  const [targetTriageStatus, setTargetTriageStatus] = useState<AnomalyStatus>('acknowledged');
  const [triageNote, setTriageNote] = useState<string>('');

  // Create Alert Rule Modal
  const [createRuleModalOpen, setCreateRuleModalOpen] = useState<boolean>(false);
  const [newRuleData, setNewRuleData] = useState({
    name: '',
    plant_id: '',
    metric: 'severity',
    threshold: 1.0,
    direction: 'above' as 'above' | 'below',
    severity: 'critical' as 'info' | 'warning' | 'critical',
    channels: ['email'] as ('email' | 'webhook')[],
    webhook_url: '',
    recipients: '',
  });

  // Test Alert Dispatch Modal
  const [testModalRule, setTestModalRule] = useState<AlertRule | null>(null);
  const [testRecipientOverride, setTestRecipientOverride] = useState<string>('');
  const [testMessageInput, setTestMessageInput] = useState<string>('');
  const [testDispatchLoading, setTestDispatchLoading] = useState<boolean>(false);
  const [testDispatchResult, setTestDispatchResult] = useState<{
    status: string;
    message: string;
    recipient: string;
  } | null>(null);
  const [emailDiagnostics, setEmailDiagnostics] = useState<EmailDiagnostics | null>(null);

  // Load baseline metadata
  useEffect(() => {
    Promise.all([getPlants(), getDetectors()])
      .then(([plantsData, detectorsData]) => {
        setPlants(plantsData);
        setDetectors(detectorsData);
        if (plantsData.length > 0 && !newRuleData.plant_id) {
          setNewRuleData((prev) => ({ ...prev, plant_id: plantsData[0].id }));
        }
      })
      .catch((err) => console.warn('Could not load plant/detector metadata:', err));
  }, []);

  // Fetch anomalies & summary
  const loadData = () => {
    setLoading(true);
    setError(null);
    const pId = filterPlant !== 'all' ? filterPlant : undefined;

    Promise.all([
      getAnomalies({
        plant_id: pId,
        severity: filterSeverity !== 'all' ? filterSeverity : undefined,
        status: filterStatus !== 'all' ? filterStatus : undefined,
        detector_id: filterDetector !== 'all' ? filterDetector : undefined,
      }),
      getAnomalySummary(pId),
      getAlertRules(pId),
      getAlertDeliveries(pId, 25),
    ])
      .then(([anomList, sumData, rulesData, delivsData]) => {
        setAnomalies(anomList);
        setSummary(sumData);
        setAlertRules(rulesData);
        setDeliveries(delivsData);
        setLoading(false);
      })
      .catch((err) => {
        setError(err?.response?.data?.detail || 'Failed to load anomalies data from SCADA backend.');
        setLoading(false);
      });
  };

  useEffect(() => {
    loadData();
  }, [filterPlant, filterSeverity, filterStatus, filterDetector]);

  // Load detail evidence when single anomaly is selected
  useEffect(() => {
    if (activeView === 'detail' && selectedAnomalyId) {
      setEvidenceLoading(true);
      getAnomalyEvidence(selectedAnomalyId)
        .then((ev) => {
          setEvidenceData(ev);
          setEvidenceLoading(false);
        })
        .catch((err) => {
          console.error('Failed to load evidence chart:', err);
          setEvidenceLoading(false);
        });
    }
  }, [activeView, selectedAnomalyId]);

  // Filtered anomalies by search query, with unresolved Critical/High anomalies prioritized
  const filteredAnomalies = useMemo(() => {
    const list = anomalies.filter((a) => {
      // Exclude superseded duplicate records
      if (a.details?.is_superseded) return false;
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return (
        (a.summary && a.summary.toLowerCase().includes(q)) ||
        (a.asset_name && a.asset_name.toLowerCase().includes(q)) ||
        (a.plant_name && a.plant_name.toLowerCase().includes(q)) ||
        (a.detector_name && a.detector_name.toLowerCase().includes(q)) ||
        a.severity.toLowerCase().includes(q) ||
        a.status.toLowerCase().includes(q)
      );
    });

    // Never display the same logical event twice in one view
    const seenEventKeys = new Set<string>();
    const uniqueList = list.filter((a) => {
      const eventKey = a.details?.event_fingerprint || `${a.plant_id}:${a.asset_id || 'none'}:${a.start_time}:${a.details?.detector_method || a.source}`;
      if (seenEventKeys.has(eventKey)) return false;
      seenEventKeys.add(eventKey);
      return true;
    });

    const SEVERITY_RANK: Record<string, number> = {
      critical: 4,
      high: 3,
      medium: 2,
      low: 1,
    };

    return [...uniqueList].sort((a, b) => {
      const aUnresolved = a.status !== 'resolved' && a.status !== 'false_positive';
      const bUnresolved = b.status !== 'resolved' && b.status !== 'false_positive';
      const aCritHigh = a.severity === 'critical' || a.severity === 'high';
      const bCritHigh = b.severity === 'critical' || b.severity === 'high';

      // Priority tier 2: Unresolved Critical/High
      // Priority tier 1: Other Unresolved
      // Priority tier 0: Resolved / False Positive
      const aTier = aUnresolved && aCritHigh ? 2 : aUnresolved ? 1 : 0;
      const bTier = bUnresolved && bCritHigh ? 2 : bUnresolved ? 1 : 0;

      if (aTier !== bTier) {
        return bTier - aTier;
      }

      // Within tier, rank by severity
      const aSev = SEVERITY_RANK[a.severity] || 0;
      const bSev = SEVERITY_RANK[b.severity] || 0;
      if (aSev !== bSev) {
        return bSev - aSev;
      }

      // Then by start_time descending
      return new Date(b.start_time).getTime() - new Date(a.start_time).getTime();
    });
  }, [anomalies, searchQuery]);

  // Bulk checkbox handlers
  const handleToggleSelectAll = () => {
    if (selectedIds.length === filteredAnomalies.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(filteredAnomalies.map((a) => a.id));
    }
  };

  const handleToggleSelectOne = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  // Bulk triage execution
  const executeBulkTriage = async () => {
    if (selectedIds.length === 0) return;
    setActionLoading(true);
    try {
      await bulkTriageAnomalies({
        anomaly_ids: selectedIds,
        status: bulkTargetStatus,
        status_note: bulkNote || `Bulk triage action to ${bulkTargetStatus}`,
      });
      setSelectedIds([]);
      setBulkModalOpen(false);
      setBulkNote('');
      loadData();
    } catch (err: any) {
      alert(`Bulk triage failed: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  // Single triage execution
  const executeSingleTriage = async () => {
    if (!selectedAnomalyId) return;
    setActionLoading(true);
    try {
      await triageAnomaly(selectedAnomalyId, {
        status: targetTriageStatus,
        status_note: triageNote || `Triage action: ${targetTriageStatus}`,
      });
      setSingleTriageModal(false);
      setTriageNote('');
      loadData();
      if (activeView === 'detail') {
        const ev = await getAnomalyEvidence(selectedAnomalyId);
        setEvidenceData(ev);
      }
    } catch (err: any) {
      alert(`Triage failed: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  // Trigger manual plant scan
  const handleTriggerScan = async () => {
    if (plants.length === 0) return;
    const targetPlantId = filterPlant !== 'all' ? filterPlant : plants[0].id;
    setActionLoading(true);
    setScanMessage(null);
    try {
      const res = await triggerPlantAnomalyScan(targetPlantId, 24);
      setScanMessage(
        `Scanned ${res.assets_scanned ?? 0} assets, evaluated ${res.anomalies_detected ?? 0} candidate detections (${res.anomalies_created ?? 0} new anomalies created, ${res.anomalies_merged ?? 0} reconciled with existing anomalies).`
      );
      loadData();
    } catch (err: any) {
      alert(`Scan failed: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  // Create Alert Rule
  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      const recipients = newRuleData.recipients
        .split(',')
        .map((r) => r.trim())
        .filter((r) => r.length > 0);

      await createAlertRule({
        name: newRuleData.name,
        plant_id: newRuleData.plant_id,
        metric: newRuleData.metric,
        threshold: Number(newRuleData.threshold),
        direction: newRuleData.direction,
        severity: newRuleData.severity,
        channels: newRuleData.channels,
        enabled: true,
        config: {
          recipients: recipients.length > 0 ? recipients : undefined,
          webhook_url: newRuleData.webhook_url || undefined,
        },
      });
      setCreateRuleModalOpen(false);
      loadData();
    } catch (err: any) {
      alert(`Failed to create alert rule: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  // Delete Alert Rule
  const handleDeleteRule = async (ruleId: string) => {
    if (!confirm('Are you sure you want to delete this alert rule?')) return;
    try {
      await deleteAlertRule(ruleId);
      loadData();
    } catch (err: any) {
      alert(`Failed to delete rule: ${err?.response?.data?.detail || err.message}`);
    }
  };

  // Test Alert Dispatch
  const openTestDispatchModal = (rule: AlertRule) => {
    setTestModalRule(rule);
    const recs = rule.config?.recipients;
    const defaultRec = Array.isArray(recs) && recs.length > 0 ? recs[0] : (typeof recs === 'string' ? recs : '');
    setTestRecipientOverride(defaultRec);
    setTestMessageInput(`PlantIQ Live Alert Verification Ping [${rule.name}]`);
    setTestDispatchResult(null);
    getEmailDiagnostics().then(setEmailDiagnostics).catch(() => setEmailDiagnostics(null));
  };

  const handleExecuteTestDispatch = async () => {
    if (!testModalRule) return;
    setTestDispatchLoading(true);
    setTestDispatchResult(null);
    try {
      const res = await testAlertRule(testModalRule.id, {
        recipient_override: testRecipientOverride.trim() || undefined,
        test_message: testMessageInput.trim() || undefined,
      });
      setTestDispatchResult(res);
      loadData();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err.message || 'Notification test dispatch failed';
      setTestDispatchResult({
        status: 'failed',
        message: detail,
        recipient: testRecipientOverride.trim() || 'Unspecified',
      });
      loadData();
    } finally {
      setTestDispatchLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* View Switcher & Title Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-4 rounded-xl border border-slate-200/80 shadow-xs">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-[#004874] flex items-center justify-center text-white shadow-xs">
            <AlertTriangle className="w-5 h-5 text-amber-300" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-slate-800 tracking-tight flex items-center gap-2">
              <span>ANOMALY INTELLIGENCE & TRIAGE</span>
            </h1>
            <p className="text-xs text-slate-500 font-medium">
              Multi-detector algorithmic triage, root-cause diagnostics & configurable alert dispatch
            </p>
          </div>
        </div>

        {/* View Switcher Pills */}
        <div className="flex items-center gap-2">
          <div className="bg-slate-100 p-1 rounded-lg border border-slate-200 flex items-center">
            <button
              id="view-tab-inbox"
              onClick={() => setActiveView('inbox')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${
                activeView === 'inbox'
                  ? 'bg-white text-slate-800 shadow-xs'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Anomaly Inbox {summary ? `(${summary.open_count})` : ''}
            </button>
            <button
              id="view-tab-alerts"
              onClick={() => setActiveView('alerts')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold flex items-center gap-1.5 transition ${
                activeView === 'alerts'
                  ? 'bg-white text-slate-800 shadow-xs'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              <Bell className="w-3.5 h-3.5" />
              <span>Alert Rules & Dispatch</span>
            </button>
          </div>

          <button
            id="btn-scan-plant"
            onClick={handleTriggerScan}
            disabled={actionLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#004874] hover:bg-[#00385c] text-white text-xs font-semibold shadow-xs transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${actionLoading ? 'animate-spin' : ''}`} />
            <span>Run Detector Scan</span>
          </button>
        </div>
      </div>

      {scanMessage && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs px-4 py-2.5 rounded-lg flex items-center justify-between">
          <span className="font-medium flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            {scanMessage}
          </span>
          <button onClick={() => setScanMessage(null)} className="text-emerald-600 hover:text-emerald-900 font-bold text-sm">
            ×
          </button>
        </div>
      )}

      {/* VIEW: ANOMALY DETAIL & RCA */}
      {activeView === 'detail' && (
        <div className="space-y-6 animate-fadeIn">
          {/* Breadcrumb Header */}
          <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
            <button
              id="btn-back-to-inbox"
              onClick={() => {
                setActiveView('inbox');
                setSelectedAnomalyId(null);
                setEvidenceData(null);
              }}
              className="flex items-center gap-2 text-xs font-bold text-slate-600 hover:text-[#004874] transition"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>BACK TO ANOMALY INBOX</span>
            </button>

            {evidenceData && (
              <div className="flex items-center gap-2">
                {onAskCopilot && (
                  <button
                    id="btn-detail-ask-copilot"
                    onClick={() => {
                      onAskCopilot(
                        `Investigate ${evidenceData.severity.toUpperCase()} anomaly on ${
                          evidenceData.asset_name || 'Inverter Asset'
                        }: ${evidenceData.canonical_key || 'active_power'} outlier starting ${evidenceData.start_time}. Peak loss is ${
                          evidenceData.estimated_loss_kw || 0
                        } kW. Evaluate hypotheses and recommend maintenance actions.`,
                        {
                          route: 'anomalies',
                          anomalyId: evidenceData.anomaly_id,
                          anomalyTitle: evidenceData.detector_name || evidenceData.canonical_key || 'Detected Anomaly',
                          assetId: evidenceData.asset_id || undefined,
                          assetName: evidenceData.asset_name || undefined,
                        }
                      );
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-bold shadow-xs transition"
                  >
                    <Sparkles className="w-3.5 h-3.5 text-sky-200" />
                    <span>Ask Copilot</span>
                  </button>
                )}
                <button
                  id="btn-detail-triage"
                  onClick={() => {
                    setTargetTriageStatus('acknowledged');
                    setSingleTriageModal(true);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-white text-xs font-bold shadow-xs transition"
                >
                  Acknowledge
                </button>
                <button
                  id="btn-detail-resolve"
                  onClick={() => {
                    setTargetTriageStatus('resolved');
                    setSingleTriageModal(true);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold shadow-xs transition"
                >
                  Resolve
                </button>
                <button
                  id="btn-detail-fp"
                  onClick={() => {
                    setTargetTriageStatus('false_positive');
                    setSingleTriageModal(true);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-slate-200 hover:bg-slate-300 text-slate-700 text-xs font-bold shadow-xs transition"
                >
                  False Positive
                </button>
              </div>
            )}
          </div>

          {evidenceLoading ? (
            <div className="bg-white p-12 rounded-xl border border-slate-200 text-center">
              <RefreshCw className="w-8 h-8 text-[#004874] animate-spin mx-auto mb-3" />
              <p className="text-xs font-mono font-semibold text-slate-600 uppercase">
                Querying TimescaleDB Telemetry Evidence Window...
              </p>
            </div>
          ) : evidenceData ? (
            <>
              {/* Anomaly Overview Card */}
              <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`px-2.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-wider ${SEVERITY_COLORS[evidenceData.severity].bg} ${SEVERITY_COLORS[evidenceData.severity].text} border ${SEVERITY_COLORS[evidenceData.severity].border}`}>
                        {evidenceData.severity} SEVERITY
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${STATUS_CONFIG[evidenceData.status].badge} border`}>
                        {STATUS_CONFIG[evidenceData.status].label}
                      </span>
                      <span className="text-xs font-mono text-slate-400">
                        METHOD: {evidenceData.detector_method?.toUpperCase()}
                      </span>
                    </div>
                    <h2 className="text-base font-bold text-slate-800">
                      {evidenceData.asset_name || 'Inverter Asset'} — {evidenceData.canonical_key || 'active_power'} Outlier Event
                    </h2>
                  </div>

                  <div className="text-right text-xs font-mono">
                    <div className="text-slate-400 text-[10px] uppercase font-bold">Detected Window</div>
                    <div className="text-slate-700 font-semibold">
                      {new Date(evidenceData.start_time).toLocaleString()}
                      {evidenceData.end_time ? ` → ${new Date(evidenceData.end_time).toLocaleTimeString()}` : ''}
                    </div>
                  </div>
                </div>

                {/* Metric Summary Chips */}
                <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                  <div className="bg-slate-50 p-3 rounded-lg border border-slate-200/80">
                    <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Avg Observed Power</div>
                    <div className="text-sm font-mono font-bold text-slate-800">
                      {evidenceData.observed_value !== null ? `${evidenceData.observed_value} kW` : '—'}
                    </div>
                  </div>
                  <div className="bg-slate-50 p-3 rounded-lg border border-slate-200/80">
                    <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Expected Baseline (Peak)</div>
                    <div className="text-sm font-mono font-bold text-slate-800">
                      {evidenceData.baseline_value !== null ? `${evidenceData.baseline_value} kW` : '—'}
                    </div>
                  </div>
                  <div className="bg-slate-50 p-3 rounded-lg border border-slate-200/80">
                    <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Threshold Bound (Peak)</div>
                    <div className="text-sm font-mono font-bold text-slate-800">
                      {evidenceData.threshold_value !== null ? `${evidenceData.threshold_value} kW` : '—'}
                    </div>
                  </div>
                  <div className="bg-amber-50/50 p-3 rounded-lg border border-amber-200/80">
                    <div className="text-[10px] font-mono uppercase text-amber-700 font-bold">Peak Power Deficit</div>
                    <div className="text-sm font-mono font-bold text-amber-900">
                      {evidenceData.estimated_loss_kw ? `${evidenceData.estimated_loss_kw} kW` : '0.0 kW'}
                    </div>
                  </div>
                  <div className="bg-rose-50/50 p-3 rounded-lg border border-rose-200/80">
                    <div className="text-[10px] font-mono uppercase text-rose-700 font-bold">Integrated Energy Loss</div>
                    <div className="text-sm font-mono font-bold text-rose-900">
                      {evidenceData.estimated_loss_kwh !== null && evidenceData.estimated_loss_kwh !== undefined
                        ? `${evidenceData.estimated_loss_kwh.toLocaleString()} kWh`
                        : 'N/A'}
                    </div>
                  </div>
                  <div className="bg-emerald-50/50 p-3 rounded-lg border border-emerald-200/80">
                    <div className="text-[10px] font-mono uppercase text-emerald-700 font-bold">Financial Impact</div>
                    <div className="text-sm font-mono font-bold text-emerald-900">
                      {evidenceData.estimated_loss_inr !== null && evidenceData.estimated_loss_inr !== undefined
                        ? `₹${evidenceData.estimated_loss_inr.toLocaleString()}`
                        : 'N/A'}
                    </div>
                  </div>
                </div>
              </div>

              {/* Telemetry Evidence Chart */}
              <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-mono font-bold uppercase text-slate-800 tracking-wider flex items-center gap-2">
                      <Activity className="w-4 h-4 text-[#004874]" />
                      <span>TELEMETRY EVIDENCE CHART (OBSERVED VS BASELINE CONTOUR)</span>
                    </h3>
                    <p className="text-[11px] text-slate-500 font-medium">
                      High-frequency telemetry samples ±6 hours around detected anomaly interval. Shaded region indicates active fault duration.
                    </p>
                  </div>
                  <div className="flex items-center gap-3 text-[11px] font-mono">
                    <span className="flex items-center gap-1.5 text-[#004874] font-bold">
                      <span className="w-3 h-0.5 bg-[#004874]" /> Observed kW
                    </span>
                    <span className="flex items-center gap-1.5 text-slate-400 font-semibold">
                      <span className="w-3 h-0.5 bg-slate-400 border-dashed" /> Expected Baseline
                    </span>
                    <span className="flex items-center gap-1.5 text-rose-600 font-semibold">
                      <span className="w-2.5 h-2.5 rounded-xs bg-rose-200/60 border border-rose-300" /> Fault Window
                    </span>
                  </div>
                </div>

                <div className="h-72 w-full pt-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={evidenceData.data_points} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis
                        dataKey="ts"
                        tickFormatter={(v) => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        tick={{ fontSize: 10, fill: '#64748b' }}
                      />
                      <YAxis
                        tick={{ fontSize: 10, fill: '#64748b' }}
                        unit={` ${evidenceData.unit}`}
                      />
                      <Tooltip
                        content={({ active, payload, label }) => {
                          if (active && payload && payload.length) {
                            const obs = payload[0]?.value as number | undefined;
                            const base = payload[1]?.value as number | undefined;
                            const instDeficit = (obs !== undefined && base !== undefined && base > obs)
                              ? Math.max(0, base - obs)
                              : 0;
                            return (
                              <div className="bg-slate-900 text-white p-3 rounded-lg shadow-xl text-xs font-mono space-y-1">
                                <div className="text-slate-400">{new Date(label).toLocaleString()}</div>
                                <div className="text-sky-300 font-bold">Observed: {obs !== undefined ? `${obs} kW` : '—'}</div>
                                <div className="text-slate-300">Baseline: {base !== undefined ? `${base} kW` : '—'}</div>
                                {instDeficit > 0 && (
                                  <div className="text-amber-300">Instant Deficit: {instDeficit.toFixed(1)} kW</div>
                                )}
                              </div>
                            );
                          }
                          return null;
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="observed"
                        stroke="#004874"
                        strokeWidth={2.5}
                        dot={{ r: 2 }}
                        activeDot={{ r: 5 }}
                        name="Observed"
                      />
                      <Line
                        type="monotone"
                        dataKey="baseline"
                        stroke="#94a3b8"
                        strokeWidth={1.5}
                        strokeDasharray="4 4"
                        dot={false}
                        name="Baseline"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Root Cause Analysis (RCA) Split Section */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Left: Ranked AI Hypotheses */}
                <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs space-y-4">
                  <div className="border-b border-slate-100 pb-2">
                    <h3 className="text-xs font-mono font-bold uppercase text-slate-800 tracking-wider flex items-center gap-2">
                      <Zap className="w-4 h-4 text-amber-500" />
                      <span>AI-GENERATED ROOT CAUSE HYPOTHESES (RANKED)</span>
                    </h3>
                    <p className="text-[11px] text-slate-500">
                      Algorithmic attribution based on telemetry signatures, loss gradients, and historical fault catalog.
                    </p>
                  </div>

                  <div className="space-y-3">
                    {evidenceData.ranked_hypotheses.map((h) => (
                      <div key={h.rank} className="p-3.5 rounded-lg border border-slate-200 bg-slate-50/50 space-y-2">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="w-5 h-5 rounded-full bg-[#004874] text-white text-[10px] font-bold flex items-center justify-center font-mono">
                              #{h.rank}
                            </span>
                            <span className="text-xs font-bold text-slate-800">{h.hypothesis}</span>
                          </div>
                          <span className="text-xs font-mono font-bold text-sky-800">
                            {(h.confidence * 100).toFixed(0)}% Confidence
                          </span>
                        </div>

                        {/* Confidence Progress Bar */}
                        <div className="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
                          <div
                            className="bg-[#004874] h-1.5 rounded-full transition-all duration-500"
                            style={{ width: `${h.confidence * 100}%` }}
                          />
                        </div>

                        <p className="text-[11px] text-slate-600 leading-relaxed font-sans">{h.description}</p>
                        <div className="text-[10px] font-mono text-slate-400 font-semibold uppercase">
                          CATEGORY: {h.category}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Right: Measured Telemetry & Recommended Checks */}
                <div className="space-y-6">
                  {/* Measured Evidence Card */}
                  <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs space-y-3">
                    <div className="border-b border-slate-100 pb-2">
                      <h3 className="text-xs font-mono font-bold uppercase text-slate-800 tracking-wider flex items-center gap-2">
                        <FileText className="w-4 h-4 text-emerald-600" />
                        <span>MEASURED TELEMETRY EVIDENCE (GROUND TRUTH)</span>
                      </h3>
                      <p className="text-[11px] text-slate-500">
                        Empirically measured SCADA variables verifying anomaly existence.
                      </p>
                    </div>

                    <div className="grid grid-cols-2 gap-2.5">
                      {evidenceData.supporting_evidence.map((ev, idx) => (
                        <div key={idx} className="p-2.5 rounded-lg bg-slate-50 border border-slate-200 text-xs">
                          <div className="text-[10px] font-mono text-slate-400 uppercase font-semibold">{ev.label}</div>
                          <div className="text-xs font-mono font-bold text-slate-800 mt-0.5">{ev.value}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Recommended Field Actions Checklist */}
                  <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs space-y-3">
                    <div className="border-b border-slate-100 pb-2">
                      <h3 className="text-xs font-mono font-bold uppercase text-slate-800 tracking-wider flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-sky-600" />
                        <span>RECOMMENDED FIELD INSPECTION CHECKS</span>
                      </h3>
                      <p className="text-[11px] text-slate-500">
                        Prescribed standard operating procedure for site electrical maintenance engineers.
                      </p>
                    </div>

                    <ul className="space-y-2">
                      {evidenceData.recommended_checks.map((chk, idx) => (
                        <li key={idx} className="flex items-start gap-2.5 text-xs text-slate-700 bg-slate-50 p-2.5 rounded-lg border border-slate-200/60">
                          <CheckSquare className="w-4 h-4 text-[#004874] mt-0.5 shrink-0" />
                          <span>{chk}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <EmptyState title="Evidence Unavailable" description="Could not load anomaly evidence data." />
          )}
        </div>
      )}

      {/* VIEW: ANOMALY INBOX (UI-06) */}
      {activeView === 'inbox' && (
        <div className="space-y-6">
          {/* Executive Summary Metric Cards */}
          {summary && (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Total Anomalies</div>
                <div className="text-xl font-mono font-bold text-slate-800 mt-1">{summary.total_anomalies}</div>
              </div>

              <div className="bg-white p-4 rounded-xl border border-rose-200 shadow-xs">
                <div className="text-[10px] font-mono uppercase text-rose-600 font-bold flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                  <span>Open Unresolved</span>
                </div>
                <div className="text-xl font-mono font-bold text-rose-700 mt-1">{summary.open_count}</div>
              </div>

              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Critical / High</div>
                <div className="text-xl font-mono font-bold text-amber-600 mt-1">
                  {summary.critical_count} / {summary.high_count}
                </div>
              </div>

              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Medium / Low</div>
                <div className="text-xl font-mono font-bold text-slate-600 mt-1">
                  {summary.medium_count} / {summary.low_count}
                </div>
              </div>

              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                <div className="text-[10px] font-mono uppercase text-slate-400 font-bold flex items-center gap-1">
                  <TrendingDown className="w-3 h-3 text-rose-500" />
                  <span>Total Loss kWh</span>
                </div>
                <div className="text-xl font-mono font-bold text-slate-800 mt-1">
                  {summary.total_estimated_loss_kwh.toLocaleString()}
                </div>
              </div>

              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
                <div className="text-[10px] font-mono uppercase text-slate-400 font-bold flex items-center gap-1">
                  <DollarSign className="w-3 h-3 text-emerald-600" />
                  <span>Financial Loss (₹)</span>
                </div>
                <div className="text-xl font-mono font-bold text-emerald-700 mt-1">
                  ₹{summary.total_estimated_financial_loss_inr.toLocaleString()}
                </div>
              </div>
            </div>
          )}

          {/* Filter Bar */}
          <div className="bg-white p-4 rounded-xl border border-slate-200/80 shadow-xs space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {/* Plant Filter */}
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono uppercase text-slate-400 font-bold">Plant:</span>
                <select
                  id="filter-plant-select"
                  value={filterPlant}
                  onChange={(e) => setFilterPlant(e.target.value)}
                  className="bg-slate-50 border border-slate-200 text-xs font-semibold rounded-lg px-3 py-1.5 text-slate-700 focus:outline-hidden focus:ring-1 focus:ring-[#004874]"
                >
                  <option value="all">All Solar Plants</option>
                  {plants.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Search Query */}
              <div className="relative w-full sm:w-64">
                <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
                <input
                  id="filter-search-input"
                  type="text"
                  placeholder="Search asset, detector, note..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs font-medium text-slate-800 focus:outline-hidden focus:ring-1 focus:ring-[#004874]"
                />
              </div>
            </div>

            {/* Severity & Status Chips */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-100">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[10px] font-mono uppercase text-slate-400 font-bold mr-1">Severity:</span>
                {['all', 'critical', 'high', 'medium', 'low'].map((sev) => (
                  <button
                    key={sev}
                    id={`filter-severity-${sev}`}
                    onClick={() => setFilterSeverity(sev)}
                    className={`px-2.5 py-1 rounded text-xs font-semibold capitalize transition ${
                      filterSeverity === sev
                        ? 'bg-[#004874] text-white shadow-xs'
                        : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    {sev}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[10px] font-mono uppercase text-slate-400 font-bold mr-1">Status:</span>
                {['all', 'open', 'acknowledged', 'resolved', 'false_positive'].map((st) => (
                  <button
                    key={st}
                    id={`filter-status-${st}`}
                    onClick={() => setFilterStatus(st)}
                    className={`px-2.5 py-1 rounded text-xs font-semibold capitalize transition ${
                      filterStatus === st
                        ? 'bg-slate-800 text-white shadow-xs'
                        : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    {st.replace('_', ' ')}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Bulk Action Banner (Visible when items selected) */}
          {selectedIds.length > 0 && (
            <div className="bg-slate-900 text-white px-4 py-3 rounded-xl shadow-lg flex items-center justify-between animate-fadeIn">
              <div className="flex items-center gap-2 text-xs font-mono font-bold">
                <CheckSquare className="w-4 h-4 text-sky-400" />
                <span>{selectedIds.length} ANOMALIES SELECTED</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  id="btn-bulk-acknowledge"
                  onClick={() => {
                    setBulkTargetStatus('acknowledged');
                    setBulkModalOpen(true);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-white text-xs font-bold transition"
                >
                  Acknowledge Selected
                </button>
                <button
                  id="btn-bulk-resolve"
                  onClick={() => {
                    setBulkTargetStatus('resolved');
                    setBulkModalOpen(true);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold transition"
                >
                  Resolve Selected
                </button>
                <button
                  id="btn-bulk-fp"
                  onClick={() => {
                    setBulkTargetStatus('false_positive');
                    setBulkModalOpen(true);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-bold transition"
                >
                  Mark False Positive
                </button>
                <button
                  id="btn-bulk-cancel"
                  onClick={() => setSelectedIds([])}
                  className="px-2 py-1.5 text-xs text-slate-400 hover:text-white"
                >
                  Deselect
                </button>
              </div>
            </div>
          )}

          {/* Anomalies Table */}
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-[10px] font-mono uppercase text-slate-400 font-bold tracking-wider">
                    <th className="py-3 px-4 w-10 text-center">
                      <button onClick={handleToggleSelectAll} className="cursor-pointer">
                        {selectedIds.length > 0 && selectedIds.length === filteredAnomalies.length ? (
                          <CheckSquare className="w-4 h-4 text-[#004874]" />
                        ) : (
                          <Square className="w-4 h-4 text-slate-400" />
                        )}
                      </button>
                    </th>
                    <th className="py-3 px-4">Severity / Status</th>
                    <th className="py-3 px-4">Detected Timestamp</th>
                    <th className="py-3 px-4">Plant & Asset</th>
                    <th className="py-3 px-4">Detector Method</th>
                    <th className="py-3 px-4">Loss Deficit (kW / kWh)</th>
                    <th className="py-3 px-4">Revenue Risk (₹)</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {loading ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-400 font-mono">
                        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-[#004874]" />
                        Loading SCADA Anomaly Stream...
                      </td>
                    </tr>
                  ) : filteredAnomalies.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center">
                        <EmptyState
                          title="No Anomalies Found"
                          description="No detected telemetry anomalies matched the current filters."
                        />
                      </td>
                    </tr>
                  ) : (
                    filteredAnomalies.map((anom) => {
                      const isSelected = selectedIds.includes(anom.id);
                      const sevStyle = SEVERITY_COLORS[anom.severity];
                      const statStyle = STATUS_CONFIG[anom.status];
                      const details = anom.details || {};
                      const kwh = details.total_energy_loss_kwh || 0.0;
                      const inr = details.total_financial_loss_inr || 0.0;

                      return (
                        <tr
                          key={anom.id}
                          className={`hover:bg-slate-50/80 transition cursor-pointer ${
                            isSelected ? 'bg-sky-50/40' : ''
                          }`}
                          onClick={() => {
                            setSelectedAnomalyId(anom.id);
                            setActiveView('detail');
                          }}
                        >
                          <td
                            className="py-3 px-4 text-center"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleToggleSelectOne(anom.id);
                            }}
                          >
                            {isSelected ? (
                              <CheckSquare className="w-4 h-4 text-[#004874]" />
                            ) : (
                              <Square className="w-4 h-4 text-slate-300" />
                            )}
                          </td>

                          <td className="py-3 px-4 whitespace-nowrap">
                            <div className="flex items-center gap-1.5">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${sevStyle.bg} ${sevStyle.text} border ${sevStyle.border}`}>
                                {anom.severity}
                              </span>
                              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${statStyle.badge} border`}>
                                {statStyle.label}
                              </span>
                            </div>
                          </td>

                          <td className="py-3 px-4 whitespace-nowrap font-mono text-slate-600">
                            {new Date(anom.start_time).toLocaleString()}
                          </td>

                          <td className="py-3 px-4">
                            <div className="font-bold text-slate-800">{anom.asset_name || 'Inverter'}</div>
                            <div className="text-[10px] text-slate-400">{anom.plant_name || 'Solar Plant'}</div>
                          </td>

                          <td className="py-3 px-4 whitespace-nowrap font-mono text-slate-600">
                            <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 text-[10px] border border-slate-200">
                              {anom.detector_name || anom.source}
                            </span>
                          </td>

                          <td className="py-3 px-4 whitespace-nowrap font-mono">
                            <div className="text-slate-800 font-bold">
                              {anom.estimated_loss_kw ? `${anom.estimated_loss_kw} kW` : '—'}
                            </div>
                            <div className="text-[10px] text-slate-400">
                              {kwh ? `${kwh.toLocaleString()} kWh` : '0 kWh'}
                            </div>
                          </td>

                          <td className="py-3 px-4 whitespace-nowrap font-mono font-bold text-emerald-700">
                            {inr ? `₹${inr.toLocaleString()}` : '₹0'}
                          </td>

                          <td
                            className="py-3 px-4 text-right whitespace-nowrap"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div className="flex items-center justify-end gap-1.5">
                              {onAskCopilot && (
                                <button
                                  onClick={() => {
                                    onAskCopilot(
                                      `Investigate anomaly on ${anom.asset_name || 'inverter asset'}: ${
                                        anom.summary || 'detected outlier'
                                      } (${new Date(anom.start_time).toLocaleString()}). Severity: ${anom.severity.toUpperCase()}, Deficit: ${
                                        anom.estimated_loss_kw || 0
                                      } kW. Trace root causes and historical context.`,
                                      {
                                        route: 'anomalies',
                                        anomalyId: anom.id,
                                        anomalyTitle: anom.summary,
                                        assetId: anom.asset_id,
                                        assetName: anom.asset_name,
                                      }
                                    );
                                  }}
                                  className="text-xs text-sky-700 hover:text-sky-900 font-semibold flex items-center gap-1 px-2 py-1 rounded bg-sky-50 hover:bg-sky-100 border border-sky-200 transition"
                                  title="Investigate Anomaly with Solar Copilot"
                                >
                                  <Sparkles className="w-3 h-3 text-sky-600" />
                                  <span>Ask Copilot</span>
                                </button>
                              )}
                              <button
                                onClick={() => {
                                  setSelectedAnomalyId(anom.id);
                                  setActiveView('detail');
                                }}
                                className="text-xs text-[#004874] hover:text-[#002f4c] font-bold flex items-center gap-1"
                              >
                                <span>View Evidence</span>
                                <ChevronRight className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* VIEW: ALERT RULES & DISPATCH SETTINGS (S4-FS-03) */}
      {activeView === 'alerts' && (
        <div className="space-y-6 animate-fadeIn">
          {/* Rules Header & Create Button */}
          <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-slate-200 shadow-xs">
            <div>
              <h2 className="text-sm font-bold text-slate-800 tracking-tight flex items-center gap-2">
                <Bell className="w-4 h-4 text-[#004874]" />
                <span>CONFIGURABLE ALERT RULES & NOTIFICATION DESTINATIONS</span>
              </h2>
              <p className="text-xs text-slate-500 font-medium">
                Automatic trigger rules for anomaly severity and KPI breaches with SMTP and webhook delivery.
              </p>
            </div>
            <button
              id="btn-create-alert-rule"
              onClick={() => setCreateRuleModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#004874] hover:bg-[#00385c] text-white text-xs font-semibold shadow-xs transition"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Create Alert Rule</span>
            </button>
          </div>

          {/* Active Rules Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {alertRules.length === 0 ? (
              <div className="col-span-full">
                <EmptyState
                  title="No Alert Rules Configured"
                  description="Create an alert rule to receive automated emails or webhooks when critical anomalies occur."
                  action={
                    <button
                      onClick={() => setCreateRuleModalOpen(true)}
                      className="px-3 py-1.5 rounded-lg bg-[#004874] text-white text-xs font-semibold"
                    >
                      Add First Rule
                    </button>
                  }
                />
              </div>
            ) : (
              alertRules.map((rule) => (
                <div key={rule.id} className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-semibold">
                        {rule.plant_name || 'Plant'}
                      </span>
                      <h3 className="text-sm font-bold text-slate-800 mt-1">{rule.name}</h3>
                    </div>
                    <button
                      onClick={() => handleDeleteRule(rule.id)}
                      className="text-slate-400 hover:text-rose-600 p-1"
                      title="Delete rule"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="bg-slate-50 p-2.5 rounded-lg text-xs font-mono space-y-1">
                    <div className="text-slate-500">Metric: <strong className="text-slate-800">{rule.metric}</strong></div>
                    <div className="text-slate-500">Condition: <strong className="text-slate-800">{rule.direction} {rule.threshold}</strong></div>
                    <div className="text-slate-500">Severity Tier: <strong className="text-amber-700 uppercase">{rule.severity}</strong></div>
                  </div>

                  <div className="flex items-center justify-between text-xs pt-2 border-t border-slate-100">
                    <div className="flex items-center gap-1.5">
                      {rule.channels.map((ch) => (
                        <span key={ch} className="px-2 py-0.5 rounded text-[10px] font-mono bg-sky-50 text-sky-800 font-bold border border-sky-200">
                          {ch.toUpperCase()}
                        </span>
                      ))}
                    </div>
                    <button
                      onClick={() => openTestDispatchModal(rule)}
                      className="text-xs font-bold text-[#004874] hover:underline flex items-center gap-1"
                    >
                      <Send className="w-3 h-3" />
                      <span>Test Dispatch</span>
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Delivery Audit Log History */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
            <div className="p-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
              <h3 className="text-xs font-mono font-bold uppercase text-slate-700 tracking-wider">
                RECENT ALERT DISPATCH AUDIT LOG (DELIVERIES)
              </h3>
              <span className="text-xs text-slate-400 font-mono">{deliveries.length} entries</span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50/50 text-[10px] text-slate-400 uppercase">
                    <th className="py-2.5 px-4">Timestamp</th>
                    <th className="py-2.5 px-4">Channel</th>
                    <th className="py-2.5 px-4">Destination Recipient</th>
                    <th className="py-2.5 px-4">Status</th>
                    <th className="py-2.5 px-4">Details / Errors</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {deliveries.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-slate-400">
                        No alert notifications have been dispatched yet.
                      </td>
                    </tr>
                  ) : (
                    deliveries.map((d) => (
                      <tr key={d.id} className="hover:bg-slate-50">
                        <td className="py-2.5 px-4 text-slate-600">{new Date(d.created_at).toLocaleString()}</td>
                        <td className="py-2.5 px-4 font-bold text-slate-700 uppercase">{d.channel}</td>
                        <td className="py-2.5 px-4 text-slate-800">{d.recipient}</td>
                        <td className="py-2.5 px-4">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${
                            d.status?.toLowerCase() === 'delivered'
                              ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
                              : d.status?.toLowerCase() === 'accepted'
                              ? 'bg-sky-100 text-sky-800 border-sky-300'
                              : d.status?.toLowerCase() === 'simulated'
                              ? 'bg-purple-100 text-purple-800 border-purple-300'
                              : 'bg-rose-100 text-rose-800 border-rose-300'
                          }`}>
                            {d.status}
                          </span>
                        </td>
                        <td className="py-2.5 px-4 text-slate-600 max-w-sm truncate" title={d.error_message || d.payload?.title || 'OK'}>
                          {d.error_message || (d.payload?.message ? `${d.payload.message} (${d.payload.title || 'OK'})` : d.payload?.title || 'OK')}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: BULK TRIAGE DIALOG */}
      {bulkModalOpen && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4 border border-slate-200 animate-fadeIn">
            <h3 className="text-sm font-bold text-slate-800">
              Bulk Triage ({selectedIds.length} Anomalies)
            </h3>
            <p className="text-xs text-slate-500">
              Set target operational status for all selected anomalies. An audit log entry will be saved for each record.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-400 font-bold mb-1">
                  Target Status
                </label>
                <select
                  value={bulkTargetStatus}
                  onChange={(e) => setBulkTargetStatus(e.target.value as AnomalyStatus)}
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs font-semibold text-slate-800"
                >
                  <option value="acknowledged">Acknowledged (Under Investigation)</option>
                  <option value="resolved">Resolved (Fault Addressed)</option>
                  <option value="false_positive">False Positive (Benign Outlier)</option>
                  <option value="open">Open (Reopen)</option>
                </select>
              </div>

              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-400 font-bold mb-1">
                  Justification Note (Required for Compliance)
                </label>
                <textarea
                  rows={3}
                  value={bulkNote}
                  onChange={(e) => setBulkNote(e.target.value)}
                  placeholder="e.g. Field inspection dispatch confirmed; inverter breaker reset."
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs font-medium text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setBulkModalOpen(false)}
                disabled={actionLoading}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                onClick={executeBulkTriage}
                disabled={actionLoading}
                className="px-4 py-1.5 rounded-lg text-xs font-bold bg-[#004874] text-white hover:bg-[#00385c]"
              >
                {actionLoading ? 'Saving...' : 'Apply Status Transition'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: SINGLE TRIAGE DIALOG */}
      {singleTriageModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4 border border-slate-200 animate-fadeIn">
            <h3 className="text-sm font-bold text-slate-800">
              Update Anomaly Status → {targetTriageStatus.toUpperCase()}
            </h3>

            <div className="space-y-3">
              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-400 font-bold mb-1">
                  Status Transition Note
                </label>
                <textarea
                  rows={3}
                  value={triageNote}
                  onChange={(e) => setTriageNote(e.target.value)}
                  placeholder="Record RCA notes or field maintenance findings..."
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs font-medium text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setSingleTriageModal(false)}
                disabled={actionLoading}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                onClick={executeSingleTriage}
                disabled={actionLoading}
                className="px-4 py-1.5 rounded-lg text-xs font-bold bg-[#004874] text-white hover:bg-[#00385c]"
              >
                {actionLoading ? 'Saving...' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: CREATE ALERT RULE */}
      {createRuleModalOpen && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <form onSubmit={handleCreateRule} className="bg-white rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4 border border-slate-200 animate-fadeIn">
            <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
              <Bell className="w-4 h-4 text-[#004874]" />
              <span>Configure New Alert Rule</span>
            </h3>

            <div className="space-y-3">
              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-400 font-bold mb-1">Rule Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Critical Trip Alarm"
                  value={newRuleData.name}
                  onChange={(e) => setNewRuleData({ ...newRuleData, name: e.target.value })}
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs text-slate-800"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[10px] font-mono uppercase text-slate-400 font-bold mb-1">Plant</label>
                  <select
                    value={newRuleData.plant_id}
                    onChange={(e) => setNewRuleData({ ...newRuleData, plant_id: e.target.value })}
                    className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs text-slate-800"
                  >
                    {plants.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-[10px] font-mono uppercase text-slate-400 font-bold mb-1">Severity Trigger</label>
                  <select
                    value={newRuleData.severity}
                    onChange={(e) => setNewRuleData({ ...newRuleData, severity: e.target.value as any })}
                    className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs text-slate-800"
                  >
                    <option value="info">Info & Above</option>
                    <option value="warning">Warning & Above</option>
                    <option value="critical">Critical Only</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-400 font-bold mb-1">Email Recipients (Comma-separated)</label>
                <input
                  type="text"
                  placeholder="eng@plantiq.io, ops@plantiq.io"
                  value={newRuleData.recipients}
                  onChange={(e) => setNewRuleData({ ...newRuleData, recipients: e.target.value })}
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs text-slate-800"
                />
                <p className="text-[10px] text-slate-400 mt-1">
                  For sandbox testing without a custom domain, enter your verified Resend account email address.
                </p>
              </div>

              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-400 font-bold mb-1">Webhook URL (Optional)</label>
                <input
                  type="url"
                  placeholder="https://api.plantiq.io/webhook"
                  value={newRuleData.webhook_url}
                  onChange={(e) => setNewRuleData({ ...newRuleData, webhook_url: e.target.value })}
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setCreateRuleModalOpen(false)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={actionLoading}
                className="px-4 py-1.5 rounded-lg text-xs font-bold bg-[#004874] text-white hover:bg-[#00385c]"
              >
                Save Rule
              </button>
            </div>
          </form>
        </div>
      )}

      {/* MODAL: TEST ALERT DISPATCH */}
      {testModalRule && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full p-5 space-y-4 border border-slate-200 animate-fadeIn">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-sky-50 text-[#004874] flex items-center justify-center">
                  <Send className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-800">
                    Test Alert Notification Dispatch
                  </h3>
                  <p className="text-[11px] text-slate-500">
                    Rule: <span className="font-semibold text-slate-700">{testModalRule.name}</span> ({testModalRule.channels.join(', ').toUpperCase()})
                  </p>
                </div>
              </div>
              <button
                onClick={() => setTestModalRule(null)}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <XCircle className="w-5 h-5" />
              </button>
            </div>

            {/* Safe Diagnostics Indicator */}
            {emailDiagnostics && (
              <div
                className={`p-2.5 rounded-lg border text-xs flex items-center justify-between ${
                  emailDiagnostics.is_configured
                    ? 'bg-emerald-50/90 border-emerald-200 text-emerald-900'
                    : 'bg-amber-50/90 border-amber-200 text-amber-900'
                }`}
              >
                <div className="flex items-center gap-2">
                  <div
                    className={`w-2 h-2 rounded-full ${
                      emailDiagnostics.is_configured ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'
                    }`}
                  />
                  <span className="font-semibold text-[11px]">
                    {emailDiagnostics.is_configured
                      ? 'EMAIL_PROVIDER_API_KEY Configured'
                      : 'EMAIL_PROVIDER_API_KEY Missing in backend/.env'}
                  </span>
                </div>
                <span className="font-mono text-[10px] text-slate-500">
                  {emailDiagnostics.is_configured
                    ? `Provider: ${emailDiagnostics.provider.toUpperCase()}`
                    : 'Save file & restart backend'}
                </span>
              </div>
            )}

            {/* Provider testing restriction notice */}
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900 space-y-1">
              <div className="font-bold flex items-center gap-1.5 text-amber-950">
                <Info className="w-4 h-4 text-amber-700 shrink-0" />
                <span>Transactional Email Testing Notice</span>
              </div>
              <p className="text-[11px] leading-relaxed text-amber-800">
                Testing uses the default verified sandbox sender (<code className="font-mono bg-amber-100/70 px-1 rounded text-amber-900">onboarding@resend.dev</code>).
                Provider restriction: Emails can <strong>only</strong> be delivered to the verified email address associated with your Resend account.
                Custom domains can be added later in Resend for unrestricted recipient delivery.
              </p>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-500 font-bold mb-1">
                  Recipient Destination
                </label>
                <input
                  type="text"
                  required
                  value={testRecipientOverride}
                  onChange={(e) => setTestRecipientOverride(e.target.value)}
                  placeholder="Enter the email address you control (e.g. your Resend account email)"
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#004874]"
                />
              </div>

              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-500 font-bold mb-1">
                  Test Message
                </label>
                <input
                  type="text"
                  value={testMessageInput}
                  onChange={(e) => setTestMessageInput(e.target.value)}
                  placeholder="Manual verification test ping from UI"
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#004874]"
                />
              </div>
            </div>

            {/* Outcome Feedback Banner */}
            {testDispatchResult && (
              <div
                className={`p-3 rounded-lg border text-xs space-y-1.5 animate-fadeIn ${
                  testDispatchResult.status === 'accepted'
                    ? 'bg-sky-50 border-sky-200 text-sky-950'
                    : testDispatchResult.status === 'delivered'
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-950'
                    : testDispatchResult.status === 'simulated'
                    ? 'bg-purple-50 border-purple-200 text-purple-950'
                    : 'bg-rose-50 border-rose-200 text-rose-950'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 font-bold">
                    {testDispatchResult.status === 'accepted' || testDispatchResult.status === 'delivered' ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                    ) : testDispatchResult.status === 'simulated' ? (
                      <Info className="w-4 h-4 text-purple-600 shrink-0" />
                    ) : (
                      <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
                    )}
                    <span>
                      {testDispatchResult.status === 'accepted'
                        ? 'Provider Accepted Request'
                        : testDispatchResult.status === 'delivered'
                        ? 'Delivery Confirmed'
                        : testDispatchResult.status === 'simulated'
                        ? 'Simulated Offline Dispatch'
                        : 'Dispatch Failed'}
                    </span>
                  </div>
                  <span
                    className={`text-[10px] font-mono font-bold uppercase px-2 py-0.5 rounded border ${
                      testDispatchResult.status === 'accepted'
                        ? 'bg-sky-100 text-sky-800 border-sky-300'
                        : testDispatchResult.status === 'delivered'
                        ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
                        : testDispatchResult.status === 'simulated'
                        ? 'bg-purple-100 text-purple-800 border-purple-300'
                        : 'bg-rose-100 text-rose-800 border-rose-300'
                    }`}
                  >
                    {testDispatchResult.status}
                  </span>
                </div>
                <p className="text-[11px] leading-relaxed break-words font-mono bg-white/60 p-2 rounded border border-black/5">
                  {testDispatchResult.message}
                </p>
                {testDispatchResult.status === 'accepted' && (
                  <p className="text-[10px] text-sky-700 italic">
                    The email has been queued and accepted by Resend. Check your inbox (and spam/junk folder) at {testDispatchResult.recipient}.
                  </p>
                )}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setTestModalRule(null)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100"
              >
                Close
              </button>
              <button
                type="button"
                onClick={handleExecuteTestDispatch}
                disabled={testDispatchLoading || !testRecipientOverride}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-[#004874] text-white hover:bg-[#00385c] disabled:opacity-50 shadow-xs"
              >
                {testDispatchLoading ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Dispatching...</span>
                  </>
                ) : (
                  <>
                    <Send className="w-3.5 h-3.5" />
                    <span>Send Test Notification</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AnomaliesPage;
