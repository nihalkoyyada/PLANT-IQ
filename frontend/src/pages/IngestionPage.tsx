import React, { useEffect, useState, useCallback } from 'react';
import { FileUploader } from '../components/ingestion/FileUploader';
import { PipelineStepper } from '../components/ingestion/PipelineStepper';
import { SignalMapper, ColumnMappingItem } from '../components/ingestion/SignalMapper';
import { Badge } from '../components/common/Badge';
import { profileFile } from '../api/ai';
import { getFiles, uploadFile } from '../api/files';
import {
  getIngestionJobs,
  getIngestionJob,
  runIngestionJob,
  createIngestionJob,
  getMappingTemplates,
  createMappingTemplate,
} from '../api/ingestion';
import { AIProfileResponse, FileRecord, IngestionJob, UploadProgress } from '../types';
import { Clock, AlertCircle, ShieldAlert, Loader2, RotateCcw, Check } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { resetSCADAData } from '../api/dev';

export const IngestionPage: React.FC = () => {
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const userRole = user?.role?.toLowerCase() || 'viewer';
  const canUpload = userRole === 'admin' || userRole === 'engineer';
  const isAdmin = userRole === 'admin';

  const [activeStep, setActiveStep] = useState<number>(1);
  const [selectedFileName, setSelectedFileName] = useState<string>('No file selected');
  const [currentFileRecord, setCurrentFileRecord] = useState<FileRecord | null>(null);
  const [profileData, setProfileData] = useState<AIProfileResponse | null>(null);
  const [customMappings, setCustomMappings] = useState<Record<string, string>>({});

  const [files, setFiles] = useState<FileRecord[]>([]);
  const [filesLoading, setFilesLoading] = useState<boolean>(false);
  const [filesError, setFilesError] = useState<string | null>(null);

  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [loadingProfile, setLoadingProfile] = useState<boolean>(false);
  const [ingesting, setIngesting] = useState<boolean>(false);
  const [ingestProgress, setIngestProgress] = useState<number>(0);
  const [ingestStatusText, setIngestStatusText] = useState<string>('Ingesting SCADA telemetry...');
  const [resetting, setResetting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const resetIngestionPipeline = useCallback(() => {
    setActiveStep(1);
    setSelectedFileName('No file selected');
    setCurrentFileRecord(null);
    setProfileData(null);
    setCustomMappings({});
    setIngestProgress(0);
    setIngestStatusText('Ingesting SCADA telemetry...');
    setIngesting(false);
    setErrorMessage(null);
  }, []);

  const formatBytes = (bytes: number | null | undefined): string => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const selectAndProfileFile = async (fileRecord: FileRecord) => {
    try {
      setErrorMessage(null);
      setCurrentFileRecord(fileRecord);
      setSelectedFileName(fileRecord.original_name || fileRecord.path);
      setLoadingProfile(true);

      const profileRes = await profileFile({
        file_id: fileRecord.id,
        file_path: fileRecord.path,
        sparkline_points: 10,
      });

      setProfileData(profileRes);

      try {
        const jobsForFile = await getIngestionJobs(fileRecord.id);
        const hasCompletedJob = jobsForFile.some((j) => j.status === 'completed' || j.status === 'done');
        if (hasCompletedJob) {
          setActiveStep(6);
        } else {
          setActiveStep(3);
        }
      } catch (jobErr) {
        setActiveStep(3);
      }
    } catch (err: any) {
      console.error('Profiling file failed:', err);
      const detail = err.response?.data?.detail || err.message || 'Profiling failed';
      setErrorMessage(`Could not profile ${fileRecord.original_name || fileRecord.path}: ${detail}`);
    } finally {
      setLoadingProfile(false);
    }
  };

  const loadFiles = useCallback(async () => {
    try {
      setFilesLoading(true);
      setFilesError(null);
      const filesRes = await getFiles();
      setFiles(filesRes);
      return filesRes;
    } catch (err: any) {
      console.error('Failed to fetch recent files:', err);
      const msg = err.response?.data?.detail || err.message || 'Failed to load recent ingest records';
      setFilesError(msg);
      return [];
    } finally {
      setFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authLoading || !isAuthenticated) {
      return;
    }

    const initPage = async () => {
      const filesRes = await loadFiles();
      if (filesRes && filesRes.length > 0) {
        await selectAndProfileFile(filesRes[0]);
      }

      getIngestionJobs()
        .then((jobsRes) => setJobs(jobsRes))
        .catch((err) => console.warn('Failed to load ingestion jobs:', err));
    };

    initPage();
  }, [authLoading, isAuthenticated, loadFiles]);

  if (!canUpload && !authLoading) {
    return (
      <div className="bg-rose-50 border border-rose-200 text-rose-800 p-6 rounded-xl text-sm flex items-center gap-4 my-6">
        <ShieldAlert className="w-6 h-6 text-rose-600 flex-shrink-0" />
        <div>
          <strong className="font-bold text-base block mb-1">Access Restricted (Viewer Role)</strong>
          <span>Your account ({user?.email}) has Viewer permissions and cannot perform SCADA telemetry uploads or ingestion operations. Contact an administrator for Engineer or Admin access.</span>
        </div>
      </div>
    );
  }

  const handleResetData = async () => {
    if (!window.confirm('Are you sure you want to reset all SCADA telemetry data? This will clear all uploaded files, readings, channels, and ingestion records.')) {
      return;
    }

    try {
      setResetting(true);
      await resetSCADAData();
      resetIngestionPipeline();
      await loadFiles();
      alert('SCADA database reset completed! Database is now empty and ready for fresh CSV demo upload.');
    } catch (err: any) {
      alert(`Reset failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setResetting(false);
    }
  };

  const handleFileSelect = async (browserFile: File) => {
    try {
      setErrorMessage(null);
      setIsUploading(true);
      setActiveStep(1);
      setUploadProgress(null);

      const ext = browserFile.name.substring(browserFile.name.lastIndexOf('.')).toLowerCase();
      if (!['.csv', '.parquet', '.zip'].includes(ext)) {
        throw new Error(`Invalid file format '${ext}'. Only CSV, Parquet, and ZIP files are supported.`);
      }

      if (browserFile.size > 2 * 1024 * 1024 * 1024) {
        throw new Error('File exceeds the maximum supported size of 2 GB.');
      }

      const uploadedRecord = await uploadFile(browserFile, undefined, (progress) => {
        setUploadProgress(progress);
      });

      setCurrentFileRecord(uploadedRecord);
      setSelectedFileName(uploadedRecord.original_name || uploadedRecord.path);
      setIsUploading(false);
      setUploadProgress(null);

      setActiveStep(2);
      setLoadingProfile(true);
      await loadFiles();
      await selectAndProfileFile(uploadedRecord);
    } catch (err: any) {
      console.error('File upload or profiling failed:', err);
      const detail = err.response?.data?.detail || err.message || 'File upload failed';
      setErrorMessage(detail);
    } finally {
      setIsUploading(false);
      setLoadingProfile(false);
      setUploadProgress(null);
    }
  };

  const canonicalLabels: Record<string, { key: string; type: string }> = {
    DATE_TIME: { key: 'timestamp', type: 'ISO 8601' },
    PLANT_ID: { key: 'plant_id', type: 'Global Ref' },
    SOURCE_KEY: { key: 'device_id', type: 'Asset Inverter' },
    DC_POWER: { key: 'power_dc', type: 'kW' },
    AC_POWER: { key: 'power_ac', type: 'kW' },
    DAILY_YIELD: { key: 'energy_ac_daily', type: 'kWh' },
    TOTAL_YIELD: { key: 'energy_ac_total', type: 'kWh' },
    IRRADIANCE: { key: 'irradiance', type: 'W/m²' },
    IRRADIATION: { key: 'irradiation', type: 'W/m²' },
    AMBIENT_TEMPERATURE: { key: 'ambient_temperature', type: '°C' },
    MODULE_TEMPERATURE: { key: 'module_temperature', type: '°C' },
  };

  const handleUpdateMapping = (rawColumn: string, newMappedKey: string) => {
    setCustomMappings((prev) => ({
      ...prev,
      [rawColumn]: newMappedKey,
    }));
  };

  const mappingItems: ColumnMappingItem[] = profileData
    ? profileData.columns.map((col) => {
        const userCustomKey = customMappings[col.name];
        const suggestion = profileData.mapping_suggestions.find((s) => s.raw_column === col.name);
        const canon = canonicalLabels[col.name] || {
          key: suggestion?.canonical_key || col.name.toLowerCase(),
          type: col.data_type || 'ISO 8601',
        };
        const finalKey = userCustomKey || canon.key;
        return {
          rawColumn: col.name,
          mappedKey: finalKey,
          targetType: canon.type,
          confidence: suggestion ? Math.round(suggestion.confidence * 100) : 100,
          sampleData: col.sample_values ? String(col.sample_values[0]) : undefined,
          notes: col.name === 'SOURCE_KEY' ? 'Mapped to 22 Discrete Inverters' : undefined,
          valueSpan: col.min_val !== undefined && col.max_val !== undefined ? `${col.min_val} → ${col.max_val}` : undefined,
        };
      })
    : [];

  const handleExecuteIngest = async () => {
    if (!currentFileRecord) {
      alert('Please select or upload a SCADA telemetry file first.');
      return;
    }

    try {
      setErrorMessage(null);
      setIngesting(true);
      setActiveStep(4);
      setIngestProgress(0.05);
      setIngestStatusText('Initializing background ingestion worker...');

      let targetJobId: string | undefined;

      const existingJobs = await getIngestionJobs(currentFileRecord.id);
      if (existingJobs.length > 0) {
        targetJobId = existingJobs[0].id;
      } else {
        const templates = await getMappingTemplates(user?.org_id);
        let templateId: string;

        if (templates.length > 0) {
          templateId = templates[0].id;
        } else {
          const mappingsObj: Record<string, string> = {};
          mappingItems.forEach((m) => {
            mappingsObj[m.rawColumn] = m.mappedKey;
          });

          if (!Object.values(mappingsObj).includes('timestamp')) {
            mappingsObj['DATE_TIME'] = 'timestamp';
          }
          if (!Object.values(mappingsObj).includes('source_key')) {
            mappingsObj['SOURCE_KEY'] = 'source_key';
          }

          const newTemplate = await createMappingTemplate({
            org_id: user?.org_id || '',
            name: `${selectedFileName} Mapping`,
            source_signature: `scada_sig_${Date.now()}`,
            mappings: mappingsObj,
          });
          templateId = newTemplate.id;
        }

        const newJob = await createIngestionJob({
          file_id: currentFileRecord.id,
          template_id: templateId,
        });
        targetJobId = newJob.id;
      }

      if (targetJobId) {
        const initialRes = await runIngestionJob(targetJobId);

        if (initialRes.status === 'completed' || initialRes.status === 'done') {
          setActiveStep(6);
          setIngestProgress(1.0);
          window.dispatchEvent(new CustomEvent('plantiq:ingested'));
          const count = initialRes.qc_summary?.readings_inserted || initialRes.rows_total || profileData?.row_count;
          await loadFiles();
          setIngesting(false);
          alert(`Ingestion job completed! ${count} telemetry readings inserted into database.`);
          resetIngestionPipeline();
          return;
        }

        const pollJobId = targetJobId;
        const startTime = Date.now();
        const pollInterval = setInterval(async () => {
          try {
            const jobStatus = await getIngestionJob(pollJobId);
            const status = jobStatus.status;
            const summary = jobStatus.qc_summary || {};
            const progressVal = summary.progress !== undefined ? summary.progress : 0.5;
            const processed = summary.rows_processed || 0;
            const total = summary.rows_total || profileData?.row_count || 68778;

            setIngestProgress(progressVal);

            if (status === 'qc' || progressVal >= 0.60) {
              setActiveStep(5);
              setIngestStatusText(`Executing Quality Control (QC) validation bitmasks... (${Math.round(progressVal * 100)}%)`);
            } else {
              setActiveStep(4);
              setIngestStatusText(`Processing SCADA rows: ${processed.toLocaleString()} / ${total.toLocaleString()} (${Math.round(progressVal * 100)}%)...`);
            }

            if (status === 'completed' || status === 'done') {
              clearInterval(pollInterval);
              setActiveStep(6);
              setIngestProgress(1.0);
              window.dispatchEvent(new CustomEvent('plantiq:ingested'));
              const inserted = summary.readings_inserted || summary.rows_inserted || processed;
              await loadFiles();
              setIngesting(false);
              alert(`Ingestion job completed successfully! ${inserted.toLocaleString()} telemetry readings processed and inserted into database.`);
              resetIngestionPipeline();
            } else if (status === 'failed') {
              clearInterval(pollInterval);
              setIngesting(false);
              const errMsg = jobStatus.error || 'Ingestion worker encountered an error';
              setErrorMessage(`Ingestion Job Failed: ${errMsg}`);
              alert(`Ingestion Job Failed: ${errMsg}`);
            } else if (Date.now() - startTime > 120000) {
              clearInterval(pollInterval);
              setIngesting(false);
              setErrorMessage('Ingestion status polling timeout. Worker is continuing processing in background.');
            }
          } catch (pollErr: any) {
            console.warn('Job polling warning:', pollErr);
          }
        }, 500);
      }
    } catch (err: any) {
      console.error('Ingestion execution error:', err);
      const detail = err.response?.data?.detail || err.message || 'Ingestion execution failed';
      setIngesting(false);
      setErrorMessage(`Failed to start ingestion job: ${detail}`);
      alert(`Failed to start ingestion job: ${detail}`);
    }
  };

  return (
    <div className="space-y-5 pb-12">
      {/* Header */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">Upload &amp; Mapping</h1>
            <Badge variant="emerald">● LIVE 15M CADENCE</Badge>
          </div>
          <p className="text-xs text-slate-500 font-mono mt-0.5">
            Ingest raw SCADA time-series files (CSV, Parquet, ZIP) into PostgreSQL / TimescaleDB
          </p>
        </div>

        {isAdmin && (
          <button
            onClick={handleResetData}
            disabled={resetting}
            className="px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 rounded-lg text-xs font-mono font-bold transition flex items-center gap-1.5 self-start md:self-auto"
          >
            {resetting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-rose-600" />
            ) : (
              <RotateCcw className="w-3.5 h-3.5 text-rose-600" />
            )}
            <span>RESET DEMO DATA</span>
          </button>
        )}
      </div>

      {/* Error Alert Banner if Upload/Profiling Fails */}
      {errorMessage && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 p-4 rounded-xl text-xs flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />
          <div>
            <strong className="font-bold">Upload Error:</strong> {errorMessage}
          </div>
        </div>
      )}

      {/* Stepper View Switcher */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-1 space-y-5">
          <FileUploader
            activeFileName={selectedFileName}
            onFileSelect={handleFileSelect}
            isProfiling={loadingProfile}
            isUploading={isUploading}
            uploadProgress={uploadProgress}
          />

          <PipelineStepper
            currentStep={activeStep}
            fileName={selectedFileName}
            rowCount={profileData?.row_count || 0}
            colCount={profileData?.column_count || 0}
            statusText={ingestStatusText}
            progress={ingestProgress}
            isIngesting={ingesting}
            onProceed={handleExecuteIngest}
          />

          {/* Recent Ingest Records Card */}
          <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs space-y-3">
            <div className="flex items-center justify-between border-b border-slate-100 pb-2">
              <span className="text-[10px] font-mono font-bold uppercase text-slate-500 tracking-wider flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-slate-400" /> RECENT INGEST RECORDS
              </span>
              <span className="text-[11px] font-mono text-sky-700 font-bold">
                {filesLoading ? (
                  <span className="text-slate-400 flex items-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" /> Loading...
                  </span>
                ) : filesError ? (
                  <span className="text-rose-600">Error</span>
                ) : (
                  `${files.length} ${files.length === 1 ? 'file' : 'files'} active`
                )}
              </span>
            </div>

            <div className="space-y-2 text-xs font-mono max-h-56 overflow-y-auto">
              {filesLoading ? (
                <div className="p-3 text-center text-slate-400 font-mono text-xs flex items-center justify-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-600" />
                  <span>Fetching recent ingest records...</span>
                </div>
              ) : filesError ? (
                <div className="p-2.5 bg-rose-50 rounded-lg border border-rose-200 text-rose-700 text-xs">
                  {filesError}
                </div>
              ) : files.length > 0 ? (
                files.map((f) => {
                  const isSelected = currentFileRecord?.id === f.id;
                  return (
                    <div
                      key={f.id}
                      onClick={() => selectAndProfileFile(f)}
                      title="Click to view file schema and signal mappings"
                      className={`p-2.5 rounded-lg border cursor-pointer transition space-y-1 ${
                        isSelected
                          ? 'bg-sky-50 border-sky-400 ring-2 ring-sky-200'
                          : 'bg-slate-50 hover:bg-slate-100 border-slate-200'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-900 truncate max-w-[170px]" title={f.original_name || f.path}>
                          {f.original_name || f.path}
                        </span>
                        <div className="flex items-center gap-1">
                          {isSelected && <Check className="w-3.5 h-3.5 text-sky-600 font-bold" />}
                          <Badge variant={isSelected ? 'blue' : 'emerald'}>
                            {isSelected ? 'SELECTED' : 'ACTIVE'}
                          </Badge>
                        </div>
                      </div>
                      <p className="text-[10px] text-slate-500">
                        {formatBytes(f.size_bytes)} • {new Date(f.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                  );
                })
              ) : (
                <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-200 text-slate-400 text-center text-xs">
                  No ingest records found
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="lg:col-span-2 space-y-5">
          <SignalMapper
            fileName={selectedFileName}
            rowCount={profileData?.row_count || 0}
            colCount={profileData?.column_count || 0}
            mappings={mappingItems}
            onConfirmAll={handleExecuteIngest}
            onUpdateMapping={handleUpdateMapping}
          />
        </div>
      </div>
    </div>
  );
};

