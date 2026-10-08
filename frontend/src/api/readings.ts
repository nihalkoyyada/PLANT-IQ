import { apiClient } from './client';
import {
  ReadingAggregate,
  ReadingSummary,
  QCStatsResponse,
} from '../types';

export interface GetReadingAggregateParams {
  channel_id: string;
  start?: string;
  end?: string;
  interval?: '5min' | '15min' | 'hour' | 'day' | 'week';
}

export interface GetReadingSummaryParams {
  channel_id: string;
  start?: string;
  end?: string;
}

export const getReadingAggregate = async (
  params: GetReadingAggregateParams
): Promise<ReadingAggregate[]> => {
  const response = await apiClient.get<ReadingAggregate[]>(
    '/readings/aggregate',
    { params }
  );

  return response.data;
};

export const getReadingSummary = async (
  params: GetReadingSummaryParams
): Promise<ReadingSummary> => {
  const response = await apiClient.get<ReadingSummary>(
    '/readings/summary',
    { params }
  );

  return response.data;
};

export const getQCStats = async (): Promise<QCStatsResponse> => {
  const response = await apiClient.get<QCStatsResponse>(
    '/readings/qc'
  );

  return response.data;
};

export interface LatestReading {
  channel_id: string;
  ts: string;
  value: number;
  quality: number;
  ingestion_job_id?: string | null;
}

export const getLatestReading = async (
  channelId: string
): Promise<LatestReading> => {
  const response = await apiClient.get<LatestReading>(
    '/readings/latest',
    {
      params: {
        channel_id: channelId,
      },
    }
  );

  return response.data;
};

export const getLatestReadingsBatch = async (
  channelIds: string[]
): Promise<Record<string, LatestReading>> => {
  if (channelIds.length === 0) return {};
  const response = await apiClient.post<Record<string, LatestReading>>(
    '/readings/latest-batch',
    { channel_ids: channelIds }
  );

  return response.data;
};

export interface PowerReading {
  channel_id: string;
  timestamp: string;
  raw_value: number;
  raw_unit?: string | null;
  value_kw: number;
  value: number;
  quality: number;
  source: string;
}

export const getLatestPowerReading = async (
  channelId: string,
  nonZero: boolean = true
): Promise<PowerReading> => {
  const response = await apiClient.get<PowerReading>(
    '/readings/latest-power',
    {
      params: {
        channel_id: channelId,
        non_zero: nonZero,
      },
    }
  );

  return response.data;
};

export const getLatestPowerReadingsBatch = async (
  channelIds: string[],
  nonZero: boolean = true
): Promise<Record<string, PowerReading>> => {
  if (channelIds.length === 0) return {};
  const response = await apiClient.post<Record<string, PowerReading>>(
    '/readings/latest-power-batch',
    { channel_ids: channelIds, non_zero: nonZero }
  );

  return response.data;
};