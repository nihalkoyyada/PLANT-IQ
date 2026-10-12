import React, { useState, useEffect } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import { AlertCircle, RefreshCw, Activity } from 'lucide-react';
import { getReadingAggregate } from '../../api/readings';

interface DeviceChartProps {
  acChannelId?: string;
  dcChannelId?: string;
  latestTimestamp?: string;
}

interface ChartPoint {
  timestamp: string;
  timeLabel: string;
  fullTimeLabel: string;
  acPowerKw?: number | null;
  dcPowerKw?: number | null;
}

export const DeviceChart: React.FC<DeviceChartProps> = ({
  acChannelId,
  dcChannelId,
  latestTimestamp,
}) => {
  const [range, setRange] = useState<'24H' | '7D'>('24H');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);

  const fetchChartData = async () => {
    if (!acChannelId && !dcChannelId) {
      setLoading(false);
      setChartData([]);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      // 1. Determine anchor timestamp for historical window
      let anchorDate = new Date();
      if (latestTimestamp && latestTimestamp !== 'No reading') {
        const parsed = new Date(latestTimestamp);
        if (!isNaN(parsed.getTime())) {
          anchorDate = parsed;
        }
      }

      const endIso = anchorDate.toISOString();
      const hoursBack = range === '24H' ? 24 : 168;
      const startIso = new Date(anchorDate.getTime() - hoursBack * 60 * 60 * 1000).toISOString();
      const interval = range === '24H' ? '15min' : 'hour';

      // 2. Query aggregate readings for AC and DC channels
      const [acAggs, dcAggs] = await Promise.all([
        acChannelId
          ? getReadingAggregate({ channel_id: acChannelId, start: startIso, end: endIso, interval }).catch(() => [])
          : Promise.resolve([]),
        dcChannelId
          ? getReadingAggregate({ channel_id: dcChannelId, start: startIso, end: endIso, interval }).catch(() => [])
          : Promise.resolve([]),
      ]);

      let finalAcAggs = acAggs;
      let finalDcAggs = dcAggs;

      // Fallback: If range-filtered query returned empty, query min/max range for the channel
      if (finalAcAggs.length === 0 && finalDcAggs.length === 0) {
        const [fallbackAc, fallbackDc] = await Promise.all([
          acChannelId
            ? getReadingAggregate({ channel_id: acChannelId, interval }).catch(() => [])
            : Promise.resolve([]),
          dcChannelId
            ? getReadingAggregate({ channel_id: dcChannelId, interval }).catch(() => [])
            : Promise.resolve([]),
        ]);
        finalAcAggs = fallbackAc;
        finalDcAggs = fallbackDc;
      }

      if (finalAcAggs.length === 0 && finalDcAggs.length === 0) {
        setChartData([]);
        setLoading(false);
        return;
      }

      // 3. Process & Align Telemetry Data
      const timeMap: Record<string, { acKw?: number; dcKw?: number }> = {};

      finalAcAggs.forEach((item) => {
        if (!item.start) return;
        const ts = new Date(item.start).toISOString();
        if (item.average_value !== undefined && item.average_value !== null) {
          const raw = Number(item.average_value);
          const kw = raw > 500.0 ? raw / 1000.0 : raw;
          if (!timeMap[ts]) timeMap[ts] = {};
          timeMap[ts].acKw = Math.max(0, Number(kw.toFixed(2)));
        }
      });

      finalDcAggs.forEach((item) => {
        if (!item.start) return;
        const ts = new Date(item.start).toISOString();
        if (item.average_value !== undefined && item.average_value !== null) {
          const raw = Number(item.average_value);
          let kw = raw > 50000.0 ? raw / 1000.0 : (raw > 5000.0 ? raw / 10.0 : raw);
          if (timeMap[ts]?.acKw !== undefined && timeMap[ts].acKw! > 0) {
            const ac = timeMap[ts].acKw!;
            if (raw / 10.0 >= ac * 0.5 && raw / 10.0 <= ac * 1.8) {
              kw = raw / 10.0;
            } else if (raw / 1000.0 >= ac * 0.5 && raw / 1000.0 <= ac * 1.8) {
              kw = raw / 1000.0;
            }
          }
          if (!timeMap[ts]) timeMap[ts] = {};
          timeMap[ts].dcKw = Math.max(0, Number(kw.toFixed(2)));
        }
      });

      const sortedTimestamps = Object.keys(timeMap).sort(
        (a, b) => new Date(a).getTime() - new Date(b).getTime()
      );

      const points: ChartPoint[] = sortedTimestamps.map((ts) => {
        const date = new Date(ts);
        const timeLabel = range === '24H'
          ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })
          : `${date.toLocaleDateString([], { month: 'short', day: 'numeric', timeZone: 'UTC' })} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })}`;

        const fullTimeLabel = `${date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })}`;

        return {
          timestamp: ts,
          timeLabel,
          fullTimeLabel,
          acPowerKw: timeMap[ts].acKw !== undefined ? timeMap[ts].acKw : null,
          dcPowerKw: timeMap[ts].dcKw !== undefined ? timeMap[ts].dcKw : null,
        };
      });

      setChartData(points);
    } catch (err: any) {
      console.error('Error fetching device historical telemetry:', err);
      setError('Failed to load historical telemetry data.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchChartData();
  }, [acChannelId, dcChannelId, latestTimestamp, range]);

  if (loading) {
    return (
      <div className="bg-slate-50 p-6 rounded-xl border border-slate-200/80 animate-pulse space-y-3">
        <div className="h-4 bg-slate-200 rounded w-1/3"></div>
        <div className="h-48 bg-slate-200/70 rounded w-full"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-rose-50/70 p-4 rounded-xl border border-rose-200 font-mono text-xs text-rose-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-rose-600" />
          <span>{error}</span>
        </div>
        <button
          onClick={fetchChartData}
          className="flex items-center gap-1 px-2.5 py-1 bg-white border border-rose-200 rounded text-rose-700 hover:bg-rose-100 font-semibold cursor-pointer"
        >
          <RefreshCw className="w-3 h-3" />
          Retry
        </button>
      </div>
    );
  }

  if (chartData.length === 0) {
    return (
      <div className="bg-slate-50 p-6 rounded-xl border border-slate-200/80 text-center font-mono text-xs text-slate-500 space-y-2">
        <Activity className="w-6 h-6 text-slate-400 mx-auto" />
        <p className="font-semibold text-slate-700">No historical telemetry available for this inverter.</p>
        <span className="text-[10px] text-slate-400">
          No 5-minute or 15-minute readings found in the database for the selected channels.
        </span>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/95 p-4 rounded-xl border border-slate-800 shadow-xl space-y-3">
      {/* Header & Range Selector */}
      <div className="flex items-center justify-between text-xs font-mono">
        <span className="text-slate-300 font-bold uppercase tracking-wider flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping inline-block" />
          Telemetry Trend ({range})
        </span>

        <div className="flex items-center gap-1 bg-slate-800 p-0.5 rounded-md border border-slate-700">
          {(['24H', '7D'] as const).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-2 py-0.5 text-[10px] font-bold rounded transition cursor-pointer ${
                range === r
                  ? 'bg-sky-600 text-white shadow-xs'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Recharts Container */}
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="acGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
              </linearGradient>
              <linearGradient id="dcGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#fbbf24" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#fbbf24" stopOpacity={0.0} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />

            <XAxis
              dataKey="timeLabel"
              stroke="#64748b"
              tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'monospace' }}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
            />

            <YAxis
              stroke="#64748b"
              tick={{ fill: '#94a3b8', fontSize: 10, fontFamily: 'monospace' }}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
              unit=" kW"
            />

            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const pt = payload[0].payload as ChartPoint;
                  return (
                    <div className="bg-slate-900 border border-slate-700 p-2.5 rounded-lg shadow-xl text-white font-mono text-xs space-y-1">
                      <div className="text-[11px] font-bold text-slate-400 border-b border-slate-800 pb-1">
                        {pt.fullTimeLabel}
                      </div>
                      {pt.acPowerKw !== null && pt.acPowerKw !== undefined && (
                        <div className="flex items-center justify-between gap-4 text-sky-400">
                          <span>AC Power:</span>
                          <span className="font-bold">{pt.acPowerKw} kW</span>
                        </div>
                      )}
                      {pt.dcPowerKw !== null && pt.dcPowerKw !== undefined && (
                        <div className="flex items-center justify-between gap-4 text-amber-400">
                          <span>DC Power:</span>
                          <span className="font-bold">{pt.dcPowerKw} kW</span>
                        </div>
                      )}
                    </div>
                  );
                }
                return null;
              }}
            />

            <Legend
              wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace', paddingTop: '8px' }}
              formatter={(value) => <span className="text-slate-300 font-medium">{value}</span>}
            />

            <Area
              type="monotone"
              dataKey="acPowerKw"
              name="AC Power (kW)"
              stroke="#38bdf8"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#acGradient)"
              connectNulls={false}
            />

            <Area
              type="monotone"
              dataKey="dcPowerKw"
              name="DC Power (kW)"
              stroke="#fbbf24"
              strokeWidth={2}
              fillOpacity={1}
              fill="url(#dcGradient)"
              connectNulls={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
