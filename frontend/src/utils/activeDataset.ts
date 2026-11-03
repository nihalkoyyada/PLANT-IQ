import { useState, useEffect, useCallback } from 'react';
import { getActiveTelemetrySources, ActiveTelemetrySourceItem } from '../api/files';

const STORAGE_KEY = 'plantiq_active_datasets';

let inFlightSourcesPromise: Promise<any> | null = null;
let cachedSourcesResult: any = null;

export const getStoredActiveDatasets = (): string[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        // Return unique, trimmed strings only
        const unique = Array.from(
          new Set(
            parsed
              .filter((n): n is string => typeof n === 'string' && Boolean(n.trim()))
              .map((n) => n.trim())
          )
        );
        return unique;
      }
    }
  } catch (err) {
    console.warn('Failed to parse stored active datasets:', err);
  }
  return [];
};

export const clearStoredActiveDatasets = () => {
  try {
    cachedSourcesResult = null;
    inFlightSourcesPromise = null;
    localStorage.removeItem(STORAGE_KEY);
    window.dispatchEvent(new CustomEvent('plantiq:datasets-updated', { detail: [] }));
  } catch (err) {
    console.warn('Failed to clear stored active datasets:', err);
  }
};

export const setStoredActiveDatasets = (names: string[]) => {
  try {
    const unique = Array.from(
      new Set(
        names
          .filter((n): n is string => typeof n === 'string' && Boolean(n.trim()))
          .map((n) => n.trim())
      )
    );
    const existing = getStoredActiveDatasets();
    if (
      existing.length === unique.length &&
      existing.every((val, idx) => val === unique[idx])
    ) {
      return; // Identical, prevent redundant storage and event dispatch loops
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(unique));
    window.dispatchEvent(new CustomEvent('plantiq:datasets-updated', { detail: unique }));
  } catch (err) {
    console.warn('Failed to save active datasets to storage:', err);
  }
};

export const useActiveDatasets = () => {
  const [activeDatasets, setActiveState] = useState<string[]>(() => {
    const stored = getStoredActiveDatasets();
    return stored;
  });
  const [activeSources, setActiveSources] = useState<ActiveTelemetrySourceItem[]>([]);
  const [allFilesSummary, setAllFilesSummary] = useState<ActiveTelemetrySourceItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);

  const fetchActiveSources = useCallback(async (forceRefresh: boolean = false) => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('plantiq_token') : null;
    if (!token) {
      return;
    }
    try {
      setLoading(true);
      if (forceRefresh) {
        cachedSourcesResult = null;
        inFlightSourcesPromise = null;
      }
      if (forceRefresh || !cachedSourcesResult) {
        if (!inFlightSourcesPromise) {
          inFlightSourcesPromise = getActiveTelemetrySources().finally(() => {
            inFlightSourcesPromise = null;
          });
        }
        cachedSourcesResult = await inFlightSourcesPromise;
      }
      const res = cachedSourcesResult;
      const sources = res.active_sources || [];
      const allFiles = res.all_files || [];
      setActiveSources(sources);
      setAllFilesSummary(allFiles);

      // Datasets that actually have data in the database (readings > 0 or completed job)
      const validDbFiles = allFiles.filter(
        (f: any) => (f.readings_count && f.readings_count > 0) || f.has_completed_job
      );
      const validDbNames = new Set(
        validDbFiles.map((f: any) => (f.original_name || '').trim().toLowerCase())
      );
      // Also add any names from active_sources that have readings > 0
      sources.forEach((s: any) => {
        if (s.readings_count && s.readings_count > 0) {
          validDbNames.add(s.original_name.trim().toLowerCase());
        }
      });

      const stored = getStoredActiveDatasets();
      let nextActive: string[] = [];

      if (stored.length > 0 && validDbNames.size > 0) {
        // Filter stored datasets: remove duplicates, failed datasets, and 0-reading files
        const filtered = stored.filter((name) => validDbNames.has(name.trim().toLowerCase()));
        if (filtered.length > 0) {
          nextActive = filtered;
        }
      }

      if (nextActive.length === 0) {
        if (res.active_dataset_names && res.active_dataset_names.length > 0) {
          nextActive = res.active_dataset_names;
        } else if (validDbFiles.length > 0) {
          nextActive = [validDbFiles[0].original_name];
        } else {
          // No active data in DB, clear active selection
          nextActive = [];
        }
      }

      // Deduplicate names strictly
      const uniqueNext = Array.from(new Set(nextActive.map((n) => n.trim())));
      setActiveState((prev) => {
        if (
          prev.length === uniqueNext.length &&
          prev.every((val, idx) => val === uniqueNext[idx])
        ) {
          return prev;
        }
        return uniqueNext;
      });

      const existingStored = getStoredActiveDatasets();
      if (
        existingStored.length !== uniqueNext.length ||
        existingStored.some((val, idx) => val !== uniqueNext[idx])
      ) {
        setStoredActiveDatasets(uniqueNext);
      }
    } catch (err) {
      console.warn('Failed to load active telemetry sources from API:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchActiveSources();

    const handleUpdated = (event: Event) => {
      const custom = event as CustomEvent<string[]>;
      const newNames = custom.detail && Array.isArray(custom.detail)
        ? custom.detail
        : getStoredActiveDatasets();

      setActiveState((prev) => {
        if (
          prev.length === newNames.length &&
          prev.every((val, idx) => val === newNames[idx])
        ) {
          return prev;
        }
        return newNames;
      });
    };

    const handleIngested = () => {
      cachedSourcesResult = null;
      inFlightSourcesPromise = null;
      fetchActiveSources(true);
    };

    window.addEventListener('plantiq:datasets-updated', handleUpdated);
    window.addEventListener('plantiq:ingested', handleIngested);

    return () => {
      window.removeEventListener('plantiq:datasets-updated', handleUpdated);
      window.removeEventListener('plantiq:ingested', handleIngested);
    };
  }, [fetchActiveSources]);

  const updateActiveDatasets = (newNames: string[]) => {
    setActiveState(newNames);
    setStoredActiveDatasets(newNames);
  };

  // Dynamic stream classification for ANY uploaded dataset based on signal types and assets
  const activeSourceItems = activeSources.filter((s) => activeDatasets.includes(s.original_name));

  const hasWeather =
    activeSourceItems.length > 0
      ? activeSourceItems.some(
          (s) =>
            s.dataset_type === 'weather' ||
            s.dataset_type === 'hybrid' ||
            s.original_name.toLowerCase().includes('weather') ||
            s.original_name.toLowerCase().includes('sensor') ||
            s.original_name.toLowerCase().includes('met') ||
            s.original_name.toLowerCase().includes('irradian')
        )
      : activeDatasets.some(
          (d) =>
            d.toLowerCase().includes('weather') ||
            d.toLowerCase().includes('sensor') ||
            d.toLowerCase().includes('met') ||
            d.toLowerCase().includes('irradian')
        );

  const hasGeneration =
    activeSourceItems.length > 0
      ? activeSourceItems.some(
          (s) =>
            s.dataset_type === 'generation' ||
            s.dataset_type === 'hybrid' ||
            s.original_name.toLowerCase().includes('generation') ||
            s.original_name.toLowerCase().includes('inverter') ||
            s.original_name.toLowerCase().includes('yield') ||
            s.original_name.toLowerCase().includes('power') ||
            s.original_name.toLowerCase().includes('demo')
        )
      : activeDatasets.some(
          (d) =>
            d.toLowerCase().includes('generation') ||
            d.toLowerCase().includes('inverter') ||
            d.toLowerCase().includes('yield') ||
            d.toLowerCase().includes('power') ||
            d.toLowerCase().includes('demo')
        );

  const isWeatherOnly = activeDatasets.length > 0 && hasWeather && !hasGeneration;
  const isGenOnly = activeDatasets.length > 0 && hasGeneration && !hasWeather;
  const isMerged = activeDatasets.length > 1 && ((hasWeather && hasGeneration) || activeDatasets.length > 1);

  return {
    activeDatasets,
    setActiveDatasets: updateActiveDatasets,
    activeSources,
    activeSourceItems,
    allFilesSummary,
    hasWeather,
    hasGeneration,
    isWeatherOnly,
    isGenOnly,
    isMerged,
    refreshActiveDatasets: fetchActiveSources,
    loading,
  };
};
