import { apiClient } from './client';
import { Channel } from '../types';

export const getChannels = async (): Promise<Channel[]> => {
  const response = await apiClient.get<Channel[]>('/channels');
  return response.data;
};

export const getChannel = async (channelId: string): Promise<Channel> => {
  const response = await apiClient.get<Channel>(`/channels/${channelId}`);
  return response.data;
};

export const updateChannel = async (channelId: string, data: Partial<Channel>): Promise<Channel> => {
  const response = await apiClient.patch<Channel>(`/channels/${channelId}`, data);
  return response.data;
};

export const deleteChannel = async (channelId: string): Promise<void> => {
  await apiClient.delete(`/channels/${channelId}`);
};