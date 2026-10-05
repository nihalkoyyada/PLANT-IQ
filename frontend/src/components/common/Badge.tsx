import React from 'react';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'emerald' | 'blue' | 'amber' | 'rose' | 'slate' | 'navy';
  size?: 'sm' | 'md';
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'blue',
  size = 'sm',
  className = '',
}) => {
  const variantStyles = {
    emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200/60',
    blue: 'bg-sky-50 text-sky-700 border-sky-200/60',
    amber: 'bg-amber-50 text-amber-700 border-amber-200/60',
    rose: 'bg-rose-50 text-rose-700 border-rose-200/60',
    slate: 'bg-slate-100 text-slate-600 border-slate-200',
    navy: 'bg-[#004874]/10 text-[#004874] border-[#004874]/20',
  };

  const sizeStyles = {
    sm: 'text-[11px] px-2 py-0.5 font-mono font-medium',
    md: 'text-xs px-2.5 py-1 font-mono font-medium',
  };

  return (
    <span
      className={`inline-flex items-center gap-1 border rounded-md uppercase tracking-wider ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
    >
      {children}
    </span>
  );
};
