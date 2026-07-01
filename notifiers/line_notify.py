"""LINE通知（LINE Notify／LINE Messaging API想定）: 将来拡張用スタブ・未実装。

実装イメージ（将来）:
    import requests
    resp = requests.post(
        "https://notify-api.line.me/api/notify",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": f"{payload.title}\\n{payload.summary}\\n{payload.report_url}"},
        timeout=10,
    )
"""
from __future__ import annotations

from .base import NotificationPayload, Notifier


class LineNotifier(Notifier):
    """LINEへの通知スタブ。トークンは環境変数などから渡す想定（未実装）。"""

    def __init__(self, token: str = ""):
        self.token = token

    def send(self, payload: NotificationPayload) -> bool:
        raise NotImplementedError("LINE通知は未実装です（将来拡張用インターフェースのみ）。")
