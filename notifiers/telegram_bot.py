"""Telegram通知（Bot API想定）: 将来拡張用スタブ・未実装。

実装イメージ（将来）:
    import requests
    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": f"{payload.title}\\n{payload.summary}\\n{payload.report_url}"},
        timeout=10,
    )
"""
from __future__ import annotations

from .base import NotificationPayload, Notifier


class TelegramNotifier(Notifier):
    """Telegram Bot APIへの通知スタブ（未実装）。"""

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def is_configured(self) -> bool:
        return False  # 未実装のため常にFalse（将来実装時に置き換える）

    def send(self, payload: NotificationPayload) -> bool:
        raise NotImplementedError("Telegram通知は未実装です（将来拡張用インターフェースのみ）。")
