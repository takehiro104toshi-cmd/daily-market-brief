"""LINE Messaging APIによるプッシュ通知（実装済み）。

LINE Notify は2025年3月末にサービスを終了したため、後継として案内されている
LINE Messaging API の「プッシュメッセージ」機能を使用する。

環境変数がすべて揃っている場合のみ実際に送信する。未設定の場合は
is_configured() が False を返し、呼び出し側（main.py）はこの通知を
スキップする（レポート生成自体は失敗させない）。

環境変数:
    LINE_CHANNEL_ACCESS_TOKEN  LINE Developersコンソールで発行する
                               チャネルアクセストークン（長期）
    LINE_TO                    通知を送るユーザーID または グループID

事前準備（README.md にも詳細を記載）:
    1. LINE Developersコンソールで Messaging API チャネルを作成する
    2. チャネルアクセストークン（長期）を発行する
    3. 通知を受け取りたいアカウント（Bot）を友だち追加し、
       そのユーザーID（またはグループID）を控える
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

from .base import NotificationPayload, Notifier

logger = logging.getLogger("market_brief")

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
MAX_TEXT_LENGTH = 1000  # LINE Messaging APIのテキストメッセージ上限に配慮
MAX_ATTEMPTS = 2  # 初回送信+1回のリトライ（一時的なネットワーク不調への耐性）
RETRY_DELAY_SECONDS = 2


class LineNotifier(Notifier):
    def __init__(self, channel_access_token: Optional[str] = None, to: Optional[str] = None):
        self.channel_access_token = (
            channel_access_token if channel_access_token is not None else os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
        )
        self.to = to if to is not None else os.environ.get("LINE_TO")

    def is_configured(self) -> bool:
        return bool(self.channel_access_token and self.to)

    def _post_once(self, text: str) -> None:
        resp = requests.post(
            LINE_PUSH_URL,
            headers={
                "Authorization": f"Bearer {self.channel_access_token}",
                "Content-Type": "application/json",
            },
            json={"to": self.to, "messages": [{"type": "text", "text": text}]},
            timeout=15,
        )
        resp.raise_for_status()

    def send(self, payload: NotificationPayload) -> bool:
        if not self.is_configured():
            logger.info("LINE通知はチャネルアクセストークン未設定のためスキップします。")
            return False

        text = payload.summary.strip()
        if payload.report_url:
            text = f"{text}\n{payload.report_url}"
        text = f"{payload.title}\n{text}"[:MAX_TEXT_LENGTH]

        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                self._post_once(text)
                logger.info("LINE通知を送信しました。（試行%d回目）", attempt)
                return True
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < MAX_ATTEMPTS:
                    logger.warning(
                        "LINE通知の送信に失敗しました。%d秒後に再試行します（試行%d/%d回目）: %s",
                        RETRY_DELAY_SECONDS, attempt, MAX_ATTEMPTS, exc,
                    )
                    time.sleep(RETRY_DELAY_SECONDS)

        logger.warning("LINE通知の送信に失敗しました（レポート生成は継続します）: %s", last_error)
        return False
