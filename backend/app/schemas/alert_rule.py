"""Pydantic schemas for PlantIQ Alert Rules and Notifications Delivery (§12, Task S4-FS-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AlertRuleBase(BaseModel):
    plant_id: UUID
    name: str = Field(..., min_length=1, max_length=120)
    metric: str = Field(..., description="Metric key e.g. 'severity', 'active_power', 'pr', 'loss_kw'")
    threshold: float
    direction: Literal["above", "below"]
    severity: Literal["info", "warning", "critical"]
    channels: List[Literal["email", "webhook"]] = Field(default_factory=list)
    enabled: bool = True
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Delivery parameters: e.g. {'recipients': ['eng@plantiq.io'], 'webhook_url': 'https://api.plantiq.io/hooks'}",
    )


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    metric: Optional[str] = None
    threshold: Optional[float] = None
    direction: Optional[Literal["above", "below"]] = None
    severity: Optional[Literal["info", "warning", "critical"]] = None
    channels: Optional[List[Literal["email", "webhook"]]] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


class AlertRuleResponse(AlertRuleBase):
    id: UUID
    created_at: datetime
    plant_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("config", mode="after")
    @classmethod
    def mask_credentials(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure sensitive tokens or passwords are never leaked to frontend."""
        if not isinstance(v, dict):
            return {}
        safe = dict(v)
        sensitive_patterns = ("secret", "token", "password", "auth", "api_key", "authorization")
        for k, val in list(safe.items()):
            if any(p in k.lower() for p in sensitive_patterns) and isinstance(val, str) and val:
                safe[k] = "***"
        return safe



class AlertDeliveryResponse(BaseModel):
    id: UUID
    rule_id: UUID
    plant_id: UUID
    anomaly_id: Optional[UUID] = None
    channel: str
    recipient: str
    status: str
    attempt_count: int
    payload: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestAlertRequest(BaseModel):
    recipient_override: Optional[str] = None
    test_message: Optional[str] = "PlantIQ Alert Rule Test Verification"


class TestAlertResponse(BaseModel):
    rule_id: UUID
    channel: str
    status: str
    message: str
    recipient: str


class EmailDiagnosticResponse(BaseModel):
    is_configured: bool
    provider: str
    from_email: str
    env_file_detected: bool
    env_file_path: Optional[str] = None
    mock_mode_active: bool
