"""notifiers/ の将来拡張用インターフェースを検証する（実装なし・スタブのみ）。"""
import pytest

from notifiers.base import NotificationPayload, Notifier
from notifiers.discord_webhook import DiscordNotifier
from notifiers.email_sender import EmailNotifier
from notifiers.line_notify import LineNotifier
from notifiers.slack_webhook import SlackNotifier
from notifiers.telegram_bot import TelegramNotifier


@pytest.mark.parametrize(
    "notifier_cls",
    [LineNotifier, DiscordNotifier, SlackNotifier, TelegramNotifier, EmailNotifier],
)
def test_notifier_stubs_implement_the_interface_but_are_not_functional(notifier_cls):
    notifier = notifier_cls()
    assert isinstance(notifier, Notifier)
    with pytest.raises(NotImplementedError):
        notifier.send(NotificationPayload(title="t", summary="s", report_url="https://example.com"))
