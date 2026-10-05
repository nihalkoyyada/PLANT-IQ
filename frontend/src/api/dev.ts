import { apiClient } from './client';

export interface ResetSCADAResponse {
  status: string;
  cleared: Record<string, number>;
  message: string;
}

export const resetSCADAData = async (): Promise<ResetSCADAResponse> => {
  const response = await apiClient.post<ResetSCADAResponse>('/dev/reset-scada');
  return response.data;
};
