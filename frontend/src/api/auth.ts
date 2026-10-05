import { apiClient } from './client';
import { TokenResponse, User } from '../types';

export const loginApi = async (email: string, password: string): Promise<TokenResponse> => {
  const response = await apiClient.post<TokenResponse>('/auth/login', {
    email: email.trim(),
    password,
  });
  return response.data;
};

export const getMeApi = async (): Promise<User> => {
  const response = await apiClient.get<User>('/auth/me');
  return response.data;
};
