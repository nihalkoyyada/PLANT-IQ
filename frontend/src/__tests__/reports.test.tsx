import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { ReportsPage } from '../pages/ReportsPage';
import * as reportsApi from '../api/reports';
import * as plantsApi from '../api/plants';
import { Plant, Report } from '../types';

// Polyfill URL methods for jsdom
if (!window.URL.createObjectURL) {
  window.URL.createObjectURL = vi.fn().mockReturnValue('blob:http://localhost/mock-blob-url');
}
if (!window.URL.revokeObjectURL) {
  window.URL.revokeObjectURL = vi.fn();
}

// Mock auth context
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u-1', email: 'engineer@plantiq.io', role: 'engineer', org_id: 'org-1' },
    isAuthenticated: true,
  }),
}));

// Mock plants API
vi.mock('../api/plants', () => ({
  getPlants: vi.fn(),
}));

// Mock reports API
vi.mock('../api/reports', () => ({
  getReports: vi.fn(),
  generateReport: vi.fn(),
  downloadReport: vi.fn(),
  getReport: vi.fn(),
}));

const mockPlants = [
  {
    id: 'plant-alpha',
    org_id: 'org-1',
    name: 'Surya-A Solar Plant',
    plant_type: 'solar',
    capacity_ac_kw: 10000,
    capacity_dc_kwp: 12000,
    timezone: 'Asia/Kolkata',
    tariff_inr_per_kwh: 3.5,
  },
  {
    id: 'plant-beta',
    org_id: 'org-1',
    name: 'Wind Farm Beta',
    plant_type: 'wind',
    capacity_ac_kw: 25000,
    capacity_dc_kwp: 25000,
  },
] as unknown as Plant[];

const mockReports: Report[] = [
  {
    id: 'rep-001',
    org_id: 'org-1',
    plant_id: 'plant-alpha',
    plant_name: 'Surya-A Solar Plant',
    report_type: 'daily',
    title: 'Surya-A Daily Performance Report - 2020-06-17',
    start_date: '2020-06-17',
    end_date: '2020-06-17',
    status: 'completed',
    file_size_bytes: 145200,
    metrics_summary: {
      gross_generation_mwh: 45.2,
      performance_ratio: 78.4,
      cuf_percent: 18.8,
      availability_percent: 99.2,
      revenue_generated_inr: 158201.75,
      anomalies_count: 2,
      revenue_loss_inr: 498.75,
      has_telemetry_gap: false,
    },
    created_at: '2026-11-09T08:00:00Z',
    completed_at: '2026-11-09T08:00:05Z',
  },
  {
    id: 'rep-002',
    org_id: 'org-1',
    plant_id: 'plant-alpha',
    plant_name: 'Surya-A Solar Plant',
    report_type: 'weekly',
    title: 'Surya-A Weekly Performance Report - W25',
    start_date: '2020-06-10',
    end_date: '2020-06-17',
    status: 'processing',
    metrics_summary: null,
    created_at: '2026-11-09T08:30:00Z',
  },
];

describe('S6-FS-01 Reports Module Frontend Tests (ReportsPage)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(plantsApi.getPlants).mockResolvedValue(mockPlants);
    vi.mocked(reportsApi.getReports).mockResolvedValue({
      items: mockReports,
      total: 2,
      skip: 0,
      limit: 20,
    });
  });

  it('renders Reports page header, filters, and reports table', async () => {
    render(<ReportsPage />);

    expect(screen.getByText('Executive & Operational Reports')).toBeDefined();
    expect(screen.getByRole('button', { name: /generate report/i })).toBeDefined();

    await waitFor(() => {
      expect(screen.getByText('Surya-A Daily Performance Report - 2020-06-17')).toBeDefined();
      expect(screen.getByText('Surya-A Weekly Performance Report - W25')).toBeDefined();
    });

    // Check table headers
    expect(screen.getByText('Report Details')).toBeDefined();
    expect(screen.getByText('Plant & Period')).toBeDefined();
    expect(screen.getByText('Status')).toBeDefined();
    expect(screen.getByText('Key Metrics')).toBeDefined();

    // Check report statuses in table
    expect(screen.getByText('Completed')).toBeDefined();
    expect(screen.getByText('Compiling PDF')).toBeDefined();
  });

  it('opens Generate Report modal and validates Daily and Weekly date logic', async () => {
    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generate report/i })).toBeDefined();
    });

    fireEvent.click(screen.getByRole('button', { name: /generate report/i }));

    // Modal should be visible
    expect(screen.getByText('Generate SCADA Report')).toBeDefined();

    // Select Weekly report type
    const weeklyBtn = screen.getByText('Weekly Performance');
    fireEvent.click(weeklyBtn);

    // Verify date label changes for weekly range
    expect(screen.getByText('Start Date *')).toBeDefined();
    expect(screen.getByText('End Date')).toBeDefined();

    // Cancel modal
    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    fireEvent.click(cancelBtn);
    expect(screen.queryByText('Generate SCADA Report')).toBeNull();
  });

  it('submits a new report request and calls generateReport API with proper payload', async () => {
    vi.mocked(reportsApi.generateReport).mockResolvedValue({
      id: 'rep-003',
      org_id: 'org-1',
      plant_id: 'plant-alpha',
      plant_name: 'Surya-A Solar Plant',
      report_type: 'daily',
      title: 'Midday Diagnostic Report',
      start_date: '2020-06-17',
      end_date: '2020-06-17',
      status: 'pending',
      created_at: new Date().toISOString(),
    });

    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generate report/i })).toBeDefined();
    });

    fireEvent.click(screen.getByRole('button', { name: /generate report/i }));

    // Type a custom title
    const titleInput = screen.getByPlaceholderText(/e\.g\. Mid-Summer Degradation/i);
    fireEvent.change(titleInput, { target: { value: 'Midday Diagnostic Report' } });

    // Click submit
    const submitBtn = screen.getByRole('button', { name: /generate pdf report/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(reportsApi.generateReport).toHaveBeenCalledWith(
        expect.objectContaining({
          plant_id: 'plant-alpha',
          report_type: 'daily',
          title: 'Midday Diagnostic Report',
        })
      );
    });
  });

  it('calls downloadReport when Download PDF action is clicked for a completed report', async () => {
    vi.mocked(reportsApi.downloadReport).mockResolvedValue(undefined);

    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByText('Surya-A Daily Performance Report - 2020-06-17')).toBeDefined();
    });

    const downloadButtons = screen.getAllByRole('button', { name: /download pdf/i });
    expect(downloadButtons.length).toBeGreaterThan(0);

    fireEvent.click(downloadButtons[0]);

    await waitFor(() => {
      expect(reportsApi.downloadReport).toHaveBeenCalledWith(
        'rep-001',
        'surya-a_daily_performance_report_-_2020-06-17.pdf'
      );
    });
  });

  it('displays empty state when no reports exist', async () => {
    vi.mocked(reportsApi.getReports).mockResolvedValue({
      items: [],
      total: 0,
      skip: 0,
      limit: 20,
    });

    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByText('No reports generated yet')).toBeDefined();
      expect(screen.getByText(/Compile your first formal daily operational/i)).toBeDefined();
    });
  });

  it('opens report details modal when clicking View on a completed report', async () => {
    render(<ReportsPage />);

    await waitFor(() => {
      expect(screen.getByText('Surya-A Daily Performance Report - 2020-06-17')).toBeDefined();
    });

    const viewButtons = screen.getAllByRole('button', { name: /view/i });
    expect(viewButtons.length).toBeGreaterThan(0);

    fireEvent.click(viewButtons[0]);

    await waitFor(() => {
      expect(screen.getByText('Authoritative Telemetry Metrics')).toBeDefined();
      expect(screen.getAllByText(/45\.2 MWh/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/78\.4%/i).length).toBeGreaterThan(0);
    });
  });
});
