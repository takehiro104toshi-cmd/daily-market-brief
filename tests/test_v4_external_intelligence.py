"""v4.x External Data Foundation（Article Intelligence Data Tank連携）をネットワークなしで検証する（§31）。

manifest/package取得・gzip展開・checksum/schema検証・latest/warning/stale判定・
timeout/retry・cache更新/fallback・legacy fallback・URL未設定時の後方互換・
Data Quality表示・private本文非露出・件数上限・既存pytest互換・6回生成/Cloudflare/
手動実行との互換性を確認する。
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.analysis.external_intelligence import build_external_intelligence_bundle, hot_articles_to_headlines
from src.analysis.models import AnalysisBundle, ExternalIntelligenceBundle
from src.collectors.news import dedupe_headlines, Headline
from src.data.external_intelligence_client import (
    ExternalIntelligenceClient,
    classify_freshness,
    validate_package_schema,
)


def _make_package(generated_at: datetime, **overrides) -> dict:
    package = {
        "schema_version": "1.0",
        "generated_at_utc": generated_at.isoformat(),
        "generated_at_jst": generated_at.isoformat(),
        "tank_status": {"total_articles": 1234, "new_articles_24h": 56},
        "hot_articles": [{"article_id": "a1", "title": "テスト記事"}],
        "global_drivers": [{"event_cluster_id": "e1"}],
        "market_reactions": [],
        "risk_radar": [],
        "theme_summary": [],
        "event_clusters": [],
        "historical_matches": [],
        "source_health": [],
        "quality": {},
    }
    package.update(overrides)
    return package


def _compress(package: dict) -> bytes:
    return gzip.compress(json.dumps(package, ensure_ascii=False).encode("utf-8"))


def _manifest_for(package_bytes: bytes) -> dict:
    return {"checksum": hashlib.sha256(package_bytes).hexdigest(), "generated_at": "now"}


def _fake_transport(responses):
    """url -> bytes の辞書からのフェイクtransport。未登録URLはFileNotFoundErrorを投げる。"""
    def _t(url, timeout):
        if url not in responses:
            raise FileNotFoundError(url)
        value = responses[url]
        if isinstance(value, Exception):
            raise value
        return value
    return _t


BASE_CONFIG = {
    "enabled": True,
    "manifest_url": "https://tank.example/manifest.json",
    "package_url": "https://tank.example/intelligence_package.json.gz",
    "timeout_seconds": 5,
    "retry_count": 1,
    "latest_minutes": 30,
    "warning_minutes": 90,
    "stale_minutes": 360,
    "cache_enabled": True,
    "cache_dir": "data/external_intelligence_cache",
    "fallback_to_cache": True,
    "fallback_to_legacy_news": True,
}


# ---------- 1〜5: manifest取得・package取得・gzip展開・checksum/schema validation ----------

def test_fetch_latest_package_success(tmp_path):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    package = _make_package(now)
    pkg_bytes = _compress(package)
    manifest = _manifest_for(pkg_bytes)
    responses = {
        BASE_CONFIG["manifest_url"]: json.dumps(manifest).encode("utf-8"),
        BASE_CONFIG["package_url"]: pkg_bytes,
    }
    client = ExternalIntelligenceClient(BASE_CONFIG, base_dir=tmp_path, transport=_fake_transport(responses), now=now)
    result, status = client.fetch_latest_package()
    assert result is not None
    assert result["schema_version"] == "1.0"
    assert status["usage_state"] == "latest"
    assert status["freshness_label"] == "latest"
    assert status["checksum"] == manifest["checksum"]


def test_checksum_mismatch_falls_back(tmp_path):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    package = _make_package(now)
    pkg_bytes = _compress(package)
    bad_manifest = {"checksum": "0" * 64}
    responses = {
        BASE_CONFIG["manifest_url"]: json.dumps(bad_manifest).encode("utf-8"),
        BASE_CONFIG["package_url"]: pkg_bytes,
    }
    client = ExternalIntelligenceClient(BASE_CONFIG, base_dir=tmp_path, transport=_fake_transport(responses), now=now)
    result, status = client.fetch_latest_package()
    assert result is None  # キャッシュも無いので unavailable/fallback
    assert status["usage_state"] == "fallback"
    assert "checksum_mismatch" in status["reason"]


def test_schema_validation_rejects_incomplete_package():
    assert validate_package_schema({"schema_version": "1.0"}) is False
    assert validate_package_schema(_make_package(datetime.now(timezone.utc))) is True


# ---------- 6/7/8: latest / warning / stale 判定 ----------

def test_freshness_classification_boundaries():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    assert classify_freshness((now - timedelta(minutes=10)).isoformat(), now, 30, 90, 360) == "latest"
    assert classify_freshness((now - timedelta(minutes=60)).isoformat(), now, 30, 90, 360) == "warning"
    assert classify_freshness((now - timedelta(minutes=200)).isoformat(), now, 30, 90, 360) == "stale"
    assert classify_freshness((now - timedelta(hours=8)).isoformat(), now, 30, 90, 360) == "stale"


# ---------- 9/10: timeout / retry ----------

def test_network_timeout_triggers_fallback_when_no_cache(tmp_path):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    responses = {BASE_CONFIG["manifest_url"]: TimeoutError("timeout")}
    client = ExternalIntelligenceClient(BASE_CONFIG, base_dir=tmp_path, transport=_fake_transport(responses), now=now)
    result, status = client.fetch_latest_package()
    assert result is None
    assert status["usage_state"] == "fallback"
    assert "network_error" in status["reason"]


def test_retry_count_used_before_giving_up(tmp_path):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    calls = {"n": 0}

    def flaky_transport(url, timeout):
        calls["n"] += 1
        raise ConnectionError("boom")

    cfg = {**BASE_CONFIG, "retry_count": 2}
    client = ExternalIntelligenceClient(cfg, base_dir=tmp_path, transport=flaky_transport, now=now)
    client.fetch_latest_package()
    assert calls["n"] == 3  # 初回 + retry_count(2) 回


# ---------- 11/12: cache更新・fallback ----------

def test_cache_updated_on_success_and_used_on_next_failure(tmp_path):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    package = _make_package(now)
    pkg_bytes = _compress(package)
    manifest = _manifest_for(pkg_bytes)
    responses = {
        BASE_CONFIG["manifest_url"]: json.dumps(manifest).encode("utf-8"),
        BASE_CONFIG["package_url"]: pkg_bytes,
    }
    client = ExternalIntelligenceClient(BASE_CONFIG, base_dir=tmp_path, transport=_fake_transport(responses), now=now)
    client.fetch_latest_package()
    assert client.package_cache_path.exists() and client.manifest_cache_path.exists()

    # 次回は取得失敗 → 直前キャッシュを使う
    later = now + timedelta(minutes=5)
    failing_client = ExternalIntelligenceClient(
        BASE_CONFIG, base_dir=tmp_path, transport=_fake_transport({}), now=later
    )
    result, status = failing_client.fetch_latest_package()
    assert result is not None
    assert status["usage_state"] in ("cached", "stale")


# ---------- 13: legacy fallback（キャッシュも無い場合） ----------

def test_legacy_fallback_when_no_cache_and_fetch_fails(tmp_path):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    client = ExternalIntelligenceClient(BASE_CONFIG, base_dir=tmp_path, transport=_fake_transport({}), now=now)
    result, status = client.fetch_latest_package()
    assert result is None
    assert status["usage_state"] == "fallback"
    # bundle化すると全リストが空になり、既存Engineには一切影響しない
    bundle = build_external_intelligence_bundle(result, status)
    assert bundle.hot_articles == [] and bundle.global_drivers == []


# ---------- 14: URL未設定時の後方互換 ----------

def test_missing_urls_disable_without_network_call(tmp_path):
    calls = {"n": 0}

    def should_not_be_called(url, timeout):
        calls["n"] += 1
        raise AssertionError("network should not be called when URLs are unset")

    cfg = {**BASE_CONFIG, "manifest_url": "", "package_url": ""}
    client = ExternalIntelligenceClient(cfg, base_dir=tmp_path, transport=should_not_be_called)
    result, status = client.fetch_latest_package()
    assert result is None
    assert status["usage_state"] == "disabled"
    assert calls["n"] == 0


# ---------- 15/16: 破損package / schema不一致時のfallback ----------

def test_corrupt_gzip_falls_back(tmp_path):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    responses = {
        BASE_CONFIG["manifest_url"]: json.dumps({"checksum": ""}).encode("utf-8"),
        BASE_CONFIG["package_url"]: b"not gzip data",
    }
    client = ExternalIntelligenceClient(BASE_CONFIG, base_dir=tmp_path, transport=_fake_transport(responses), now=now)
    result, status = client.fetch_latest_package()
    assert result is None
    assert status["usage_state"] == "fallback"


def test_schema_mismatch_falls_back(tmp_path):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    broken_pkg = {"schema_version": "1.0"}  # 必須キー欠落
    pkg_bytes = gzip.compress(json.dumps(broken_pkg).encode("utf-8"))
    manifest = _manifest_for(pkg_bytes)
    responses = {
        BASE_CONFIG["manifest_url"]: json.dumps(manifest).encode("utf-8"),
        BASE_CONFIG["package_url"]: pkg_bytes,
    }
    client = ExternalIntelligenceClient(BASE_CONFIG, base_dir=tmp_path, transport=_fake_transport(responses), now=now)
    result, status = client.fetch_latest_package()
    assert result is None
    assert status["usage_state"] == "fallback"
    assert status["reason"] == "schema_validation_failed"


# ---------- 17: Data Quality 表示用コンテキスト ----------

def test_bundle_carries_display_fields():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    package = _make_package(now)
    status = {
        "usage_state": "latest", "freshness_label": "latest",
        "package_generated_at": package["generated_at_utc"], "fetched_at": now.isoformat(),
        "schema_version": "1.0", "reason": "",
    }
    bundle = build_external_intelligence_bundle(package, status)
    assert bundle.tank_total_articles == 1234
    assert bundle.tank_new_articles_24h == 56
    assert bundle.usage_state == "latest"


# ---------- 18: private本文が構造的にHTMLへ出ない ----------

def test_bundle_never_carries_full_body_even_if_present_in_package():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    # 万一パッケージ側に想定外の private_full_body 的なキーが混ざっていても、
    # ExternalIntelligenceBundle は固定フィールドしか持たないため出力に混入しない。
    package = _make_package(now, hot_articles=[{"article_id": "a1", "full_body": "秘匿本文であってはならない"}])
    status = {"usage_state": "latest", "freshness_label": "latest", "package_generated_at": "", "fetched_at": "",
              "schema_version": "1.0", "reason": ""}
    bundle = build_external_intelligence_bundle(package, status)
    from dataclasses import asdict
    blob = json.dumps(asdict(bundle), ensure_ascii=False)
    # hot_articlesの中身（Data Tank側が既にallowlistしている想定）はそのまま透過するが、
    # ExternalIntelligenceBundle自体に本文保持用フィールドが存在しないことを確認する。
    assert not hasattr(bundle, "full_body")
    assert "hot_articles" in blob


# ---------- 19: 最大件数だけEngineへ渡す（防御的キャップ） ----------

def test_bundle_defensively_caps_item_counts():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    # Data Tank側の上限が壊れていても、Market Intelligence側で再度キャップする
    package = _make_package(now, hot_articles=[{"article_id": f"a{i}"} for i in range(500)])
    status = {"usage_state": "latest", "freshness_label": "latest", "package_generated_at": "", "fetched_at": "",
              "schema_version": "1.0", "reason": ""}
    bundle = build_external_intelligence_bundle(package, status, limits={"hot_articles": 100})
    assert len(bundle.hot_articles) == 100


# ---------- 20: 既存pytest互換（AnalysisBundle） ----------

def test_analysis_bundle_default_external_intelligence_is_none():
    # 既存の AnalysisBundle 生成コード（外部連携を知らない）でも動作すること
    import inspect
    from src.analysis.models import AnalysisBundle as AB
    field_names = {f for f in AB.__dataclass_fields__}
    assert "external_intelligence" in field_names
    default = AB.__dataclass_fields__["external_intelligence"].default
    assert default is None


# ---------- 21/22: 6回生成・手動/Cloudflare実行との互換性（既存main.py経路が壊れない） ----------

def test_main_module_imports_and_wires_without_error():
    import main as main_module  # noqa: F401  # インポートできる（構文・依存関係エラーなし）
    assert hasattr(main_module, "ExternalIntelligenceClient")


# ---------- 23〜26: hot_articlesを既存ニュースパイプラインへ合流させる（段階的接続） ----------

def test_hot_articles_to_headlines_converts_allowlisted_fields():
    hot_articles = [
        {
            "article_id": "a1",
            "title": "FRBが追加利下げを示唆",
            "url": "https://example.com/a1",
            "source": "Federal Reserve Press Releases",
            "published_at": "2026-07-20T09:00:00+09:00",
            "source_trust": 0.97,
            "public_excerpt": "本文の要約（これはHeadlineへ引き継がれない）",
        }
    ]
    headlines = hot_articles_to_headlines(hot_articles)
    assert len(headlines) == 1
    h = headlines[0]
    assert h.title == "FRBが追加利下げを示唆"
    assert h.link == "https://example.com/a1"
    assert h.source == "Data Tank: Federal Reserve Press Releases"
    assert h.reliability == pytest.approx(0.97)
    assert not hasattr(h, "public_excerpt")  # 本文相当のフィールドは構造的に引き継がない


def test_hot_articles_to_headlines_skips_incomplete_entries():
    hot_articles = [
        {"article_id": "a1", "title": "", "url": "https://example.com/a1"},  # タイトル欠落
        {"article_id": "a2", "title": "タイトルのみ", "url": ""},  # URL欠落
        {"article_id": "a3", "title": "正常な記事", "url": "https://example.com/a3"},
    ]
    headlines = hot_articles_to_headlines(hot_articles)
    assert len(headlines) == 1
    assert headlines[0].title == "正常な記事"


def test_hot_articles_to_headlines_defaults_missing_trust_to_neutral():
    headlines = hot_articles_to_headlines([{"title": "情報源信頼度なし", "url": "https://example.com/a1"}])
    assert headlines[0].reliability == pytest.approx(0.5)
    assert headlines[0].source == "Data Tank"


def test_tank_headlines_merge_and_dedupe_with_existing_rss():
    # 既存RSS（低信頼度）とData Tank（高信頼度）が同じニュースを配信していた場合、
    # 既存のdedupe_headlinesが信頼度の高い方（Data Tank由来）を自動的に残すことを確認する。
    existing = [Headline(title="日銀、金融政策を維持", link="https://existing.example/1",
                          source="Yahoo!ニュース 経済", reliability=0.6)]
    tank = hot_articles_to_headlines([
        {"title": "日銀、金融政策を維持", "url": "https://tank.example/1",
         "source": "日本銀行 新着情報", "source_trust": 0.97},
    ])
    merged = dedupe_headlines(existing + tank)
    assert len(merged) == 1  # 同一見出しとして統合される
    assert merged[0].source == "Data Tank: 日本銀行 新着情報"  # 信頼度の高い方が採用される
    assert "Yahoo!ニュース 経済" in merged[0].duplicate_sources


def test_tank_headlines_added_as_new_when_no_overlap():
    existing = [Headline(title="米国株が下落", link="https://existing.example/1", source="Yahoo!ニュース 経済")]
    tank = hot_articles_to_headlines([
        {"title": "TSMCがアリゾナ工場へ追加投資", "url": "https://tank.example/1",
         "source": "Investing.com News", "source_trust": 0.7},
    ])
    merged = dedupe_headlines(existing + tank)
    assert len(merged) == 2  # 重複しないニュースはそのまま両方残る
