"""URL正規化（Phase 1-C。tank url_normalize.py の純ロジック移植）。

canonical URLは dedup・content-addressed ID の安定性のために使う。
**original_urlは必ず別途保持する**（正規化は表記ゆれ吸収であり、元表記を失わない。
呼び出し側＝feed_parser.FeedEntry が link_original / link_canonical を両方持つ）。
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "yclid", "igshid",
    "mc_cid", "mc_eid", "ref", "ref_src", "ref_url", "spm", "cmpid",
    "ito", "src", "from", "amp",
}


def _is_tracking_param(key: str) -> bool:
    lk = key.lower()
    return lk in _TRACKING_PARAMS or any(lk.startswith(p) for p in _TRACKING_PARAM_PREFIXES)


def normalize_url(raw_url: str) -> str:
    """正規化URLを返す（tank Phase 3 §12 dedup検証済みロジック）。

    - スキームをhttpsへ畳む（http/https差異で同一記事を別物にしない）
    - ホスト小文字化・先頭www.除去
    - フラグメント除去
    - トラッキングパラメータ除去（utm_* / fbclid / gclid 等）
    - 残クエリをキー順ソート・末尾スラッシュ除去

    いずれも「同一リソースの表記ゆれ」の吸収であり、異なる記事は統合しない。
    """
    if not raw_url:
        return ""
    parts = urlsplit(raw_url.strip())
    scheme = (parts.scheme or "https").lower()
    if scheme in ("http", "https"):
        scheme = "https"
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or ""
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    ]
    query_pairs.sort(key=lambda kv: kv[0])
    query = urlencode(query_pairs)
    return urlunsplit((scheme, netloc, path, query, ""))


def source_domain_of(raw_url: str) -> str:
    """URLからソースドメイン（www.除去済み小文字host）を得る。"""
    parts = urlsplit(raw_url.strip()) if raw_url else None
    if not parts or not parts.netloc:
        return ""
    host = parts.netloc.lower()
    return host[4:] if host.startswith("www.") else host
