"""Phase 4 P4-3a Morning Delivery packaging のテスト。

凍結済み P4-1 / P4-2 成果物を束ねるだけの層であることを見る:

    Markdown をバイト単位で運ぶ / brief・signal を再解釈しない /
    公開 JSON は監査 dump ではない（明示 key のみ・内部語彙ゼロ）/
    binding 不一致は fail closed / 同一入力 → 同一 delivery_id。

Compass pipeline の意味論も Market Signal の写像 93 件も複製しない。
"""
from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.intelligence.compass.model import QualityVerdict
from src.intelligence.reports.delivery import (
    DELIVERY_FORMATS,
    FORBIDDEN_PUBLIC_SUBSTRINGS,
    MORNING_DELIVERY_SCHEMA_VERSION,
    PUBLIC_KEYS,
    PUBLIC_SIGNAL_KEYS,
    PUBLIC_UNAVAILABLE_REASONS,
    DeliveryFormat,
    MorningDelivery,
    UnmappedDeliveryState,
    build_morning_delivery,
    canonical_delivery,
    delivery_payload,
    delivery_public_json,
    delivery_public_payload,
    make_delivery_id,
)
from src.intelligence.reports.market_signal import (
    MARKET_SIGNAL_SCHEMA_VERSION,
    SIGNAL_LEVEL_JA,
    build_market_signal,
)
from src.intelligence.reports.model import MORNING_BRIEF_SCHEMA_VERSION
from src.intelligence.reports.render_markdown import render_morning_brief_markdown
from tests.intelligence.test_market_signal import _brief as make_brief

DELIVERY_SRC = Path("src/intelligence/reports/delivery.py")
EMIT_SRC = Path("src/intelligence/reports/delivery_emit.py")

ADVICE_TOKENS = ("推奨", "買い", "売り", "目標株価", "ターゲット", "妙味", "押し目",
                 "すべきです", "おすすめ", "スタンス", "確率", "強気", "弱気")


# ---------------------------------------------------------------- helpers

def _bundle(**kwargs):
    """凍結 3 点（brief / signal / Markdown）を実 P4-1・P4-2 経路から作る。"""
    brief = make_brief(**kwargs)
    signal = build_market_signal(brief)
    markdown = render_morning_brief_markdown(brief)
    return brief, signal, markdown


def _delivery(**kwargs) -> MorningDelivery:
    brief, signal, markdown = _bundle(**kwargs)
    return build_morning_delivery(brief, signal, markdown)


def _tops(path: Path) -> set:
    tops = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.lstrip(".").split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
    return tops


# ---------------------------------------------------------------- packaging

class TestPackaging:
    """1–12。"""

    def test_builder_accepts_the_three_frozen_products(self):
        brief, signal, markdown = _bundle()
        delivery = build_morning_delivery(brief, signal, markdown)
        assert delivery.brief is brief              # 参照のまま（組み直さない）
        assert delivery.signal is signal
        assert delivery.session_date == brief.session_date
        assert delivery.reference_session == brief.reference_session

    def test_brief_object_is_unchanged(self):
        brief, signal, markdown = _bundle()
        before = brief.as_dict()
        build_morning_delivery(brief, signal, markdown)
        assert brief.as_dict() == before

    def test_signal_object_is_unchanged(self):
        brief, signal, markdown = _bundle()
        before = signal.as_dict()
        build_morning_delivery(brief, signal, markdown)
        assert signal.as_dict() == before

    def test_markdown_is_byte_identical(self):
        brief, signal, markdown = _bundle()
        delivery = build_morning_delivery(brief, signal, markdown)
        assert delivery.markdown.encode("utf-8") == markdown.encode("utf-8")
        assert delivery.markdown == markdown

    def test_markdown_sha256_is_correct(self):
        brief, signal, markdown = _bundle()
        delivery = build_morning_delivery(brief, signal, markdown)
        assert delivery.markdown_sha256 == hashlib.sha256(
            markdown.encode("utf-8")).hexdigest()

    def test_markdown_byte_count_is_correct(self):
        brief, signal, markdown = _bundle()
        delivery = build_morning_delivery(brief, signal, markdown)
        assert delivery.markdown_bytes == len(markdown.encode("utf-8"))

    def test_same_inputs_give_identical_delivery(self):
        assert _delivery() == _delivery()

    def test_same_inputs_give_identical_delivery_id(self):
        assert _delivery().delivery_id == _delivery().delivery_id

    def test_delivery_id_uses_the_shared_prefix(self):
        did = _delivery().delivery_id
        assert did.startswith("delivery_") and len(did) == len("delivery_") + 24

    @pytest.mark.parametrize("kwargs", [
        {"session_date": "2026-09-16"},
        {"reference_session": "2026-09-11"},
        {"brief_id": "brief_other"},
        {"direction": "DOWNWARD_BIAS"},
    ])
    def test_changed_identity_field_changes_delivery_id(self, kwargs):
        assert _delivery(**kwargs).delivery_id != _delivery().delivery_id

    def test_japanese_label_is_excluded_from_identity(self):
        delivery = _delivery()
        payload = delivery_payload(
            schema_version=delivery.schema_version, session_date=delivery.session_date,
            reference_session=delivery.reference_session,
            brief_id=delivery.brief.brief_id, signal_id=delivery.signal.signal_id,
            markdown_sha256=delivery.markdown_sha256,
            markdown_bytes=delivery.markdown_bytes, formats=delivery.formats)
        canonical = canonical_delivery(payload)
        for label in SIGNAL_LEVEL_JA.values():
            assert label not in canonical
        assert make_delivery_id(payload) == delivery.delivery_id

    def test_markdown_body_is_excluded_from_identity(self):
        delivery = _delivery()
        payload = delivery_payload(
            schema_version=delivery.schema_version, session_date=delivery.session_date,
            reference_session=delivery.reference_session,
            brief_id=delivery.brief.brief_id, signal_id=delivery.signal.signal_id,
            markdown_sha256=delivery.markdown_sha256,
            markdown_bytes=delivery.markdown_bytes, formats=delivery.formats)
        assert "モーニングブリーフ" not in canonical_delivery(payload)
        assert set(payload) == {"schema_version", "session_date", "reference_session",
                                "brief_id", "signal_id", "markdown_sha256",
                                "markdown_bytes", "formats"}

    def test_output_path_is_excluded_from_identity(self):
        """path も filename も同一性の材料ではない（payload に現れない）。"""
        delivery = _delivery()
        for name in ("output", "v2", "latest_morning_brief", ".md", ".json", "/"):
            assert name not in canonical_delivery(delivery_payload(
                schema_version=delivery.schema_version, session_date=delivery.session_date,
                reference_session=delivery.reference_session,
                brief_id=delivery.brief.brief_id, signal_id=delivery.signal.signal_id,
                markdown_sha256=delivery.markdown_sha256,
                markdown_bytes=delivery.markdown_bytes, formats=delivery.formats)), name

    def test_formats_are_exactly_markdown_and_json(self):
        assert _delivery().formats == DELIVERY_FORMATS
        assert DELIVERY_FORMATS == (DeliveryFormat.MARKDOWN, DeliveryFormat.JSON)
        assert {f.value for f in DeliveryFormat} == {"MARKDOWN", "JSON"}

    def test_schema_version_is_010(self):
        assert MORNING_DELIVERY_SCHEMA_VERSION == "0.1.0"
        assert _delivery().schema_version == "0.1.0"


# ---------------------------------------------------------------- fail closed

class TestBindingAndFailClosed:
    """13–17。"""

    def test_brief_id_mismatch_fails_closed(self):
        brief, signal, markdown = _bundle()
        with pytest.raises(UnmappedDeliveryState):
            build_morning_delivery(brief, replace(signal, brief_id="brief_other"), markdown)

    def test_session_date_mismatch_fails_closed(self):
        brief, signal, markdown = _bundle()
        with pytest.raises(UnmappedDeliveryState):
            build_morning_delivery(brief, replace(signal, session_date="2026-09-16"),
                                   markdown)

    def test_reference_session_mismatch_fails_closed(self):
        brief, signal, markdown = _bundle()
        with pytest.raises(UnmappedDeliveryState):
            build_morning_delivery(brief, replace(signal, reference_session="2026-09-01"),
                                   markdown)

    def test_unapproved_format_fails_closed(self):
        delivery = _delivery()
        with pytest.raises(UnmappedDeliveryState):
            replace(delivery, formats=(DeliveryFormat.MARKDOWN,))

    def test_markdown_digest_mismatch_fails_closed(self):
        delivery = _delivery()
        with pytest.raises(UnmappedDeliveryState):
            replace(delivery, markdown=delivery.markdown + "x")

    def test_markdown_byte_count_mismatch_fails_closed(self):
        delivery = _delivery()
        with pytest.raises(UnmappedDeliveryState):
            replace(delivery, markdown_bytes=delivery.markdown_bytes + 1)

    def test_malformed_digest_fails_closed(self):
        delivery = _delivery()
        with pytest.raises(UnmappedDeliveryState):
            replace(delivery, markdown_sha256="NOTAHASH")

    def test_unpublishable_unavailable_reason_fails_closed(self):
        """内部自由文の理由を配信面へ出さない。"""
        brief, signal, markdown = _bundle(direction="MIXED")
        delivery = build_morning_delivery(brief, signal, markdown)
        broken = replace(delivery, signal=replace(delivery.signal,
                                                  unavailable_reason="some_new_reason"))
        with pytest.raises(UnmappedDeliveryState):
            delivery_public_payload(broken)


# ---------------------------------------------------------------- public JSON

class TestPublicJson:
    """18–30。"""

    def test_exact_public_top_level_key_set(self):
        payload = delivery_public_payload(_delivery())
        assert tuple(payload) == PUBLIC_KEYS
        assert set(payload) == {
            "schema_version", "delivery_id", "session_date", "reference_session",
            "brief_id", "signal_id", "markdown_sha256", "markdown_bytes", "signal"}

    def test_exact_public_signal_key_set(self):
        payload = delivery_public_payload(_delivery())
        assert tuple(payload["signal"]) == PUBLIC_SIGNAL_KEYS
        assert set(payload["signal"]) == {"available", "label", "unavailable_reason"}

    def test_available_signal_exposes_only_an_approved_label(self):
        payload = delivery_public_payload(_delivery(direction="UPWARD_BIAS",
                                                    confidence="LOW"))
        assert payload["signal"]["available"] is True
        assert payload["signal"]["label"] == SIGNAL_LEVEL_JA["SLIGHT_UPWARD_LEAN"]
        assert payload["signal"]["label"] in SIGNAL_LEVEL_JA.values()

    @pytest.mark.parametrize("direction", ["MIXED", "UNCERTAIN"])
    def test_unavailable_signal_invents_no_direction(self, direction):
        payload = delivery_public_payload(_delivery(direction=direction))
        assert payload["signal"]["available"] is False
        assert payload["signal"]["label"] == ""
        assert payload["signal"]["unavailable_reason"] in PUBLIC_UNAVAILABLE_REASONS

    def test_no_internal_vocabulary_reaches_the_public_payload(self):
        for kwargs in ({}, {"direction": "DOWNWARD_BIAS", "confidence": "HIGH"},
                       {"direction": "MIXED"}, {"direction": "RANGE_BOUND",
                                                "confidence": "LOW"}):
            blob = delivery_public_json(_delivery(**kwargs))
            for forbidden in FORBIDDEN_PUBLIC_SUBSTRINGS:
                assert forbidden not in blob, (kwargs, forbidden)

    def test_raw_outlook_direction_and_confidence_and_horizon_are_absent(self):
        blob = delivery_public_json(_delivery())
        for name in ("UPWARD_BIAS", "DOWNWARD_BIAS", "RANGE_BOUND", "MIXED", "UNCERTAIN",
                     "HIGH", "MEDIUM", "LOW", "next_tokyo_session",
                     "direction", "confidence", "horizon"):
            assert name not in blob, name

    def test_principle_refs_and_raw_dimensions_are_absent(self):
        blob = delivery_public_json(_delivery())
        for name in ("JP_", "JP_DIR_001", "JP_US_001", "rule_ref", "principle_refs",
                     "nikkei_vs_topix", "nt_ratio", "japan_rates", "usd_jpy",
                     "japan_equities", "us_curve", "breadth", "turnover"):
            assert name not in blob, name

    def test_draft_package_claim_fact_context_ids_are_absent(self):
        brief, signal, markdown = _bundle()
        blob = delivery_public_json(build_morning_delivery(brief, signal, markdown))
        for name in ("draft_id", "package_id", "claim_id", "fact_id", "ctx_id",
                     brief.draft_id, brief.package_id, "compass_", "evpkg_"):
            assert name not in blob, name

    def test_audit_text_is_not_serialized(self):
        blob = delivery_public_json(_delivery())
        for name in ("text", "display_text", "tier1", "tier2", "tier3", "points",
                     "claims", "outlook", "invalidation_conditions", "abstain_reason"):
            assert name not in blob, name

    def test_public_payload_is_not_a_dataclass_dump(self):
        delivery = _delivery()
        payload = delivery_public_payload(delivery)
        assert set(payload) != set(delivery.brief.as_dict())
        assert set(payload) != set(delivery.signal.as_dict())
        assert len(json.dumps(payload)) < len(json.dumps(delivery.brief.as_dict()))

    def test_no_advice_language(self):
        for kwargs in ({}, {"direction": "MIXED"}, {"direction": "DOWNWARD_BIAS"}):
            blob = delivery_public_json(_delivery(**kwargs))
            for advice in ADVICE_TOKENS:
                assert advice not in blob, advice

    def test_no_paths_credentials_or_governance_records(self):
        blob = delivery_public_json(_delivery())
        for name in ("/", "\\", "C:", "output", ".md", ".json",
                     "decision_id", "cdc_", "record_hash", "packet_id", "candidate_id",
                     "KEEP_REVIEWING", "NOT_PROMOTED", "promotion", "replay_run_id",
                     "api_key", "sk-"):
            assert name not in blob, name

    def test_public_json_is_deterministic_and_sorted(self):
        delivery = _delivery()
        first = delivery_public_json(delivery)
        assert first == delivery_public_json(delivery)
        assert first.endswith("\n")
        assert json.loads(first) == delivery_public_payload(delivery)
        # key 順が安定（sort_keys）
        assert first.index('"brief_id"') < first.index('"delivery_id"')

    def test_public_json_keeps_japanese_readable(self):
        """ensure_ascii=False。ラベルは承認済みのものがそのまま読める形で入る。"""
        delivery = _delivery()
        blob = delivery_public_json(delivery)
        assert delivery.signal.label in SIGNAL_LEVEL_JA.values()
        assert delivery.signal.label in blob
        assert "\\u" not in blob


# ---------------------------------------------------------------- degraded

class TestDegradedStates:
    """53–56。"""

    @pytest.mark.parametrize("direction", ["MIXED", "UNCERTAIN"])
    def test_unavailable_signal_still_builds_a_valid_delivery(self, direction):
        delivery = _delivery(direction=direction)
        assert delivery.signal.available is False
        assert delivery.markdown_bytes > 0
        assert delivery.delivery_id.startswith("delivery_")

    @pytest.mark.parametrize("verdict", [QualityVerdict.ABSTAINED, QualityVerdict.REJECTED])
    def test_abstained_or_rejected_brief_is_explicit_and_safe(self, verdict):
        delivery = _delivery(verdict=verdict)
        payload = delivery_public_payload(delivery)
        assert payload["signal"]["available"] is False
        assert payload["signal"]["label"] == ""
        assert payload["signal"]["unavailable_reason"] in PUBLIC_UNAVAILABLE_REASONS
        assert delivery.markdown == render_morning_brief_markdown(delivery.brief)

    def test_degraded_dimensions_create_no_new_interpretation(self):
        base = _delivery()
        brief, signal, markdown = _bundle()
        widened = replace(brief, tier2=replace(
            brief.tier2, missing_dimensions=("japan_rates",),
            unreliable_dimensions=("usd_jpy",),
            dimension_status={"japan_rates": "MISSING", "usd_jpy": "STALE"}))
        # brief が変われば Markdown も brief_id も変わるが、公開 signal は変わらない
        other = build_morning_delivery(widened, replace(signal, brief_id=widened.brief_id),
                                       render_morning_brief_markdown(widened))
        assert (delivery_public_payload(other)["signal"]
                == delivery_public_payload(base)["signal"])

    def test_repeated_build_is_idempotent(self):
        brief, signal, markdown = _bundle()
        first = build_morning_delivery(brief, signal, markdown)
        assert first == build_morning_delivery(brief, signal, markdown)


# ---------------------------------------------------------------- boundaries

class TestBoundaries:
    """42–52（packaging 側）。"""

    def test_no_legacy_or_notifier_imports(self):
        """`LEGACY_FORBIDDEN_PREFIXES` を実 import（AST ＋ import 文）で検査する。

        散文での言及は違反ではないので、import 文の形だけを見る。
        """
        forbidden = {"notifiers", "main", "scripts", "report", "analysis", "collectors"}
        src = DELIVERY_SRC.read_text(encoding="utf-8")
        for legacy in ("src.report", "src.analysis", "src.collectors", "src.data",
                       "src.date", "notifiers", "scripts", "main"):
            assert f"import {legacy}" not in src, legacy
            assert f"from {legacy}" not in src, legacy
        assert not _tops(DELIVERY_SRC) & forbidden

    def test_no_governance_imports(self):
        forbidden = {"decision", "formal_review", "review", "shadow_review",
                     "corpus", "corpus_research", "replay", "evaluation"}
        assert not _tops(DELIVERY_SRC) & forbidden

    def test_no_phase5_imports(self):
        forbidden = {"predictions", "themes", "thesis", "screening", "personalization"}
        assert not _tops(DELIVERY_SRC) & forbidden

    def test_no_article_tank_imports(self):
        src = DELIVERY_SRC.read_text(encoding="utf-8")
        for name in ("article-intelligence-data-tank", "external_intelligence", "tank"):
            assert name not in src, name

    def test_no_llm_imports(self):
        src = DELIVERY_SRC.read_text(encoding="utf-8")
        for name in ("llm", "anthropic", "openai"):
            assert name not in src, name

    def test_no_network(self):
        src = DELIVERY_SRC.read_text(encoding="utf-8")
        for name in ("requests", "urllib", "socket", "http"):
            assert name not in src, name

    def test_packaging_module_has_no_filesystem_io(self):
        src = DELIVERY_SRC.read_text(encoding="utf-8")
        for name in ("open(", "Path(", "write_text", "write_bytes", "mkdir", "os.",
                     "tempfile", "sqlite3", "data_root", "datetime", "random", "uuid"):
            assert name not in src, name

    def test_packaging_imports_stay_inside_the_allowed_layers(self):
        allowed = {"__future__", "hashlib", "json", "re", "dataclasses", "enum",
                   "typing", "core", "market_signal", "model"}
        assert _tops(DELIVERY_SRC) <= allowed, _tops(DELIVERY_SRC) - allowed

    def test_frozen_modules_do_not_reference_delivery(self):
        for name in ("model.py", "morning_brief.py", "render_markdown.py", "pilot.py",
                     "market_signal.py", "market_signal_pilot.py"):
            src = (Path("src/intelligence/reports") / name).read_text(encoding="utf-8")
            assert "delivery" not in src, name
            assert "MorningDelivery" not in src, name

    def test_frozen_schema_versions_are_unchanged(self):
        assert MORNING_BRIEF_SCHEMA_VERSION == "0.2.0"
        assert MARKET_SIGNAL_SCHEMA_VERSION == "0.1.0"
