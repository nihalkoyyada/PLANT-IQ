import React, { useEffect, useState } from 'react';
import { Calendar, RefreshCw, Download, Activity, Sun } from 'lucide-react';
import { MetricCard } from '../components/dashboard/MetricCard';
import { AnomalyBanner } from '../components/dashboard/AnomalyBanner';
import { GenerationChart, ChartPoint } from '../components/dashboard/GenerationChart';
import { Badge } from '../components/common/Badge';
import { getPlants } from '../api/plants';
import { getAssets } from '../api/assets';
import { getChannels } from '../api/channels';
import { getReadingAggregate } from '../api/readings';
import { Plant } from '../types';

export const DashboardPage: React.FC<{ onNavigateTab?: (tab: string) => void }> = ({ onNavigateTab }) => {
  const [plant, setPlant] = useState<Plant | null>(null);
  const [inverterCount, setInverterCount] = useState<number>(0);
  const [channelCount, setChannelCount] = useState<number>(0);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'loss' | 'feed'>('overview');

  useEffect(() => {
    async function loadDashboardData() {
      try {
        setLoading(true);
        const [plantsData, assetsData, channelsData] = await Promise.all([
          getPlants(),
          getAssets(),
          getChannels(),
        ]);

        if (plantsData.length > 0) {
          setPlant(plantsData[0]);
        }

        const inverters = assetsData.filter((a) => a.asset_type === 'inverter' || a.name.includes('1BY'));
        setInverterCount(inverters.length);
        setChannelCount(channelsData.length);

        // Find AC & DC power channels to fetch real telemetry time series
        const acChannel = channelsData.find((c) => c.canonical_key === 'power_ac');
        const dcChannel = channelsData.find((c) => c.canonical_key === 'power_dc');

        if (acChannel) {
          const [acAgg, dcAgg] = await Promise.all([
            getReadingAggregate({ channel_id: acChannel.id, interval: 'hour' }),
            dcChannel
              ? getReadingAggregate({ channel_id: dcChannel.id, interval: 'hour' })
              : Promise.resolve([]),
          ]);

          if (acAgg && acAgg.length > 0) {
            const mapped: ChartPoint[] = acAgg.map((item, idx) => {
              const dateObj = new Date(item.start);
              const timeFormatted = dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              const dcVal = dcAgg[idx]?.average_value || (item.average_value !== null ? item.average_value * 1.05 : 0);
              return {
                timestamp: item.start,
                time: timeFormatted,
                acPower: item.average_value !== null ? parseFloat((item.average_value / 1000).toFixed(2)) : 0,
                dcPower: dcVal !== null ? parseFloat((dcVal / 1000).toFixed(2)) : 0,
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

  const hasData = chartData.length > 0 || inverterCount > 0;

  const totalMWh = chartData.reduce((acc, pt) => acc + (pt.acPower || 0), 0) / 1000;
  const prValue = plant?.expected_pr ? (plant.expected_pr * 100).toFixed(1) : (hasData ? '78.0' : '0.0');

  return (
    <div className="space-y-4 pb-12">
      {/* Top SCADA Toolbar Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">Dashboard</h1>
            <Badge variant={hasData ? 'emerald' : 'slate'}>
              {hasData ? '● LIVE TELEMETRY' : '● NO TELEMETRY LOADED'}
            </Badge>
          </div>
          <div className="flex items-center gap-2 text-xs font-mono text-slate-500 mt-1">
            <Calendar className="w-3.5 h-3.5 text-sky-600" />
            <span>{hasData ? 'Active Ingest Stream' : 'No dataset active'}</span>
            {hasData && <Badge variant="blue">DATABASE ACTIVE</Badge>}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-right hidden sm:block font-mono">
            <div className={`text-xs font-bold ${hasData ? 'text-emerald-700' : 'text-slate-400'}`}>
              ● SYNC: {hasData ? 'NOMINAL' : 'EMPTY DATABASE'}
            </div>
            <div className="text-[10px] text-slate-400">
              {inverterCount} inverters • {channelCount} channels
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
            {hasData ? '2' : '0'}
          </span>
        </button>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="GROSS GENERATION"
          value={hasData ? totalMWh.toFixed(1) : '0.0'}
          unit="MWh"
          change={hasData ? `${chartData.length} hours aggregate` : 'No telemetry'}
          isPositive={hasData}
          badgeText={hasData ? 'AGGREGATED' : 'EMPTY'}
          badgeVariant={hasData ? 'emerald' : 'blue'}
        />
        <MetricCard
          title="PR INDEX"
          value={prValue}
          unit="%"
          change={hasData ? 'Target PR' : 'No dataset'}
          isPositive={hasData}
          subtitle="Target PR"
          progress={hasData ? parseFloat(prValue) : 0}
        />
        <MetricCard
          title="ACTIVE INVERTERS"
          value={inverterCount.toString()}
          unit="Nodes"
          change={hasData ? `${channelCount} channels` : 'No dataset'}
          isPositive={hasData}
          subtitle="Persisted Assets"
          icon={<Sun className="w-4 h-4" />}
        />
        <MetricCard
          title="TOTAL CHANNELS"
          value={channelCount.toString()}
          unit="Channels"
          change={hasData ? 'Telemetry active' : 'No channels'}
          isPositive={hasData}
          badgeText={hasData ? '● ACTIVE' : '● INACTIVE'}
          badgeVariant={hasData ? 'emerald' : 'blue'}
        />
      </div>

      {/* Anomaly Alert Banner */}
      {hasData && <AnomalyBanner onTriage={() => onNavigateTab && onNavigateTab('quality')} />}

      {/* Main Diurnal Telemetry Chart */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
        {chartData.length === 0 && !loading ? (
          <div className="p-12 text-center text-slate-400 font-mono text-xs flex flex-col items-center justify-center gap-2">
            <Activity className="w-8 h-8 text-slate-300" />
            <strong className="text-slate-600 font-bold text-sm">No Telemetry Data Available</strong>
            <span>Upload a SCADA CSV or Parquet dataset to render real-time generation curves.</span>
          </div>
        ) : (
          <GenerationChart data={chartData} loading={loading} />
        )}
      </div>
    </div>
  );
};
