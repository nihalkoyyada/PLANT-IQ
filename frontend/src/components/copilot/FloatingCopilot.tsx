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
  Maximize2,
  MessageSquare,
  Minimize2,
  Minus,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Square,
  Terminal,
  X,
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
} from '../../api/copilot';
import {
  ChartSpec,
  CitationMetadata,
  ConversationItem,
  CopilotInfo,
  CopilotMessage,
  CopilotPageContext,
  ToolTraceStep,
} from '../../types/copilot';
import { Plant } from '../../types';

export interface FloatingCopilotProps {
  selectedPlant: Plant | null;
  activeTab: string;
  pageContext?: CopilotPageContext;
  initialPrompt?: string | null;
  isOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  onClearInitialPrompt?: () => void;
}

export const FloatingCopilot: React.FC<FloatingCopilotProps> = ({
  selectedPlant,
  activeTab,
  pageContext,
  initialPrompt,
  isOpen: controlledIsOpen,
  onOpenChange,
  onClearInitialPrompt,
}) => {
  // Panel open / closed state (supports controlled or self-managed)
  const [internalIsOpen, setInternalIsOpen] = useState<boolean>(false);
  const isOpen = controlledIsOpen !== undefined ? controlledIsOpen : internalIsOpen;

  const setIsOpen = (open: boolean) => {
    if (onOpenChange) {
      onOpenChange(open);
    } else {
      setInternalIsOpen(open);
    }
  };

  // View mode: 'compact' (default panel), 'expanded' (larger), 'minimized' (docked pill)
  const [viewMode, setViewMode] = useState<'compact' | 'expanded' | 'minimized'>('compact');
  const [showHistoryDropdown, setShowHistoryDropdown] = useState<boolean>(false);

  // Copilot runtime and chat state
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
  const plantName = selectedPlant?.name || pageContext?.plantName || 'Surya Solar Farm';

  // Load copilot info and past conversations
  useEffect(() => {
    getCopilotInfo()
      .then((info) => setCopilotInfo(info))
      .catch((err) => console.warn('Could not fetch copilot info:', err));

    if (plantId) {
      loadConversations();
    }
  }, [plantId]);

  // Handle incoming initial prompt from contextual "Ask Copilot" actions
  useEffect(() => {
    if (initialPrompt && initialPrompt.trim()) {
      setInputPrompt(initialPrompt.trim());
      setIsOpen(true);
      if (viewMode === 'minimized') {
        setViewMode('compact');
      }
      onClearInitialPrompt?.();
      setTimeout(() => textareaRef.current?.focus(), 150);
    }
  }, [initialPrompt]);

  // Auto-scroll messages container to bottom when messages update
  useEffect(() => {
    if (isOpen && viewMode !== 'minimized') {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isStreaming, isOpen, viewMode]);

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
    setShowHistoryDropdown(false);
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
    setShowHistoryDropdown(false);
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
    const element = document.getElementById(`floating-tool-step-${msgId}-${seq}`);
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
                className={`inline-flex items-center px-1.5 py-0.5 mx-0.5 text-[10px] font-mono font-bold rounded transition ${
                  isFocused
                    ? 'bg-amber-400 text-slate-900 ring-2 ring-amber-400/50 shadow'
                    : 'bg-sky-100 text-[#004874] hover:bg-sky-200 border border-sky-300'
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

  // Context-aware starter questions based on active route
  const getContextualStarterPrompts = () => {
    const route = (pageContext?.route || activeTab || 'dashboard').toLowerCase();

    if (route === 'dashboard') {
      return [
        {
          title: 'Fleet Performance',
          prompt: "Explain today's fleet performance and underperforming inverters.",
          icon: Activity,
        },
        {
          title: 'PR & Shortfall',
          prompt: 'Compute the 24-hour Performance Ratio and generation shortfall for Surya Solar Farm.',
          icon: Zap,
        },
        {
          title: 'Loss Breakdown',
          prompt: 'Analyze inverter energy deficits and breakdown loss causes across the fleet.',
          icon: AlertCircle,
        },
      ];
    }

    if (route === 'telemetry') {
      const signals = pageContext?.selectedSignals?.length
        ? ` for ${pageContext.selectedSignals.join(', ')}`
        : '';
      return [
        {
          title: 'Telemetry Trends',
          prompt: `Explain the selected telemetry trends${signals} and identify unusual behavior.`,
          icon: Activity,
        },
        {
          title: 'Solar Curve vs POA',
          prompt: 'Plot solar active power generation vs POA irradiance for today.',
          icon: BarChart2,
        },
        {
          title: 'String Balance',
          prompt: 'Check string telemetry balance across active inverters.',
          icon: Zap,
        },
      ];
    }

    if (route === 'devices') {
      const assetTarget = pageContext?.assetName ? ` for ${pageContext.assetName}` : '';
      return [
        {
          title: 'Inverter Performance',
          prompt: `Analyze this inverter's performance${assetTarget} and possible causes of power loss.`,
          icon: Zap,
        },
        {
          title: 'Clipping Check',
          prompt: `Check inverter clipping status${assetTarget} and DC/AC conversion efficiency.`,
          icon: BarChart2,
        },
        {
          title: 'Fleet Top Losers',
          prompt: 'Identify the top 5 underperforming inverters by energy loss over the last 7 days.',
          icon: AlertCircle,
        },
      ];
    }

    if (route === 'anomalies') {
      const anomTarget = pageContext?.anomalyTitle
        ? ` (${pageContext.anomalyTitle})`
        : pageContext?.anomalyId
        ? ` (${pageContext.anomalyId.slice(0, 8)})`
        : '';
      return [
        {
          title: 'Explain Anomaly',
          prompt: `Explain this anomaly${anomTarget} and correlate it with available weather telemetry.`,
          icon: AlertCircle,
        },
        {
          title: 'Trip Hypotheses',
          prompt: 'Evaluate operational hypotheses for this event and recommend technician actions.',
          icon: Zap,
        },
        {
          title: 'Historical Recurrence',
          prompt: 'Check whether similar anomalies have occurred on this inverter in the past 30 days.',
          icon: Activity,
        },
      ];
    }

    // Default / Plants / Other routes
    return [
      {
        title: 'Plant Overview',
        prompt: `Give me a summary of ${plantName} performance and active telemetry.`,
        icon: Activity,
      },
      {
        title: 'Operational Health',
        prompt: 'Check active anomalies, inverter trips, and operational health status.',
        icon: AlertCircle,
      },
      {
        title: 'Solar Generation Curve',
        prompt: 'Show me a chart of solar generation vs POA irradiance for today.',
        icon: BarChart2,
      },
    ];
  };

  const starterPrompts = getContextualStarterPrompts();

  // -------------------------------------------------------------
  // 1. Minimized State: Sleek compact white dock pill
  // -------------------------------------------------------------
  if (isOpen && viewMode === 'minimized') {
    return (
      <div
        id="floating-copilot-minimized"
        className="fixed z-50 bottom-20 md:bottom-6 right-4 md:right-6 bg-white/95 backdrop-blur-md border border-slate-300 shadow-xl rounded-full px-3.5 py-2 flex items-center gap-2.5 text-slate-800 animate-in fade-in duration-200"
      >
        <button
          onClick={() => setViewMode('compact')}
          className="flex items-center gap-2 text-xs font-semibold hover:text-[#004874] transition"
          title="Restore Solar Copilot"
        >
          <div className="relative">
            <Sparkles className="w-4 h-4 text-[#004874]" />
            <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          </div>
          <span>Solar Copilot</span>
          {isStreaming && (
            <span className="text-[10px] font-mono text-[#004874] flex items-center gap-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>Thinking...</span>
            </span>
          )}
        </button>

        <div className="h-4 w-px bg-slate-200 mx-1" />

        <button
          onClick={() => setViewMode('compact')}
          className="p-1 rounded hover:bg-slate-100 text-slate-500 hover:text-slate-800 transition"
          title="Expand"
          aria-label="Expand Copilot"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => setIsOpen(false)}
          className="p-1 rounded hover:bg-slate-100 text-slate-500 hover:text-rose-600 transition"
          title="Close"
          aria-label="Close Copilot"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  // -------------------------------------------------------------
  // 2. Closed State: Launcher Button with Accessible Tooltip
  // -------------------------------------------------------------
  if (!isOpen) {
    return (
      <div className="fixed z-50 bottom-20 md:bottom-6 right-4 md:right-6 group">
        {/* Tooltip on hover */}
        <div className="absolute bottom-full right-0 mb-2.5 hidden group-hover:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-slate-800 text-xs font-semibold shadow-xl pointer-events-none whitespace-nowrap font-sans">
          <Sparkles className="w-3.5 h-3.5 text-[#004874]" />
          <span>Ask Solar Copilot</span>
          <span className="text-[10px] text-slate-500 font-mono">({plantName})</span>
        </div>

        {/* Floating Launcher Button */}
        <button
          id="btn-floating-copilot-launcher"
          onClick={() => {
            setIsOpen(true);
            setViewMode('compact');
          }}
          aria-label="Ask Solar Copilot"
          title="Ask Solar Copilot"
          className="relative w-14 h-14 rounded-full bg-gradient-to-tr from-[#004874] via-sky-600 to-cyan-500 text-white shadow-xl shadow-sky-950/20 hover:shadow-cyan-500/30 hover:scale-105 active:scale-95 transition-all duration-200 flex items-center justify-center border-2 border-white focus:outline-none focus:ring-4 focus:ring-sky-400/40"
        >
          <Sparkles className="w-6 h-6 text-white animate-pulse" />

          {/* Glowing Status Dot */}
          <span
            className={`absolute top-1 right-1 w-3.5 h-3.5 rounded-full border-2 border-white ${
              copilotInfo?.is_mock ? 'bg-amber-400' : 'bg-emerald-400'
            }`}
          />
        </button>
      </div>
    );
  }

  // -------------------------------------------------------------
  // 3. Open State: Clean White Background Floating Window
  // -------------------------------------------------------------
  const isExpanded = viewMode === 'expanded';

  return (
    <div
      id="floating-copilot-window"
      role="region"
      aria-label="Solar SCADA Copilot Chatbot"
      className={`fixed z-50 transition-all duration-200 ease-out flex flex-col bg-white border border-slate-200 shadow-2xl rounded-2xl overflow-hidden font-sans text-slate-800 ${
        isExpanded
          ? 'bottom-4 md:bottom-6 right-2 md:right-6 w-[calc(100vw-1rem)] sm:w-[740px] lg:w-[860px] h-[calc(100vh-2rem)] sm:h-[740px] max-h-[92vh]'
          : 'bottom-20 md:bottom-6 right-2 md:right-6 w-[calc(100vw-1rem)] sm:w-[440px] h-[580px] max-h-[calc(100vh-6rem)]'
      }`}
    >
      {/* ---------------- Panel Header ---------------- */}
      <div className="h-13 px-3.5 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between shrink-0 select-none">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-7 h-7 rounded-lg bg-sky-100 border border-sky-300 flex items-center justify-center shrink-0">
            <Sparkles className="w-4 h-4 text-[#004874]" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-bold text-xs md:text-sm text-slate-900 truncate">Solar Copilot</span>
              <span
                className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold uppercase tracking-wider ${
                  copilotInfo?.is_mock
                    ? 'bg-amber-100 text-amber-900 border border-amber-300'
                    : 'bg-emerald-100 text-emerald-900 border border-emerald-300'
                }`}
              >
                {copilotInfo?.is_mock ? 'Mock' : 'Live'}
              </span>
            </div>
          </div>
        </div>

        {/* Header Action Controls */}
        <div className="flex items-center gap-1 text-slate-500">
          {/* Conversation History Popover Toggle */}
          <div className="relative">
            <button
              onClick={() => setShowHistoryDropdown((prev) => !prev)}
              className="p-1.5 rounded-lg hover:bg-slate-200/80 text-slate-600 hover:text-slate-900 transition"
              title="Prior Conversations"
              aria-label="Conversation history"
            >
              <MessageSquare className="w-4 h-4" />
            </button>

            {showHistoryDropdown && (
              <div className="absolute right-0 top-full mt-1.5 w-64 bg-white border border-slate-200 rounded-xl shadow-2xl p-2 z-50 text-xs text-slate-800">
                <div className="flex items-center justify-between px-2 py-1 text-[10px] font-mono uppercase text-slate-500 border-b border-slate-100 pb-1.5 mb-1.5">
                  <span>Chat Threads</span>
                  <button
                    onClick={handleNewConversation}
                    className="text-[#004874] hover:text-sky-700 flex items-center gap-1 font-bold"
                  >
                    <Plus className="w-3 h-3" />
                    <span>New</span>
                  </button>
                </div>
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {conversations.length === 0 ? (
                    <div className="p-3 text-center text-slate-400 text-[11px] font-mono">
                      No saved threads
                    </div>
                  ) : (
                    conversations.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => handleSelectConversation(c.id)}
                        className={`w-full text-left p-2 rounded-lg text-xs truncate flex items-center justify-between gap-2 transition ${
                          c.id === activeConversationId
                            ? 'bg-sky-50 text-[#004874] border border-sky-200 font-semibold'
                            : 'hover:bg-slate-100 text-slate-700'
                        }`}
                      >
                        <span className="truncate">{c.title || 'Untitled Session'}</span>
                        <span className="text-[10px] font-mono text-slate-400 shrink-0">
                          {c.message_count}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          {/* New Chat Button */}
          <button
            onClick={handleNewConversation}
            className="p-1.5 rounded-lg hover:bg-slate-200/80 text-slate-600 hover:text-slate-900 transition"
            title="Start New Investigation"
            aria-label="New Investigation"
          >
            <Plus className="w-4 h-4" />
          </button>

          {/* Minimize Button */}
          <button
            onClick={() => setViewMode('minimized')}
            className="p-1.5 rounded-lg hover:bg-slate-200/80 text-slate-600 hover:text-slate-900 transition"
            title="Minimize"
            aria-label="Minimize Copilot"
          >
            <Minus className="w-4 h-4" />
          </button>

          {/* Expand / Restore Button */}
          <button
            onClick={() => setViewMode(isExpanded ? 'compact' : 'expanded')}
            className="p-1.5 rounded-lg hover:bg-slate-200/80 text-slate-600 hover:text-slate-900 transition hidden sm:inline-flex"
            title={isExpanded ? 'Restore' : 'Expand'}
            aria-label={isExpanded ? 'Restore window size' : 'Expand window size'}
          >
            {isExpanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>

          {/* Close Button */}
          <button
            onClick={() => setIsOpen(false)}
            className="p-1.5 rounded-lg hover:bg-slate-200/80 text-slate-600 hover:text-rose-600 transition"
            title="Close"
            aria-label="Close Copilot"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ---------------- Active SCADA Page Context Pill ---------------- */}
      <div className="px-3.5 py-1.5 bg-slate-50/70 border-b border-slate-200 flex items-center justify-between text-[11px] font-mono text-slate-600 shrink-0 overflow-x-auto">
        <div className="flex items-center gap-2 truncate">
          <span className="text-[#004874] font-bold truncate flex items-center gap-1">
            <span>📍</span>
            <span>{plantName}</span>
          </span>
          <span className="text-slate-300">·</span>
          <span className="capitalize text-slate-800 font-medium">
            {pageContext?.route || activeTab || 'Dashboard'}
          </span>
          {pageContext?.assetName && (
            <>
              <span className="text-slate-300">·</span>
              <span className="text-amber-700 font-semibold truncate">⚡ {pageContext.assetName}</span>
            </>
          )}
          {pageContext?.anomalyTitle && (
            <>
              <span className="text-slate-300">·</span>
              <span className="text-rose-700 font-semibold truncate">⚠️ {pageContext.anomalyTitle}</span>
            </>
          )}
          {pageContext?.selectedSignals && pageContext.selectedSignals.length > 0 && (
            <>
              <span className="text-slate-300">·</span>
              <span className="text-emerald-700 font-semibold truncate">
                📊 {pageContext.selectedSignals.slice(0, 2).join(', ')}
                {pageContext.selectedSignals.length > 2
                  ? ` +${pageContext.selectedSignals.length - 2}`
                  : ''}
              </span>
            </>
          )}
        </div>
        <div className="text-[10px] text-slate-400 shrink-0 ml-2">Active Scope</div>
      </div>

      {/* ---------------- Messages Scroll Container ---------------- */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-4 bg-white">
        {messages.length === 0 ? (
          /* Empty State: Contextual Starter Prompts */
          <div className="py-6 px-1 space-y-4 text-center">
            <div className="w-10 h-10 rounded-xl bg-sky-50 border border-sky-200 flex items-center justify-center mx-auto text-[#004874] shadow-xs">
              <Bot className="w-5 h-5" />
            </div>
            <div className="space-y-1">
              <h3 className="text-xs font-bold text-slate-900">How can I assist your operations?</h3>
              <p className="text-[11px] text-slate-500 max-w-xs mx-auto leading-relaxed">
                Solar Copilot analyzes SCADA telemetry, computes PR, and detects inverter anomalies
                in real time.
              </p>
            </div>

            {/* Starter Suggestion Chips */}
            <div className="pt-2 space-y-2 text-left">
              <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 px-1">
                Contextual Questions for{' '}
                <span className="text-[#004874] font-bold uppercase">
                  {pageContext?.route || activeTab}
                </span>
                :
              </div>
              <div className="grid grid-cols-1 gap-2">
                {starterPrompts.map((item, idx) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={idx}
                      onClick={() => handleSendMessage(item.prompt)}
                      className="w-full p-2.5 rounded-xl bg-slate-50 hover:bg-sky-50/70 border border-slate-200 hover:border-sky-300 text-slate-700 hover:text-slate-900 transition flex items-start gap-2.5 text-left group shadow-xs"
                    >
                      <Icon className="w-4 h-4 text-[#004874] shrink-0 mt-0.5 group-hover:text-sky-600" />
                      <div className="min-w-0">
                        <div className="text-xs font-bold text-[#004874] group-hover:text-sky-700">
                          {item.title}
                        </div>
                        <div className="text-[11px] text-slate-600 line-clamp-2 leading-relaxed">
                          {item.prompt}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        ) : (
          /* Message List */
          messages.map((msg) => {
            const isUser = msg.role === 'user';
            const hasTools = (msg.tool_calls || []).length > 0;
            const hasCharts = (msg.charts || []).length > 0;
            const isWorkingExpanded = expandedWorking[msg.id] ?? false;

            return (
              <div
                key={msg.id}
                className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} w-full`}
              >
                {/* Bubble */}
                <div
                  className={`rounded-2xl p-3 text-xs leading-relaxed max-w-[92%] sm:max-w-[85%] ${
                    isUser
                      ? 'bg-[#004874] text-white rounded-br-none shadow-sm'
                      : 'bg-slate-50 text-slate-800 border border-slate-200 rounded-bl-none shadow-xs'
                  }`}
                >
                  {/* Assistant Header Tag */}
                  {!isUser && (
                    <div className="flex items-center justify-between pb-1.5 mb-2 border-b border-slate-200 text-[10px] font-mono text-slate-500">
                      <span className="flex items-center gap-1 text-[#004874] font-bold">
                        <Sparkles className="w-3 h-3" />
                        <span>Copilot</span>
                      </span>
                      <span className="text-slate-400">{msg.model || 'mock-copilot-v1'}</span>
                    </div>
                  )}

                  {/* Show Working Accordion (Tool Calls) */}
                  {!isUser && hasTools && (
                    <div className="mb-2 rounded-lg bg-white border border-slate-200 overflow-hidden">
                      <button
                        onClick={() => toggleWorking(msg.id)}
                        className="w-full flex items-center justify-between p-2 text-left text-[11px] font-mono font-medium text-slate-700 hover:text-slate-900 bg-slate-100/70 hover:bg-slate-100 transition"
                      >
                        <span className="flex items-center gap-1.5">
                          <Terminal className="w-3.5 h-3.5 text-amber-600" />
                          <span>
                            Show Working ({msg.tool_calls?.length} tool{' '}
                            {msg.tool_calls?.length === 1 ? 'step' : 'steps'})
                          </span>
                        </span>
                        {isWorkingExpanded ? (
                          <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
                        ) : (
                          <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
                        )}
                      </button>

                      {isWorkingExpanded && (
                        <div className="p-2 space-y-1.5 border-t border-slate-200 bg-slate-50/70 font-mono text-[10px]">
                          {msg.tool_calls?.map((tool) => {
                            const toolKey = `${msg.id}_${tool.seq}`;
                            const isDetailsOpen = expandedToolDetails[toolKey] ?? false;
                            const isFocused = focusedToolSeq === tool.seq;

                            return (
                              <div
                                id={`floating-tool-step-${msg.id}-${tool.seq}`}
                                key={tool.seq}
                                className={`rounded border p-1.5 transition ${
                                  isFocused
                                    ? 'bg-amber-50 border-amber-400 ring-1 ring-amber-300'
                                    : 'bg-white border-slate-200'
                                }`}
                              >
                                <div className="flex items-center justify-between gap-1">
                                  <div className="flex items-center gap-1.5 truncate">
                                    <span className="px-1 py-0.2 rounded bg-sky-100 text-[#004874] font-bold text-[9px] border border-sky-300">
                                      [T{tool.seq}]
                                    </span>
                                    <span className="text-slate-800 font-semibold truncate">
                                      {tool.tool_name}
                                    </span>
                                  </div>
                                  <div className="flex items-center gap-1.5 text-[9px] shrink-0">
                                    <span className="text-slate-500">{tool.duration_ms}ms</span>
                                    <span
                                      className={`px-1 py-0.2 rounded uppercase font-bold text-[8px] ${
                                        tool.status === 'ok'
                                          ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                                          : tool.status === 'rejected'
                                          ? 'bg-amber-100 text-amber-800 border border-amber-300'
                                          : 'bg-rose-100 text-rose-800 border border-rose-300'
                                      }`}
                                    >
                                      {tool.status}
                                    </span>
                                    <button
                                      onClick={() => toggleToolDetails(toolKey)}
                                      className="text-slate-400 hover:text-slate-700 p-0.5"
                                    >
                                      {isDetailsOpen ? (
                                        <ChevronDown className="w-3 h-3" />
                                      ) : (
                                        <ChevronRight className="w-3 h-3" />
                                      )}
                                    </button>
                                  </div>
                                </div>

                                {isDetailsOpen && (
                                  <div className="mt-1.5 pt-1.5 border-t border-slate-200 space-y-1">
                                    <div className="text-slate-500 text-[9px]">Input:</div>
                                    <pre className="bg-slate-100 p-1.5 rounded overflow-x-auto text-[#004874] border border-slate-200">
                                      {JSON.stringify(tool.arguments, null, 2)}
                                    </pre>
                                    {tool.raw_output && Object.keys(tool.raw_output).length > 0 && (
                                      <>
                                        <div className="text-slate-500 text-[9px]">Output:</div>
                                        <pre className="bg-slate-100 p-1.5 rounded overflow-x-auto text-emerald-800 border border-slate-200 max-h-32">
                                          {JSON.stringify(tool.raw_output, null, 2)}
                                        </pre>
                                      </>
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
                  <div className="whitespace-pre-wrap break-words text-slate-800">
                    {isUser ? (
                      <span className="text-white">{msg.content}</span>
                    ) : msg.content ? (
                      renderFormattedContent(msg.content, msg.id)
                    ) : msg.isStreaming ? (
                      <div className="flex items-center gap-2 text-slate-500 font-mono text-xs py-1">
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-[#004874]" />
                        <span>Analyzing telemetry and reasoning...</span>
                      </div>
                    ) : null}

                    {msg.isStreaming && msg.content && (
                      <span className="inline-block w-1.5 h-3.5 ml-1 bg-[#004874] animate-pulse" />
                    )}
                  </div>

                  {/* Rendered Charts */}
                  {!isUser && hasCharts && (
                    <div className="mt-3 space-y-2">
                      {msg.charts?.map((chart, cIdx) => (
                        <div
                          key={cIdx}
                          className="rounded-xl bg-white border border-slate-200 p-2.5 shadow-xs"
                        >
                          <div className="flex items-center justify-between pb-1.5 mb-1.5 border-b border-slate-100 text-[11px]">
                            <span className="font-bold text-slate-900 flex items-center gap-1.5 truncate">
                              <BarChart2 className="w-3.5 h-3.5 text-[#004874] shrink-0" />
                              <span className="truncate">{chart.title || 'Telemetry Chart'}</span>
                            </span>
                            <span className="text-[9px] font-mono text-slate-400 uppercase">
                              {chart.chart_type}
                            </span>
                          </div>
                          <div className="h-44 w-full pt-1">
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
                                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                                <XAxis dataKey="index" stroke="#64748b" fontSize={9} />
                                <YAxis stroke="#64748b" fontSize={9} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: '#ffffff',
                                    borderColor: '#cbd5e1',
                                    color: '#0f172a',
                                    fontSize: '10px',
                                  }}
                                />
                                <Legend wrapperStyle={{ fontSize: '9px' }} />
                                {chart.series?.map((s, sIdx) => (
                                  <Line
                                    key={sIdx}
                                    type="monotone"
                                    dataKey={s.name}
                                    stroke={s.color || (sIdx === 0 ? '#0284c7' : '#f59e0b')}
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

                  {/* Latency footnote */}
                  {!isUser && msg.latency_ms && !msg.isStreaming && (
                    <div className="mt-1.5 pt-1.5 border-t border-slate-200 text-[9px] font-mono text-slate-400 flex items-center justify-between">
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
          <div className="p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center justify-between gap-2 shadow-xs">
            <div className="flex items-center gap-1.5 truncate">
              <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
              <span className="truncate">{streamError}</span>
            </div>
            <button
              onClick={() => handleSendMessage()}
              className="px-2 py-0.5 rounded bg-rose-600 hover:bg-rose-700 text-white font-mono text-[10px] font-semibold flex items-center gap-1 shrink-0 transition"
            >
              <RefreshCw className="w-3 h-3" />
              <span>Retry</span>
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ---------------- Bottom Input Box ---------------- */}
      <div className="p-3 bg-slate-50 border-t border-slate-200 shrink-0">
        <div className="relative rounded-xl bg-white border border-slate-300 focus-within:border-sky-500 focus-within:ring-2 focus-within:ring-sky-100 transition shadow-xs">
          <textarea
            ref={textareaRef}
            value={inputPrompt}
            onChange={(e) => setInputPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Ask Copilot about ${plantName} telemetry, PR, anomalies... (Enter to send)`}
            rows={2}
            disabled={isStreaming}
            className="w-full bg-transparent px-3 py-2 text-xs text-slate-900 placeholder-slate-400 focus:outline-none resize-none font-sans"
          />

          <div className="flex items-center justify-between px-3 py-1.5 border-t border-slate-100 bg-slate-50/50 rounded-b-xl text-[10px] font-mono">
            <span className="text-slate-500 truncate max-w-[200px]">
              {pageContext?.assetName
                ? `Asset: ${pageContext.assetName}`
                : `Plant: ${plantName}`}
            </span>

            <div className="flex items-center gap-1.5">
              {isStreaming ? (
                <button
                  onClick={handleStopGenerating}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs transition shadow-xs"
                  title="Stop generating"
                >
                  <Square className="w-3 h-3 fill-current" />
                  <span>Stop</span>
                </button>
              ) : (
                <button
                  onClick={() => handleSendMessage()}
                  disabled={!inputPrompt.trim()}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-[#004874] hover:bg-[#003b60] disabled:opacity-40 disabled:hover:bg-[#004874] text-white font-semibold text-xs transition shadow-xs"
                  title="Send message"
                  aria-label="Send message"
                >
                  <span>Send</span>
                  <Send className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>
        </div>
        <div className="text-[9px] font-mono text-slate-400 text-center pt-1.5">
          PlantIQ SCADA Copilot enforces tenant isolation & read-only access.
        </div>
      </div>
    </div>
  );
};
