import React, { useState } from 'react';
import { Cpu, Search, ChevronRight } from 'lucide-react';
import { Badge } from '../common/Badge';

export interface DeviceItem {
  id: string;
  name: string;
  sourceKey: string;
  assetType: string;
  ratedKw: number;
  status: 'ONLINE' | 'MAINTENANCE' | 'OFFLINE';
  lastReading: string;
  acPowerKw?: number;
  dcPowerKw?: number;
  acTimestamp?: string;
  dcTimestamp?: string;
  dailyYieldKwh?: number;
  totalYieldKwh?: number;
}

const formatReadingTime = (tsStr?: string): string | null => {
  if (!tsStr || tsStr === 'No reading') return null;
  try {
    const d = new Date(tsStr);
    if (isNaN(d.getTime())) return null;
    const day = d.getUTCDate();
    const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
    const year = d.getUTCFullYear();
    const hours = String(d.getUTCHours()).padStart(2, '0');
    const mins = String(d.getUTCMinutes()).padStart(2, '0');
    return `${day} ${month} ${year} ${hours}:${mins} UTC`;
  } catch {
    return null;
  }
};

interface DeviceTableProps {
  devices: DeviceItem[];
  onSelectDevice: (device: DeviceItem) => void;
}

export const DeviceTable: React.FC<DeviceTableProps> = ({ devices, onSelectDevice }) => {
  const [search, setSearch] = useState('');

  const filtered = devices.filter(
    (d) =>
      d.name.toLowerCase().includes(search.toLowerCase()) ||
      d.sourceKey.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="bg-white rounded-xl border border-slate-200/90 shadow-xs overflow-hidden space-y-4 p-4">
      {/* Search Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <div>
          <h3 className="text-sm font-bold text-slate-900 tracking-tight">Solar Inverter Fleet</h3>
          <p className="text-xs text-slate-500 font-mono">
            {devices.length} Discrete SCADA Inverter Nodes
          </p>
        </div>

        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search inverter key..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 pr-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs font-mono text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 w-full sm:w-60"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-[10px] font-mono font-semibold uppercase text-slate-500 tracking-wider">
              <th className="py-2.5 px-3">INVERTER / ASSET KEY</th>
              <th className="py-2.5 px-3">TYPE</th>
              <th className="py-2.5 px-3">RATED (KW)</th>
              <th className="py-2.5 px-3">STATUS</th>
              <th className="py-2.5 px-3">AC POWER</th>
              <th className="py-2.5 px-3">DC POWER</th>
              <th className="py-2.5 px-3">DAILY YIELD</th>
              <th className="py-2.5 px-3">ACTION</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-xs font-mono">
            {filtered.length > 0 ? (
              filtered.map((dev) => (
                <tr
                  key={dev.id}
                  onClick={() => onSelectDevice(dev)}
                  className="hover:bg-sky-50/60 transition cursor-pointer group"
                >
                  <td className="py-3 px-3">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700">
                        <Cpu className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="font-bold text-slate-900">{dev.name}</div>
                        <div className="text-[10px] text-slate-400 font-mono">{dev.sourceKey}</div>
                      </div>
                    </div>
                  </td>
                  <td className="py-3 px-3 capitalize text-slate-600">{dev.assetType}</td>
                  <td className="py-3 px-3 font-semibold text-slate-800">{dev.ratedKw} kW</td>
                  <td className="py-3 px-3">
                    <Badge variant={dev.status === 'ONLINE' ? 'emerald' : 'rose'}>
                      ● {dev.status}
                    </Badge>
                  </td>
                  <td className="py-3 px-3">
                    {dev.acPowerKw !== undefined && dev.acPowerKw !== null ? (
                      <div>
                        <div className="text-sky-700 font-semibold">{dev.acPowerKw.toFixed(1)} kW</div>
                        {dev.acTimestamp && formatReadingTime(dev.acTimestamp) && (
                          <div className="text-[9px] text-slate-400 font-mono font-normal">
                            Data: {formatReadingTime(dev.acTimestamp)}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-slate-400 font-semibold">---</span>
                    )}
                  </td>
                  <td className="py-3 px-3">
                    {dev.dcPowerKw !== undefined && dev.dcPowerKw !== null ? (
                      <div>
                        <div className="text-amber-700 font-semibold">{dev.dcPowerKw.toFixed(1)} kW</div>
                        {dev.dcTimestamp && formatReadingTime(dev.dcTimestamp) && (
                          <div className="text-[9px] text-slate-400 font-mono font-normal">
                            Data: {formatReadingTime(dev.dcTimestamp)}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-slate-400 font-semibold">---</span>
                    )}
                  </td>
                  <td className="py-3 px-3 text-emerald-700 font-semibold">
                    {dev.dailyYieldKwh !== undefined && dev.dailyYieldKwh !== null ? `${dev.dailyYieldKwh.toFixed(0)} kWh` : '---'}
                  </td>
                  <td className="py-3 px-3">
                    <button className="p-1 rounded bg-slate-100 group-hover:bg-[#004874] group-hover:text-white transition">
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={8} className="py-6 text-center text-slate-400 text-xs">
                  No matching inverters found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
