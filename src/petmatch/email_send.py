"""Email delivery: Resend HTTP API (default) or SMTP fallback."""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from .config import CONFIG, Config


def _send_resend(subject: str, html: str, text: str, cfg: Config) -> bool:
    if not cfg.resend_api_key:
        print("  [email] RESEND_API_KEY not set; skipping send.")
        return False
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {cfg.resend_api_key}",
                     "Content-Type": "application/json"},
            json={"from": cfg.report_from, "to": [cfg.report_email],
                  "subject": subject, "html": html, "text": text},
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        print(f"  [email] resend error: {e}")
        return False
    if resp.status_code >= 300:
        print(f"  [email] resend failed {resp.status_code}: {resp.text[:300]}")
        return False
    print(f"  [email] sent via Resend to {cfg.report_email}")
    return True


def _send_smtp(subject: str, html: str, text: str, cfg: Config) -> bool:
    if not (cfg.smtp_user and cfg.smtp_pass):
        print("  [email] SMTP_USER/SMTP_PASS not set; skipping send.")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.report_from
    msg["To"] = cfg.report_email
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(cfg.smtp_user, cfg.smtp_pass)
            server.sendmail(cfg.smtp_user, [cfg.report_email], msg.as_string())
    except (smtplib.SMTPException, OSError) as e:
        print(f"  [email] smtp error: {e}")
        return False
    print(f"  [email] sent via SMTP to {cfg.report_email}")
    return True


def send_email(subject: str, html: str, text: str, cfg: Config = CONFIG) -> bool:
    if cfg.email_backend == "smtp":
        return _send_smtp(subject, html, text, cfg)
    return _send_resend(subject, html, text, cfg)
