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