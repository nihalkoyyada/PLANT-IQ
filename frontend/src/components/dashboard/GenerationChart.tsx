import React, { useState, useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
} from 'recharts';
import { Zap, Activity } from 'lucide-react';

export interface ChartPoint {
  timestamp?: string; // ISO timestamp string e.g. "2026-10-03T12:00:00Z"
  time: string;      // Formatted time e.g. "12:00"
  acPower: number;   // Power in MW
  dcPower: number;   // Power in MW
  isFault?: boolean;
}

interface GenerationChartProps {
  data: ChartPoint[];
  loading?: boolean;
}

const formatMonthDay = (date: Date): string => {
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
};

const formatTimeOnly = (date: Date): string => {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const formatFullDateTime = (date: Date): string => {
  return `${formatMonthDay(date)}, ${formatTimeOnly(date)}`;
};

const CustomTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    const point = payload[0].payload;
    const acItem = payload.find((p: any) => p.dataKey === 'acPower');
    const dcItem = payload.find((p: any) => p.dataKey === 'dcPower');

    return (
      <div className="bg-slate-900 border border-slate-700 p-3 rounded-lg shadow-xl text-white font-mono text-xs space-y-1.5 min-w-[160px]">
        <div className="font-bold text-slate-300 border-b border-slate-700/80 pb-1 flex items-center justify-between">
          <span>{point.fullTimeLabel || point.time}</span>
        </div>
        <div className="space-y-1 pt-0.5">
          <div className="flex items-center justify-between gap-3 text-sky-400">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-sky-400 inline-block" />
              AC Power:
            </span>
            <span className="font-bold">{acItem?.value !== undefined ? `${acItem.value} MW` : 'N/A'}</span>
          </div>
          <div className="flex items-center justify-between gap-3 text-amber-400">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-400 inline-block" />
              DC Power:
            </span>
            <span className="font-bold">{dcItem?.value !== undefined ? `${dcItem.value} MW` : 'N/A'}</span>
          </div>
        </div>
      </div>
    );
  }
  return null;
};

export const GenerationChart: React.FC<GenerationChartProps> = ({ data, loading }) => {
  const [timeRange, setTimeRange] = useState<'24H' | '7D' | '30D'>('24H');

  // Process data, calculate KPIs dynamically for active timeRange, and downsample for optimal visualization
  const processed = useMemo(() => {
    if (!data || data.length === 0) {
      return {
        displayData: [],
        peakAc: { val: 0, timeLabel: '' },
        peakDc: { val: 0, timeLabel: '' },
        avgAc: 0,
        avgDc: 0,
        peakAcPoint: null,
        peakDcPoint: null,
      };
    }

    // 1. Calculate max timestamp in dataset to anchor time range windows
    let latestMs = 0;
    const parsedPoints = data.map((pt) => {
      const ms = pt.timestamp ? new Date(pt.timestamp).getTime() : 0;
      if (ms > latestMs) latestMs = ms;
      return { ...pt, ms };
    });

    if (latestMs === 0) {
      latestMs = Date.now();
    }

    // 2. Filter dataset based on active timeRange
    let rangeCutoffMs = 0;
    if (timeRange === '24H') {
      rangeCutoffMs = latestMs - 24 * 3600 * 1000;
    } else if (timeRange === '7D') {
      rangeCutoffMs = latestMs - 7 * 24 * 3600 * 1000;
    } else {
      rangeCutoffMs = latestMs - 30 * 24 * 3600 * 1000;
    }

    let rangePoints = parsedPoints.filter((pt) => pt.ms >= rangeCutoffMs);
    if (rangePoints.length === 0) {
      const count = timeRange === '24H' ? 24 : timeRange === '7D' ? 168 : data.length;
      rangePoints = parsedPoints.slice(-count);
    }

    // 3. Calculate exact KPIs for the selected timeRange
    let maxAc = 0;
    let maxAcPt: (typeof rangePoints)[0] | null = null;
    let maxDc = 0;
    let maxDcPt: (typeof rangePoints)[0] | null = null;
    let sumAc = 0;
    let sumDc = 0;

    rangePoints.forEach((pt) => {
      const ac = pt.acPower || 0;
      const dc = pt.dcPower || 0;
      sumAc += ac;
      sumDc += dc;

      if (ac > maxAc) {
        maxAc = ac;
        maxAcPt = pt;
      }
      if (dc > maxDc) {
        maxDc = dc;
        maxDcPt = pt;
      }
    });

    const avgAc = rangePoints.length > 0 ? sumAc / rangePoints.length : 0;
    const avgDc = rangePoints.length > 0 ? sumDc / rangePoints.length : 0;

    const formatPeakTime = (pt: typeof maxAcPt) => {
      if (!pt) return '';
      if (pt.timestamp) {
        const d = new Date(pt.timestamp);
        return timeRange === '24H' ? `@ ${formatTimeOnly(d)}` : `@ ${formatFullDateTime(d)}`;
      }
      return `@ ${pt.time}`;
    };

    const peakAcTimeLabel = formatPeakTime(maxAcPt);
    const peakDcTimeLabel = formatPeakTime(maxDcPt);

    // 4. Downsample/aggregate rangePoints for chart visualization
    let targetBucketSize = 1;
    if (timeRange === '24H' && rangePoints.length > 48) {
      targetBucketSize = Math.ceil(rangePoints.length / 36);
    } else if (timeRange === '7D' && rangePoints.length > 48) {
      targetBucketSize = Math.ceil(rangePoints.length / 42);
    } else if (timeRange === '30D' && rangePoints.length > 60) {
      targetBucketSize = Math.ceil(rangePoints.length / 50);
    }

    // Build displayData with presentation X-axis formatting per view mode
    const displayData: any[] = [];
    let lastDateStr = '';

    const totalDays = rangePoints.length > 0 && rangePoints[0].timestamp && rangePoints[rangePoints.length - 1].timestamp
      ? Math.max(1, Math.round((rangePoints[rangePoints.length - 1].ms - rangePoints[0].ms) / (24 * 3600 * 1000)))
      : (timeRange === '30D' ? 30 : 7);

    const dateLabelIntervalDays = timeRange === '30D' ? Math.max(4, Math.ceil(totalDays / 6)) : 1;
    let dayCount = 0;

    for (let i = 0; i < rangePoints.length; i += targetBucketSize) {
      const chunk = rangePoints.slice(i, i + targetBucketSize);
      const avgChunkAc = chunk.reduce((acc, p) => acc + (p.acPower || 0), 0) / chunk.length;
      const avgChunkDc = chunk.reduce((acc, p) => acc + (p.dcPower || 0), 0) / chunk.length;
      const mid = chunk[Math.floor(chunk.length / 2)];

      let displayTime = mid.time;
      let fullTimeLabel = mid.time;

      if (mid.timestamp) {
        const d = new Date(mid.timestamp);
        const dateStr = formatMonthDay(d);
        const timeStr = formatTimeOnly(d);

        if (timeRange === '24H') {
          displayTime = timeStr;
          fullTimeLabel = timeStr;
        } else {
          // 7D or 30D view: Date-oriented presentation labels
          fullTimeLabel = formatFullDateTime(d);

          if (dateStr !== lastDateStr) {
            dayCount++;
            if ((dayCount - 1) % dateLabelIntervalDays === 0) {
              displayTime = dateStr;
            } else {
              displayTime = '';
            }
            lastDateStr = dateStr;
          } else {
            displayTime = '';
          }
        }
      }

      displayData.push({
        displayTime,
        fullTimeLabel,
        acPower: parseFloat(avgChunkAc.toFixed(2)),
        dcPower: parseFloat(avgChunkDc.toFixed(2)),
      });
    }

    // Find display dots for peaks
    const peakAcPoint = displayData.find((p) => p.acPower === parseFloat(maxAc.toFixed(2))) || null;
    const peakDcPoint = displayData.find((p) => p.dcPower === parseFloat(maxDc.toFixed(2))) || null;

    return {
      displayData,
      peakAc: { val: parseFloat(maxAc.toFixed(2)), timeLabel: peakAcTimeLabel },
      peakDc: { val: parseFloat(maxDc.toFixed(2)), timeLabel: peakDcTimeLabel },
      avgAc: parseFloat(avgAc.toFixed(2)),
      avgDc: parseFloat(avgDc.toFixed(2)),
      peakAcPoint,
      peakDcPoint,
    };
  }, [data, timeRange]);

  // Dynamic Y-axis scale starting at 0 with 15% top padding
  const yMax = useMemo(() => {
    if (!data || data.length === 0) return 10;
    const highest = Math.max(processed.peakAc.val, processed.peakDc.val);
    return highest > 0 ? parseFloat((highest * 1.15).toFixed(1)) : 10;
  }, [data, processed]);

  return (
    <div className="bg-white rounded-xl p-4 border border-slate-200/90 shadow-xs space-y-4">
      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <div>
          <h3 className="text-base font-bold text-slate-900 tracking-tight">AC vs DC Power Generation</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            AC and DC power generation throughout the selected time period.
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap self-start sm:self-auto">
          {/* Time Range Selector */}
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg text-xs font-mono">
            {(['24H', '7D', '30D'] as const).map((range) => (
              <button
                key={range}
                type="button"
                onClick={() => setTimeRange(range)}
                className={`px-2.5 py-1 rounded font-bold transition ${
                  timeRange === range
                    ? 'bg-white text-slate-900 shadow-xs'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                {range}
              </button>
            ))}
          </div>

          {/* Legend */}
          <div className="flex items-center gap-3 text-xs font-mono font-medium border-l border-slate-200 pl-3">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#0284c7]" />
              <span className="text-slate-700">AC Power (MW)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#d97706]" />
              <span className="text-slate-700">DC Power (MW)</span>
            </div>
          </div>
        </div>
      </div>

      {/* KPI Summary Banner */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-sky-50/80 p-3 rounded-xl border border-sky-100">
          <div className="text-[10px] font-mono text-slate-500 uppercase font-bold">PEAK AC POWER</div>
          <div className="text-base font-bold font-mono text-sky-900 mt-0.5">
            {processed.peakAc.val} <span className="text-xs font-normal text-sky-700">MW</span>
          </div>
          {processed.peakAc.timeLabel && (
            <div className="text-[10px] font-mono text-sky-600 mt-0.5 truncate" title={processed.peakAc.timeLabel}>
              {processed.peakAc.timeLabel}
            </div>
          )}
        </div>

        <div className="bg-amber-50/80 p-3 rounded-xl border border-amber-100">
          <div className="text-[10px] font-mono text-slate-500 uppercase font-bold">PEAK DC POWER</div>
          <div className="text-base font-bold font-mono text-amber-900 mt-0.5">
            {processed.peakDc.val} <span className="text-xs font-normal text-amber-700">MW</span>
          </div>
          {processed.peakDc.timeLabel && (
            <div className="text-[10px] font-mono text-amber-600 mt-0.5 truncate" title={processed.peakDc.timeLabel}>
              {processed.peakDc.timeLabel}
            </div>
          )}
        </div>

        <div className="bg-slate-50 p-3 rounded-xl border border-slate-200">
          <div className="text-[10px] font-mono text-slate-500 uppercase font-bold">AVG AC POWER</div>
          <div className="text-base font-bold font-mono text-slate-800 mt-0.5">
            {processed.avgAc} <span className="text-xs font-normal text-slate-500">MW</span>
          </div>
          <div className="text-[10px] font-mono text-slate-400 mt-0.5">{timeRange} Mean</div>
        </div>

        <div className="bg-slate-50 p-3 rounded-xl border border-slate-200">
          <div className="text-[10px] font-mono text-slate-500 uppercase font-bold">AVG DC POWER</div>
          <div className="text-base font-bold font-mono text-slate-800 mt-0.5">
            {processed.avgDc} <span className="text-xs font-normal text-slate-500">MW</span>
          </div>
          <div className="text-[10px] font-mono text-slate-400 mt-0.5">{timeRange} Mean</div>
        </div>
      </div>

      {/* Chart Canvas */}
      <div className="h-64 w-full relative">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-50/60 backdrop-blur-xs rounded-lg">
            <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
              <Activity className="w-4 h-4 animate-spin text-sky-600" />
              Loading Telemetry Profile...
            </div>
          </div>
        ) : processed.displayData.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-slate-400 font-mono">
            No telemetry data available for selected time range
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={processed.displayData} margin={{ top: 15, right: 15, left: 0, bottom: 5 }}>
              <defs>
                <linearGradient id="colorAc" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#0284c7" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#0284c7" stopOpacity={0.05} />
                </linearGradient>
                <linearGradient id="colorDc" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#d97706" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#d97706" stopOpacity={0.02} />
                </linearGradient>
              </defs>

              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />

              <XAxis
                dataKey="displayTime"
                stroke="#94a3b8"
                fontSize={10}
                tickLine={false}
                minTickGap={25}
                interval="preserveStartEnd"
              />

              <YAxis
                stroke="#94a3b8"
                fontSize={10}
                tickLine={false}
                domain={[0, yMax]}
                tickFormatter={(val) => `${val} MW`}
              />

              <Tooltip content={<CustomTooltip />} />

              <Area
                type="monotone"
                dataKey="dcPower"
                stroke="#d97706"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#colorDc)"
                name="DC Power (MW)"
              />

              <Area
                type="monotone"
                dataKey="acPower"
                stroke="#0284c7"
                strokeWidth={2.5}
                fillOpacity={1}
                fill="url(#colorAc)"
                name="AC Power (MW)"
              />

              {/* Peak Highlights */}
              {processed.peakAcPoint && (
                <ReferenceDot
                  x={processed.peakAcPoint.displayTime}
                  y={processed.peakAcPoint.acPower}
                  r={5}
                  fill="#0284c7"
                  stroke="#ffffff"
                  strokeWidth={2}
                />
              )}
              {processed.peakDcPoint && (
                <ReferenceDot
                  x={processed.peakDcPoint.displayTime}
                  y={processed.peakDcPoint.dcPower}
                  r={5}
                  fill="#d97706"
                  stroke="#ffffff"
                  strokeWidth={2}
                />
              )}
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Footer SCADA Status Banner */}
      <div className="bg-slate-50 rounded-lg p-2.5 border border-slate-200/80 flex flex-col sm:flex-row sm:items-center justify-between text-xs font-mono text-slate-700 gap-2">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-amber-500 flex-shrink-0" />
          <span>
            <strong className="text-slate-900">Peak DC:</strong> {processed.peakDc.val} MW
          </span>
          <span className="text-slate-300">|</span>
          <span>
            <strong className="text-slate-900">Peak AC:</strong> {processed.peakAc.val} MW
          </span>
        </div>
        <div className="text-emerald-700 font-semibold bg-emerald-100/80 px-2 py-0.5 rounded text-[11px] self-start sm:self-auto">
          ● SCADA TELEMETRY ACTIVE ({timeRange})
        </div>
      </div>
    </div>
  );
};
