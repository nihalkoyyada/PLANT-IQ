import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  Bell,
  BellRing,
  Check,
  CheckCircle2,
  Edit2,
  ExternalLink,
  Loader2,
  Mail,
  Plus,
  RefreshCw,
  Search,
  Send,
  ToggleLeft,
  ToggleRight,
  Trash2,
  X,
} from 'lucide-react';
import {
  createAlertRule,
  deleteAlertRule,
  getAlertRules,
  testAlertRule,
  updateAlertRule,
} from '../../api/alertRules';
import { AlertRule, Plant } from '../../types';

interface AdminAlertRulesTabProps {
  plants: Plant[];
  selectedPlant: Plant | null;
}

export const AdminAlertRulesTab: React.FC<AdminAlertRulesTabProps> = ({
  plants,
  selectedPlant,
}) => {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters
  const [plantFilter, setPlantFilter] = useState<string>(selectedPlant?.id || '');
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [search, setSearch] = useState<string>('');

  // Modals state
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [isTestModalOpen, setIsTestModalOpen] = useState<boolean>(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState<boolean>(false);
  const [selectedRule, setSelectedRule] = useState<AlertRule | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Form states for Add Rule
  const [addName, setAddName] = useState<string>('');
  const [addPlantId, setAddPlantId] = useState<string>(selectedPlant?.id || plants[0]?.id || '');
  const [addMetric, setAddMetric] = useState<string>('power_ac');
  const [addDirection, setAddDirection] = useState<'above' | 'below'>('below');
  const [addThreshold, setAddThreshold] = useState<number>(1000);
  const [addSeverity, setAddSeverity] = useState<'info' | 'warning' | 'critical'>('warning');
  const [addEmailChannel, setAddEmailChannel] = useState<boolean>(true);
  const [addWebhookChannel, setAddWebhookChannel] = useState<boolean>(false);
  const [addRecipients, setAddRecipients] = useState<string>('ops@plantiq.io');
  const [addWebhookUrl, setAddWebhookUrl] = useState<string>('');
  const [addEnabled, setAddEnabled] = useState<boolean>(true);

  // Test dispatch modal state
  const [testRecipient, setTestRecipient] = useState<string>('');
  const [testMessage, setTestMessage] = useState<string>('Simulated SCADA emergency alert dispatch');
  const [testResult, setTestResult] = useState<any>(null);

  const fetchRules = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getAlertRules(plantFilter || undefined);
      setRules(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load alert rules');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRules();
  }, [plantFilter]);

  const handleToggleEnabled = async (rule: AlertRule) => {
    try {
      const updated = await updateAlertRule(rule.id, { enabled: !rule.enabled });
      setRules((prev) => prev.map((item) => (item.id === rule.id ? updated : item)));
      setSuccessMsg(`Alert rule "${rule.name}" ${updated.enabled ? 'activated' : 'paused'}`);
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update rule status');
    }
  };

  const handleOpenAdd = () => {
    setAddName('');
    setAddPlantId(plantFilter || selectedPlant?.id || plants[0]?.id || '');
    setAddMetric('power_ac');
    setAddDirection('below');
    setAddThreshold(1000);
    setAddSeverity('warning');
    setAddEmailChannel(true);
    setAddWebhookChannel(false);
    setAddRecipients('ops@plantiq.io');
    setAddWebhookUrl('');
    setAddEnabled(true);
    setError(null);
    setIsAddModalOpen(true);
  };

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addName.trim()) {
      setError('Rule name is required');
      return;
    }

    const channels: ('email' | 'webhook')[] = [];
    if (addEmailChannel) channels.push('email');
    if (addWebhookChannel) channels.push('webhook');

    if (channels.length === 0) {
      setError('Please select at least one notification channel (Email or Webhook)');
      return;
    }

    const config: Record<string, any> = {};
    if (addEmailChannel && addRecipients.trim()) {
      config.recipients = addRecipients.split(',').map((s) => s.trim()).filter(Boolean);
    }
    if (addWebhookChannel && addWebhookUrl.trim()) {
      config.webhook_url = addWebhookUrl.trim();
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await createAlertRule({
        plant_id: addPlantId,
        name: addName.trim(),
        metric: addMetric.trim(),
        threshold: Number(addThreshold),
        direction: addDirection,
        severity: addSeverity,
        channels,
        enabled: addEnabled,
        config,
      });
      setSuccessMsg(`Alert rule "${addName}" created successfully`);
      setIsAddModalOpen(false);
      fetchRules();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create alert rule');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenTest = (rule: AlertRule) => {
    setSelectedRule(rule);
    const defaultRecip = rule.config?.recipients?.[0] || 'ops@plantiq.io';
    setTestRecipient(defaultRecip);
    setTestMessage(`Test notification dispatch for alert rule "${rule.name}"`);
    setTestResult(null);
    setError(null);
    setIsTestModalOpen(true);
  };

  const handleExecuteTest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRule) return;
    setIsSubmitting(true);
    setError(null);
    setTestResult(null);
    try {
      const res = await testAlertRule(selectedRule.id, {
        recipient_override: testRecipient.trim() || undefined,
        test_message: testMessage.trim() || undefined,
      });
      setTestResult(res);
      setSuccessMsg(`Test alert dispatched via ${res.channel} (${res.status})`);
      setTimeout(() => setSuccessMsg(null), 5000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Test dispatch failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenDelete = (rule: AlertRule) => {
    setSelectedRule(rule);
    setError(null);
    setIsDeleteModalOpen(true);
  };

  const handleDeleteRule = async () => {
    if (!selectedRule) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await deleteAlertRule(selectedRule.id);
      setSuccessMsg(`Alert rule "${selectedRule.name}" deleted successfully`);
      setIsDeleteModalOpen(false);
      fetchRules();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to delete alert rule');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Filtered rules
  const filteredRules = rules.filter((r) => {
    const matchesSeverity = !severityFilter || r.severity === severityFilter;
    const matchesSearch =
      !search ||
      r.name.toLowerCase().includes(search.toLowerCase()) ||
      r.metric.toLowerCase().includes(search.toLowerCase());
    return matchesSeverity && matchesSearch;
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
            placeholder="Search by rule name or metric..."
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

          {/* Severity filter */}
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#004874]"
          >
            <option value="">All Severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>

          <button
            onClick={() => {
              setSearch('');
              setSeverityFilter('');
              fetchRules();
            }}
            title="Refresh alert rules"
            className="p-1.5 text-slate-600 hover:text-slate-900 border border-slate-200 rounded-lg hover:bg-slate-50 transition"
          >
            <RefreshCw className="w-4 h-4" />
          </button>

          <button
            onClick={handleOpenAdd}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[#004874] hover:bg-sky-800 text-white text-xs font-semibold rounded-lg transition shadow-xs"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Alert Rule</span>
          </button>
        </div>
      </div>

      {/* Rules Table */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono uppercase text-slate-500">
                <th className="py-2.5 px-4 font-semibold">Rule Name / Plant</th>
                <th className="py-2.5 px-4 font-semibold">Trigger Condition</th>
                <th className="py-2.5 px-4 font-semibold">Severity</th>
                <th className="py-2.5 px-4 font-semibold">Dispatch Channels</th>
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
                      <span>Loading operational alert rules...</span>
                    </div>
                  </td>
                </tr>
              ) : filteredRules.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                    No alert rules configured.
                  </td>
                </tr>
              ) : (
                filteredRules.map((r) => {
                  const severityBadge =
                    r.severity === 'critical'
                      ? 'bg-rose-100 text-rose-800 border-rose-200'
                      : r.severity === 'warning'
                      ? 'bg-amber-100 text-amber-800 border-amber-200'
                      : 'bg-sky-100 text-sky-800 border-sky-200';

                  return (
                    <tr key={r.id} className="hover:bg-slate-50/60 transition">
                      <td className="py-2.5 px-4">
                        <div className="font-semibold text-slate-800">{r.name}</div>
                        <div className="text-[10px] font-mono text-slate-400">
                          {r.plant_name || 'Plant Scoped'}
                        </div>
                      </td>
                      <td className="py-2.5 px-4 font-mono text-slate-700">
                        <span className="font-semibold">{r.metric}</span>{' '}
                        <span className="text-slate-500">{r.direction}</span>{' '}
                        <span className="text-slate-900 font-bold">{r.threshold}</span>
                      </td>
                      <td className="py-2.5 px-4">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border ${severityBadge}`}>
                          {r.severity}
                        </span>
                      </td>
                      <td className="py-2.5 px-4">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {r.channels?.map((ch) => (
                            <span
                              key={ch}
                              className="inline-flex items-center gap-1 text-[10px] font-mono font-semibold bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded"
                            >
                              {ch === 'email' ? <Mail className="w-3 h-3 text-sky-600" /> : <ExternalLink className="w-3 h-3 text-indigo-600" />}
                              <span>{ch}</span>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <button
                          onClick={() => handleToggleEnabled(r)}
                          title={r.enabled ? 'Click to pause' : 'Click to activate'}
                          className="inline-flex items-center gap-1 focus:outline-none transition"
                        >
                          {r.enabled ? (
                            <span className="inline-flex items-center gap-1 text-emerald-700 font-semibold text-[11px] bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                              <CheckCircle2 className="w-3 h-3" />
                              <span>Active</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-slate-500 font-medium text-[11px] bg-slate-100 px-2 py-0.5 rounded-full border border-slate-200">
                              <span>Paused</span>
                            </span>
                          )}
                        </button>
                      </td>
                      <td className="py-2.5 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => handleOpenTest(r)}
                            title="Test Dispatch"
                            className="p-1 text-sky-700 hover:bg-sky-50 rounded transition"
                          >
                            <Send className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleOpenDelete(r)}
                            title="Delete Rule"
                            className="p-1 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded transition"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
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

      {/* MODAL: CREATE ALERT RULE */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-lg overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div className="flex items-center gap-2">
                <BellRing className="w-4 h-4 text-[#004874]" />
                <h3 className="font-bold text-sm text-slate-800">Create Operational Alert Rule</h3>
              </div>
              <button
                onClick={() => setIsAddModalOpen(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateRule} className="p-5 space-y-3.5 text-xs max-h-[80vh] overflow-y-auto">
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
                  <label className="block font-semibold text-slate-700 mb-1">Rule Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Inverter Midday Underperformance"
                    value={addName}
                    onChange={(e) => setAddName(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Metric *</label>
                  <input
                    type="text"
                    required
                    placeholder="power_ac"
                    value={addMetric}
                    onChange={(e) => setAddMetric(e.target.value)}
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Direction *</label>
                  <select
                    value={addDirection}
                    onChange={(e) => setAddDirection(e.target.value as any)}
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  >
                    <option value="below">below</option>
                    <option value="above">above</option>
                  </select>
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Threshold *</label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={addThreshold}
                    onChange={(e) => setAddThreshold(parseFloat(e.target.value) || 0)}
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  />
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Severity Tier *</label>
                <div className="grid grid-cols-3 gap-2">
                  {(['critical', 'warning', 'info'] as const).map((sev) => (
                    <button
                      key={sev}
                      type="button"
                      onClick={() => setAddSeverity(sev)}
                      className={`py-1.5 px-3 rounded-lg border text-center font-bold font-mono text-[11px] uppercase transition ${
                        addSeverity === sev
                          ? sev === 'critical'
                            ? 'bg-rose-100 border-rose-300 text-rose-800'
                            : sev === 'warning'
                            ? 'bg-amber-100 border-amber-300 text-amber-800'
                            : 'bg-sky-100 border-sky-300 text-sky-800'
                          : 'bg-slate-50 border-slate-200 text-slate-500 hover:bg-slate-100'
                      }`}
                    >
                      {sev}
                    </button>
                  ))}
                </div>
              </div>

              <div className="pt-2 border-t border-slate-100 space-y-2">
                <label className="block font-semibold text-slate-700">Notification Channels</label>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={addEmailChannel}
                      onChange={(e) => setAddEmailChannel(e.target.checked)}
                      className="rounded text-[#004874]"
                    />
                    <span className="text-slate-800 font-medium">Email Notification</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={addWebhookChannel}
                      onChange={(e) => setAddWebhookChannel(e.target.checked)}
                      className="rounded text-[#004874]"
                    />
                    <span className="text-slate-800 font-medium">Webhook URL Dispatch</span>
                  </label>
                </div>
              </div>

              {addEmailChannel && (
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Recipient Emails (comma-separated)
                  </label>
                  <input
                    type="text"
                    placeholder="ops@solarplant.com, alerts@plantiq.io"
                    value={addRecipients}
                    onChange={(e) => setAddRecipients(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  />
                </div>
              )}

              {addWebhookChannel && (
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Webhook Destination URL
                  </label>
                  <input
                    type="url"
                    placeholder="https://hooks.slack.com/services/..."
                    value={addWebhookUrl}
                    onChange={(e) => setAddWebhookUrl(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  />
                </div>
              )}

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
                  <span>Save Alert Rule</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: TEST ALERT DISPATCH */}
      {isTestModalOpen && selectedRule && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div className="flex items-center gap-2">
                <Send className="w-4 h-4 text-[#004874]" />
                <h3 className="font-bold text-sm text-slate-800">Test Alert Dispatch</h3>
              </div>
              <button
                onClick={() => setIsTestModalOpen(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleExecuteTest} className="p-5 space-y-3.5 text-xs">
              <div className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg space-y-1">
                <div className="font-semibold text-slate-800">{selectedRule.name}</div>
                <div className="text-[11px] font-mono text-slate-500">
                  Condition: {selectedRule.metric} {selectedRule.direction} {selectedRule.threshold}
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  Recipient Override (optional)
                </label>
                <input
                  type="text"
                  placeholder="test-recipient@domain.com"
                  value={testRecipient}
                  onChange={(e) => setTestRecipient(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Test Message Body</label>
                <textarea
                  rows={2}
                  value={testMessage}
                  onChange={(e) => setTestMessage(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              {testResult && (
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg space-y-1 text-emerald-800 font-mono text-[11px]">
                  <div className="font-bold flex items-center gap-1.5 text-emerald-900">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    <span>Dispatch {testResult.status}</span>
                  </div>
                  <div>Channel: {testResult.channel}</div>
                  <div>Recipient: {testResult.recipient}</div>
                </div>
              )}

              <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsTestModalOpen(false)}
                  className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-1.5 bg-[#004874] hover:bg-sky-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition"
                >
                  {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Dispatch Test</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: DELETE CONFIRMATION */}
      {isDeleteModalOpen && selectedRule && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-sm overflow-hidden animate-in fade-in zoom-in-95 duration-150 p-5 space-y-4">
            <div className="w-10 h-10 rounded-full bg-rose-100 text-rose-600 flex items-center justify-center mx-auto">
              <Trash2 className="w-5 h-5" />
            </div>
            <div className="text-center space-y-1">
              <h3 className="font-bold text-sm text-slate-800">Delete Alert Rule</h3>
              <p className="text-xs text-slate-600">
                Are you sure you want to permanently delete rule{' '}
                <span className="font-semibold text-slate-900">{selectedRule.name}</span>?
              </p>
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
                onClick={handleDeleteRule}
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

