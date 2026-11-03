import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { Header } from '../components/layout/Header';
import { GenerationChart } from '../components/dashboard/GenerationChart';
import { PipelineStepper } from '../components/ingestion/PipelineStepper';
import { DeviceTable } from '../components/devices/DeviceTable';
import { DeviceChart } from '../components/devices/DeviceChart';
import { SignalMapper } from '../components/ingestion/SignalMapper';
import * as readingsApi from '../api/readings';
import {
  getStoredActiveDatasets,
  setStoredActiveDatasets,
} from '../utils/activeDataset';

import { AuthProvider } from '../context/AuthContext';

// Polyfill ResizeObserver for jsdom
(globalThis as any).ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

describe('Dataset Selection & Multi-Dataset Feed Display Tests', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('stores and retrieves active datasets from localStorage', () => {
    expect(getStoredActiveDatasets()).toEqual([]);

    setStoredActiveDatasets(['Surya-A-demo.csv']);
    expect(getStoredActiveDatasets()).toEqual(['Surya-A-demo.csv']);

    setStoredActiveDatasets(['Surya-A-demo.csv', 'Plant_1_Generation_Data.csv']);
    expect(getStoredActiveDatasets()).toEqual([
      'Surya-A-demo.csv',
      'Plant_1_Generation_Data.csv',
    ]);
  });

  it('dispatches plantiq:datasets-updated custom event when datasets change', () => {
    const listener = vi.fn();
    window.addEventListener('plantiq:datasets-updated', listener);

    setStoredActiveDatasets(['Plant_1_Generation_Data.csv']);

    expect(listener).toHaveBeenCalled();
    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail).toEqual(['Plant_1_Generation_Data.csv']);

    window.removeEventListener('plantiq:datasets-updated', listener);
  });

  it('displays active dataset badge in top navigation Header', async () => {
    setStoredActiveDatasets(['Surya-A-demo.csv', 'Plant_1_Generation_Data.csv']);

    render(
      <AuthProvider>
        <Header
          onNavigateTab={vi.fn()}
        />
      </AuthProvider>
    );

    const pill = screen.getByTestId('header-active-dataset-pill');
    expect(pill).toBeDefined();
    expect(pill.textContent).toContain('FEED (2):');
    expect(pill.textContent).toContain('Surya-A-demo.csv');
    expect(pill.textContent).toContain('Plant_1_Generation_Data.csv');
  });

  it('displays dataset attribution badges in GenerationChart header for 2 datasets', () => {
    render(
      <GenerationChart
        data={[]}
        activeDatasets={['Surya-A-demo.csv', 'Plant_1_Generation_Data.csv']}
      />
    );

    const feedBadge = screen.getByTestId('chart-active-feed-badge');
    expect(feedBadge).toBeDefined();
    expect(feedBadge.textContent).toContain('FEED (2 DATASETS):');
    expect(feedBadge.textContent).toContain('Surya-A-demo.csv');
    expect(feedBadge.textContent).toContain('Plant_1_Generation_Data.csv');
  });

  it('displays single dataset badge in GenerationChart header when 1 dataset is selected', () => {
    render(
      <GenerationChart
        data={[]}
        activeDatasets={['Surya-A-demo.csv']}
      />
    );

    const feedBadge = screen.getByTestId('chart-active-feed-badge');
    expect(feedBadge).toBeDefined();
    expect(feedBadge.textContent).toContain('FEED:');
    expect(feedBadge.textContent).toContain('Surya-A-demo.csv');
  });

  it('renders PipelineStepper with disabled button and completed state when dataset ingestion is complete', () => {
    const handleProceed = vi.fn();
    render(
      <PipelineStepper
        currentStep={6}
        fileName="Plant_1_Weather_Sensor_Data.csv"
        disabled={true}
        proceedButtonText="✓ Ingestion Completed for Plant_1_Weather_Sensor_Data.csv (Telemetry Live)"
        onProceed={handleProceed}
      />
    );

    const btn = screen.getByRole('button');
    expect(btn).toBeDefined();
    expect(btn.getAttribute('disabled')).not.toBeNull();
    expect(btn.textContent).toContain('Ingestion Completed');
    expect(btn.textContent).toContain('Telemetry Live');

    btn.click();
    expect(handleProceed).not.toHaveBeenCalled();
  });

  it('renders PipelineStepper with enabled button for newly uploaded uningested dataset', () => {
    const handleProceed = vi.fn();
    render(
      <PipelineStepper
        currentStep={3}
        fileName="New_SCADA_Upload.csv"
        disabled={false}
        proceedButtonText="Confirm Signal Mappings & Execute Ingestion"
        onProceed={handleProceed}
      />
    );

    const btn = screen.getByRole('button');
    expect(btn).toBeDefined();
    expect(btn.getAttribute('disabled')).toBeNull();
    expect(btn.textContent).toContain('Confirm Signal Mappings & Execute Ingestion');

    btn.click();
    expect(handleProceed).toHaveBeenCalledTimes(1);
  });

  it('displays dynamic MERGED (4 DATASETS) badge and fleet title in DeviceTable when 4 datasets are merged', () => {
    const mockDevices = [
      { id: 'dev-1', name: 'INV-01', sourceKey: 'INV-01', assetType: 'inverter', status: 'ONLINE' as const, lastReading: '2020-06-17 18:30:00 UTC' },
      { id: 'dev-2', name: 'WS-01', sourceKey: 'WS-01', assetType: 'weather_station', status: 'ONLINE' as const, lastReading: '2020-06-17 18:30:00 UTC' },
    ];
    render(
      <DeviceTable
        devices={mockDevices}
        onSelectDevice={vi.fn()}
        activeDatasets={[
          'Plant_2_Generation_Data.csv',
          'Plant_2_Weather_Sensor_Data.csv',
          'Plant_1_Generation_Data.csv',
          'Surya-A-demo.csv',
        ]}
      />
    );

    expect(screen.getByText('MERGED (4 DATASETS)')).toBeDefined();
    expect(screen.getByText('Merged Fleet (Inverters & Weather Station)')).toBeDefined();
  });

  it('renders DeviceChart with historical telemetry curves for an inverter', async () => {
    vi.spyOn(readingsApi, 'getReadingAggregate').mockResolvedValue([
      {
        channel_id: 'ac-1',
        interval: '15min',
        start: '2020-06-17T12:00:00Z',
        end: '2020-06-17T12:00:00Z',
        reading_count: 1,
        average_value: 1250.5,
        minimum_value: 1200.0,
        maximum_value: 1300.0,
      },
    ]);

    await act(async () => {
      render(
        <DeviceChart
          acChannelId="ac-1"
          dcChannelId="dc-1"
          assetType="inverter"
          latestTimestamp="2020-06-17 18:30:00 UTC"
        />
      );
    });

    expect(screen.getByText('Inverter Telemetry Trend', { exact: false })).toBeDefined();
    expect(screen.getByText('24H')).toBeDefined();
    expect(screen.getByText('7D')).toBeDefined();
  });

  it('renders SignalMapper tabs with VIEW SIGNALS buttons and triggers modal', () => {
    const handleOpenSchemaModal = vi.fn();
    const handleSelectFileToView = vi.fn();

    render(
      <SignalMapper
        fileName="Plant_2_Weather_Sensor_Data.csv"
        rowCount={3259}
        colCount={6}
        mappings={[
          {
            rawColumn: 'DATE_TIME',
            mappedKey: 'timestamp',
            targetType: 'ISO 8601',
            confidence: 100,
          },
          {
            rawColumn: 'IRRADIATION',
            mappedKey: 'irradiance_poa',
            targetType: 'kW/m²',
            confidence: 100,
          },
        ]}
        activeFileId="file-weather-1"
        selectedFiles={[
          {
            id: 'file-weather-1',
            name: 'Plant_2_Weather_Sensor_Data.csv',
            isWeather: true,
          },
          {
            id: 'file-gen-2',
            name: 'Plant_2_Generation_Data.csv',
            isWeather: false,
          },
        ]}
        onSelectFileToView={handleSelectFileToView}
        onOpenSchemaModal={handleOpenSchemaModal}
      />
    );

    // Verify tabs rendered
    expect(screen.getByText('PARSED SCHEMAS FOR SELECTED DATASETS (2):')).toBeDefined();
    expect(screen.getAllByText('Plant_2_Weather_Sensor_Data.csv').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Plant_2_Generation_Data.csv')).toBeDefined();

    // Verify detected signals rendered
    expect(screen.getByText('DATE_TIME')).toBeDefined();
    expect(screen.getByText('IRRADIATION')).toBeDefined();

    // Verify VIEW SIGNALS buttons
    const viewSignalsBtns = screen.getAllByText('VIEW SIGNALS ↗');
    expect(viewSignalsBtns.length).toBe(2);

    // Click on VIEW SIGNALS
    viewSignalsBtns[0].click();
    expect(handleOpenSchemaModal).toHaveBeenCalledWith('file-weather-1');
  });

  it('renders SignalMapper loading indicator when profiling dataset', () => {
    render(
      <SignalMapper
        fileName="Plant_2_Weather_Sensor_Data.csv"
        mappings={[]}
        isLoading={true}
      />
    );

    expect(screen.getByText(/Profiling schema & detected signals for Plant_2_Weather_Sensor_Data.csv/)).toBeDefined();
  });
});

