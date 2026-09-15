"""text/language正規化（Phase 1-D）: deterministic・意味を書き換えない。"""
from __future__ import annotations

from src.intelligence.normalization.language import normalize_language
from src.intelligence.normalization.text import (
    content_fingerprint,
    normalize_text,
    normalize_title,
)


def test_title_html_entities_and_whitespace() -> None:
    assert normalize_title("Fed &amp; markets　 rally\n now") == "Fed & markets rally now"


def test_title_unicode_nfc() -> None:
    # 結合文字（か+゛）→ 合成済み「が」（NFC）
    assert normalize_title("株価が上昇") == "株価が上昇"


def test_title_meaning_preserved_no_truncation() -> None:
    t = "日銀、政策金利を0.25%引き上げ　円は147円台へ"
    assert normalize_title(t) == "日銀、政策金利を0.25%引き上げ 円は147円台へ"  # 全角空白のみ正規化


def test_text_line_endings_and_blank_lines() -> None:
    raw = "line1\r\nline2\r\rline3\n\n\n\nline4   spaced"
    assert normalize_text(raw) == "line1\nline2\n\nline3\n\nline4 spaced"


def test_fingerprint_absorbs_minor_markup_differences() -> None:
    a = content_fingerprint("Fed &amp; Markets", "Some  summary\r\nhere")
    b = content_fingerprint("Fed & Markets", "Some summary\nhere")
    assert a == b  # minor markup差分は同一fingerprint


def test_fingerprint_distinguishes_content_changes() -> None:
    a = content_fingerprint("BOJ holds rates", "")
    b = content_fingerprint("BOJ raises rates", "")
    assert a != b  # 意味の異なる内容は別fingerprint（semantic統合はしない）


def test_language_normalization() -> None:
    assert normalize_language("ja") == "ja"
    assert normalize_language("JP") == "ja"
    assert normalize_language("en-US") == "en-us"
    assert normalize_language("zh-CN") == "zh-hans"
    assert normalize_language("") == "und"
    assert normalize_language("xx") == "und"  # 不明はundetermined（推測しない）
