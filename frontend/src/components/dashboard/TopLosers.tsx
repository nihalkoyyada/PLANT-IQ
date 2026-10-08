import React from 'react';
import { LossAnalysisResponse } from '../../types';
import { AlertTriangle, ArrowDownRight, Zap, CheckCircle } from 'lucide-react';

interface TopLosersProps {
  data: LossAnalysisResponse | null;
  loading: boolean;
}

export const TopLosers: React.FC<TopLosersProps> = ({ data, loading }) => {
  if (loading) {
    return (
      <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs animate-pulse space-y-4">
        <div className="h-6 bg-slate-200 rounded w-1/3"></div>
        <div className="grid grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-16 bg-slate-100 rounded-lg"></div>
          ))}
        </div>
        <div className="h-48 bg-slate-100 rounded w-full"></div>
      </div>
    );
  }

  if (!data || !data.has_data || data.losers.length === 0) {
    return (
      <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs">
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="w-5 h-5 text-amber-500" />
          <h3 className="text-sm font-semibold uppercase text-slate-800 tracking-wider font-mono">
            Loss Analysis & Top Underperforming Assets
          </h3>
        </div>
        <div className="h-40 flex items-center justify-center text-slate-400 font-mono text-sm border border-dashed border-slate-200 rounded-lg">
          No loss data available for the selected period.
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-rose-600" />
          <h3 className="text-sm font-semibold uppercase text-slate-800 tracking-wider font-mono">
            Loss Analysis & Top Underperforming Assets ({data.range.toUpperCase()})
          </h3>
        </div>
        <span className="text-xs font-mono text-slate-500 bg-slate-100 px-2.5 py-1 rounded-md self-start sm:self-auto">
          Ranked by Actual Energy Loss (MWh)
        </span>
      </div>

      {/* Overview Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-slate-50 p-3 rounded-lg border border-slate-200/70">
          <span className="text-[11px] font-mono uppercase text-slate-500 font-medium">Expected Generation</span>
          <div className="text-lg font-bold text-slate-900 font-mono mt-0.5">{data.total_expected_mwh} <span className="text-xs font-normal text-slate-500">MWh</span></div>
        </div>
        <div className="bg-emerald-50/60 p-3 rounded-lg border border-emerald-100">
          <span className="text-[11px] font-mono uppercase text-emerald-700 font-medium">Actual Delivered</span>
          <div className="text-lg font-bold text-emerald-900 font-mono mt-0.5">{data.total_actual_mwh} <span className="text-xs font-normal text-emerald-600">MWh</span></div>
        </div>
        <div className="bg-rose-50/60 p-3 rounded-lg border border-rose-100">
          <span className="text-[11px] font-mono uppercase text-rose-700 font-medium">Total Energy Loss</span>
          <div className="text-lg font-bold text-rose-900 font-mono mt-0.5">{data.total_loss_mwh} <span className="text-xs font-normal text-rose-600">MWh</span></div>
        </div>
        <div className="bg-amber-50/60 p-3 rounded-lg border border-amber-100">
          <span className="text-[11px] font-mono uppercase text-amber-700 font-medium font-mono">Total Loss Ratio</span>
          <div className="text-lg font-bold text-amber-900 font-mono mt-0.5">{data.total_loss_pct}%</div>
        </div>
      </div>

      {/* Top Losers Table */}
      <div className="overflow-x-auto custom-scrollbar">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 font-mono text-slate-600">
              <th className="py-2.5 px-3 font-semibold w-16 text-center">Rank</th>
              <th className="py-2.5 px-3 font-semibold">Inverter / Asset</th>
              <th className="py-2.5 px-3 font-semibold text-right">Expected (MWh)</th>
              <th className="py-2.5 px-3 font-semibold text-right">Actual (MWh)</th>
              <th className="py-2.5 px-3 font-semibold text-right">Energy Loss</th>
              <th className="py-2.5 px-3 font-semibold text-right">Loss %</th>
              <th className="py-2.5 px-3 font-semibold text-center">PR Ratio</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.losers.map((item) => (
              <tr key={item.asset_id} className="hover:bg-slate-50/80 transition-colors font-mono">
                <td className="py-2.5 px-3 text-center">
                  <span
                    className={`inline-flex items-center justify-center w-6 h-6 rounded-full font-bold text-[11px] ${
                      item.rank === 1
                        ? 'bg-rose-100 text-rose-700 border border-rose-300'
                        : item.rank === 2
                        ? 'bg-amber-100 text-amber-700 border border-amber-300'
                        : item.rank === 3
                        ? 'bg-amber-50 text-amber-600 border border-amber-200'
                        : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {item.rank}
                  </span>
                </td>
                <td className="py-2.5 px-3 font-semibold text-slate-800">
                  <div className="flex items-center gap-2">
                    <Zap className="w-3.5 h-3.5 text-sky-600" />
                    <span>{item.asset_name}</span>
                  </div>
                </td>
                <td className="py-2.5 px-3 text-right text-slate-600">{item.expected_mwh} MWh</td>
                <td className="py-2.5 px-3 text-right text-emerald-700 font-medium">{item.actual_mwh} MWh</td>
                <td className="py-2.5 px-3 text-right text-rose-600 font-bold">
                  <div className="flex items-center justify-end gap-1">
                    <ArrowDownRight className="w-3.5 h-3.5" />
                    <span>{item.loss_mwh} MWh</span>
                  </div>
                </td>
                <td className="py-2.5 px-3 text-right text-rose-600 font-bold">{item.loss_pct}%</td>
                <td className="py-2.5 px-3 text-center">
                  {item.pr !== null ? (
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                        item.pr >= 85
                          ? 'bg-emerald-100 text-emerald-800'
                          : item.pr >= 75
                          ? 'bg-sky-100 text-sky-800'
                          : 'bg-rose-100 text-rose-800'
                      }`}
                    >
                      {item.pr}%
                    </span>
                  ) : (
                    <span className="text-slate-400 font-normal">N/A</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
