import { apiClient } from './client';
import {
  PlatformAuditLogResponse,
  PlatformMonitoringResponse,
  PlatformOrgListItem,
  PlatformOrgListResponse,
  PlatformOverviewResponse,
  PlatformPlantsResponse,
  PlatformSettingsResponse,
  PlatformUserListItem,
  PlatformUserListResponse,
} from '../types';

export interface PlatformOrgQueryParams {
  search?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export interface PlatformUserQueryParams {
  search?: string;
  role?: string;
  is_active?: boolean;
  org_id?: string;
  limit?: number;
  offset?: number;
}

export interface PlatformAuditLogQueryParams {
  action?: string;
  org_id?: string;
  entity?: string;
  user_id?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export const getPlatformOverview = async (): Promise<PlatformOverviewResponse> => {
  const response = await apiClient.get<PlatformOverviewResponse>('/platform/overview');
  return response.data;
};

export const getPlatformOrganizations = async (
  params?: PlatformOrgQueryParams
): Promise<PlatformOrgListResponse> => {
  const response = await apiClient.get<PlatformOrgListResponse>('/platform/organizations', {
    params,
  });
  return response.data;
};

export const createPlatformOrganization = async (payload: {
  name: string;
  details?: string;
  admin_email?: string;
  admin_password?: string;
  admin_full_name?: string;
}): Promise<PlatformOrgListItem> => {
  const response = await apiClient.post<PlatformOrgListItem>('/platform/organizations', payload);
  return response.data;
};

export const getPlatformOrganizationDetails = async (orgId: string): Promise<any> => {
  const response = await apiClient.get(`/platform/organizations/${orgId}`);
  return response.data;
};

export const updatePlatformOrganizationStatus = async (
  orgId: string,
  payload: { status: 'active' | 'suspended'; reason?: string }
): Promise<PlatformOrgListItem> => {
  const response = await apiClient.patch<PlatformOrgListItem>(
    `/platform/organizations/${orgId}/status`,
    payload
  );
  return response.data;
};

export const inspectPlatformTenant = async (orgId: string): Promise<any> => {
  const response = await apiClient.get(`/platform/organizations/${orgId}/inspect`);
  return response.data;
};

export const deletePlatformOrganization = async (orgId: string): Promise<void> => {
  await apiClient.delete(`/platform/organizations/${orgId}`);
};

export const getPlatformUsers = async (
  params?: PlatformUserQueryParams
): Promise<PlatformUserListResponse> => {
  const response = await apiClient.get<PlatformUserListResponse>('/platform/users', {
    params,
  });
  return response.data;
};

export const createPlatformUser = async (payload: {
  email: string;
  password: string;
  full_name: string;
  role: string;
  org_id?: string;
  is_active?: boolean;
}): Promise<PlatformUserListItem> => {
  const response = await apiClient.post<PlatformUserListItem>('/platform/users', payload);
  return response.data;
};

export const updatePlatformUser = async (
  userId: string,
  payload: {
    full_name?: string;
    role?: string;
    is_active?: boolean;
    password?: string;
    org_id?: string;
  }
): Promise<PlatformUserListItem> => {
  const response = await apiClient.patch<PlatformUserListItem>(`/platform/users/${userId}`, payload);
  return response.data;
};

export const deletePlatformUser = async (userId: string): Promise<void> => {
  await apiClient.delete(`/platform/users/${userId}`);
};

export const getPlatformPlantsAssets = async (): Promise<PlatformPlantsResponse> => {
  const response = await apiClient.get<PlatformPlantsResponse>('/platform/plants-assets');
  return response.data;
};

export const getPlatformMonitoring = async (): Promise<PlatformMonitoringResponse> => {
  const response = await apiClient.get<PlatformMonitoringResponse>('/platform/monitoring');
  return response.data;
};

export const getPlatformAuditLogs = async (
  params?: PlatformAuditLogQueryParams
): Promise<PlatformAuditLogResponse> => {
  const response = await apiClient.get<PlatformAuditLogResponse>('/platform/audit-logs', {
    params,
  });
  return response.data;
};

export const getPlatformSettings = async (): Promise<PlatformSettingsResponse> => {
  const response = await apiClient.get<PlatformSettingsResponse>('/platform/settings');
  return response.data;
};

export const updatePlatformSettings = async (payload: {
  platform_name?: string;
  maintenance_mode?: boolean;
  telemetry_retention_days?: number;
  session_timeout_minutes?: number;
}): Promise<PlatformSettingsResponse> => {
  const response = await apiClient.patch<PlatformSettingsResponse>('/platform/settings', payload);
  return response.data;
};
