"""Immutable Raw Store（Phase 1-C）。

構成（metadata と content blob の分離。domainへ巨大bodyを埋め込まない）:

    <root>/blobs/<hash先頭2桁>/<sha256hex>   … 生body（content-addressed・物理dedup）
    <root>/raw_items.jsonl                   … RawItemメタデータ（append-only）
    <root>/fetch_attempts.jsonl              … FetchAttempt（append-only）

保証:
- append-only / immutable … 上書きAPIを提供しない。同一URLの内容更新は新レコード
- atomic write            … blobはtempファイル→os.replace（tank cursor.pyのパターン移植）
- content hash検証        … verify_blob()で再計算照合
- duplicate-safe          … 同一hash blobは物理1つ（provenanceはRawItem/Attemptが保持）
- crash-safe              … JSONL末尾の破損行は読み飛ばして復帰（書きかけを許容する追記設計）
- 再オープン・読み戻し    … 起動時にJSONLからインデックス再構築（導出であり二重保存ではない）

既定の設置場所は data/vnext/raw/（.gitignore済み。Git tracking禁止）。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from ..core import serialization
from ..sources.model import RawItem
from .model import FetchAttempt


class BlobStore:
    """content-addressed blob格納。同一内容は物理1ファイル。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)

    def locator_for(self, content_hash: str) -> str:
        return f"blobs/{content_hash[:2]}/{content_hash}"

    def _path(self, content_hash: str) -> Path:
        return self.root / self.locator_for(content_hash)

    def store(self, body: bytes) -> Tuple[str, str, bool]:
        """body → (content_hash, locator, created)。atomic・冪等。"""
        content_hash = hashlib.sha256(body).hexdigest()
        path = self._path(content_hash)
        if path.exists():
            # 物理dedup: 既存blobを信頼しつつサイズだけ照合（破損検知）
            if path.stat().st_size != len(body):
                raise ValueError(f"blob corruption detected for {content_hash}")
            return content_hash, self.locator_for(content_hash), False
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".blob-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return content_hash, self.locator_for(content_hash), True

    def read(self, content_hash: str) -> bytes:
        return self._path(content_hash).read_bytes()

    def read_locator(self, locator: str) -> bytes:
        path = (self.root / locator).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"locator escapes store root: {locator}")
        return path.read_bytes()

    def exists(self, content_hash: str) -> bool:
        return self._path(content_hash).exists()

    def verify_blob(self, content_hash: str) -> bool:
        """格納済みblobのhash再計算照合（content hash verification）。"""
        try:
            body = self.read(content_hash)
        except FileNotFoundError:
            return False
        return hashlib.sha256(body).hexdigest() == content_hash


class JsonlRawRepository:
    """RawItem / FetchAttempt のJSONL永続化＋blob格納（RawRepository / FetchAttemptRepository充足）。

    読み込み時、JSONLの末尾破損行（クラッシュ時の書きかけ）はスキップして復帰する。
    スキップ件数は recovered_lines に記録し、silent failureにしない。
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = BlobStore(self.root)
        self._items_path = self.root / "raw_items.jsonl"
        self._attempts_path = self.root / "fetch_attempts.jsonl"
        serialization.register_domain_types()
        self._items: Dict[str, RawItem] = {}
        self._attempts: List[FetchAttempt] = []
        self.recovered_lines = 0
        self._load()

    # ---------------------------------------------------------------- 読み戻し

    def _load(self) -> None:
        for path, sink in ((self._items_path, "item"), (self._attempts_path, "attempt")):
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = serialization.decode(json.loads(line))
                    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                        self.recovered_lines += 1  # 破損行（クラッシュ書きかけ等）は読み飛ばす
                        continue
                    if sink == "item":
                        self._items[obj.raw_item_id] = obj
                    else:
                        self._attempts.append(obj)

    @staticmethod
    def _append(path: Path, obj) -> None:
        line = json.dumps(serialization.encode(obj), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ---------------------------------------------------------------- RawRepository

    def store_body(self, body: bytes) -> Tuple[str, str, bool]:
        return self.blobs.store(body)

    def add_raw_item(self, item: RawItem) -> bool:
        """追加。同一ID＋同一内容は冪等スキップ（False）。同一IDで内容差はエラー。"""
        existing = self._items.get(item.raw_item_id)
        if existing is not None:
            if serialization.encode(existing) == serialization.encode(item):
                return False
            raise ValueError(f"raw_item_id collision with different content: {item.raw_item_id}")
        self._append(self._items_path, item)
        self._items[item.raw_item_id] = item
        return True

    def get_raw_item(self, raw_item_id: str) -> Optional[RawItem]:
        return self._items.get(raw_item_id)

    def read_body(self, item: RawItem) -> bytes:
        """metadata→body lookup。storage_ref空は「原文非保存」の明示なのでエラー。"""
        if not item.storage_ref:
            raise ValueError(f"raw item has no stored body: {item.raw_item_id}")
        return self.blobs.read_locator(item.storage_ref)

    def iter_raw_items(self) -> Iterator[RawItem]:
        return iter(list(self._items.values()))

    def has_content_hash(self, content_hash: str) -> bool:
        return any(i.content_hash == content_hash for i in self._items.values())

    # ---------------------------------------------------------------- FetchAttemptRepository

    def add_attempt(self, attempt: FetchAttempt) -> bool:
        self._append(self._attempts_path, attempt)
        self._attempts.append(attempt)
        return True

    def iter_attempts(self) -> Iterator[FetchAttempt]:
        return iter(list(self._attempts))

    def attempts_for(self, source_id: str) -> Tuple[FetchAttempt, ...]:
        return tuple(a for a in self._attempts if a.source_id == source_id)

    def latest_conditional(self, endpoint_id: str) -> Tuple[str, str]:
        """条件付きGET用の (etag, last_modified) を観測列から導出する（二重保存しない）。

        直近の成立応答（200系/304）が持つvalidatorを新しい順に探す。
        """
        best: Optional[FetchAttempt] = None
        best_key: Optional[datetime] = None
        for a in self._attempts:
            if a.endpoint_id != endpoint_id:
                continue
            if not (200 <= a.status_code < 300 or a.not_modified):
                continue
            if not (a.etag or a.last_modified):
                continue
            if best_key is None or a.requested_at > best_key:
                best, best_key = a, a.requested_at
        if best is None:
            return "", ""
        return best.etag, best.last_modified
