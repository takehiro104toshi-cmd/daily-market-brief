"""Discord通知（Webhook想定）: 将来拡張用スタブ・未実装。

実装イメージ（将来）:
    import requests
    resp = requests.post(
        webhook_url,
        json={"content": f"**{payload.title}**\\n{payload.summary}\\n{payload.report_url}"},
        timeout=10,
    )
"""
from __future__ import annotations

from .base import NotificationPayload, Notifier


class DiscordNotifier(Notifier):
    """Discord Webhookへの通知スタブ（未実装）。"""

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url

    def send(self, payload: NotificationPayload) -> bool:
        raise NotImplementedError("Discord通知は未実装です（将来拡張用インターフェースのみ）。")
