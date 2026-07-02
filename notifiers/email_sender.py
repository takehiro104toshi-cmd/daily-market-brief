"""SMTPによるメール通知（実装済み）。

環境変数がすべて揃っている場合のみ実際に送信する。
どれか一つでも未設定の場合は is_configured() が False を返し、
呼び出し側（main.py）はこの通知をスキップする
（レポート生成自体は失敗させない）。

環境変数:
    SMTP_HOST      SMTPサーバーのホスト名
    SMTP_PORT      SMTPサーバーのポート番号（既定: 587、STARTTLS想定）
    SMTP_USER      SMTP認証のユーザー名
    SMTP_PASSWORD  SMTP認証のパスワード（Gmail等はアプリパスワードを推奨）
    MAIL_TO        送信先メールアドレス
    MAIL_FROM      送信元メールアドレス（未設定時は SMTP_USER を使用）
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from .base import NotificationPayload, Notifier

logger = logging.getLogger("market_brief")


class EmailNotifier(Notifier):
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        mail_to: Optional[str] = None,
        mail_from: Optional[str] = None,
    ):
        self.host = host if host is not None else os.environ.get("SMTP_HOST")
        raw_port = port if port is not None else os.environ.get("SMTP_PORT", "587")
        try:
            self.port = int(raw_port)
        except (TypeError, ValueError):
            self.port = 587
        self.user = user if user is not None else os.environ.get("SMTP_USER")
        self.password = password if password is not None else os.environ.get("SMTP_PASSWORD")
        self.mail_to = mail_to if mail_to is not None else os.environ.get("MAIL_TO")
        self.mail_from = mail_from if mail_from is not None else os.environ.get("MAIL_FROM") or self.user

    def is_configured(self) -> bool:
        return bool(self.host and self.user and self.password and self.mail_to)

    def send(self, payload: NotificationPayload) -> bool:
        if not self.is_configured():
            logger.info("メール通知はSMTP設定が未完了のためスキップします。")
            return False

        body = payload.summary.strip()
        if payload.report_url:
            body = f"{body}\n\n{payload.report_url}"

        msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = payload.title
        msg["From"] = self.mail_from
        msg["To"] = self.mail_to

        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.mail_from, [self.mail_to], msg.as_string())
            logger.info("メール通知を送信しました。")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("メール通知の送信に失敗しました（レポート生成は継続します）: %s", exc)
            return False
