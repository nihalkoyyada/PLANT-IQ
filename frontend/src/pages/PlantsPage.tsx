import React, { useEffect, useState } from 'react';
import { Sun, MapPin, Clock, ChevronDown } from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { getPlants } from '../api/plants';
import { getAssets } from '../api/assets';
import { getChannels } from '../api/channels';
import { Asset, Channel, Plant } from '../types';

export const PlantsPage: React.FC = () => {
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
          // Prefer a plant that has assets if available
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

  const plantAssets = currentPlant
    ? allAssets.filter((a) => a.plant_id === currentPlant.id)
    : [];
  const plantAssetIds = new Set(plantAssets.map((a) => a.id));

  const inverters = plantAssets.filter(
    (a) =>
      a.asset_type?.toLowerCase() === 'inverter' ||
      a.name.startsWith('INV-') ||
      a.name.includes('1BY')
  );

  const plantChannels = allChannels.filter((c) => plantAssetIds.has(c.asset_id));

  const inverterCount = inverters.length;
  const channelCount = plantChannels.length;

  return (
    <div className="space-y-4 pb-12">
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
                    className="text-xl font-bold text-slate-900 tracking-tight bg-slate-50 border border-slate-200 rounded-lg px-3 py-1 pr-8 appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-sky-500"
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

              <Badge variant={inverterCount > 0 ? 'emerald' : 'slate'}>
                {inverterCount > 0 ? '● OPERATIONAL' : '● IDLE (NO INVERTERS)'}
              </Badge>
              <Badge variant="navy">
                {currentPlant?.capacity_ac_kw
                  ? `${(currentPlant.capacity_ac_kw / 1000).toFixed(0)} MW AC`
                  : '28 MW AC'}
              </Badge>
            </div>
            <p className="text-xs text-slate-500 font-mono mt-1 flex items-center gap-2">
              <MapPin className="w-3.5 h-3.5 text-slate-400" />
              <span>
                {currentPlant?.latitude && currentPlant?.longitude
                  ? `Rajasthan, India (${currentPlant.latitude.toFixed(2)}° N, ${currentPlant.longitude.toFixed(2)}° E)`
                  : 'Rajasthan, India (27.54° N, 71.92° E)'}
              </span>
              <span className="text-slate-300">|</span>
              <Clock className="w-3.5 h-3.5 text-slate-400" />
              <span>{currentPlant?.timezone || 'Asia/Kolkata'}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Badge variant="blue">SCADA NODE PRIMARY</Badge>
        </div>
      </div>

      {/* Plant Specification Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-2">
          <span className="text-[10px] font-mono font-semibold uppercase text-slate-400">
            CAPACITY DETAILS
          </span>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-900 font-mono">
              {currentPlant?.capacity_ac_kw
                ? (currentPlant.capacity_ac_kw / 1000).toFixed(1)
                : '27.5'}
            </span>
            <span className="text-xs font-mono text-slate-500 font-bold">MW AC</span>
          </div>
          <div className="text-xs text-slate-500 font-mono flex justify-between border-t border-slate-100 pt-2">
            <span>DC Capacity:</span>
            <strong className="text-slate-800">
              {currentPlant?.capacity_dc_kwp
                ? (currentPlant.capacity_dc_kwp / 1000).toFixed(1)
                : '28.3'}{' '}
              MWp
            </strong>
          </div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-2">
          <span className="text-[10px] font-mono font-semibold uppercase text-slate-400">
            BENCHMARK PERFORMANCE
          </span>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-emerald-600 font-mono">
              {currentPlant?.expected_pr
                ? (currentPlant.expected_pr * 100).toFixed(0)
                : '78'}
              %
            </span>
            <span className="text-xs font-mono text-slate-500 font-bold">Target PR</span>
          </div>
          <div className="text-xs text-slate-500 font-mono flex justify-between border-t border-slate-100 pt-2">
            <span>Tariff Rate:</span>
            <strong className="text-slate-800">
              ₹{currentPlant?.tariff_inr_per_kwh || '3.50'} / kWh
            </strong>
          </div>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-2">
          <span className="text-[10px] font-mono font-semibold uppercase text-slate-400">
            ASSET INFRASTRUCTURE
          </span>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-sky-800 font-mono">{inverterCount}</span>
            <span className="text-xs font-mono text-slate-500 font-bold">
              Inverter Blocks
            </span>
          </div>
          <div className="text-xs text-slate-500 font-mono flex justify-between border-t border-slate-100 pt-2">
            <span>Active Channels:</span>
            <strong className="text-slate-800">{channelCount} Channels</strong>
          </div>
        </div>
      </div>
    </div>
  );
};

