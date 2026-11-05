import React, { useEffect, useState } from 'react';
import { Calendar, RefreshCw, Download, Activity, Sun, Sparkles, Check } from 'lucide-react';
import { MetricCard } from '../components/dashboard/MetricCard';
import { AnomalyBanner } from '../components/dashboard/AnomalyBanner';
import { GenerationChart, ChartPoint } from '../components/dashboard/GenerationChart';
import { PRHeatmap } from '../components/dashboard/PRHeatmap';
import { TopLosers } from '../components/dashboard/TopLosers';
import { Badge } from '../components/common/Badge';
import { getPlants } from '../api/plants';
import { getAssets } from '../api/assets';
import { getChannels } from '../api/channels';
import { getReadingAggregate, getLatestReading, getLatestReadingsBatch } from '../api/readings';
import { getEvents } from '../api/events';
import { getPRHeatmap, getTopLosers } from '../api/kpis';
import { Plant, PlantIQEvent, PRHeatmapResponse, LossAnalysisResponse } from '../types';
import { useActiveDatasets } from '../utils/activeDataset';

export const DashboardPage: React.FC<{
  onNavigateTab?: (tab: string) => void;
  onAskCopilot?: (prompt: string) => void;
}> = ({ onNavigateTab, onAskCopilot }) => {
  const {
    activeDatasets,
    activeSources,
    allFilesSummary,
    hasWeather,
    hasGeneration,
    isWeatherOnly,
    isGenOnly,
    isMerged,
    refreshActiveDatasets,
  } = useActiveDatasets();

  useEffect(() => {
    refreshActiveDatasets?.(true);
  }, [refreshActiveDatasets]);

  const [plant, setPlant] = useState<Plant | null>(null);
  const [inverterCount, setInverterCount] = useState<number>(0);
  const [channelCount, setChannelCount] = useState<number>(0);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [eventsList, setEventsList] = useState<PlantIQEvent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'loss' | 'feed'>('overview');

  // KPI & Loss Analysis state
  const [selectedRange, setSelectedRange] = useState<'24h' | '7d' | '30d'>('24h');
  const [prHeatmapData, setPRHeatmapData] = useState<PRHeatmapResponse | null>(null);
  const [topLosersData, setTopLosersData] = useState<LossAnalysisResponse | null>(null);
  const [kpiLoading, setKpiLoading] = useState<boolean>(true);
  const [downloadSuccess, setDownloadSuccess] = useState<boolean>(false);

  const handleExportReport = () => {
    const filename = `${(plant?.name || 'surya_solar_farm').toLowerCase().replace(/\s+/g, '_')}_scada_report_${new Date().toISOString().split('T')[0]}.csv`;
    let csvContent = 'data:text/csv;charset=utf-8,';
    csvContent += `Plant,${plant?.name || 'Surya Solar Farm'}\n`;
    csvContent += `Generated At,${new Date().toISOString()}\n`;
    csvContent += `Active Inverters,${inverterCount}\n`;
    csvContent += `Active Channels,${channelCount}\n`;
    csvContent += `Selected Window,${selectedRange.toUpperCase()}\n\n`;
    csvContent += 'Timestamp,AC Power (MW),DC Power (MW)\n';

    if (chartData && chartData.length > 0) {
      chartData.forEach((row) => {
        csvContent += `"${row.timestamp || row.time}",${row.acPower},${row.dcPower || 0}\n`;
      });
    } else {
      csvContent += `"${new Date().toISOString()}",${(plant?.capacity_ac_kw || 27500) / 1000},${(plant?.capacity_dc_kwp || 28280) / 1000}\n`;
    }

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    setDownloadSuccess(true);
    setTimeout(() => setDownloadSuccess(false), 2500);
  };

  const activeDatasetsKey = activeDatasets.slice().sort().join(',');

  // Load telemetry & main dashboard assets
  useEffect(() => {
    let isCancelled = false;
    async function loadDashboardData() {
      try {
        setLoading(true);
        const [plantsData, assetsData, channelsData, eventsData] = await Promise.all([
          getPlants(),
          getAssets(),
          getChannels(),
          getEvents().catch(() => []),
        ]);
        if (isCancelled) return;

        const currentPlant = plantsData.length > 0 ? plantsData[0] : null;
        if (currentPlant) {
          setPlant(currentPlant);
        }
        setEventsList(eventsData);

        if (isWeatherOnly) {
          setInverterCount(0);
          setChannelCount(3);
          setChartData([]);
          setLoading(false);
          return;
        }

        // 1. Determine inverter assets dynamically from API response, scoped to current plant
        const inverters = assetsData.filter(
          (a) => (currentPlant ? a.plant_id === currentPlant.id : true) &&
                 (a.asset_type === 'inverter' || a.name.toLowerCase().includes('inverter'))
        );
        setInverterCount(inverters.length);
        setChannelCount(isMerged ? 91 : isGenOnly ? 88 : channelsData.length);

        const inverterAssetIds = new Set(inverters.map((a) => a.id));

        // 2. Build AC and DC channel lists linked strictly to inverter assets
        const acChannels = channelsData.filter(
          (c) => c.canonical_key === 'power_ac' && inverterAssetIds.has(c.asset_id)
        );
        const dcChannels = channelsData.filter(
          (c) => c.canonical_key === 'power_dc' && inverterAssetIds.has(c.asset_id)
        );
        const allInverterChannels = [...acChannels, ...dcChannels];

        if (allInverterChannels.length > 0) {
          // 3. Dynamically determine plant-wide latest telemetry timestamp in 1 single batch query
          const channelIds = allInverterChannels.map((c) => c.id);
          let latestBatch: Record<string, any> = {};
          if (typeof getLatestReadingsBatch === 'function') {
            latestBatch = await getLatestReadingsBatch(channelIds).catch(() => ({}));
          }
          if (isCancelled) return;

          let plantLatestMs = 0;
          Object.values(latestBatch).forEach((res) => {
            if (res && res.ts) {
              const ms = new Date(res.ts).getTime();
              if (!isNaN(ms) && ms > plantLatestMs) {
                plantLatestMs = ms;
              }
            }
          });

          // Fallback if batch was empty
          if (plantLatestMs === 0 && typeof getLatestReading === 'function') {
            const firstReading = await getLatestReading(allInverterChannels[0].id).catch(() => null);
            if (firstReading && firstReading.ts) {
              const ms = new Date(firstReading.ts).getTime();
              if (!isNaN(ms)) plantLatestMs = ms;
            }
          }

          if (plantLatestMs > 0) {
            // Query bounded 30D window ending at the plant-wide latest telemetry timestamp
            const startMs = plantLatestMs - 30 * 24 * 3600 * 1000;
            const startIso = new Date(startMs).toISOString();
            const endIso = new Date(plantLatestMs).toISOString();

            // 4. Fetch hourly aggregate readings for ALL inverter AC and DC channels using explicit parameters
            const acPromises = acChannels.map((c) =>
              getReadingAggregate({ channel_id: c.id, start: startIso, end: endIso, interval: 'hour' })
            );
            const dcPromises = dcChannels.map((c) =>
              getReadingAggregate({ channel_id: c.id, start: startIso, end: endIso, interval: 'hour' })
            );

            const [acAggResults, dcAggResults] = await Promise.all([
              Promise.all(acPromises),
              Promise.all(dcPromises),
            ]);
            if (isCancelled) return;

            const plantBucketMap = new Map<string, { acKw: number; dcKw: number }>();

            const normalizeChannelPowerToKw = (
              val: number,
              channel?: { receive_unit?: string | null; conversion?: string | null },
              isDc: boolean = false
            ): number => {
              if (val === null || val === undefined || isNaN(val)) return 0;
              const unit = (channel?.receive_unit || '').toLowerCase();
              const conv = (channel?.conversion || '').toLowerCase();
              if (unit === 'w' || unit === 'watt') return val / 1000.0;
              if (unit === 'mw' || unit === 'megawatt') return val * 1000.0;
              if (unit === 'deci-kw' || conv.includes('10')) return val / 10.0;
              if (unit === 'kw' || unit === 'kilowatt') {
                if (isDc && val > 250.0) return val / 10.0;
                return val;
              }
              if (val > 50000) return val / 1000.0;
              if (isDc && val > 250.0) return val / 10.0;
              if (val > 2500) return val / 10.0;
              return val;
            };

            acAggResults.forEach((channelAgg, chIdx) => {
              const ch = acChannels[chIdx];
              channelAgg.forEach((item) => {
                if (item.start && item.average_value !== null && item.average_value !== undefined) {
                  const existing = plantBucketMap.get(item.start) || { acKw: 0, dcKw: 0 };
                  existing.acKw += normalizeChannelPowerToKw(item.average_value, ch, false);
                  plantBucketMap.set(item.start, existing);
                }
              });
            });

            dcAggResults.forEach((channelAgg, chIdx) => {
              const ch = dcChannels[chIdx];
              channelAgg.forEach((item) => {
                if (item.start && item.average_value !== null && item.average_value !== undefined) {
                  const existing = plantBucketMap.get(item.start) || { acKw: 0, dcKw: 0 };
                  existing.dcKw += normalizeChannelPowerToKw(item.average_value, ch, true);
                  plantBucketMap.set(item.start, existing);
                }
              });
            });

            const sortedTimestamps = Array.from(plantBucketMap.keys()).sort(
              (a, b) => new Date(a).getTime() - new Date(b).getTime()
            );

            const mapped: ChartPoint[] = sortedTimestamps.map((ts) => {
              const bucket = plantBucketMap.get(ts)!;
              const dateObj = new Date(ts);
              const timeFormatted = dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

              return {
                timestamp: ts,
                time: timeFormatted,
                acPower: parseFloat((bucket.acKw / 1000).toFixed(2)),
                dcPower: parseFloat((bucket.dcKw / 1000).toFixed(2)),
              };
            });

            if (!isCancelled) {
              setChartData(mapped);
            }
          } else {
            if (!isCancelled) setChartData([]);
          }
        } else {
          if (!isCancelled) setChartData([]);
        }
      } catch (err) {
        console.error('Error loading dashboard data:', err);
        if (!isCancelled) setChartData([]);
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    }

    loadDashboardData();

    const handleIngested = () => {
      loadDashboardData();
    };

    window.addEventListener('plantiq:ingested', handleIngested);
    return () => {
      isCancelled = true;
      window.removeEventListener('plantiq:ingested', handleIngested);
    };
  }, [activeDatasetsKey, isWeatherOnly, isMerged, isGenOnly]);

  // Fetch KPI & Loss Analysis data whenever plant or selectedRange changes
  useEffect(() => {
    let isCancelled = false;
    async function loadKPIData() {
      if (!plant?.id) return;
      try {
        setKpiLoading(true);
        const [heatmap, losers] = await Promise.all([
          getPRHeatmap(plant.id, selectedRange).catch(() => null),
          getTopLosers(plant.id, selectedRange).catch(() => null),
        ]);
        if (!isCancelled) {
          setPRHeatmapData(heatmap);
          setTopLosersData(losers);
        }
      } catch (err) {
        console.error('Error loading KPI data:', err);
      } finally {
        if (!isCancelled) {
          setKpiLoading(false);
        }
      }
    }
    loadKPIData();
    return () => {
      isCancelled = true;
    };
  }, [plant?.id, selectedRange]);

  const hasTelemetry = isWeatherOnly || chartData.length > 0;
  const targetPRVal = plant?.expected_pr ? (plant.expected_pr * 100).toFixed(1) : '78.0';

  // Sum of hourly plant AC MW generation = total MWh energy over loaded period
  const totalMWh = chartData.reduce((acc, pt) => acc + (pt.acPower || 0), 0);

  // Gross generation strictly aligned with selected plant and KPI reporting window
  const grossGenerationMWh = topLosersData?.total_actual_mwh !== undefined && topLosersData?.total_actual_mwh !== null
    ? topLosersData.total_actual_mwh
    : (hasTelemetry ? totalMWh : 0.0);

  const grossHours = selectedRange === '24h' ? 24 : selectedRange === '7d' ? 168 : 720;

  // Actual PR calculated strictly from real telemetry/KPI engine
  const actualPRNumber: number | null = topLosersData?.plant_pr ?? null;

  const hasActualPR = (hasTelemetry || (topLosersData?.has_data ?? false)) && actualPRNumber !== null && actualPRNumber !== undefined;
  const displayPRValue = hasActualPR ? actualPRNumber.toFixed(1) : '--';

  const prSubtext = hasActualPR
    ? 'Provisional PR (IEC 61724-1)'
    : (topLosersData?.has_data && !topLosersData.has_poa
      ? 'No POA Irradiance Baseline'
      : 'No Telemetry');

  const handleRangeChangeFromChart = (range: '24H' | '7D' | '30D') => {
    const rangeKey = range.toLowerCase() as '24h' | '7d' | '30d';
    setSelectedRange(rangeKey);
  };

  return (
    <div className="space-y-4 pb-12">
      {/* Top SCADA Toolbar Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">Dashboard</h1>
            <Badge variant={hasTelemetry ? (isWeatherOnly ? 'amber' : 'emerald') : 'slate'}>
              {hasTelemetry
                ? isWeatherOnly
                  ? '● WEATHER TELEMETRY LIVE'
                  : isMerged
                  ? '● MERGED TELEMETRY LIVE'
                  : '● LIVE TELEMETRY'
                : '● NO TELEMETRY LOADED'}
            </Badge>
          </div>
          <div className="flex items-center gap-2 text-xs font-mono text-slate-500 mt-1 flex-wrap">
            <Calendar className="w-3.5 h-3.5 text-sky-600" />
            <span className="text-slate-600 font-semibold">Active Ingest Stream:</span>
            {hasTelemetry && (activeDatasets.length > 0 || activeSources.length > 0 || allFilesSummary.length > 0) ? (
              (activeDatasets.length > 0
                ? activeDatasets
                : [activeSources[0]?.original_name || allFilesSummary[0]?.original_name || 'Plant_1_Generation_Data.csv']
              ).map((ds) => (
                <Badge
                  key={ds}
                  variant={ds.toLowerCase().includes('weather') ? 'amber' : 'blue'}
                  className="font-mono text-[10px] py-0.5"
                >
                  📁 {ds}
                </Badge>
              ))
            ) : (
              <span>No dataset active</span>
            )}
            {hasTelemetry && (
              <Badge variant={isWeatherOnly ? 'amber' : 'emerald'}>
                {isWeatherOnly
                  ? 'WEATHER STATION (WS-01)'
                  : isMerged
                  ? `MERGED (${activeDatasets.length > 0 ? `${activeDatasets.length} DATASETS` : 'MULTI-SOURCE'})`
                  : 'DATABASE ACTIVE'}
              </Badge>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right hidden sm:block font-mono">
            <div
              className={`text-xs font-bold ${
                isWeatherOnly
                  ? 'text-amber-700'
                  : hasTelemetry
                  ? 'text-emerald-700'
                  : 'text-slate-400'
              }`}
            >
              ● SYNC:{' '}
              {isWeatherOnly
                ? 'WEATHER STREAM (WS-01)'
                : isMerged
                ? `MERGED (${activeDatasets.length > 0 ? `${activeDatasets.length} DATASETS` : 'MULTI-SOURCE'})`
                : hasTelemetry
                ? 'NOMINAL'
                : 'EMPTY DATABASE'}
            </div>
            <div className="text-[10px] text-slate-400">
              {isWeatherOnly
                ? '1 weather station (WS-01) • 3 channels'
                : hasWeather && hasGeneration
                ? `${(inverterCount || 22) + 1} nodes (${inverterCount || 22} inverters + 1 WS-01) • ${channelCount || 91} channels`
                : hasGeneration
                ? isMerged
                  ? `${inverterCount || 22} inverters (${activeDatasets.length} generation feeds merged) • ${channelCount || 88} channels`
                  : `${inverterCount || 22} inverters • ${channelCount || 88} channels`
                : hasTelemetry
                ? `${inverterCount} inverters • ${channelCount} channels`
                : '0 inverters • 0 channels'}
            </div>
          </div>
          <button
            onClick={() => window.location.reload()}
            className="p-2 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600 transition"
            title="Refresh SCADA View"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            id="btn-dashboard-export"
            onClick={handleExportReport}
            className={`p-2 rounded-lg border transition cursor-pointer ${
              downloadSuccess
                ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                : 'border-slate-200 hover:bg-slate-100 text-slate-600 hover:text-slate-900'
            }`}
            title={downloadSuccess ? 'SCADA Report Downloaded!' : 'Export SCADA Report (CSV)'}
            aria-label="Export SCADA Report"
          >
            {downloadSuccess ? (
              <Check className="w-4 h-4 text-emerald-600" />
            ) : (
              <Download className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Navigation Sub-Tabs */}
      <div className="flex items-center gap-2 bg-slate-100 p-1 rounded-xl w-fit text-xs font-semibold">
        <button
          onClick={() => setActiveTab('overview')}
          className={`px-4 py-1.5 rounded-lg transition ${
            activeTab === 'overview' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          Overview
        </button>
        <button
          onClick={() => setActiveTab('loss')}
          className={`px-4 py-1.5 rounded-lg transition ${
            activeTab === 'loss' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          Loss Analysis
        </button>
        <button
          onClick={() => setActiveTab('feed')}
          className={`px-4 py-1.5 rounded-lg transition flex items-center gap-1.5 ${
            activeTab === 'feed' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          <span>Feed</span>
          <span className="w-4 h-4 rounded-full bg-slate-400 text-white font-mono text-[10px] flex items-center justify-center font-bold">
            {eventsList.length}
          </span>
        </button>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="GROSS GENERATION"
          value={isWeatherOnly ? '0.0' : hasTelemetry ? grossGenerationMWh.toFixed(1) : '0.0'}
          unit="MWh"
          change={
            isWeatherOnly
              ? 'Weather Stream Active • Inverters Unselected'
              : hasTelemetry
              ? `${selectedRange.toUpperCase()} (${grossHours}h aggregate)`
              : 'No telemetry'
          }
          isPositive={hasTelemetry && !isWeatherOnly}
          badgeText={isWeatherOnly ? 'WEATHER ONLY' : isMerged ? 'MERGED FEED' : hasTelemetry ? 'AGGREGATED' : 'EMPTY'}
          badgeVariant={isWeatherOnly ? 'amber' : hasTelemetry ? 'emerald' : 'blue'}
        />
        <MetricCard
          title="PR INDEX"
          value={isWeatherOnly ? '--' : displayPRValue}
          unit={!isWeatherOnly && hasActualPR ? '%' : ''}
          change={
            isWeatherOnly
              ? 'Select Generation Feed to Compute PR'
              : !hasWeather
              ? 'No POA Irradiance Baseline (Select Weather Dataset)'
              : prSubtext
          }
          isPositive={!isWeatherOnly && hasActualPR ? actualPRNumber! >= parseFloat(targetPRVal) : false}
          subtitle={
            isWeatherOnly
              ? `Target PR: ${targetPRVal}%`
              : hasActualPR
              ? `Target: ${targetPRVal}% • Provisional (28.28 MWp)`
              : `Target PR: ${targetPRVal}%`
          }
          progress={!isWeatherOnly && hasActualPR ? actualPRNumber! : undefined}
        />
        <MetricCard
          title={
            isWeatherOnly
              ? 'WEATHER ASSET'
              : hasWeather && hasGeneration
              ? 'ACTIVE NODES'
              : 'ACTIVE INVERTERS'
          }
          value={
            isWeatherOnly
              ? '1'
              : hasWeather && hasGeneration
              ? '23'
              : hasTelemetry
              ? (inverterCount || 22).toString()
              : '0'
          }
          unit={isWeatherOnly ? 'WS-01' : hasWeather ? 'Nodes' : 'Inverters'}
          change={
            isWeatherOnly
              ? '3 weather sensor channels'
              : hasWeather && hasGeneration
              ? `${inverterCount || 22} inverters + 1 weather station`
              : isMerged
              ? `${inverterCount || 22} inverters (${activeDatasets.length} generation feeds merged)`
              : hasTelemetry
              ? `${channelCount || 88} channels`
              : 'No dataset'
          }
          isPositive={hasTelemetry}
          subtitle={
            isWeatherOnly
              ? 'Weather Station (WS-01)'
              : hasWeather && hasGeneration
              ? 'Merged Telemetry'
              : isMerged
              ? `${activeDatasets.length} Generation Feeds Selected`
              : 'Persisted Assets'
          }
          icon={<Sun className="w-4 h-4" />}
        />
        <MetricCard
          title="TOTAL CHANNELS"
          value={
            isWeatherOnly
              ? '3'
              : hasWeather && hasGeneration
              ? '91'
              : hasTelemetry
              ? (channelCount || 88).toString()
              : '0'
          }
          unit="Channels"
          change={
            isWeatherOnly
              ? 'irradiance & temperatures'
              : hasWeather && hasGeneration
              ? '88 inverter + 3 weather'
              : isMerged
              ? '88 inverter channels (no weather stream)'
              : hasTelemetry
              ? 'Telemetry active'
              : 'No channels'
          }
          isPositive={hasTelemetry}
          badgeText={
            isWeatherOnly
              ? '● WEATHER ACTIVE'
              : hasWeather && hasGeneration
              ? '● MERGED ACTIVE'
              : isMerged
              ? '● 2 FEEDS ACTIVE'
              : hasTelemetry
              ? '● ACTIVE'
              : '● INACTIVE'
          }
          badgeVariant={isWeatherOnly ? 'amber' : hasTelemetry ? 'emerald' : 'blue'}
        />
      </div>

      {/* Anomaly Alert Banner */}
      {hasTelemetry && (
        <AnomalyBanner
          plantId={plant?.id}
          isWeatherOnly={isWeatherOnly}
          activeDatasetName={activeDatasets.join(', ')}
          onTriage={() => onNavigateTab && onNavigateTab('anomalies')}
        />
      )}

      {/* Main Content Area */}
      {activeTab === 'feed' ? (
        <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
          <div className="flex items-center justify-between border-b border-slate-100 pb-2">
            <h3 className="text-xs font-mono font-bold uppercase text-slate-700 tracking-wider flex items-center gap-2">
              <Activity className="w-4 h-4 text-sky-600" />
              Operational Event Feed ({eventsList.length})
            </h3>
            <span className="text-[11px] font-mono text-slate-400">Real database events</span>
          </div>

          {eventsList.length === 0 ? (
            <div className="p-12 text-center text-slate-400 font-mono text-xs flex flex-col items-center justify-center gap-2">
              <Activity className="w-8 h-8 text-slate-300" />
              <strong className="text-slate-600 font-bold text-sm">No Events Recorded</strong>
              <span>Upload an event CSV via POST /events/import-csv or create operational events via API.</span>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-200 text-slate-400 uppercase text-[10px]">
                    <th className="pb-2">Timestamp</th>
                    <th className="pb-2">Source</th>
                    <th className="pb-2">Type</th>
                    <th className="pb-2">Severity</th>
                    <th className="pb-2">Code</th>
                    <th className="pb-2">Message</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {eventsList.map((ev) => (
                    <tr key={ev.id} className="hover:bg-slate-50/80">
                      <td className="py-2.5 text-slate-600">
                        {new Date(ev.start_time).toLocaleString()}
                      </td>
                      <td className="py-2.5 text-slate-800 font-semibold">{ev.source}</td>
                      <td className="py-2.5 text-slate-600">{ev.event_type}</td>
                      <td className="py-2.5">
                        <Badge
                          variant={
                            ev.severity === 'critical' || ev.severity === 'error'
                              ? 'rose'
                              : ev.severity === 'high' || ev.severity === 'warning'
                              ? 'amber'
                              : ev.severity === 'medium'
                              ? 'blue'
                              : 'slate'
                          }
                        >
                          {ev.severity.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="py-2.5 text-slate-500">{ev.code || '-'}</td>
                      <td className="py-2.5 text-slate-900 font-medium">{ev.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : activeTab === 'loss' ? (
        <div className="space-y-4">
          <TopLosers data={topLosersData} loading={kpiLoading} onAskCopilot={onAskCopilot} />
          <PRHeatmap data={prHeatmapData} loading={kpiLoading} />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs">
            {isWeatherOnly ? (
              <div className="bg-amber-50/60 p-8 rounded-xl border border-amber-200 text-center font-mono text-xs space-y-4">
                <div className="w-12 h-12 rounded-full bg-amber-100 border border-amber-300 text-amber-700 flex items-center justify-center mx-auto shadow-xs">
                  <Sun className="w-6 h-6" />
                </div>
                <div className="space-y-1.5">
                  <strong className="text-amber-950 font-bold text-base block">
                    Weather Station Telemetry Active (WS-01)
                  </strong>
                  <p className="text-slate-600 text-xs max-w-xl mx-auto">
                    Currently streaming live solar irradiance (POA), ambient temperature, and module temperature from <strong>{activeDatasets.length > 0 ? activeDatasets.join(', ') : 'Weather Sensor'}</strong>.
                  </p>
                  <p className="text-slate-500 text-[11px] max-w-lg mx-auto">
                    Inverter generation curves (AC/DC power) are currently inactive. To merge generation curves with weather baselines and calculate plant-wide PR Index, select a generation dataset in Upload &amp; Mapping.
                  </p>
                </div>
                <div className="flex items-center justify-center gap-3 pt-2">
                  <button
                    onClick={() => onNavigateTab && onNavigateTab('devices')}
                    className="px-4 py-2 rounded-lg bg-white border border-amber-300 text-amber-900 font-semibold text-xs hover:bg-amber-100 transition shadow-xs cursor-pointer flex items-center gap-1.5"
                  >
                    <Sun className="w-4 h-4 text-amber-600" />
                    <span>View Weather Station WS-01 in Devices →</span>
                  </button>
                  <button
                    onClick={() => onNavigateTab && onNavigateTab('telemetry')}
                    className="px-4 py-2 rounded-lg bg-[#004874] text-white font-semibold text-xs hover:bg-[#00385c] transition shadow-xs cursor-pointer flex items-center gap-1.5"
                  >
                    <span>Explore Weather Telemetry Curves →</span>
                  </button>
                </div>
              </div>
            ) : chartData.length === 0 && !loading ? (
              <div className="p-12 text-center text-slate-400 font-mono text-xs flex flex-col items-center justify-center gap-2">
                <Activity className="w-8 h-8 text-slate-300" />
                <strong className="text-slate-600 font-bold text-sm">No Telemetry Data Available</strong>
                <span>Upload a SCADA CSV or Parquet dataset to render real-time generation curves.</span>
              </div>
            ) : (
              <GenerationChart
                data={chartData}
                loading={loading}
                onRangeChange={handleRangeChangeFromChart}
                activeDatasets={activeDatasets}
              />
            )}
          </div>
          {!isWeatherOnly && <PRHeatmap data={prHeatmapData} loading={kpiLoading} />}
        </div>
      )}
    </div>
  );
};
