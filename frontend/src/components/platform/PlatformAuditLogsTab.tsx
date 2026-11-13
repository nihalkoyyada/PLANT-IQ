import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  Building2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  History,
  Loader2,
  RefreshCw,
  Search,
  Shield,
  X,
} from 'lucide-react';
import { getPlatformAuditLogs, getPlatformOrganizations } from '../../api/platform';
import { formatApiError } from '../../api/client';
import { PlatformAuditLogItem, PlatformOrgListItem } from '../../types';

export const PlatformAuditLogsTab: React.FC = () => {
  const [logs, setLogs] = useState<PlatformAuditLogItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [organizations, setOrganizations] = useState<PlatformOrgListItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Pagination
  const [search, setSearch] = useState<string>('');
  const [actionFilter, setActionFilter] = useState<string>('');
  const [orgFilter, setOrgFilter] = useState<string>('');
  const [page, setPage] = useState<number>(1);
  const pageSize = 20;

  // Expanded rows
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);

  const fetchLogs = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const res = await getPlatformAuditLogs({
        search: search.trim() || undefined,
        action: actionFilter || undefined,
        org_id: orgFilter || undefined,
        limit: pageSize,
        offset,
      });
      setLogs(res.items);
      setTotalCount(res.total);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to load global platform audit logs'));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [page, actionFilter, orgFilter]);

  useEffect(() => {
    getPlatformOrganizations({ limit: 100 })
      .then((res) => setOrganizations(res.items))
      .catch(() => {});
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchLogs();
  };

  const toggleExpand = (id: string) => {
    setExpandedLogId((prev) => (prev === id ? null : id));
  };

  const totalPages = Math.ceil(totalCount / pageSize);

  return (
    <div className="space-y-4">
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

      {/* Filter and Search Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-center justify-between gap-3">
        <form onSubmit={handleSearchSubmit} className="flex-1 flex items-center gap-2 w-full md:w-auto">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search audit trail by actor, action, or details..."
              className="w-full pl-9 pr-3 py-2 text-xs border border-slate-200 rounded-lg text-slate-800 bg-white"
            />
          </div>
          <button
            type="submit"
            className="px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold cursor-pointer transition"
          >
            Search
          </button>
        </form>

        <div className="flex items-center gap-2 flex-wrap w-full md:w-auto justify-end">
          <select
            value={orgFilter}
            onChange={(e) => {
              setOrgFilter(e.target.value);
              setPage(1);
            }}
            aria-label="Filter audit logs by organization"
            className="px-3 py-2 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 max-w-[160px] truncate"
          >
            <option value="">All Organizations</option>
            {organizations.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
              </option>
            ))}
          </select>

          <select
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setPage(1);
            }}
            aria-label="Filter audit logs by action"
            className="px-3 py-2 text-xs border border-slate-200 rounded-lg bg-white text-slate-700"
          >
            <option value="">All Actions</option>
            <option value="ORGANIZATION_CREATE">Organization Created</option>
            <option value="ORGANIZATION_SUSPEND">Organization Suspended</option>
            <option value="ORGANIZATION_ACTIVATE">Organization Activated</option>
            <option value="TENANT_INSPECT">Tenant Inspected</option>
            <option value="USER_CREATE">User Created</option>
            <option value="USER_UPDATE">User Updated</option>
            <option value="USER_DELETE">User Deleted</option>
            <option value="login_success">Login Succeeded</option>
            <option value="login_failed">Login Failed</option>
          </select>

          <button
            onClick={fetchLogs}
            className="p-2 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 cursor-pointer transition"
            title="Refresh Audit Logs"
            aria-label="Refresh audit logs"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-[#004874]' : ''}`} />
          </button>
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono text-slate-500 uppercase">
                <th className="py-3 px-4 font-semibold">Timestamp</th>
                <th className="py-3 px-3 font-semibold">Actor</th>
                <th className="py-3 px-3 font-semibold">Tenant Organization</th>
                <th className="py-3 px-3 font-semibold">Action</th>
                <th className="py-3 px-3 font-semibold">Target Entity</th>
                <th className="py-3 px-4 font-semibold text-right">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#004874] mb-2" />
                    QUERYING TAMPER-EVIDENT PLATFORM AUDIT TRAIL...
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                    No audit records found matching your filters.
                  </td>
                </tr>
              ) : (
                logs.map((log) => {
                  const isExpanded = expandedLogId === log.id;
                  return (
                    <React.Fragment key={log.id}>
                      <tr className="hover:bg-slate-50/80 transition cursor-pointer" onClick={() => toggleExpand(log.id)}>
                        <td className="py-3 px-4 font-mono text-[11px] text-slate-500 whitespace-nowrap">
                          {new Date(log.created_at).toLocaleString()}
                        </td>
                        <td className="py-3 px-3">
                          <div className="font-semibold text-slate-900">{log.actor_name || 'System / Automated'}</div>
                          {log.actor_email && (
                            <div className="text-[10px] font-mono text-slate-400">{log.actor_email}</div>
                          )}
                        </td>
                        <td className="py-3 px-3 font-semibold text-slate-700">
                          {log.org_name || 'Platform Core'}
                        </td>
                        <td className="py-3 px-3">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-slate-100 text-slate-800">
                            {log.action}
                          </span>
                        </td>
                        <td className="py-3 px-3 font-mono text-[11px] text-slate-600">
                          {log.entity} {log.entity_id ? `(${log.entity_id.slice(0, 8)}...)` : ''}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleExpand(log.id);
                            }}
                            className="p-1 text-slate-400 hover:text-slate-700 rounded transition cursor-pointer"
                            aria-label={isExpanded ? 'Collapse row details' : 'Expand row details'}
                          >
                            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                          </button>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="bg-slate-50/60">
                          <td colSpan={6} className="p-4 border-t border-slate-100">
                            <div className="p-3 bg-slate-900 text-emerald-400 rounded-lg font-mono text-[11px] overflow-x-auto max-h-56">
                              <pre>{JSON.stringify(log.details, null, 2)}</pre>
                            </div>
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

        {/* Pagination Footer */}
        <div className="p-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-xs text-slate-500 font-mono">
          <div>
            Showing {logs.length} of {totalCount} platform audit events
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1 rounded border border-slate-200 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white cursor-pointer transition"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="font-semibold text-slate-700">
              Page {page} of {totalPages || 1}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1 rounded border border-slate-200 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white cursor-pointer transition"
              aria-label="Next page"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

