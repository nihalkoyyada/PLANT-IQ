"""Security Scoping & Authorization Context for Copilot Tools (§10.3, Task S5-AI-01).

Enforces multi-tenant organization isolation and plant-level authorization.
Guarantees that LLM-initiated tool calls cannot access, inspect, or leak data across
different organizations or unauthorized plants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Anomaly, Asset, Channel, Event, Plant


class SecurityScopeError(Exception):
    """Raised when a Copilot tool attempts unauthorized cross-tenant or cross-plant access."""

    def __init__(self, message: str, code: str = "FORBIDDEN_SCOPE") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolSecurityContext:
    """Multi-tenant security boundary enclosing every Copilot tool invocation."""

    org_id: UUID
    user_id: Optional[UUID] = None
    plant_id: Optional[UUID] = None
    allowed_plant_ids: Optional[Set[UUID]] = None  # None means all plants within org_id
    user_role: Optional[str] = "engineer"

    def __post_init__(self) -> None:
        if self.plant_id and self.allowed_plant_ids is None:
            self.allowed_plant_ids = {self.plant_id}
        elif self.plant_id and self.allowed_plant_ids is not None:
            self.allowed_plant_ids.add(self.plant_id)

    def validate_plant_access(self, plant_id: UUID, session: Session) -> Plant:
        """Verify plant exists, belongs to the authorized organization, and is in user scope."""
        stmt = select(Plant).where(Plant.id == plant_id, Plant.org_id == self.org_id)
        plant = session.execute(stmt).scalars().first()

        if not plant:
            raise SecurityScopeError(
                f"Plant '{plant_id}' not found or access denied for organization '{self.org_id}'.",
                code="PLANT_NOT_FOUND_OR_DENIED",
            )

        if self.allowed_plant_ids is not None and plant.id not in self.allowed_plant_ids:
            raise SecurityScopeError(
                f"Access to plant '{plant.name}' ({plant_id}) is not permitted under current user scope.",
                code="PLANT_SCOPE_DENIED",
            )

        return plant

    def validate_asset_access(self, asset_id: UUID, session: Session) -> Asset:
        """Verify asset exists and belongs to an authorized plant in this organization."""
        stmt = (
            select(Asset)
            .join(Plant, Asset.plant_id == Plant.id)
            .where(Asset.id == asset_id, Plant.org_id == self.org_id)
        )
        asset = session.execute(stmt).scalars().first()

        if not asset:
            raise SecurityScopeError(
                f"Asset '{asset_id}' not found or access denied for organization '{self.org_id}'.",
                code="ASSET_NOT_FOUND_OR_DENIED",
            )

        if self.allowed_plant_ids is not None and asset.plant_id not in self.allowed_plant_ids:
            raise SecurityScopeError(
                f"Access to asset '{asset.name}' on plant '{asset.plant_id}' is outside allowed user scope.",
                code="ASSET_SCOPE_DENIED",
            )

        return asset

    def validate_channel_access(self, channel_id: UUID, session: Session) -> Channel:
        """Verify channel exists and belongs to an authorized asset/plant in this organization."""
        stmt = (
            select(Channel)
            .join(Asset, Channel.asset_id == Asset.id)
            .join(Plant, Asset.plant_id == Plant.id)
            .where(Channel.id == channel_id, Plant.org_id == self.org_id)
        )
        channel = session.execute(stmt).scalars().first()

        if not channel:
            raise SecurityScopeError(
                f"Channel '{channel_id}' not found or access denied for organization '{self.org_id}'.",
                code="CHANNEL_NOT_FOUND_OR_DENIED",
            )

        if self.allowed_plant_ids is not None and channel.asset and channel.asset.plant_id not in self.allowed_plant_ids:
            raise SecurityScopeError(
                f"Channel '{channel_id}' is associated with an unauthorized plant.",
                code="CHANNEL_SCOPE_DENIED",
            )

        return channel

    def validate_anomaly_access(self, anomaly_id: UUID, session: Session) -> Anomaly:
        """Verify anomaly exists and belongs to an authorized plant in this organization."""
        stmt = (
            select(Anomaly)
            .join(Plant, Anomaly.plant_id == Plant.id)
            .where(Anomaly.id == anomaly_id, Plant.org_id == self.org_id)
        )
        anomaly = session.execute(stmt).scalars().first()

        if not anomaly:
            raise SecurityScopeError(
                f"Anomaly record '{anomaly_id}' not found or access denied for organization '{self.org_id}'.",
                code="ANOMALY_NOT_FOUND_OR_DENIED",
            )

        if self.allowed_plant_ids is not None and anomaly.plant_id not in self.allowed_plant_ids:
            raise SecurityScopeError(
                f"Anomaly '{anomaly_id}' belongs to plant '{anomaly.plant_id}' outside allowed user scope.",
                code="ANOMALY_SCOPE_DENIED",
            )

        return anomaly

    def validate_event_access(self, event_id: UUID, session: Session) -> Event:
        """Verify SCADA event exists and belongs to an authorized plant in this organization."""
        stmt = (
            select(Event)
            .join(Plant, Event.plant_id == Plant.id)
            .where(Event.id == event_id, Plant.org_id == self.org_id)
        )
        event = session.execute(stmt).scalars().first()

        if not event:
            raise SecurityScopeError(
                f"Event record '{event_id}' not found or access denied for organization '{self.org_id}'.",
                code="EVENT_NOT_FOUND_OR_DENIED",
            )

        if self.allowed_plant_ids is not None and event.plant_id not in self.allowed_plant_ids:
            raise SecurityScopeError(
                f"Event '{event_id}' belongs to plant '{event.plant_id}' outside allowed user scope.",
                code="EVENT_SCOPE_DENIED",
            )

        return event
