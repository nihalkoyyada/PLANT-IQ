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


