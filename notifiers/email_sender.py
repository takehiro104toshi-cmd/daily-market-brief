"""メール通知（SMTP想定）: 将来拡張用スタブ・未実装。

実装イメージ（将来）:
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(f"{payload.summary}\\n{payload.report_url}")
    msg["Subject"] = payload.title
    msg["From"] = from_addr
    msg["To"] = to_addr
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
"""
from __future__ import annotations

from .base import NotificationPayload, Notifier


class EmailNotifier(Notifier):
    """SMTP経由のメール通知スタブ（未実装）。"""

    def __init__(self, smtp_host: str = "", to_addr: str = ""):
        self.smtp_host = smtp_host
        self.to_addr = to_addr

    def send(self, payload: NotificationPayload) -> bool:
        raise NotImplementedError("メール通知は未実装です（将来拡張用インターフェースのみ）。")
