import { apiClient } from './client';
import { CanonicalSignal } from '../types';

export const getCanonicalSignals = async (): Promise<CanonicalSignal[]> => {
  const response = await apiClient.get<CanonicalSignal[]>('/canonical-signals');
  return response.data;
};

export const getCanonicalSignal = async (key: string): Promise<CanonicalSignal> => {
  const response = await apiClient.get<CanonicalSignal>(`/canonical-signals/${key}`);
  return response.data;
};

export const createCanonicalSignal = async (data: CanonicalSignal): Promise<CanonicalSignal> => {
  const response = await apiClient.post<CanonicalSignal>('/canonical-signals', data);
  return response.data;
};

export const updateCanonicalSignal = async (
  key: string,
  data: Partial<CanonicalSignal>
): Promise<CanonicalSignal> => {
  const response = await apiClient.patch<CanonicalSignal>(`/canonical-signals/${key}`, data);
  return response.data;
};

export const deleteCanonicalSignal = async (key: string): Promise<void> => {
  await apiClient.delete(`/canonical-signals/${key}`);
};
