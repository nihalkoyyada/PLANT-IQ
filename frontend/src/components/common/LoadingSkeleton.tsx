import React from 'react';

export const LoadingSkeleton: React.FC<{ rows?: number }> = ({ rows = 3 }) => {
  return (
    <div className="space-y-3 animate-pulse p-4 bg-white rounded-xl border border-slate-200">
      <div className="h-4 bg-slate-200 rounded w-1/3"></div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-3 bg-slate-100 rounded w-full"></div>
      ))}
    </div>
  );
};
