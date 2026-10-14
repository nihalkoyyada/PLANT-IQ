"""Alert Notification Delivery Handlers for Email (Resend API) & Webhooks (§12, Task S4-FS-03).

Provides:
- Transactional email delivery via Resend API (official SDK / API client).
- Sandbox testing support using onboarding@resend.dev without requiring custom domain or Gmail.
- Explicit detection and clear reporting of provider testing restrictions.
- Accurate delivery status tracking: ACCEPTED, DELIVERED, SIMULATED, FAILED.
- Zero silent localhost SMTP attempts and zero false DELIVERED simulations.
- Secure Webhook dispatch via HTTP POST with custom headers, HMAC-ready signatures, and timeouts.
- Sanitized payload and credential masking to ensure zero leakage of secrets.
"""

from __future__ import annotations

import email.message
import json
import logging
import os
import smtplib
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger("plantiq.alerts.delivery")

STATUS_ACCEPTED = "accepted"
STATUS_DELIVERED = "delivered"
STATUS_SIMULATED = "simulated"
STATUS_FAILED = "failed"


def mask_sensitive_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of dictionary with passwords and tokens masked."""
    if not isinstance(data, dict):
        return {}
    clean = {}
    sensitive_keys = {"secret", "token", "password", "auth", "api_key", "authorization", "webhook_secret"}
    for k, v in data.items():
        if isinstance(v, dict):
            clean[k] = mask_sensitive_dict(v)
        elif any(s in k.lower() for s in sensitive_keys) and isinstance(v, str) and v:
            clean[k] = "***"
        else:
            clean[k] = v
    return clean


def build_email_html(subject: str, body_text: str, payload: Optional[Dict[str, Any]] = None) -> str:
    """Generate a clean, responsive HTML email template for PlantIQ alerts."""
    data = payload or {}
    severity = str(data.get("severity", "Warning")).upper()
    plant_name = data.get("plant_name") or "Solar Installation"
    rule_name = data.get("rule_name") or data.get("alert_rule_name") or "Telemetry Monitoring Rule"
    summary = data.get("summary") or subject

    badge_bg = "#dc2626" if "CRIT" in severity else ("#d97706" if "WARN" in severity else "#0284c7")

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 24px; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ background-color: #004874; padding: 20px 24px; color: #ffffff; }}
    .header h1 {{ margin: 0; font-size: 18px; font-weight: 700; letter-spacing: -0.02em; }}
    .header p {{ margin: 4px 0 0 0; font-size: 12px; opacity: 0.85; }}
    .content {{ padding: 24px; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; color: #ffffff; background-color: {badge_bg}; text-transform: uppercase; }}
    .meta-table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }}
    .meta-table td {{ padding: 8px 12px; border-bottom: 1px solid #f1f5f9; }}
    .meta-label {{ color: #64748b; font-weight: 600; width: 35%; }}
    .meta-value {{ color: #0f172a; font-weight: 500; }}
    .body-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-top: 18px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; line-height: 1.5; white-space: pre-wrap; color: #334155; }}
    .footer {{ padding: 16px 24px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 11px; color: #94a3b8; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>PlantIQ &bull; Telemetry Alert Notification</h1>
      <p>Autonomous Solar Performance & Anomaly Monitoring Platform</p>
    </div>
    <div class="content">
      <div style="margin-bottom: 16px;">
        <span class="badge">{severity}</span>
        <h2 style="margin: 8px 0 4px 0; font-size: 16px; color: #0f172a;">{summary}</h2>
      </div>
      <table class="meta-table">
        <tr><td class="meta-label">Plant</td><td class="meta-value">{plant_name}</td></tr>
        <tr><td class="meta-label">Rule Trigger</td><td class="meta-value">{rule_name}</td></tr>
        <tr><td class="meta-label">Severity Tier</td><td class="meta-value">{severity}</td></tr>
      </table>
      <div class="body-box">{body_text}</div>
    </div>
    <div class="footer">
      Sent automatically by PlantIQ Alert Engine &bull; Verify notifications and active alerts in your dashboard.
    </div>
  </div>
</body>
</html>"""
    return html


def send_webhook_alert(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout_seconds: float = 5.0,
    max_retries: int = 2,
) -> Tuple[str, str]:
    """Dispatch an alert payload to a remote webhook endpoint with retries and timeout."""
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return STATUS_FAILED, f"Invalid webhook URL destination: '{url}'"

    req_headers = {
        "Content-Type": "application/json",
        "User-Agent": "PlantIQ-Alert-Engine/1.0",
    }
    if headers:
        for k, v in headers.items():
            if k.lower() not in ("content-length", "host"):
                req_headers[k] = str(v)

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                resp = client.post(url, json=payload, headers=req_headers)
                if 200 <= resp.status_code < 300:
                    return STATUS_DELIVERED, f"HTTP {resp.status_code} Success"
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.TimeoutException:
            last_error = f"Webhook request timed out after {timeout_seconds}s (attempt {attempt}/{max_retries})"
        except Exception as exc:
            last_error = f"Webhook connection error: {str(exc)} (attempt {attempt}/{max_retries})"

        if attempt < max_retries:
            time.sleep(0.5 * attempt)

    return STATUS_FAILED, last_error


def send_email_alert(
    recipient: str,
    subject: str,
    body_text: str,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    from_email: Optional[str] = None,
    timeout_seconds: float = 10.0,
    payload: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Dispatch an email alert notification via provider API (Resend) or external SMTP.

    Returns:
        Tuple[str, str]: (status, message)
        - 'accepted': provider queued and accepted the email for dispatch
        - 'delivered': confirmed delivered (e.g. webhook confirmation)
        - 'simulated': explicitly enabled local mock testing (MOCK_EMAIL=true)
        - 'failed': error, rejection, invalid recipient, or missing credentials
    """
    clean_recipient = recipient.strip() if recipient else ""
    if not clean_recipient or "@" not in clean_recipient:
        return STATUS_FAILED, f"Invalid recipient email address: '{recipient}'"

    from app.core.config import get_email_api_key, get_settings

    current_settings = get_settings()

    # Explicit mock testing: ONLY allowed when MOCK_EMAIL is explicitly enabled
    is_mock = (
        bool(current_settings.MOCK_EMAIL)
        or os.getenv("MOCK_EMAIL", "").lower() in ("1", "true")
        or os.getenv("MOCK_SMTP", "").lower() in ("1", "true")
    )
    if is_mock:
        logger.info(f"[Mock Email] Simulated delivery to {clean_recipient} with subject '{subject}'")
        return STATUS_SIMULATED, f"Simulated delivery to {clean_recipient} (MOCK_EMAIL is active)"

    # Safely retrieve Resend API key (with live .env refresh fallback)
    api_key = get_email_api_key()
    if api_key:
        api_key = api_key.strip()

    # Dispatch via Resend API / SDK
    if api_key:
        sender = (
            from_email
            or settings.EMAIL_FROM
            or os.getenv("EMAIL_FROM")
            or "PlantIQ Alerts <onboarding@resend.dev>"
        ).strip()

        html_content = build_email_html(subject=subject, body_text=body_text, payload=payload)

        try:
            import resend
            from resend.exceptions import ResendError

            resend.api_key = api_key

            params: resend.Emails.SendParams = {
                "from": sender,
                "to": [clean_recipient],
                "subject": subject,
                "text": body_text,
                "html": html_content,
            }

            resp = resend.Emails.send(params)
            email_id = resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", str(resp))
            logger.info(f"Resend accepted email dispatch to {clean_recipient} (ID: {email_id})")
            return STATUS_ACCEPTED, f"Email accepted by Resend (ID: {email_id}) for dispatch to {clean_recipient}"

        except Exception as exc:
            err_msg = str(exc)
            err_lower = err_msg.lower()
            code = getattr(exc, "code", None)

            # Detect provider testing recipient restrictions (§4)
            if (
                "only send testing emails to your own email address" in err_lower
                or "resend.dev" in err_lower
                or code == 403
            ):
                restriction_msg = (
                    f"Provider recipient restriction: In testing mode with 'onboarding@resend.dev', "
                    f"Resend only permits delivering to your registered account email. "
                    f"Recipient '{clean_recipient}' was rejected. "
                    f"To send to any recipient, verify your custom domain at resend.com/domains."
                )
                logger.warning(restriction_msg)
                return STATUS_FAILED, restriction_msg

            if code == 401 or "invalid api key" in err_lower or "api_key" in err_lower:
                auth_msg = (
                    "Resend authentication failed (HTTP 401): Invalid API Key. "
                    "Please verify EMAIL_PROVIDER_API_KEY in backend/.env."
                )
                logger.warning(auth_msg)
                return STATUS_FAILED, auth_msg

            logger.error(f"Resend dispatch error: {err_msg}")
            return STATUS_FAILED, f"Resend API error: {err_msg}"

    # No Resend API key configured: Check if a genuine external SMTP host was provided
    raw_host = (smtp_host or settings.SMTP_HOST or os.getenv("SMTP_HOST") or "").strip()
    is_invalid_or_local = (
        not raw_host
        or raw_host.lower() in ("localhost", "127.0.0.1", "none", "mock", "simulated", "false")
    )

    if is_invalid_or_local:
        return (
            STATUS_FAILED,
            "Email delivery not configured: EMAIL_PROVIDER_API_KEY is missing. "
            "Please add EMAIL_PROVIDER_API_KEY to backend/.env (create a free API key at https://resend.com) "
            "or set MOCK_EMAIL=true for offline mock testing.",
        )

    # Genuine external SMTP relay (e.g. custom corporate relay)
    port = int(smtp_port or settings.SMTP_PORT or os.getenv("SMTP_PORT", "587"))
    user = smtp_user or settings.SMTP_USER or os.getenv("SMTP_USER", "")
    password = smtp_password or settings.SMTP_PASSWORD or os.getenv("SMTP_PASSWORD", "")
    sender = from_email or settings.EMAIL_FROM or os.getenv("SMTP_FROM_EMAIL", "alerts@plantiq.io")

    msg = email.message.EmailMessage()
    msg.set_content(body_text)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = clean_recipient

    try:
        if port == 465:
            with smtplib.SMTP_SSL(raw_host, port, timeout=timeout_seconds) as server:
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(raw_host, port, timeout=timeout_seconds) as server:
                server.starttls()
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
        return STATUS_ACCEPTED, f"Sent email to {clean_recipient} via SMTP {raw_host}:{port}"
    except Exception as exc:
        logger.warning(f"External SMTP dispatch to {clean_recipient} failed: {exc}")
        return STATUS_FAILED, f"SMTP delivery failed: {str(exc)}"


def dispatch_alert_delivery(
    channel: str,
    recipient: str,
    payload: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Route alert delivery to appropriate channel (email or webhook).

    Returns:
        Tuple[str, str]: (status, message)
        status is one of: 'accepted', 'delivered', 'simulated', 'failed'
    """
    cfg = config or {}
    ch = channel.lower().strip()

    if ch == "webhook":
        headers = cfg.get("headers") or {}
        if "secret" in cfg and cfg["secret"]:
            headers["X-PlantIQ-Secret"] = str(cfg["secret"])
        timeout = float(cfg.get("timeout_seconds", 5.0))
        return send_webhook_alert(url=recipient, payload=payload, headers=headers, timeout_seconds=timeout)

    elif ch == "email":
        subject = payload.get("title") or f"[PlantIQ Alert] {payload.get('severity', 'Warning').upper()}: {payload.get('summary', 'Telemetry Alert')}"
        body = payload.get("formatted_body") or json.dumps(payload, indent=2)
        return send_email_alert(
            recipient=recipient,
            subject=subject,
            body_text=body,
            smtp_host=cfg.get("smtp_host"),
            smtp_port=cfg.get("smtp_port"),
            smtp_user=cfg.get("smtp_user"),
            smtp_password=cfg.get("smtp_password"),
            from_email=cfg.get("from_email"),
            payload=payload,
        )

    return STATUS_FAILED, f"Unsupported alert channel: '{channel}'"
