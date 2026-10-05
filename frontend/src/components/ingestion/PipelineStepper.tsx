import React from 'react';
import { CheckCircle2, ArrowRight, FileSpreadsheet, Loader2 } from 'lucide-react';
import { Badge } from '../common/Badge';

interface PipelineStepperProps {
  currentStep?: number;
  fileName?: string;
  rowCount?: number;
  colCount?: number;
  statusText?: string;
  progress?: number;
  isIngesting?: boolean;
  onProceed?: () => void;
}

export const PipelineStepper: React.FC<PipelineStepperProps> = ({
  currentStep = 1,
  fileName = 'No file selected',
  rowCount = 0,
  colCount = 0,
  statusText,
  progress = 0,
  isIngesting = false,
  onProceed,
}) => {
  const steps = [
    { id: 1, label: 'UPLOAD' },
    { id: 2, label: 'PROFILE' },
    { id: 3, label: 'MAPPING' },
    { id: 4, label: 'INGEST' },
    { id: 5, label: 'QC VAL' },
    { id: 6, label: 'READY' },
  ];

  return (
    <div className="bg-white rounded-xl p-4 border border-slate-200/90 shadow-xs space-y-4">
      {/* File Card */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-100">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-sky-50 border border-sky-200/80 flex items-center justify-center text-sky-700 flex-shrink-0">
            <FileSpreadsheet className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-bold text-slate-900 font-mono">{fileName}</h4>
              <Badge variant={rowCount > 0 ? (isIngesting ? 'amber' : 'emerald') : 'slate'}>
                {isIngesting ? 'INGESTING' : rowCount > 0 ? 'ACTIVE' : 'READY'}
              </Badge>
            </div>
            <p className="text-xs text-slate-500 font-mono">
              {rowCount > 0 ? `${rowCount.toLocaleString()} rows • ${colCount} cols` : 'No dataset loaded'}
            </p>
          </div>
        </div>
      </div>

      {/* Stepper Status Header */}
      <div className="flex items-center justify-between text-xs font-mono">
        <span className="text-slate-500 uppercase font-semibold">INGESTION PIPELINE STATE</span>
        <span className="text-amber-700 font-bold">● Step {currentStep} of 6</span>
      </div>

      {/* Progress Bar when ingesting */}
      {isIngesting && (
        <div className="space-y-1.5 p-3 bg-sky-50 rounded-xl border border-sky-200">
          <div className="flex items-center justify-between text-xs font-mono">
            <span className="text-sky-900 font-bold flex items-center gap-1.5">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-600" />
              {statusText || 'Ingesting SCADA telemetry...'}
            </span>
            <span className="font-bold text-sky-700">{Math.round(progress * 100)}%</span>
          </div>
          <div className="w-full h-2 bg-sky-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-sky-600 transition-all duration-300 rounded-full"
              style={{ width: `${Math.min(100, Math.max(5, Math.round(progress * 100)))}%` }}
            />
          </div>
        </div>
      )}

      {/* Step Indicators */}
      <div className="grid grid-cols-6 gap-2">
        {steps.map((step) => {
          const isDone = step.id < currentStep;
          const isCurrent = step.id === currentStep;

          return (
            <div key={step.id} className="flex flex-col items-center gap-1.5 text-center">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-mono font-bold transition ${
                  isDone
                    ? 'bg-emerald-500 text-white'
                    : isCurrent
                    ? 'bg-amber-500 text-white ring-4 ring-amber-100'
                    : 'bg-slate-100 text-slate-400'
                }`}
              >
                {isDone ? <CheckCircle2 className="w-4 h-4" /> : step.id}
              </div>
              <span
                className={`text-[10px] font-mono font-semibold uppercase tracking-wider ${
                  isDone
                    ? 'text-emerald-700'
                    : isCurrent
                    ? 'text-amber-800'
                    : 'text-slate-400'
                }`}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Proceed Button */}
      {onProceed && !isIngesting && (
        <button
          onClick={onProceed}
          className="w-full py-2.5 bg-[#004874] hover:bg-[#003354] text-white text-xs font-semibold rounded-lg shadow-sm transition flex items-center justify-center gap-2 border border-sky-300/30"
        >
          <span>Confirm Signal Mappings &amp; Execute Ingestion</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};

