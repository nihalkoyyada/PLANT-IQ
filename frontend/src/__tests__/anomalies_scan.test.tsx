import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AnomaliesPage } from '../pages/AnomaliesPage';

// Polyfill ResizeObserver for jsdom
(globalThis as any).ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Mock auth context
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'test@plantiq.io', role: 'engineer' },
    isAuthenticated: true,
  }),
}));

vi.mock('../api/plants', () => ({
  getPlants: vi.fn().mockResolvedValue([
    { id: 'plant-alpha', name: 'Surya-A Solar Plant', capacity_ac_kw: 27500 },
  ]),
}));

vi.mock('../api/detectors', () => ({
  getDetectors: vi.fn().mockResolvedValue([]),
}));

vi.mock('../api/alertRules', () => ({
  getAlertRules: vi.fn().mockResolvedValue([]),
  getAlertDeliveries: vi.fn().mockResolvedValue([]),
}));

const mockTriggerPlantAnomalyScan = vi.fn();

vi.mock('../api/anomalies', () => ({
  getAnomalies: vi.fn().mockResolvedValue([]),
  getAnomalySummary: vi.fn().mockResolvedValue({
    total_anomalies: 0,
    open_count: 0,
    acknowledged_count: 0,
    resolved_count: 0,
    critical_count: 0,
    high_count: 0,
    total_estimated_loss_kwh: 0,
    total_estimated_financial_loss_inr: 0,
  }),
  getAnomalyEvidence: vi.fn(),
  triageAnomaly: vi.fn(),
  bulkTriageAnomalies: vi.fn(),
  triggerPlantAnomalyScan: (...args: any[]) => mockTriggerPlantAnomalyScan(...args),
}));

describe('AnomaliesPage Scan Notification Regression Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('displays accurate scan notification distinguishing raw candidate detections from reconciled anomalies', async () => {
    mockTriggerPlantAnomalyScan.mockResolvedValueOnce({
      status: 'success',
      assets_scanned: 22,
      anomalies_detected: 250,
      anomalies_created: 0,
      anomalies_merged: 250,
    });

    render(<AnomaliesPage />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Run Detector Scan/i })).toBeDefined();
    });

    const runScanBtn = screen.getByRole('button', { name: /Run Detector Scan/i });
    fireEvent.click(runScanBtn);

    await waitFor(() => {
      expect(
        screen.getByText(
          'Scanned 22 assets, evaluated 250 candidate detections (0 new anomalies created, 250 reconciled with existing anomalies).'
        )
      ).toBeDefined();
    });

    expect(mockTriggerPlantAnomalyScan).toHaveBeenCalledWith('plant-alpha', 24);
  });

  it('uses nullish coalescing (??) when response fields are 0, null, or undefined', async () => {
    mockTriggerPlantAnomalyScan.mockResolvedValueOnce({
      status: 'success',
      assets_scanned: 0,
      anomalies_detected: null,
      anomalies_created: undefined,
      anomalies_merged: 0,
    });

    render(<AnomaliesPage />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Run Detector Scan/i })).toBeDefined();
    });

    const runScanBtn = screen.getByRole('button', { name: /Run Detector Scan/i });
    fireEvent.click(runScanBtn);

    await waitFor(() => {
      expect(
        screen.getByText(
          'Scanned 0 assets, evaluated 0 candidate detections (0 new anomalies created, 0 reconciled with existing anomalies).'
        )
      ).toBeDefined();
    });
  });
});
