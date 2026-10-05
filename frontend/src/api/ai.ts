import { apiClient } from './client';
import { AIProfileResponse } from '../types';

export interface AIProfileParams {
  file_id?: string;
  file_path?: string;
  sparkline_points?: number;
}

export const profileFile = async (params: AIProfileParams): Promise<AIProfileResponse> => {
  const response = await apiClient.post<AIProfileResponse>('/ai/profile', params);
  return response.data;
};
