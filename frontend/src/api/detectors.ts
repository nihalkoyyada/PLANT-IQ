import { apiClient } from './client';
import { Detector } from '../types';

export const getDetectors = async (plantId?: string): Promise<Detector[]> => {
  const response = await apiClient.get<Detector[]>('/detectors', {
    params: plantId ? { plant_id: plantId } : undefined,
  });
  return response.data;
};

export const getDetector = async (detectorId: string): Promise<Detector> => {
  const response = await apiClient.get<Detector>(`/detectors/${detectorId}`);
  return response.data;
};

export const createDetector = async (data: Partial<Detector> & { plant_id: string; name: string; method: string; canonical_key: string }): Promise<Detector> => {
  const response = await apiClient.post<Detector>('/detectors', data);
  return response.data;
};

export const updateDetector = async (
  detectorId: string,
  data: Partial<Detector>
): Promise<Detector> => {
  const response = await apiClient.patch<Detector>(`/detectors/${detectorId}`, data);
  return response.data;
};

export const deleteDetector = async (detectorId: string): Promise<void> => {
  await apiClient.delete(`/detectors/${detectorId}`);
};
