import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import React, { useState } from 'react';
import { CopilotPage } from '../pages/CopilotPage';
import { FloatingCopilot } from '../components/copilot/FloatingCopilot';
import * as copilotApi from '../api/copilot';
import { Plant } from '../types';
import { CopilotPageContext } from '../types/copilot';

// Polyfill ResizeObserver and scrollIntoView for jsdom
(globalThis as any).ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

Element.prototype.scrollIntoView = vi.fn();

const mockPlant: Plant = {
  id: 'd253760d-d8ad-4a18-b655-fc22a5222d59',
  org_id: 'org-1',
  name: 'Surya Solar Farm',
  plant_type: 'solar',
  capacity_ac_kw: 27500,
  capacity_dc_kwp: 28280,
  latitude: 28.5,
  longitude: 77.2,
  timezone: 'Asia/Kolkata',
  cod_date: '2020-01-01',
  expected_pr: 0.80,
  tariff_inr_per_kwh: 3.50,
  metadata: {},
  created_at: '2026-01-01T00:00:00Z',
};

describe('Sprint 5 Copilot UI & Streaming Tests (S5-FS-02 & S5-FS-03)', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.spyOn(copilotApi, 'getCopilotInfo').mockResolvedValue({
      provider: 'mock',
      provider_class: 'MockLLMProvider',
      model: 'mock-copilot-v1',
      is_mock: true,
      tool_count: 12,
      tools: ['query_timeseries', 'get_plant_summary', 'render_chart'],
    });

    vi.spyOn(copilotApi, 'listConversations').mockResolvedValue([
      {
        id: 'conv-101',
        title: 'Surya PR & Inverter Analysis',
        plant_id: mockPlant.id,
        created_at: '2026-10-15T12:00:00Z',
        message_count: 2,
      },
    ]);

    vi.spyOn(copilotApi, 'getConversation').mockResolvedValue({
      id: 'conv-101',
      title: 'Surya PR & Inverter Analysis',
      plant_id: mockPlant.id,
      created_at: '2026-10-15T12:00:00Z',
      messages: [
        {
          id: 'msg-u1',
          role: 'user',
          content: 'What is today Performance Ratio?',
          created_at: '2026-10-15T12:00:00Z',
          tool_calls: [],
          charts: [],
        },
        {
          id: 'msg-a1',
          role: 'assistant',
          content: 'Based on [T1], the 24-hour Performance Ratio for Surya Solar Farm is 81.4%.',
          model: 'mock-copilot-v1',
          latency_ms: 124,
          created_at: '2026-10-15T12:00:01Z',
          tool_calls: [
            {
              id: 'tc-1',
              seq: 1,
              tool_name: 'compute_kpi_pr',
              input: { plant_id: mockPlant.id, hours: 24 },
              output: { plant_pr: 81.4, status: 'nominal' },
              status: 'ok',
              duration_ms: 45,
              created_at: '2026-10-15T12:00:00Z',
            },
          ],
          charts: [],
        },
      ],
    });
  });

  // =========================================================================
  // Dedicated Copilot Page Tests (Preserved Functionality)
  // =========================================================================

  it('renders dedicated Copilot page with Deterministic Mock LLM badge and active plant name', async () => {
    render(<CopilotPage selectedPlant={mockPlant} />);

    await waitFor(() => {
      expect(screen.getByText('Deterministic Mock LLM')).toBeDefined();
    });

    expect(screen.getByText('Solar SCADA Copilot')).toBeDefined();
    expect(screen.getAllByText('Surya Solar Farm').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('mock-copilot-v1')).toBeDefined();
  });

  it('displays past conversation threads in sidebar and loads message history on click', async () => {
    render(<CopilotPage selectedPlant={mockPlant} />);

    await waitFor(() => {
      expect(screen.getByText('Surya PR & Inverter Analysis')).toBeDefined();
    });

    const threadButton = screen.getByText('Surya PR & Inverter Analysis');
    fireEvent.click(threadButton);

    await waitFor(() => {
      expect(screen.getByText('What is today Performance Ratio?')).toBeDefined();
    });

    expect(screen.getByText(/Show Working/i)).toBeDefined();
    expect(screen.getByText('[T1]')).toBeDefined();
  });

  it('toggles Show Working accordion and reveals tool call parameters', async () => {
    render(<CopilotPage selectedPlant={mockPlant} />);

    await waitFor(() => {
      expect(screen.getByText('Surya PR & Inverter Analysis')).toBeDefined();
    });

    fireEvent.click(screen.getByText('Surya PR & Inverter Analysis'));

    await waitFor(() => {
      expect(screen.getByText(/Show Working/i)).toBeDefined();
    });

    const showWorkingBtn = screen.getByText(/Show Working/i);
    fireEvent.click(showWorkingBtn);

    await waitFor(() => {
      expect(screen.getByText('compute_kpi_pr')).toBeDefined();
    });
  });

  it('handles contextual initialPrompt pre-filling and clears it on dedicated page', async () => {
    const handleClear = vi.fn();
    const promptText = 'Investigate anomaly on Inverter 04: trip event at 12:00';

    render(
      <CopilotPage
        selectedPlant={mockPlant}
        initialPrompt={promptText}
        onClearInitialPrompt={handleClear}
      />
    );

    const textarea = screen.getByPlaceholderText(/Ask Copilot about plant telemetry/i) as HTMLTextAreaElement;
    expect(textarea.value).toBe(promptText);
    expect(handleClear).toHaveBeenCalledTimes(1);
  });

  it('calls streamCopilotChat when user submits message and renders stream events on dedicated page', async () => {
    const streamSpy = vi.spyOn(copilotApi, 'streamCopilotChat').mockImplementation(
      async (payload, callbacks) => {
        callbacks.onStart?.({ conversation_id: 'conv-new', message_id: 'msg-start' });
        callbacks.onToolStart?.({
          seq: 1,
          tool: 'get_plant_summary',
          tag: '[T1]',
          arguments: { plant_id: mockPlant.id },
        });
        callbacks.onToolEnd?.({
          seq: 1,
          tool: 'get_plant_summary',
          status: 'ok',
          duration_ms: 30,
        });
        callbacks.onDelta?.('Plant Surya is operating at nominal output.');
        callbacks.onDone?.({
          conversation_id: 'conv-new',
          message_id: 'msg-done',
          content: 'Plant Surya is operating at nominal output.',
          tool_trace: [],
          citations: [],
          charts: [],
          latency_ms: 150,
          model: 'mock-copilot-v1',
        });
      }
    );

    render(<CopilotPage selectedPlant={mockPlant} />);

    const textarea = screen.getByPlaceholderText(/Ask Copilot about plant telemetry/i);
    fireEvent.change(textarea, { target: { value: 'Summarize solar generation' } });

    const sendBtn = screen.getByRole('button', { name: /Send/i });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(streamSpy).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(screen.getByText('Plant Surya is operating at nominal output.')).toBeDefined();
    });
  });

  // =========================================================================
  // Persistent Floating Copilot Chatbot Tests (Requirements 1-6)
  // =========================================================================

  it('renders fixed launcher button with AI icon and accessible tooltip', async () => {
    render(<FloatingCopilot selectedPlant={mockPlant} activeTab="dashboard" isOpen={false} />);

    const launcherBtn = screen.getByRole('button', { name: /Ask Solar Copilot/i });
    expect(launcherBtn).toBeDefined();
    expect(launcherBtn.getAttribute('title')).toBe('Ask Solar Copilot');
    expect(launcherBtn.getAttribute('id')).toBe('btn-floating-copilot-launcher');
  });

  it('supports opening, minimizing, expanding, and closing the floating panel', async () => {
    const TestContainer = () => {
      const [isOpen, setIsOpen] = useState(false);
      return (
        <div>
          <button id="external-open-btn" onClick={() => setIsOpen(true)}>
            Open Widget
          </button>
          <FloatingCopilot
            selectedPlant={mockPlant}
            activeTab="dashboard"
            isOpen={isOpen}
            onOpenChange={setIsOpen}
          />
        </div>
      );
    };

    render(<TestContainer />);

    // Initially closed: launcher is visible
    expect(screen.getByRole('button', { name: /Ask Solar Copilot/i })).toBeDefined();
    expect(screen.queryByRole('region', { name: /Solar SCADA Copilot Chatbot/i })).toBeNull();

    // Click launcher to open
    const launcherBtn = screen.getByRole('button', { name: /Ask Solar Copilot/i });
    fireEvent.click(launcherBtn);

    // Panel should now be open
    await waitFor(() => {
      expect(screen.getByRole('region', { name: /Solar SCADA Copilot Chatbot/i })).toBeDefined();
    });

    // Minimize panel
    const minimizeBtn = screen.getByRole('button', { name: /Minimize Copilot/i });
    fireEvent.click(minimizeBtn);

    // Minimized pill should be visible
    await waitFor(() => {
      expect(screen.getByText(/Solar Copilot/i)).toBeDefined();
      expect(screen.getByTitle(/Restore Solar Copilot/i)).toBeDefined();
    });

    // Restore panel
    const restoreBtn = screen.getByTitle(/Restore Solar Copilot/i);
    fireEvent.click(restoreBtn);

    await waitFor(() => {
      expect(screen.getByRole('region', { name: /Solar SCADA Copilot Chatbot/i })).toBeDefined();
    });

    // Expand panel
    const expandBtn = screen.getByRole('button', { name: /Expand window size/i });
    fireEvent.click(expandBtn);

    // Should now show restore button
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Restore window size/i })).toBeDefined();
    });

    // Close panel
    const closeBtn = screen.getByRole('button', { name: /Close Copilot/i });
    fireEvent.click(closeBtn);

    // Panel should be closed and launcher visible again
    await waitFor(() => {
      expect(screen.queryByRole('region', { name: /Solar SCADA Copilot Chatbot/i })).toBeNull();
      expect(screen.getByRole('button', { name: /Ask Solar Copilot/i })).toBeDefined();
    });
  });

  it('displays structured page context in header pill and updates reactively', async () => {
    const pageContext: CopilotPageContext = {
      route: 'devices',
      plantId: mockPlant.id,
      plantName: 'Surya Solar Farm',
      assetId: 'inv-04',
      assetName: 'Inverter INV-04',
    };

    const { rerender } = render(
      <FloatingCopilot
        selectedPlant={mockPlant}
        activeTab="devices"
        pageContext={pageContext}
        isOpen={true}
      />
    );

    // Verify context pill elements
    expect(screen.getAllByText('Surya Solar Farm').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('devices').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('⚡ Inverter INV-04')).toBeDefined();

    // Rerender with telemetry context
    const updatedContext: CopilotPageContext = {
      route: 'telemetry',
      plantId: mockPlant.id,
      plantName: 'Surya Solar Farm',
      selectedSignals: ['power_ac', 'irradiance_poa'],
      dateRange: '2026-10-01 to 2026-10-15',
    };

    rerender(
      <FloatingCopilot
        selectedPlant={mockPlant}
        activeTab="telemetry"
        pageContext={updatedContext}
        isOpen={true}
      />
    );

    expect(screen.getAllByText('telemetry').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/power_ac, irradiance_poa/i).length).toBeGreaterThanOrEqual(1);
  });

  it('renders route-specific contextual starter questions', async () => {
    // 1. Dashboard starter prompts
    const { rerender } = render(
      <FloatingCopilot
        selectedPlant={mockPlant}
        activeTab="dashboard"
        pageContext={{ route: 'dashboard', plantName: mockPlant.name }}
        isOpen={true}
      />
    );

    expect(screen.getByText('Fleet Performance')).toBeDefined();
    expect(screen.getByText("Explain today's fleet performance and underperforming inverters.")).toBeDefined();

    // 2. Anomaly Inbox starter prompts
    rerender(
      <FloatingCopilot
        selectedPlant={mockPlant}
        activeTab="anomalies"
        pageContext={{ route: 'anomalies', anomalyTitle: 'Midday Inverter Trip' }}
        isOpen={true}
      />
    );

    expect(screen.getByText('Explain Anomaly')).toBeDefined();
    expect(screen.getByText(/Explain this anomaly \(Midday Inverter Trip\)/i)).toBeDefined();
    expect(screen.getByText('Trip Hypotheses')).toBeDefined();

    // 3. Telemetry Explorer starter prompts
    rerender(
      <FloatingCopilot
        selectedPlant={mockPlant}
        activeTab="telemetry"
        pageContext={{ route: 'telemetry', selectedSignals: ['AC Power'] }}
        isOpen={true}
      />
    );

    expect(screen.getByText('Telemetry Trends')).toBeDefined();
    expect(screen.getByText(/Explain the selected telemetry trends for AC Power/i)).toBeDefined();
    expect(screen.getByText('Solar Curve vs POA')).toBeDefined();
  });

  it('pre-fills input prompt and automatically opens widget on contextual Ask Copilot action', async () => {
    const handleClearPrompt = vi.fn();
    const prompt = 'Analyze operational performance and active power for Inverter 04.';

    const ContextualHarness = () => {
      const [isOpen, setIsOpen] = useState(false);
      return (
        <FloatingCopilot
          selectedPlant={mockPlant}
          activeTab="devices"
          pageContext={{ route: 'devices', assetName: 'Inverter 04' }}
          isOpen={isOpen}
          onOpenChange={setIsOpen}
          initialPrompt={prompt}
          onClearInitialPrompt={handleClearPrompt}
        />
      );
    };

    render(<ContextualHarness />);

    // Initial prompt should auto-open widget and populate textarea
    await waitFor(() => {
      const textarea = screen.getByPlaceholderText(/Ask Copilot about Surya Solar Farm telemetry/i) as HTMLTextAreaElement;
      expect(textarea.value).toBe(prompt);
      expect(handleClearPrompt).toHaveBeenCalledTimes(1);
    });
  });

  it('streams response in FloatingCopilot with tool trace, citation tags, and stop generation', async () => {
    let abortSignalObserved: AbortSignal | undefined;

    const streamSpy = vi.spyOn(copilotApi, 'streamCopilotChat').mockImplementation(
      async (payload, callbacks, signal) => {
        abortSignalObserved = signal;
        callbacks.onStart?.({ conversation_id: 'conv-float', message_id: 'msg-f1' });
        callbacks.onToolStart?.({
          seq: 1,
          tool: 'query_inverter_power',
          tag: '[T1]',
          arguments: { plant_id: mockPlant.id, inverter_id: 'inv-01' },
        });
        callbacks.onToolEnd?.({
          seq: 1,
          tool: 'query_inverter_power',
          status: 'ok',
          duration_ms: 65,
        });
        callbacks.onDelta?.('Inverter INV-01 is operating at 98.2% efficiency according to [T1].');
        callbacks.onDone?.({
          conversation_id: 'conv-float',
          message_id: 'msg-f1',
          content: 'Inverter INV-01 is operating at 98.2% efficiency according to [T1].',
          tool_trace: [
            {
              seq: 1,
              tool_name: 'query_inverter_power',
              arguments: { plant_id: mockPlant.id, inverter_id: 'inv-01' },
              raw_output: { efficiency: 98.2 },
              status: 'ok',
              duration_ms: 65,
            },
          ],
          citations: [
            {
              index: 1,
              tool_name: 'query_inverter_power',
              tag: '[T1]',
              arguments: { inverter_id: 'inv-01' },
            },
          ],
          charts: [],
          latency_ms: 180,
          model: 'mock-copilot-v1',
        });
      }
    );

    render(
      <FloatingCopilot
        selectedPlant={mockPlant}
        activeTab="devices"
        isOpen={true}
      />
    );

    const textarea = screen.getByPlaceholderText(/Ask Copilot about Surya Solar Farm telemetry/i);
    fireEvent.change(textarea, { target: { value: 'Check Inverter 01 efficiency' } });

    const sendBtn = screen.getByRole('button', { name: /Send message/i });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(streamSpy).toHaveBeenCalledTimes(1);
    });

    // Content with citation pill [T1]
    await waitFor(() => {
      expect(screen.getByText(/Inverter INV-01 is operating at 98.2% efficiency/i)).toBeDefined();
      expect(screen.getByText('[T1]')).toBeDefined();
    });

    // Show Working accordion
    expect(screen.getByText(/Show Working \(1 tool step\)/i)).toBeDefined();
    const showWorkingBtn = screen.getByText(/Show Working \(1 tool step\)/i);
    fireEvent.click(showWorkingBtn);

    await waitFor(() => {
      expect(screen.getByText('query_inverter_power')).toBeDefined();
      expect(screen.getByText('65ms')).toBeDefined();
    });
  });

  it('preserves conversation messages after closing and reopening the floating panel', async () => {
    const TestHarness = () => {
      const [isOpen, setIsOpen] = useState(true);
      return (
        <div>
          <button id="toggle-btn" onClick={() => setIsOpen((prev) => !prev)}>
            Toggle Panel
          </button>
          <FloatingCopilot
            selectedPlant={mockPlant}
            activeTab="dashboard"
            isOpen={isOpen}
            onOpenChange={setIsOpen}
          />
        </div>
      );
    };

    render(<TestHarness />);

    // Load past conversation
    await waitFor(() => {
      expect(screen.getByTitle('Prior Conversations')).toBeDefined();
    });

    // Open history popover
    fireEvent.click(screen.getByTitle('Prior Conversations'));
    await waitFor(() => {
      expect(screen.getByText('Surya PR & Inverter Analysis')).toBeDefined();
    });

    // Select thread
    fireEvent.click(screen.getByText('Surya PR & Inverter Analysis'));

    await waitFor(() => {
      expect(screen.getByText('What is today Performance Ratio?')).toBeDefined();
    });

    // Close panel
    const toggleBtn = screen.getByRole('button', { name: /Toggle Panel/i });
    fireEvent.click(toggleBtn);

    // Panel is now closed
    await waitFor(() => {
      expect(screen.queryByRole('region', { name: /Solar SCADA Copilot Chatbot/i })).toBeNull();
    });

    // Reopen panel
    fireEvent.click(toggleBtn);

    // Message history should still be preserved
    await waitFor(() => {
      expect(screen.getByRole('region', { name: /Solar SCADA Copilot Chatbot/i })).toBeDefined();
      expect(screen.getByText('What is today Performance Ratio?')).toBeDefined();
      expect(screen.getByText('[T1]')).toBeDefined();
    });
  });
});
