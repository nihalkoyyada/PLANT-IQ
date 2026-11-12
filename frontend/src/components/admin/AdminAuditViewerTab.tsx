import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  Calendar,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock,
  Code,
  FileText,
  History,
  Loader2,
  RefreshCw,
  Search,
  Shield,
  User as UserIcon,
  X,
} from 'lucide-react';
import { getAuditLogActions, getAuditLogs } from '../../api/admin';
import { AuditLog } from '../../types';

export const AdminAuditViewerTab: React.FC = () => {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Pagination
  const [actionFilter, setActionFilter] = useState<string>('');
  const [entityFilter, setEntityFilter] = useState<string>('');
  const [search, setSearch] = useState<string>('');
  const [availableActions, setAvailableActions] = useState<string[]>([]);
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);

  const [page, setPage] = useState<number>(1);
  const pageSize = 20;

  const fetchLogs = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const res = await getAuditLogs({
        action: actionFilter || undefined,
        entity: entityFilter || undefined,
        search: search.trim() || undefined,
        limit: pageSize,
        offset,
      });
      setLogs(res.items);
      setTotalCount(res.total);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to retrieve security audit logs');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [page, actionFilter, entityFilter]);

  useEffect(() => {
    getAuditLogActions()
      .then((actions) => setAvailableActions(actions))
      .catch(() => {});
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchLogs();
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  return (
    <div className="space-y-4">
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
        <form onSubmit={handleSearchSubmit} className="flex-1 w-full flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search audit action or entity..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#004874] text-slate-800"
            />
          </div>
          <button
            type="submit"
            className="px-3 py-1.5 text-xs font-semibold bg-[#004874] text-white rounded-lg hover:bg-sky-800 transition shadow-xs"
          >
            Search
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          {/* Action Filter */}
          <select
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setPage(1);
            }}
            className="px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#004874]"
          >
            <option value="">All Actions</option>
            {availableActions.map((act) => (
              <option key={act} value={act}>
                {act}
              </option>
            ))}
          </select>

          {/* Entity Filter */}
          <select
            value={entityFilter}
            onChange={(e) => {
              setEntityFilter(e.target.value);
              setPage(1);
            }}
            className="px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#004874]"
          >
            <option value="">All Entities</option>
            <option value="auth">auth</option>
            <option value="user">user</option>
            <option value="organization">organization</option>
            <option value="detector">detector</option>
            <option value="alert_rule">alert_rule</option>
            <option value="anomaly">anomaly</option>
          </select>

          <button
            onClick={() => {
              setSearch('');
              setActionFilter('');
              setEntityFilter('');
              setPage(1);
              fetchLogs();
            }}
            title="Refresh audit logs"
            className="p-1.5 text-slate-600 hover:text-slate-900 border border-slate-200 rounded-lg hover:bg-slate-50 transition"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono uppercase text-slate-500">
                <th className="py-2.5 px-4 font-semibold">Timestamp (UTC)</th>
                <th className="py-2.5 px-4 font-semibold">Actor / User</th>
                <th className="py-2.5 px-4 font-semibold">Action</th>
                <th className="py-2.5 px-4 font-semibold">Target Entity</th>
                <th className="py-2.5 px-4 font-semibold">Security Details & Metadata</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-slate-500 font-mono">
                    <div className="flex items-center justify-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-[#004874]" />
                      <span>Loading tamper-evident security audit logs...</span>
                    </div>
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-slate-400 font-mono">
                    No audit records found matching criteria.
                  </td>
                </tr>
              ) : (
                logs.map((log) => {
                  const isExpanded = expandedLogId === log.id;
                  const isFailure = log.action.includes('fail') || log.action.includes('delete');
                  const isSuccess = log.action.includes('success') || log.action.includes('create');

                  const actionBadge = isFailure
                    ? 'bg-rose-100 text-rose-800 border-rose-200'
                    : isSuccess
                    ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
                    : 'bg-sky-100 text-sky-800 border-sky-200';

                  const dateObj = new Date(log.created_at);

                  return (
                    <React.Fragment key={log.id}>
                      <tr className="hover:bg-slate-50/60 transition">
                        <td className="py-2.5 px-4 font-mono text-slate-500 whitespace-nowrap">
                          <div className="flex items-center gap-1.5 text-slate-700 font-semibold text-[11px]">
                            <Clock className="w-3.5 h-3.5 text-slate-400" />
                            <span>{dateObj.toLocaleDateString()} {dateObj.toLocaleTimeString()}</span>
                          </div>
                        </td>
                        <td className="py-2.5 px-4">
                          {log.user_email ? (
                            <div>
                              <div className="font-semibold text-slate-800">{log.user_name || 'User'}</div>
                              <div className="font-mono text-[10px] text-slate-500">{log.user_email}</div>
                            </div>
                          ) : (
                            <span className="font-mono text-slate-400 italic text-[11px]">System / Unauthenticated</span>
                          )}
                        </td>
                        <td className="py-2.5 px-4">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border ${actionBadge}`}>
                            {log.action}
                          </span>
                        </td>
                        <td className="py-2.5 px-4">
                          <span className="font-mono text-slate-700 bg-slate-100 px-1.5 py-0.5 rounded text-[11px]">
                            {log.entity}
                          </span>
                        </td>
                        <td className="py-2.5 px-4">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-mono text-[11px] text-slate-600 truncate max-w-xs">
                              {JSON.stringify(log.details)}
                            </span>
                            <button
                              onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                              className="p-1 text-slate-400 hover:text-slate-700 rounded transition shrink-0"
                              title="Inspect JSON details"
                            >
                              {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                            </button>
                          </div>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="bg-slate-900 text-slate-100 font-mono text-[11px]">
                          <td colSpan={5} className="p-3.5 pl-6 border-b border-slate-800">
                            <div className="flex items-center justify-between mb-1.5 text-slate-400 text-[10px]">
                              <span>Audit Event ID: {log.id}</span>
                              <span>Target Entity ID: {log.entity_id || 'N/A'}</span>
                            </div>
                            <pre className="overflow-x-auto text-emerald-400 p-2 bg-slate-950 rounded">
                              {JSON.stringify(log.details, null, 2)}
                            </pre>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="p-3 bg-slate-50 border-t border-slate-200/80 flex items-center justify-between text-xs text-slate-600 font-mono">
          <div>
            Showing {logs.length > 0 ? (page - 1) * pageSize + 1 : 0} to{' '}
            {Math.min(page * pageSize, totalCount)} of {totalCount} audit logs
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1 rounded border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="px-2 font-semibold">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1 rounded border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

