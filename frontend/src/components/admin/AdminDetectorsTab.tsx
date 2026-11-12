import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  Check,
  CheckCircle2,
  Code,
  Edit2,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Sliders,
  ToggleLeft,
  ToggleRight,
  Trash2,
  X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import {
  createDetector,
  deleteDetector,
  getDetectors,
  runDetector,
  updateDetector,
} from '../../api/detectors';
import { getCanonicalSignals } from '../../api/canonicalSignals';
import { CanonicalSignal, Detector, Plant } from '../../types';

interface AdminDetectorsTabProps {
  plants: Plant[];
  selectedPlant: Plant | null;
}

export const AdminDetectorsTab: React.FC<AdminDetectorsTabProps> = ({
  plants,
  selectedPlant,
}) => {
  const { user } = useAuth();
  const userRole = user?.role?.toLowerCase() || 'viewer';
  const canManageDetectors = userRole === 'admin' || userRole === 'super_admin';
  const canRunScan = userRole === 'admin' || userRole === 'super_admin' || userRole === 'engineer';

  const [detectors, setDetectors] = useState<Detector[]>([]);
  const [canonicalSignals, setCanonicalSignals] = useState<CanonicalSignal[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters
  const [plantFilter, setPlantFilter] = useState<string>(selectedPlant?.id || '');
  const [methodFilter, setMethodFilter] = useState<string>('');
  const [search, setSearch] = useState<string>('');

  // Modals state
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState<boolean>(false);
  const [selectedDetector, setSelectedDetector] = useState<Detector | null>(null);
  const [runningDetectorId, setRunningDetectorId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Form states for Add Detector
  const [addName, setAddName] = useState<string>('');
  const [addPlantId, setAddPlantId] = useState<string>(selectedPlant?.id || plants[0]?.id || '');
  const [addMethod, setAddMethod] = useState<string>('zscore');
  const [addCanonicalKey, setAddCanonicalKey] = useState<string>('power_ac');
  const [addConditionText, setAddConditionText] = useState<string>('zscore > 3.0');
  const [addScopeJson, setAddScopeJson] = useState<string>('{"asset_type": "inverter"}');
  const [addParamsJson, setAddParamsJson] = useState<string>('{"threshold": 3.0, "window_hours": 24}');
  const [addEnabled, setAddEnabled] = useState<boolean>(true);

  // Detection Method presets and auto-templates
  const methodPresets: Record<string, { condition: string; params: string; placeholder: string; explanation: string }> = {
    zscore: {
      condition: 'zscore > 3.0',
      params: '{"threshold": 3.0, "window_hours": 24}',
      placeholder: 'e.g. Midday Inverter Trip Outlier',
      explanation: 'Z-Score compares inverters against peer median under identical sun (> 3.0 = 99.7% confidence fault).',
    },
    iqr: {
      condition: 'iqr_multiplier > 1.5',
      params: '{"k": 1.5, "window_hours": 24}',
      placeholder: 'e.g. IQR Quartile Boundary Outlier',
      explanation: 'Interquartile Range box-plot filter (k = 1.5 standard outlier, 2.0 extreme outlier).',
    },
    deviation: {
      condition: 'pr_deviation > 0.20',
      params: '{"threshold_pct": 0.20, "window_hours": 24}',
      placeholder: 'e.g. 20% Performance Ratio Drop',
      explanation: 'Flags when generation drops below expected baseline by chosen percentage (0.20 = 20% drop).',
    },
    irradiance_residual: {
      condition: 'residual > 50.0',
      params: '{"residual_kw": 50.0, "window_hours": 24}',
      placeholder: 'e.g. Irradiance Pyranometer Mismatch',
      explanation: 'Compares actual power output against weather pyranometer solar irradiance model.',
    },
    isolation_forest: {
      condition: 'anomaly_score > 0.65',
      params: '{"contamination": 0.05, "n_estimators": 100, "window_hours": 24}',
      placeholder: 'e.g. Multivariate ML Isolation Forest',
      explanation: 'Machine learning tree-ensemble outlier detection (score from 0.0 normal to 1.0 anomalous).',
    },
  };

  const handleMethodChange = (newMethod: string) => {
    setAddMethod(newMethod);
    const preset = methodPresets[newMethod];
    if (preset) {
      setAddConditionText(preset.condition);
      setAddParamsJson(preset.params);
    }
  };


  // Form states for Edit Params
  const [editParamsJson, setEditParamsJson] = useState<string>('{}');
  const [editScopeJson, setEditScopeJson] = useState<string>('{}');
  const [editConditionText, setEditConditionText] = useState<string>('');

  const fetchDetectors = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getDetectors(plantFilter || undefined);
      setDetectors(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load detectors');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchDetectors();
  }, [plantFilter]);

  useEffect(() => {
    getCanonicalSignals()
      .then((sigs) => setCanonicalSignals(sigs))
      .catch(() => {});
  }, []);

  // Inline toggle enabled status
  const handleToggleEnabled = async (d: Detector) => {
    if (!canManageDetectors) return;
    try {
      const updated = await updateDetector(d.id, { enabled: !d.enabled });
      setDetectors((prev) => prev.map((item) => (item.id === d.id ? updated : item)));
      setSuccessMsg(`Detector "${d.name}" ${updated.enabled ? 'enabled' : 'disabled'}`);
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update detector status');
    }
  };

  // Run on-demand detector scan
  const handleRunScan = async (d: Detector) => {
    setRunningDetectorId(d.id);
    setError(null);
    try {
      const res = await runDetector(d.id, { window_hours: 24, dry_run: false });
      const foundCount = res?.anomalies_detected ?? res?.candidates_found ?? 0;
      setSuccessMsg(`Scan finished for "${d.name}": ${foundCount} anomalies flagged.`);
      setTimeout(() => setSuccessMsg(null), 5000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || `Scan failed for ${d.name}`);
    } finally {
      setRunningDetectorId(null);
    }
  };

  const handleOpenAdd = () => {
    setAddName('');
    setAddPlantId(plantFilter || selectedPlant?.id || plants[0]?.id || '');
    setAddMethod('zscore');
    setAddCanonicalKey('power_ac');
    setAddConditionText('zscore > 3.0');
    setAddScopeJson('{"asset_type": "inverter"}');
    setAddParamsJson('{"threshold": 3.0, "window_hours": 24}');
    setAddEnabled(true);
    setError(null);
    setIsAddModalOpen(true);
  };

  const handleCreateDetector = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addName.trim()) {
      setError('Detector name is required');
      return;
    }

    let parsedScope = {};
    let parsedParams = {};
    try {
      parsedScope = JSON.parse(addScopeJson);
      parsedParams = JSON.parse(addParamsJson);
    } catch (parseErr) {
      setError('Invalid JSON format in scope or parameters');
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await createDetector({
        plant_id: addPlantId,
        name: addName.trim(),
        method: addMethod,
        canonical_key: addCanonicalKey,
        condition_text: addConditionText.trim(),
        asset_scope: parsedScope,
        parameters: parsedParams,
        enabled: addEnabled,
      });
      setSuccessMsg(`Detector "${addName}" registered successfully`);
      setIsAddModalOpen(false);
      fetchDetectors();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create detector');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenEdit = (d: Detector) => {
    setSelectedDetector(d);
    setEditParamsJson(JSON.stringify(d.parameters || {}, null, 2));
    setEditScopeJson(JSON.stringify(d.asset_scope || {}, null, 2));
    setEditConditionText(d.condition_text || '');
    setError(null);
    setIsEditModalOpen(true);
  };

  const handleUpdateDetector = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDetector) return;

    let parsedParams = {};
    let parsedScope = {};
    try {
      parsedParams = JSON.parse(editParamsJson);
      parsedScope = JSON.parse(editScopeJson);
    } catch (parseErr) {
      setError('Invalid JSON syntax');
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await updateDetector(selectedDetector.id, {
        parameters: parsedParams,
        asset_scope: parsedScope,
        condition_text: editConditionText.trim(),
      });
      setSuccessMsg(`Detector "${selectedDetector.name}" updated successfully`);
      setIsEditModalOpen(false);
      fetchDetectors();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update detector');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenDelete = (d: Detector) => {
    setSelectedDetector(d);
    setError(null);
    setIsDeleteModalOpen(true);
  };

  const handleDeleteDetector = async () => {
    if (!selectedDetector) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await deleteDetector(selectedDetector.id);
      setSuccessMsg(`Detector "${selectedDetector.name}" deleted successfully`);
      setIsDeleteModalOpen(false);
      fetchDetectors();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to delete detector');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Filtered detectors
  const filteredDetectors = detectors.filter((d) => {
    const matchesMethod = !methodFilter || d.method === methodFilter;
    const matchesSearch =
      !search ||
      d.name.toLowerCase().includes(search.toLowerCase()) ||
      d.canonical_key.toLowerCase().includes(search.toLowerCase());
    return matchesMethod && matchesSearch;
  });

  return (
    <div className="space-y-4">
      {/* Toast Feedback */}
      {successMsg && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs rounded-lg flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Check className="w-4 h-4 text-emerald-600" />
            <span className="font-semibold">{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-500 hover:text-emerald-700">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="p-3 bg-rose-50 border border-rose-200 text-rose-800 text-xs rounded-lg flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-500 hover:text-rose-700">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Control Bar */}
      <div className="bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-xs flex flex-col md:flex-row items-center justify-between gap-3">
        <div className="relative flex-1 w-full">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400" />
          <input
            type="text"
            placeholder="Search by detector name or signal..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#004874] text-slate-800"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          {/* Plant filter */}
          <select
            value={plantFilter}
            onChange={(e) => setPlantFilter(e.target.value)}
            className="px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#004874]"
          >
            <option value="">All Plants</option>
            {plants.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>

          {/* Method filter */}
          <select
            value={methodFilter}
            onChange={(e) => setMethodFilter(e.target.value)}
            className="px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#004874]"
          >
            <option value="">All Methods</option>
            <option value="zscore">D1 - Statistical Outlier (zscore)</option>
            <option value="iqr">D1 - IQR Spread</option>
            <option value="deviation">D2 - PR Deviation</option>
            <option value="irradiance_residual">D3 - Irradiance Residual</option>
            <option value="isolation_forest">D4 - Isolation Forest</option>
          </select>

          <button
            onClick={() => {
              setSearch('');
              setMethodFilter('');
              fetchDetectors();
            }}
            title="Refresh detector registry"
            className="p-1.5 text-slate-600 hover:text-slate-900 border border-slate-200 rounded-lg hover:bg-slate-50 transition"
          >
            <RefreshCw className="w-4 h-4" />
          </button>

          {!canManageDetectors && (
            <div className="px-2.5 py-1 text-[11px] font-mono font-semibold bg-amber-50 text-amber-800 border border-amber-200 rounded-lg flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-amber-600" />
              <span>Read-Only Calibration Mode</span>
            </div>
          )}

          {canManageDetectors && (
            <button
              onClick={handleOpenAdd}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[#004874] hover:bg-sky-800 text-white text-xs font-semibold rounded-lg transition shadow-xs"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New Detector</span>
            </button>
          )}
        </div>
      </div>

      {/* Detectors Table */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono uppercase text-slate-500">
                <th className="py-2.5 px-4 font-semibold">Detector Name / Formula</th>
                <th className="py-2.5 px-4 font-semibold">Method</th>
                <th className="py-2.5 px-4 font-semibold">Canonical Signal</th>
                <th className="py-2.5 px-4 font-semibold">Scope & Parameters</th>
                <th className="py-2.5 px-4 font-semibold text-center">Status</th>
                <th className="py-2.5 px-4 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-500 font-mono">
                    <div className="flex items-center justify-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-[#004874]" />
                      <span>Loading registered detectors...</span>
                    </div>
                  </td>
                </tr>
              ) : filteredDetectors.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                    No detectors configured for selected filter.
                  </td>
                </tr>
              ) : (
                filteredDetectors.map((d) => {
                  const isRunning = runningDetectorId === d.id;
                  const methodColor =
                    d.method === 'zscore' || d.method === 'iqr'
                      ? 'bg-sky-100 text-sky-800 border-sky-200'
                      : d.method === 'deviation'
                      ? 'bg-amber-100 text-amber-800 border-amber-200'
                      : d.method === 'irradiance_residual'
                      ? 'bg-indigo-100 text-indigo-800 border-indigo-200'
                      : 'bg-emerald-100 text-emerald-800 border-emerald-200';

                  return (
                    <tr key={d.id} className="hover:bg-slate-50/60 transition">
                      <td className="py-2.5 px-4">
                        <div className="font-semibold text-slate-800">{d.name}</div>
                        <div className="text-[10px] font-mono text-slate-500 truncate max-w-xs">
                          {d.condition_text || 'Default condition'}
                        </div>
                      </td>
                      <td className="py-2.5 px-4">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border ${methodColor}`}>
                          {d.method}
                        </span>
                      </td>
                      <td className="py-2.5 px-4">
                        <span className="font-mono text-slate-700 bg-slate-100 px-1.5 py-0.5 rounded text-[11px]">
                          {d.canonical_key}
                        </span>
                      </td>
                      <td className="py-2.5 px-4">
                        <div className="text-[11px] text-slate-600 font-mono">
                          {d.asset_scope ? JSON.stringify(d.asset_scope) : 'All assets'}
                        </div>
                        <div className="text-[10px] text-slate-400 font-mono truncate max-w-[180px]">
                          {JSON.stringify(d.parameters)}
                        </div>
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <button
                          onClick={() => handleToggleEnabled(d)}
                          disabled={!canManageDetectors}
                          title={!canManageDetectors ? 'Calibration toggle restricted to Organization Admin' : d.enabled ? 'Click to disable' : 'Click to enable'}
                          className={`inline-flex items-center gap-1 focus:outline-none transition ${!canManageDetectors ? 'cursor-default opacity-80' : 'cursor-pointer'}`}
                        >
                          {d.enabled ? (
                            <span className="inline-flex items-center gap-1 text-emerald-700 font-semibold text-[11px] bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                              <CheckCircle2 className="w-3 h-3" />
                              <span>Enabled</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-slate-500 font-medium text-[11px] bg-slate-100 px-2 py-0.5 rounded-full border border-slate-200">
                              <span>Disabled</span>
                            </span>
                          )}
                        </button>
                      </td>
                      <td className="py-2.5 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {canRunScan && (
                            <button
                              onClick={() => handleRunScan(d)}
                              disabled={isRunning}
                              title="Run On-Demand Scan Now"
                              className="p-1 text-emerald-700 hover:bg-emerald-50 rounded transition disabled:opacity-40"
                            >
                              {isRunning ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-600" />
                              ) : (
                                <Play className="w-3.5 h-3.5" />
                              )}
                            </button>
                          )}
                          {canManageDetectors && (
                            <>
                              <button
                                onClick={() => handleOpenEdit(d)}
                                title="Edit Parameters"
                                className="p-1 text-slate-500 hover:text-sky-700 hover:bg-sky-50 rounded transition"
                              >
                                <Sliders className="w-3.5 h-3.5" />
                              </button>
                              <button
                                onClick={() => handleOpenDelete(d)}
                                title="Delete Detector"
                                className="p-1 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded transition"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </>
                          )}
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

      {/* MODAL: ADD DETECTOR */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-lg overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-[#004874]" />
                <h3 className="font-bold text-sm text-slate-800">Configure Anomaly Detector</h3>
              </div>
              <button
                onClick={() => setIsAddModalOpen(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateDetector} className="p-5 space-y-3.5 text-xs max-h-[80vh] overflow-y-auto">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Target Plant *</label>
                  <select
                    value={addPlantId}
                    onChange={(e) => setAddPlantId(e.target.value)}
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  >
                    {plants.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Detection Method *</label>
                  <select
                    value={addMethod}
                    onChange={(e) => handleMethodChange(e.target.value)}
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  >
                    <option value="zscore">D1 - Statistical Outlier (zscore)</option>
                    <option value="iqr">D1 - IQR Boundary Outlier</option>
                    <option value="deviation">D2 - PR Deviation (Peer Median)</option>
                    <option value="irradiance_residual">D3 - Irradiance Residual Regression</option>
                    <option value="isolation_forest">D4 - Multivariate Isolation Forest</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Detector Name *</label>
                <input
                  type="text"
                  required
                  placeholder={methodPresets[addMethod]?.placeholder || "e.g. Midday Inverter Trip Outlier"}
                  value={addName}
                  onChange={(e) => setAddName(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Canonical Signal *</label>
                  <select
                    value={addCanonicalKey}
                    onChange={(e) => setAddCanonicalKey(e.target.value)}
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  >
                    {canonicalSignals.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.name} ({s.key})
                      </option>
                    ))}
                    {canonicalSignals.length === 0 && (
                      <option value="power_ac">power_ac</option>
                    )}
                  </select>
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Condition Expression</label>
                  <input
                    type="text"
                    value={addConditionText}
                    onChange={(e) => setAddConditionText(e.target.value)}
                    placeholder="e.g. zscore > 3.0"
                    className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  />
                  {methodPresets[addMethod] && (
                    <p className="text-[10px] text-sky-800 bg-sky-50/80 border border-sky-200/60 rounded px-2 py-1 mt-1 font-mono">
                      {methodPresets[addMethod].explanation}
                    </p>
                  )}
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1 flex items-center justify-between">
                  <span>Asset Scope JSON</span>
                  <span className="text-[10px] text-slate-400 font-mono">e.g. {`{"asset_type": "inverter"}`}</span>
                </label>
                <textarea
                  rows={2}
                  value={addScopeJson}
                  onChange={(e) => setAddScopeJson(e.target.value)}
                  className="w-full px-3 py-1.5 font-mono text-[11px] border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1 flex items-center justify-between">
                  <span>Parameters JSON (thresholds, window)</span>
                  <span className="text-[10px] text-slate-400 font-mono">e.g. {`{"threshold": 3.0, "window_hours": 24}`}</span>
                </label>
                <textarea
                  rows={3}
                  value={addParamsJson}
                  onChange={(e) => setAddParamsJson(e.target.value)}
                  className="w-full px-3 py-1.5 font-mono text-[11px] border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="detActiveToggle"
                  checked={addEnabled}
                  onChange={(e) => setAddEnabled(e.target.checked)}
                  className="rounded text-[#004874] focus:ring-0"
                />
                <label htmlFor="detActiveToggle" className="text-slate-700 font-medium">
                  Enable detector immediately upon creation
                </label>
              </div>

              <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-1.5 bg-[#004874] hover:bg-sky-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition"
                >
                  {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Save Detector</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: EDIT PARAMETERS JSON */}
      {isEditModalOpen && selectedDetector && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div>
                <h3 className="font-bold text-sm text-slate-800">Edit Detector Parameters</h3>
                <p className="text-[11px] font-mono text-slate-500">{selectedDetector.name}</p>
              </div>
              <button
                onClick={() => setIsEditModalOpen(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleUpdateDetector} className="p-5 space-y-3.5 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Condition Expression</label>
                <input
                  type="text"
                  value={editConditionText}
                  onChange={(e) => setEditConditionText(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Asset Scope JSON</label>
                <textarea
                  rows={3}
                  value={editScopeJson}
                  onChange={(e) => setEditScopeJson(e.target.value)}
                  className="w-full px-3 py-1.5 font-mono text-[11px] border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Parameters JSON</label>
                <textarea
                  rows={4}
                  value={editParamsJson}
                  onChange={(e) => setEditParamsJson(e.target.value)}
                  className="w-full px-3 py-1.5 font-mono text-[11px] border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-1.5 bg-[#004874] hover:bg-sky-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition"
                >
                  {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Save Configuration</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: DELETE CONFIRMATION */}
      {isDeleteModalOpen && selectedDetector && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-sm overflow-hidden animate-in fade-in zoom-in-95 duration-150 p-5 space-y-4">
            <div className="w-10 h-10 rounded-full bg-rose-100 text-rose-600 flex items-center justify-center mx-auto">
              <Trash2 className="w-5 h-5" />
            </div>
            <div className="text-center space-y-1">
              <h3 className="font-bold text-sm text-slate-800">Delete Detector</h3>
              <p className="text-xs text-slate-600">
                Are you sure you want to delete detector{' '}
                <span className="font-semibold text-slate-900">{selectedDetector.name}</span>?
              </p>
              <p className="text-[11px] text-rose-600 font-medium">Historical anomaly records will remain preserved.</p>
            </div>
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setIsDeleteModalOpen(false)}
                className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 text-xs transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteDetector}
                disabled={isSubmitting}
                className="px-4 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-semibold rounded-lg text-xs shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition"
              >
                {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                <span>Confirm Delete</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

