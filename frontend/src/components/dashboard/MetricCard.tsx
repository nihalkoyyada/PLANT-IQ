import React from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { Badge } from '../common/Badge';

interface MetricCardProps {
  title: string;
  value: string | number;
  unit?: string;
  change?: string;
  isPositive?: boolean;
  subtitle?: string;
  badgeText?: string;
  badgeVariant?: 'emerald' | 'blue' | 'amber' | 'rose' | 'navy';
  progress?: number;
  icon?: React.ReactNode;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  unit,
  change,
  isPositive = true,
  subtitle,
  badgeText,
  badgeVariant = 'emerald',
  progress,
  icon,
}) => {
  return (
    <div className="bg-white rounded-xl p-4 border border-slate-200/90 shadow-xs flex flex-col justify-between hover:shadow-md transition">
      <div className="flex items-start justify-between mb-2">
        <div className="space-y-0.5">
          <span className="text-[11px] font-mono font-semibold uppercase text-slate-500 tracking-wider">
            {title}
          </span>
          {icon && <div className="text-sky-600">{icon}</div>}
        </div>
        {badgeText && <Badge variant={badgeVariant}>{badgeText}</Badge>}
      </div>

      <div className="my-1 flex items-baseline gap-1.5">
        <span className="text-2xl font-bold text-slate-900 tracking-tight font-sans">{value}</span>
        {unit && <span className="text-xs font-semibold text-slate-500 font-mono">{unit}</span>}
      </div>

      <div className="flex items-center justify-between text-xs pt-1 border-t border-slate-100 mt-2">
        {change && (
          <div className={`flex items-center gap-1 font-mono font-medium ${isPositive ? 'text-emerald-600' : 'text-rose-600'}`}>
            {isPositive ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
            <span>{change}</span>
          </div>
        )}
        {subtitle && <span className="text-[11px] text-slate-400 font-mono ml-auto">{subtitle}</span>}
      </div>

      {progress !== undefined && (
        <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden mt-2">
          <div
            className="bg-[#004874] h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(progress, 100)}%` }}
          />
        </div>
      )}
    </div>
  );
};
