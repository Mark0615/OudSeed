"""Tests for SMTP email delivery helpers."""

from unittest.mock import Mock, patch

import pytest

from src.notifications.email_delivery import (
    SMTPEmailConfig,
    SMTPEmailSender,
    load_smtp_email_config_from_env,
)


def test_load_smtp_email_config_from_env(monkeypatch) -> None:
    """SMTP config is loaded from environment variables."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "reports@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")

    config = load_smtp_email_config_from_env()

    assert config.host == "smtp.example.com"
    assert config.port == 2525
    assert config.username == "sender@example.com"
    assert config.password == "secret"
    assert config.from_email == "reports@example.com"
    assert config.use_tls is False


def test_load_smtp_email_config_requires_credentials(monkeypatch) -> None:
    """Missing SMTP credentials fail clearly."""
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with pytest.raises(ValueError, match="SMTP_HOST"):
        load_smtp_email_config_from_env()


def test_smtp_email_sender_sends_message() -> None:
    """SMTP sender logs in and sends a message."""
    smtp_instance = Mock()
    smtp_context = Mock()
    smtp_context.__enter__ = Mock(return_value=smtp_instance)
    smtp_context.__exit__ = Mock(return_value=None)

    with patch("src.notifications.email_delivery.smtplib.SMTP", return_value=smtp_context):
        sender = SMTPEmailSender(
            SMTPEmailConfig(
                host="smtp.example.com",
                port=587,
                username="sender@example.com",
                password="secret",
                from_email="reports@example.com",
            )
        )
        sender.send(
            recipient="user@example.com",
            subject="Report",
            body="Body",
        )

    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("sender@example.com", "secret")
    sent_message = smtp_instance.send_message.call_args.args[0]
    assert sent_message["To"] == "user@example.com"
    assert sent_message["Subject"] == "Report"


def test_smtp_email_sender_can_send_html_alternative() -> None:
    """SMTP sender can include an HTML alternative body."""
    smtp_instance = Mock()
    smtp_context = Mock()
    smtp_context.__enter__ = Mock(return_value=smtp_instance)
    smtp_context.__exit__ = Mock(return_value=None)

    with patch("src.notifications.email_delivery.smtplib.SMTP", return_value=smtp_context):
        sender = SMTPEmailSender(
            SMTPEmailConfig(
                host="smtp.example.com",
                port=587,
                username="sender@example.com",
                password="secret",
                from_email="reports@example.com",
            )
        )
        sender.send(
            recipient="user@example.com",
            subject="Report",
            body="Plain body",
            html_body="<strong>HTML body</strong>",
        )

    sent_message = smtp_instance.send_message.call_args.args[0]
    assert sent_message.is_multipart()
    assert "HTML body" in sent_message.get_body(("html",)).get_content()
