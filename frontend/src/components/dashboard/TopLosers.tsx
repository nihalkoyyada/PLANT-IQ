import React from 'react';
import { LossAnalysisResponse } from '../../types';
import { AlertTriangle, ArrowDownRight, Zap, Info, CheckCircle2 } from 'lucide-react';

interface TopLosersProps {
  data: LossAnalysisResponse | null;
  loading: boolean;
}

export const TopLosers: React.FC<TopLosersProps> = ({ data, loading }) => {
  if (loading) {
    return (
      <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs animate-pulse space-y-4">
        <div className="h-6 bg-slate-200 rounded w-1/3"></div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-20 bg-slate-100 rounded-lg"></div>
          ))}
        </div>
        <div className="h-48 bg-slate-100 rounded w-full"></div>
      </div>
    );
  }

  if (!data || !data.has_data) {
    return (
      <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs">
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle className="w-5 h-5 text-amber-500" />
          <h3 className="text-sm font-semibold uppercase text-slate-800 tracking-wider font-mono">
            Loss Analysis & Underperforming Inverters
          </h3>
        </div>
        <div className="h-40 flex items-center justify-center text-slate-400 font-mono text-sm border border-dashed border-slate-200 rounded-lg">
          No telemetry or loss analysis data available for the selected period.
        </div>
      </div>
    );
  }

  const hasPoa = Boolean(data.has_poa);
  const underperformingList = data.losers.filter((item) => (item.loss_mwh ?? 0) > 0);
  const hasDeficits = underperformingList.length > 0;

  const headerTitle = hasPoa
    ? hasDeficits
      ? `Loss Analysis & Top Underperforming Inverters (${data.range.toUpperCase()})`
      : `Inverter Performance & Baseline Compliance (${data.range.toUpperCase()})`
    : `Inverter Generation & Efficiency Analysis (${data.range.toUpperCase()})`;

  const rankingBadgeText = hasPoa
    ? hasDeficits
      ? 'Ranked by Inverter Energy Deficit (MWh)'
      : '● 100% Inverters Meeting Expected Baseline'
    : 'Ranked by Actual AC Generation (MWh)';

  const netShortfallMWh = data.net_shortfall_mwh ?? 0.0;
  const aggregateDeficitMWh = data.aggregate_inverter_deficit_mwh ?? data.total_loss_mwh ?? 0.0;
  const surplusMWh =
    data.total_expected_mwh !== null &&
    data.total_expected_mwh !== undefined &&
    data.total_actual_mwh > data.total_expected_mwh
      ? Number((data.total_actual_mwh - data.total_expected_mwh).toFixed(2))
      : 0;

  return (
    <div className="bg-white rounded-xl p-5 border border-slate-200/90 shadow-xs space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          {hasPoa ? (
            hasDeficits ? (
              <AlertTriangle className="w-5 h-5 text-rose-600" />
            ) : (
              <CheckCircle2 className="w-5 h-5 text-emerald-600" />
            )
          ) : (
            <Zap className="w-5 h-5 text-sky-600" />
          )}
          <h3 className="text-sm font-semibold uppercase text-slate-800 tracking-wider font-mono">
            {headerTitle}
          </h3>
        </div>
        <span
          className={`text-xs font-mono border px-2.5 py-1 rounded-md self-start sm:self-auto ${
            hasPoa && !hasDeficits
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : hasPoa && hasDeficits
              ? 'bg-rose-50 text-rose-700 border-rose-200'
              : 'bg-slate-100 text-slate-600 border-slate-200/80'
          }`}
        >
          {rankingBadgeText}
        </span>
      </div>

      {/* Provisional PR & Capacity Notice */}
      <div className="bg-slate-50 border border-slate-200/80 rounded-lg p-2.5 text-[11px] font-mono text-slate-600 flex items-start gap-2">
        <Info className="w-4 h-4 text-sky-600 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-slate-800">Provisional Capacity Baseline: </span>
          PR and expected generation use the configured plant capacity (28,280.55 kWp DC / 27,500 kW AC), empirically derived from operating summer p99 readings. Authoritative manufacturer STC nameplate records are unverified. PR is reported without artificial clamping.
        </div>
      </div>

      {/* Explanatory Banner when POA Irradiance Baseline is Missing */}
      {!hasPoa && (
        <div className="bg-amber-50/90 border border-amber-200/80 rounded-lg p-3 text-xs font-mono text-amber-900 flex items-start gap-2.5">
          <Info className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-bold">POA Irradiance Baseline Unavailable: </span>
            Solar resource reference energy and energy loss metrics cannot be calculated without plane-of-array irradiance telemetry. Displaying measured AC generation and inverter conversion efficiency (&eta;).
          </div>
        </div>
      )}

      {/* Overview Metric Cards distinguishing Net Shortfall from Aggregate Inverter Deficit */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {/* Card 1: Expected Generation */}
        <div className="bg-slate-50 p-3 rounded-lg border border-slate-200/70">
          <span className="text-[11px] font-mono uppercase text-slate-500 font-medium">Expected Generation</span>
          <div className="text-lg font-bold text-slate-900 font-mono mt-0.5">
            {data.total_expected_mwh !== null && data.total_expected_mwh !== undefined ? (
              <>
                {data.total_expected_mwh} <span className="text-xs font-normal text-slate-500">MWh</span>
              </>
            ) : (
              <span className="text-slate-400 font-normal">N/A</span>
            )}
          </div>
          <span className="text-[10px] font-mono text-slate-400 mt-1 block">Solar Resource Baseline</span>
        </div>

        {/* Card 2: Actual Delivered */}
        <div className="bg-emerald-50/60 p-3 rounded-lg border border-emerald-100">
          <span className="text-[11px] font-mono uppercase text-emerald-700 font-medium">Actual Delivered</span>
          <div className="text-lg font-bold text-emerald-900 font-mono mt-0.5">
            {data.total_actual_mwh} <span className="text-xs font-normal text-emerald-600">MWh</span>
          </div>
          <span className="text-[10px] font-mono text-emerald-700 mt-1 block">
            {surplusMWh > 0 ? `+${surplusMWh} MWh Surplus` : 'AC Exported'}
          </span>
        </div>

        {/* Card 3: Net Plant Shortfall */}
        <div className="bg-blue-50/60 p-3 rounded-lg border border-blue-100">
          <span className="text-[11px] font-mono uppercase text-blue-700 font-medium">Net Plant Shortfall</span>
          <div className="text-lg font-bold text-blue-900 font-mono mt-0.5">
            {hasPoa ? (
              <>
                {netShortfallMWh.toFixed(2)} <span className="text-xs font-normal text-blue-600">MWh</span>
              </>
            ) : (
              <span className="text-slate-400 font-normal">N/A</span>
            )}
          </div>
          <span className="text-[10px] font-mono text-blue-700 mt-1 block">
            {netShortfallMWh === 0 ? '● Zero Shortfall (Surplus)' : `${data.net_shortfall_pct ?? 0}% Plant Shortfall`}
          </span>
        </div>

        {/* Card 4: Aggregate Inverter Deficit */}
        <div className="bg-rose-50/60 p-3 rounded-lg border border-rose-100">
          <span className="text-[11px] font-mono uppercase text-rose-700 font-medium">Inverter Deficits (∑)</span>
          <div className="text-lg font-bold text-rose-900 font-mono mt-0.5">
            {hasPoa ? (
              <>
                {aggregateDeficitMWh.toFixed(2)} <span className="text-xs font-normal text-rose-600">MWh</span>
              </>
            ) : (
              <span className="text-slate-400 font-normal">N/A</span>
            )}
          </div>
          <span className="text-[10px] font-mono text-rose-700 mt-1 block">
            {aggregateDeficitMWh === 0
              ? '● 0 MWh (All Units Nominal)'
              : `${data.total_loss_pct ?? 0}% Aggregate Deficit`}
          </span>
        </div>
      </div>

      {/* Metric Distinction Footnote */}
      <div className="text-[11px] font-mono text-slate-500 bg-slate-50 px-3 py-2 rounded-lg border border-slate-200/60 flex items-start gap-2">
        <Info className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-slate-700">Metric Definitions: </span>
          <em>Net Plant Shortfall</em> is the overall plant generation deficit relative to expected reference energy (max(∑Expected &minus; ∑Actual, 0)).
          <em> Inverter Deficits (∑)</em> is the aggregate shortfall across individual underperforming inverters (∑ max(Expected<sub>i</sub> &minus; Actual<sub>i</sub>, 0)) before offsetting by overperforming units.
        </div>
      </div>

      {/* Inverter Table OR Empty State */}
      {hasPoa && !hasDeficits ? (
        <div className="bg-emerald-50/40 border border-emerald-200/80 rounded-xl p-8 text-center space-y-2.5 font-mono">
          <div className="inline-flex p-3 rounded-full bg-emerald-100 text-emerald-700">
            <CheckCircle2 className="w-6 h-6" />
          </div>
          <h4 className="text-sm font-bold text-slate-800 uppercase tracking-wide">
            No Underperforming Assets Detected
          </h4>
          <p className="text-xs text-slate-600 max-w-lg mx-auto">
            All plant inverters met or exceeded their expected generation baseline during this {data.range.toUpperCase()} reporting window. Net plant shortfall and aggregate inverter deficits are both 0.00 MWh.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto custom-scrollbar">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 font-mono text-slate-600">
                <th className="py-2.5 px-3 font-semibold w-16 text-center">Rank</th>
                <th className="py-2.5 px-3 font-semibold">Inverter / Asset</th>
                <th className="py-2.5 px-3 font-semibold text-right">Expected (MWh)</th>
                <th className="py-2.5 px-3 font-semibold text-right">Actual (MWh)</th>
                <th className="py-2.5 px-3 font-semibold text-right">Inverter Deficit</th>
                <th className="py-2.5 px-3 font-semibold text-right">Deficit %</th>
                <th
                  className="py-2.5 px-3 font-semibold text-center cursor-help"
                  title={
                    hasPoa
                      ? 'Provisional Performance Ratio (IEC 61724-1) based on configured 28.28 MWp capacity'
                      : 'Total-period Inverter AC/DC Energy Conversion Efficiency (Actual AC MWh / Integrated DC MWh)'
                  }
                >
                  {hasPoa ? 'PR (Provisional)*' : 'PR / Efficiency'}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(hasDeficits ? underperformingList : data.losers).map((item) => (
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
                  <td className="py-2.5 px-3 text-right text-slate-600">
                    {item.expected_mwh !== null && item.expected_mwh !== undefined ? (
                      `${item.expected_mwh} MWh`
                    ) : (
                      <span className="text-slate-400 font-normal">N/A</span>
                    )}
                  </td>
                  <td className="py-2.5 px-3 text-right text-emerald-700 font-medium">{item.actual_mwh} MWh</td>
                  <td className="py-2.5 px-3 text-right text-rose-600 font-bold">
                    {hasPoa && item.loss_mwh !== null && item.loss_mwh !== undefined && item.loss_mwh > 0 ? (
                      <div className="flex items-center justify-end gap-1">
                        <ArrowDownRight className="w-3.5 h-3.5" />
                        <span>{item.loss_mwh} MWh</span>
                      </div>
                    ) : hasPoa ? (
                      <span className="text-emerald-600 font-normal">0.00 MWh</span>
                    ) : (
                      <span className="text-slate-400 font-normal">N/A</span>
                    )}
                  </td>
                  <td className="py-2.5 px-3 text-right text-rose-600 font-bold">
                    {item.loss_pct !== null && item.loss_pct !== undefined ? (
                      `${item.loss_pct}%`
                    ) : (
                      <span className="text-slate-400 font-normal">N/A</span>
                    )}
                  </td>
                  <td className="py-2.5 px-3 text-center">
                    {item.pr !== null && item.pr !== undefined ? (
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                          item.pr >= 85
                            ? 'bg-emerald-100 text-emerald-800'
                            : item.pr >= 75
                            ? 'bg-sky-100 text-sky-800'
                            : 'bg-rose-100 text-rose-800'
                        }`}
                      >
                        {item.pr}% PR
                      </span>
                    ) : item.efficiency !== null && item.efficiency !== undefined ? (
                      <span
                        title="Inverter Energy Conversion Efficiency (η = Actual AC MWh / Integrated DC MWh)"
                        className="inline-block px-2 py-0.5 rounded text-[11px] font-semibold bg-sky-100 text-sky-800 cursor-help"
                      >
                        {item.efficiency}% η
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
      )}
    </div>
  );
};
