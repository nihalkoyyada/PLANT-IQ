import { apiClient } from './client';
import { TokenResponse, User } from '../types';

export const loginApi = async (email: string, password: string): Promise<TokenResponse> => {
  const response = await apiClient.post<TokenResponse>('/auth/login', {
    email: email.trim(),
    password,
  });
  return response.data;
};

export const registerApi = async (data: {
  email: string;
  password: string;
  full_name: string;
  org_id?: string;
  organization_name?: string;
  role?: string;
}): Promise<TokenResponse> => {
  const response = await apiClient.post<TokenResponse>('/auth/register', data);
  return response.data;
};

export const refreshTokenApi = async (refreshToken: string): Promise<TokenResponse> => {
  const response = await apiClient.post<TokenResponse>('/auth/refresh', {
    refresh_token: refreshToken,
  });
  return response.data;
};

export const getMeApi = async (): Promise<User> => {
  const response = await apiClient.get<User>('/auth/me');
  return response.data;
};
