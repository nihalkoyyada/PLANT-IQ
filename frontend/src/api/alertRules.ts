import { apiClient } from './client';
import { AlertDelivery, AlertRule } from '../types';

export const getAlertRules = async (plantId?: string): Promise<AlertRule[]> => {
  const response = await apiClient.get<AlertRule[]>('/alert-rules', {
    params: plantId ? { plant_id: plantId } : undefined,
  });
  return response.data;
};

export const getAlertRule = async (ruleId: string): Promise<AlertRule> => {
  const response = await apiClient.get<AlertRule>(`/alert-rules/${ruleId}`);
  return response.data;
};

export const createAlertRule = async (data: Partial<AlertRule> & { plant_id: string; name: string; metric: string; threshold: number; direction: string; severity: string }): Promise<AlertRule> => {
  const response = await apiClient.post<AlertRule>('/alert-rules', data);
  return response.data;
};

export const updateAlertRule = async (
  ruleId: string,
  data: Partial<AlertRule>
): Promise<AlertRule> => {
  const response = await apiClient.patch<AlertRule>(`/alert-rules/${ruleId}`, data);
  return response.data;
};

export const deleteAlertRule = async (ruleId: string): Promise<void> => {
  await apiClient.delete(`/alert-rules/${ruleId}`);
};

export const testAlertRule = async (
  ruleId: string,
  data: { recipient_override?: string; test_message?: string }
): Promise<{ rule_id: string; channel: string; status: string; message: string; recipient: string }> => {
  const response = await apiClient.post(`/alert-rules/${ruleId}/test`, data);
  return response.data;
};

export const getAlertDeliveries = async (plantId?: string, limit: number = 50): Promise<AlertDelivery[]> => {
  const response = await apiClient.get<AlertDelivery[]>('/alert-rules/deliveries', {
    params: {
      plant_id: plantId || undefined,
      limit,
    },
  });
  return response.data;
};

export interface EmailDiagnostics {
  is_configured: boolean;
  provider: string;
  from_email: string;
  env_file_detected: boolean;
  env_file_path?: string;
  mock_mode_active: boolean;
}

export const getEmailDiagnostics = async (): Promise<EmailDiagnostics> => {
  const response = await apiClient.get<EmailDiagnostics>('/alert-rules/email-diagnostics');
  return response.data;
};

