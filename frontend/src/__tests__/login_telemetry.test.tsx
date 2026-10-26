import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import React from 'react';
import { LoginPage } from '../pages/LoginPage';
import * as plantsApi from '../api/plants';

// Mock AuthContext
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    login: vi.fn(),
    isAuthenticated: false,
    user: null,
  }),
}));

describe('PlantIQ Login Page — Real-Time Live Plant Generation Widget', () => {
  const mockLiveTelemetry: plantsApi.PublicPlantTelemetryResponse = {
    plant_id: 'd253760d-d8ad-4a18-b655-fc22a5222d59',
    plant_name: 'Surya Solar Farm - 50MW',
    capacity_ac_mw: 27.5,
    capacity_dc_mw: 28.28,
    ac_power_mw: 24.77,
    dc_power_mw: 25.38,
    latest_timestamp: '2026-10-16T12:00:00Z',
    data_freshness: 'LIVE',
    status_label: 'SCADA TELEMETRY ACTIVE',
    stale_days: null,
    freshness_seconds: 120,
    inverter_count: 22,
    channel_count: 44,
    peak_ac_power_mw: 29.05,
    trend: [
      { timestamp: '2026-10-16T06:00:00Z', time: '06:00', ac_power_mw: 1.2, dc_power_mw: 1.3 },
      { timestamp: '2026-10-16T09:00:00Z', time: '09:00', ac_power_mw: 15.4, dc_power_mw: 16.0 },
      { timestamp: '2026-10-16T12:00:00Z', time: '12:00', ac_power_mw: 24.77, dc_power_mw: 25.38 },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders dynamic plant telemetry from backend API and removes hardcoded values', async () => {
    vi.spyOn(plantsApi, 'getPublicPlantTelemetry').mockResolvedValue(mockLiveTelemetry);

    render(<LoginPage />);

    await waitFor(() => {
      expect(screen.getByText(/SURYA SOLAR FARM - 50MW \(MW\)/i)).toBeDefined();
    });

    // Check dynamic power readings
    expect(screen.getByText('24.77 MW')).toBeDefined();
    expect(screen.getByText('25.38 MW')).toBeDefined();

    // Verify static hardcoded mockup values (24.02 MW, 53.27 MW) do NOT exist
    expect(screen.queryByText('24.02 MW')).toBeNull();
    expect(screen.queryByText('53.27 MW')).toBeNull();

    // Check status badge and label
    const badge = document.getElementById('login-telemetry-badge');
    expect(badge).toBeDefined();
    expect(badge?.textContent).toContain('LIVE');
    expect(screen.getByText('SCADA TELEMETRY ACTIVE')).toBeDefined();

    // Check actual timestamp formatting (16 OCT 12:00 UTC), not browser current time
    const lastUpdate = document.getElementById('login-last-update-time');
    expect(lastUpdate?.textContent).toContain('16 OCT 12:00 UTC');
  });

  it('handles STALE data status accurately when telemetry is older than threshold', async () => {
    const mockStaleTelemetry: plantsApi.PublicPlantTelemetryResponse = {
      ...mockLiveTelemetry,
      data_freshness: 'STALE',
      status_label: 'TELEMETRY STALE (7d ago)',
      latest_timestamp: '2020-06-17T23:45:00Z',
      ac_power_mw: 0.0,
      dc_power_mw: 0.0,
    };
    vi.spyOn(plantsApi, 'getPublicPlantTelemetry').mockResolvedValue(mockStaleTelemetry);

    render(<LoginPage />);

    await waitFor(() => {
      const badge = document.getElementById('login-telemetry-badge');
      expect(badge?.textContent).toContain('STALE');
    });

    expect(screen.getByText('TELEMETRY STALE (7d ago)')).toBeDefined();
    expect(screen.getAllByText('0.00 MW').length).toBe(2);
    const lastUpdate = document.getElementById('login-last-update-time');
    expect(lastUpdate?.textContent).toContain('17 JUN 23:45 UTC');
  });

  it('handles OFFLINE or error state gracefully without breaking the login form', async () => {
    vi.spyOn(plantsApi, 'getPublicPlantTelemetry').mockRejectedValue(new Error('Network error'));

    render(<LoginPage />);

    await waitFor(() => {
      const badge = document.getElementById('login-telemetry-badge');
      expect(badge?.textContent).toContain('OFFLINE');
    });

    // Login form remains functional and interactive
    const emailInput = screen.getByPlaceholderText('e.g. john@example.com') as HTMLInputElement;
    expect(emailInput).toBeDefined();
    expect(screen.getByRole('button', { name: /Sign In to PlantIQ/i })).toBeDefined();
  });

  it('automatically sets up 15-second refresh interval and cleans up on unmount', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval');
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval');
    const spy = vi.spyOn(plantsApi, 'getPublicPlantTelemetry').mockResolvedValue(mockLiveTelemetry);

    const { unmount } = render(<LoginPage />);

    // Initial fetch on mount
    expect(spy).toHaveBeenCalledTimes(1);

    // Wait for initial fetch to complete and release isFetchingRef
    await waitFor(() => {
      expect(screen.getByText('24.77 MW')).toBeDefined();
    });

    // Verify 15-second interval was registered
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 15000);

    // Trigger interval callback directly
    const intervalCallback = setIntervalSpy.mock.calls[0][0] as () => void;
    await act(async () => {
      intervalCallback();
    });

    expect(spy).toHaveBeenCalledTimes(2);

    // Unmount and verify interval was cleared
    unmount();
    expect(clearIntervalSpy).toHaveBeenCalled();
  });
});
