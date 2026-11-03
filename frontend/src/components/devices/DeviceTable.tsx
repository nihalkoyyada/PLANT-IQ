import React, { useState } from 'react';
import { Cpu, Search, ChevronRight, Sparkles, Sun } from 'lucide-react';
import { Badge } from '../common/Badge';

export interface DeviceItem {
  id: string;
  name: string;
  sourceKey: string;
  assetType: string;
  datasetOrigin?: string;
  ratedKw?: number | null;
  status: 'ONLINE' | 'MAINTENANCE' | 'OFFLINE';
  lastReading: string;
  acPowerKw?: number;
  dcPowerKw?: number;
  acTimestamp?: string;
  dcTimestamp?: string;
  dailyYieldKwh?: number;
  totalYieldKwh?: number;
  acChannelId?: string;
  dcChannelId?: string;
  // Weather specific metrics
  irradiancePoa?: number;
  ambientTemp?: number;
  moduleTemp?: number;
  weatherTimestamp?: string;
  irradianceChannelId?: string;
  ambientTempChannelId?: string;
  moduleTempChannelId?: string;
}

const formatReadingTime = (tsStr?: string): string | null => {
  if (!tsStr || tsStr === 'No reading') return null;
  try {
    const d = new Date(tsStr);
    if (isNaN(d.getTime())) return null;
    const day = d.getUTCDate();
    const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
    const year = d.getUTCFullYear();
    const hours = String(d.getUTCHours()).padStart(2, '0');
    const mins = String(d.getUTCMinutes()).padStart(2, '0');
    return `${day} ${month} ${year} ${hours}:${mins} UTC`;
  } catch {
    return null;
  }
};

interface DeviceTableProps {
  devices: DeviceItem[];
  onSelectDevice: (device: DeviceItem) => void;
  onAskCopilot?: (prompt: string) => void;
  activeDatasets?: string[];
}

export const DeviceTable: React.FC<DeviceTableProps> = ({
  devices,
  onSelectDevice,
  onAskCopilot,
  activeDatasets = [],
}) => {
  const [search, setSearch] = useState('');

  const filtered = devices.filter(
    (d) =>
      d.name.toLowerCase().includes(search.toLowerCase()) ||
      d.sourceKey.toLowerCase().includes(search.toLowerCase()) ||
      d.assetType.toLowerCase().includes(search.toLowerCase())
  );

  const isWeatherOnly =
    activeDatasets.length === 1 && activeDatasets[0].toLowerCase().includes('weather');
  const isMerged = activeDatasets.length > 1;

  const hasWeather = devices.some(
    (d) => d.assetType === 'weather_station' || d.name.toLowerCase().startsWith('ws-')
  );
  const hasInverter = devices.some(
    (d) => d.assetType !== 'weather_station' && !d.name.toLowerCase().startsWith('ws-')
  );

  const fleetTitle = isWeatherOnly
    ? 'Weather Station Fleet'
    : isMerged
    ? hasWeather && hasInverter
      ? 'Merged Fleet (Inverters & Weather Station)'
      : hasWeather
      ? 'Weather Station Fleet'
      : 'Merged Inverter Fleet'
    : 'Solar Inverter Fleet';

  return (
    <div className="bg-white rounded-xl border border-slate-200/90 shadow-xs overflow-hidden space-y-4 p-4">
      {/* Search Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-slate-900 tracking-tight">{fleetTitle}</h3>
            {isMerged && (
              <Badge variant="blue" className="text-[9px] py-0.5">
                MERGED ({activeDatasets.length > 0 ? `${activeDatasets.length} DATASETS` : 'MULTI-SOURCE'})
              </Badge>
            )}
            {isWeatherOnly && (
              <Badge variant="amber" className="text-[9px] py-0.5">
                WEATHER ONLY
              </Badge>
            )}
          </div>
          <p className="text-xs text-slate-500 font-mono">
            {devices.length} {devices.length === 1 ? 'Discrete SCADA Node' : 'Discrete SCADA Nodes'}
            {activeDatasets.length > 0 && ` • Feed: ${activeDatasets.join(', ')}`}
          </p>
        </div>

        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search asset key or type..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 pr-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs font-mono text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 w-full sm:w-60"
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-[10px] font-mono font-semibold uppercase text-slate-500 tracking-wider">
              <th className="py-2.5 px-3">
                {isWeatherOnly ? 'WEATHER ASSET KEY' : 'ASSET / NODE KEY'}
              </th>
              <th className="py-2.5 px-3">TYPE</th>
              <th className="py-2.5 px-3">
                {isWeatherOnly ? 'SENSORS' : isMerged ? 'RATED / SENSORS' : 'RATED (KW)'}
              </th>
              <th className="py-2.5 px-3">STATUS</th>
              <th className="py-2.5 px-3">
                {isWeatherOnly ? 'POA IRRADIANCE' : isMerged ? 'AC POWER / IRRAD' : 'AC POWER'}
              </th>
              <th className="py-2.5 px-3">
                {isWeatherOnly ? 'AMBIENT TEMP' : isMerged ? 'DC POWER / AMB' : 'DC POWER'}
              </th>
              <th className="py-2.5 px-3">
                {isWeatherOnly ? 'MODULE TEMP' : isMerged ? 'DAILY YIELD / MOD' : 'DAILY YIELD'}
              </th>
              <th className="py-2.5 px-3">ACTION</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-xs font-mono">
            {filtered.length > 0 ? (
              filtered.map((dev) => {
                const isWeather =
                  dev.assetType === 'weather_station' ||
                  dev.assetType === 'weather_sensor' ||
                  dev.name.toLowerCase().includes('weather') ||
                  dev.name.toLowerCase().startsWith('ws-');

                return (
                  <tr
                    key={dev.id}
                    onClick={() => onSelectDevice(dev)}
                    className="hover:bg-sky-50/60 transition cursor-pointer group"
                  >
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-2">
                        <div
                          className={`w-7 h-7 rounded border flex items-center justify-center ${
                            isWeather
                              ? 'bg-amber-50 border-amber-200 text-amber-600'
                              : 'bg-sky-50 border-sky-200 text-sky-700'
                          }`}
                        >
                          {isWeather ? <Sun className="w-4 h-4" /> : <Cpu className="w-4 h-4" />}
                        </div>
                        <div>
                          <div className="font-bold text-slate-900">{dev.name}</div>
                          <div className="text-[10px] text-slate-400 font-mono">
                            {dev.sourceKey}
                            {isWeather && ' • Weather Station'}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-3 capitalize text-slate-600">
                      {isWeather ? 'Weather Station' : dev.assetType}
                    </td>
                    <td className="py-3 px-3 font-semibold text-slate-800">
                      {isWeather ? (
                        <span className="text-amber-700 font-medium text-[11px]">Pyranometer + RTD</span>
                      ) : dev.ratedKw !== undefined && dev.ratedKw !== null ? (
                        `${dev.ratedKw} kW`
                      ) : (
                        <span className="text-slate-400 font-normal">N/A</span>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <Badge variant={dev.status === 'ONLINE' ? 'emerald' : 'rose'}>
                        ● {dev.status}
                      </Badge>
                    </td>
                    <td className="py-3 px-3">
                      {isWeather ? (
                        <div>
                          <div className="text-amber-700 font-bold">
                            {dev.irradiancePoa !== undefined && dev.irradiancePoa !== null
                              ? `${dev.irradiancePoa.toFixed(2)} kW/m²`
                              : '---'}
                          </div>
                          {(dev.weatherTimestamp || dev.lastReading) && (
                            <div className="text-[9px] text-slate-400 font-mono font-normal">
                              {formatReadingTime(dev.weatherTimestamp || dev.lastReading) || 'Telemetry live'}
                            </div>
                          )}
                        </div>
                      ) : dev.acPowerKw !== undefined && dev.acPowerKw !== null ? (
                        <div>
                          <div className="text-sky-700 font-semibold">{dev.acPowerKw.toFixed(1)} kW</div>
                          {dev.acTimestamp && formatReadingTime(dev.acTimestamp) && (
                            <div className="text-[9px] text-slate-400 font-mono font-normal">
                              Data: {formatReadingTime(dev.acTimestamp)}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-400 font-semibold">---</span>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      {isWeather ? (
                        <div>
                          <div className="text-sky-700 font-semibold">
                            {dev.ambientTemp !== undefined && dev.ambientTemp !== null
                              ? `${dev.ambientTemp.toFixed(1)} °C`
                              : '---'}
                          </div>
                          <div className="text-[9px] text-slate-400 font-mono font-normal">Ambient</div>
                        </div>
                      ) : dev.dcPowerKw !== undefined && dev.dcPowerKw !== null ? (
                        <div>
                          <div className="text-amber-700 font-semibold">{dev.dcPowerKw.toFixed(1)} kW</div>
                          {dev.dcTimestamp && formatReadingTime(dev.dcTimestamp) && (
                            <div className="text-[9px] text-slate-400 font-mono font-normal">
                              Data: {formatReadingTime(dev.dcTimestamp)}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-400 font-semibold">---</span>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      {isWeather ? (
                        <div>
                          <div className="text-emerald-700 font-semibold">
                            {dev.moduleTemp !== undefined && dev.moduleTemp !== null
                              ? `${dev.moduleTemp.toFixed(1)} °C`
                              : '---'}
                          </div>
                          <div className="text-[9px] text-slate-400 font-mono font-normal">Module</div>
                        </div>
                      ) : (
                        <span className="text-emerald-700 font-semibold">
                          {dev.dailyYieldKwh !== undefined && dev.dailyYieldKwh !== null
                            ? `${dev.dailyYieldKwh.toFixed(0)} kWh`
                            : '---'}
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-1">
                        {onAskCopilot && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              if (isWeather) {
                                onAskCopilot(
                                  `Analyze weather sensor telemetry for ${dev.name} (${dev.sourceKey}). Irradiance POA: ${
                                    dev.irradiancePoa !== undefined ? dev.irradiancePoa.toFixed(2) + ' kW/m²' : 'N/A'
                                  }, Ambient: ${
                                    dev.ambientTemp !== undefined ? dev.ambientTemp.toFixed(1) + '°C' : 'N/A'
                                  }, Module: ${
                                    dev.moduleTemp !== undefined ? dev.moduleTemp.toFixed(1) + '°C' : 'N/A'
                                  }. Check for sensor drift, temperature coefficients, and pyranometer calibration.`
                                );
                              } else {
                                onAskCopilot(
                                  `Analyze performance and active power for ${dev.name} (${dev.sourceKey}). Status: ${dev.status}, AC: ${
                                    dev.acPowerKw !== undefined ? dev.acPowerKw.toFixed(1) + ' kW' : 'N/A'
                                  }. Check for clipping, tripping, or generation shortfall.`
                                );
                              }
                            }}
                            title={`Analyze ${dev.name} with Solar Copilot`}
                            className="p-1 rounded text-sky-600 hover:bg-sky-100 hover:text-sky-800 transition"
                          >
                            <Sparkles className="w-3.5 h-3.5" />
                          </button>
                        )}
                        <button className="p-1 rounded bg-slate-100 group-hover:bg-[#004874] group-hover:text-white transition">
                          <ChevronRight className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={8} className="py-6 text-center text-slate-400 text-xs">
                  No matching devices found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
