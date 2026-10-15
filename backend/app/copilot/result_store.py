"""Large Array & Timeseries Reference Management Store (§10.3, Task S5-AI-01).

Implements:
1. ResultRefStore: Thread-safe, bounded, TTL-based cache storing heavy timeseries data arrays
   and returning compact result references (e.g. `ref_ts_8f93a2b1`) to prevent overloading
   the LLM context window with thousands of raw coordinates.
2. ChartStore: Cache for validated ECharts specifications rendered by the Copilot tool layer,
   allowing the frontend to fetch and render full-fidelity charts via inline chart IDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4


@dataclass
class StoredResult:
    """Cached dataset payload with metadata and TTL expiration."""

    ref_id: str
    data: Any
    metadata: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    ttl_seconds: int = 3600  # Default 1 hour TTL

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class ResultRefStore:
    """Thread-safe in-memory result reference store with LRU pruning and TTL expiration."""

    def __init__(self, max_entries: int = 1000, default_ttl_seconds: int = 3600) -> None:
        self.max_entries = max_entries
        self.default_ttl_seconds = default_ttl_seconds
        self._store: Dict[str, StoredResult] = {}
        self._lock = threading.Lock()

    def put(
        self,
        data: Any,
        prefix: str = "ref_ts",
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """Store an arbitrary data payload and return a compact reference identifier."""
        ref_id = f"{prefix}_{uuid4().hex[:10]}"
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        stored = StoredResult(
            ref_id=ref_id,
            data=data,
            metadata=metadata or {},
            created_at=time.time(),
            ttl_seconds=ttl,
        )

        with self._lock:
            # Prune expired entries if capacity reached
            if len(self._store) >= self.max_entries:
                self._prune_expired_locked()
                # If still at capacity, evict oldest entry
                if len(self._store) >= self.max_entries:
                    oldest_key = min(self._store.keys(), key=lambda k: self._store[k].created_at)
                    self._store.pop(oldest_key, None)

            self._store[ref_id] = stored

        return ref_id

    def get(self, ref_id: str) -> Optional[Any]:
        """Retrieve cached data payload by its reference ID if not expired."""
        with self._lock:
            item = self._store.get(ref_id)
            if not item:
                return None
            if item.is_expired:
                self._store.pop(ref_id, None)
                return None
            return item.data

    def get_metadata(self, ref_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored metadata for a reference ID."""
        with self._lock:
            item = self._store.get(ref_id)
            if not item or item.is_expired:
                return None
            return item.metadata

    def has(self, ref_id: str) -> bool:
        """Check whether a reference ID exists and is currently valid."""
        return self.get(ref_id) is not None

    def clear(self) -> None:
        """Clear all stored entries."""
        with self._lock:
            self._store.clear()

    def _prune_expired_locked(self) -> None:
        """Remove all expired entries while lock is held."""
        expired = [k for k, v in self._store.items() if v.is_expired]
        for k in expired:
            self._store.pop(k, None)

    def format_timeseries_result(
        self,
        series_data: List[Dict[str, Any]],
        max_inline_points: int = 50,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Package timeseries query results for LLM consumption.

        If the total number of points exceeds `max_inline_points`, the full raw array is
        cached in the ResultRefStore and a compact payload containing summary statistics,
        preview samples, and the `result_ref` is returned.
        """
        total_points = sum(len(s.get("data", [])) for s in series_data)

        # Compute summary statistics across all series
        series_summaries = []
        for s in series_data:
            points = s.get("data", [])
            vals = [p[1] for p in points if isinstance(p, (list, tuple)) and len(p) >= 2 and p[1] is not None]
            min_val = min(vals) if vals else None
            max_val = max(vals) if vals else None
            avg_val = round(sum(vals) / len(vals), 2) if vals else None

            # Generate compact preview: first 2 points and last 2 points
            preview = []
            if len(points) <= 4:
                preview = points
            else:
                preview = points[:2] + [("...", "...")] + points[-2:]

            series_summaries.append({
                "series_name": s.get("name", "series"),
                "canonical_signal": s.get("canonical_signal"),
                "asset_id": s.get("asset_id"),
                "asset_name": s.get("asset_name"),
                "unit": s.get("unit"),
                "point_count": len(points),
                "min": min_val,
                "max": max_val,
                "avg": avg_val,
                "preview": preview,
            })

        # Cache full data in store
        ref_id = self.put(data=series_data, prefix="ref_ts", metadata=metadata)

        if total_points <= max_inline_points:
            # Inline complete data if small enough
            return {
                "result_ref": ref_id,
                "total_points": total_points,
                "series_summaries": series_summaries,
                "data": series_data,
                "notice": "Timeseries data is small and returned inline.",
            }

        return {
            "result_ref": ref_id,
            "total_points": total_points,
            "series_summaries": series_summaries,
            "notice": (
                f"Dataset contains {total_points:,} points. Full data cached under result_ref '{ref_id}'. "
                "Use result_ref when calling render_chart to visualize this timeseries."
            ),
        }


class ChartStore(ResultRefStore):
    """Specialized reference store for ECharts specifications."""
    pass


# Global Singletons
default_result_store = ResultRefStore(max_entries=2000, default_ttl_seconds=7200)
default_chart_store = ChartStore(max_entries=1000, default_ttl_seconds=7200)


def format_timeseries_result(
    series_data: List[Dict[str, Any]],
    max_inline_points: int = 50,
    metadata: Optional[Dict[str, Any]] = None,
    store: Optional[ResultRefStore] = None,
) -> Dict[str, Any]:
    """Top-level helper formatting timeseries data using default or supplied ResultRefStore."""
    target_store = store or default_result_store
    return target_store.format_timeseries_result(
        series_data=series_data,
        max_inline_points=max_inline_points,
        metadata=metadata,
    )


