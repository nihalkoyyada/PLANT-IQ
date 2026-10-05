import React, { useState } from 'react';
import { CheckCircle2, Sliders, Database, Check, X } from 'lucide-react';
import { Badge } from '../common/Badge';

export interface ColumnMappingItem {
  rawColumn: string;
  mappedKey: string;
  targetType: string;
  confidence: number;
  sampleData?: string;
  valueSpan?: string;
  notes?: string;
}

export const CANONICAL_SIGNAL_OPTIONS = [
  { key: 'timestamp', label: 'timestamp (ISO 8601)', type: 'ISO 8601' },
  { key: 'plant_id', label: 'plant_id (Global Ref)', type: 'Global Ref' },
  { key: 'device_id', label: 'device_id (Asset Inverter)', type: 'Asset Inverter' },
  { key: 'source_key', label: 'source_key (Source Key)', type: 'Source Key' },
  { key: 'power_ac', label: 'power_ac (Active AC Power - kW)', type: 'kW' },
  { key: 'power_dc', label: 'power_dc (DC Power - kW)', type: 'kW' },
  { key: 'energy_ac_daily', label: 'energy_ac_daily (Daily Yield - kWh)', type: 'kWh' },
  { key: 'energy_ac_total', label: 'energy_ac_total (Total Yield - kWh)', type: 'kWh' },
  { key: 'irradiance', label: 'irradiance (Solar Irradiance - W/m²)', type: 'W/m²' },
  { key: 'irradiation', label: 'irradiation (Solar Irradiance - W/m²)', type: 'W/m²' },
  { key: 'ambient_temperature', label: 'ambient_temperature (Ambient Temp - °C)', type: '°C' },
  { key: 'module_temperature', label: 'module_temperature (Module Temp - °C)', type: '°C' },
  { key: 'voltage', label: 'voltage (Voltage - V)', type: 'V' },
  { key: 'current', label: 'current (Current - A)', type: 'A' },
  { key: 'grid_frequency', label: 'grid_frequency (Frequency - Hz)', type: 'Hz' },
];

interface SignalMapperProps {
  fileName?: string;
  rowCount?: number;
  colCount?: number;
  mappings: ColumnMappingItem[];
  onConfirmAll?: () => void;
  onUpdateMapping?: (rawColumn: string, newMappedKey: string, newTargetType?: string) => void;
}

export const SignalMapper: React.FC<SignalMapperProps> = ({
  fileName = 'No file selected',
  rowCount = 0,
  colCount = 0,
  mappings = [],
  onConfirmAll,
  onUpdateMapping,
}) => {
  const [editingRow, setEditingRow] = useState<string | null>(null);
  const [customName, setCustomName] = useState<string>('');

  const handleStartEdit = (rawCol: string, currentMappedKey: string) => {
    setEditingRow(rawCol);
    setCustomName(currentMappedKey);
  };

  const handleSaveEdit = (rawCol: string) => {
    const trimmed = customName.trim();
    if (onUpdateMapping && trimmed) {
      const matchOpt = CANONICAL_SIGNAL_OPTIONS.find((opt) => opt.key === trimmed);
      onUpdateMapping(rawCol, trimmed, matchOpt?.type);
    }
    setEditingRow(null);
  };

  const handleCancelEdit = () => {
    setEditingRow(null);
  };

  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
        <div>
          <span className="text-[10px] font-mono font-bold text-sky-800 uppercase tracking-wider">
            STEP 2 OF 5 : SIGNAL SCHEMA ALIGNMENT
          </span>
          <h3 className="text-base font-bold text-slate-900 tracking-tight">SCADA Column Registry</h3>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={colCount > 0 ? 'emerald' : 'slate'}>
            <CheckCircle2 className="w-3 h-3 inline mr-1" />
            {colCount > 0 ? `${colCount} Auto-Matched` : '0 Columns'}
          </Badge>
        </div>
      </div>

      {/* Target Plant Summary Banner */}
      <div className="bg-sky-50/80 rounded-xl p-4 border border-sky-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-sky-600 text-white flex items-center justify-center font-bold">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-bold text-slate-900">{fileName}</span>
              <Badge variant={rowCount > 0 ? 'emerald' : 'slate'}>
                {rowCount > 0 ? 'PARSED' : 'IDLE'}
              </Badge>
            </div>
            <p className="text-xs text-slate-600">Target: Surya Solar Farm (50MW Phase 1)</p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 text-center border-t sm:border-t-0 sm:border-l border-sky-200/60 pt-2 sm:pt-0 sm:pl-4">
          <div>
            <div className="text-[10px] font-mono text-slate-500 uppercase">ROW COUNT</div>
            <div className="text-xs font-bold text-slate-900 font-mono">{rowCount.toLocaleString()}</div>
          </div>
          <div>
            <div className="text-[10px] font-mono text-slate-500 uppercase">COLUMNS</div>
            <div className="text-xs font-bold text-slate-900 font-mono">{colCount} Detected</div>
          </div>
          <div>
            <div className="text-[10px] font-mono text-slate-500 uppercase">CADENCE</div>
            <div className="text-xs font-bold text-sky-700 font-mono">{rowCount > 0 ? '15-Min' : 'N/A'}</div>
          </div>
        </div>
      </div>

      {/* Mappings Cards */}
      <div className="space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs font-mono text-slate-500">
          <span className="font-bold text-slate-700">DETECTED SIGNALS ({mappings.length})</span>
          {onConfirmAll && mappings.length > 0 && (
            <button
              type="button"
              onClick={onConfirmAll}
              className="px-4 py-2 bg-[#004874] hover:bg-[#003354] text-white text-xs font-semibold rounded-lg shadow-sm transition flex items-center justify-center gap-1.5"
            >
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>Confirm &amp; Execute Ingestion</span>
            </button>
          )}
        </div>

        {mappings.length === 0 ? (
          <div className="p-8 text-center bg-slate-50 rounded-xl border border-slate-200 text-slate-400 font-mono text-xs space-y-1">
            <strong className="text-slate-600 font-bold block">No Signals Registered</strong>
            <span>Upload a SCADA CSV or Parquet file to trigger automated schema profiling &amp; signal mapping.</span>
          </div>
        ) : (
          mappings.map((item, idx) => (
            <div
              key={idx}
              className="p-3.5 bg-slate-50/80 hover:bg-slate-100/60 rounded-xl border border-slate-200/80 transition space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-mono text-xs">
                  <span className="text-slate-400 font-semibold uppercase text-[10px]">RAW COLUMN</span>
                  <span className="px-2 py-0.5 bg-slate-200/80 rounded font-bold text-slate-800">
                    {item.rawColumn}
                  </span>
                </div>
                <Badge variant={item.confidence >= 99 ? 'emerald' : 'amber'}>
                  {item.confidence}% High
                </Badge>
              </div>

              <div className="flex items-center gap-2 font-mono text-xs pl-2 border-l-2 border-sky-500">
                <span className="text-sky-600 font-bold">↳</span>
                {editingRow === item.rawColumn ? (
                  <div className="flex items-center gap-2 flex-1 flex-wrap">
                    <input
                      type="text"
                      value={customName}
                      onChange={(e) => setCustomName(e.target.value)}
                      placeholder="Type custom signal name..."
                      className="bg-white border border-sky-400 rounded px-2.5 py-1 text-xs font-semibold text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500 flex-1 min-w-[180px]"
                    />
                    <select
                      value=""
                      onChange={(e) => {
                        if (e.target.value) {
                          setCustomName(e.target.value);
                        }
                      }}
                      className="bg-slate-100 hover:bg-slate-200 border border-slate-300 rounded px-2 py-1 text-xs font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500 cursor-pointer"
                      title="Quick pick from standard preset canonical signals"
                    >
                      <option value="">-- Presets --</option>
                      {CANONICAL_SIGNAL_OPTIONS.map((opt) => (
                        <option key={opt.key} value={opt.key}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => handleSaveEdit(item.rawColumn)}
                      className="px-2 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-[11px] font-semibold flex items-center gap-1 transition"
                    >
                      <Check className="w-3.5 h-3.5" /> Save
                    </button>
                    <button
                      type="button"
                      onClick={handleCancelEdit}
                      className="px-2 py-1 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded text-[11px] font-semibold flex items-center gap-1 transition"
                    >
                      <X className="w-3.5 h-3.5" /> Cancel
                    </button>
                  </div>
                ) : (
                  <>
                    <span className="bg-white border border-slate-200 rounded px-2.5 py-1 text-xs font-semibold text-slate-900">
                      {item.mappedKey} ({item.targetType})
                    </span>
                    <button
                      type="button"
                      onClick={() => handleStartEdit(item.rawColumn, item.mappedKey)}
                      className="text-[11px] text-sky-600 hover:underline font-semibold ml-auto flex items-center gap-1"
                    >
                      <Sliders className="w-3 h-3" /> Edit
                    </button>
                  </>
                )}
              </div>

              {(item.sampleData || item.valueSpan || item.notes) && (
                <div className="text-[11px] font-mono text-slate-500 bg-white p-2 rounded border border-slate-100 flex flex-wrap gap-4">
                  {item.sampleData && (
                    <span>
                      <strong className="text-slate-700">SAMPLE DATA:</strong> {item.sampleData}
                    </span>
                  )}
                  {item.valueSpan && (
                    <span>
                      <strong className="text-slate-700">VALUE SPAN:</strong> {item.valueSpan}
                    </span>
                  )}
                  {item.notes && (
                    <span className="text-sky-700 font-medium">
                      🔀 {item.notes}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {onConfirmAll && mappings.length > 0 && (
        <button
          type="button"
          onClick={onConfirmAll}
          className="w-full py-2.5 bg-[#004874] hover:bg-[#003354] text-white text-xs font-semibold rounded-lg shadow-sm transition flex items-center justify-center gap-2"
        >
          <CheckCircle2 className="w-4 h-4" />
          <span>Confirm Signal Mappings &amp; Execute Ingestion</span>
        </button>
      )}
    </div>
  );
};
