import React, { useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertCircle,
  BarChart2,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Layers,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Square,
  Terminal,
  Zap,
} from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import {
  getCopilotInfo,
  getConversation,
  listConversations,
  streamCopilotChat,
} from '../api/copilot';
import {
  ChartSpec,
  CitationMetadata,
  ConversationItem,
  CopilotInfo,
  CopilotMessage,
  ToolTraceStep,
} from '../types/copilot';
import { Plant } from '../types';

interface CopilotPageProps {
  selectedPlant: Plant | null;
  initialPrompt?: string | null;
  onClearInitialPrompt?: () => void;
}

export const CopilotPage: React.FC<CopilotPageProps> = ({
  selectedPlant,
  initialPrompt,
  onClearInitialPrompt,
}) => {
  const [copilotInfo, setCopilotInfo] = useState<CopilotInfo | null>(null);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [inputPrompt, setInputPrompt] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [expandedWorking, setExpandedWorking] = useState<Record<string, boolean>>({});
  const [expandedToolDetails, setExpandedToolDetails] = useState<Record<string, boolean>>({});
  const [focusedToolSeq, setFocusedToolSeq] = useState<number | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const plantId = selectedPlant?.id || 'd253760d-d8ad-4a18-b655-fc22a5222d59';

  // Load Copilot runtime info and conversation list on mount
  useEffect(() => {
    getCopilotInfo()
      .then((info) => setCopilotInfo(info))
      .catch((err) => console.warn('Could not fetch copilot info:', err));

    if (plantId) {
      loadConversations();
    }
  }, [plantId]);

  // Handle incoming initial prompt (from contextual Ask Copilot triggers)
  useEffect(() => {
    if (initialPrompt && initialPrompt.trim()) {
      setInputPrompt(initialPrompt.trim());
      onClearInitialPrompt?.();
      // Auto-focus input
      setTimeout(() => textareaRef.current?.focus(), 100);
    }
  }, [initialPrompt]);

  // Auto scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  const loadConversations = async () => {
    try {
      const list = await listConversations(plantId);
      setConversations(list);
    } catch (err) {
      console.warn('Failed to load copilot conversations:', err);
    }
  };

  const handleSelectConversation = async (convId: string) => {
    if (isStreaming) return;
    setActiveConversationId(convId);
    setStreamError(null);
    try {
      const details = await getConversation(convId);
      const formatted: CopilotMessage[] = (details.messages || []).map((m: any) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        model: m.model,
        latency_ms: m.latency_ms,
        created_at: m.created_at,
        tool_calls: (m.tool_calls || []).map((tc: any) => ({
          seq: tc.seq,
          tool_name: tc.tool_name,
          arguments: tc.input || {},
          raw_output: tc.output || {},
          status: tc.status,
          duration_ms: tc.duration_ms || 0,
          tool_call_id: tc.id,
        })),
        charts: (m.charts || []).map((ch: any) => ch.spec || ch),
      }));
      setMessages(formatted);
    } catch (err) {
      console.error('Failed to load conversation details:', err);
      setStreamError('Could not retrieve conversation history.');
    }
  };

  const handleNewConversation = () => {
    if (isStreaming) {
      handleStopGenerating();
    }
    setActiveConversationId(null);
    setMessages([]);
    setStreamError(null);
    setInputPrompt('');
    setTimeout(() => textareaRef.current?.focus(), 50);
  };

  const handleStopGenerating = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
  };

  const handleSendMessage = async (promptToSend?: string) => {
    const text = (promptToSend || inputPrompt).trim();
    if (!text || isStreaming) return;

    setInputPrompt('');
    setStreamError(null);
    setFocusedToolSeq(null);

    const userMsgId = 'user_' + Date.now();
    const assistantMsgId = 'asst_' + Date.now();

    const userMsg: CopilotMessage = {
      id: userMsgId,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    };

    const initialAssistantMsg: CopilotMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      tool_calls: [],
      charts: [],
      citations: [],
      isStreaming: true,
      model: copilotInfo?.model || 'mock-copilot-v1',
    };

    setMessages((prev) => [...prev, userMsg, initialAssistantMsg]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await streamCopilotChat(
        {
          prompt: text,
          plant_id: plantId,
          conversation_id: activeConversationId,
        },
        {
          onStart: (data) => {
            if (!activeConversationId && data.conversation_id) {
              setActiveConversationId(data.conversation_id);
              loadConversations();
            }
          },
          onToolStart: (step) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                const tools = [...(last.tool_calls || [])];
                const existingIndex = tools.findIndex((t) => t.seq === step.seq);
                const newStep: ToolTraceStep = {
                  seq: step.seq,
                  tool_name: step.tool,
                  arguments: step.arguments || {},
                  raw_output: {},
                  status: 'ok',
                  duration_ms: 0,
                };
                if (existingIndex >= 0) {
                  tools[existingIndex] = { ...tools[existingIndex], ...newStep };
                } else {
                  tools.push(newStep);
                }
                last.tool_calls = tools;
              }
              return updated;
            });
          },
          onToolEnd: (step) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                const tools = [...(last.tool_calls || [])];
                const idx = tools.findIndex((t) => t.seq === step.seq);
                if (idx >= 0) {
                  tools[idx] = {
                    ...tools[idx],
                    status: step.status,
                    duration_ms: step.duration_ms,
                  };
                }
                last.tool_calls = tools;
              }
              return updated;
            });
          },
          onChart: (chart) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                last.charts = [...(last.charts || []), chart];
              }
              return updated;
            });
          },
          onDelta: (chunk) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                last.content = (last.content || '') + chunk;
              }
              return updated;
            });
          },
          onError: (err) => {
            setStreamError(`${err.error || 'Provider Error'}: ${err.message}`);
          },
          onDone: (result) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                last.content = result.content || last.content;
                last.tool_calls = result.tool_trace || last.tool_calls;
                last.charts = result.charts || last.charts;
                last.citations = result.citations || [];
                last.latency_ms = result.latency_ms;
                last.model = result.model || last.model;
                last.isStreaming = false;
              }
              return updated;
            });
            loadConversations();
          },
        },
        controller.signal
      );
    } catch (err: any) {
      if (err.name === 'AbortError') {
        console.log('User cancelled stream');
      } else {
        console.error('Error during chat stream:', err);
        setStreamError(err.message || 'Stream connection failed.');
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.role === 'assistant') {
          last.isStreaming = false;
        }
        return updated;
      });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const toggleWorking = (msgId: string) => {
    setExpandedWorking((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  const toggleToolDetails = (toolKey: string) => {
    setExpandedToolDetails((prev) => ({ ...prev, [toolKey]: !prev[toolKey] }));
  };

  const handleCitationClick = (msgId: string, seq: number) => {
    setExpandedWorking((prev) => ({ ...prev, [msgId]: true }));
    setFocusedToolSeq(seq);
    const element = document.getElementById(`tool-step-${msgId}-${seq}`);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  // Render clickable citation tags [T1], [T2]
  const renderFormattedContent = (content: string, msgId: string) => {
    if (!content) return null;
    const parts = content.split(/(\[T\d+\])/g);
    return (
      <span className="leading-relaxed">
        {parts.map((part, i) => {
          const match = part.match(/\[T(\d+)\]/);
          if (match) {
            const seq = parseInt(match[1], 10);
            const isFocused = focusedToolSeq === seq;
            return (
              <button
                key={i}
                onClick={() => handleCitationClick(msgId, seq)}
                title={`Jump to Tool Step [T${seq}] in Show Working`}
                className={`inline-flex items-center px-1.5 py-0.5 mx-0.5 text-[11px] font-mono font-bold rounded transition ${
                  isFocused
                    ? 'bg-amber-400 text-slate-900 ring-2 ring-amber-400/50 shadow'
                    : 'bg-sky-100 text-sky-800 hover:bg-sky-200 border border-sky-300/60'
                }`}
              >
                {part}
              </button>
            );
          }
          return <span key={i}>{part}</span>;
        })}
      </span>
    );
  };

  const quickPrompts = [
    {
      title: 'Plant Overview',
      prompt: 'Give me a summary of Surya Solar Farm performance and telemetry.',
      icon: Activity,
    },
    {
      title: 'PR & KPI Check',
      prompt: 'Compute the 24-hour Performance Ratio and generation shortfall.',
      icon: Zap,
    },
    {
      title: 'Anomaly Investigation',
      prompt: 'Check active anomalies and underperforming inverters on the plant.',
      icon: AlertCircle,
    },
    {
      title: 'Plot Solar Curve',
      prompt: 'Show me a chart of solar generation vs POA irradiance for today.',
      icon: BarChart2,
    },
  ];

  return (
    <div className="flex h-[calc(100vh-80px)] bg-slate-900 text-slate-100 rounded-xl overflow-hidden border border-slate-800 shadow-2xl font-sans">
      {/* ---------------- Left Sidebar: Conversations ---------------- */}
      <div className="w-72 bg-slate-950 border-r border-slate-800/80 flex flex-col justify-between hidden md:flex">
        <div className="p-4 flex flex-col h-full overflow-hidden">
          {/* New Chat Button */}
          <button
            onClick={handleNewConversation}
            className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold text-xs transition shadow-md shadow-sky-900/30 mb-4"
          >
            <Plus className="w-4 h-4" />
            <span>New Investigation</span>
          </button>

          {/* Conversations List */}
          <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
            <div className="px-2 py-1 text-[10px] font-mono font-semibold uppercase text-slate-500 tracking-wider">
              INVESTIGATION THREADS
            </div>
            {conversations.length === 0 ? (
              <div className="p-4 text-center text-xs text-slate-500 font-mono">
                No prior threads found
              </div>
            ) : (
              conversations.map((c) => {
                const isActive = c.id === activeConversationId;
                return (
                  <button
                    key={c.id}
                    onClick={() => handleSelectConversation(c.id)}
                    className={`w-full text-left p-2.5 rounded-lg text-xs transition flex flex-col gap-1 border ${
                      isActive
                        ? 'bg-slate-800/90 border-sky-500/60 text-sky-200 shadow-sm'
                        : 'bg-slate-900/50 border-transparent hover:bg-slate-800/50 text-slate-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 font-medium truncate">
                      <MessageSquare className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                      <span className="truncate">{c.title || 'Untitled Session'}</span>
                    </div>
                    <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 px-5">
                      <span>{c.message_count} turns</span>
                      <span>{new Date(c.created_at).toLocaleDateString()}</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Runtime / Provider Footer Badge */}
        <div className="p-3 border-t border-slate-800/80 bg-slate-950/80 text-[11px] font-mono">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="flex items-center gap-1.5">
              <Bot className="w-3.5 h-3.5 text-sky-400" />
              <span>AI Provider</span>
            </span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                copilotInfo?.is_mock
                  ? 'bg-amber-400/20 text-amber-300 border border-amber-400/30'
                  : 'bg-emerald-400/20 text-emerald-300 border border-emerald-400/30'
              }`}
            >
              {copilotInfo?.is_mock ? 'Mock Mode' : 'Live Provider'}
            </span>
          </div>
          <div className="text-slate-500 text-[10px] truncate">
            Model: <span className="text-slate-300">{copilotInfo?.model || 'mock-copilot-v1'}</span>
          </div>
          <div className="text-slate-500 text-[10px] flex items-center justify-between mt-1">
            <span>SCADA Tools:</span>
            <span className="text-sky-300 font-semibold">{copilotInfo?.tool_count || 12} ready</span>
          </div>
        </div>
      </div>

      {/* ---------------- Main Chat Area ---------------- */}
      <div className="flex-1 flex flex-col bg-slate-900">
        {/* Top Header Bar */}
        <div className="h-14 px-4 bg-slate-950/70 border-b border-slate-800 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-sky-600/20 border border-sky-500/40 flex items-center justify-center shadow-inner">
              <Sparkles className="w-4 h-4 text-sky-400" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-white flex items-center gap-2">
                <span>Solar SCADA Copilot</span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-sky-950 text-sky-300 border border-sky-800">
                  Sprint 5
                </span>
              </h1>
              <div className="text-[11px] font-mono text-slate-400 flex items-center gap-2">
                <span>Active Asset:</span>
                <span className="text-sky-300 font-semibold">
                  {selectedPlant?.name || 'Surya Solar Farm (27.5 MW AC)'}
                </span>
              </div>
            </div>
          </div>

          {/* Provider Status Pill */}
          <div className="flex items-center gap-2">
            {copilotInfo?.is_mock ? (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-950/60 border border-amber-600/40 text-amber-300 text-xs font-mono">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                <span>Deterministic Mock LLM</span>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-950/60 border border-emerald-600/40 text-emerald-300 text-xs font-mono">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span>Anthropic Claude Live</span>
              </div>
            )}
          </div>
        </div>

        {/* Messages Stream Container */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-5">
          {messages.length === 0 ? (
            /* Empty State / Welcome Screen */
            <div className="max-w-2xl mx-auto py-8 text-center space-y-6">
              <div className="w-14 h-14 rounded-2xl bg-sky-600/10 border border-sky-500/30 flex items-center justify-center mx-auto shadow-lg shadow-sky-950">
                <Bot className="w-7 h-7 text-sky-400" />
              </div>
              <div className="space-y-2">
                <h2 className="text-xl font-bold text-white tracking-tight">
                  Welcome to PlantIQ Solar Copilot
                </h2>
                <p className="text-xs text-slate-400 max-w-lg mx-auto leading-relaxed">
                  Ask natural-language questions about SCADA telemetry, solar farm Performance
                  Ratio, active inverters, clipping, or tripping anomalies. The agent autonomously
                  orchestrates operational diagnostic tools.
                </p>
              </div>

              {/* Quick Starter Prompts */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-left pt-2">
                {quickPrompts.map((item, idx) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={idx}
                      onClick={() => handleSendMessage(item.prompt)}
                      className="p-3.5 rounded-xl bg-slate-950/60 hover:bg-slate-800/80 border border-slate-800 hover:border-sky-500/50 text-slate-300 hover:text-white transition group flex flex-col gap-1.5 shadow-sm"
                    >
                      <div className="flex items-center gap-2 font-semibold text-xs text-sky-400 group-hover:text-sky-300">
                        <Icon className="w-4 h-4" />
                        <span>{item.title}</span>
                      </div>
                      <div className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed font-sans">
                        {item.prompt}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            /* Chat Messages List */
            messages.map((msg) => {
              const isUser = msg.role === 'user';
              const hasTools = (msg.tool_calls || []).length > 0;
              const hasCharts = (msg.charts || []).length > 0;
              const isWorkingExpanded = expandedWorking[msg.id] ?? false;

              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-4xl mx-auto w-full`}
                >
                  {/* Message Bubble */}
                  <div
                    className={`rounded-2xl p-4 text-xs md:text-sm max-w-[90%] md:max-w-[85%] ${
                      isUser
                        ? 'bg-sky-600 text-white rounded-br-none shadow-md shadow-sky-900/20'
                        : 'bg-slate-950/90 text-slate-200 border border-slate-800/90 rounded-bl-none shadow-md shadow-black/40'
                    }`}
                  >
                    {/* Assistant Header Badge */}
                    {!isUser && (
                      <div className="flex items-center justify-between gap-3 pb-2.5 mb-2.5 border-b border-slate-800/80 text-[11px] font-mono text-slate-400">
                        <span className="flex items-center gap-1.5 text-sky-400 font-semibold">
                          <Sparkles className="w-3.5 h-3.5" />
                          <span>PlantIQ Copilot</span>
                        </span>
                        <span className="text-slate-500 text-[10px]">
                          {msg.model || 'mock-copilot-v1'}
                        </span>
                      </div>
                    )}

                    {/* Show Working Accordion (Tool Calls) */}
                    {!isUser && hasTools && (
                      <div className="mb-3 rounded-lg bg-slate-900/90 border border-slate-800 overflow-hidden">
                        <button
                          onClick={() => toggleWorking(msg.id)}
                          className="w-full flex items-center justify-between p-2.5 text-left text-xs font-mono font-medium text-slate-300 hover:text-white bg-slate-800/50 hover:bg-slate-800/80 transition"
                        >
                          <span className="flex items-center gap-2">
                            <Terminal className="w-3.5 h-3.5 text-amber-400" />
                            <span>
                              Show Working ({msg.tool_calls?.length} SCADA tool execution{' '}
                              {msg.tool_calls?.length === 1 ? 'step' : 'steps'})
                            </span>
                          </span>
                          {isWorkingExpanded ? (
                            <ChevronDown className="w-4 h-4 text-slate-400" />
                          ) : (
                            <ChevronRight className="w-4 h-4 text-slate-400" />
                          )}
                        </button>

                        {/* Expanded Tool Execution Steps */}
                        {isWorkingExpanded && (
                          <div className="p-2.5 space-y-2 border-t border-slate-800 bg-slate-950/60 font-mono text-xs">
                            {msg.tool_calls?.map((tool) => {
                              const toolKey = `${msg.id}_${tool.seq}`;
                              const isDetailsOpen = expandedToolDetails[toolKey] ?? false;
                              const isFocused = focusedToolSeq === tool.seq;

                              return (
                                <div
                                  id={`tool-step-${msg.id}-${tool.seq}`}
                                  key={tool.seq}
                                  className={`rounded border p-2 transition ${
                                    isFocused
                                      ? 'bg-amber-950/30 border-amber-500/60 ring-1 ring-amber-500/40'
                                      : 'bg-slate-900/70 border-slate-800'
                                  }`}
                                >
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="flex items-center gap-2">
                                      <span className="px-1.5 py-0.5 rounded bg-sky-950 text-sky-300 font-bold text-[10px] border border-sky-800">
                                        [T{tool.seq}]
                                      </span>
                                      <span className="text-slate-200 font-semibold">
                                        {tool.tool_name}
                                      </span>
                                    </div>
                                    <div className="flex items-center gap-2 text-[10px]">
                                      <span className="text-slate-400 flex items-center gap-1">
                                        <Clock className="w-3 h-3" />
                                        {tool.duration_ms}ms
                                      </span>
                                      <span
                                        className={`px-1.5 py-0.5 rounded uppercase font-bold text-[9px] ${
                                          tool.status === 'ok'
                                            ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                            : tool.status === 'rejected'
                                            ? 'bg-amber-950 text-amber-400 border border-amber-800'
                                            : 'bg-rose-950 text-rose-400 border border-rose-800'
                                        }`}
                                      >
                                        {tool.status}
                                      </span>
                                      <button
                                        onClick={() => toggleToolDetails(toolKey)}
                                        className="text-slate-400 hover:text-white p-0.5 rounded"
                                      >
                                        {isDetailsOpen ? (
                                          <ChevronDown className="w-3.5 h-3.5" />
                                        ) : (
                                          <ChevronRight className="w-3.5 h-3.5" />
                                        )}
                                      </button>
                                    </div>
                                  </div>

                                  {/* Expandable JSON Inspector */}
                                  {isDetailsOpen && (
                                    <div className="mt-2 pt-2 border-t border-slate-800/80 space-y-1.5 text-[10px]">
                                      <div>
                                        <div className="text-slate-500">Parameters:</div>
                                        <pre className="bg-slate-950 p-1.5 rounded overflow-x-auto text-sky-300 border border-slate-800">
                                          {JSON.stringify(tool.arguments, null, 2)}
                                        </pre>
                                      </div>
                                      {tool.raw_output && Object.keys(tool.raw_output).length > 0 && (
                                        <div>
                                          <div className="text-slate-500">Output:</div>
                                          <pre className="bg-slate-950 p-1.5 rounded overflow-x-auto text-emerald-300 border border-slate-800 max-h-40">
                                            {JSON.stringify(tool.raw_output, null, 2)}
                                          </pre>
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Main Content Body */}
                    <div className="whitespace-pre-wrap break-words">
                      {isUser ? (
                        msg.content
                      ) : msg.content ? (
                        renderFormattedContent(msg.content, msg.id)
                      ) : msg.isStreaming ? (
                        <div className="flex items-center gap-2 text-slate-400 font-mono text-xs py-1">
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />
                          <span>Analyzing telemetry and reasoning...</span>
                        </div>
                      ) : null}

                      {/* Blinking streaming cursor */}
                      {msg.isStreaming && msg.content && (
                        <span className="inline-block w-1.5 h-3.5 ml-1 bg-sky-400 animate-pulse" />
                      )}
                    </div>

                    {/* Rendered Charts Visualization */}
                    {!isUser && hasCharts && (
                      <div className="mt-4 space-y-3">
                        {msg.charts?.map((chart, cIdx) => (
                          <div
                            key={cIdx}
                            className="rounded-xl bg-slate-900 border border-slate-800 p-3 shadow-inner"
                          >
                            <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800 text-xs">
                              <span className="font-bold text-white flex items-center gap-1.5">
                                <BarChart2 className="w-4 h-4 text-sky-400" />
                                {chart.title || 'Telemetry Chart'}
                              </span>
                              <span className="text-[10px] font-mono text-slate-500 uppercase">
                                {chart.chart_type}
                              </span>
                            </div>
                            <div className="h-48 w-full pt-1">
                              <ResponsiveContainer width="100%" height="100%">
                                <LineChart
                                  data={(chart.series?.[0]?.data || []).map((v, i) => {
                                    const point: Record<string, any> = { index: i + 1 };
                                    chart.series?.forEach((s) => {
                                      point[s.name] = s.data?.[i] ?? 0;
                                    });
                                    return point;
                                  })}
                                >
                                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                  <XAxis dataKey="index" stroke="#94a3b8" fontSize={10} />
                                  <YAxis stroke="#94a3b8" fontSize={10} />
                                  <Tooltip
                                    contentStyle={{
                                      backgroundColor: '#0f172a',
                                      borderColor: '#334155',
                                      color: '#f8fafc',
                                      fontSize: '11px',
                                    }}
                                  />
                                  <Legend wrapperStyle={{ fontSize: '10px' }} />
                                  {chart.series?.map((s, sIdx) => (
                                    <Line
                                      key={sIdx}
                                      type="monotone"
                                      dataKey={s.name}
                                      stroke={s.color || (sIdx === 0 ? '#38bdf8' : '#f59e0b')}
                                      dot={false}
                                      strokeWidth={2}
                                    />
                                  ))}
                                </LineChart>
                              </ResponsiveContainer>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Metadata Footnote */}
                    {!isUser && msg.latency_ms && !msg.isStreaming && (
                      <div className="mt-2 pt-2 border-t border-slate-800/60 text-[10px] font-mono text-slate-500 flex items-center justify-between">
                        <span>Latency: {msg.latency_ms}ms</span>
                        <span>{new Date(msg.created_at).toLocaleTimeString()}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}

          {/* Error Banner */}
          {streamError && (
            <div className="max-w-2xl mx-auto p-3 rounded-lg bg-rose-950/80 border border-rose-600/50 text-rose-200 text-xs flex items-center justify-between gap-3 shadow-lg">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{streamError}</span>
              </div>
              <button
                onClick={() => handleSendMessage()}
                className="px-2.5 py-1 rounded bg-rose-900 hover:bg-rose-800 text-white font-mono text-[11px] font-semibold flex items-center gap-1 transition"
              >
                <RefreshCw className="w-3 h-3" />
                <span>Retry</span>
              </button>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* ---------------- Bottom Input Box ---------------- */}
        <div className="p-4 bg-slate-950 border-t border-slate-800/80">
          <div className="max-w-4xl mx-auto space-y-2">
            <div className="relative rounded-xl bg-slate-900 border border-slate-700/80 focus-within:border-sky-500 transition shadow-inner">
              <textarea
                ref={textareaRef}
                value={inputPrompt}
                onChange={(e) => setInputPrompt(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask Copilot about plant telemetry, PR index, inverter faults, or generate charts... (Enter to send)"
                rows={2}
                disabled={isStreaming}
                className="w-full bg-transparent px-3.5 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none resize-none font-sans"
              />

              <div className="flex items-center justify-between px-3 py-1.5 border-t border-slate-800/60 bg-slate-950/40 rounded-b-xl text-[11px] font-mono">
                <div className="flex items-center gap-2 text-slate-500">
                  <span>Plant:</span>
                  <span className="text-slate-300 font-medium truncate max-w-[200px]">
                    {selectedPlant?.name || 'Surya Solar Farm'}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {isStreaming ? (
                    <button
                      onClick={handleStopGenerating}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs transition shadow"
                    >
                      <Square className="w-3.5 h-3.5 fill-current" />
                      <span>Stop</span>
                    </button>
                  ) : (
                    <button
                      onClick={() => handleSendMessage()}
                      disabled={!inputPrompt.trim()}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:hover:bg-sky-600 text-white font-semibold text-xs transition shadow shadow-sky-900/30"
                    >
                      <span>Send</span>
                      <Send className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
            <div className="text-[10px] font-mono text-slate-500 text-center">
              PlantIQ SCADA Copilot enforces plant tenant isolation, read-only telemetry queries,
              and strict execution safeguards.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
