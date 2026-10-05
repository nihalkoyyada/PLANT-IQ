import { apiClient } from './client';
import { IngestionJob, MappingTemplate } from '../types';

export const getMappingTemplates = async (orgId?: string): Promise<MappingTemplate[]> => {
  const params = orgId ? { org_id: orgId } : {};
  const response = await apiClient.get<MappingTemplate[]>('/mapping-templates', { params });
  return response.data;
};

export const createMappingTemplate = async (data: {
  org_id: string;
  name: string;
  source_signature: string;
  mappings: Record<string, any>;
}): Promise<MappingTemplate> => {
  const response = await apiClient.post<MappingTemplate>('/mapping-templates', data);
  return response.data;
};

export const getIngestionJobs = async (fileId?: string, templateId?: string): Promise<IngestionJob[]> => {
  const params: Record<string, string> = {};
  if (fileId) params.file_id = fileId;
  if (templateId) params.template_id = templateId;
  const response = await apiClient.get<IngestionJob[]>('/ingestion-jobs', { params });
  return response.data;
};

export const createIngestionJob = async (data: {
  file_id: string;
  template_id: string;
}): Promise<IngestionJob> => {
  const response = await apiClient.post<IngestionJob>('/ingestion-jobs', data);
  return response.data;
};

export const runIngestionJob = async (jobId: string): Promise<IngestionJob> => {
  const response = await apiClient.post<IngestionJob>(`/ingestion-jobs/${jobId}/run`);
  return response.data;
};

export const getIngestionJob = async (jobId: string): Promise<IngestionJob> => {
  const response = await apiClient.get<IngestionJob>(`/ingestion-jobs/${jobId}`);
  return response.data;
};
