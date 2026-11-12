import { apiClient } from './client';
import {
  AdminSummaryResponse,
  AdminUserListResponse,
  AuditLogListResponse,
  Organization,
  User,
} from '../types';

export interface GetAdminUsersParams {
  org_id?: string;
  role?: string;
  is_active?: boolean;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface CreateAdminUserPayload {
  email: string;
  password: string;
  full_name: string;
  role: string;
  is_active?: boolean;
  org_id?: string;
}

export interface UpdateAdminUserPayload {
  full_name?: string;
  role?: string;
  is_active?: boolean;
  password?: string;
}

export interface GetAuditLogsParams {
  action?: string;
  entity?: string;
  user_id?: string;
  start_time?: string;
  end_time?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface CreateOrgPayload {
  name: string;
  admin_email?: string;
  admin_password?: string;
  admin_full_name?: string;
}

// User Management
export const getAdminUsers = async (
  params?: GetAdminUsersParams
): Promise<AdminUserListResponse> => {
  const response = await apiClient.get<AdminUserListResponse>('/admin/users', {
    params,
  });
  return response.data;
};

export const createAdminUser = async (
  payload: CreateAdminUserPayload
): Promise<User> => {
  const response = await apiClient.post<User>('/admin/users', payload);
  return response.data;
};

export const updateAdminUser = async (
  userId: string,
  payload: UpdateAdminUserPayload
): Promise<User> => {
  const response = await apiClient.patch<User>(`/admin/users/${userId}`, payload);
  return response.data;
};

export const deleteAdminUser = async (userId: string): Promise<void> => {
  await apiClient.delete(`/admin/users/${userId}`);
};

// Audit Log Viewer
export const getAuditLogs = async (
  params?: GetAuditLogsParams
): Promise<AuditLogListResponse> => {
  const response = await apiClient.get<AuditLogListResponse>('/admin/audit-logs', {
    params,
  });
  return response.data;
};

export const getAuditLogActions = async (): Promise<string[]> => {
  const response = await apiClient.get<string[]>('/admin/audit-logs/actions');
  return response.data;
};

// Admin Summary
export const getAdminSummary = async (): Promise<AdminSummaryResponse> => {
  const response = await apiClient.get<AdminSummaryResponse>('/admin/summary');
  return response.data;
};

// Organizations (Super Admin)
export const getOrganizations = async (): Promise<Organization[]> => {
  const response = await apiClient.get<Organization[]>('/organizations');
  return response.data;
};

export const createOrganization = async (
  payload: CreateOrgPayload
): Promise<Organization> => {
  const response = await apiClient.post<Organization>('/organizations', payload);
  return response.data;
};

// Invitations (Org Admin & Super Admin)
export interface UserInvitation {
  id: string;
  token: string;
  email: string;
  full_name: string;
  role: string;
  org_id: string;
  org_name?: string;
  status: string;
  expires_at: string;
  created_at: string;
  invitation_link?: string;
}

export interface InviteUserPayload {
  email: string;
  full_name: string;
  role: 'engineer' | 'viewer' | 'admin';
  org_id?: string;
}

export const inviteUserApi = async (payload: InviteUserPayload): Promise<UserInvitation> => {
  const response = await apiClient.post<UserInvitation>('/admin/invitations', payload);
  return response.data;
};

export const listInvitationsApi = async (params?: { org_id?: string; status?: string }): Promise<{ total: number; items: UserInvitation[] }> => {
  const response = await apiClient.get<{ total: number; items: UserInvitation[] }>('/admin/invitations', { params });
  return response.data;
};

export const revokeInvitationApi = async (invitationId: string): Promise<void> => {
  await apiClient.delete(`/admin/invitations/${invitationId}`);
};

