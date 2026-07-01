"""通知チャネル共通インターフェース（将来拡張用・現時点では未実装）。

将来的にLINE Notify・Discord・Slack・Telegram・メールへレポートの要約を
送信できるようにするための土台。本バージョンではインターフェースの型だけを
定義し、実際の送信ロジックは実装しない（ユーザー要望により今回は実装不要）。

想定する使い方（将来）:
    from notifiers.line_notify import LineNotifier
    from notifiers.base import NotificationPayload

    notifier = LineNotifier(token="...")
    notifier.send(NotificationPayload(
        title="Market Intelligence System v2",
        summary=ai_summary_text,
        report_url="https://github.com/.../mobile_market_brief.md",
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
    def send(self, payload: NotificationPayload) -> bool:
        """通知を送信する。成功時 True、失敗時 False を返す想定。

        本バージョンでは未実装（NotImplementedError）。
        """
        raise NotImplementedError
