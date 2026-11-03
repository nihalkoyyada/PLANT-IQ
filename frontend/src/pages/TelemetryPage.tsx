import React, { useEffect, useState, useMemo, useRef } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import {
  Activity,
  SlidersHorizontal,
  Table as TableIcon,
  CalendarDays,
  RefreshCw,
  AlertCircle,
  Search,
  ChevronDown,
  Check,
  X,
  Download,
  Zap,
  Sun,
  Layers,
  Trash2,
} from 'lucide-react';

import { Badge } from '../components/common/Badge';
import { AssetTree } from '../components/telemetry/AssetTree';
import { getChannels } from '../api/channels';
import { getAssets } from '../api/assets';
import { getPlants } from '../api/plants';
import { getReadingAggregate } from '../api/readings';
import { Channel, Asset, Plant, ReadingAggregate } from '../types';
import { useActiveDatasets } from '../utils/activeDataset';

/* =========================================================
 * COLOR PALETTE & HELPER FUNCTIONS
 * ========================================================= */

const STROKE_COLORS = [
  '#0284c7', // Sky Blue
  '#10b981', // Emerald Green
  '#f59e0b', // Amber
  '#ef4444', // Rose Red
  '#8b5cf6', // Violet
  '#ec4899', // Pink
  '#14b8a6', // Teal
  '#f97316', // Orange
  '#3b82f6', // Blue
  '#6366f1', // Indigo
];

const getHumanMetricName = (canonicalKey: string, sourceName: string): string => {
  const key = (canonicalKey || '').toLowerCase();
  const src = (sourceName || '').toUpperCase();

  if (key === 'irradiance_poa' || key === 'irradiance' || src.includes('IRRADIANCE')) {
    return 'POA Irradiance';
  }
  if (key === 'temperature_ambient' || src.includes('AMBIENT')) {
    return 'Ambient Temp';
  }
  if (key === 'temperature_module' || src.includes('MODULE')) {
    return 'Module Temp';
  }
  if (key.includes('temp') || src.includes('TEMP')) {
    return 'Temperature';
  }
  if (key === 'power_ac' || src.includes('AC_POWER') || src.includes('AC POWER')) {
    return 'AC Power';
  }
  if (key === 'power_dc' || src.includes('DC_POWER') || src.includes('DC POWER')) {
    return 'DC Power';
  }
  if (
    key === 'energy_ac_daily' ||
    key === 'daily_yield' ||
    src.includes('DAILY_YIELD') ||
    src.includes('DAILY YIELD')
  ) {
    return 'Daily Energy';
  }
  if (
    key === 'energy_ac_total' ||
    key === 'total_yield' ||
    src.includes('TOTAL_YIELD') ||
    src.includes('TOTAL YIELD')
  ) {
    return 'Total Energy';
  }

  const raw = canonicalKey || sourceName || 'Signal';
  return raw
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
};

const getAssetNameForChannel = (channel: Channel, assetsList: Asset[]): string => {
  if (channel.asset_id) {
    const found = assetsList.find((a) => a.id === channel.asset_id);
    if (found && found.name) return found.name;
  }
  return 'Inverter';
};

/* =========================================================
 * MAIN TELEMETRY PAGE COMPONENT (S3-FS-02 UI-05 EXPLORER)
 * ========================================================= */

export const TelemetryPage: React.FC<{
  onAskCopilot?: (prompt: string, context?: any) => void;
}> = ({ onAskCopilot }) => {
  const { activeDatasets } = useActiveDatasets();
  const [plants, setPlants] = useState<Plant[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedChannelIds, setSelectedChannelIds] = useState<string[]>([]);

  const [interval, setInterval] = useState<'5min' | '15min' | 'hour' | 'day' | 'week'>('hour');

  const [startDate, setStartDate] = useState<string>('2020-05-15');
  const [endDate, setEndDate] = useState<string>('2020-06-18');

  // Channel ID -> ReadingAggregate[]
  const [channelDataMap, setChannelDataMap] = useState<Record<string, ReadingAggregate[]>>({});

  const [loading, setLoading] = useState<boolean>(false);
  const [initialLoading, setInitialLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');

  const [appliedRange, setAppliedRange] = useState({
    start: '2020-05-15',
    end: '2020-06-18',
  });

  const [activeTableChannelId, setActiveTableChannelId] = useState<string>('');

  /*
   * Scope detection based on selected datasets
   */
  const isWeatherOnly = useMemo(() => {
    return activeDatasets.length === 1 && activeDatasets[0].toLowerCase().includes('weather');
  }, [activeDatasets]);

  const isGenerationOnly = useMemo(() => {
    return activeDatasets.length === 1 && !activeDatasets[0].toLowerCase().includes('weather');
  }, [activeDatasets]);

  const isMerged = useMemo(() => {
    return activeDatasets.length > 1 || activeDatasets.length === 0;
  }, [activeDatasets]);

  /*
   * Fetch initial structure: Plants, Assets, Channels
   */
  useEffect(() => {
    async function fetchInitialData() {
      try {
        setInitialLoading(true);
        const [plantsList, chans, asts] = await Promise.all([
          getPlants().catch(() => [] as Plant[]),
          getChannels(),
          getAssets().catch(() => [] as Asset[]),
        ]);

        setPlants(plantsList);
        setChannels(chans);
        setAssets(asts);
      } catch (err) {
        console.error('Failed to fetch initial telemetry structure:', err);
        setPlants([]);
        setChannels([]);
        setAssets([]);
        setSelectedChannelIds([]);
        setError('Unable to load telemetry structure.');
      } finally {
        setInitialLoading(false);
      }
    }

    fetchInitialData();
  }, []);

  /*
   * Dynamically filter assets and channels based on active dataset selection
   */
  const filteredAssets = useMemo(() => {
    if (isWeatherOnly) {
      return assets.filter(
        (a) =>
          a.asset_type === 'weather_station' ||
          a.name === 'WS-01' ||
          a.name.toLowerCase().includes('weather')
      );
    }
    if (isGenerationOnly) {
      return assets.filter(
        (a) =>
          a.asset_type !== 'weather_station' &&
          a.name !== 'WS-01' &&
          !a.name.toLowerCase().includes('weather')
      );
    }
    // Merged: WS-01 sorted first, followed by inverters
    return [...assets].sort((a, b) => {
      if (a.name === 'WS-01' || a.asset_type === 'weather_station') return -1;
      if (b.name === 'WS-01' || b.asset_type === 'weather_station') return 1;
      return a.name.localeCompare(b.name);
    });
  }, [assets, isWeatherOnly, isGenerationOnly]);

  const filteredChannels = useMemo(() => {
    if (isWeatherOnly) {
      return channels.filter((c) => {
        const isWeatherKey =
          ['irradiance_poa', 'temperature_ambient', 'temperature_module'].includes(c.canonical_key) ||
          c.source_name.toLowerCase().includes('irradiance') ||
          c.source_name.toLowerCase().includes('temp');
        const parentAsset = assets.find((a) => a.id === c.asset_id);
        const isWeatherAsset =
          parentAsset?.name === 'WS-01' || parentAsset?.asset_type === 'weather_station';
        return isWeatherKey || isWeatherAsset;
      });
    }
    if (isGenerationOnly) {
      return channels.filter((c) => {
        const parentAsset = assets.find((a) => a.id === c.asset_id);
        const isWeatherAsset =
          parentAsset?.name === 'WS-01' || parentAsset?.asset_type === 'weather_station';
        const isWeatherKey =
          ['irradiance_poa', 'temperature_ambient', 'temperature_module'].includes(c.canonical_key);
        return !isWeatherAsset && !isWeatherKey;
      });
    }
    return channels;
  }, [channels, assets, isWeatherOnly, isGenerationOnly]);

  /*
   * Synchronize default channel selection when datasets or channels change
   */
  useEffect(() => {
    if (filteredChannels.length === 0) {
      setSelectedChannelIds([]);
      return;
    }

    // Check if currently selected channels are still valid within filteredChannels
    const validSelected = selectedChannelIds.filter((id) =>
      filteredChannels.some((c) => c.id === id)
    );

    if (validSelected.length > 0) {
      if (validSelected.length !== selectedChannelIds.length) {
        setSelectedChannelIds(validSelected);
      }
      return;
    }

    // Auto-select smart defaults based on active stream
    if (isWeatherOnly) {
      const irr = filteredChannels.find((c) => c.canonical_key === 'irradiance_poa');
      const amb = filteredChannels.find((c) => c.canonical_key === 'temperature_ambient');
      const defaults = [irr?.id, amb?.id].filter(Boolean) as string[];
      if (defaults.length > 0) {
        setSelectedChannelIds(defaults);
      } else {
        setSelectedChannelIds(filteredChannels.slice(0, 2).map((c) => c.id));
      }
    } else if (isGenerationOnly) {
      const powerChans = filteredChannels.filter(
        (c) => c.canonical_key === 'power_ac' || c.canonical_key === 'power_dc'
      );
      if (powerChans.length >= 2) {
        setSelectedChannelIds([powerChans[0].id, powerChans[1].id]);
      } else {
        setSelectedChannelIds(filteredChannels.slice(0, 2).map((c) => c.id));
      }
    } else {
      // Merged: Select Inverter 01 AC Power and WS-01 POA Irradiance for correlation
      const inv01Power = filteredChannels.find((c) => c.canonical_key === 'power_ac');
      const wsIrradiance = filteredChannels.find((c) => c.canonical_key === 'irradiance_poa');
      const defaults = [inv01Power?.id, wsIrradiance?.id].filter(Boolean) as string[];
      if (defaults.length >= 2) {
        setSelectedChannelIds(defaults);
      } else {
        setSelectedChannelIds(filteredChannels.slice(0, 2).map((c) => c.id));
      }
    }
  }, [filteredChannels, isWeatherOnly, isGenerationOnly]);

  /*
   * Map channels to detailed metadata for labels, units, and legend formatting
   */
  const channelInfoMap = useMemo(() => {
    const map: Record<
      string,
      {
        id: string;
        assetName: string;
        metricName: string;
        displayName: string;
        unit: string;
        canonicalKey: string;
        sourceName: string;
        color: string;
      }
    > = {};

    filteredChannels.forEach((ch, idx) => {
      const assetName = getAssetNameForChannel(ch, assets);
      const metricName = getHumanMetricName(ch.canonical_key, ch.source_name);
      let defaultUnit = metricName.includes('Energy') ? 'kWh' : 'kW';
      if (metricName.includes('Irradiance') || ch.canonical_key === 'irradiance_poa') {
        defaultUnit = 'kW/m²';
      } else if (metricName.includes('Temp') || ch.canonical_key.includes('temperature')) {
        defaultUnit = '°C';
      }
      const unit = ch.receive_unit || defaultUnit;

      map[ch.id] = {
        id: ch.id,
        assetName,
        metricName,
        displayName: `${assetName} — ${metricName}`,
        unit,
        canonicalKey: ch.canonical_key,
        sourceName: ch.source_name,
        color: STROKE_COLORS[idx % STROKE_COLORS.length],
      };
    });

    return map;
  }, [filteredChannels, assets]);

  /*
   * List of currently selected channel objects
   */
  const selectedChannelsInfo = useMemo(() => {
    return selectedChannelIds
      .map((id, idx) => {
        const info = channelInfoMap[id];
        if (!info) return null;
        return {
          ...info,
          color: STROKE_COLORS[idx % STROKE_COLORS.length],
        };
      })
      .filter(Boolean) as Array<{
      id: string;
      assetName: string;
      metricName: string;
      displayName: string;
      unit: string;
      canonicalKey: string;
      sourceName: string;
      color: string;
    }>;
  }, [selectedChannelIds, channelInfoMap]);

  /*
   * Fetch aggregate data in parallel for ALL selected channels whenever selected channels, interval, or date range changes
   */
  useEffect(() => {
    if (selectedChannelIds.length === 0) {
      setChannelDataMap({});
      return;
    }

    async function fetchAllAggregates() {
      try {
        setLoading(true);
        setError('');

        const start = `${appliedRange.start}T00:00:00Z`;
        const end = `${appliedRange.end}T23:59:59Z`;

        const results = await Promise.all(
          selectedChannelIds.map(async (channelId) => {
            try {
              const data = await getReadingAggregate({
                channel_id: channelId,
                start,
                end,
                interval,
              });
              return { channelId, data };
            } catch (err) {
              console.warn(`Error fetching aggregate for channel ${channelId}:`, err);
              return { channelId, data: [] };
            }
          })
        );

        const newMap: Record<string, ReadingAggregate[]> = {};
        results.forEach(({ channelId, data }) => {
          newMap[channelId] = data;
        });

        setChannelDataMap(newMap);
      } catch (err: any) {
        console.error('Error fetching telemetry aggregates:', err);
        setChannelDataMap({});
        setError('Unable to load telemetry data for selected channels.');
      } finally {
        setLoading(false);
      }
    }

    fetchAllAggregates();
  }, [selectedChannelIds, interval, appliedRange.start, appliedRange.end]);

  /*
   * TIMESTAMP ALIGNMENT LOGIC (Crucial S3-FS-02 Requirement)
   * Builds timestamp-keyed map combining values from all selected channels without assuming array index ordering.
   */
  const alignedChartPoints = useMemo(() => {
    if (selectedChannelIds.length === 0) return [];

    const timestampMap = new Map<string, Record<string, any>>();

    selectedChannelIds.forEach((channelId) => {
      const readings = channelDataMap[channelId] || [];
      readings.forEach((r) => {
        const rawTs = r.start;
        if (!timestampMap.has(rawTs)) {
          timestampMap.set(rawTs, {
            rawTimestamp: rawTs,
            time: new Date(rawTs).toLocaleString([], {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            }),
          });
        }

        const entry = timestampMap.get(rawTs)!;
        entry[channelId] = r.average_value !== null ? parseFloat(r.average_value.toFixed(2)) : null;
        entry[`${channelId}_min`] = r.minimum_value !== null ? parseFloat(r.minimum_value.toFixed(2)) : null;
        entry[`${channelId}_max`] = r.maximum_value !== null ? parseFloat(r.maximum_value.toFixed(2)) : null;
        entry[`${channelId}_count`] = r.reading_count;
      });
    });

    return Array.from(timestampMap.values()).sort(
      (a, b) => new Date(a.rawTimestamp).getTime() - new Date(b.rawTimestamp).getTime()
    );
  }, [selectedChannelIds, channelDataMap]);

  /*
   * Handle single channel toggle
   */
  const handleToggleChannel = (channelId: string) => {
    setSelectedChannelIds((prev) => {
      if (prev.includes(channelId)) {
        return prev.filter((id) => id !== channelId);
      }
      return [...prev, channelId];
    });
  };

  /*
   * Handle batch selection/deselection
   */
  const handleSelectChannels = (channelIds: string[], select: boolean) => {
    setSelectedChannelIds((prev) => {
      const set = new Set(prev);
      channelIds.forEach((id) => {
        if (select) {
          set.add(id);
        } else {
          set.delete(id);
        }
      });
      return Array.from(set);
    });
  };

  /*
   * Clear all selected channels
   */
  const handleClearAll = () => {
    setSelectedChannelIds([]);
  };

  /*
   * Apply date range
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
    setAppliedRange({ start: startDate, end: endDate });
  };

  /*
   * Reset date range
   */
  const handleResetRange = () => {
    const defaultStart = '2020-05-15';
    const defaultEnd = '2020-06-18';
    setStartDate(defaultStart);
    setEndDate(defaultEnd);
    setAppliedRange({ start: defaultStart, end: defaultEnd });
    setError('');
  };

  /*
   * CSV EXPORT FUNCTIONALITY (Step 7 Requirement)
   * Builds timestamp-aligned CSV file and triggers browser download.
   */
  const handleExportCSV = () => {
    if (alignedChartPoints.length === 0 || selectedChannelsInfo.length === 0) {
      alert('No telemetry data available to export.');
      return;
    }

    // Build CSV Headers: Timestamp, Inverter 01 — AC Power (kW), Inverter 01 — DC Power (kW)...
    const activeSourcesInfo = activeDatasets.length > 0 ? activeDatasets.join('; ') : 'Surya-A-demo.csv';
    const metadataComment = `# PlantIQ Telemetry Export - Active Datasets: ${activeSourcesInfo}\n# Date Range: ${appliedRange.start} to ${appliedRange.end}\n`;
    const headers = [
      'Timestamp',
      ...selectedChannelsInfo.map((info) => `"${info.displayName} (${info.unit})"`),
    ];

    const rows = alignedChartPoints.map((pt) => {
      const tsFormatted = `"${pt.rawTimestamp}"`;
      const values = selectedChannelsInfo.map((info) => {
        const val = pt[info.id];
        return val !== undefined && val !== null ? val : '';
      });
      return [tsFormatted, ...values].join(',');
    });

    const csvContent = metadataComment + [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute(
      'download',
      `PlantIQ_Telemetry_${appliedRange.start}_to_${appliedRange.end}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Determine Y-Axis Label
  const yAxisLabel = useMemo(() => {
    if (selectedChannelsInfo.length === 0) return 'Value';
    const units = new Set(selectedChannelsInfo.map((i) => i.unit));
    if (units.size === 1) {
      const unit = Array.from(units)[0];
      return unit === 'kW'
        ? 'Power (kW)'
        : unit === 'kWh'
        ? 'Energy (kWh)'
        : unit === 'kW/m²'
        ? 'POA Irradiance (kW/m²)'
        : unit === '°C'
        ? 'Temperature (°C)'
        : `Value (${unit})`;
    }
    return 'Value';
  }, [selectedChannelsInfo]);

  // Determine active channel for table view
  const primaryTableChannel = useMemo(() => {
    if (activeTableChannelId && selectedChannelIds.includes(activeTableChannelId)) {
      return selectedChannelsInfo.find((i) => i.id === activeTableChannelId) || selectedChannelsInfo[0];
    }
    return selectedChannelsInfo[0] || null;
  }, [activeTableChannelId, selectedChannelIds, selectedChannelsInfo]);

  const activeTableReadings = useMemo(() => {
    if (!primaryTableChannel) return [];
    return channelDataMap[primaryTableChannel.id] || [];
  }, [primaryTableChannel, channelDataMap]);

  return (
    <div className="space-y-4 pb-12 font-mono">
      {/* ========================================================= */}
      {/* HEADER TOOLBAR */}
      {/* ========================================================= */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold text-slate-900 tracking-tight font-sans">
                Telemetry Analytics Explorer
              </h1>
              {isWeatherOnly ? (
                <Badge variant="amber">WEATHER STREAM (WS-01)</Badge>
              ) : isGenerationOnly ? (
                <Badge variant="blue">GENERATION STREAM</Badge>
              ) : (
                <Badge variant="emerald">
                  MERGED ({activeDatasets.length > 0 ? `${activeDatasets.length} DATASETS` : 'MULTI-DATASET'})
                </Badge>
              )}
              <Badge variant={selectedChannelIds.length > 0 ? 'emerald' : 'slate'}>
                {selectedChannelIds.length > 0 ? `${selectedChannelIds.length} ACTIVE CHANNELS` : 'NO SELECTION'}
              </Badge>
              <div
                id="telemetry-active-datasets-pill"
                className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-100 border border-slate-200 text-xs font-mono text-slate-700"
                title="Active dataset source feeding telemetry readings"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <span className="font-semibold text-slate-500">FEED:</span>
                <span className="text-slate-800 font-medium">
                  {activeDatasets.length > 0 ? activeDatasets.join(', ') : 'Surya-A-demo.csv'}
                </span>
              </div>
            </div>
            <p className="text-xs text-slate-500 font-mono mt-0.5">
              Multi-channel time series telemetry curves with timestamp alignment
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs font-mono">
            {/* Resolution Selector */}
            <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg">
              {(['5min', '15min', 'hour', 'day', 'week'] as const).map((inv) => (
                <button
                  key={inv}
                  onClick={() => setInterval(inv)}
                  className={`px-2.5 py-1 rounded text-xs uppercase transition ${
                    interval === inv
                      ? 'bg-[#004874] text-white font-bold'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {inv}
                </button>
              ))}
            </div>

            {/* CSV Export Button */}
            <button
              onClick={handleExportCSV}
              disabled={alignedChartPoints.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-xs transition disabled:opacity-50 disabled:cursor-not-allowed shadow-xs"
            >
              <Download className="w-3.5 h-3.5" />
              <span>EXPORT CSV</span>
            </button>
          </div>
        </div>

        {/* Date Range Section */}
        <div className="mt-4 pt-4 border-t border-slate-100">
          <div className="flex flex-col lg:flex-row lg:items-end gap-3">
            <div className="flex-1 min-w-[160px]">
              <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">
                Start Date
              </label>
              <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5">
                <CalendarDays className="w-3.5 h-3.5 text-slate-400" />
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full bg-transparent text-xs font-mono text-slate-700 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex-1 min-w-[160px]">
              <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">
                End Date
              </label>
              <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5">
                <CalendarDays className="w-3.5 h-3.5 text-slate-400" />
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full bg-transparent text-xs font-mono text-slate-700 focus:outline-none"
                />
              </div>
            </div>

            <button
              onClick={handleApplyRange}
              disabled={loading}
              className="px-4 py-2 rounded-lg bg-[#004874] text-white text-xs font-mono font-bold hover:bg-[#003b60] transition disabled:opacity-50"
            >
              {loading ? 'LOADING...' : 'APPLY RANGE'}
            </button>

            <button
              onClick={handleResetRange}
              disabled={loading}
              className="px-4 py-2 rounded-lg border border-slate-200 bg-white text-slate-600 text-xs font-mono font-bold hover:bg-slate-50 transition flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              RESET
            </button>
          </div>
        </div>
      </div>

      {/* ERROR BANNER */}
      {error && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 flex items-start gap-3">
          <AlertCircle className="w-4 h-4 text-rose-600 mt-0.5 shrink-0" />
          <div>
            <p className="text-xs font-mono font-bold text-rose-700">TELEMETRY QUERY ERROR</p>
            <p className="text-xs font-mono text-rose-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* MAIN WORKSPACE GRID: ASSET TREE + CHART/TABLE */}
      {/* ========================================================= */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* LEFT COLUMN: ASSET TREE */}
        <div className="lg:col-span-4 xl:col-span-3">
          <AssetTree
            plants={plants}
            assets={filteredAssets}
            channels={filteredChannels}
            selectedChannelIds={selectedChannelIds}
            onToggleChannel={handleToggleChannel}
            onSelectChannels={handleSelectChannels}
            loading={initialLoading}
            error={null}
          />
        </div>

        {/* RIGHT COLUMN: MULTI-CHANNEL CHART & TABLE */}
        <div className="lg:col-span-8 xl:col-span-9 space-y-4">
          {/* Selected Channel Tags Bar */}
          <div className="bg-white p-3 rounded-xl border border-slate-200/90 shadow-xs space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-sky-600" />
                Selected Telemetry Series ({selectedChannelsInfo.length})
              </span>
              {selectedChannelsInfo.length > 0 && (
                <button
                  onClick={handleClearAll}
                  className="text-[11px] text-rose-600 hover:text-rose-800 font-semibold flex items-center gap-1"
                >
                  <Trash2 className="w-3 h-3" />
                  Clear All
                </button>
              )}
            </div>

            {selectedChannelsInfo.length === 0 ? (
              <div className="text-xs text-slate-400 italic py-1">
                No channels selected. Expand the Asset Hierarchy on the left to select signals.
              </div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {selectedChannelsInfo.map((info) => (
                  <div
                    key={info.id}
                    className="inline-flex items-center gap-1.5 bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-lg text-xs"
                  >
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: info.color }}
                    />
                    <span className="font-semibold text-slate-800">{info.displayName}</span>
                    <span className="text-[10px] text-slate-400 font-mono">({info.unit})</span>
                    <button
                      onClick={() => handleToggleChannel(info.id)}
                      className="text-slate-400 hover:text-rose-600 ml-1"
                      title="Remove series"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* MULTI-CHANNEL CHART CARD */}
          <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
            <div className="border-b border-slate-100 pb-2 flex items-center justify-between">
              <div>
                <h3 className="text-xs font-mono font-bold uppercase text-slate-800 tracking-wider flex items-center gap-2">
                  <Activity className="w-4 h-4 text-sky-600" />
                  <span>
                    {selectedChannelsInfo.length > 0
                      ? `Multi-Channel Curve Explorer (${selectedChannelsInfo.length} Series)`
                      : 'Telemetry Explorer'}
                  </span>
                </h3>
                <p className="text-[11px] text-slate-500 font-mono mt-0.5">
                  Synchronized aggregate curves grouped by exact timestamp
                </p>
              </div>

              <span className="text-xs font-mono text-slate-500 font-semibold">
                {alignedChartPoints.length} Timestamps
              </span>
            </div>

            <div className="h-80 w-full relative pt-2">
              {loading ? (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-50/70 rounded-lg z-10">
                  <div className="flex items-center gap-2 text-xs font-mono text-slate-600">
                    <Activity className="w-5 h-5 animate-spin text-sky-600" />
                    Querying Telemetry Readings...
                  </div>
                </div>
              ) : selectedChannelIds.length === 0 ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-xs text-slate-400 font-mono">
                  <SlidersHorizontal className="w-8 h-8 mb-2 text-slate-300" />
                  <strong className="text-slate-600 font-bold text-sm">No Channel Selected</strong>
                  <span>Select one or more channels from the Asset Tree to explore telemetry.</span>
                </div>
              ) : alignedChartPoints.length === 0 ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-xs text-slate-400 font-mono">
                  <Activity className="w-8 h-8 mb-2 text-slate-300" />
                  <strong className="text-slate-600 font-bold text-sm">No Telemetry Data Available</strong>
                  <span>No telemetry readings available for the selected channels and date range.</span>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={alignedChartPoints}
                    margin={{
                      top: 10,
                      right: 15,
                      left: 15,
                      bottom: 25,
                    }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis
                      dataKey="time"
                      stroke="#94a3b8"
                      fontSize={10}
                      tickLine={false}
                      label={{
                        value: 'Time',
                        position: 'insideBottom',
                        offset: -15,
                        fontSize: 10,
                        fill: '#64748b',
                        fontWeight: 'bold',
                      }}
                    />
                    <YAxis
                      stroke="#94a3b8"
                      fontSize={10}
                      tickLine={false}
                      label={{
                        value: yAxisLabel,
                        angle: -90,
                        position: 'insideLeft',
                        offset: 0,
                        fontSize: 10,
                        fill: '#64748b',
                        fontWeight: 'bold',
                      }}
                    />
                    <Tooltip
                      content={({ active, payload, label }) => {
                        if (!active || !payload || !payload.length) return null;
                        const pt = payload[0].payload;
                        return (
                          <div className="bg-[#004874] border border-[#0284c7] text-white p-3 rounded-xl shadow-xl text-xs font-mono space-y-1.5 min-w-[220px]">
                            <div className="font-bold border-b border-sky-600/60 pb-1 text-sky-200">
                              {pt.time}
                            </div>
                            <div className="space-y-1">
                              {selectedChannelsInfo.map((info) => {
                                const val = pt[info.id];
                                if (val === undefined || val === null) return null;
                                return (
                                  <div
                                    key={info.id}
                                    className="flex items-center justify-between gap-3 text-[11px]"
                                  >
                                    <span className="flex items-center gap-1.5 truncate">
                                      <span
                                        className="w-2 h-2 rounded-full shrink-0"
                                        style={{ backgroundColor: info.color }}
                                      />
                                      <span className="truncate">{info.displayName}</span>
                                    </span>
                                    <span className="font-bold text-emerald-300 whitespace-nowrap">
                                      {val.toLocaleString()} {info.unit}
                                    </span>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        );
                      }}
                    />
                    <Legend
                      verticalAlign="top"
                      height={36}
                      formatter={(value, entry) => (
                        <span className="text-xs font-mono text-slate-700 font-semibold mr-3">
                          {value}
                        </span>
                      )}
                    />
                    {selectedChannelsInfo.map((info) => (
                      <Line
                        key={info.id}
                        type="monotone"
                        dataKey={info.id}
                        name={info.displayName}
                        stroke={info.color}
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 5 }}
                        connectNulls={false}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* TELEMETRY READINGS TABLE */}
          <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
            <div className="flex items-center justify-between border-b border-slate-100 pb-2">
              <div className="flex items-center gap-2">
                <TableIcon className="w-4 h-4 text-slate-500" />
                <h3 className="text-xs font-mono font-bold uppercase text-slate-700 tracking-wider">
                  Readings Table — {primaryTableChannel?.displayName || 'Primary Channel'}
                </h3>
              </div>

              {selectedChannelsInfo.length > 1 && (
                <div className="flex items-center gap-1 text-xs">
                  <span className="text-[10px] text-slate-400">View Channel:</span>
                  <select
                    value={primaryTableChannel?.id || ''}
                    onChange={(e) => setActiveTableChannelId(e.target.value)}
                    className="bg-slate-50 border border-slate-200 rounded px-2 py-0.5 text-xs text-slate-700"
                  >
                    {selectedChannelsInfo.map((info) => (
                      <option key={info.id} value={info.id}>
                        {info.displayName}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div className="overflow-x-auto">
              {activeTableReadings.length === 0 ? (
                <div className="p-6 text-center text-xs text-slate-400 font-mono">
                  No readings available for selected channel and date range
                </div>
              ) : (
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-[10px] uppercase text-slate-500 font-semibold">
                      <th className="py-2 px-3">TIME</th>
                      <th className="py-2 px-3">READINGS</th>
                      <th className="py-2 px-3">
                        AVERAGE {primaryTableChannel?.metricName.toUpperCase()}
                      </th>
                      <th className="py-2 px-3">
                        LOWEST {primaryTableChannel?.metricName.toUpperCase()}
                      </th>
                      <th className="py-2 px-3">
                        HIGHEST {primaryTableChannel?.metricName.toUpperCase()}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {activeTableReadings.slice(0, 15).map((row, idx) => (
                      <tr key={`${row.start}-${idx}`} className="hover:bg-slate-50">
                        <td className="py-2 px-3 font-semibold text-slate-800">
                          {new Date(row.start).toLocaleString()}
                        </td>
                        <td className="py-2 px-3 text-slate-600">{row.reading_count}</td>
                        <td className="py-2 px-3 text-sky-700 font-bold">
                          {row.average_value !== null
                            ? `${row.average_value.toFixed(2)} ${primaryTableChannel?.unit}`
                            : 'N/A'}
                        </td>
                        <td className="py-2 px-3 text-emerald-700">
                          {row.minimum_value !== null
                            ? `${row.minimum_value.toFixed(2)} ${primaryTableChannel?.unit}`
                            : 'N/A'}
                        </td>
                        <td className="py-2 px-3 text-rose-700">
                          {row.maximum_value !== null
                            ? `${row.maximum_value.toFixed(2)} ${primaryTableChannel?.unit}`
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
      </div>
    </div>
  );
};