import { apiClient } from './client';
import { TokenResponse, User } from '../types';

export const loginApi = async (
  email: string,
  password: string,
  portal?: 'platform_admin' | 'scada'
): Promise<TokenResponse> => {
  const payload: { email: string; password: string; portal?: string } = {
    email: email.trim(),
    password,
  };
  if (portal) {
    payload.portal = portal;
  }
  const response = await apiClient.post<TokenResponse>('/auth/login', payload);
  return response.data;
};

export const registerApi = async (data: {
  email: string;
  password: string;
  full_name: string;
  org_id?: string;
  organization_name?: string;
  role?: string;
  invitation_token?: string;
}): Promise<TokenResponse> => {
  const response = await apiClient.post<TokenResponse>('/auth/register', data);
  return response.data;
};

export interface InvitationVerifyResult {
  valid: boolean;
  email: string;
  full_name: string;
  role: string;
  org_id: string;
  org_name: string;
  expires_at: string;
}

export const verifyInvitationApi = async (token: string): Promise<InvitationVerifyResult> => {
  const response = await apiClient.get<InvitationVerifyResult>(`/auth/invitations/${encodeURIComponent(token)}`);
  return response.data;
};

export const acceptInvitationApi = async (token: string, password: string): Promise<TokenResponse> => {
  const response = await apiClient.post<TokenResponse>('/auth/invitations/accept', {
    token,
    password,
  });
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
