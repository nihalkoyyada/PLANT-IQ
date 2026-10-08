import React, { useEffect, useState } from 'react';
import { Calendar, RefreshCw, Download, Activity, Sun } from 'lucide-react';
import { MetricCard } from '../components/dashboard/MetricCard';
import { AnomalyBanner } from '../components/dashboard/AnomalyBanner';
import { GenerationChart, ChartPoint } from '../components/dashboard/GenerationChart';
import { PRHeatmap } from '../components/dashboard/PRHeatmap';
import { TopLosers } from '../components/dashboard/TopLosers';
import { Badge } from '../components/common/Badge';
import { getPlants } from '../api/plants';
import { getAssets } from '../api/assets';
import { getChannels } from '../api/channels';
import { getReadingAggregate, getLatestReading } from '../api/readings';
import { getEvents } from '../api/events';
import { getPRHeatmap, getTopLosers } from '../api/kpis';
import { Plant, PlantIQEvent, PRHeatmapResponse, LossAnalysisResponse } from '../types';

export const DashboardPage: React.FC<{ onNavigateTab?: (tab: string) => void }> = ({ onNavigateTab }) => {
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

  // Load telemetry & main dashboard assets
  useEffect(() => {
    async function loadDashboardData() {
      try {
        setLoading(true);
        const [plantsData, assetsData, channelsData, eventsData] = await Promise.all([
          getPlants(),
          getAssets(),
          getChannels(),
          getEvents().catch(() => []),
        ]);

        if (plantsData.length > 0) {
          setPlant(plantsData[0]);
        }
        setEventsList(eventsData);

        // 1. Determine inverter assets dynamically from API response
        const inverters = assetsData.filter(
          (a) => a.asset_type === 'inverter' || a.name.toLowerCase().includes('inverter')
        );
        setInverterCount(inverters.length);
        setChannelCount(channelsData.length);

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
          // 3. Dynamically determine plant-wide latest telemetry timestamp across ALL inverter AC/DC channels
          const latestResults = await Promise.all(
            allInverterChannels.map((c) => getLatestReading(c.id).catch(() => null))
          );

          let plantLatestMs = 0;
          latestResults.forEach((res) => {
            if (res && res.ts) {
              const ms = new Date(res.ts).getTime();
              if (!isNaN(ms) && ms > plantLatestMs) {
                plantLatestMs = ms;
              }
            }
          });

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

            const plantBucketMap = new Map<string, { acKw: number; dcKw: number }>();

            acAggResults.forEach((channelAgg) => {
              channelAgg.forEach((item) => {
                if (item.start && item.average_value !== null && item.average_value !== undefined) {
                  const existing = plantBucketMap.get(item.start) || { acKw: 0, dcKw: 0 };
                  existing.acKw += item.average_value;
                  plantBucketMap.set(item.start, existing);
                }
              });
            });

            dcAggResults.forEach((channelAgg) => {
              channelAgg.forEach((item) => {
                if (item.start && item.average_value !== null && item.average_value !== undefined) {
                  const existing = plantBucketMap.get(item.start) || { acKw: 0, dcKw: 0 };
                  existing.dcKw += item.average_value;
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

            setChartData(mapped);
          } else {
            setChartData([]);
          }
        } else {
          setChartData([]);
        }
      } catch (err) {
        console.error('Error loading dashboard data:', err);
        setChartData([]);
      } finally {
        setLoading(false);
      }
    }

    loadDashboardData();

    const handleIngested = () => {
      loadDashboardData();
    };

    window.addEventListener('plantiq:ingested', handleIngested);
    return () => {
      window.removeEventListener('plantiq:ingested', handleIngested);
    };
  }, []);

  // Fetch KPI & Loss Analysis data whenever plant or selectedRange changes
  useEffect(() => {
    async function loadKPIData() {
      try {
        setKpiLoading(true);
        const [heatmap, losers] = await Promise.all([
          getPRHeatmap(plant?.id, selectedRange).catch(() => null),
          getTopLosers(plant?.id, selectedRange).catch(() => null),
        ]);
        setPRHeatmapData(heatmap);
        setTopLosersData(losers);
      } catch (err) {
        console.error('Error loading KPI data:', err);
      } finally {
        setKpiLoading(false);
      }
    }
    loadKPIData();
  }, [plant, selectedRange]);

  const hasTelemetry = chartData.length > 0;
  const targetPRVal = plant?.expected_pr ? (plant.expected_pr * 100).toFixed(1) : '78.0';

  // Sum of hourly plant AC MW generation = total MWh energy over loaded period
  const totalMWh = chartData.reduce((acc, pt) => acc + (pt.acPower || 0), 0);

  // Actual PR calculated strictly from real telemetry/KPI engine
  const actualPRNumber: number | null =
    topLosersData?.plant_pr ??
    (topLosersData?.has_data && topLosersData.total_expected_mwh > 0
      ? (topLosersData.total_actual_mwh / topLosersData.total_expected_mwh) * 100
      : null);

  const hasActualPR = hasTelemetry && actualPRNumber !== null && actualPRNumber !== undefined;
  const displayPRValue = hasActualPR ? actualPRNumber.toFixed(1) : '--';

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
            <Badge variant={hasTelemetry ? 'emerald' : 'slate'}>
              {hasTelemetry ? '● LIVE TELEMETRY' : '● NO TELEMETRY LOADED'}
            </Badge>
          </div>
          <div className="flex items-center gap-2 text-xs font-mono text-slate-500 mt-1">
            <Calendar className="w-3.5 h-3.5 text-sky-600" />
            <span>{hasTelemetry ? 'Active Ingest Stream' : 'No dataset active'}</span>
            {hasTelemetry && <Badge variant="blue">DATABASE ACTIVE</Badge>}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right hidden sm:block font-mono">
            <div className={`text-xs font-bold ${hasTelemetry ? 'text-emerald-700' : 'text-slate-400'}`}>
              ● SYNC: {hasTelemetry ? 'NOMINAL' : 'EMPTY DATABASE'}
            </div>
            <div className="text-[10px] text-slate-400">
              {hasTelemetry
                ? `${inverterCount} inverters • ${channelCount} channels`
                : '0 inverters • 0 channels'}
            </div>
          </div>
          <button
            onClick={() => window.location.reload()}
            className="p-2 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600 transition"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button className="p-2 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-600 transition">
            <Download className="w-4 h-4" />
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
          value={hasTelemetry ? totalMWh.toFixed(1) : '0.0'}
          unit="MWh"
          change={hasTelemetry ? `${chartData.length} hours aggregate` : 'No telemetry'}
          isPositive={hasTelemetry}
          badgeText={hasTelemetry ? 'AGGREGATED' : 'EMPTY'}
          badgeVariant={hasTelemetry ? 'emerald' : 'blue'}
        />
        <MetricCard
          title="PR INDEX"
          value={displayPRValue}
          unit={hasActualPR ? '%' : ''}
          change={hasActualPR ? 'Actual PR' : 'No telemetry'}
          isPositive={hasActualPR ? actualPRNumber! >= parseFloat(targetPRVal) : false}
          subtitle={`Target PR: ${targetPRVal}%`}
          progress={hasActualPR ? actualPRNumber! : undefined}
        />
        <MetricCard
          title="ACTIVE INVERTERS"
          value={hasTelemetry ? inverterCount.toString() : '0'}
          unit="Nodes"
          change={hasTelemetry ? `${channelCount} channels` : 'No dataset'}
          isPositive={hasTelemetry}
          subtitle="Persisted Assets"
          icon={<Sun className="w-4 h-4" />}
        />
        <MetricCard
          title="TOTAL CHANNELS"
          value={hasTelemetry ? channelCount.toString() : '0'}
          unit="Channels"
          change={hasTelemetry ? 'Telemetry active' : 'No channels'}
          isPositive={hasTelemetry}
          badgeText={hasTelemetry ? '● ACTIVE' : '● INACTIVE'}
          badgeVariant={hasTelemetry ? 'emerald' : 'blue'}
        />
      </div>

      {/* Anomaly Alert Banner */}
      {hasTelemetry && <AnomalyBanner onTriage={() => onNavigateTab && onNavigateTab('quality')} />}

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
                              : ev.severity === 'warning'
                              ? 'amber'
                              : 'blue'
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
          <TopLosers data={topLosersData} loading={kpiLoading} />
          <PRHeatmap data={prHeatmapData} loading={kpiLoading} />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs">
            {chartData.length === 0 && !loading ? (
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
              />
            )}
          </div>
          <PRHeatmap data={prHeatmapData} loading={kpiLoading} />
        </div>
      )}
    </div>
  );
};
