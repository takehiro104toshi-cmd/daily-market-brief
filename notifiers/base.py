"""通知チャネル共通インターフェース。

email_sender.py（SMTP）と line_sender.py（LINE Messaging API）は実装済みで、
環境変数が揃っている場合のみ実際に送信する。discord_webhook.py・
slack_webhook.py・telegram_bot.py は引き続き将来拡張用のスタブ（未実装）。

想定する使い方:
    from notifiers.email_sender import EmailNotifier
    from notifiers.base import NotificationPayload

    notifier = EmailNotifier()
    if notifier.is_configured():
        notifier.send(NotificationPayload(
            title="【Market Brief】2026-07-01 朝刊",
            summary="今日の結論...\n重要ニュース3件...",
            report_url="https://<owner>.github.io/daily-market-brief/",
        ))
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class NotificationPayload:
    """通知内容。市場ブリーフの要約テキストとレポートへのリンクなどを想定。"""

    title: str
    summary: str
    report_url: str = ""


class Notifier(ABC):
    """各通知チャネルが実装すべき共通インターフェース。"""

    @abstractmethod
    def is_configured(self) -> bool:
        """送信に必要な設定（環境変数など）が揃っているかどうかを返す。

        False の場合、呼び出し側は send() を呼ばずにスキップすることが期待される
        （未実装のチャネルは常に False を返す）。
        """
        raise NotImplementedError

    @abstractmethod
    def send(self, payload: NotificationPayload) -> bool:
        """通知を送信する。成功時 True、失敗・未実装時 False を返す。

        例外を送出せず、失敗時も False を返してレポート生成全体を
        止めないようにすることが期待される。
        """
        raise NotImplementedError
