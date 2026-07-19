"""Article Intelligence Data Tank Consumer Client（v4.x 別リポジトリ連携）。

Data Tank（別リポジトリ・別プロジェクト）が生成した軽量な Published Intelligence
Package（manifest.json + intelligence_package.json.gz）を取得するだけの薄いクライアント。

責務: manifest取得 → package取得 → gzip展開 → checksum検証 → schema検証 →
cache保存 → timeout/retry → stale判定 → fallback → Data Quality用status生成。

設計上の安全性:
  - config.yaml の external_intelligence.manifest_url / package_url が未設定なら、
    ネットワークへは一切アクセスせず即座に disabled 状態を返す（既存動作に影響なし）。
  - 取得失敗・checksum不一致・schema不一致のいずれでも、直前キャッシュがあればそれを使い、
    無ければ None を返す（呼び出し側=main.pyは _safe_call で包み、Data Tank障害が
    レポート生成全体を止めない）。
  - 数千記事の本体は保存しない（受け取ったpackageをそのままキャッシュするだけで、
    Market Intelligence側で新たに重いDBを持たない）。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Tuple

DEFAULT_CACHE_DIR = "data/external_intelligence_cache"
REQUIRED_PACKAGE_KEYS = {
    "schema_version", "generated_at_utc", "tank_status", "hot_articles",
    "global_drivers", "market_reactions", "risk_radar", "theme_summary",
    "event_clusters", "historical_matches", "source_health", "quality",
}

Transport = Callable[[str, int], bytes]


def _default_transport(url: str, timeout: int) -> bytes:
    import requests

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _now_utc(now: Optional[datetime] = None) -> datetime:
    if now is not None:
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".ext-intel-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def validate_package_schema(package: dict) -> bool:
    return isinstance(package, dict) and REQUIRED_PACKAGE_KEYS.issubset(package.keys())


def classify_freshness(generated_at_utc: str, now: datetime, latest_minutes: int, warning_minutes: int, stale_minutes: int) -> str:
    """§15: 30分以内=latest / 30-90分=warning / 90分超=stale / 6時間超=stale（fallback候補）。"""
    try:
        generated = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "stale"
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    elapsed_minutes = max(0.0, (now - generated).total_seconds() / 60.0)
    if elapsed_minutes <= latest_minutes:
        return "latest"
    if elapsed_minutes <= warning_minutes:
        return "warning"
    return "stale"  # 90分超・6時間超とも "stale"（呼び出し側でfallback候補として扱う）


class ExternalIntelligenceClient:
    def __init__(
        self,
        config: dict,
        base_dir: Optional[Path] = None,
        transport: Optional[Transport] = None,
        now: Optional[datetime] = None,
    ):
        self.config = config or {}
        self.base_dir = Path(base_dir) if base_dir else Path(".")
        self.transport = transport or _default_transport
        self._now_override = now
        cache_dir_cfg = self.config.get("cache_dir", DEFAULT_CACHE_DIR)
        self.cache_dir = self.base_dir / cache_dir_cfg
        self.manifest_cache_path = self.cache_dir / "manifest.json"
        self.package_cache_path = self.cache_dir / "intelligence_package.json.gz"
        self.status_cache_path = self.cache_dir / "fetch_status.json"

    def _now(self) -> datetime:
        return _now_utc(self._now_override)

    def _get(self, url: str) -> bytes:
        timeout = self.config.get("timeout_seconds", 10)
        retry_count = self.config.get("retry_count", 1)
        last_exc: Optional[Exception] = None
        for _attempt in range(max(1, retry_count + 1)):
            try:
                return self.transport(url, timeout)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise last_exc  # type: ignore[misc]

    def _load_cache(self) -> Tuple[Optional[dict], Optional[str]]:
        if not (self.manifest_cache_path.exists() and self.package_cache_path.exists()):
            return None, None
        try:
            manifest = json.loads(self.manifest_cache_path.read_text(encoding="utf-8"))
            package = json.loads(gzip.decompress(self.package_cache_path.read_bytes()))
        except (OSError, json.JSONDecodeError, gzip.BadGzipFile):
            return None, None
        if not validate_package_schema(package):
            return None, None
        return package, manifest.get("generated_at") or package.get("generated_at_utc", "")

    def _save_cache(self, manifest: dict, package_bytes: bytes) -> None:
        _write_atomic(self.manifest_cache_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        _write_atomic(self.package_cache_path, package_bytes)

    def _write_status(self, status: dict) -> None:
        try:
            _write_atomic(self.status_cache_path, json.dumps(status, ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError:
            pass

    def fetch_latest_package(self) -> Tuple[Optional[dict], dict]:
        """Published Intelligence Package を取得する。戻り値: (package_or_None, status)。

        status には usage_state（latest/cached/stale/unavailable/fallback）、
        freshness_label（latest/warning/stale）、fetched_at、package_generated_at、
        schema_version、checksum、reason を含む。
        """
        now = self._now()
        manifest_url = self.config.get("manifest_url", "") or ""
        package_url = self.config.get("package_url", "") or ""
        enabled = self.config.get("enabled", True)
        cache_enabled = self.config.get("cache_enabled", True)
        fallback_to_cache = self.config.get("fallback_to_cache", True)

        base_status = {
            "fetched_at": now.isoformat(),
            "usage_state": "disabled",
            "freshness_label": "",
            "package_generated_at": "",
            "schema_version": "",
            "checksum": "",
            "reason": "",
        }

        if not enabled or not manifest_url or not package_url:
            base_status["reason"] = "not_configured"
            return None, base_status

        try:
            manifest_bytes = self._get(manifest_url)
            manifest = json.loads(manifest_bytes)
            package_bytes = self._get(package_url)
        except Exception as exc:  # noqa: BLE001
            return self._fallback(base_status, f"network_error: {exc}", cache_enabled, fallback_to_cache)

        expected_checksum = manifest.get("checksum", "")
        actual_checksum = hashlib.sha256(package_bytes).hexdigest()
        if expected_checksum and expected_checksum != actual_checksum:
            return self._fallback(base_status, "checksum_mismatch", cache_enabled, fallback_to_cache)

        try:
            package = json.loads(gzip.decompress(package_bytes))
        except (gzip.BadGzipFile, OSError, json.JSONDecodeError):
            return self._fallback(base_status, "decompress_or_json_error", cache_enabled, fallback_to_cache)

        if not validate_package_schema(package):
            return self._fallback(base_status, "schema_validation_failed", cache_enabled, fallback_to_cache)

        latest_minutes = self.config.get("latest_minutes", 30)
        warning_minutes = self.config.get("warning_minutes", 90)
        stale_minutes = self.config.get("stale_minutes", 360)
        freshness = classify_freshness(
            package.get("generated_at_utc", ""), now, latest_minutes, warning_minutes, stale_minutes
        )

        if cache_enabled:
            self._save_cache(manifest, package_bytes)

        status = {
            "fetched_at": now.isoformat(),
            "usage_state": "latest",
            "freshness_label": freshness,
            "package_generated_at": package.get("generated_at_utc", ""),
            "schema_version": package.get("schema_version", ""),
            "checksum": actual_checksum,
            "reason": "",
        }
        self._write_status(status)
        return package, status

    def _fallback(self, base_status: dict, reason: str, cache_enabled: bool, fallback_to_cache: bool) -> Tuple[Optional[dict], dict]:
        now = self._now()
        if cache_enabled and fallback_to_cache:
            package, generated_at = self._load_cache()
            if package is not None:
                latest_minutes = self.config.get("latest_minutes", 30)
                warning_minutes = self.config.get("warning_minutes", 90)
                stale_minutes = self.config.get("stale_minutes", 360)
                freshness = classify_freshness(
                    package.get("generated_at_utc", ""), now, latest_minutes, warning_minutes, stale_minutes
                )
                status = {
                    "fetched_at": now.isoformat(),
                    "usage_state": "cached" if freshness != "stale" else "stale",
                    "freshness_label": freshness,
                    "package_generated_at": package.get("generated_at_utc", ""),
                    "schema_version": package.get("schema_version", ""),
                    "checksum": "",
                    "reason": reason,
                }
                self._write_status(status)
                return package, status

        status = dict(base_status)
        status["usage_state"] = "fallback"
        status["reason"] = reason
        self._write_status(status)
        return None, status
