"""設定読み込み・出典URL管理・HTTP取得まわりの共通ユーティリティ。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
import yaml

logger = logging.getLogger("market_brief")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 market-brief-bot/1.0"
    )
}


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def safe_get(url: str, timeout: int = 10, **kwargs) -> Optional[requests.Response]:
    """公開URLへのGET。失敗時はNoneを返し、例外で処理全体を止めない。"""
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, **kwargs)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        logger.warning("取得失敗: %s (%s)", url, exc)
        return None


@dataclass(frozen=True)
class SourceRef:
    label: str
    url: str
    category: str


class SourceRegistry:
    """レポート中で参照した出典URLを、セクション11向けに重複なく記録する。"""

    def __init__(self) -> None:
        self._sources: list[SourceRef] = []

    def add(self, label: str, url: str, category: str) -> None:
        if not url:
            return
        ref = SourceRef(label=label, url=url, category=category)
        if ref in self._sources:
            return
        self._sources.append(ref)

    def all(self) -> list[SourceRef]:
        return list(self._sources)
