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
