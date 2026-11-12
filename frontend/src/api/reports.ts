import { apiClient } from './client';
import { Report, ReportListResponse } from '../types';

export interface GenerateReportPayload {
  plant_id: string;
  report_type: 'daily' | 'weekly';
  start_date: string;
  end_date?: string;
  title?: string;
}

export interface ListReportsParams {
  plant_id?: string;
  report_type?: string;
  status?: string;
  skip?: number;
  limit?: number;
}

export const getReports = async (params?: ListReportsParams): Promise<ReportListResponse> => {
  const response = await apiClient.get<ReportListResponse>('/reports', { params });
  return response.data;
};

export const generateReport = async (payload: GenerateReportPayload): Promise<Report> => {
  const response = await apiClient.post<Report>('/reports/generate', payload);
  return response.data;
};

export const getReport = async (id: string): Promise<Report> => {
  const response = await apiClient.get<Report>(`/reports/${id}`);
  return response.data;
};

export const downloadReport = async (id: string, defaultFilename: string = 'plantiq_report.pdf'): Promise<void> => {
  const response = await apiClient.get(`/reports/${id}/download`, {
    responseType: 'blob',
  });

  // Extract filename from Content-Disposition header if available
  let filename = defaultFilename;
  const disposition = response.headers['content-disposition'];
  if (disposition && disposition.includes('filename=')) {
    const filenameMatch = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
    if (filenameMatch && filenameMatch[1]) {
      filename = filenameMatch[1].replace(/['"]/g, '');
    }
  }

  // Create temporary anchor to trigger native browser download
  const blob = new Blob([response.data], { type: 'application/pdf' });
  const downloadUrl = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = downloadUrl;
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(downloadUrl);
};

