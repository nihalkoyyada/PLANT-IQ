import React, { useEffect, useState, useMemo } from 'react';
import {
  Sun,
  MapPin,
  Clock,
  ChevronDown,
  Layers,
  Zap,
  ShieldCheck,
  Building2,
  CloudSun,
  Leaf,
  Activity,
  ArrowUpRight,
} from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { getPlants } from '../api/plants';
import { getAssets } from '../api/assets';
import { getChannels } from '../api/channels';
import { Asset, Channel, Plant } from '../types';
import { useActiveDatasets } from '../utils/activeDataset';

interface PlantsPageProps {
  onNavigateTab?: (tab: string) => void;
}

export const PlantsPage: React.FC<PlantsPageProps> = ({ onNavigateTab }) => {
  const { activeDatasets } = useActiveDatasets();
  const isWeatherOnly =
    activeDatasets.length === 1 && activeDatasets[0].toLowerCase().includes('weather');
  const isGenOnly =
    activeDatasets.length === 1 && !activeDatasets[0].toLowerCase().includes('weather');
  const isMerged = activeDatasets.length > 1;

  const [plants, setPlants] = useState<Plant[]>([]);
  const [selectedPlantId, setSelectedPlantId] = useState<string | null>(null);
  const [allAssets, setAllAssets] = useState<Asset[]>([]);
  const [allChannels, setAllChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    async function loadPlantData() {
      try {
        setLoading(true);
        const [plantsData, assetsData, channelsData] = await Promise.all([
          getPlants(),
          getAssets(),
          getChannels(),
        ]);

        setPlants(plantsData);
        setAllAssets(assetsData);
        setAllChannels(channelsData);

        if (plantsData.length > 0) {
          const targetPlant =
            plantsData.find((p) => assetsData.some((a) => a.plant_id === p.id)) ||
            plantsData[0];
          setSelectedPlantId(targetPlant.id);
        } else {
          setSelectedPlantId(null);
        }
      } catch (err) {
        console.error('Error loading plant infrastructure:', err);
      } finally {
        setLoading(false);
      }
    }

    loadPlantData();
  }, []);

  const currentPlant = plants.find((p) => p.id === selectedPlantId) || plants[0] || null;

  const plantAssets = useMemo(() => {
    return currentPlant ? allAssets.filter((a) => a.plant_id === currentPlant.id) : [];
  }, [currentPlant, allAssets]);

  const plantAssetIds = useMemo(() => {
    return new Set(plantAssets.map((a) => a.id));
  }, [plantAssets]);

  const inverters = useMemo(() => {
    return plantAssets.filter(
      (a) =>
        a.asset_type?.toLowerCase() === 'inverter' ||
        a.name.startsWith('INV-') ||
        a.name.includes('1BY')
    );
  }, [plantAssets]);

  const weatherStations = useMemo(() => {
    return plantAssets.filter(
      (a) =>
        a.asset_type?.toLowerCase() === 'weather_station' ||
        a.name.toLowerCase().startsWith('ws-') ||
        a.name.toLowerCase().includes('weather')
    );
  }, [plantAssets]);

  const plantChannels = useMemo(() => {
    return allChannels.filter((c) => plantAssetIds.has(c.asset_id));
  }, [allChannels, plantAssetIds]);

  const inverterCount = inverters.length;
  const channelCount = plantChannels.length;

  // Accurate channel classification
  const channelBreakdown = useMemo(() => {
    const acPower = plantChannels.filter((c) => c.canonical_key === 'power_ac');
    const dcPower = plantChannels.filter((c) => c.canonical_key === 'power_dc');
    const dailyYield = plantChannels.filter((c) =>
      ['energy_ac_daily', 'daily_yield'].includes(c.canonical_key)
    );
    const totalYield = plantChannels.filter((c) =>
      ['energy_ac_total', 'total_yield'].includes(c.canonical_key)
    );
    const weatherChannels = plantChannels.filter((c) =>
      [
        'irradiance_poa',
        'temperature_ambient',
        'temperature_module',
        'ambient_temperature',
        'module_temperature',
      ].includes(c.canonical_key)
    );

    return {
      acPowerCount: acPower.length,
      dcPowerCount: dcPower.length,
      dailyYieldCount: dailyYield.length,
      totalYieldCount: totalYield.length,
      weatherCount: weatherChannels.length,
    };
  }, [plantChannels]);

  const activeInverterCount = isWeatherOnly ? 0 : inverters.length;
  const activeChannelCount = isWeatherOnly
    ? channelBreakdown.weatherCount
    : isGenOnly
    ? channelBreakdown.acPowerCount +
      channelBreakdown.dcPowerCount +
      channelBreakdown.dailyYieldCount +
      channelBreakdown.totalYieldCount
    : channelCount;

  const acCapacityMw = currentPlant?.capacity_ac_kw
    ? (currentPlant.capacity_ac_kw / 1000).toFixed(1)
    : '27.5';
  const dcCapacityMwp = currentPlant?.capacity_dc_kwp
    ? (currentPlant.capacity_dc_kwp / 1000).toFixed(1)
    : '28.3';
  const dcAcRatio =
    currentPlant?.capacity_ac_kw && currentPlant?.capacity_dc_kwp
      ? (currentPlant.capacity_dc_kwp / currentPlant.capacity_ac_kw).toFixed(2)
      : '1.03';

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-[#004874] text-white flex items-center justify-center font-bold shadow-md flex-shrink-0">
            <Sun className="w-6 h-6 text-amber-400" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              {plants.length > 1 ? (
                <div className="relative inline-block">
                  <select
                    value={selectedPlantId || ''}
                    onChange={(e) => setSelectedPlantId(e.target.value)}
                    aria-label="Select Solar Plant"
                    className="text-xl font-bold text-slate-900 tracking-tight bg-slate-50 border border-slate-200 rounded-lg px-3 py-1 pr-8 appearance-none cursor-pointer focus:outline-hidden focus:ring-2 focus:ring-sky-500"
                  >
                    {plants.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="w-4 h-4 text-slate-500 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              ) : (
                <h1 className="text-xl font-bold text-slate-900 tracking-tight">
                  {currentPlant ? currentPlant.name : 'Surya Solar Farm'}
                </h1>
              )}

              <Badge
                variant={
                  isWeatherOnly
                    ? 'amber'
                    : isGenOnly
                    ? 'blue'
                    : inverterCount > 0
                    ? 'emerald'
                    : 'slate'
                }
              >
                {isWeatherOnly
                  ? '● WEATHER TELEMETRY ACTIVE (WS-01)'
                  : isGenOnly
                  ? `● GENERATION ACTIVE (${inverterCount} INVERTERS)`
                  : inverterCount > 0
                  ? `● OPERATIONAL (${inverterCount + weatherStations.length} NODES MERGED)`
                  : '● IDLE'}
              </Badge>
              <Badge variant="navy">
                {`${acCapacityMw} MW AC / ${dcCapacityMwp} MWp DC`}
              </Badge>
              {activeDatasets.length > 0 && (
                <div
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-100 border border-slate-200 text-xs font-mono text-slate-700"
                  title="Active dataset source feeding SCADA channels"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="font-semibold text-slate-500">FEED:</span>
                  <span className="text-slate-800 font-medium">
                    {activeDatasets.join(', ')}
                  </span>
                </div>
              )}
            </div>
            <p className="text-xs text-slate-500 font-mono mt-1 flex items-center gap-2 flex-wrap">
              <MapPin className="w-3.5 h-3.5 text-slate-400" />
              <span>
                {currentPlant?.latitude && currentPlant?.longitude
                  ? `Rajasthan, India (${currentPlant.latitude.toFixed(2)}° N, ${currentPlant.longitude.toFixed(2)}° E)`
                  : 'Rajasthan, India (27.54° N, 71.92° E)'}
              </span>
              <span className="text-slate-300">|</span>
              <Clock className="w-3.5 h-3.5 text-slate-400" />
              <span>{currentPlant?.timezone || 'Asia/Kolkata'}</span>
              <span className="text-slate-300">|</span>
              <span className="text-slate-500 font-sans font-medium">Type: Utility-Scale Solar PV</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Badge variant="blue">SCADA NODE PRIMARY</Badge>
          {onNavigateTab && (
            <button
              onClick={() => onNavigateTab('dashboard')}
              className="text-xs font-semibold px-3 py-1.5 bg-[#004874] hover:bg-[#00385c] text-white rounded-lg transition flex items-center gap-1.5 shadow-2xs cursor-pointer"
            >
              <span>View Dashboard</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Plant Specification Overview (3 Cards) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Capacity Details */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">
              CAPACITY DETAILS
            </span>
            <Zap className="w-4 h-4 text-amber-500" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-slate-900 font-mono">
              {acCapacityMw}
            </span>
            <span className="text-xs font-mono text-slate-500 font-bold">MW AC Rated</span>
          </div>
          <div className="text-xs text-slate-600 font-mono space-y-1.5 border-t border-slate-100 pt-3">
            <div className="flex justify-between">
              <span className="text-slate-500">Peak DC Nameplate:</span>
              <strong className="text-slate-800">{dcCapacityMwp} MWp</strong>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Inverter Loading Ratio (ILR):</span>
              <strong className="text-slate-800">{dcAcRatio}x</strong>
            </div>
          </div>
        </div>

        {/* Benchmark Performance */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">
              BENCHMARK PERFORMANCE
            </span>
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-emerald-600 font-mono">
              {currentPlant?.expected_pr
                ? (currentPlant.expected_pr * 100).toFixed(0)
                : '78'}
              %
            </span>
            <span className="text-xs font-mono text-slate-500 font-bold">Target PR Baseline</span>
          </div>
          <div className="text-xs text-slate-600 font-mono space-y-1.5 border-t border-slate-100 pt-3">
            <div className="flex justify-between">
              <span className="text-slate-500">Power PPA Tariff:</span>
              <strong className="text-slate-800">
                ₹{currentPlant?.tariff_inr_per_kwh || '3.50'} / kWh
              </strong>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Loss Revenue Index:</span>
              <strong className="text-emerald-700">₹3,500 / MWh</strong>
            </div>
          </div>
        </div>

        {/* Plant Infrastructure Scope */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">
              PLANT INFRASTRUCTURE SCOPE
            </span>
            <Building2 className="w-4 h-4 text-sky-600" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-sky-800 font-mono">
              {isWeatherOnly ? '1' : isGenOnly ? inverterCount : `${inverterCount + weatherStations.length}`}
            </span>
            <span className="text-xs font-mono text-slate-500 font-bold">
              {isWeatherOnly
                ? 'Weather Station (WS-01)'
                : isGenOnly
                ? 'Inverter Blocks'
                : `SCADA Nodes (${inverterCount} Inverters${weatherStations.length > 0 ? ` + ${weatherStations.length} WS` : ''})`}
            </span>
          </div>
          <div className="text-xs text-slate-600 font-mono space-y-1.5 border-t border-slate-100 pt-3">
            <div className="flex justify-between">
              <span className="text-slate-500">Active Telemetry:</span>
              <strong className="text-slate-800">
                {activeChannelCount} Channels {isWeatherOnly ? '(Weather Feed)' : isGenOnly ? '(Generation Feed)' : '(Merged)'}
              </strong>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Reference Weather System:</span>
              <strong className="text-slate-800">
                {weatherStations.length} Station (WS-01) {isWeatherOnly ? '• LIVE STREAM' : '• ACTIVE'}
              </strong>
            </div>
          </div>
        </div>
      </div>

      {/* SCADA Channel Architecture */}
      <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-3">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-[#004874]" />
            <h3 className="text-sm font-bold text-slate-800">
              Plant SCADA Channel Architecture ({activeChannelCount} Channels {isWeatherOnly ? '• Weather Stream' : isGenOnly ? '• Generation Stream' : '• Merged Telemetry'})
            </h3>
          </div>
          <span className="text-xs font-mono text-slate-500">15-minute synchronous telemetry cadence</span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <div
            className={`p-3.5 rounded-lg border transition ${
              isWeatherOnly
                ? 'bg-slate-50/50 border-dashed border-slate-200 opacity-60'
                : 'bg-slate-50 border-slate-200/80'
            }`}
          >
            <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">AC Power Channels</div>
            <div className="text-lg font-mono font-bold text-slate-900 mt-1">
              {isWeatherOnly ? '0' : channelBreakdown.acPowerCount} Channels
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5 font-medium">
              {isWeatherOnly ? '22 Inverters (Awaiting Feed)' : 'kW Active Generation'}
            </div>
          </div>

          <div
            className={`p-3.5 rounded-lg border transition ${
              isWeatherOnly
                ? 'bg-slate-50/50 border-dashed border-slate-200 opacity-60'
                : 'bg-slate-50 border-slate-200/80'
            }`}
          >
            <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">DC Power Channels</div>
            <div className="text-lg font-mono font-bold text-slate-900 mt-1">
              {isWeatherOnly ? '0' : channelBreakdown.dcPowerCount} Channels
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5 font-medium">
              {isWeatherOnly ? '22 Inverters (Awaiting Feed)' : 'kW String Input'}
            </div>
          </div>

          <div
            className={`p-3.5 rounded-lg border transition ${
              isWeatherOnly
                ? 'bg-slate-50/50 border-dashed border-slate-200 opacity-60'
                : 'bg-slate-50 border-slate-200/80'
            }`}
          >
            <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Daily Yield Channels</div>
            <div className="text-lg font-mono font-bold text-slate-900 mt-1">
              {isWeatherOnly ? '0' : channelBreakdown.dailyYieldCount} Channels
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5 font-medium">
              {isWeatherOnly ? '22 Inverters (Awaiting Feed)' : 'kWh Daily Integrals'}
            </div>
          </div>

          <div
            className={`p-3.5 rounded-lg border transition ${
              isWeatherOnly
                ? 'bg-slate-50/50 border-dashed border-slate-200 opacity-60'
                : 'bg-slate-50 border-slate-200/80'
            }`}
          >
            <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Total Yield Channels</div>
            <div className="text-lg font-mono font-bold text-slate-900 mt-1">
              {isWeatherOnly ? '0' : channelBreakdown.totalYieldCount} Channels
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5 font-medium">
              {isWeatherOnly ? '22 Inverters (Awaiting Feed)' : 'kWh Cumulative Metered'}
            </div>
          </div>

          <div
            className={`p-3.5 rounded-lg border transition ${
              isWeatherOnly
                ? 'bg-amber-50/80 border-amber-300 ring-1 ring-amber-300/50 shadow-2xs'
                : 'bg-amber-50/60 border-amber-200/80'
            }`}
          >
            <div className="text-[10px] font-mono uppercase text-amber-700 font-bold flex items-center justify-between">
              <span>Meteorological Sensors</span>
              {isWeatherOnly && (
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-200/70 text-amber-900 font-bold">
                  ACTIVE FEED
                </span>
              )}
            </div>
            <div className="text-lg font-mono font-bold text-amber-900 mt-1">
              {channelBreakdown.weatherCount} Sensors
            </div>
            <div className="text-[11px] text-amber-700 mt-0.5 font-medium">
              POA Irradiance &amp; Temperatures
            </div>
          </div>
        </div>
      </div>

      {/* Meteorological Station & Solar Resource Reference (WS-01) */}
      <div className="bg-gradient-to-r from-amber-50/70 via-sky-50/50 to-white p-5 rounded-xl border border-amber-200/80 shadow-xs space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-amber-500 text-white flex items-center justify-center shadow-xs">
              <CloudSun className="w-4 h-4 text-white" />
            </div>
            <div>
              <h4 className="text-sm font-bold text-slate-900">
                Meteorological Station WS-01 (Reference Weather System)
              </h4>
              <p className="text-xs text-slate-600 font-medium">
                Authoritative on-site pyranometer and temperature sensor telemetry driving real-time PR Index and irradiance-residual loss models.
              </p>
            </div>
          </div>
          <Badge variant="emerald">POA TELEMETRY ACTIVE</Badge>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
          <div className="bg-white/80 p-3 rounded-lg border border-slate-200 shadow-2xs flex items-center gap-3">
            <div className="w-8 h-8 rounded-md bg-amber-100 text-amber-600 flex items-center justify-center font-bold text-xs flex-shrink-0">
              <Sun className="w-4 h-4" />
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Channel: irradiance_poa</div>
              <div className="text-xs font-bold text-slate-800">Plane-of-Array Pyranometer</div>
              <div className="text-[11px] font-mono text-emerald-700 font-semibold">kW/m² Telemetry Stream</div>
            </div>
          </div>

          <div className="bg-white/80 p-3 rounded-lg border border-slate-200 shadow-2xs flex items-center gap-3">
            <div className="w-8 h-8 rounded-md bg-sky-100 text-sky-600 flex items-center justify-center font-bold text-xs flex-shrink-0">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Channel: temperature_ambient</div>
              <div className="text-xs font-bold text-slate-800">Ambient Air RTD Sensor</div>
              <div className="text-[11px] font-mono text-slate-600 font-medium">°C Thermal Telemetry</div>
            </div>
          </div>

          <div className="bg-white/80 p-3 rounded-lg border border-slate-200 shadow-2xs flex items-center gap-3">
            <div className="w-8 h-8 rounded-md bg-rose-100 text-rose-600 flex items-center justify-center font-bold text-xs flex-shrink-0">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400 font-bold">Channel: temperature_module</div>
              <div className="text-xs font-bold text-slate-800">PV Module Backsheet Sensor</div>
              <div className="text-[11px] font-mono text-slate-600 font-medium">°C Cell Temperature</div>
            </div>
          </div>
        </div>
      </div>

      {/* Plant Grid Specifications & Environmental Impact */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Electrical & Interconnection Specifications */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
          <div className="flex items-center gap-2 border-b border-slate-100 pb-2.5">
            <Zap className="w-4 h-4 text-[#004874]" />
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-800">
              Electrical & Grid Interconnection
            </h4>
          </div>

          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between py-1 border-b border-slate-50">
              <span className="text-slate-500 font-sans">Collector Substation Voltage:</span>
              <strong className="text-slate-800">33 kV Internal Collector / 132 kV Grid Delivery</strong>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-50">
              <span className="text-slate-500 font-sans">Interconnection Compliance:</span>
              <strong className="text-slate-800">CEA Technical Standards for Grid Connectivity</strong>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-50">
              <span className="text-slate-500 font-sans">SCADA Polling Cadence:</span>
              <strong className="text-slate-800">15-Minute Synchronous Interval</strong>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-500 font-sans">PPA Revenue Settlement:</span>
              <strong className="text-emerald-700">₹3.50 / kWh Net Delivered Energy</strong>
            </div>
          </div>
        </div>

        {/* Environmental & Clean Energy Metrics */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
          <div className="flex items-center gap-2 border-b border-slate-100 pb-2.5">
            <Leaf className="w-4 h-4 text-emerald-600" />
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-800">
              Environmental & Clean Energy Impact
            </h4>
          </div>

          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between py-1 border-b border-slate-50">
              <span className="text-slate-500 font-sans">Grid Carbon Displacement Factor:</span>
              <strong className="text-slate-800">~0.82 kg CO₂ / kWh (CEA Baseline)</strong>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-50">
              <span className="text-slate-500 font-sans">Greenhouse Gas (GHG) Reduction:</span>
              <strong className="text-emerald-700">Zero Direct Operational Emissions</strong>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-50">
              <span className="text-slate-500 font-sans">Cleaning & Maintenance Protocol:</span>
              <strong className="text-slate-800">Automated Dry Surface Module Cleaning</strong>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-500 font-sans">Resource Classification:</span>
              <strong className="text-slate-800">100% Renewable Solar PV Generation</strong>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
