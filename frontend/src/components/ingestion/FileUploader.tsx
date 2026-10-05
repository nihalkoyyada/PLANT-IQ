import React, { useState } from 'react';
import { UploadCloud, FileText, Loader2 } from 'lucide-react';
import { Badge } from '../common/Badge';
import { UploadProgress } from '../../types';

interface FileUploaderProps {
  onFileSelect: (file: File) => void;
  activeFileName?: string;
  isProfiling?: boolean;
  isUploading?: boolean;
  uploadProgress?: UploadProgress | null;
}

export const FileUploader: React.FC<FileUploaderProps> = ({
  onFileSelect,
  activeFileName = 'surya_solar.csv',
  isProfiling = false,
  isUploading = false,
  uploadProgress = null,
}) => {
  const [dragActive, setDragActive] = useState(false);

  const isBusy = isUploading || isProfiling;

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    if (isBusy) return;
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      onFileSelect(e.dataTransfer.files[0]);
    }
  };

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="space-y-4">
      {/* Upload Header Banner */}
      <div className="bg-sky-50/80 rounded-xl p-4 border border-sky-100 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <UploadCloud className="w-4 h-4 text-sky-700" />
            <span className="text-[10px] font-mono uppercase font-bold text-sky-800 tracking-wider">
              SCADA INGESTION STREAM
            </span>
          </div>
          <h3 className="text-sm font-bold text-slate-900">Telemetry Data Upload</h3>
          <p className="text-xs text-slate-600">
            Ingest raw SCADA time-series files (CSV, Parquet, ZIP up to 2GB) into Surya Solar Plant database.
          </p>
        </div>
      </div>

      {/* Drag & Drop Area */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!isBusy) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center text-center transition ${
          dragActive ? 'border-sky-500 bg-sky-50/50' : 'border-sky-200 bg-white'
        }`}
      >
        <div className="w-12 h-12 rounded-2xl bg-sky-50 flex items-center justify-center text-sky-600 mb-3 shadow-xs">
          {isBusy ? (
            <Loader2 className="w-6 h-6 animate-spin text-sky-700" />
          ) : (
            <UploadCloud className="w-6 h-6" />
          )}
        </div>

        <h4 className="text-sm font-bold text-slate-800 mb-1">
          {isUploading
            ? uploadProgress?.status || 'Uploading File...'
            : isProfiling
            ? 'Profiling File Schema & Signals...'
            : 'Drop CSV, Parquet or ZIP files here'}
        </h4>

        {isUploading && uploadProgress ? (
          <div className="w-full max-w-xs space-y-2 my-2">
            <div className="w-full bg-slate-200 h-2 rounded-full overflow-hidden">
              <div
                className="bg-sky-600 h-full transition-all duration-300 rounded-full"
                style={{ width: `${uploadProgress.percentage}%` }}
              />
            </div>
            <div className="flex justify-between text-[11px] font-mono text-slate-600">
              <span>{uploadProgress.percentage}%</span>
              <span>
                {formatBytes(uploadProgress.uploadedBytes)} / {formatBytes(uploadProgress.totalBytes)}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-slate-500 max-w-sm mb-4">
            Automated timestamp detection & telemetry schemas (Up to 2GB)
          </p>
        )}

        <label
          className={`cursor-pointer inline-flex items-center gap-2 px-4 py-2 bg-[#004874] hover:bg-[#003354] text-white text-xs font-semibold rounded-lg shadow-sm transition mb-3 ${
            isBusy ? 'opacity-60 pointer-events-none' : ''
          }`}
        >
          <FileText className="w-4 h-4" />
          <span>{isBusy ? 'Processing Upload...' : 'Browse Local Telemetry Files'}</span>
          <input
            type="file"
            accept=".csv,.parquet,.zip"
            className="hidden"
            disabled={isBusy}
            onChange={(e) => {
              if (e.target.files && e.target.files[0]) {
                onFileSelect(e.target.files[0]);
              }
            }}
          />
        </label>

        <div className="flex flex-wrap items-center justify-center gap-2 text-[10px] font-mono text-slate-400">
          <Badge variant="slate">Max 2GB (Chunked &gt;50MB)</Badge>
          <Badge variant="slate">15m / 5m / 1s intervals</Badge>
          <Badge variant="navy">Canonical Profiler v4.2</Badge>
        </div>
      </div>
    </div>
  );
};
