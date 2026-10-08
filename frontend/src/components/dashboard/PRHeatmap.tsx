import React, { useState } from 'react';
import { PRHeatmapResponse, PRHeatmapCell } from '../../types';
import { Activity, Info } from 'lucide-react';

interface PRHeatmapProps {
  data: PRHeatmapResponse | null;
  loading: boolean;
}

export const PRHeatmap: React.FC<PRHeatmapProps> = ({ data, loading }) => {
  const [activeTooltip, setActiveTooltip] = useState<{
    inverter: string;
    cell: PRHeatmapCell;
    x: number;
    y: number;
  } | null>(null);

  if (loading) {
    return (
      <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs animate-pulse">
        <div className="h-6 bg-slate-200 rounded w-1/4 mb-4"></div>
        <div className="h-48 bg-slate-100 rounded w-full"></div>
      </div>
    );
  }

  if (!data || !data.inverters || data.inverters.length === 0) {
    return (
      <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-sky-600" />
            <h3 className="text-sm font-semibold uppercase text-slate-800 tracking-wider">
              Performance Ratio (PR) Heatmap
            </h3>
          </div>
        </div>
        <div className="h-40 flex items-center justify-center text-slate-400 font-mono text-sm border border-dashed border-slate-200 rounded-lg">
          No PR heatmap data available for the selected period.
        </div>
      </div>
    );
  }

  const getCellColor = (cell: PRHeatmapCell) => {
    if (!cell.has_data || cell.pr === null) {
      return 'bg-slate-100 text-slate-400 border border-slate-200/60';
    }
    if (cell.pr >= 85) {
      return 'bg-emerald-500 hover:bg-emerald-600 text-white font-medium shadow-2xs';
    }
    if (cell.pr >= 75) {
      return 'bg-sky-500 hover:bg-sky-600 text-white font-medium shadow-2xs';
    }
    return 'bg-rose-500 hover:bg-rose-600 text-white font-medium shadow-2xs';
  };

  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs relative">
      {/* Header & Legend */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-sky-600" />
          <h3 className="text-sm font-semibold uppercase text-slate-800 tracking-wider font-mono">
            Performance Ratio (PR) Heatmap ({data.range.toUpperCase()})
          </h3>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 text-xs font-mono">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-xs bg-emerald-500 inline-block"></span>
            <span className="text-slate-600">≥85% Healthy</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-xs bg-sky-500 inline-block"></span>
            <span className="text-slate-600">75-84% Moderate</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-xs bg-rose-500 inline-block"></span>
            <span className="text-slate-600">&lt;75% Degraded</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-xs bg-slate-200 border border-slate-300 inline-block"></span>
            <span className="text-slate-500">N/A Missing</span>
          </div>
        </div>
      </div>

      {/* Grid Container */}
      <div className="overflow-x-auto custom-scrollbar max-h-[460px]">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/80 sticky top-0 z-10">
              <th className="py-2.5 px-3 font-mono font-semibold text-slate-700 uppercase tracking-wider sticky left-0 bg-slate-50 z-20 min-w-[130px] border-r border-slate-200">
                Inverter
              </th>
              {data.time_buckets.map((bucket, idx) => (
                <th
                  key={idx}
                  className="py-2.5 px-1.5 text-center font-mono font-medium text-slate-600 min-w-[52px] border-r border-slate-100 last:border-r-0"
                >
                  {bucket}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.inverters.map((row) => (
              <tr key={row.asset_id} className="hover:bg-slate-50/50 transition-colors">
                <td className="py-1.5 px-3 font-mono font-semibold text-slate-800 whitespace-nowrap sticky left-0 bg-white z-10 border-r border-slate-200 shadow-xs">
                  {row.asset_name}
                </td>
                {row.cells.map((cell, cIdx) => (
                  <td
                    key={cIdx}
                    className="p-1 text-center min-w-[52px]"
                    onMouseEnter={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      setActiveTooltip({
                        inverter: row.asset_name,
                        cell,
                        x: rect.left + rect.width / 2,
                        y: rect.top - 8,
                      });
                    }}
                    onMouseLeave={() => setActiveTooltip(null)}
                  >
                    <div
                      className={`h-7 rounded-xs flex items-center justify-center font-mono text-[11px] cursor-pointer transition-transform hover:scale-105 ${getCellColor(
                        cell
                      )}`}
                    >
                      {cell.has_data && cell.pr !== null ? `${cell.pr}%` : 'N/A'}
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Floating Tooltip */}
      {activeTooltip && (
        <div
          className="fixed z-50 transform -translate-x-1/2 -translate-y-full bg-slate-900 text-white p-2.5 rounded-lg shadow-xl border border-slate-700 pointer-events-none text-xs font-mono w-48"
          style={{ top: `${activeTooltip.y}px`, left: `${activeTooltip.x}px` }}
        >
          <div className="flex items-center justify-between font-bold border-b border-slate-700 pb-1 mb-1 text-sky-400">
            <span>{activeTooltip.inverter}</span>
            <span className="text-[10px] text-slate-400">{activeTooltip.cell.label}</span>
          </div>
          {activeTooltip.cell.has_data && activeTooltip.cell.pr !== null ? (
            <div className="space-y-0.5">
              <div className="flex justify-between">
                <span className="text-slate-400">PR Ratio:</span>
                <span
                  className={
                    activeTooltip.cell.pr >= 85
                      ? 'text-emerald-400 font-bold'
                      : activeTooltip.cell.pr >= 75
                      ? 'text-sky-400 font-bold'
                      : 'text-rose-400 font-bold'
                  }
                >
                  {activeTooltip.cell.pr}%
                </span>
              </div>
              {activeTooltip.cell.ac_kw !== null && (
                <div className="flex justify-between">
                  <span className="text-slate-400">AC Power:</span>
                  <span>{activeTooltip.cell.ac_kw} kW</span>
                </div>
              )}
              {activeTooltip.cell.dc_kw !== null && (
                <div className="flex justify-between">
                  <span className="text-slate-400">DC Power:</span>
                  <span>{activeTooltip.cell.dc_kw} kW</span>
                </div>
              )}
            </div>
          ) : (
            <div className="text-slate-400 text-center py-1 flex items-center justify-center gap-1">
              <Info className="w-3.5 h-3.5 text-amber-400" />
              <span>Telemetry Missing</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
