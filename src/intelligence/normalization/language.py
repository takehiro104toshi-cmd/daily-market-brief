"""言語正規化（Phase 1-D）。BCP-47系の小文字表現へ決定論的に統一する。

証拠源はdeterministicなもののみ（source registryのdefault・XML/HTTPメタデータ）。
言語判定モデルは使わない。不明はBCP-47の未確定タグ "und" を返す。
"""
from __future__ import annotations

#: 主要primary subtag（プロジェクトの情報源で実際に現れうるもの）
_KNOWN_PRIMARY = {
    "ja", "en", "de", "fr", "zh", "es", "it", "ko", "pt", "ru", "ar", "hi", "nl",
}

_ALIASES = {
    "jp": "ja",       # 慣用ミス
    "jpn": "ja",
    "eng": "en",
    "zh-cn": "zh-hans",
    "zh-tw": "zh-hant",
}

UNKNOWN_LANGUAGE = "und"  # BCP-47 undetermined


def normalize_language(value: str) -> str:
    """言語表記をBCP-47系小文字へ正規化する。判定できなければ "und"。"""
    v = (value or "").strip().lower().replace("_", "-")
    if not v:
        return UNKNOWN_LANGUAGE
    v = _ALIASES.get(v, v)
    primary = v.split("-", 1)[0]
    primary = _ALIASES.get(primary, primary)
    if primary not in _KNOWN_PRIMARY:
        return UNKNOWN_LANGUAGE
    if "-" in v:
        rest = v.split("-", 1)[1]
        return f"{primary}-{rest}"
    return primary
