"""テキスト正規化（Phase 1-D）。安全なdeterministic処理のみ。

許可: Unicode正規化（NFC）・HTMLエンティティ復号・改行/空白正規化。
禁止: 要約・翻訳・意味変更・投資判断の付与（INTERPRETED層はP1-E以降）。
"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata

_WS_RE = re.compile(r"[ \t 　]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_title(text: str) -> str:
    """タイトル正規化: NFC＋エンティティ復号＋空白畳み込み。意味は書き換えない。翻訳禁止。"""
    if not text:
        return ""
    t = html.unescape(text)
    t = unicodedata.normalize("NFC", t)
    t = _WS_RE.sub(" ", t.replace("\r\n", " ").replace("\r", " ").replace("\n", " "))
    return t.strip()


def normalize_text(text: str) -> str:
    """本文/summary正規化: NFC＋改行統一（LF）＋行内空白畳み込み＋過剰空行削減。

    raw textはblob/FeedEntry.raw_xml側に無傷で残る（ここは派生値）。
    """
    if not text:
        return ""
    t = html.unescape(text)
    t = unicodedata.normalize("NFC", t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS_RE.sub(" ", line).strip() for line in t.split("\n")]
    t = "\n".join(lines)
    t = _MULTI_NEWLINE_RE.sub("\n\n", t)
    return t.strip()


def content_fingerprint(title: str, summary: str = "") -> str:
    """normalized content fingerprint（sha256 hex）。

    用途: 同一記事がminor markup差分（空白・エンティティ・改行）で再配信された場合の
    比較（tank content_hashの概念移植）。**semantic dedupではない**（Phase 2）。
    raw content hash（バイト同一性）とは別物として保持する。
    """
    basis = normalize_title(title).lower() + "\x1f" + normalize_text(summary).lower()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
