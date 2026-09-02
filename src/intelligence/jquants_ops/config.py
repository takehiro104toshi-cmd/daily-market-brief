"""jquants_ops の設定（`config.yaml: jquants_ops`）。読めなければ既定値。credentialは置かない。"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

CONFIG_SECTION = "jquants_ops"


@dataclass(frozen=True)
class OpsConfig:
    seed_sessions: int = 70                  # 初期構築で取る session 数（active 60 + buffer 10）
    active_calculation_sessions: int = 60    # 朝の指標計算に使う直近 session 数
    safety_buffer_sessions: int = 10         # corporate action / 欠落 session の余裕
    max_metric_window: int = 25              # 最長の指標窓（25日騰落レシオ）
    calendar_range_days: int = 150           # calendar 取得レンジ（暦日）
    master_refresh_days: int = 7             # master の再取得間隔（暦日）
    flow_lookback_days: int = 14             # 週次flowの差分取得レンジ（最新 period_end から）
    earnings_calendar_days_ahead: int = 90   # 決算予定の取得レンジ（先）
    retry_max_attempts: int = 2              # bounded retry（初回を含めた試行回数）
    retry_backoff_seconds: Tuple[int, ...] = (2, 4)
    partial_session_ratio: Decimal = Decimal("0.90")   # 行数がこの比率未満なら PARTIAL_SESSION
    request_interval_seconds: Decimal = Decimal("0.3")
    pilot_seed_sessions: int = 30            # live pilot の seed（本番 seed 70 の mechanism 検証）

    def as_dict(self) -> Dict[str, object]:
        return {
            "seed_sessions": self.seed_sessions,
            "active_calculation_sessions": self.active_calculation_sessions,
            "safety_buffer_sessions": self.safety_buffer_sessions,
            "max_metric_window": self.max_metric_window,
            "calendar_range_days": self.calendar_range_days,
            "master_refresh_days": self.master_refresh_days,
            "flow_lookback_days": self.flow_lookback_days,
            "earnings_calendar_days_ahead": self.earnings_calendar_days_ahead,
            "retry_max_attempts": self.retry_max_attempts,
            "retry_backoff_seconds": list(self.retry_backoff_seconds),
            "partial_session_ratio": str(self.partial_session_ratio),
            "request_interval_seconds": str(self.request_interval_seconds),
            "pilot_seed_sessions": self.pilot_seed_sessions,
        }


def _int(value, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _decimal(value, default: Decimal) -> Decimal:
    try:
        return Decimal(str(value)) if value is not None else default
    except (InvalidOperation, ValueError):
        return default


def config_from_mapping(section: Optional[Mapping]) -> OpsConfig:
    s = dict(section or {})
    d = OpsConfig()
    backoff = s.get("retry_backoff_seconds")
    return OpsConfig(
        seed_sessions=_int(s.get("seed_sessions"), d.seed_sessions),
        active_calculation_sessions=_int(s.get("active_calculation_sessions"),
                                         d.active_calculation_sessions),
        safety_buffer_sessions=_int(s.get("safety_buffer_sessions"), d.safety_buffer_sessions),
        max_metric_window=_int(s.get("max_metric_window"), d.max_metric_window),
        calendar_range_days=_int(s.get("calendar_range_days"), d.calendar_range_days),
        master_refresh_days=_int(s.get("master_refresh_days"), d.master_refresh_days),
        flow_lookback_days=_int(s.get("flow_lookback_days"), d.flow_lookback_days),
        earnings_calendar_days_ahead=_int(s.get("earnings_calendar_days_ahead"),
                                          d.earnings_calendar_days_ahead),
        retry_max_attempts=_int(s.get("retry_max_attempts"), d.retry_max_attempts),
        retry_backoff_seconds=tuple(int(b) for b in backoff) if isinstance(backoff, (list, tuple))
        and backoff else d.retry_backoff_seconds,
        partial_session_ratio=_decimal(s.get("partial_session_ratio"), d.partial_session_ratio),
        request_interval_seconds=_decimal(s.get("request_interval_seconds"),
                                          d.request_interval_seconds),
        pilot_seed_sessions=_int(s.get("pilot_seed_sessions"), d.pilot_seed_sessions))


def load_ops_config(config_path: Path = Path("config.yaml")) -> OpsConfig:
    try:
        import yaml

        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        return config_from_mapping(data.get(CONFIG_SECTION))
    except Exception:  # noqa: BLE001
        return config_from_mapping(None)
