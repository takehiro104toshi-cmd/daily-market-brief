"""Mobile intake の repository 設定（config.yaml `mobile_intake`）。

機械固有の絶対 path はここに置かない（local_config.py が env / ローカルファイルから解決する）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

CONFIG_SECTION = "mobile_intake"


@dataclass(frozen=True)
class MobileIntakeConfig:
    provider: str = "ICLOUD_DRIVE"                 # ICLOUD_DRIVE / ONEDRIVE / GOOGLE_DRIVE / LOCAL_FOLDER
    inbox_subpath: str = "Shortcuts/CompassInbox"  # provider の同期 root からの相対 path
    stable_seconds: int = 20                       # mtime がこれ以上前で size 不変なら安定
    stable_samples: int = 2
    sample_interval_seconds: float = 1.0
    unstable_timeout_minutes: int = 30             # これを超えて不安定なら FAILED(TIMEOUT_UNSTABLE)
    stale_lock_minutes: int = 15                   # crash 後の lock はこれを超えたら回収
    max_files_per_run: int = 20                    # 1 回の処理上限（bounded）
    time_budget_seconds: int = 120                 # 1 回の時間上限（bounded）
    scheduler_interval_minutes: int = 5            # Task Scheduler の間隔
    task_name: str = "CompassIntake"
    status_in_inbox: bool = True                   # 同期フォルダの _status/ に status を書く（iPhone から見える）
    status_dir_name: str = "_status"
    shortcut_name: str = "羅針盤に追加"
    local_config_dir_name: str = ".compass_intake"
    trigger_research: bool = True                  # Corpus SUCCESS 後に Phase 3.8 incremental analysis を呼ぶ

    def as_dict(self) -> Dict[str, Any]:
        return {"provider": self.provider, "inbox_subpath": self.inbox_subpath,
                "stable_seconds": self.stable_seconds, "stable_samples": self.stable_samples,
                "sample_interval_seconds": self.sample_interval_seconds,
                "unstable_timeout_minutes": self.unstable_timeout_minutes,
                "stale_lock_minutes": self.stale_lock_minutes,
                "max_files_per_run": self.max_files_per_run,
                "time_budget_seconds": self.time_budget_seconds,
                "scheduler_interval_minutes": self.scheduler_interval_minutes,
                "task_name": self.task_name, "status_in_inbox": self.status_in_inbox,
                "status_dir_name": self.status_dir_name, "shortcut_name": self.shortcut_name,
                "local_config_dir_name": self.local_config_dir_name,
                "trigger_research": self.trigger_research}


def config_from_mapping(section: Optional[Mapping[str, Any]]) -> MobileIntakeConfig:
    s = dict(section or {})
    base = MobileIntakeConfig()

    def _int(key: str, default: int) -> int:
        try:
            return int(s.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(s.get(key, default))
        except (TypeError, ValueError):
            return default

    return MobileIntakeConfig(
        provider=str(s.get("provider", base.provider) or base.provider).upper(),
        inbox_subpath=str(s.get("inbox_subpath", base.inbox_subpath) or base.inbox_subpath),
        stable_seconds=_int("stable_seconds", base.stable_seconds),
        stable_samples=max(2, _int("stable_samples", base.stable_samples)),
        sample_interval_seconds=_float("sample_interval_seconds", base.sample_interval_seconds),
        unstable_timeout_minutes=_int("unstable_timeout_minutes", base.unstable_timeout_minutes),
        stale_lock_minutes=_int("stale_lock_minutes", base.stale_lock_minutes),
        max_files_per_run=max(1, _int("max_files_per_run", base.max_files_per_run)),
        time_budget_seconds=max(5, _int("time_budget_seconds", base.time_budget_seconds)),
        scheduler_interval_minutes=max(1, _int("scheduler_interval_minutes",
                                               base.scheduler_interval_minutes)),
        task_name=str(s.get("task_name", base.task_name) or base.task_name),
        status_in_inbox=bool(s.get("status_in_inbox", base.status_in_inbox)),
        status_dir_name=str(s.get("status_dir_name", base.status_dir_name) or base.status_dir_name),
        shortcut_name=str(s.get("shortcut_name", base.shortcut_name) or base.shortcut_name),
        local_config_dir_name=str(s.get("local_config_dir_name", base.local_config_dir_name)
                                  or base.local_config_dir_name),
        trigger_research=bool(s.get("trigger_research", base.trigger_research)))


def load_mobile_intake_config(config_path: Path = Path("config.yaml")) -> MobileIntakeConfig:
    section: Mapping[str, Any] = {}
    if config_path.is_file():
        try:
            import yaml

            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            section = raw.get(CONFIG_SECTION) or {}
        except Exception:  # noqa: BLE001
            section = {}
    return config_from_mapping(section)
