import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import { App } from '../App';
import * as authApi from '../api/auth';
import * as plantsApi from '../api/plants';

// Polyfill ResizeObserver for jsdom
(globalThis as any).ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Polyfill window.matchMedia for jsdom
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

// Mock APIs
vi.mock('../api/client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}));

vi.mock('../api/plants', () => ({
  getPlants: vi.fn().mockResolvedValue([
    { id: 'plant-1', name: 'Surya Solar Farm - 50MW', capacity_ac_kw: 27500 },
  ]),
  getPublicPlantTelemetry: vi.fn().mockResolvedValue({
    plant_id: 'plant-1',
    plant_name: 'Surya Solar Farm - 50MW',
    capacity_ac_mw: 27.5,
    capacity_dc_mw: 28.28,
    ac_power_mw: 24.77,
    dc_power_mw: 25.38,
    latest_timestamp: '2026-10-16T12:00:00Z',
    data_freshness: 'LIVE',
    status_label: 'SCADA TELEMETRY ACTIVE',
    inverter_count: 22,
    channel_count: 44,
    trend: [],
  }),
}));

vi.mock('../api/readings', () => ({
  getQCStats: vi.fn().mockResolvedValue({ total_readings: 1000, active_channels: 10 }),
  getReadingAggregate: vi.fn().mockResolvedValue([]),
  getLatestReading: vi.fn().mockResolvedValue(null),
  getLatestReadingsBatch: vi.fn().mockResolvedValue({}),
}));

vi.mock('../api/assets', () => ({
  getAssets: vi.fn().mockResolvedValue([]),
}));

vi.mock('../api/files', () => ({
  getActiveTelemetrySources: vi.fn().mockResolvedValue([]),
  getFiles: vi.fn().mockResolvedValue([]),
}));

vi.mock('../api/platform', () => ({
  getPlatformOverview: vi.fn().mockResolvedValue({
    total_organizations: 1,
    active_organizations: 1,
    suspended_organizations: 0,
    total_users: 1,
    total_plants: 1,
    total_devices: 1,
    total_readings: 1000,
    ingestion_health: { pending: 0, processing: 0, completed: 1, failed: 0 },
    system_health: {
      database: { status: 'healthy', latency_ms: 1 },
      redis: { status: 'healthy', latency_ms: 1 },
      api: { status: 'healthy', latency_ms: 1 },
      celery: { status: 'healthy', latency_ms: 1 },
    },
    recent_activity: [],
  }),
  getPlatformOrganizations: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  getPlatformUsers: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  getPlatformPlants: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  getPlatformAuditLogs: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  getPlatformSettings: vi.fn().mockResolvedValue({ maintenance_mode: false }),
}));

vi.mock('../api/admin', () => ({
  getAdminSummary: vi.fn().mockResolvedValue({
    total_organizations: 1,
    total_users: 4,
    total_detectors: 8,
    total_alert_rules: 5,
    total_audit_logs: 100,
  }),
  getAdminUsers: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  getAdminAuditLogs: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}));

vi.mock('../api/anomalies', () => ({
  getAnomalies: vi.fn().mockResolvedValue([]),
  getAnomalySummary: vi.fn().mockResolvedValue({ total_active: 0, critical: 0, warning: 0, info: 0 }),
}));

describe('PlantIQ — Enterprise Authentication & Role-Based Login Flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    window.history.replaceState(null, '', '/');
  });

  it('renders SCADA Operational Login by default with switch to Platform Admin Login', async () => {
    vi.spyOn(authApi, 'getMeApi').mockRejectedValue(new Error('Unauthenticated'));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/SCADA Operational Login/i)).toBeDefined();
    });

    expect(screen.getByPlaceholderText(/e.g. (john@example\.com|admin@surya\.plantiq\.ai)/i)).toBeDefined();
    expect(screen.getByPlaceholderText(/e.g. Enter your password/i)).toBeDefined();
    expect(screen.getByText(/PLATFORM ACCESS DOMAIN/i)).toBeDefined();

    // Verify Platform Admin Login switch button is rendered
    expect(screen.getByText(/Platform Admin Login/i)).toBeDefined();
    expect(screen.getByText(/Platform Super Admin\? Access Admin Portal Login/i)).toBeDefined();
  });

  it('renders dedicated Platform Admin Login page at /admin-portal-login with Super Admin scope', async () => {
    vi.spyOn(authApi, 'getMeApi').mockRejectedValue(new Error('Unauthenticated'));
    window.history.replaceState(null, '', '/admin-portal-login');

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Platform Super Admin Sign In/i)).toBeDefined();
    });

    expect(
      screen.getByText(/Restricted strictly to Platform Super Administrators/i)
    ).toBeDefined();
    expect(screen.getByText(/SCADA Operational Login/i)).toBeDefined();
    expect(screen.getByText(/Root Multi-Tenant Platform Control Plane/i)).toBeDefined();
    expect(screen.getByPlaceholderText(/root_superadmin@plantiq.io/i)).toBeDefined();
  });

  it('redirects super_admin to /platform-admin upon successful login', async () => {
    vi.spyOn(authApi, 'getMeApi').mockResolvedValue({
      id: 'super-1',
      email: 'root_superadmin@plantiq.io',
      full_name: 'Root Super Admin',
      role: 'super_admin',
      is_active: true,
      org_id: 'org-1',
    } as any);

    localStorage.setItem('plantiq_token', 'mock_super_token');
    window.history.replaceState(null, '', '/admin-portal-login');

    render(<App />);

    await waitFor(() => {
      expect(window.location.pathname).toBe('/platform-admin');
    });

    // Super Admin header pill / platform badge rendered
    await waitFor(() => {
      expect(screen.getByText(/ROOT PLATFORM/i)).toBeDefined();
    });
  });

  it('redirects org admin to /dashboard and verifies Admin Panel is NOT in the SCADA sidebar', async () => {
    vi.spyOn(authApi, 'getMeApi').mockResolvedValue({
      id: 'admin-1',
      email: 'admin@surya.plantiq.ai',
      full_name: 'Surya Admin',
      role: 'admin',
      is_active: true,
      org_id: 'org-1',
    } as any);

    localStorage.setItem('plantiq_token', 'mock_admin_token');
    window.history.replaceState(null, '', '/');

    render(<App />);

    await waitFor(() => {
      expect(window.location.pathname).toBe('/dashboard');
    });

    // CRITICAL REQUIREMENT: Admin Panel must NOT be seen in the SCADA operational sidebar!
    expect(screen.queryByText('Admin Panel')).toBeNull();

    // Verify Admin Console quick access is present in top Header
    expect(screen.getByText(/Admin Console/i)).toBeDefined();
  });

  it('renders dedicated Admin Console without SCADA sidebar when visiting /admin', async () => {
    vi.spyOn(authApi, 'getMeApi').mockResolvedValue({
      id: 'admin-1',
      email: 'admin@surya.plantiq.ai',
      full_name: 'Surya Admin',
      role: 'admin',
      is_active: true,
      org_id: 'org-1',
    } as any);

    localStorage.setItem('plantiq_token', 'mock_admin_token');
    window.history.replaceState(null, '', '/admin');

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Organization Administration & Controls/i)).toBeDefined();
    });

    // Back to SCADA button is rendered
    expect(screen.getByText(/Back to SCADA/i)).toBeDefined();

    // SCADA Operational System sidebar is NOT rendered
    expect(screen.queryByText(/SCADA OPERATIONAL SYSTEM/i)).toBeNull();
  });

  it('blocks Organization Admin from entering /platform-admin and redirects to permitted view', async () => {
    vi.spyOn(authApi, 'getMeApi').mockResolvedValue({
      id: 'admin-1',
      email: 'admin@surya.plantiq.ai',
      full_name: 'Surya Admin',
      role: 'admin',
      is_active: true,
      org_id: 'org-1',
    } as any);

    localStorage.setItem('plantiq_token', 'mock_admin_token');
    window.history.replaceState(null, '', '/platform-admin');

    render(<App />);

    // Route guard intercepts and prevents super admin console access
    await waitFor(() => {
      expect(window.location.pathname).toBe('/admin');
    });

    expect(screen.queryByText(/ROOT PLATFORM/i)).toBeNull();
  });

  it('redirects engineer to /dashboard and prevents direct URL access to /platform-admin and /admin', async () => {
    vi.spyOn(authApi, 'getMeApi').mockResolvedValue({
      id: 'eng-1',
      email: 'engineer@surya.plantiq.ai',
      full_name: 'Surya Engineer',
      role: 'engineer',
      is_active: true,
      org_id: 'org-1',
    } as any);

    localStorage.setItem('plantiq_token', 'mock_eng_token');
    // Engineer maliciously enters /platform-admin in the browser address bar
    window.history.replaceState(null, '', '/platform-admin');

    render(<App />);

    // Route guard intercepts and redirects to /dashboard
    await waitFor(() => {
      expect(window.location.pathname).toBe('/dashboard');
    });

    // Admin Panel and Platform Admin are NOT rendered in sidebar
    expect(screen.queryByText(/Platform Admin/i)).toBeNull();
    expect(screen.queryByText(/Admin Panel/i)).toBeNull();
  });

  it('redirects viewer to /dashboard and prevents direct URL access to /upload or /admin', async () => {
    vi.spyOn(authApi, 'getMeApi').mockResolvedValue({
      id: 'view-1',
      email: 'viewer@surya.plantiq.ai',
      full_name: 'Surya Viewer',
      role: 'viewer',
      is_active: true,
      org_id: 'org-1',
    } as any);

    localStorage.setItem('plantiq_token', 'mock_viewer_token');
    // Viewer tries to directly enter /upload
    window.history.replaceState(null, '', '/upload');

    render(<App />);

    // Route guard intercepts and redirects to /dashboard
    await waitFor(() => {
      expect(window.location.pathname).toBe('/dashboard');
    });

    expect(screen.queryByText(/Upload & Mapping/i)).toBeNull();
  });

  it('removes public role selection from registration page and enforces invitation policy', async () => {
    vi.spyOn(authApi, 'getMeApi').mockRejectedValue(new Error('Unauthenticated'));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Sign In to SCADA/i)).toBeDefined();
    });

    // Click Register button on Common Login Page
    const registerBtn = screen.getByRole('button', { name: /Register/i });
    fireEvent.click(registerBtn);

    await waitFor(() => {
      expect(screen.getByText(/Create Operator Account/i)).toBeDefined();
    });

    // Verify clear provisioning notice and invitation requirements
    expect(screen.getByText(/Admin accounts provisioned by Platform Admin/i)).toBeDefined();
    expect(screen.getByText(/Enterprise Role-Based Access Policy/i)).toBeDefined();
    expect(
      screen.getByText(/Organization Admin or Super Admin access\? Contact platform administration/i)
    ).toBeDefined();
    expect(screen.getByText(/HAVE AN INVITATION TOKEN\?/i)).toBeDefined();

    // Verify public role selection buttons/cards for Super Admin & Admin are NOT clickable options
    expect(screen.queryByRole('button', { name: /Super Admin/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Organization Admin/i })).toBeNull();
  });
});
