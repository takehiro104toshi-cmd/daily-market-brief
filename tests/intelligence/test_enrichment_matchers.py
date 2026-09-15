"""P2-E: textmatch規則・entity/theme/eventマッチャの安全則テスト。"""
from __future__ import annotations

from src.intelligence.enrichment.entity_matcher import match_entities
from src.intelligence.enrichment.event_matcher import match_event_types, match_time_horizon
from src.intelligence.enrichment.textmatch import find_term
from src.intelligence.enrichment.theme_matcher import match_themes

from .enrichment_fixtures import catalogs


def _e(text, summary=""):
    ec, _, _ = catalogs()
    return match_entities(ec, {"headline": text, "summary": summary})


def _t(text, summary=""):
    _, tt, _ = catalogs()
    return match_themes(tt, {"headline": text, "summary": summary})


def _ev(text, summary=""):
    _, _, et = catalogs()
    return match_event_types(et, {"headline": text, "summary": summary})


class TestTextMatchRules:
    def test_uppercase_abbreviation_case_sensitive(self):
        assert find_term("The AI boom continues", "AI") == "AI"
        assert find_term("said Mr. Aiello", "AI") is None       # 語中不一致
        assert find_term("air quality improves", "AI") is None  # 小文字文脈不一致

    def test_explicit_case_marker(self):
        assert find_term("the Fed decided", "=Fed") == "Fed"
        assert find_term("he fed the dog", "=Fed") is None

    def test_word_boundary_with_periods(self):
        assert find_term("U.S. stocks rose", "U.S.") == "U.S."
        assert find_term("MUST not match", "US") is None  # 語中のUS

    def test_japanese_substring(self):
        assert find_term("日銀が利上げを見送り", "日銀") == "日銀"
        assert find_term("半導体株が上昇", "量子") is None

    def test_case_insensitive_normal_words(self):
        assert find_term("SEMICONDUCTOR sales", "semiconductor") == "SEMICONDUCTOR"


class TestEntityMatcherSafety:
    def test_safe_alias_single_match(self):
        got = [m.entity.entity_id for m in _e("Nvidia shares surge on AI demand").matches]
        assert got == ["company:nvidia"]

    def test_ambiguous_alias_without_context_not_linked(self):
        outcome = _e("Apple falls from tree in Somerset orchard")
        assert outcome.matches == ()
        assert outcome.ambiguous_skipped[0][0] == "company:apple"  # queue候補として記録

    def test_ambiguous_alias_with_context_linked(self):
        outcome = _e("Apple unveils new iPhone lineup")
        assert [m.entity.entity_id for m in outcome.matches] == ["company:apple"]
        assert outcome.matches[0].matched_via == "context_alias"

    def test_uppercase_words_never_treated_as_ticker(self):
        # AI / IT / US / CAT / ARM の裸大文字語はticker扱いされない
        outcome = _e("CAT and ARM are common words in IT news about US and AI")
        tickers = [m for m in outcome.matches if m.matched_via == "ticker_notation"]
        assert tickers == []
        assert all(m.entity.entity_id != "company:arm" for m in outcome.matches)

    def test_explicit_ticker_notation_links(self):
        outcome = _e("$NVDA jumped while NASDAQ:MSFT was flat")
        by_id = {m.entity.entity_id: m for m in outcome.matches}
        assert by_id["company:nvidia"].matched_via == "ticker_notation"
        assert by_id["company:nvidia"].evidence_text == "$NVDA"
        assert "company:microsoft" in by_id

    def test_jp_ticker_notation(self):
        outcome = _e("トヨタ自動車 (7203.T) が上昇")
        assert any(m.entity.entity_id == "company:toyota" for m in outcome.matches)

    def test_unknown_ticker_queued_not_linked(self):
        outcome = _e("$ZZZZ soared 40% today")
        assert outcome.matches == ()
        assert outcome.unknown_tickers == (("$ZZZZ", "headline"),)

    def test_country_semantic_is_subject_country(self):
        outcome = _e("Japan and China agree on trade framework")
        codes = sorted(m.value for m in outcome.matches
                       if m.dimension.value == "country")
        assert codes == ["CN", "JP"]  # 値はISOコード（subject country）

    def test_verb_fed_not_central_bank(self):
        assert _e("He fed the dog before the rate decision").matches == ()

    def test_central_bank_and_person_context(self):
        got = {m.entity.entity_id for m in
               _e("Fed holds rates steady as Powell cites inflation").matches}
        assert got == {"central_bank:fed", "person:jerome_powell"}

    def test_evidence_verbatim(self):
        m = _e("NVIDIA reported strong results").matches[0]
        assert m.evidence_text == "NVIDIA" and m.evidence_field == "headline"


class TestThemeMatcherSafety:
    def test_single_weak_keyword_never_tags(self):
        assert _t("Power outage hits the city") == ()        # "power"単独
        assert _t("The energy of the crowd was amazing") == ()

    def test_strong_signal_tags(self):
        got = [t.theme.slug for t in _t("New data center opens in Texas")]
        assert got == ["data_center"]

    def test_multi_weak_tags(self):
        matches = _t("Power grid strained by energy demand")
        slugs = {t.theme.slug for t in matches}
        assert "power" in slugs  # weak "power"+"energy" の2信号（+grid strong）
        power = [t for t in matches if t.theme.slug == "power"][0]
        assert power.strength in ("strong", "multi_weak")

    def test_exclusion_nuclear_weapons(self):
        assert all(t.theme.slug != "nuclear"
                   for t in _t("Iran nuclear program talks stall over nuclear weapons"))

    def test_nuclear_power_tags(self):
        assert any(t.theme.slug == "nuclear"
                   for t in _t("Japan restarts nuclear power plant"))

    def test_multi_label(self):
        slugs = {t.theme.slug for t in
                 _t("Nvidia earnings beat as AI chip demand surges",
                    "The semiconductor giant posted record data center revenue")}
        assert {"ai", "semiconductors", "data_center"} <= slugs

    def test_role_primary_when_strong_in_headline(self):
        m = [t for t in _t("Semiconductor stocks rally") if t.theme.slug == "semiconductors"][0]
        assert m.role == "primary"
        m2 = [t for t in _t("Markets rise", "Gains led by semiconductor makers")
              if t.theme.slug == "semiconductors"][0]
        assert m2.role == "secondary"

    def test_japanese_signals(self):
        slugs = {t.theme.slug for t in _t("日銀の利上げ観測で円高進行")}
        assert {"rates_monetary", "fx"} <= slugs


class TestEventMatcher:
    def test_rule_hits(self):
        assert [e.event_type.type_name for e in
                _ev("Toyota quarterly profit beats estimates")] == ["EARNINGS"]

    def test_no_rule_no_other(self):
        # 規則外はOTHERで埋めない（未分類のまま）
        assert _ev("Hot tubs and rosé: festival gets a luxury makeover") == ()

    def test_exclusion_product_vs_missile(self):
        assert all(e.event_type.type_name != "PRODUCT"
                   for e in _ev("North Korea launches new missile"))

    def test_multi_label_events(self):
        types = {e.event_type.type_name for e in
                 _ev("Nvidia earnings beat estimates as shares surge")}
        assert {"EARNINGS", "PRICE_MOVE"} <= types

    def test_geopolitics_excludes_trade_war(self):
        types = {e.event_type.type_name for e in
                 _ev("Trade war fears hit markets as tariffs loom")}
        assert "GEOPOLITICS" not in types

    def test_time_horizon_high_confidence_only(self):
        _, _, et = catalogs()
        assert [h.horizon for h in match_time_horizon(
            et, {"headline": "Toyota plans EV lineup by 2030"})] == ["YEARS"]
        assert match_time_horizon(et, {"headline": "Stocks rise today"}) == ()
