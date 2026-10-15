import React, { useEffect, useState } from 'react';
import { AlertOctagon, CheckCircle2 } from 'lucide-react';
import { Badge } from '../common/Badge';
import { getAnomalySummary } from '../../api/anomalies';
import { AnomalySummary } from '../../types';

interface AnomalyBannerProps {
  plantId?: string;
  summary?: AnomalySummary | null;
  onTriage?: () => void;
}

export const AnomalyBanner: React.FC<AnomalyBannerProps> = ({ plantId, summary, onTriage }) => {
  const [summaryData, setSummaryData] = useState<AnomalySummary | null>(summary || null);
  const [isLoading, setIsLoading] = useState<boolean>(!summary);
  const [hasError, setHasError] = useState<boolean>(false);

  useEffect(() => {
    if (summary) {
      setSummaryData(summary);
      setIsLoading(false);
      setHasError(false);
      return;
    }

    let isMounted = true;
    setIsLoading(true);
    setHasError(false);

    async function fetchSummary() {
      try {
        const data = await getAnomalySummary(plantId);
        if (isMounted) {
          setSummaryData(data);
          setIsLoading(false);
        }
      } catch (err) {
        if (isMounted) {
          setHasError(true);
          setIsLoading(false);
        }
      }
    }

    fetchSummary();
    return () => {
      isMounted = false;
    };
  }, [plantId, summary]);

  // Derived live counts
  const openCount = summaryData?.open_count ?? 0;
  const criticalCount = summaryData?.critical_count ?? 0;
  const highCount = summaryData?.high_count ?? 0;
  const mediumCount = summaryData?.medium_count ?? 0;
  const lowCount = summaryData?.low_count ?? 0;
  const isAllNominal = summaryData !== null && openCount === 0;

  if (isLoading && !summaryData) {
    return (
      <div className="bg-slate-50/90 rounded-xl p-3.5 border border-slate-200/80 flex items-center justify-between shadow-xs animate-pulse">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-slate-200 flex items-center justify-center text-slate-400 flex-shrink-0" />
          <div className="space-y-1">
            <div className="h-3.5 w-48 bg-slate-200 rounded" />
            <div className="h-2.5 w-72 bg-slate-100 rounded" />
          </div>
        </div>
      </div>
    );
  }

  if (hasError && !summaryData) {
    return (
      <div className="bg-amber-50/90 rounded-xl p-3.5 border border-amber-200/80 flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-amber-100 border border-amber-300/80 flex items-center justify-center text-amber-600 flex-shrink-0">
            <AlertOctagon className="w-5 h-5" />
          </div>
          <div>
            <h4 className="text-xs font-bold text-amber-950">Anomaly Summary Unavailable</h4>
            <p className="text-[11px] text-amber-700">Telemetry anomaly status could not be synchronized from API service.</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="amber">STATUS OFFLINE</Badge>
          {onTriage && (
            <button
              onClick={onTriage}
              className="ml-2 text-xs font-semibold px-2.5 py-1 bg-amber-600 hover:bg-amber-700 text-white rounded-md transition shadow-xs"
            >
              Inbox
            </button>
          )}
        </div>
      </div>
    );
  }

  if (isAllNominal) {
    return (
      <div className="bg-emerald-50/90 rounded-xl p-3.5 border border-emerald-200/80 flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-emerald-100 border border-emerald-300/80 flex items-center justify-center text-emerald-600 flex-shrink-0">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <h4 className="text-xs font-bold text-emerald-950">0 Active Telemetry Anomalies</h4>
            <p className="text-[11px] text-emerald-700">All plant inverters operating within nominal baseline parameters</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <Badge variant="emerald">ALL NOMINAL</Badge>
          {onTriage && (
            <button
              onClick={onTriage}
              className="ml-2 text-xs font-semibold px-2.5 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-md transition shadow-xs"
            >
              Inbox
            </button>
          )}
        </div>
      </div>
    );
  }

  const titleText = summaryData !== null
    ? `${openCount} Active Telemetry Anomalies`
    : 'Active Telemetry Anomalies';

  const subtitleText = summaryData !== null
    ? (criticalCount > 0 && highCount > 0
        ? `Live triage required: ${criticalCount} critical, ${highCount} high priority unresolved`
        : criticalCount > 0
        ? `Live triage required: ${criticalCount} critical unresolved`
        : highCount > 0
        ? `Live triage required: ${highCount} high priority unresolved`
        : openCount > 0
        ? `Live triage required on ${openCount} unresolved items`
        : 'Live triage required on active anomalies')
    : 'Live triage required on detected plant deviations';

  return (
    <div className="bg-rose-50/90 rounded-xl p-3.5 border border-rose-200/80 flex items-center justify-between shadow-xs">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-rose-100 border border-rose-300/80 flex items-center justify-center text-rose-600 flex-shrink-0">
          <AlertOctagon className="w-5 h-5 animate-pulse" />
        </div>
        <div>
          <h4 className="text-xs font-bold text-rose-950">{titleText}</h4>
          <p className="text-[11px] text-rose-700">{subtitleText}</p>
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        {criticalCount > 0 && <Badge variant="rose">{criticalCount} CRIT</Badge>}
        {highCount > 0 && <Badge variant="amber">{highCount} H</Badge>}
        {mediumCount > 0 && <Badge variant="blue">{mediumCount} M</Badge>}
        {lowCount > 0 && <Badge variant="slate">{lowCount} L</Badge>}
        {summaryData === null && (
          <>
            <Badge variant="rose">ALERT</Badge>
          </>
        )}
        {onTriage && (
          <button
            onClick={onTriage}
            className="ml-2 text-xs font-semibold px-2.5 py-1 bg-rose-600 hover:bg-rose-700 text-white rounded-md transition shadow-xs"
          >
            Triage
          </button>
        )}
      </div>
    </div>
  );
};
