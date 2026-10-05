import React from 'react';
import { AlertOctagon } from 'lucide-react';
import { Badge } from '../common/Badge';

export const AnomalyBanner: React.FC<{ onTriage?: () => void }> = ({ onTriage }) => {
  return (
    <div className="bg-rose-50/90 rounded-xl p-3.5 border border-rose-200/80 flex items-center justify-between shadow-xs">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-rose-100 border border-rose-300/80 flex items-center justify-center text-rose-600 flex-shrink-0">
          <AlertOctagon className="w-5 h-5 animate-pulse" />
        </div>
        <div>
          <h4 className="text-xs font-bold text-rose-950">7 Active Telemetry Anomalies</h4>
          <p className="text-[11px] text-rose-700">Live triage required on 2 blocks</p>
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        <Badge variant="rose">2 H</Badge>
        <Badge variant="amber">3 M</Badge>
        <Badge variant="blue">2 L</Badge>
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
