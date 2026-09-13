"""ID戦略（Phase 1-A）。決定理由: docs/evidence/PROVENANCE_MODEL.md §ID戦略。

方式の使い分け（比較検討の結論）:
- **ULID**（時刻順ソート可能・26文字Crockford Base32・stdlibのみで実装可）
  → システムが生成するレコード: Statement / Observation / EvidenceLink。
    UUIDv7と同等の時刻順性を持ち、Python 3.11 stdlibにuuid7が無いためULIDを採用。
- **content-addressed ID**（sha256先頭24hex）
  → 取得物の同一性が内容で決まるもの: SourceDocument / RawItem。
    同じ内容を再取得してもIDが一致し、Phase 2のdedup（tank資産）へ直結する。
- **人間可読slug**
  → Source（情報源カタログのキー。knowledge/source_feeds.yaml の id と一致させる）。

prefixでドメインを識別する: doc_ / raw_ / fact_ / ana_ / fcst_ / obs_ / link_
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(now: Optional[datetime] = None) -> str:
    """ULID（48bit ms timestamp + 80bit random、26文字）を生成する。

    now を注入すればテストで時刻順を決定的に検証できる（乱数部は残る）。
    """
    ts_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000) & ((1 << 48) - 1)
    value = (ts_ms << 80) | secrets.randbits(80)
    chars = []
    for i in range(26):
        chars.append(_CROCKFORD[(value >> (5 * (25 - i))) & 31])
    return "".join(chars)


def new_id(prefix: str, now: Optional[datetime] = None) -> str:
    """時刻順ID: 例 fact_01K3W2... / obs_01K3W2..."""
    return f"{prefix}_{new_ulid(now)}"


def content_id(prefix: str, *parts: str) -> str:
    """内容アドレスID: 同一内容→同一ID（dedup readiness）。

    partsは同一性を定義する正規化済み文字列（例: source_id, locator, content_hash）。
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def sha256_hex(data: bytes) -> str:
    """RawItem/SourceDocumentのcontent_hash用。"""
    return hashlib.sha256(data).hexdigest()
