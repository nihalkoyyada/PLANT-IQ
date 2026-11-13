import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  Building2,
  Cpu,
  Loader2,
  RefreshCw,
  Search,
  Sun,
  Wind,
  Zap,
} from 'lucide-react';
import { getPlatformPlantsAssets } from '../../api/platform';
import { formatApiError } from '../../api/client';
import { PlatformPlantsResponse } from '../../types';

export const PlatformPlantsTab: React.FC = () => {
  const [data, setData] = useState<PlatformPlantsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getPlatformPlantsAssets();
      setData(res);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to load cross-tenant plant inventory'));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const filteredItems = (data?.items || []).filter((p) => {
    const matchesSearch =
      p.name.toLowerCase().includes(search.toLowerCase()) ||
      p.org_name.toLowerCase().includes(search.toLowerCase());
    const matchesType = !typeFilter || p.plant_type.toLowerCase() === typeFilter.toLowerCase();
    return matchesSearch && matchesType;
  });

  return (
    <div className="space-y-4">
      {/* Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs">
          <span className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Total Plants</span>
          <div className="text-xl font-bold text-slate-900 mt-1">{data?.total_plants ?? 0}</div>
        </div>
        <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs">
          <span className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Total Capacity</span>
          <div className="text-xl font-bold text-slate-900 mt-1">{data?.total_capacity_mw ?? 0} MW</div>
        </div>
        <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs">
          <span className="text-[10px] font-mono text-amber-700 uppercase font-semibold">Solar MW</span>
          <div className="text-xl font-bold text-amber-900 mt-1">{data?.solar_capacity_mw ?? 0} MW</div>
        </div>
        <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs">
          <span className="text-[10px] font-mono text-sky-700 uppercase font-semibold">Wind MW</span>
          <div className="text-xl font-bold text-sky-900 mt-1">{data?.wind_capacity_mw ?? 0} MW</div>
        </div>
        <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-xs col-span-2 md:col-span-1">
          <span className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Inverters & Devices</span>
          <div className="text-xl font-bold text-slate-900 mt-1">{data?.total_devices ?? 0}</div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-center justify-between gap-3">
        <div className="relative flex-1 w-full md:max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter plants by name or organization..."
            className="w-full pl-9 pr-3 py-2 text-xs border border-slate-200 rounded-lg text-slate-800 bg-white"
          />
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto justify-end">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            aria-label="Filter plants by generation type"
            className="px-3 py-2 text-xs border border-slate-200 rounded-lg bg-white text-slate-700"
          >
            <option value="">All Types</option>
            <option value="solar">Solar PV</option>
            <option value="wind">Wind</option>
            <option value="process">Process</option>
          </select>

          <button
            onClick={fetchData}
            className="p-2 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 cursor-pointer transition"
            title="Refresh Plants"
            aria-label="Refresh plants"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-[#004874]' : ''}`} />
          </button>
        </div>
      </div>

      {/* Plants Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono text-slate-500 uppercase">
                <th className="py-3 px-4 font-semibold">Plant Name</th>
                <th className="py-3 px-3 font-semibold">Tenant Organization</th>
                <th className="py-3 px-3 font-semibold">Generation Type</th>
                <th className="py-3 px-3 font-semibold">Rated Capacity</th>
                <th className="py-3 px-3 font-semibold text-center">Connected Inverters / Assets</th>
                <th className="py-3 px-4 font-semibold text-right">Registered</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#004874] mb-2" />
                    QUERYING CROSS-TENANT ASSET INVENTORY...
                  </td>
                </tr>
              ) : filteredItems.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                    No plants found matching the criteria.
                  </td>
                </tr>
              ) : (
                filteredItems.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-50/80 transition">
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-lg bg-amber-50 text-amber-700 flex items-center justify-center shrink-0">
                          {p.plant_type === 'wind' ? <Wind className="w-4 h-4 text-sky-700" /> : <Sun className="w-4 h-4" />}
                        </div>
                        <div>
                          <div className="font-bold text-slate-900">{p.name}</div>
                          <div className="text-[10px] font-mono text-slate-400">ID: {p.id.slice(0, 8)}...</div>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-3 font-semibold text-slate-800">
                      {p.org_name}
                    </td>
                    <td className="py-3 px-3">
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-slate-100 text-slate-700">
                        {p.plant_type}
                      </span>
                    </td>
                    <td className="py-3 px-3 font-mono font-bold text-slate-800">
                      {p.capacity_mw} MW
                    </td>
                    <td className="py-3 px-3 text-center font-mono font-bold text-slate-700">
                      {p.device_count}
                    </td>
                    <td className="py-3 px-4 text-right font-mono text-[11px] text-slate-400">
                      {new Date(p.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

