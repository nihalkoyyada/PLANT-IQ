import React, { useEffect, useState } from 'react';
import { DeviceTable, DeviceItem } from '../components/devices/DeviceTable';
import { getAssets } from '../api/assets';
import { getChannels } from '../api/channels';
import {
  getLatestReadingsBatch,
  getLatestReading,
  getLatestPowerReadingsBatch,
  getLatestPowerReading,
} from '../api/readings';
import { Badge } from '../components/common/Badge';
import { Cpu, X, LineChart as ChartIcon, Zap } from 'lucide-react';

export const DevicesPage: React.FC = () => {
  const [devices, setDevices] = useState<DeviceItem[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<DeviceItem | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    async function loadDevices() {
      try {
        setLoading(true);

        const [assetsData, channelsData] = await Promise.all([
          getAssets(),
          getChannels(),
        ]);

        // Filter inverter assets
        const inverters = assetsData.filter(
          (asset) =>
            asset.asset_type === 'inverter' ||
            asset.name.toLowerCase().includes('1by')
        );

        // Collect all channel IDs for batch fetching
        const allChannelIds = channelsData.map((c) => c.id);

        let latestReadingsMap: Record<string, any> = {};
        let latestPowerReadingsMap: Record<string, any> = {};

        try {
          const [generalBatch, powerBatch] = await Promise.all([
            getLatestReadingsBatch(allChannelIds),
            getLatestPowerReadingsBatch(allChannelIds, true),
          ]);
          latestReadingsMap = generalBatch;
          latestPowerReadingsMap = powerBatch;
        } catch (batchErr) {
          console.warn('Batch latest readings call failed, falling back to individual queries:', batchErr);
        }

        // Map inverters to DeviceItem objects with actual readings
        const mappedDevices = await Promise.all(
          inverters.map(async (inv): Promise<DeviceItem> => {
            const assetChannels = channelsData.filter(
              (channel) => channel.asset_id === inv.id
            );

            const acChannel = assetChannels.find((channel) => {
              const key = (channel.canonical_key || '').toLowerCase();
              const src = (channel.source_name || '').toUpperCase();
              return key === 'power_ac' || src === 'AC_POWER' || src === 'AC POWER';
            });

            const dcChannel = assetChannels.find((channel) => {
              const key = (channel.canonical_key || '').toLowerCase();
              const src = (channel.source_name || '').toUpperCase();
              return key === 'power_dc' || src === 'DC_POWER' || src === 'DC POWER';
            });

            const dailyEnergyChannel = assetChannels.find((channel) => {
              const key = (channel.canonical_key || '').toLowerCase();
              const src = (channel.source_name || '').toUpperCase();
              return key === 'energy_ac_daily' || src === 'DAILY_YIELD' || src === 'DAILY YIELD';
            });

            const totalEnergyChannel = assetChannels.find((channel) => {
              const key = (channel.canonical_key || '').toLowerCase();
              const src = (channel.source_name || '').toUpperCase();
              return key === 'energy_ac_total' || src === 'TOTAL_YIELD' || src === 'TOTAL YIELD';
            });

            let acPowerKw: number | undefined;
            let dcPowerKw: number | undefined;
            let acTimestamp: string | undefined;
            let dcTimestamp: string | undefined;
            let dailyYieldKwh: number | undefined;
            let totalYieldKwh: number | undefined;
            let lastReading = 'No reading';

            // 1. AC Power Reading
            if (acChannel) {
              const r = latestPowerReadingsMap[acChannel.id];
              if (r && r.value_kw !== undefined && r.value_kw !== null) {
                acPowerKw = Number(r.value_kw);
                acTimestamp = r.timestamp || r.ts;
                lastReading = acTimestamp || 'No reading';
              } else {
                try {
                  const singleR = await getLatestPowerReading(acChannel.id, true);
                  if (singleR && singleR.value_kw !== undefined && singleR.value_kw !== null) {
                    acPowerKw = Number(singleR.value_kw);
                    acTimestamp = singleR.timestamp;
                    lastReading = acTimestamp;
                  }
                } catch (e) {
                  console.warn(`Could not fetch AC reading for ${inv.name}:`, e);
                }
              }
            }

            // 2. DC Power Reading
            if (dcChannel) {
              const r = latestPowerReadingsMap[dcChannel.id];
              if (r && r.value_kw !== undefined && r.value_kw !== null) {
                dcPowerKw = Number(r.value_kw);
                dcTimestamp = r.timestamp || r.ts;
                if (lastReading === 'No reading' && dcTimestamp) {
                  lastReading = dcTimestamp;
                }
              } else {
                try {
                  const singleR = await getLatestPowerReading(dcChannel.id, true);
                  if (singleR && singleR.value_kw !== undefined && singleR.value_kw !== null) {
                    dcPowerKw = Number(singleR.value_kw);
                    dcTimestamp = singleR.timestamp;
                    if (lastReading === 'No reading' && dcTimestamp) {
                      lastReading = dcTimestamp;
                    }
                  }
                } catch (e) {
                  console.warn(`Could not fetch DC reading for ${inv.name}:`, e);
                }
              }
            }

            // 3. Daily Yield Reading
            if (dailyEnergyChannel) {
              const r = latestReadingsMap[dailyEnergyChannel.id];
              if (r && r.value !== undefined && r.value !== null) {
                const rawVal = Number(r.value);
                if (!isNaN(rawVal)) {
                  dailyYieldKwh = rawVal;
                }
              } else {
                try {
                  const singleR = await getLatestReading(dailyEnergyChannel.id);
                  if (singleR && singleR.value !== undefined && singleR.value !== null) {
                    const rawVal = Number(singleR.value);
                    if (!isNaN(rawVal)) {
                      dailyYieldKwh = rawVal;
                    }
                  }
                } catch (e) {
                  // Optional metric
                }
              }
            }

            // 4. Total Yield Reading
            if (totalEnergyChannel) {
              const r = latestReadingsMap[totalEnergyChannel.id];
              if (r && r.value !== undefined && r.value !== null) {
                const rawVal = Number(r.value);
                if (!isNaN(rawVal)) {
                  totalYieldKwh = rawVal;
                }
              } else {
                try {
                  const singleR = await getLatestReading(totalEnergyChannel.id);
                  if (singleR && singleR.value !== undefined && singleR.value !== null) {
                    const rawVal = Number(singleR.value);
                    if (!isNaN(rawVal)) {
                      totalYieldKwh = rawVal;
                    }
                  }
                } catch (e) {
                  // Optional metric
                }
              }
            }

            // Format timestamp cleanly
            if (lastReading !== 'No reading') {
              try {
                const date = new Date(lastReading);
                if (!isNaN(date.getTime())) {
                  lastReading = date.toISOString().replace('T', ' ').replace('Z', ' UTC');
                }
              } catch (_) {}
            }

            return {
              id: inv.id,
              name: inv.name,
              sourceKey: inv.metadata?.source_key || inv.name,
              assetType: inv.asset_type,
              ratedKw: inv.rated_kw || 50,
              status: acChannel || dcChannel ? 'ONLINE' : 'OFFLINE',
              lastReading,
              acPowerKw,
              dcPowerKw,
              acTimestamp,
              dcTimestamp,
              dailyYieldKwh,
              totalYieldKwh,
            };
          })
        );

        setDevices(mappedDevices);
      } catch (err) {
        console.error('Error loading devices:', err);
        setDevices([]);
      } finally {
        setLoading(false);
      }
    }

    loadDevices();
  }, []);

  return (
    <div className="space-y-4 pb-12">
      {/* Header */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">
              Devices &amp; Inverters
            </h1>

            <Badge variant={devices.length > 0 ? 'emerald' : 'slate'}>
              ● {devices.length} ACTIVE INVERTERS
            </Badge>
          </div>

          <p className="text-xs text-slate-500 font-mono mt-0.5">
            Real-time telemetry and health monitoring across discrete solar string inverters
          </p>
        </div>
      </div>

      {/* Inverter Table */}
      {devices.length === 0 && !loading ? (
        <div className="bg-white p-12 rounded-xl border border-slate-200/90 text-center font-mono text-xs text-slate-400 space-y-2">
          <Cpu className="w-8 h-8 text-slate-300 mx-auto" />

          <strong className="text-slate-600 text-sm font-bold block">
            No Inverter Data Available
          </strong>

          <span>
            Upload and ingest a SCADA telemetry file to populate active inverter nodes.
          </span>
        </div>
      ) : (
        <DeviceTable
          devices={devices}
          onSelectDevice={(dev) => setSelectedDevice(dev)}
        />
      )}

      {/* Selected Inverter Detail Drawer */}
      {selectedDevice && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40 backdrop-blur-xs">
          <div className="w-full max-w-lg bg-white h-full shadow-2xl p-6 overflow-y-auto space-y-4 border-l border-slate-200">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <div className="w-9 h-9 rounded-lg bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700">
                  <Cpu className="w-5 h-5" />
                </div>

                <div>
                  <h3 className="text-base font-bold text-slate-900 font-mono">
                    {selectedDevice.name}
                  </h3>

                  <p className="text-xs text-slate-500 font-mono">
                    {selectedDevice.sourceKey}
                  </p>
                </div>
              </div>

              <button
                onClick={() => setSelectedDevice(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Device Information */}
            <div className="grid grid-cols-2 gap-3 font-mono text-xs">
              <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                <div className="text-[10px] text-slate-400">
                  RATED CAPACITY
                </div>

                <div className="text-sm font-bold text-slate-800">
                  {selectedDevice.ratedKw} kW
                </div>
              </div>

              <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                <div className="text-[10px] text-slate-400">
                  STATUS
                </div>

                <Badge
                  variant={
                    selectedDevice.status === 'ONLINE'
                      ? 'emerald'
                      : 'rose'
                  }
                >
                  ● {selectedDevice.status}
                </Badge>
              </div>
            </div>

            {/* Telemetry Snapshot */}
            <div className="bg-sky-50/70 p-4 rounded-xl border border-sky-100 space-y-3 font-mono text-xs">
              <div className="flex items-center gap-2 text-sky-900 font-bold">
                <Zap className="w-4 h-4 text-amber-500" />
                <span>TELEMETRY SNAPSHOT</span>
              </div>

              <div className="grid grid-cols-2 gap-2 text-slate-700">
                <div>
                  AC Power:{' '}
                  <strong className="text-sky-800">
                    {selectedDevice.acPowerKw !== undefined && selectedDevice.acPowerKw !== null
                      ? `${selectedDevice.acPowerKw.toFixed(1)} kW`
                      : '---'}
                  </strong>
                </div>

                <div>
                  DC Power:{' '}
                  <strong className="text-amber-800">
                    {selectedDevice.dcPowerKw !== undefined && selectedDevice.dcPowerKw !== null
                      ? `${selectedDevice.dcPowerKw.toFixed(1)} kW`
                      : '---'}
                  </strong>
                </div>

                <div>
                  Daily Yield:{' '}
                  <strong className="text-emerald-800">
                    {selectedDevice.dailyYieldKwh !== undefined
                      ? `${selectedDevice.dailyYieldKwh.toFixed(0)} kWh`
                      : '---'}
                  </strong>
                </div>

                <div>
                  Total Yield:{' '}
                  <strong>
                    {selectedDevice.totalYieldKwh !== undefined
                      ? `${selectedDevice.totalYieldKwh.toLocaleString()} kWh`
                      : '---'}
                  </strong>
                </div>
              </div>

              <div className="pt-2 border-t border-sky-100 text-[10px] text-slate-500">
                Last reading: {selectedDevice.lastReading}
              </div>
            </div>

            {/* Historical Telemetry */}
            <div className="border-t border-slate-100 pt-4">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-800 mb-2">
                <ChartIcon className="w-4 h-4 text-sky-600" />
                <span>HISTORICAL TELEMETRY TREND</span>
              </div>

              <p className="text-xs text-slate-500 font-mono">
                5-minute cadence readings synchronized from database telemetry.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};