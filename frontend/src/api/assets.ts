import { apiClient } from './client';
import { Asset } from '../types';

export const getAssets = async (): Promise<Asset[]> => {
  const response = await apiClient.get<Asset[]>('/assets');
  return response.data;
};

export const getAsset = async (assetId: string): Promise<Asset> => {
  const response = await apiClient.get<Asset>(`/assets/${assetId}`);
  return response.data;
};

export const updateAsset = async (assetId: string, data: Partial<Asset>): Promise<Asset> => {
  const response = await apiClient.patch<Asset>(`/assets/${assetId}`, data);
  return response.data;
};

export const deleteAsset = async (assetId: string): Promise<void> => {
  await apiClient.delete(`/assets/${assetId}`);
};
