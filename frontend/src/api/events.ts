import { apiClient } from './client';
import { PlantIQEvent, EventCreateRequest, EventImportSummary } from '../types';

export interface GetEventsFilterParams {
  plant_id?: string;
  asset_id?: string;
  severity?: string;
  event_type?: string;
  source?: string;
  start_time_gte?: string;
  end_time_lte?: string;
  limit?: number;
  offset?: number;
}

export const getEvents = async (params?: GetEventsFilterParams): Promise<PlantIQEvent[]> => {
  const response = await apiClient.get<PlantIQEvent[]>('/events', { params });
  return response.data;
};

export const createEvent = async (eventData: EventCreateRequest): Promise<PlantIQEvent> => {
  const response = await apiClient.post<PlantIQEvent>('/events', eventData);
  return response.data;
};

export const importEventsCSV = async (
  file: File,
  defaultPlantId?: string
): Promise<EventImportSummary> => {
  const formData = new FormData();
  formData.append('file', file);
  if (defaultPlantId) {
    formData.append('default_plant_id', defaultPlantId);
  }

  const response = await apiClient.post<EventImportSummary>('/events/import-csv', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};
