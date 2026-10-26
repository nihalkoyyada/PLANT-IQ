/**
 * Copilot API Service & Server-Sent Events (SSE) Streaming Client (§10.2, §10.3, Task S5-FS-02).
 */

import { apiClient } from './client';
import {
  ChartSpec,
  CitationMetadata,
  ConversationItem,
  CopilotChatPayload,
  CopilotInfo,
  ToolTraceStep,
} from '../types/copilot';

const BASE_URL = import.meta.env.VITE_API_URL || '/api';

export async function getCopilotInfo(): Promise<CopilotInfo> {
  const response = await apiClient.get<CopilotInfo>('/copilot/info');
  return response.data;
}

export async function listConversations(plantId: string): Promise<ConversationItem[]> {
  const response = await apiClient.get<{ conversations: ConversationItem[]; count: number }>(
    `/copilot/conversations?plant_id=${plantId}`
  );
  return response.data.conversations || [];
}

export async function getConversation(conversationId: string): Promise<{
  id: string;
  title: string;
  plant_id: string;
  created_at: string;
  messages: any[];
}> {
  const response = await apiClient.get(`/copilot/conversations/${conversationId}`);
  return response.data;
}

export interface StreamEventCallbacks {
  onStart?: (data: { conversation_id: string; message_id: string }) => void;
  onToolStart?: (step: { seq: number; tool: string; tag: string; arguments: Record<string, any> }) => void;
  onToolEnd?: (step: { seq: number; tool: string; status: 'ok' | 'error' | 'rejected'; duration_ms: number }) => void;
  onChart?: (chart: ChartSpec) => void;
  onDelta?: (text: string) => void;
  onError?: (error: { error: string; message: string; provider?: string }) => void;
  onDone?: (result: {
    conversation_id: string;
    message_id: string;
    content: string;
    tool_trace: ToolTraceStep[];
    citations: CitationMetadata[];
    charts: ChartSpec[];
    latency_ms: number;
    model: string;
  }) => void;
}

/**
 * Connect to /copilot/chat/stream SSE endpoint and stream tokens & tool events incrementally.
 */
export async function streamCopilotChat(
  payload: CopilotChatPayload,
  callbacks: StreamEventCallbacks,
  signal?: AbortSignal
): Promise<void> {
  const token = localStorage.getItem('plantiq_token');
  const url = `${BASE_URL}/copilot/chat/stream`;

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    let errorDetail = response.statusText;
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errorDetail;
    } catch {
      // ignore json parse error
    }
    throw new Error(`Copilot stream request failed (${response.status}): ${errorDetail}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Streaming response body is unavailable.');
  }

  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    // Keep incomplete trailing segment in buffer
    buffer = blocks.pop() || '';

    for (const block of blocks) {
      if (!block.trim()) continue;

      let eventType = 'message';
      let eventDataStr = '';

      const lines = block.split('\n');
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          eventDataStr = line.slice(6).trim();
        }
      }

      if (!eventDataStr) continue;

      try {
        const parsed = JSON.parse(eventDataStr);

        if (eventType === 'start' || parsed.event === 'start') {
          callbacks.onStart?.(parsed);
        } else if (eventType === 'tool_start' || parsed.event === 'tool_start') {
          callbacks.onToolStart?.(parsed);
        } else if (eventType === 'tool_end' || parsed.event === 'tool_end') {
          callbacks.onToolEnd?.(parsed);
        } else if (eventType === 'chart' || parsed.event === 'chart') {
          callbacks.onChart?.(parsed.chart || parsed);
        } else if (eventType === 'delta' || parsed.event === 'delta') {
          callbacks.onDelta?.(parsed.text || '');
        } else if (eventType === 'error' || parsed.event === 'error') {
          callbacks.onError?.(parsed);
        } else if (eventType === 'done' || parsed.event === 'done') {
          callbacks.onDone?.(parsed.result || parsed);
        }
      } catch (e) {
        console.warn('Failed to parse SSE event data block:', eventDataStr, e);
      }
    }
  }
}
