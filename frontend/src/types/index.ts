export interface Plant {
  id: string;
  org_id: string;
  name: string;
  plant_type: 'solar' | 'wind' | 'process' | string;
  capacity_ac_kw: number | null;
  capacity_dc_kwp: number | null;
  latitude: number | null;
  longitude: number | null;
  timezone: string;
  cod_date: string | null;
  expected_pr: number;
  tariff_inr_per_kwh: number | null;
  metadata: Record<string, any>;
  created_at: string;
}

export interface Asset {
  id: string;
  plant_id: string;
  parent_id: string | null;
  name: string;
  asset_type: 'plant' | 'block' | 'inverter' | 'string' | 'transformer' | 'meter' | 'weather_station' | 'sensor' | string;
  make: string | null;
  model: string | null;
  rated_kw: number | null;
  metadata: Record<string, any>;
}

export interface Channel {
  id: string;
  asset_id: string;
  canonical_key: string;
  source_name: string;
  receive_unit: string | null;
  conversion: string | null;
  interval_s: number;
  agg_semantics: string;
}

export interface ReadingAggregate {
  channel_id: string;
  interval: string;
  start: string;
  end: string;
  reading_count: number;
  average_value: number | null;
  minimum_value: number | null;
  maximum_value: number | null;
}

export interface ReadingSummary {
  channel_id: string;
  start: string | null;
  end: string | null;
  reading_count: number;
  average_value: number | null;
  minimum_value: number | null;
  maximum_value: number | null;
}

export interface Reading {
  channel_id: string;
  ts: string;
  value: number;
  quality: number;
  ingestion_job_id?: string | null;
}

export interface FileRecord {
  id: string;
  org_id: string;
  kind: 'raw_upload' | 'report' | 'export' | string;
  path: string;
  original_name: string | null;
  size_bytes: number | null;
  created_by: string | null;
  created_at: string;
}

export interface MappingTemplate {
  id: string;
  org_id: string;
  name: string;
  source_signature: string;
  mappings: Record<string, any>;
  created_at: string;
}

export interface IngestionJob {
  id: string;
  file_id: string;
  template_id: string;
  status: 'pending' | 'profiling' | 'awaiting_mapping' | 'ingesting' | 'qc' | 'done' | 'failed' | 'processing' | 'completed' | string;
  rows_total: number | null;
  time_min: string | null;
  time_max: string | null;
  qc_summary: Record<string, any>;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface AIColumnProfile {
  name: string;
  data_type?: string;
  null_count?: number;
  null_percentage?: number;
  distinct_count?: number;
  sample_values?: any[];
  sparkline?: number[];
  min_val?: number;
  max_val?: number;
}

export interface AITimestampProfile {
  column_name?: string;
  min_timestamp?: string;
  max_timestamp?: string;
  detected_cadence_s?: number;
  timezone?: string;
}

export interface AIMappingSuggestion {
  raw_column: string;
  canonical_key: string;
  confidence: number;
  reason?: string;
}

export interface AIProfileResponse {
  file_path: string;
  file_name: string;
  file_format: string;
  file_size_bytes: number;
  row_count: number;
  column_count: number;
  columns: AIColumnProfile[];
  timestamp_profile: AITimestampProfile | null;
  mapping_suggestions: AIMappingSuggestion[];
  profiling_duration_ms: number;
}

export interface User {
  id: string;
  org_id: string;
  email: string;
  full_name: string;
  role: 'admin' | 'engineer' | 'viewer' | string;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Organization {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface ChunkUploadInitRequest {
  filename: string;
  total_size: number;
  total_chunks: number;
}

export interface ChunkUploadInitResponse {
  upload_id: string;
  filename: string;
  total_size: number;
  total_chunks: number;
  chunk_size?: number;
  status: string;
}

export interface ChunkUploadChunkResponse {
  upload_id: string;
  chunk_index: number;
  received: number;
  status: string;
}

export interface ChunkUploadCompleteRequest {
  upload_id: string;
}

export interface UploadProgress {
  filename: string;
  uploadedBytes: number;
  totalBytes: number;
  percentage: number;
  status: string;
  currentChunk?: number;
  totalChunks?: number;
}

export interface QCStatsResponse {
  total_readings: number;
  active_channels: number;
  cadence_integrity: string;
  ingestion_quality: number;
  duplicates_count: number;
  out_of_bounds_count: number;
  hypertable_active: boolean;
}

export interface PlantIQEvent {
  id: string;
  plant_id: string;
  asset_id?: string | null;
  source: string;
  event_type: string;
  severity: 'info' | 'warning' | 'critical' | 'error' | string;
  start_time: string;
  end_time?: string | null;
  code?: string | null;
  message: string;
  metadata?: Record<string, any>;
  created_at: string;
}

export interface EventCreateRequest {
  plant_id: string;
  asset_id?: string | null;
  source?: string;
  event_type?: string;
  severity?: string;
  start_time: string;
  end_time?: string | null;
  code?: string | null;
  message: string;
  metadata?: Record<string, any>;
}

export interface EventImportSummary {
  total_rows: number;
  imported_rows: number;
  failed_rows: number;
  validation_errors: Array<{
    row: number;
    error: string;
    data?: Record<string, any>;
  }>;
}

export interface PRHeatmapCell {
  timestamp: string;
  label: string;
  pr: number | null;
  pr_pct: string;
  status: 'healthy' | 'moderate' | 'degraded' | 'missing_data' | string;
  has_data: boolean;
  ac_kw: number | null;
  dc_kw: number | null;
  efficiency?: number | null;
}

export interface PRHeatmapRow {
  asset_id: string;
  asset_name: string;
  cells: PRHeatmapCell[];
}

export interface PRHeatmapResponse {
  plant_id: string;
  range: string;
  time_buckets: string[];
  inverters: PRHeatmapRow[];
  has_poa?: boolean;
}

export interface TopLosersItem {
  rank: number;
  asset_id: string;
  asset_name: string;
  expected_mwh?: number | null;
  actual_mwh: number;
  loss_mwh?: number | null;
  loss_pct?: number | null;
  pr: number | null;
  efficiency?: number | null;
  has_data: boolean;
}

export interface LossAnalysisResponse {
  plant_id: string;
  range: string;
  total_expected_mwh?: number | null;
  total_actual_mwh: number;
  net_shortfall_mwh?: number | null;
  aggregate_inverter_deficit_mwh?: number | null;
  total_loss_mwh?: number | null;
  total_loss_pct?: number | null;
  net_shortfall_pct?: number | null;
  has_data: boolean;
  has_poa?: boolean;
  plant_pr?: number | null;
  ranking_mode?: 'deficit' | 'none' | 'generation' | string;
  losers: TopLosersItem[];
}

export interface CanonicalSignal {
  key: string;
  name: string;
  category: string;
  unit: string;
  y_min?: number | null;
  y_max?: number | null;
  applicable_types: string[];
  description?: string | null;
}

export interface Detector {
  id: string;
  plant_id: string;
  name: string;
  method: 'zscore' | 'iqr' | 'deviation' | 'isolation_forest' | string;
  canonical_key: string;
  asset_scope: Record<string, any>;
  parameters: Record<string, any>;
  condition_text: string;
  enabled: boolean;
  created_at: string;
}

export type AnomalySeverity = 'low' | 'medium' | 'high' | 'critical';
export type AnomalyStatus = 'open' | 'acknowledged' | 'resolved' | 'false_positive';

export interface Anomaly {
  id: string;
  plant_id: string;
  plant_name?: string | null;
  asset_id?: string | null;
  asset_name?: string | null;
  channel_id?: string | null;
  channel_name?: string | null;
  detector_id?: string | null;
  detector_name?: string | null;
  start_time: string;
  end_time?: string | null;
  source: string;
  score: number;
  severity: AnomalySeverity;
  status: AnomalyStatus;
  estimated_loss_kw?: number | null;
  summary?: string | null;
  details: Record<string, any>;
  rca_narrative?: Record<string, any> | null;
  rca_by?: string | null;
  status_note?: string | null;
  created_at: string;
}

export interface AnomalySummary {
  total_anomalies: number;
  open_count: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  total_estimated_loss_kwh: number;
  total_estimated_financial_loss_inr: number;
}

export interface BulkAnomalyTriageRequest {
  anomaly_ids: string[];
  status: AnomalyStatus;
  status_note?: string;
}

export interface BulkAnomalyTriageResponse {
  updated_count: number;
  status: string;
  anomaly_ids: string[];
}

export interface AnomalyEvidenceDataPoint {
  ts: string;
  observed?: number | null;
  baseline?: number | null;
  upper_bound?: number | null;
  lower_bound?: number | null;
  is_anomaly: boolean;
}

export interface AnomalyHypothesis {
  rank: number;
  hypothesis: string;
  confidence: number;
  category: string;
  description: string;
}

export interface AnomalySupportingEvidence {
  label: string;
  value: string;
  status: string;
  type: string;
}

export interface AnomalyEvidenceResponse {
  anomaly_id: string;
  plant_id: string;
  plant_name?: string | null;
  asset_id?: string | null;
  asset_name?: string | null;
  channel_id?: string | null;
  canonical_key?: string | null;
  detector_name?: string | null;
  detector_method?: string | null;
  observed_value?: number | null;
  baseline_value?: number | null;
  threshold_value?: number | null;
  unit: string;
  severity: AnomalySeverity;
  status: AnomalyStatus;
  status_note?: string | null;
  estimated_loss_kw?: number | null;
  estimated_loss_kwh?: number | null;
  estimated_loss_inr?: number | null;
  start_time: string;
  end_time?: string | null;
  data_points: AnomalyEvidenceDataPoint[];
  rca_narrative?: Record<string, any> | null;
  supporting_evidence: AnomalySupportingEvidence[];
  recommended_checks: string[];
  ranked_hypotheses: AnomalyHypothesis[];
}

export interface AlertRule {
  id: string;
  plant_id: string;
  plant_name?: string | null;
  name: string;
  metric: string;
  threshold: number;
  direction: 'above' | 'below';
  severity: 'info' | 'warning' | 'critical';
  channels: ('email' | 'webhook')[];
  enabled: boolean;
  config: {
    recipients?: string[];
    webhook_url?: string;
    webhook_secret?: string;
    smtp_host?: string;
    [key: string]: any;
  };
  created_at: string;
}

export interface AlertDelivery {
  id: string;
  rule_id: string;
  plant_id: string;
  anomaly_id?: string | null;
  channel: string;
  recipient: string;
  status: 'accepted' | 'delivered' | 'failed' | 'simulated' | string;
  attempt_count: number;
  payload: Record<string, any>;
  error_message?: string | null;
  created_at: string;
}

