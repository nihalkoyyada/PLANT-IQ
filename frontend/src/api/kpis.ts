import { apiClient } from './client';
import { PRHeatmapResponse, LossAnalysisResponse } from '../types';

export const getPRHeatmap = async (
  plantId?: string,
  range: string = '24h'
): Promise<PRHeatmapResponse> => {
  const url = plantId ? `/plants/${plantId}/kpis/heatmap` : '/plants/kpis/heatmap';
  const response = await apiClient.get<PRHeatmapResponse>(url, {
    params: { range },
  });
  return response.data;
};

export const getTopLosers = async (
  plantId?: string,
  range: string = '24h',
  limit: number = 10
): Promise<LossAnalysisResponse> => {
  const url = plantId ? `/plants/${plantId}/kpis/top-losers` : '/plants/kpis/top-losers';
  const response = await apiClient.get<LossAnalysisResponse>(url, {
    params: { range, limit },
  });
  return response.data;
};
