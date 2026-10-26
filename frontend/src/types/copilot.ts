/**
 * Copilot Agent & Streaming Chat TypeScript Interfaces (§10.2, §10.3, Tasks S5-FS-01, S5-FS-02, S5-FS-03).
 */

export interface ToolTraceStep {
  seq: number;
  tool_name: string;
  arguments: Record<string, any>;
  raw_output: Record<string, any>;
  status: 'ok' | 'error' | 'rejected';
  duration_ms: number;
  tool_call_id?: string | null;
  chart_id?: string | null;
  created_at?: string;
}

export interface CitationMetadata {
  index: number;
  tool_name: string;
  tool_call_id?: string | null;
  tag: string; // e.g. "[T1]"
  arguments?: Record<string, any>;
  summary_snippet?: string;
}

export interface ChartSpec {
  chart_id?: string;
  title: string;
  chart_type: 'line' | 'bar' | 'scatter' | 'area';
  x_axis?: {
    type?: string;
    name?: string;
    data?: any[];
  };
  y_axis?: {
    name?: string;
    unit?: string;
  };
  series: Array<{
    name: string;
    type?: string;
    color?: string;
    data: any[];
    data_ref?: string;
  }>;
  created_at?: string;
}

export interface CopilotMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  model?: string | null;
  latency_ms?: number | null;
  created_at: string;
  tool_calls?: ToolTraceStep[];
  citations?: CitationMetadata[];
  charts?: ChartSpec[];
  isStreaming?: boolean;
}

export interface ConversationItem {
  id: string;
  title: string | null;
  plant_id: string;
  created_at: string;
  message_count: number;
}

export interface CopilotInfo {
  provider: 'mock' | 'live' | string;
  provider_class: string;
  model: string;
  is_mock: boolean;
  tool_count: number;
  tools: string[];
}

export interface CopilotChatPayload {
  prompt: string;
  plant_id: string;
  conversation_id?: string | null;
  client_message_id?: string | null;
}

export interface CopilotPageContext {
  route: string;
  plantId?: string;
  plantName?: string;
  assetId?: string;
  assetName?: string;
  anomalyId?: string;
  anomalyTitle?: string;
  selectedSignals?: string[];
  dateRange?: string;
}

