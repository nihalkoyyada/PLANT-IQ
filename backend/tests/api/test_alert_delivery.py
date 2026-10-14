"""Unit and Integration Tests for Alert Notification Delivery Handlers (§12, Task S4-FS-03).

Validates:
- Missing configuration failure without localhost fallback or false success simulation.
- Successful Resend API provider acceptance (status == 'accepted').
- Resend API error handling (401 invalid key, rate limits).
- Resend recipient restriction detection (403 / testing restriction on onboarding@resend.dev).
- Explicit mock testing (status == 'simulated' ONLY when MOCK_EMAIL=true).
- Webhook delivery status tracking (delivered / failed).
- API endpoint integration test (/alert-rules/{id}/test) with database audit verification.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
import resend.exceptions

from app.alerts.delivery import (
    STATUS_ACCEPTED,
    STATUS_DELIVERED,
    STATUS_FAILED,
    STATUS_SIMULATED,
    dispatch_alert_delivery,
    send_email_alert,
    send_webhook_alert,
)
from app.core.config import settings
from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.main import app
from app.models import AlertDelivery, AlertRule, Organization, Plant, User


@pytest.fixture
def client():
    return TestClient(app)


def test_send_email_alert_missing_configuration_fails(monkeypatch):
    """When EMAIL_PROVIDER_API_KEY is missing and no external SMTP host is configured,

    delivery must fail with a helpful error message and MUST NOT attempt localhost
    or claim delivery succeeded.
    """
    monkeypatch.setattr(settings, "EMAIL_PROVIDER_API_KEY", None)
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "MOCK_EMAIL", False)
    monkeypatch.delenv("EMAIL_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("MOCK_EMAIL", raising=False)
    monkeypatch.delenv("MOCK_SMTP", raising=False)

    status, message = send_email_alert(
        recipient="operator@plantiq.io",
        subject="Breach Warning",
        body_text="Inverter power drop detected",
    )

    assert status == STATUS_FAILED
    assert "EMAIL_PROVIDER_API_KEY is missing" in message
    assert "https://resend.com" in message
    assert "simulated" not in message.lower()


def test_send_email_alert_resend_accepted(monkeypatch):
    """When EMAIL_PROVIDER_API_KEY is configured and Resend accepts the email,

    delivery status must be 'accepted' and record the provider email ID.
    """
    monkeypatch.setattr(settings, "EMAIL_PROVIDER_API_KEY", "re_live_test_key_123")
    monkeypatch.setattr(settings, "MOCK_EMAIL", False)
    monkeypatch.delenv("MOCK_EMAIL", raising=False)
    monkeypatch.delenv("MOCK_SMTP", raising=False)

    with patch("resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "resend_msg_abcdef123456"}

        status, message = send_email_alert(
            recipient="engineer@solartech.com",
            subject="Critical Inverter Alarm",
            body_text="Inverter INV-01 output dropped to 0 kW",
        )

        assert status == STATUS_ACCEPTED
        assert "Email accepted by Resend (ID: resend_msg_abcdef123456)" in message
        assert "engineer@solartech.com" in message
        mock_send.assert_called_once()
        call_params = mock_send.call_args[0][0]
        assert call_params["to"] == ["engineer@solartech.com"]
        assert call_params["subject"] == "Critical Inverter Alarm"
        assert "<html>" in call_params["html"].lower()


def test_send_email_alert_resend_api_error_401(monkeypatch):
    """When Resend returns an HTTP 401 Invalid API Key error,

    delivery status must be 'failed' with actionable guidance.
    """
    monkeypatch.setattr(settings, "EMAIL_PROVIDER_API_KEY", "re_invalid_key_xyz")
    monkeypatch.setattr(settings, "MOCK_EMAIL", False)

    err = resend.exceptions.ResendError(
        code=401,
        error_type="authentication_error",
        message="API key is invalid",
        suggested_action="Check your API key",
    )

    with patch("resend.Emails.send", side_effect=err):
        status, message = send_email_alert(
            recipient="ops@plantiq.io",
            subject="Test Ping",
            body_text="Health check",
        )

        assert status == STATUS_FAILED
        assert "Resend authentication failed (HTTP 401)" in message
        assert "EMAIL_PROVIDER_API_KEY" in message


def test_send_email_alert_resend_recipient_restriction_detected(monkeypatch):
    """When Resend rejects an email due to sandbox testing restrictions (onboarding@resend.dev

    only allowing verified account email), delivery status must be 'failed' and explicitly
    explain the restriction and resolution.
    """
    monkeypatch.setattr(settings, "EMAIL_PROVIDER_API_KEY", "re_test_key_abc")
    monkeypatch.setattr(settings, "MOCK_EMAIL", False)

    err = resend.exceptions.ResendError(
        code=403,
        error_type="forbidden",
        message="You can only send testing emails to your own email address (owner@company.com). To send to other domains, you must verify a domain at resend.com/domains.",
        suggested_action="Verify domain",
    )

    with patch("resend.Emails.send", side_effect=err):
        status, message = send_email_alert(
            recipient="client@thirdparty.com",
            subject="Daily Summary",
            body_text="Daily PR report",
        )

        assert status == STATUS_FAILED
        assert "Provider recipient restriction" in message
        assert "onboarding@resend.dev" in message
        assert "resend.com/domains" in message


def test_send_email_alert_explicit_mock_mode(monkeypatch):
    """When MOCK_EMAIL is explicitly enabled, delivery returns 'simulated' status."""
    monkeypatch.setattr(settings, "MOCK_EMAIL", True)

    status, message = send_email_alert(
        recipient="dev@plantiq.local",
        subject="Mock Test",
        body_text="Testing offline",
    )

    assert status == STATUS_SIMULATED
    assert "Simulated delivery" in message
    assert "MOCK_EMAIL is active" in message


def test_send_email_alert_invalid_recipient():
    """Invalid recipient emails fail immediately without attempting API calls."""
    status, message = send_email_alert(
        recipient="invalid-recipient-without-at",
        subject="Test",
        body_text="Test body",
    )
    assert status == STATUS_FAILED
    assert "Invalid recipient email address" in message


def test_send_webhook_alert_success_and_failure():
    """Webhooks track status as 'delivered' on HTTP 2xx or 'failed' on network error."""
    with patch("httpx.Client.post") as mock_post:
        # Success case
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        status, message = send_webhook_alert(
            url="https://hooks.plantiq.io/alerts",
            payload={"test": 1},
        )
        assert status == STATUS_DELIVERED
        assert "HTTP 200 Success" in message

        # Failure case
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        status, message = send_webhook_alert(
            url="https://hooks.plantiq.io/alerts",
            payload={"test": 1},
            max_retries=1,
        )
        assert status == STATUS_FAILED
        assert "HTTP 500" in message


def test_api_test_alert_rule_endpoint_resend_acceptance(client: TestClient, monkeypatch):
    """Verify POST /alert-rules/{rule_id}/test works end-to-end with Resend API

    and creates an audit record with status 'accepted'.
    """
    monkeypatch.setattr(settings, "EMAIL_PROVIDER_API_KEY", "re_integration_test_key")
    monkeypatch.setattr(settings, "MOCK_EMAIL", False)

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.name == "Resend Test Org").first()
        if not org:
            org = Organization(name="Resend Test Org")
            db.add(org)
            db.commit()
            db.refresh(org)

        user = db.query(User).filter(User.email == "tester@plantiq.io").first()
        if not user:
            user = User(
                org_id=org.id,
                email="tester@plantiq.io",
                password_hash="hashed_pw",
                full_name="Tester",
                role="engineer",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        plant = db.query(Plant).filter(Plant.name == "Resend Test Plant").first()
        if not plant:
            plant = Plant(
                org_id=org.id,
                name="Resend Test Plant",
                plant_type="solar",
                capacity_ac_kw=1500.0,
                capacity_dc_kwp=1650.0,
            )
            db.add(plant)
            db.commit()
            db.refresh(plant)

        rule = AlertRule(
            plant_id=plant.id,
            name="Resend Email Rule",
            metric="active_power",
            threshold=500.0,
            direction="below",
            severity="critical",
            channels=["email"],
            enabled=True,
            config={"recipients": ["tester@plantiq.io"]},
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)

        token = create_access_token(data={"sub": str(user.id), "org_id": str(org.id), "role": user.role})
        headers = {"Authorization": f"Bearer {token}"}

        with patch("resend.Emails.send") as mock_send:
            mock_send.return_value = {"id": "resend_api_998877"}

            res = client.post(
                f"/alert-rules/{rule.id}/test",
                json={"test_message": "Manual verification ping"},
                headers=headers,
            )

            assert res.status_code == 200, res.text
            data = res.json()
            assert data["status"] == "accepted"
            assert data["channel"] == "email"
            assert data["recipient"] == "tester@plantiq.io"
            assert "resend_api_998877" in data["message"]

            delivery = (
                db.query(AlertDelivery)
                .filter(AlertDelivery.rule_id == rule.id)
                .order_by(AlertDelivery.created_at.desc())
                .first()
            )
            assert delivery is not None
            assert delivery.status == "accepted"
            assert delivery.error_message is None
    finally:
        db.close()


def test_api_email_diagnostics_endpoint(client: TestClient, monkeypatch):
    """Verify GET /alert-rules/email-diagnostics safely reports configuration status without leaking secrets."""
    from app.core.config import get_settings

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "tester@plantiq.io").first()
        if not user:
            org = db.query(Organization).first()
            user = User(
                org_id=org.id,
                email="tester@plantiq.io",
                password_hash="hashed_pw",
                full_name="Tester",
                role="engineer",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        token = create_access_token(data={"sub": str(user.id), "org_id": str(user.org_id), "role": user.role})
        headers = {"Authorization": f"Bearer {token}"}

        # Case 1: Configured with key
        secret_key = "re_confidential_diagnostic_key_123"
        monkeypatch.setenv("EMAIL_PROVIDER_API_KEY", secret_key)
        get_settings(reload=True)

        res = client.get("/alert-rules/email-diagnostics", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["is_configured"] is True
        assert data["provider"] == "resend"
        assert secret_key not in res.text

        # Case 2: Missing key
        monkeypatch.delenv("EMAIL_PROVIDER_API_KEY", raising=False)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        get_settings(reload=True)

        res_missing = client.get("/alert-rules/email-diagnostics", headers=headers)
        assert res_missing.status_code == 200
        data_missing = res_missing.json()
        assert data_missing["is_configured"] is False
    finally:
        db.close()
