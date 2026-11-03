import React, { useEffect, useState } from 'react';
import { DeviceTable, DeviceItem } from '../components/devices/DeviceTable';
import { DeviceChart } from '../components/devices/DeviceChart';
import { getAssets } from '../api/assets';
import { getChannels } from '../api/channels';
import {
  getLatestReadingsBatch,
  getLatestReading,
  getLatestPowerReadingsBatch,
  getLatestPowerReading,
} from '../api/readings';
import { Badge } from '../components/common/Badge';
import { Cpu, X, LineChart as ChartIcon, Zap, Sparkles, Sun } from 'lucide-react';
import { useActiveDatasets } from '../utils/activeDataset';

export const DevicesPage: React.FC<{
  onAskCopilot?: (prompt: string, context?: any) => void;
}> = ({ onAskCopilot }) => {
  const { activeDatasets } = useActiveDatasets();
  const [devices, setDevices] = useState<DeviceItem[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<DeviceItem | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const isWeatherOnly =
    activeDatasets.length === 1 && activeDatasets[0].toLowerCase().includes('weather');
  const isGenOnly =
    activeDatasets.length === 1 && activeDatasets[0].toLowerCase().includes('generation');
  const isMerged = activeDatasets.length > 1;

  useEffect(() => {
    async function loadDevices() {
      try {
        setLoading(true);

        const [assetsData, channelsData] = await Promise.all([
          getAssets(),
          getChannels(),
        ]);

        // Filter assets according to user's selected active dataset(s)
        let targetAssets = assetsData;
        if (isWeatherOnly) {
          targetAssets = assetsData.filter(
            (asset) =>
              asset.asset_type === 'weather_station' ||
              asset.asset_type === 'weather_sensor' ||
              asset.name.toLowerCase().startsWith('ws-')
          );
        } else if (isGenOnly) {
          targetAssets = assetsData.filter(
            (asset) =>
              asset.asset_type === 'inverter' ||
              asset.name.toLowerCase().includes('1by')
          );
        } else {
          // Merged or all active: include both weather station and inverters, placing weather station at top
          targetAssets = assetsData
            .filter(
              (asset) =>
                asset.asset_type === 'inverter' ||
                asset.asset_type === 'weather_station' ||
                asset.name.toLowerCase().startsWith('ws-') ||
                asset.name.toLowerCase().includes('1by')
            )
            .sort((a, b) =>
              a.asset_type === 'weather_station' || a.name.toLowerCase().startsWith('ws-') ? -1 : 1
            );
        }

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

        // Map assets to DeviceItem objects with actual readings
        const mappedDevices = await Promise.all(
          targetAssets.map(async (asset): Promise<DeviceItem> => {
            const assetChannels = channelsData.filter(
              (channel) => channel.asset_id === asset.id
            );

            const isWeather =
              asset.asset_type === 'weather_station' ||
              asset.asset_type === 'weather_sensor' ||
              asset.name.toLowerCase().startsWith('ws-');

            if (isWeather) {
              const irradChan = assetChannels.find((c) => {
                const k = (c.canonical_key || '').toLowerCase();
                const s = (c.source_name || '').toUpperCase();
                return k === 'irradiance_poa' || s.includes('IRRAD') || s.includes('POA');
              });

              const ambChan = assetChannels.find((c) => {
                const k = (c.canonical_key || '').toLowerCase();
                const s = (c.source_name || '').toUpperCase();
                return k === 'temperature_ambient' || s.includes('AMBIENT');
              });

              const modChan = assetChannels.find((c) => {
                const k = (c.canonical_key || '').toLowerCase();
                const s = (c.source_name || '').toUpperCase();
                return k === 'temperature_module' || s.includes('MODULE');
              });

              let irradiancePoa: number | undefined;
              let ambientTemp: number | undefined;
              let moduleTemp: number | undefined;
              let weatherTimestamp: string | undefined;

              if (irradChan) {
                const r = latestReadingsMap[irradChan.id];
                if (r && r.value !== undefined && r.value !== null) {
                  const raw = Number(r.value);
                  irradiancePoa = raw > 50 ? raw / 1000 : raw;
                  weatherTimestamp = r.ts || r.timestamp;
                } else {
                  try {
                    const single = await getLatestReading(irradChan.id);
                    if (single && single.value !== undefined && single.value !== null) {
                      const raw = Number(single.value);
                      irradiancePoa = raw > 50 ? raw / 1000 : raw;
                      weatherTimestamp = single.ts;
                    }
                  } catch (_) {}
                }
              }

              if (ambChan) {
                const r = latestReadingsMap[ambChan.id];
                if (r && r.value !== undefined && r.value !== null) {
                  ambientTemp = Number(r.value);
                  if (!weatherTimestamp) weatherTimestamp = r.ts || r.timestamp;
                } else {
                  try {
                    const single = await getLatestReading(ambChan.id);
                    if (single && single.value !== undefined && single.value !== null) {
                      ambientTemp = Number(single.value);
                      if (!weatherTimestamp) weatherTimestamp = single.ts;
                    }
                  } catch (_) {}
                }
              }

              if (modChan) {
                const r = latestReadingsMap[modChan.id];
                if (r && r.value !== undefined && r.value !== null) {
                  moduleTemp = Number(r.value);
                  if (!weatherTimestamp) weatherTimestamp = r.ts || r.timestamp;
                } else {
                  try {
                    const single = await getLatestReading(modChan.id);
                    if (single && single.value !== undefined && single.value !== null) {
                      moduleTemp = Number(single.value);
                      if (!weatherTimestamp) weatherTimestamp = single.ts;
                    }
                  } catch (_) {}
                }
              }

              return {
                id: asset.id,
                name: asset.name,
                sourceKey: asset.metadata?.source_key || 'WS-01',
                assetType: 'weather_station',
                datasetOrigin: activeDatasets.find((d) => d.toLowerCase().includes('weather')) || activeDatasets[0] || 'Weather Station Feed',
                status: (irradChan || ambChan || modChan) ? 'ONLINE' : 'OFFLINE',
                lastReading: weatherTimestamp || 'No reading',
                irradiancePoa,
                ambientTemp,
                moduleTemp,
                weatherTimestamp,
                irradianceChannelId: irradChan?.id,
                ambientTempChannelId: ambChan?.id,
                moduleTempChannelId: modChan?.id,
              };
            }

            // Inverter Asset Mapping
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
                  console.warn(`Could not fetch AC reading for ${asset.name}:`, e);
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
                  console.warn(`Could not fetch DC reading for ${asset.name}:`, e);
                }
              }

              // Normalize DC power from deci-kW (10x kW) if stored raw in dataset
              if (dcPowerKw !== undefined) {
                if (acPowerKw !== undefined && acPowerKw > 0 && dcPowerKw >= acPowerKw * 5.0) {
                  dcPowerKw = Number((dcPowerKw / 10.0).toFixed(1));
                } else if (dcPowerKw > 2500.0) {
                  dcPowerKw = Number((dcPowerKw / 10.0).toFixed(1));
                } else if (dcPowerKw > 25.0 && (acPowerKw === undefined || acPowerKw === 0)) {
                  dcPowerKw = Number((dcPowerKw / 10.0).toFixed(1));
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

            const ratedKw =
              asset.rated_kw !== null && asset.rated_kw !== undefined && Number(asset.rated_kw) > 0
                ? Number(asset.rated_kw)
                : asset.metadata?.rated_ac_kw !== null &&
                  asset.metadata?.rated_ac_kw !== undefined &&
                  Number(asset.metadata.rated_ac_kw) > 0
                ? Number(asset.metadata.rated_ac_kw)
                : undefined;

            return {
              id: asset.id,
              name: asset.name,
              sourceKey: asset.metadata?.source_key || asset.name,
              assetType: asset.asset_type,
              datasetOrigin: activeDatasets.find((d) => !d.toLowerCase().includes('weather')) || activeDatasets[0] || 'Inverter Feed',
              ratedKw,
              status: acChannel || dcChannel ? 'ONLINE' : 'OFFLINE',
              lastReading,
              acPowerKw,
              dcPowerKw,
              acTimestamp,
              dcTimestamp,
              dailyYieldKwh,
              totalYieldKwh,
              acChannelId: acChannel?.id,
              dcChannelId: dcChannel?.id,
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
  }, [activeDatasets, isWeatherOnly, isGenOnly, isMerged]);

  const weatherStationCount = devices.filter(
    (d) => d.assetType === 'weather_station' || d.name.toLowerCase().startsWith('ws-')
  ).length;
  const inverterCount = devices.length - weatherStationCount;

  const activeNodesLabel = isWeatherOnly
    ? devices.length === 1
      ? 'ACTIVE WEATHER SENSOR NODE'
      : 'ACTIVE WEATHER SENSOR NODES'
    : isMerged
    ? weatherStationCount > 0 && inverterCount > 0
      ? `ACTIVE NODES (${inverterCount} Inverters + ${weatherStationCount} Weather Station${weatherStationCount > 1 ? 's' : ''})`
      : weatherStationCount > 0
      ? `ACTIVE NODES (${weatherStationCount} Weather Station${weatherStationCount > 1 ? 's' : ''})`
      : `ACTIVE NODES (${inverterCount} Inverters)`
    : 'ACTIVE INVERTERS';

  return (
    <div className="space-y-4 pb-12">
      {/* Header */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">
              {isWeatherOnly ? 'Weather Station & Sensors' : isMerged ? 'Devices & Inverters (Merged Telemetry)' : 'Devices & Inverters'}
            </h1>

            <Badge variant={devices.length > 0 ? (isWeatherOnly ? 'amber' : 'emerald') : 'slate'}>
              ● {devices.length} {activeNodesLabel}
            </Badge>
          </div>

          <p className="text-xs text-slate-500 font-mono mt-0.5">
            {isWeatherOnly
              ? `Real-time telemetry and pyranometer/temperature monitoring for Weather Station (${activeDatasets[0] || 'WS-01'})`
              : isMerged
              ? `Merged multi-source telemetry from ${activeDatasets.length > 0 ? activeDatasets.join(', ') : 'active datasets'}`
              : 'Real-time telemetry and health monitoring across discrete solar string inverters'}
          </p>
        </div>
      </div>

      {/* Inverter / Device Table */}
      {devices.length === 0 && !loading ? (
        <div className="bg-white p-12 rounded-xl border border-slate-200/90 text-center font-mono text-xs text-slate-400 space-y-2">
          <Cpu className="w-8 h-8 text-slate-300 mx-auto" />

          <strong className="text-slate-600 text-sm font-bold block">
            {isWeatherOnly ? 'No Weather Station Data Available' : 'No Device Data Available'}
          </strong>

          <span>
            Upload and ingest a SCADA telemetry file to populate active nodes.
          </span>
        </div>
      ) : (
        <DeviceTable
          devices={devices}
          onSelectDevice={(dev) => setSelectedDevice(dev)}
          onAskCopilot={onAskCopilot}
          activeDatasets={activeDatasets}
        />
      )}

      {/* Selected Device Detail Drawer */}
      {selectedDevice && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40 backdrop-blur-xs">
          <div className="w-full max-w-lg bg-white h-full shadow-2xl p-6 overflow-y-auto space-y-4 border-l border-slate-200">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <div
                  className={`w-9 h-9 rounded-lg border flex items-center justify-center ${
                    selectedDevice.assetType === 'weather_station'
                      ? 'bg-amber-50 border-amber-200 text-amber-600'
                      : 'bg-sky-50 border-sky-200 text-sky-700'
                  }`}
                >
                  {selectedDevice.assetType === 'weather_station' ? (
                    <Sun className="w-5 h-5" />
                  ) : (
                    <Cpu className="w-5 h-5" />
                  )}
                </div>

                <div>
                  <h3 className="text-base font-bold text-slate-900 font-mono">
                    {selectedDevice.name}
                  </h3>

                  <p className="text-xs text-slate-500 font-mono">
                    {selectedDevice.sourceKey}
                    {selectedDevice.assetType === 'weather_station' && ' • Weather Station Node'}
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
                  {selectedDevice.assetType === 'weather_station' ? 'INSTRUMENTATION' : 'RATED CAPACITY'}
                </div>

                <div className="text-sm font-bold text-slate-800">
                  {selectedDevice.assetType === 'weather_station' ? (
                    'Pyranometer + RTD'
                  ) : selectedDevice.ratedKw !== undefined && selectedDevice.ratedKw !== null ? (
                    `${selectedDevice.ratedKw} kW`
                  ) : (
                    <span className="text-slate-400 font-normal">N/A</span>
                  )}
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
                <span>
                  {selectedDevice.assetType === 'weather_station'
                    ? 'WEATHER TELEMETRY SNAPSHOT'
                    : 'TELEMETRY SNAPSHOT'}
                </span>
              </div>

              {selectedDevice.assetType === 'weather_station' ? (
                <div className="grid grid-cols-2 gap-2 text-slate-700">
                  <div>
                    Irradiance POA:{' '}
                    <strong className="text-amber-800">
                      {selectedDevice.irradiancePoa !== undefined && selectedDevice.irradiancePoa !== null
                        ? `${selectedDevice.irradiancePoa.toFixed(2)} kW/m²`
                        : '---'}
                    </strong>
                  </div>

                  <div>
                    Ambient Temp:{' '}
                    <strong className="text-sky-800">
                      {selectedDevice.ambientTemp !== undefined && selectedDevice.ambientTemp !== null
                        ? `${selectedDevice.ambientTemp.toFixed(1)} °C`
                        : '---'}
                    </strong>
                  </div>

                  <div>
                    Module Temp:{' '}
                    <strong className="text-emerald-800">
                      {selectedDevice.moduleTemp !== undefined && selectedDevice.moduleTemp !== null
                        ? `${selectedDevice.moduleTemp.toFixed(1)} °C`
                        : '---'}
                    </strong>
                  </div>

                  <div>
                    Sensors Active:{' '}
                    <strong className="text-slate-900">3 Channels</strong>
                  </div>
                </div>
              ) : (
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
              )}

              <div className="pt-2 border-t border-sky-100 text-[10px] text-slate-500">
                Last reading: {selectedDevice.weatherTimestamp || selectedDevice.lastReading}
              </div>
            </div>

            {/* Contextual Ask Copilot Action Button */}
            {onAskCopilot && (
              <button
                id="btn-drawer-ask-copilot"
                onClick={() => {
                  if (selectedDevice.assetType === 'weather_station') {
                    onAskCopilot(
                      `Analyze weather sensor telemetry for ${selectedDevice.name} (${selectedDevice.sourceKey}). Irradiance POA: ${
                        selectedDevice.irradiancePoa !== undefined ? selectedDevice.irradiancePoa.toFixed(2) + ' kW/m²' : 'N/A'
                      }, Ambient Temp: ${
                        selectedDevice.ambientTemp !== undefined ? selectedDevice.ambientTemp.toFixed(1) + '°C' : 'N/A'
                      }, Module Temp: ${
                        selectedDevice.moduleTemp !== undefined ? selectedDevice.moduleTemp.toFixed(1) + '°C' : 'N/A'
                      }. Check for pyranometer soiling, sensor drift, and temperature impact.`,
                      {
                        route: 'devices',
                        assetId: selectedDevice.id,
                        assetName: selectedDevice.name,
                      }
                    );
                  } else {
                    onAskCopilot(
                      `Analyze operational performance and active power for ${selectedDevice.name} (${selectedDevice.sourceKey}). Status: ${selectedDevice.status}, AC Power: ${
                        selectedDevice.acPowerKw !== undefined ? selectedDevice.acPowerKw.toFixed(1) + ' kW' : 'N/A'
                      }, DC Power: ${
                        selectedDevice.dcPowerKw !== undefined ? selectedDevice.dcPowerKw.toFixed(1) + ' kW' : 'N/A'
                      }. Identify clipping, temperature derating, or string inverter anomalies.`,
                      {
                        route: 'devices',
                        assetId: selectedDevice.id,
                        assetName: selectedDevice.name,
                      }
                    );
                  }
                }}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-semibold text-xs shadow-md transition"
              >
                <Sparkles className="w-4 h-4 text-sky-200" />
                <span>
                  {selectedDevice.assetType === 'weather_station'
                    ? 'Analyze Weather Station with Solar Copilot'
                    : 'Analyze Inverter with Solar Copilot'}
                </span>
              </button>
            )}

            {/* Historical Telemetry */}
            <div className="border-t border-slate-100 pt-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-800">
                <ChartIcon className="w-4 h-4 text-sky-600" />
                <span>HISTORICAL TELEMETRY TREND</span>
              </div>

              <p className="text-xs text-slate-500 font-mono">
                {selectedDevice.assetType === 'weather_station'
                  ? 'Weather sensor readings synchronized from database telemetry.'
                  : '5-minute cadence readings synchronized from database telemetry.'}
              </p>

              <DeviceChart
                acChannelId={selectedDevice.acChannelId}
                dcChannelId={selectedDevice.dcChannelId}
                irradianceChannelId={selectedDevice.irradianceChannelId}
                ambientTempChannelId={selectedDevice.ambientTempChannelId}
                moduleTempChannelId={selectedDevice.moduleTempChannelId}
                assetType={selectedDevice.assetType}
                latestTimestamp={
                  selectedDevice.weatherTimestamp ||
                  selectedDevice.acTimestamp ||
                  selectedDevice.dcTimestamp ||
                  selectedDevice.lastReading
                }
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};