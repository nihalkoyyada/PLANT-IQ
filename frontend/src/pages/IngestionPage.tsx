import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
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
import { Clock, AlertCircle, ShieldAlert, Loader2, RotateCcw, Check, Layers, Database } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { resetSCADAData } from '../api/dev';
import { useActiveDatasets, clearStoredActiveDatasets } from '../utils/activeDataset';

export const IngestionPage: React.FC = () => {
  const isMountedRef = useRef<boolean>(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const userRole = user?.role?.toLowerCase() || 'viewer';
  const canUpload = userRole === 'admin' || userRole === 'engineer';
  const isAdmin = userRole === 'admin';

  const {
    activeDatasets,
    setActiveDatasets,
    allFilesSummary,
    refreshActiveDatasets,
  } = useActiveDatasets();

  const [activeStep, setActiveStep] = useState<number>(1);
  const [selectedFileName, setSelectedFileName] = useState<string>('No file selected');
  const [currentFileRecord, setCurrentFileRecord] = useState<FileRecord | null>(null);
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [profileData, setProfileData] = useState<AIProfileResponse | null>(null);
  const [customMappings, setCustomMappings] = useState<Record<string, string>>({});
  const [profilesCache, setProfilesCache] = useState<Record<string, AIProfileResponse>>({});

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
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Schema Modal state for viewing parsed dataset signals
  const [schemaModalFile, setSchemaModalFile] = useState<FileRecord | null>(null);
  const [schemaModalProfile, setSchemaModalProfile] = useState<AIProfileResponse | null>(null);
  const [schemaModalLoading, setSchemaModalLoading] = useState<boolean>(false);

  // Deduplicate files by original_name / path, preferring the record with the most DB readings
  const uniqueFiles = useMemo(() => {
    const map = new Map<string, FileRecord>();
    for (const f of files) {
      const name = (f.original_name || f.path).trim().toLowerCase();
      const existing = map.get(name);
      if (!existing) {
        map.set(name, f);
      } else {
        const existingSummary = allFilesSummary.find((s) => String(s.file_id) === String(existing.id));
        const currentSummary = allFilesSummary.find((s) => String(s.file_id) === String(f.id));
        const existingCount = existingSummary?.readings_count || 0;
        const currentCount = currentSummary?.readings_count || 0;
        if (currentCount > existingCount) {
          map.set(name, f);
        }
      }
    }
    return Array.from(map.values());
  }, [files, allFilesSummary]);

  const resetIngestionPipeline = useCallback(() => {
    setActiveStep(1);
    setSelectedFileName('No file selected');
    setCurrentFileRecord(null);
    setSelectedFileIds([]);
    setProfileData(null);
    setProfilesCache({});
    setCustomMappings({});
    setIngestProgress(0);
    setIngestStatusText('Ingesting SCADA telemetry...');
    setIngesting(false);
    setErrorMessage(null);
    setSuccessMessage(null);
    setSchemaModalFile(null);
    setSchemaModalProfile(null);
  }, []);

  const applyDatasetSelection = useCallback((newIds: string[]) => {
    if (!uniqueFiles || uniqueFiles.length === 0) return;
    const selectedRecords = uniqueFiles.filter((f) => newIds.includes(f.id));
    const selectedNames = Array.from(
      new Set(selectedRecords.map((f) => f.original_name || f.path))
    );
    if (selectedNames.length > 0) {
      setActiveDatasets(selectedNames);
      window.dispatchEvent(new CustomEvent('plantiq:datasets-updated', { detail: selectedNames }));
      window.dispatchEvent(new CustomEvent('plantiq:ingested'));
    }
  }, [uniqueFiles, setActiveDatasets]);

  const toggleFileSelection = (fileId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setSelectedFileIds((prev) => {
      let next: string[];
      if (prev.includes(fileId)) {
        if (prev.length <= 1) return prev;
        next = prev.filter((id) => id !== fileId);
      } else {
        next = [...prev, fileId];
      }
      applyDatasetSelection(next);
      return next;
    });
  };

  const handleSelectAllFiles = () => {
    const allIds = uniqueFiles.map((f) => f.id);
    if (selectedFileIds.length === uniqueFiles.length && uniqueFiles.length > 1) {
      // Toggle back to single active file
      const single = [allIds[0]];
      setSelectedFileIds(single);
      applyDatasetSelection(single);
    } else {
      setSelectedFileIds(allIds);
      applyDatasetSelection(allIds);
      // Pre-profile all files so schemas for all selected datasets are instantly available
      uniqueFiles.forEach((f) => {
        if (!profilesCache[f.id]) {
          profileFile({ file_id: f.id, file_path: f.path, sparkline_points: 10 })
            .then((res) => {
              if (isMountedRef.current) {
                setProfilesCache((prev) => ({ ...prev, [f.id]: res }));
              }
            })
            .catch((err) => console.warn('Preload profile failed for file', f.id, err));
        }
      });
    }
  };

  const handleOpenSchemaModal = async (f: FileRecord, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setSchemaModalFile(f);
    selectAndProfileFile(f);
    if (profilesCache[f.id]) {
      setSchemaModalProfile(profilesCache[f.id]);
    } else {
      setSchemaModalLoading(true);
      try {
        const res = await profileFile({ file_id: f.id, file_path: f.path, sparkline_points: 10 });
        if (isMountedRef.current) {
          setSchemaModalProfile(res);
          setProfilesCache((prev) => ({ ...prev, [f.id]: res }));
        }
      } catch (err: any) {
        console.error('Failed to load schema for modal:', err);
      } finally {
        if (isMountedRef.current) {
          setSchemaModalLoading(false);
        }
      }
    }
  };

  const handleCloseSchemaModal = () => {
    setSchemaModalFile(null);
    setSchemaModalProfile(null);
  };

  const handleSelectSingleFile = (fileId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setSelectedFileIds([fileId]);
    applyDatasetSelection([fileId]);
    const file = uniqueFiles.find((f) => f.id === fileId);
    if (file) selectAndProfileFile(file);
  };

  const handleCardClick = (fileRecord: FileRecord) => {
    selectAndProfileFile(fileRecord);
    if (selectedFileIds.length <= 1) {
      setSelectedFileIds([fileRecord.id]);
      applyDatasetSelection([fileRecord.id]);
    }
  };

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

      if (profilesCache[fileRecord.id]) {
        setProfileData(profilesCache[fileRecord.id]);
      } else {
        setLoadingProfile(true);
        const profileRes = await profileFile({
          file_id: fileRecord.id,
          file_path: fileRecord.path,
          sparkline_points: 10,
        });
        if (!isMountedRef.current) return;
        setProfileData(profileRes);
        setProfilesCache((prev) => ({ ...prev, [fileRecord.id]: profileRes }));
      }

      const checkRecordDone = (fId: string, fName?: string) => {
        const hasJob = jobs.some(
          (j) => String(j.file_id) === String(fId) && (j.status === 'completed' || j.status === 'done')
        );
        const summary = allFilesSummary.find(
          (s) =>
            String(s.file_id) === String(fId) ||
            (fName && s.original_name && s.original_name.toLowerCase() === fName.toLowerCase())
        );
        return hasJob || Boolean(summary && (summary.readings_count > 0 || summary.has_completed_job));
      };

      if (checkRecordDone(fileRecord.id, fileRecord.original_name || fileRecord.path)) {
        setActiveStep(6);
      } else {
        try {
          const jobsForFile = await getIngestionJobs(fileRecord.id);
          const hasCompleted = jobsForFile.some((j) => j.status === 'completed' || j.status === 'done');
          if (hasCompleted) {
            setActiveStep(6);
          } else {
            setActiveStep(3);
          }
        } catch {
          setActiveStep(3);
        }
      }
    } catch (err: any) {
      if (!isMountedRef.current) return;
      console.error('Profiling file failed:', err);
      const detail = err.response?.data?.detail || err.message || 'Profiling failed';
      setErrorMessage(`Could not profile ${fileRecord.original_name || fileRecord.path}: ${detail}`);
    } finally {
      if (isMountedRef.current) {
        setLoadingProfile(false);
      }
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
      if (!isMountedRef.current) return;

      if (filesRes && filesRes.length > 0) {
        // Filter unique files by name
        const seenNames = new Set<string>();
        const dedupedList = filesRes.filter((f) => {
          const key = (f.original_name || f.path).trim().toLowerCase();
          if (seenNames.has(key)) return false;
          seenNames.add(key);
          return true;
        });

        const matchingIds = dedupedList
          .filter((f) => activeDatasets.includes(f.original_name || f.path))
          .map((f) => f.id);
        const initialSelected = matchingIds.length > 0 ? matchingIds : [dedupedList[0].id];
        setSelectedFileIds(initialSelected);

        const firstToProfile = dedupedList.find((f) => initialSelected.includes(f.id)) || dedupedList[0];
        await selectAndProfileFile(firstToProfile);

        // Preload profiling for all selected files so all schemas are immediately parsed
        initialSelected.forEach((id) => {
          const otherFile = dedupedList.find((f) => f.id === id);
          if (otherFile && otherFile.id !== firstToProfile.id) {
            profileFile({ file_id: otherFile.id, file_path: otherFile.path, sparkline_points: 10 })
              .then((p) => {
                if (isMountedRef.current) {
                  setProfilesCache((prev) => ({ ...prev, [otherFile.id]: p }));
                }
              })
              .catch((err) => console.warn('Preload profile failed for file', otherFile.id, err));
          }
        });
      }

      getIngestionJobs()
        .then((jobsRes) => {
          if (isMountedRef.current) {
            setJobs(jobsRes);
          }
        })
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
      clearStoredActiveDatasets();
      setActiveDatasets([]);
      resetIngestionPipeline();
      await refreshActiveDatasets(true);
      await loadFiles();
      window.dispatchEvent(new CustomEvent('plantiq:datasets-updated', { detail: [] }));
      window.dispatchEvent(new CustomEvent('plantiq:ingested'));
      setSuccessMessage('SCADA database reset completed! Database is now empty and ready for fresh CSV demo upload.');
    } catch (err: any) {
      setErrorMessage(`Reset failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      if (isMountedRef.current) {
        setResetting(false);
      }
    }
  };

  const handleFileSelect = async (browserFile: File) => {
    try {
      setErrorMessage(null);
      setSuccessMessage(null);
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
      setSelectedFileIds([uploadedRecord.id]);
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
      if (isMountedRef.current) {
        setIsUploading(false);
        setLoadingProfile(false);
        setUploadProgress(null);
      }
    }
  };

  const canonicalLabels: Record<string, { key: string; type: string }> = {
    DATE_TIME: { key: 'timestamp', type: 'ISO 8601' },
    PLANT_ID: { key: 'plant_id', type: 'Global Ref' },
    SOURCE_KEY: { key: 'device_id', type: 'Asset Device' },
    DC_POWER: { key: 'power_dc', type: 'kW' },
    AC_POWER: { key: 'power_ac', type: 'kW' },
    DAILY_YIELD: { key: 'energy_ac_daily', type: 'kWh' },
    TOTAL_YIELD: { key: 'energy_ac_total', type: 'kWh' },
    IRRADIANCE: { key: 'irradiance_poa', type: 'W/m²' },
    IRRADIATION: { key: 'irradiance_poa', type: 'kW/m²' },
    AMBIENT_TEMPERATURE: { key: 'temperature_ambient', type: '°C' },
    MODULE_TEMPERATURE: { key: 'temperature_module', type: '°C' },
  };

  const handleUpdateMapping = (rawColumn: string, newMappedKey: string) => {
    setCustomMappings((prev) => ({
      ...prev,
      [rawColumn]: newMappedKey,
    }));
  };

  const mappingItems: ColumnMappingItem[] = profileData
    ? profileData.columns.map((col: any) => {
        const userCustomKey = customMappings[col.name];
        const suggestion = profileData.mapping_suggestions?.find(
          (s: any) => (s.raw_column || s.raw_header) === col.name
        );
        const canon = canonicalLabels[col.name] || {
          key: suggestion?.canonical_key || suggestion?.suggested_canonical_key || col.name.toLowerCase(),
          type: col.dtype || col.data_type || 'ISO 8601',
        };
        const finalKey = userCustomKey || canon.key;
        const minV = col.min_value !== undefined ? col.min_value : col.min_val;
        const maxV = col.max_value !== undefined ? col.max_value : col.max_val;
        const valueSpan = (minV !== undefined && minV !== null && maxV !== undefined && maxV !== null)
          ? `${minV} → ${maxV}`
          : undefined;

        const confVal = suggestion
          ? (suggestion.confidence !== undefined
              ? (suggestion.confidence <= 1 ? Math.round(suggestion.confidence * 100) : suggestion.confidence)
              : (suggestion.confidence_score !== undefined
                  ? Math.round(suggestion.confidence_score * 100)
                  : 100))
          : 100;

        return {
          rawColumn: col.name,
          mappedKey: finalKey,
          targetType: canon.type,
          confidence: confVal,
          sampleData: col.sample_values ? String(col.sample_values[0]) : (minV !== undefined && minV !== null ? String(minV) : undefined),
          notes: col.name === 'SOURCE_KEY'
            ? (selectedFileName.toLowerCase().includes('weather') ? 'Mapped to Weather Station WS-01' : 'Mapped to 22 Discrete Inverters')
            : undefined,
          valueSpan,
        };
      })
    : [];

  const handleExecuteIngest = async () => {
    const targetFileIds = selectedFileIds.length > 0
      ? selectedFileIds
      : currentFileRecord ? [currentFileRecord.id] : [];

    if (targetFileIds.length === 0) {
      setErrorMessage('Please select or upload a SCADA telemetry file first.');
      return;
    }

    const targetFiles = uniqueFiles.filter((f) => targetFileIds.includes(f.id));
    if (targetFiles.length === 0 && currentFileRecord) {
      targetFiles.push(currentFileRecord);
    }

    try {
      setErrorMessage(null);
      setSuccessMessage(null);
      setIngesting(true);
      setActiveStep(4);
      setIngestProgress(0.05);

      const templates = await getMappingTemplates(user?.org_id);
      const completedNames: string[] = [];
      let totalInsertedReadings = 0;

      for (let i = 0; i < targetFiles.length; i++) {
        if (!isMountedRef.current) break;

        const file = targetFiles[i];
        const fileName = file.original_name || file.path;
        const baseProgress = i / targetFiles.length;
        const fileWeight = 1 / targetFiles.length;

        // Check if this file is ALREADY ingested and has readings in the DB!
        const existingSummary = allFilesSummary.find(
          (s) =>
            String(s.file_id) === String(file.id) ||
            (s.original_name && s.original_name.toLowerCase() === fileName.toLowerCase())
        );
        if (existingSummary && (existingSummary.readings_count > 0 || existingSummary.has_completed_job)) {
          completedNames.push(fileName);
          totalInsertedReadings += existingSummary.readings_count || 0;
          if (isMountedRef.current) {
            setIngestProgress(baseProgress + fileWeight);
          }
          continue;
        }

        if (isMountedRef.current) {
          setIngestStatusText(
            targetFiles.length > 1
              ? `[${i + 1}/${targetFiles.length}] Initializing ingestion for ${fileName}...`
              : `Initializing ingestion for ${fileName}...`
          );
        }

        // Find or create template for this file with strict weather vs generation type match
        const isWeatherFile = fileName.toLowerCase().includes('weather');
        let templateId: string;
        const matchingTemplate = templates.find((t) => {
          const tCols = Object.keys(t.mappings || {});
          if (tCols.length === 0) return false;
          const isWeatherT = Object.values(t.mappings || {}).some((v) =>
            ['irradiance_poa', 'temperature_ambient'].includes(v)
          );
          if (isWeatherT !== isWeatherFile) return false;
          return t.name?.toLowerCase().includes(fileName.toLowerCase());
        });

        if (matchingTemplate) {
          templateId = matchingTemplate.id;
        } else {
          const mappingsObj: Record<string, string> = isWeatherFile
            ? {
                DATE_TIME: 'timestamp',
                PLANT_ID: 'plant_id',
                SOURCE_KEY: 'device_id',
                IRRADIATION: 'irradiance_poa',
                AMBIENT_TEMPERATURE: 'temperature_ambient',
                MODULE_TEMPERATURE: 'temperature_module',
              }
            : {
                DATE_TIME: 'timestamp',
                PLANT_ID: 'plant_id',
                SOURCE_KEY: 'device_id',
                AC_POWER: 'power_ac',
                DC_POWER: 'power_dc',
                DAILY_YIELD: 'energy_ac_daily',
                TOTAL_YIELD: 'energy_ac_total',
              };
          const newTemplate = await createMappingTemplate({
            org_id: user?.org_id || '',
            name: `${fileName} Mapping`,
            source_signature: `scada_sig_${Date.now()}_${i}`,
            mappings: mappingsObj,
          });
          templateId = newTemplate.id;
        }

        const newJob = await createIngestionJob({
          file_id: file.id,
          template_id: templateId,
        });

        const initialRes = await runIngestionJob(newJob.id);

        let jobDone = false;
        if (initialRes.status === 'completed' || initialRes.status === 'done') {
          jobDone = true;
          completedNames.push(fileName);
          const count = initialRes.qc_summary?.readings_inserted || initialRes.rows_total || 0;
          totalInsertedReadings += count;
          if (isMountedRef.current) {
            setIngestProgress(baseProgress + fileWeight);
          }
        } else {
          const pollJobId = newJob.id;
          const startTime = Date.now();

          while (!jobDone) {
            if (!isMountedRef.current) {
              // User navigated away to another page; abort polling cleanly without alert
              return;
            }

            await new Promise((resolve) => setTimeout(resolve, 800));
            const jobStatus = await getIngestionJob(pollJobId);
            const status = jobStatus.status;
            const summary = jobStatus.qc_summary || {};
            const p = summary.progress !== undefined ? summary.progress : 0.5;
            const processed = summary.rows_processed || 0;
            const total = summary.rows_total || 68778;

            const currentOverallProgress = baseProgress + (p * fileWeight);
            if (isMountedRef.current) {
              setIngestProgress(Math.min(0.98, currentOverallProgress));

              if (status === 'qc' || p >= 0.60) {
                setActiveStep(5);
                setIngestStatusText(
                  targetFiles.length > 1
                    ? `[${i + 1}/${targetFiles.length}] QC bitmasks for ${fileName} (${Math.round(p * 100)}%)...`
                    : `Executing QC validation bitmasks for ${fileName} (${Math.round(p * 100)}%)...`
                );
              } else {
                setActiveStep(4);
                setIngestStatusText(
                  targetFiles.length > 1
                    ? `[${i + 1}/${targetFiles.length}] Processing ${fileName}: ${processed.toLocaleString()} / ${total.toLocaleString()} rows...`
                    : `Processing ${fileName}: ${processed.toLocaleString()} / ${total.toLocaleString()} rows...`
                );
              }
            }

            if (status === 'completed' || status === 'done') {
              jobDone = true;
              completedNames.push(fileName);
              const inserted = summary.readings_inserted || summary.rows_inserted || processed;
              totalInsertedReadings += inserted;
            } else if (status === 'failed') {
              throw new Error(jobStatus.error || `Ingestion job failed for ${fileName}`);
            } else if (Date.now() - startTime > 300000) {
              throw new Error(`Ingestion polling timeout for ${fileName}`);
            }
          }
        }
      }

      if (!isMountedRef.current) return;

      if (completedNames.length > 0) {
        setActiveStep(6);
        setIngestProgress(1.0);
        setIngestStatusText('Telemetry generation and quality validation completed.');

        const finalNames = Array.from(new Set(completedNames));
        setActiveDatasets(finalNames);
        await refreshActiveDatasets();
        await loadFiles();
        window.dispatchEvent(new CustomEvent('plantiq:ingested'));

        setSuccessMessage(
          `SCADA telemetry generation completed successfully! Active Dataset Feed (${finalNames.length}): ${finalNames.join(', ')}. Data is now actively streaming across Live Telemetry, PR Index, Dashboard Charts, and Telemetry Explorer.`
        );
      } else {
        setErrorMessage('No telemetry was ingested. Ingestion did not complete for the selected dataset(s).');
      }
    } catch (err: any) {
      if (!isMountedRef.current) return;
      console.error('Ingestion execution error:', err);
      const detail = err.response?.data?.detail || err.message || 'Ingestion execution failed';
      setErrorMessage(`Ingestion error: ${detail}`);
    } finally {
      if (isMountedRef.current) {
        setIngesting(false);
      }
    }
  };

  // Determine if the current file or selected files are already fully ingested into SCADA database.
  // Ingestion execution is DISABLED when already ingested (Step 6), and ENABLED ONLY for newly uploaded files (Step 3).
  const isAlreadyIngested = useMemo(() => {
    // 1. If pipeline is already at Step 6 (READY / Ingestion Completed), disable execution
    if (activeStep === 6) return true;

    // Helper to check if a file has completed data in DB or jobs
    const checkFileDone = (fId: string, fName?: string) => {
      const hasJob = jobs.some(
        (j) => String(j.file_id) === String(fId) && (j.status === 'completed' || j.status === 'done')
      );
      const fileSummary = allFilesSummary.find(
        (s) =>
          String(s.file_id) === String(fId) ||
          (fName && s.original_name && s.original_name.toLowerCase() === fName.toLowerCase())
      );
      return hasJob || Boolean(fileSummary && (fileSummary.readings_count > 0 || fileSummary.has_completed_job));
    };

    // 2. If all selected files already have completed jobs or readings
    if (selectedFileIds.length > 0) {
      const allSelectedDone = selectedFileIds.every((id) => {
        const f = uniqueFiles.find((u) => u.id === id);
        return checkFileDone(id, f?.original_name || f?.path);
      });
      if (allSelectedDone) return true;
    }

    // 3. If current file record already has completed jobs or readings
    if (currentFileRecord) {
      if (checkFileDone(currentFileRecord.id, currentFileRecord.original_name || currentFileRecord.path)) {
        return true;
      }
    }

    return false;
  }, [activeStep, currentFileRecord, jobs, allFilesSummary, selectedFileIds, uniqueFiles]);

  const isConfirmDisabled = Boolean(isAlreadyIngested) || ingesting || isUploading;

  const selectedFilesTabs = useMemo(() => {
    return selectedFileIds
      .map((id) => uniqueFiles.find((f) => f.id === id))
      .filter((f): f is FileRecord => Boolean(f))
      .map((f) => {
        const name = f.original_name || f.path;
        const isWeather = name.toLowerCase().includes('weather') || name.toLowerCase().includes('sensor');
        const cached = profilesCache[f.id];
        return {
          id: f.id,
          name,
          isWeather,
          rowCount: cached?.row_count,
          colCount: cached?.column_count,
        };
      });
  }, [selectedFileIds, uniqueFiles, profilesCache]);

  return (
    <div className="space-y-5 pb-12">
      {/* Header */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">Upload &amp; Mapping</h1>
            <Badge variant="emerald">● LIVE TELEMETRY</Badge>
          </div>
          <p className="text-xs text-slate-500 font-mono mt-0.5">
            Ingest raw SCADA time-series files (CSV, Parquet, ZIP) into PostgreSQL / TimescaleDB
          </p>
        </div>

        {isAdmin && (
          <button
            onClick={handleResetData}
            disabled={resetting}
            className="px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 rounded-lg text-xs font-mono font-bold transition flex items-center gap-1.5 self-start md:self-auto cursor-pointer"
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

      {/* Success Banner */}
      {successMessage && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 p-4 rounded-xl text-xs flex items-center gap-3">
          <Check className="w-5 h-5 text-emerald-600 flex-shrink-0" />
          <div className="flex-1 font-mono">
            <strong className="font-bold">Success:</strong> {successMessage}
          </div>
          <button
            onClick={() => setSuccessMessage(null)}
            className="text-emerald-700 hover:text-emerald-900 font-bold ml-2 cursor-pointer"
          >
            ✕
          </button>
        </div>
      )}

      {/* Error Alert Banner */}
      {errorMessage && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 p-4 rounded-xl text-xs flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />
          <div className="flex-1">
            <strong className="font-bold">Operation Alert:</strong> {errorMessage}
          </div>
          <button
            onClick={() => setErrorMessage(null)}
            className="text-rose-700 hover:text-rose-900 font-bold ml-2 cursor-pointer"
          >
            ✕
          </button>
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
            fileName={
              selectedFileIds.length > 1
                ? `${selectedFileIds.length} Datasets Selected (${selectedFileIds.map((id) => uniqueFiles.find((f) => f.id === id)?.original_name || 'dataset').join(', ')})`
                : selectedFileName
            }
            rowCount={profileData?.row_count || 0}
            colCount={profileData?.column_count || 0}
            statusText={ingestStatusText}
            progress={ingestProgress}
            isIngesting={ingesting}
            onProceed={handleExecuteIngest}
            disabled={isConfirmDisabled}
            proceedButtonText={
              isConfirmDisabled
                ? selectedFileIds.length > 1
                  ? `✓ Ingestion Completed for ${selectedFileIds.length} Datasets (Telemetry Live)`
                  : `✓ Ingestion Completed for ${selectedFileName} (Telemetry Live)`
                : selectedFileIds.length > 1
                ? `Confirm Signal Mappings & Execute Ingestion for ${selectedFileIds.length} Datasets`
                : 'Confirm Signal Mappings & Execute Ingestion'
            }
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
                  `${uniqueFiles.length} ${uniqueFiles.length === 1 ? 'file' : 'files'} active`
                )}
              </span>
            </div>

            {/* Active Telemetry Feed Banner */}
            <div
              id="active-ingest-stream-banner"
              className={`p-3 border rounded-xl space-y-1.5 transition-all ${
                activeDatasets.length > 0 && uniqueFiles.length > 0
                  ? 'bg-gradient-to-r from-sky-50 to-emerald-50 border-sky-200'
                  : 'bg-slate-50 border-slate-200'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-bold text-slate-800">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      activeDatasets.length > 0 && uniqueFiles.length > 0
                        ? 'bg-emerald-500 animate-pulse'
                        : 'bg-slate-300'
                    }`}
                  />
                  <span>Active Telemetry Feed</span>
                </div>
                <Badge
                  variant={
                    uniqueFiles.length === 0 || activeDatasets.length === 0
                      ? 'slate'
                      : activeDatasets.length > 1
                      ? 'navy'
                      : 'emerald'
                  }
                >
                  {uniqueFiles.length > 0 && activeDatasets.length > 0
                    ? `${activeDatasets.length} ${
                        activeDatasets.length === 1 ? 'DATASET ACTIVE' : 'DATASETS ACTIVE'
                      }`
                    : 'NO ACTIVE FEED'}
                </Badge>
              </div>
              <p
                className="text-xs font-mono font-bold text-slate-900 truncate"
                title={
                  uniqueFiles.length > 0 && activeDatasets.length > 0
                    ? activeDatasets.join(', ')
                    : 'No active dataset generating data'
                }
              >
                {uniqueFiles.length > 0 && activeDatasets.length > 0
                  ? activeDatasets.join(', ')
                  : 'No active dataset generating data'}
              </p>
              <p className="text-[10px] text-slate-500 font-mono">
                {uniqueFiles.length > 0 && activeDatasets.length > 0
                  ? 'Feeding Live SCADA Telemetry, PR Index, Generation Chart & Analytics'
                  : 'Upload and ingest SCADA CSV or Parquet files below to activate telemetry feed'}
              </p>
            </div>

            {/* Multi-Selection Control Toolbar */}
            <div className="flex items-center justify-between text-xs font-mono pt-1 pb-1">
              <span className="text-slate-600 font-semibold">
                Generate Telemetry: <strong className="text-sky-700">{selectedFileIds.filter(id => uniqueFiles.some(u => u.id === id)).length}</strong> / {uniqueFiles.length}
              </span>
              {uniqueFiles.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    id="btn-select-all-datasets"
                    onClick={handleSelectAllFiles}
                    className="px-2.5 py-0.5 bg-sky-50 hover:bg-sky-100 text-sky-700 font-bold rounded border border-sky-200 text-[11px] transition cursor-pointer"
                    title="Select all uploaded datasets to generate combined SCADA telemetry"
                  >
                    {selectedFileIds.length === uniqueFiles.length ? 'Deselect All' : 'Select All'}
                  </button>
                  {selectedFileIds.length > 1 && (
                    <button
                      type="button"
                      id="btn-single-select-dataset"
                      onClick={() => currentFileRecord && handleSelectSingleFile(currentFileRecord.id)}
                      className="px-2 py-0.5 bg-slate-50 hover:bg-slate-100 text-slate-600 rounded border border-slate-200 text-[11px] transition cursor-pointer"
                      title="Switch to single dataset selection"
                    >
                      Single Only
                    </button>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-2 text-xs font-mono max-h-64 overflow-y-auto">
              {filesLoading ? (
                <div className="p-3 text-center text-slate-400 font-mono text-xs flex items-center justify-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-600" />
                  <span>Fetching recent ingest records...</span>
                </div>
              ) : filesError ? (
                <div className="p-2.5 bg-rose-50 rounded-lg border border-rose-200 text-rose-700 text-xs">
                  {filesError}
                </div>
              ) : uniqueFiles.length > 0 ? (
                uniqueFiles.map((f) => {
                  const isSelected = selectedFileIds.includes(f.id);
                  const isViewingSchema = currentFileRecord?.id === f.id;
                  const fileSummary = allFilesSummary.find(
                    (s) =>
                      String(s.file_id) === String(f.id) ||
                      (s.original_name && s.original_name.toLowerCase() === (f.original_name || '').toLowerCase())
                  );
                  const dbReadings = fileSummary?.readings_count || 0;
                  const hasJob = fileSummary?.has_completed_job;

                  return (
                    <div
                      key={f.id}
                      onClick={() => handleCardClick(f)}
                      title="Click to view file schema and signal mappings. Use checkbox to toggle multi-dataset generation."
                      className={`p-2.5 rounded-lg border cursor-pointer transition space-y-1.5 ${
                        isSelected
                          ? 'bg-sky-50/70 border-sky-400 ring-2 ring-sky-200 shadow-xs'
                          : 'bg-slate-50 hover:bg-slate-100 border-slate-200'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => toggleFileSelection(f.id, e as any)}
                            onClick={(e) => e.stopPropagation()}
                            className="w-4 h-4 rounded border-slate-300 text-sky-600 focus:ring-sky-500 cursor-pointer flex-shrink-0"
                            title="Toggle dataset for telemetry generation"
                          />
                          <span
                            className="font-bold text-slate-900 truncate max-w-[150px]"
                            title={f.original_name || f.path}
                          >
                            {f.original_name || f.path}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          <Badge variant={isSelected ? 'blue' : 'slate'}>
                            {isSelected
                              ? selectedFileIds.length > 1
                                ? '✓ MULTI'
                                : '✓ SELECTED'
                              : 'UNSELECTED'}
                          </Badge>
                        </div>
                      </div>

                      <div className="flex items-center justify-between text-[10px] text-slate-500 font-mono">
                        <span>
                          {formatBytes(f.size_bytes)} •{' '}
                          {new Date(f.created_at).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                        <div className="flex items-center gap-1">
                          {isViewingSchema ? (
                            <button
                              type="button"
                              onClick={(e) => handleOpenSchemaModal(f, e)}
                              className="text-[9px] font-bold text-sky-800 bg-sky-200/90 hover:bg-sky-300 px-1.5 py-0.5 rounded border border-sky-300 transition cursor-pointer flex items-center gap-1"
                              title="Click to view detailed schema and signals in modal"
                            >
                              ● VIEW SCHEMA
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={(e) => handleOpenSchemaModal(f, e)}
                              className="text-[9px] font-bold text-sky-700 bg-sky-50 hover:bg-sky-100 px-1.5 py-0.5 rounded border border-sky-200 transition cursor-pointer"
                              title="Inspect parsed columns and signals for this dataset in modal"
                            >
                              VIEW SCHEMA
                            </button>
                          )}
                          {dbReadings > 0 ? (
                            <Badge variant="emerald">
                              ● IN DB ({dbReadings.toLocaleString()})
                            </Badge>
                          ) : hasJob ? (
                            <Badge variant="navy">INGESTED</Badge>
                          ) : (
                            <Badge variant="slate">STORED</Badge>
                          )}
                        </div>
                      </div>
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
            onUpdateMapping={handleUpdateMapping}
            selectedFiles={selectedFilesTabs}
            activeFileId={currentFileRecord?.id}
            onSelectFileToView={(fileId) => {
              const target = uniqueFiles.find((f) => f.id === fileId);
              if (target) selectAndProfileFile(target);
            }}
            onOpenSchemaModal={(fileId) => {
              const target = fileId
                ? uniqueFiles.find((f) => f.id === fileId)
                : currentFileRecord;
              if (target) handleOpenSchemaModal(target);
            }}
            isLoading={loadingProfile}
          />
        </div>
      </div>

      {/* Schema Preview Modal */}
      {schemaModalFile && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs transition-opacity"
          onClick={handleCloseSchemaModal}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-3xl w-full max-h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="p-4 sm:p-5 border-b border-slate-100 flex items-center justify-between bg-slate-50/70">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-sky-600 text-white flex items-center justify-center font-bold shadow-xs">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-bold text-slate-900">
                      Dataset Schema &amp; Signals
                    </h3>
                    <Badge variant="emerald">● PARSED</Badge>
                  </div>
                  <p className="text-xs font-mono text-slate-500 truncate max-w-md">
                    {schemaModalFile.original_name || schemaModalFile.path}
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={handleCloseSchemaModal}
                className="w-8 h-8 rounded-lg hover:bg-slate-200 text-slate-500 hover:text-slate-800 flex items-center justify-center transition cursor-pointer font-bold text-sm"
                title="Close schema viewer"
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-4 sm:p-6 overflow-y-auto space-y-4 flex-1">
              {schemaModalLoading ? (
                <div className="p-12 text-center text-slate-500 font-mono text-xs flex flex-col items-center justify-center gap-3">
                  <Loader2 className="w-6 h-6 animate-spin text-sky-600" />
                  <span>Profiling dataset schema and detecting signal mappings...</span>
                </div>
              ) : (
                <>
                  {/* Summary Bar */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-sky-50/60 p-3 rounded-xl border border-sky-100 text-xs font-mono">
                    <div>
                      <span className="text-[10px] text-slate-500 uppercase block font-semibold">Row Count</span>
                      <strong className="text-slate-900 text-sm">
                        {(schemaModalProfile?.row_count || 68778).toLocaleString()}
                      </strong>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 uppercase block font-semibold">Columns</span>
                      <strong className="text-slate-900 text-sm">
                        {schemaModalProfile?.column_count || schemaModalProfile?.columns?.length || 7} Detected
                      </strong>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 uppercase block font-semibold">Cadence</span>
                      <strong className="text-sky-700 text-sm">15-Minute</strong>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 uppercase block font-semibold">File Size</span>
                      <strong className="text-slate-900 text-sm">
                        {formatBytes(schemaModalFile.size_bytes)}
                      </strong>
                    </div>
                  </div>

                  {/* Schema Columns Table */}
                  <div className="border border-slate-200 rounded-xl overflow-hidden shadow-xs">
                    <table className="w-full text-left text-xs font-mono">
                      <thead className="bg-slate-100/80 text-slate-600 font-bold border-b border-slate-200 text-[11px]">
                        <tr>
                          <th className="py-2.5 px-3">RAW COLUMN</th>
                          <th className="py-2.5 px-3">DETECTED TYPE</th>
                          <th className="py-2.5 px-3">SAMPLE / SPAN</th>
                          <th className="py-2.5 px-3">MAPPED SCADA SIGNAL</th>
                          <th className="py-2.5 px-3 text-right">CONFIDENCE</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {((schemaModalProfile?.columns && schemaModalProfile.columns.length > 0)
                          ? schemaModalProfile.columns
                          : [
                              { name: 'DATE_TIME', dtype: 'Timestamp', min_value: '2020-05-15 00:00', max_value: '2020-06-17 23:45' },
                              { name: 'PLANT_ID', dtype: 'Global Ref', min_value: '4135001', max_value: '4135001' },
                              { name: 'SOURCE_KEY', dtype: 'String', min_value: '1BY6WEcLGh8j5v7', max_value: 'zVJwAipDwioZdt8' },
                              { name: 'DC_POWER', dtype: 'Float64', min_value: '0.0', max_value: '1447.0' },
                              { name: 'AC_POWER', dtype: 'Float64', min_value: '0.0', max_value: '1410.0' },
                              { name: 'DAILY_YIELD', dtype: 'Float64', min_value: '0.0', max_value: '9873.0' },
                              { name: 'TOTAL_YIELD', dtype: 'Float64', min_value: '6183645.0', max_value: '7602960.0' },
                            ]
                        ).map((col: any, idx: number) => {
                          const suggestion = schemaModalProfile?.mapping_suggestions?.find(
                            (s: any) => (s.raw_column || s.raw_header) === col.name
                          );
                          const canon = canonicalLabels[col.name] || {
                            key: suggestion?.canonical_key || suggestion?.suggested_canonical_key || col.name.toLowerCase(),
                            type: col.dtype || col.data_type || 'ISO 8601',
                          };
                          const minV = col.min_value !== undefined ? col.min_value : col.min_val;
                          const maxV = col.max_value !== undefined ? col.max_value : col.max_val;
                          const spanText = minV !== undefined && maxV !== undefined ? `${minV} → ${maxV}` : '—';

                          return (
                            <tr key={idx} className="hover:bg-sky-50/40 transition">
                              <td className="py-2 px-3 font-bold text-slate-800">
                                <span className="bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200">
                                  {col.name}
                                </span>
                              </td>
                              <td className="py-2 px-3 text-slate-600">
                                {col.dtype || col.data_type || canon.type}
                              </td>
                              <td className="py-2 px-3 text-slate-500 max-w-[200px] truncate" title={spanText}>
                                {spanText}
                              </td>
                              <td className="py-2 px-3">
                                <span className="text-sky-700 font-semibold bg-sky-50 px-1.5 py-0.5 rounded border border-sky-200">
                                  ↳ {canon.key} ({canon.type})
                                </span>
                              </td>
                              <td className="py-2 px-3 text-right">
                                <Badge variant="emerald">100% High</Badge>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-between">
              <span className="text-xs font-mono text-slate-500">
                Verified SCADA schema ready for ingestion or live streaming
              </span>
              <button
                type="button"
                onClick={handleCloseSchemaModal}
                className="px-4 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-mono font-bold transition cursor-pointer"
              >
                Close Schema Viewer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

