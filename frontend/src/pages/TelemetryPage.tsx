import React, { useEffect, useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import {
  Activity,
  SlidersHorizontal,
  Table as TableIcon,
  CalendarDays,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';

import { Badge } from '../components/common/Badge';
import { getChannels } from '../api/channels';
import { getReadingAggregate } from '../api/readings';
import { Channel, ReadingAggregate } from '../types';

export const TelemetryPage: React.FC = () => {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string>('');

  const [interval, setInterval] = useState<
    '5min' | 'hour' | 'day' | 'week'
  >('hour');

  const [startDate, setStartDate] = useState<string>('2020-05-15');
  const [endDate, setEndDate] = useState<string>('2020-06-18');

  const [aggregateData, setAggregateData] = useState<ReadingAggregate[]>([]);

  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>('');

  const [appliedRange, setAppliedRange] = useState({
    start: '2020-05-15',
    end: '2020-06-18',
  });

  /*
   * Load channels
   */
  useEffect(() => {
    async function fetchChannels() {
      try {
        const chans = await getChannels();

        setChannels(chans);

        if (chans.length > 0) {
          setSelectedChannelId(chans[0].id);
        } else {
          setSelectedChannelId('');
        }
      } catch (err) {
        console.error('Failed to fetch channels:', err);
        setChannels([]);
        setSelectedChannelId('');
        setError('Unable to load telemetry channels.');
      }
    }

    fetchChannels();
  }, []);

  /*
   * Fetch telemetry whenever:
   * - channel changes
   * - interval changes
   * - applied date range changes
   */
  useEffect(() => {
    if (!selectedChannelId) {
      setAggregateData([]);
      return;
    }

    async function fetchAggregate() {
      try {
        setLoading(true);
        setError('');

        const start = `${appliedRange.start}T00:00:00Z`;
        const end = `${appliedRange.end}T23:59:59Z`;

        const data = await getReadingAggregate({
          channel_id: selectedChannelId,
          start,
          end,
          interval,
        });

        setAggregateData(data);
      } catch (err: any) {
        console.error('Error fetching telemetry aggregate:', err);

        setAggregateData([]);

        const apiMessage =
          err?.response?.data?.detail ||
          err?.message ||
          'Unable to load telemetry data.';

        setError(String(apiMessage));
      } finally {
        setLoading(false);
      }
    }

    fetchAggregate();
  }, [
    selectedChannelId,
    interval,
    appliedRange.start,
    appliedRange.end,
  ]);

  /*
   * Apply selected date range
   */
  const handleApplyRange = () => {
    if (!startDate || !endDate) {
      setError('Please select both start and end dates.');
      return;
    }

    if (startDate > endDate) {
      setError('Start date cannot be later than end date.');
      return;
    }

    setError('');

    setAppliedRange({
      start: startDate,
      end: endDate,
    });
  };

  /*
   * Reset date range
   */
  const handleResetRange = () => {
    const defaultStart = '2020-05-15';
    const defaultEnd = '2020-06-18';

    setStartDate(defaultStart);
    setEndDate(defaultEnd);

    setAppliedRange({
      start: defaultStart,
      end: defaultEnd,
    });

    setError('');
  };

  /*
   * Convert API data into chart-friendly data
   */
  const chartPoints = aggregateData.map((d) => ({
    time: new Date(d.start).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }),

    avg:
      d.average_value !== null
        ? parseFloat(d.average_value.toFixed(2))
        : null,

    min:
      d.minimum_value !== null
        ? parseFloat(d.minimum_value.toFixed(2))
        : null,

    max:
      d.maximum_value !== null
        ? parseFloat(d.maximum_value.toFixed(2))
        : null,
  }));

  /*
   * Currently selected channel
   */
  const selectedChannel = channels.find(
    (channel) => channel.id === selectedChannelId
  );

  return (
    <div className="space-y-4 pb-12">

      {/* ========================================================= */}
      {/* HEADER */}
      {/* ========================================================= */}

      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs">

        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">

          {/* Title */}
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-slate-900 tracking-tight">
                Telemetry Analytics
              </h1>

              <Badge variant={channels.length > 0 ? 'blue' : 'slate'}>
                {channels.length > 0
                  ? 'SCADA TIME-SERIES'
                  : 'NO CHANNELS'}
              </Badge>
            </div>

            <p className="text-xs text-slate-500 font-mono mt-0.5">
              Query time-bucketed telemetry readings across{' '}
              {channels.length} channels
            </p>
          </div>

          {/* Controls */}
          <div className="flex flex-wrap items-center gap-2 text-xs font-mono">

            {/* Channel */}
            <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-lg">

              <SlidersHorizontal className="w-3.5 h-3.5 text-slate-500 ml-1" />

              <select
                value={selectedChannelId}
                onChange={(e) =>
                  setSelectedChannelId(e.target.value)
                }
                disabled={channels.length === 0}
                className="bg-transparent font-semibold text-slate-800 focus:outline-none cursor-pointer disabled:opacity-50 max-w-[240px]"
              >
                {channels.length > 0 ? (
                  channels.map((channel) => (
                    <option
                      key={channel.id}
                      value={channel.id}
                    >
                      {channel.canonical_key} ({channel.source_name})
                    </option>
                  ))
                ) : (
                  <option value="">
                    No channels available
                  </option>
                )}
              </select>
            </div>

            {/* Interval */}
            <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg">

              {(['5min', 'hour', 'day', 'week'] as const).map(
                (inv) => (
                  <button
                    key={inv}
                    onClick={() => setInterval(inv)}
                    disabled={channels.length === 0}
                    className={`px-2.5 py-1 rounded text-xs uppercase transition ${interval === inv
                        ? 'bg-[#004874] text-white font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                      } disabled:opacity-50`}
                  >
                    {inv}
                  </button>
                )
              )}
            </div>
          </div>
        </div>

        {/* ======================================================= */}
        {/* DATE RANGE */}
        {/* ======================================================= */}

        <div className="mt-4 pt-4 border-t border-slate-100">

          <div className="flex flex-col lg:flex-row lg:items-end gap-3">

            {/* Start Date */}
            <div className="flex-1 min-w-[180px]">

              <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1.5">
                Start Date
              </label>

              <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">

                <CalendarDays className="w-4 h-4 text-slate-400" />

                <input
                  type="date"
                  value={startDate}
                  onChange={(e) =>
                    setStartDate(e.target.value)
                  }
                  className="w-full bg-transparent text-xs font-mono text-slate-700 focus:outline-none"
                />

              </div>
            </div>

            {/* End Date */}
            <div className="flex-1 min-w-[180px]">

              <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1.5">
                End Date
              </label>

              <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">

                <CalendarDays className="w-4 h-4 text-slate-400" />

                <input
                  type="date"
                  value={endDate}
                  onChange={(e) =>
                    setEndDate(e.target.value)
                  }
                  className="w-full bg-transparent text-xs font-mono text-slate-700 focus:outline-none"
                />

              </div>
            </div>

            {/* Apply */}
            <button
              onClick={handleApplyRange}
              disabled={loading || channels.length === 0}
              className="px-4 py-2 rounded-lg bg-[#004874] text-white text-xs font-mono font-bold hover:bg-[#003b60] transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'LOADING...' : 'APPLY RANGE'}
            </button>

            {/* Reset */}
            <button
              onClick={handleResetRange}
              disabled={loading || channels.length === 0}
              className="px-4 py-2 rounded-lg border border-slate-200 bg-white text-slate-600 text-xs font-mono font-bold hover:bg-slate-50 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              RESET
            </button>

          </div>

          {/* Current query */}
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] font-mono text-slate-400">

            <span>
              QUERY:
            </span>

            <span className="text-slate-600">
              {appliedRange.start} 00:00:00Z
            </span>

            <span>
              →
            </span>

            <span className="text-slate-600">
              {appliedRange.end} 23:59:59Z
            </span>

            {selectedChannel && (
              <>
                <span>•</span>

                <span className="text-slate-600">
                  {selectedChannel.canonical_key}
                </span>

                <span>•</span>

                <span className="text-slate-600 uppercase">
                  {interval}
                </span>
              </>
            )}

          </div>

        </div>
      </div>

      {/* ========================================================= */}
      {/* ERROR */}
      {/* ========================================================= */}

      {error && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 flex items-start gap-3">

          <AlertCircle className="w-4 h-4 text-rose-600 mt-0.5 shrink-0" />

          <div>
            <p className="text-xs font-mono font-bold text-rose-700">
              TELEMETRY QUERY ERROR
            </p>

            <p className="text-xs font-mono text-rose-600 mt-0.5">
              {error}
            </p>
          </div>

        </div>
      )}

      {/* ========================================================= */}
      {/* CHART */}
      {/* ========================================================= */}

      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-3">

        <div className="flex items-center justify-between border-b border-slate-100 pb-2">

          <h3 className="text-xs font-mono font-bold uppercase text-slate-700 tracking-wider">
            Aggregated Telemetry Curve ({interval} buckets)
          </h3>

          <span className="text-xs font-mono text-slate-400">
            {chartPoints.length} Data Points
          </span>

        </div>

        <div className="h-72 w-full relative">

          {loading ? (

            <div className="absolute inset-0 flex items-center justify-center bg-slate-50/60 rounded-lg">

              <div className="flex items-center gap-2 text-xs font-mono text-slate-500">

                <Activity className="w-4 h-4 animate-spin text-sky-600" />

                Querying Telemetry Readings...

              </div>

            </div>

          ) : chartPoints.length === 0 ? (

            <div className="absolute inset-0 flex flex-col items-center justify-center text-xs text-slate-400 font-mono">

              <Activity className="w-6 h-6 mb-2 text-slate-300" />

              <span>
                No telemetry data available
              </span>

              <span className="text-[10px] mt-1 text-slate-300">
                Try another date range or channel
              </span>

            </div>

          ) : (

            <ResponsiveContainer
              width="100%"
              height="100%"
            >

              <LineChart
                data={chartPoints}
                margin={{
                  top: 10,
                  right: 10,
                  left: -10,
                  bottom: 0,
                }}
              >

                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="#f1f5f9"
                  vertical={false}
                />

                <XAxis
                  dataKey="time"
                  stroke="#94a3b8"
                  fontSize={10}
                  tickLine={false}
                />

                <YAxis
                  stroke="#94a3b8"
                  fontSize={10}
                  tickLine={false}
                />

                <Tooltip
                  contentStyle={{
                    backgroundColor: '#004874',
                    borderColor: '#0284c7',
                    borderRadius: '8px',
                    color: '#ffffff',
                    fontSize: '11px',
                    fontFamily: 'monospace',
                  }}
                />

                <Line
                  type="monotone"
                  dataKey="avg"
                  stroke="#0284c7"
                  strokeWidth={2}
                  dot={false}
                  name="Average Value"
                />

                <Line
                  type="monotone"
                  dataKey="max"
                  stroke="#10b981"
                  strokeWidth={1}
                  strokeDasharray="2 2"
                  dot={false}
                  name="Max Value"
                />

                <Line
                  type="monotone"
                  dataKey="min"
                  stroke="#ef4444"
                  strokeWidth={1}
                  strokeDasharray="2 2"
                  dot={false}
                  name="Min Value"
                />

              </LineChart>

            </ResponsiveContainer>

          )}

        </div>
      </div>

      {/* ========================================================= */}
      {/* TABLE */}
      {/* ========================================================= */}

      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-3">

        <div className="flex items-center justify-between border-b border-slate-100 pb-2">

          <div className="flex items-center gap-2">

            <TableIcon className="w-4 h-4 text-slate-500" />

            <h3 className="text-xs font-mono font-bold uppercase text-slate-700 tracking-wider">
              Aggregated Telemetry Bucket Table
            </h3>

          </div>

          <span className="text-[10px] font-mono text-slate-400">
            Showing first {Math.min(10, aggregateData.length)} records
          </span>

        </div>

        <div className="overflow-x-auto">

          {aggregateData.length === 0 ? (

            <div className="p-6 text-center text-xs text-slate-400 font-mono">

              No bucketed readings available for selected channel and date range

            </div>

          ) : (

            <table className="w-full text-left text-xs font-mono">

              <thead>

                <tr className="border-b border-slate-200 bg-slate-50 text-[10px] uppercase text-slate-500 font-semibold">

                  <th className="py-2 px-3">
                    TIMESTAMP BUCKET
                  </th>

                  <th className="py-2 px-3">
                    READINGS COUNT
                  </th>

                  <th className="py-2 px-3">
                    AVERAGE VALUE
                  </th>

                  <th className="py-2 px-3">
                    MIN VALUE
                  </th>

                  <th className="py-2 px-3">
                    MAX VALUE
                  </th>

                </tr>

              </thead>

              <tbody className="divide-y divide-slate-100">

                {aggregateData
                  .slice(0, 10)
                  .map((row, idx) => (

                    <tr
                      key={`${row.start}-${idx}`}
                      className="hover:bg-slate-50"
                    >

                      <td className="py-2 px-3 font-semibold text-slate-800">
                        {new Date(
                          row.start
                        ).toLocaleString()}
                      </td>

                      <td className="py-2 px-3 text-slate-600">
                        {row.reading_count}
                      </td>

                      <td className="py-2 px-3 text-sky-700 font-bold">
                        {row.average_value !== null
                          ? row.average_value.toFixed(2)
                          : 'N/A'}
                      </td>

                      <td className="py-2 px-3 text-emerald-700">
                        {row.minimum_value !== null
                          ? row.minimum_value.toFixed(2)
                          : 'N/A'}
                      </td>

                      <td className="py-2 px-3 text-rose-700">
                        {row.maximum_value !== null
                          ? row.maximum_value.toFixed(2)
                          : 'N/A'}
                      </td>

                    </tr>

                  ))}

              </tbody>

            </table>

          )}

        </div>
      </div>

    </div>
  );
};