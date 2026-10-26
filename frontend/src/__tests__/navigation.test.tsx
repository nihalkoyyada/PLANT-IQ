import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AnomalyBanner } from '../components/dashboard/AnomalyBanner';
import { Sidebar, NavTab } from '../components/layout/Sidebar';
import { MobileNav } from '../components/layout/MobileNav';
import { DashboardPage } from '../pages/DashboardPage';
import { Header } from '../components/layout/Header';

// Polyfill ResizeObserver for jsdom
(globalThis as any).ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Polyfill URL.createObjectURL and URL.revokeObjectURL for jsdom
if (!window.URL.createObjectURL) {
  window.URL.createObjectURL = vi.fn().mockReturnValue('blob:http://localhost/mock-blob-url');
}
if (!window.URL.revokeObjectURL) {
  window.URL.revokeObjectURL = vi.fn();
}

// Mock auth context for Sidebar
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'test@plantiq.io', role: 'engineer' },
    isAuthenticated: true,
  }),
}));

// Mock APIs used by Sidebar and DashboardPage
vi.mock('../api/readings', () => ({
  getQCStats: vi.fn().mockResolvedValue({ total_readings: 1000, active_channels: 10 }),
  getReadingAggregate: vi.fn().mockResolvedValue([{ start: '2026-06-17T12:00:00Z', average_value: 500 }]),
  getLatestReading: vi.fn().mockResolvedValue({ ts: '2026-06-17T12:00:00Z', value: 500 }),
}));

vi.mock('../api/plants', () => ({
  getPlants: vi.fn().mockResolvedValue([{ id: 'plant-1', name: 'Surya Solar Plant', capacity_ac_kw: 2000 }]),
}));

vi.mock('../api/assets', () => ({
  getAssets: vi.fn().mockResolvedValue([
    { id: 'asset-1', plant_id: 'plant-1', name: 'Inverter 01', asset_type: 'inverter', rated_kw: 1000 },
  ]),
}));

vi.mock('../api/channels', () => ({
  getChannels: vi.fn().mockResolvedValue([
    { id: 'ch-1', asset_id: 'asset-1', canonical_key: 'power_ac', source_name: 'AC_POWER' },
  ]),
}));

vi.mock('../api/events', () => ({
  getEvents: vi.fn().mockResolvedValue([]),
}));

vi.mock('../api/detectors', () => ({
  getDetectors: vi.fn().mockResolvedValue([]),
}));

vi.mock('../api/alertRules', () => ({
  getAlertRules: vi.fn().mockResolvedValue([]),
  getAlertDeliveries: vi.fn().mockResolvedValue([]),
}));

vi.mock('../api/anomalies', () => ({
  getAnomalies: vi.fn().mockResolvedValue([
    {
      id: 'anom-low',
      severity: 'low',
      status: 'open',
      summary: 'Low severity warning',
      asset_name: 'Inverter Low Asset',
      plant_name: 'Surya Solar Plant',
      start_time: '2026-06-17T10:00:00Z',
    },
    {
      id: 'anom-resolved-crit',
      severity: 'critical',
      status: 'resolved',
      summary: 'Resolved old critical anomaly',
      asset_name: 'Inverter Resolved Asset',
      plant_name: 'Surya Solar Plant',
      start_time: '2026-06-17T11:00:00Z',
    },
    {
      id: 'anom-crit-unresolved',
      severity: 'critical',
      status: 'open',
      summary: 'Active critical trip',
      asset_name: 'Inverter Critical Active Asset',
      plant_name: 'Surya Solar Plant',
      start_time: '2026-06-17T09:00:00Z',
    },
  ]),
  getAnomalySummary: vi.fn().mockResolvedValue({
    total_anomalies: 3,
    open_count: 2,
    acknowledged_count: 0,
    resolved_count: 1,
    critical_count: 2,
    high_count: 0,
    total_estimated_loss_kwh: 500,
    total_estimated_financial_loss_inr: 1750,
  }),
  getAnomalyEvidence: vi.fn(),
  triageAnomaly: vi.fn(),
  bulkTriageAnomalies: vi.fn(),
  triggerPlantAnomalyScan: vi.fn(),
}));

import { AnomaliesPage } from '../pages/AnomaliesPage';

describe('Sprint 4 Dashboard Triage Navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders AnomalyBanner with Triage button and fires onTriage callback', async () => {
    const handleTriage = vi.fn();
    render(<AnomalyBanner onTriage={handleTriage} />);

    await waitFor(() => {
      expect(screen.getByText(/Active Telemetry Anomalies/i)).toBeDefined();
    });
    const triageBtn = screen.getByRole('button', { name: /Triage/i });
    expect(triageBtn).toBeDefined();

    fireEvent.click(triageBtn);
    expect(handleTriage).toHaveBeenCalledTimes(1);
  });

  it('renders dynamic counts and severity badges in AnomalyBanner based on live AnomalySummary', () => {
    const mockSummary = {
      total_anomalies: 22,
      open_count: 21,
      critical_count: 3,
      high_count: 18,
      medium_count: 0,
      low_count: 0,
      total_estimated_loss_kwh: 2450.5,
      total_estimated_financial_loss_inr: 8576.75,
    };
    render(<AnomalyBanner summary={mockSummary} onTriage={vi.fn()} />);

    expect(screen.getByText('21 Active Telemetry Anomalies')).toBeDefined();
    expect(screen.getByText(/3 critical, 18 high priority unresolved/i)).toBeDefined();
    expect(screen.getByText('3 CRIT')).toBeDefined();
    expect(screen.getByText('18 H')).toBeDefined();
    expect(screen.queryByText('7 Active Telemetry Anomalies')).toBeNull();
  });

  it('navigates to "anomalies" (Anomaly Inbox) and NOT "quality" (Data Quality & QC) when Triage is clicked on Dashboard', async () => {
    const handleNavigateTab = vi.fn();
    render(<DashboardPage onNavigateTab={handleNavigateTab} />);

    // Wait for Dashboard assets/channels to load so hasTelemetry is true
    await waitFor(() => {
      expect(screen.getByText(/Active Telemetry Anomalies/i)).toBeDefined();
    });

    const triageButton = screen.getByRole('button', { name: /Triage/i });
    expect(triageButton).toBeDefined();

    fireEvent.click(triageButton);

    // Verify it navigates to 'anomalies'
    expect(handleNavigateTab).toHaveBeenCalledWith('anomalies');
    // Crucially verify it did NOT navigate to 'quality'
    expect(handleNavigateTab).not.toHaveBeenCalledWith('quality');
  });

  it('ensures Sidebar Anomaly Inbox and Dashboard Triage navigate to the identical route ("anomalies")', async () => {
    const handleSelectTab = vi.fn();
    render(<Sidebar activeTab="dashboard" onSelectTab={handleSelectTab} />);

    await waitFor(() => {
      expect(screen.getByText(/1,000 readings/i)).toBeDefined();
    });

    // Sidebar has "Anomaly Inbox"
    const anomalyInboxBtn = screen.getByRole('button', { name: /Anomaly Inbox/i });
    expect(anomalyInboxBtn).toBeDefined();

    fireEvent.click(anomalyInboxBtn);
    expect(handleSelectTab).toHaveBeenCalledWith('anomalies');

    // Sidebar also preserves "Data Quality & QC" as a distinct route ('quality')
    const qcBtn = screen.getByRole('button', { name: /Data Quality & QC/i });
    expect(qcBtn).toBeDefined();

    fireEvent.click(qcBtn);
    expect(handleSelectTab).toHaveBeenCalledWith('quality');
  });

  it('ensures MobileNav also navigates to "anomalies"', () => {
    const handleSelectTab = vi.fn();
    render(<MobileNav activeTab="dashboard" onSelectTab={handleSelectTab} />);

    const anomaliesNavBtn = screen.getByRole('button', { name: /Anomalies/i });
    expect(anomaliesNavBtn).toBeDefined();

    fireEvent.click(anomaliesNavBtn);
    expect(handleSelectTab).toHaveBeenCalledWith('anomalies');
  });

  it('prioritizes unresolved Critical/High anomalies at the top of the Anomaly Inbox', async () => {
    render(<AnomaliesPage />);

    await waitFor(() => {
      expect(screen.getByText('Inverter Critical Active Asset')).toBeDefined();
    });

    const rows = screen.getAllByRole('row');
    // Row 0 is the table header. Row 1 must be the unresolved critical anomaly
    expect(rows[1].textContent).toContain('Inverter Critical Active Asset');
    expect(rows[1].textContent).toContain('critical');
    expect(rows[1].textContent).toContain('Open');
  });

  it('verifies Solar Copilot page is removed from Sidebar and MobileNav so Copilot is exclusively the floating widget', () => {
    const handleSelectTab = vi.fn();
    render(<Sidebar activeTab="dashboard" onSelectTab={handleSelectTab} />);

    // Solar Copilot should NOT be in the sidebar navigation items
    expect(screen.queryByRole('button', { name: /Solar Copilot/i })).toBeNull();

    // Solar Copilot should NOT be in MobileNav
    const { unmount } = render(<MobileNav activeTab="dashboard" onSelectTab={handleSelectTab} />);
    expect(screen.queryByRole('button', { name: /^Copilot$/i })).toBeNull();
    unmount();
  });

  it('renders interactive Header Search bar and navigates to matching asset or page on selection', async () => {
    const handleNavigateTab = vi.fn();
    const mockPlants = [{ id: 'plant-1', name: 'Surya Solar Farm', capacity_ac_kw: 50000 }] as unknown as any[];

    render(
      <Header
        plants={mockPlants}
        selectedPlant={mockPlants[0]}
        onSelectPlant={vi.fn()}
        onNavigateTab={handleNavigateTab}
      />
    );

    const searchInput = screen.getByPlaceholderText(/Search assets, telemetry.../i) as HTMLInputElement;
    expect(searchInput).toBeDefined();

    // Focusing without typing opens Quick Navigation shortcuts
    fireEvent.focus(searchInput);
    await waitFor(() => {
      expect(screen.getByText(/Quick Navigation/i)).toBeDefined();
    });

    // Type query to filter
    fireEvent.change(searchInput, { target: { value: 'Inverter' } });

    await waitFor(() => {
      expect(screen.getByText(/Matching Results/i)).toBeDefined();
    });

    // Select filtered asset result
    const assetResult = screen.getByText('Inverter 01');
    expect(assetResult).toBeDefined();

    fireEvent.click(assetResult);

    // Navigates to devices tab
    expect(handleNavigateTab).toHaveBeenCalledWith('devices');
    expect(searchInput.value).toBe('');
  });

  it('renders interactive Header Notifications popover with badge, mark all read, and click navigation', async () => {
    const handleNavigateTab = vi.fn();
    const mockPlants = [{ id: 'plant-1', name: 'Surya Solar Farm', capacity_ac_kw: 50000 }] as unknown as any[];

    render(
      <Header
        plants={mockPlants}
        selectedPlant={mockPlants[0]}
        onSelectPlant={vi.fn()}
        onNavigateTab={handleNavigateTab}
      />
    );

    const notifBell = screen.getByRole('button', { name: /Operational Notifications/i });
    expect(notifBell).toBeDefined();

    // Click to open notifications popover
    fireEvent.click(notifBell);

    await waitFor(() => {
      expect(screen.getByText('Notifications')).toBeDefined();
      expect(screen.getByText(/Active critical trip|Inverter Trip Outlier/i)).toBeDefined();
    });

    // Click a notification to navigate to Anomaly Inbox
    const notifItem = screen.getByText(/Active critical trip|Inverter Trip Outlier/i);
    fireEvent.click(notifItem);

    expect(handleNavigateTab).toHaveBeenCalledWith('anomalies');
  });

  it('supports exporting SCADA report CSV on Dashboard download button and verifies Ask Copilot is removed', async () => {
    render(<DashboardPage onNavigateTab={vi.fn()} />);

    // Wait for Dashboard to finish loading
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Export SCADA Report/i })).toBeDefined();
    });

    const exportBtn = screen.getByRole('button', { name: /Export SCADA Report/i });
    expect(exportBtn).toBeDefined();

    // Ask Copilot button should NOT exist in the dashboard toolbar
    expect(screen.queryByRole('button', { name: /Ask Copilot/i })).toBeNull();

    // Click download button
    fireEvent.click(exportBtn);

    // Verify visual feedback on export
    await waitFor(() => {
      expect(screen.getByLabelText(/Export SCADA Report/i).getAttribute('title')).toBe('SCADA Report Downloaded!');
    });
  });
});
