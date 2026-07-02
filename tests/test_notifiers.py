"""notifiers/ の通知チャネルを検証する。

- Discord/Slack/Telegram: 将来拡張用スタブ（未実装・常に is_configured() False）
- Email/LINE: 実装済み。環境変数が揃っている場合のみ送信を試み、
  失敗しても例外を外に伝播させないことを確認する（レポート生成を止めないため）。
  実際のネットワーク送信は行わず、smtplib.SMTP / requests.post をモックする。
"""
from unittest.mock import MagicMock, patch

import pytest

from notifiers.base import NotificationPayload, Notifier
from notifiers.discord_webhook import DiscordNotifier
from notifiers.email_sender import EmailNotifier
from notifiers.line_sender import LineNotifier
from notifiers.slack_webhook import SlackNotifier
from notifiers.telegram_bot import TelegramNotifier

SAMPLE_PAYLOAD = NotificationPayload(title="t", summary="s", report_url="https://example.com")


@pytest.mark.parametrize(
    "notifier_cls",
    [DiscordNotifier, SlackNotifier, TelegramNotifier],
)
def test_stub_notifiers_are_not_configured_and_raise_on_send(notifier_cls):
    notifier = notifier_cls()
    assert isinstance(notifier, Notifier)
    assert notifier.is_configured() is False
    with pytest.raises(NotImplementedError):
        notifier.send(SAMPLE_PAYLOAD)


def test_email_notifier_not_configured_without_env(monkeypatch):
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO", "MAIL_FROM"):
        monkeypatch.delenv(var, raising=False)
    notifier = EmailNotifier()
    assert notifier.is_configured() is False
    assert notifier.send(SAMPLE_PAYLOAD) is False


def test_email_notifier_sends_when_configured():
    notifier = EmailNotifier(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="secret",
        mail_to="to@example.com",
        mail_from="from@example.com",
    )
    assert notifier.is_configured() is True

    mock_server = MagicMock()
    with patch("notifiers.email_sender.smtplib.SMTP") as mock_smtp:
        mock_smtp.return_value.__enter__.return_value = mock_server
        result = notifier.send(SAMPLE_PAYLOAD)

    assert result is True
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user@example.com", "secret")
    mock_server.sendmail.assert_called_once()


def test_email_notifier_send_failure_does_not_raise():
    notifier = EmailNotifier(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="secret",
        mail_to="to@example.com",
        mail_from="from@example.com",
    )
    with patch("notifiers.email_sender.smtplib.SMTP", side_effect=OSError("connection refused")):
        result = notifier.send(SAMPLE_PAYLOAD)

    assert result is False


def test_line_notifier_not_configured_without_env(monkeypatch):
    for var in ("LINE_CHANNEL_ACCESS_TOKEN", "LINE_TO"):
        monkeypatch.delenv(var, raising=False)
    notifier = LineNotifier()
    assert notifier.is_configured() is False
    assert notifier.send(SAMPLE_PAYLOAD) is False


def test_line_notifier_sends_when_configured():
    notifier = LineNotifier(channel_access_token="token123", to="user123")
    assert notifier.is_configured() is True

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    with patch("notifiers.line_sender.requests.post", return_value=mock_response) as mock_post:
        result = notifier.send(SAMPLE_PAYLOAD)

    assert result is True
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer token123"
    assert kwargs["json"]["to"] == "user123"


def test_line_notifier_send_failure_does_not_raise():
    notifier = LineNotifier(channel_access_token="token123", to="user123")
    with patch("notifiers.line_sender.requests.post", side_effect=OSError("network error")), \
         patch("notifiers.line_sender.time.sleep") as mock_sleep:
        result = notifier.send(SAMPLE_PAYLOAD)

    assert result is False
    mock_sleep.assert_called_once()  # 1回リトライを試みたこと


def test_line_notifier_retries_once_then_succeeds():
    notifier = LineNotifier(channel_access_token="token123", to="user123")
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    with patch(
        "notifiers.line_sender.requests.post",
        side_effect=[OSError("temporary network error"), mock_response],
    ) as mock_post, patch("notifiers.line_sender.time.sleep") as mock_sleep:
        result = notifier.send(SAMPLE_PAYLOAD)

    assert result is True
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()
