import { apiClient } from './client';
import { Plant } from '../types';

export const getPlants = async (): Promise<Plant[]> => {
  const response = await apiClient.get<Plant[]>('/plants');
  return response.data;
};

export const getPlant = async (plantId: string): Promise<Plant> => {
  const response = await apiClient.get<Plant>(`/plants/${plantId}`);
  return response.data;
};

export const updatePlant = async (plantId: string, data: Partial<Plant>): Promise<Plant> => {
  const response = await apiClient.patch<Plant>(`/plants/${plantId}`, data);
  return response.data;
};

export const deletePlant = async (plantId: string): Promise<void> => {
  await apiClient.delete(`/plants/${plantId}`);
};

export interface PublicTelemetryTrendPoint {
  timestamp: string;
  time: string;
  ac_power_mw: number;
  dc_power_mw: number;
}

export interface PublicPlantTelemetryResponse {
  plant_id: string;
  plant_name: string;
  capacity_ac_mw: number;
  capacity_dc_mw: number;
  ac_power_mw: number;
  dc_power_mw: number;
  latest_timestamp: string | null;
  data_freshness: 'LIVE' | 'STALE' | 'OFFLINE';
  status_label: string;
  stale_days?: number | null;
  freshness_seconds?: number | null;
  inverter_count: number;
  channel_count: number;
  last_active_ac_mw?: number | null;
  last_active_dc_mw?: number | null;
  last_active_timestamp?: string | null;
  peak_ac_power_mw?: number | null;
  trend: PublicTelemetryTrendPoint[];
}

export const getPublicPlantTelemetry = async (options?: {
  plantId?: string;
  staleHours?: number;
  nonZero?: boolean;
  signal?: AbortSignal;
}): Promise<PublicPlantTelemetryResponse> => {
  const params: Record<string, any> = {};
  if (options?.plantId) params.plant_id = options.plantId;
  if (options?.staleHours !== undefined) params.stale_hours = options.staleHours;
  if (options?.nonZero !== undefined) params.non_zero = options.nonZero;

  const response = await apiClient.get<PublicPlantTelemetryResponse>('/plants/public-summary', {
    params,
    signal: options?.signal,
  });
  return response.data;
};

