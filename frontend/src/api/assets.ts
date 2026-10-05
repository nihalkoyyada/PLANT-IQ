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
