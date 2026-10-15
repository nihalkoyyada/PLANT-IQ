import { apiClient } from './client';
import {
  Anomaly,
  AnomalyEvidenceResponse,
  AnomalySummary,
  BulkAnomalyTriageRequest,
  BulkAnomalyTriageResponse,
} from '../types';

export interface GetAnomaliesFilterParams {
  plant_id?: string;
  asset_id?: string;
  detector_id?: string;
  severity?: string;
  status?: string;
  start_time_gte?: string;
  end_time_lte?: string;
  limit?: number;
  offset?: number;
}

export const getAnomalies = async (params?: GetAnomaliesFilterParams): Promise<Anomaly[]> => {
  const response = await apiClient.get<Anomaly[]>('/anomalies', { params });
  return response.data;
};

export const getAnomalySummary = async (plantId?: string): Promise<AnomalySummary> => {
  const response = await apiClient.get<AnomalySummary>('/anomalies/summary', {
    params: plantId ? { plant_id: plantId } : undefined,
  });
  return response.data;
};

export const getAnomaly = async (anomalyId: string): Promise<Anomaly> => {
  const response = await apiClient.get<Anomaly>(`/anomalies/${anomalyId}`);
  return response.data;
};

export const triageAnomaly = async (
  anomalyId: string,
  data: {
    status?: string;
    severity?: string;
    status_note?: string;
    rca_narrative?: Record<string, any>;
    summary?: string;
  }
): Promise<Anomaly> => {
  const response = await apiClient.patch<Anomaly>(`/anomalies/${anomalyId}`, data);
  return response.data;
};

export const bulkTriageAnomalies = async (
  payload: BulkAnomalyTriageRequest
): Promise<BulkAnomalyTriageResponse> => {
  const response = await apiClient.post<BulkAnomalyTriageResponse>('/anomalies/bulk-triage', payload);
  return response.data;
};

export const getAnomalyEvidence = async (anomalyId: string): Promise<AnomalyEvidenceResponse> => {
  const response = await apiClient.get<AnomalyEvidenceResponse>(`/anomalies/${anomalyId}/evidence`);
  return response.data;
};

export const triggerPlantAnomalyScan = async (
  plantId: string,
  windowHours: number = 24
): Promise<Record<string, any>> => {
  const response = await apiClient.post<Record<string, any>>(`/anomalies/scan-plant/${plantId}`, null, {
    params: { window_hours: windowHours },
  });
  return response.data;
};
