"""url_normalize（Phase 1-C / tank移植ロジック）の検証。"""
from __future__ import annotations

from src.intelligence.ingestion.url_normalize import normalize_url, source_domain_of


def test_strips_tracking_params_keeps_meaningful() -> None:
    url = "https://www.Example.org/a/b/?utm_source=x&utm_medium=y&id=9&fbclid=z&page=2"
    assert normalize_url(url) == "https://example.org/a/b?id=9&page=2"


def test_removes_fragment_and_sorts_query() -> None:
    assert (
        normalize_url("https://example.org/p?b=2&a=1#section")
        == "https://example.org/p?a=1&b=2"
    )


def test_folds_scheme_and_www() -> None:
    assert normalize_url("http://www.example.org/p/") == "https://example.org/p"


def test_different_articles_stay_different() -> None:
    assert normalize_url("https://e.org/articles/1") != normalize_url("https://e.org/articles/2")


def test_empty_and_domain() -> None:
    assert normalize_url("") == ""
    assert source_domain_of("https://www.Example.co.jp/x") == "example.co.jp"
    assert source_domain_of("") == ""
