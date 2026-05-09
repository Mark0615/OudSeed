"""SMTP email delivery for generated reports."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True)
class SMTPEmailConfig:
    """SMTP settings loaded from environment variables."""

    host: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool = True


class SMTPEmailSender:
    """Send plain-text emails through SMTP."""

    def __init__(self, config: SMTPEmailConfig) -> None:
        self.config = config

    def send(
        self,
        recipient: str,
        subject: str,
        body: str,
    ) -> None:
        """Send one email."""
        message = EmailMessage()
        message["From"] = self.config.from_email
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self.config.host, self.config.port, timeout=60) as smtp:
            if self.config.use_tls:
                smtp.starttls()
            smtp.login(self.config.username, self.config.password)
            smtp.send_message(message)


def load_smtp_email_config_from_env() -> SMTPEmailConfig:
    """Load SMTP config from environment variables."""
    return SMTPEmailConfig(
        host=_required_env("SMTP_HOST"),
        port=_positive_int_env("SMTP_PORT", 587),
        username=_required_env("SMTP_USERNAME"),
        password=_required_env("SMTP_PASSWORD"),
        from_email=os.getenv("SMTP_FROM_EMAIL") or _required_env("SMTP_USERNAME"),
        use_tls=_bool_env("SMTP_USE_TLS", True),
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc

    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")

    return value


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return default

    return raw_value.strip().lower() not in {"0", "false", "no"}
