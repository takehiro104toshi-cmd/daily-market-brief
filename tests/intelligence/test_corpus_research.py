"""Phase 3.8 Automatic Compass Corpus Analyzer のオフラインテスト（ネットワーク・LLM・credential 不使用）。

structured analysis / controlled categories / salience / explicit WHY と implicit association の分離 /
outlook direction・horizon unknown / risk / watch item / market alignment・known_at・look-ahead なし /
cross-document comparison・similarity determinism / pattern identity・evidence・lifecycle・thresholds・
regime diversity・anti-overfitting・provenance・registry / DNA comparison・conflict / benchmark / review queue /
research snapshot / incremental・full rebuild・equivalence / analyzer version・supersession・no mixing /
idempotency / intake success + research failure・retry / batch import / fixture not counted /
coverage-guided acquisition / offline / secret hygiene / no PDF tracked / no source mutation。
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.corpus.config import CorpusConfig
from src.intelligence.corpus.extraction import FakeExtractor
from src.intelligence.corpus.identity import sha256_file
from src.intelligence.corpus.intake import SOURCE_HISTORICAL_IMPORT
from src.intelligence.corpus.pipeline import ingest_path
from src.intelligence.corpus.store import CorpusStore
from src.intelligence.corpus_research import categories as cat
from src.intelligence.corpus_research import lifecycle as lc
from src.intelligence.corpus_research.acquisition import recommendations
from src.intelligence.corpus_research.batch_import import batch_import
from src.intelligence.corpus_research.benchmark import compute_benchmark
from src.intelligence.corpus_research.comparator import similar_documents, similarity
from src.intelligence.corpus_research.config import ResearchConfig, config_from_mapping, load_research_config
from src.intelligence.corpus_research.dna_comparison import (
    CONFLICT,
    EXPLAINED,
    NEW,
    NOT_COMPARABLE,
    PARTIAL,
    RuleFeatures,
    compare_pattern,
    conflict_record,
    load_rules,
)
from src.intelligence.corpus_research.engine import MODE_FULL_REBUILD, ResearchEngine
from src.intelligence.corpus_research.intake_hook import RESEARCH_ANALYSIS_FAILED, RESEARCH_OK, ResearchTrigger
from src.intelligence.corpus_research.links import EXPLICIT_CONNECTIVE, SAME_PARAGRAPH_SEQUENCE, build_links
from src.intelligence.corpus_research.outlook_model import (
    DOWN,
    H_1D,
    H_NOT_STATED,
    H_SHORT,
    MIXED,
    NOT_STATED,
    RANGE,
    UP,
    classify_direction,
    classify_horizon,
)
from src.intelligence.corpus_research.patterns import P_EVIDENCE_OUTLOOK, P_FULL, derive_assignments, pattern_id_for, PatternComponents
from src.intelligence.corpus_research.regime import MarketConnector, publication_cutoff_utc, regime_alignment
from src.intelligence.corpus_research.review_queue import K_DNA_CONFLICT, K_NEW_PATTERN, build_review_items
from src.intelligence.corpus_research.risk_model import COUNTERARGUMENT, EXPLICIT_RISK, INVALIDATION_CONDITION, NOT_RISK, WATCH_ITEM, classify_risk
from src.intelligence.corpus_research.salience import salience_profile
from src.intelligence.corpus_research.statements import build_statements
from src.intelligence.corpus_research.store import REGISTRY_FILE, SNAPSHOT_FILE, ResearchStore
from src.intelligence.corpus_research.structure import analyze_structure
from src.intelligence.corpus_research.why_model import EXPLICIT_WHY, IMPLICIT_ASSOCIATION, NO_WHY, classify_why

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "src" / "intelligence" / "corpus_research"
_spec = importlib.util.spec_from_file_location("_corpus_helpers", Path(__file__).with_name("test_compass_corpus.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
make_pdf, page1, page2, page3, page4, page5 = (_helpers.make_pdf, _helpers.page1, _helpers.page2, _helpers.page3,
                                               _helpers.page4, _helpers.page5)

NOW = datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc)
CCFG = CorpusConfig()
RCFG = ResearchConfig()
DATES = [("2026年6月18日", "18", "2026-06-18"), ("2026年6月19日", "19", "2026-06-19"), ("2026年6月22日", "22", "2026-06-22"),
         ("2026年6月23日", "23", "2026-06-23"), ("2026年6月24日", "24", "2026-06-24"), ("2026年6月25日", "25", "2026-06-25"),
         ("2026年6月26日", "26", "2026-06-26"), ("2026年6月29日", "29", "2026-06-29"), ("2026年6月30日", "30", "2026-06-30"),
         ("2026年7月1日", "1", "2026-07-01")]
CHANGES = [
    "+0.72% +7.54% +0.55% -1.49 -0.98% -1.21% -1.34% -0.050 +0.049 +0.14",   # UP / rates DOWN,UP
    "-0.90% +6.10% -0.80% +1.30 +0.50% +0.40% +0.60% +0.030 -0.040 -0.60",   # DOWN / yen stronger
    "+0.10% +7.00% +0.05% +0.20 -0.10% -0.05% +0.02% +0.000 +0.005 +0.05",   # FLAT
]
OLD_BODY = "昨晩の米国株は上昇した。夜間の日経平均先物は前日終値を上回って返ってきた。背景には金利低下があろう。"
NEW_BODY = ("昨晩の米国株は上昇した。これを受けて本日は買いが先行しよう。夜間の日経平均先物は前日終値を上回って返ってきた。"
            "背景には金利低下があろう。")


def research_pages(i: int) -> list:
    d, day, _ = DATES[i]
    p1 = page1(date_jp=d, day=day, changes=CHANGES[i % 3]).replace(OLD_BODY, NEW_BODY)
    return [p1, page2(fx=(i % 2 == 0)), page3(), page4(), page5()]


class LiveFakeExtractor(FakeExtractor):
    def __init__(self, texts: dict, version: str) -> None:
        super().__init__({}, version=version)
        self._live = texts

    def page_texts(self, path: Path) -> list:
        return list(self._live.get(str(path), self._live.get(Path(path).name, [])))

    def page_count(self, path: Path) -> int:
        return len(self.page_texts(path))


class Lab:
    def __init__(self, tmp_path: Path, config: ResearchConfig = RCFG, connector: MarketConnector = None):
        self.root = tmp_path / "root"
        self.texts = {}
        self.extractor = LiveFakeExtractor(self.texts, CCFG.extractor_version)
        self.corpus = CorpusStore(self.root / "corpus")
        self.research = ResearchStore(self.root / "research")
        self.connector = connector or MarketConnector()
        self.config = config
        self.engine = ResearchEngine(self.corpus, self.research, config, CCFG, self.connector)
        self.docs = []

    def add(self, i: int, name: str = "", **ingest_kw) -> str:
        name = name or f"doc{i}.pdf"
        self.texts[name] = research_pages(i)
        r = ingest_path(self.corpus, make_pdf(self.root / "src" / name, name), config=CCFG, extractor=self.extractor,
                        now=NOW, source_type=SOURCE_HISTORICAL_IMPORT, **ingest_kw)
        self.docs.append(r.document_id)
        return r.document_id

    def run(self, minutes: int = 0):
        return self.engine.run_incremental(NOW + timedelta(minutes=minutes))

    def structures(self):
        return self.research.current_structures(self.config.version_key)

    def close(self):
        self.corpus.close()


# ============================================================ categories / statements / salience / links / why

def test_controlled_categories():
    assert cat.primary_category("日銀の金融政策決定会合に注目") == cat.CENTRAL_BANK
    assert cat.primary_category("半導体株の物色の広がり") == cat.BREADTH          # 優先順: 何を見たか
    assert cat.categorize("ドル円は160円台") == (cat.FX,)
    assert cat.primary_category("特に材料はない一日だった") == cat.OTHER
    assert cat.primary_category("") == cat.UNKNOWN
    assert set(cat.CATEGORIES) >= {"JAPAN_EQUITY", "US_EQUITY", "FX", "JAPAN_RATES", "US_RATES", "BREADTH", "TURNOVER",
                                   "SECTOR", "SIZE", "FLOW", "MACRO", "CENTRAL_BANK", "EARNINGS", "THEME", "EVENT",
                                   "VALUATION", "TECHNICAL", "OTHER", "UNKNOWN"}


def _statements(tmp_path):
    lab = Lab(tmp_path)
    doc = lab.add(0)
    record = lab.corpus.current_analysis(doc)
    artifacts = lab.corpus.artifacts_for(doc)
    return lab, build_statements(record, artifacts)


def test_statements_and_salience_not_word_count(tmp_path):
    lab, statements = _statements(tmp_path)
    assert statements and all(s.order == i for i, s in enumerate(statements))
    headline = [s for s in statements if s.headline]
    assert len(headline) == 3
    links = build_links(statements)
    profile = salience_profile(statements, links, "【半導体関連に注目】")
    assert profile[0].rank == 1 and profile[0].score >= profile[-1].score
    top = {c.category for c in profile[:3]}
    assert cat.SECTOR in top or cat.US_EQUITY in top                     # 見出し・専用段落が効く
    longest = max(statements, key=lambda s: len(s.text))
    assert profile[0].category in (cat.SECTOR, cat.US_EQUITY, cat.JAPAN_EQUITY, cat.CENTRAL_BANK)
    assert all("repetition" in c.signals for c in profile) and "word_count" not in profile[0].signals
    lab.close()


def test_links_and_why_separation(tmp_path):
    lab, statements = _statements(tmp_path)
    links = build_links(statements)
    why = classify_why(statements, links)
    types = {w.why_type for w in why}
    assert EXPLICIT_WHY in types and (IMPLICIT_ASSOCIATION in types or NO_WHY in types)
    explicit = [w for w in why if w.why_type == EXPLICIT_WHY]
    assert explicit[0].connective and explicit[0].evidence_observation_id
    assert {l.basis for l in links} <= {EXPLICIT_CONNECTIVE, SAME_PARAGRAPH_SEQUENCE}
    by_obs = {s.observation_id: s for s in statements if s.observation_id}
    for l in links:                                                       # 同一段落内だけ
        assert by_obs[l.source_observation_id].artifact_id == by_obs[l.target_observation_id].artifact_id
    lab.close()


# ============================================================ outlook / risk

def test_outlook_direction_and_horizon_not_invented():
    assert classify_direction("本日は底堅い展開を想定する") == UP
    assert classify_direction("反落を想定する") == DOWN
    assert classify_direction("狭いレンジでの推移となろう") == RANGE
    assert classify_direction("上昇後に下落する場面もありそうだ") == MIXED
    assert classify_direction("注目したい") == NOT_STATED
    assert classify_horizon("本日は底堅い") == H_1D and classify_horizon("目先のドル円") == H_SHORT
    assert classify_horizon("底堅い展開を想定する") == H_NOT_STATED


def test_risk_types_and_not_all_negative_is_risk():
    assert classify_risk("上値追いには警戒が必要だ") == EXPLICIT_RISK
    assert classify_risk("もっとも、利食い売りが重しとなる") == COUNTERARGUMENT
    assert classify_risk("25日線を割り込めば調整が深まる") == INVALIDATION_CONDITION
    assert classify_risk("決算の内容が注目される") == WATCH_ITEM
    assert classify_risk("日経平均は下落した") == NOT_RISK


def test_structure_fields_and_no_text(tmp_path):
    lab = Lab(tmp_path)
    doc = lab.add(0)
    st = analyze_structure(lab.corpus, doc, RCFG, MarketConnector(), NOW)
    d = st.as_dict()
    for key in ("document_id", "document_date", "quality", "market_state", "selected_evidence", "main_theme",
                "supporting_themes", "interpretations", "why_links", "outlook", "risk", "watch_items",
                "coverage_labels", "market_alignment", "pattern_assignments", "field_support"):
        assert key in d
    assert d["outlook_summary"]["primary_direction"] == UP and d["outlook_summary"]["primary_target"] == cat.JAPAN_EQUITY
    assert d["why_summary"][EXPLICIT_WHY] >= 1 and d["field_support"]["why_links"]
    assert d["watch_items"] and d["risk_summary"]["primary_type"] in (COUNTERARGUMENT, EXPLICIT_RISK)
    blob = json.dumps(d, ensure_ascii=False)
    assert "底堅い展開" not in blob and '"text"' not in blob                    # 本文を複製しない
    assert st.structure_id.startswith("crs_") and st.version_key == RCFG.version_key
    lab.close()


# ============================================================ market alignment / known_at / look-ahead

def test_regime_alignment_prefers_context_and_rejects_look_ahead(tmp_path):
    days = ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"]
    cutoff = publication_cutoff_utc("2026-06-18")
    assert cutoff.isoformat().startswith("2026-06-17T22:30")               # 07:30 JST
    rows = [
        {"context_type": "index_direction", "subject_id": "index:topix.close.closing.tokyo", "direction": "DOWN",
         "known_at": "2026-06-17T07:00:00+00:00", "context_id": "ctx_ok"},
        {"context_type": "breadth_state", "subject_id": "market:tse_prime", "direction": "UP",
         "known_at": "2026-06-18T05:00:00+00:00", "context_id": "ctx_late"},          # cutoff 後 → 捨てる
        {"context_type": "fx_direction", "subject_id": "fx:USDJPY.rate.closing.global", "direction": "UP",
         "known_at": "2026-06-17T21:00:00+00:00", "context_id": "ctx_fx"},
    ]
    connector = MarketConnector(trading_days=days, context_rows=lambda s: rows if s == "2026-06-17" else [],
                                market_lookup=lambda series, session: Decimal("69902.25") if "nikkei" in series else None)
    lab = Lab(tmp_path, connector=connector)
    doc = lab.add(0, trading_days=days, market_lookup=connector.market_value)
    st = analyze_structure(lab.corpus, doc, RCFG, connector, NOW).as_dict()
    r = st["regime"]
    assert r["referenced_session"] == "2026-06-17" and r["session_basis"] == "CALENDAR"
    assert r["labels"]["equity_direction"] == "DOWN" and r["sources"]["equity_direction"] == "CONTEXT"   # 紙面 UP より Context
    assert r["labels"]["breadth_state"] == "UNKNOWN" and r["look_ahead_rejected"] == 1
    assert r["labels"]["yen_direction"] == "YEN_WEAKER" and r["context_dimensions"] == 2
    assert st["market_alignment"]["comparable_values"] >= 1 and st["field_support"]["market_alignment"]
    assert r["regime_key"] != "regime:UNKNOWN"
    lab.close()


def test_connector_without_stores_reports_unavailable(tmp_path):
    c = MarketConnector(tmp_path)
    assert c.availability["calendar"] is False and c.availability["context"] is False
    assert c.referenced_session("2026-06-18") == ("UNKNOWN", "NO_CALENDAR")
    assert c.context_labels("2026-06-17", None) == {}


# ============================================================ similarity

def test_similarity_is_deterministic_and_explainable(tmp_path):
    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    lab.run()
    s = lab.structures()
    a, b, c = (s[d] for d in lab.docs)
    r1, r2 = similarity(a, b), similarity(a, b)
    assert r1.as_dict() == r2.as_dict() and similarity(b, a).score == r1.score
    assert r1.method_version == RCFG.similarity_version and 0 <= r1.score <= 1
    assert set(r1.shared_features).isdisjoint(set(r1.different_features))
    same = similarity(a, a)
    assert same.score == Decimal("1.000")
    rows = lab.research.similarities_current(RCFG.similarity_version)
    assert len(rows) == 3
    top = similar_documents(lab.docs[0], [similarity(s[x], s[y]) for x, y in [(lab.docs[0], lab.docs[1]), (lab.docs[0], lab.docs[2])]],
                            top_k=3, min_score=Decimal("0"))
    assert top and all("shared_features" in t and "method_version" in t for t in top)
    lab.close()


# ============================================================ patterns / lifecycle / anti-overfitting

def test_pattern_identity_and_assignments(tmp_path):
    lab = Lab(tmp_path)
    doc = lab.add(0)
    st = analyze_structure(lab.corpus, doc, RCFG, MarketConnector(), NOW).as_dict()
    a1 = derive_assignments(st, evidence_categories=2)
    a2 = derive_assignments(st, evidence_categories=2)
    assert [a.assignment_id for a in a1] == [a.assignment_id for a in a2]
    types = {a.pattern_type for a in a1}
    assert P_EVIDENCE_OUTLOOK in types and P_FULL in types
    full = [a for a in a1 if a.pattern_type == P_FULL][0]
    assert full.evidence_refs and full.components["outlook"] and full.components["market_state"]
    comp = PatternComponents(P_EVIDENCE_OUTLOOK, (), ("US_EQUITY",), "", "", ("dir=UP", "target=JAPAN_EQUITY"), "")
    assert pattern_id_for(comp) == pattern_id_for(comp) and pattern_id_for(comp, "2.0.0") != pattern_id_for(comp)
    for ref in full.evidence_refs:
        assert lab.corpus.provenance_chain(ref)["document"]["document_id"] == doc     # provenance
    lab.close()


def _assign(doc, date, regime, quality="VALID", eligible=True):
    return {"document_id": doc, "document_date": date, "regime_key": regime, "quality": quality, "eligible": eligible,
            "pattern_id": "cpt_x", "pattern_type": "EVIDENCE_OUTLOOK", "components": {}, "evidence_refs": ["o1"]}


def test_lifecycle_thresholds_regime_diversity_and_ceiling():
    th = RCFG.thresholds()
    one = lc.support_profile([_assign("a", "2026-06-18", "regime:1")])
    assert lc.lifecycle_status(one, th) == lc.OBSERVED
    two = lc.support_profile([_assign("a", "2026-06-18", "regime:1"), _assign("b", "2026-06-19", "regime:1")])
    assert lc.lifecycle_status(two, th) == lc.NEW_PATTERN_CANDIDATE
    three_same = lc.support_profile([_assign(d, "2026-06-%02d" % (18 + i), "regime:1") for i, d in enumerate("abc")])
    assert lc.lifecycle_status(three_same, th) == lc.NEW_PATTERN_CANDIDATE            # regime 1 つでは昇格しない
    three_div = lc.support_profile([_assign("a", "2026-06-18", "regime:1"), _assign("b", "2026-07-01", "regime:2"),
                                    _assign("c", "2026-07-20", "regime:2")])
    assert lc.lifecycle_status(three_div, th) == lc.REVIEW_CANDIDATE
    strong = lc.support_profile([_assign(d, f"2026-0{6 + i // 2}-{10 + i:02d}", f"regime:{i % 3}") for i, d in enumerate("abcdef")])
    strong = dataclasses.replace(strong, span_days=120)
    assert lc.lifecycle_status(strong, th) == lc.STRONG_PATTERN_CANDIDATE
    weak_quality = dataclasses.replace(strong, valid_ratio=Decimal("0.5"))
    assert lc.lifecycle_status(weak_quality, th) == lc.REVIEW_CANDIDATE                 # quality も要件
    assert lc.APPROVED not in lc.PHASE_38_ALLOWED and lc.PHASE_38_MAX_STATUS == lc.STRONG_PATTERN_CANDIDATE
    lim = lc.limitations(three_same, eligible_corpus=10, corpus_span_days=13, thresholds=th)
    assert any(l.startswith("CORPUS_SIZE") for l in lim) and any(l.startswith("SINGLE_REGIME") for l in lim)
    assert any(l.startswith("NOT_PREDICTIVE") for l in lim) and any(l.startswith("SHORT_SPAN") for l in lim)


def test_pattern_registry_is_research_evidence_not_production(tmp_path):
    rules_before = sha256_file(REPO_ROOT / "knowledge" / "compass_dna" / "market_rules.yaml")
    principles_before = sha256_file(REPO_ROOT / "src" / "intelligence" / "compass" / "market_principles.py")
    lab = Lab(tmp_path)
    for i in range(4):
        lab.add(i)
    lab.run()
    registry = json.loads((lab.research.root / REGISTRY_FILE).read_text(encoding="utf-8"))
    assert registry["is_production_rule_source"] is False and registry["patterns"]
    rec = registry["patterns"][0]
    for key in ("pattern_id", "pattern_version", "supporting_document_ids", "support_count", "date_range",
                "regime_coverage", "components", "evidence_references", "quality", "first_seen", "last_seen",
                "status", "limitations"):
        assert key in rec
    assert all(r["status"] in lc.PHASE_38_ALLOWED for r in registry["patterns"])
    assert max(r["support_count"] for r in registry["patterns"]) >= 2
    assert sha256_file(REPO_ROOT / "knowledge" / "compass_dna" / "market_rules.yaml") == rules_before
    assert sha256_file(REPO_ROOT / "src" / "intelligence" / "compass" / "market_principles.py") == principles_before
    lab.close()


# ============================================================ DNA comparison / conflicts

def test_dna_comparison_classifications_and_conflict_record():
    rule = RuleFeatures("R1", "us_sets_jp", ("US_EQUITY",), ("JAPAN_EQUITY",), "UP", "1d", "confirmed")
    up = {"evidence": ["US_EQUITY"], "outlook": ["dir=UP", "target=JAPAN_EQUITY"], "theme": ""}
    down = {"evidence": ["US_EQUITY"], "outlook": ["dir=DOWN", "target=JAPAN_EQUITY"], "theme": ""}
    assert compare_pattern("p1", up, [rule]).classification == EXPLAINED
    c = compare_pattern("p2", down, [rule])
    assert c.classification == CONFLICT and c.direction_relation == "OPPOSITE"
    assert compare_pattern("p3", {"evidence": ["US_EQUITY"], "outlook": [], "theme": ""}, [rule]).classification == PARTIAL
    assert compare_pattern("p4", {"evidence": ["FLOW"], "outlook": ["dir=UP", "target=SECTOR"], "theme": ""}, [rule]).classification == NEW
    assert compare_pattern("p5", {"evidence": [], "outlook": [], "theme": ""}, [rule]).classification == NOT_COMPARABLE
    rec = conflict_record(c, {"supporting_document_ids": ["d1"], "regime_coverage": ["regime:1"], "evidence_references": ["o1"]})
    assert rec["rule_id"] == "R1" and rec["supporting_document_ids"] == ["d1"] and "neither side" in rec["decision"]
    rules = load_rules(REPO_ROOT / "knowledge" / "compass_dna" / "market_rules.yaml")
    assert len(rules) == 13 and all(r.rule_id for r in rules)
    assert compare_pattern("p6", up, rules).classification in (EXPLAINED, PARTIAL, NEW, CONFLICT)


# ============================================================ benchmark / review queue / snapshot

def test_benchmark_metrics_and_boundary(tmp_path):
    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    lab.run()
    bench = lab.research.rows("benchmarks")[-1]
    m = bench["metrics"]
    assert m["documents"] == 3 and m["outlook_direction_coverage"] == "1.000" and m["why_explicit_coverage"] == "1.000"
    assert m["category_extraction_agreement"] == "1.000" and m["pattern_assignment_stability"] == "1.000"
    assert m["market_alignment_coverage"] == "0.000" and m["context_regime_coverage"] == "0.000"
    assert "precision" not in json.dumps(m) and "recall" not in json.dumps(m)
    assert "not market forecasting accuracy" in bench["boundary"]
    lab.close()


def test_review_queue_requires_supervisor(tmp_path):
    lab = Lab(tmp_path)
    for i in range(4):
        lab.add(i)
    lab.run()
    items = lab.research.review_items()
    assert items and all(it["requires_supervisor"] and not it["auto_approval"] and it["status"] == "OPEN" for it in items)
    kinds = {it["kind"] for it in items}
    assert K_NEW_PATTERN in kinds
    ids = [it["review_id"] for it in items]
    assert len(ids) == len(set(ids))
    lab.run(1)
    assert len(lab.research.review_items()) == len(items)                          # idempotent
    dna = build_review_items(pattern_records={}, conflicts=[{"conflict_id": "c1", "pattern_id": "p", "rule_id": "R", "evidence_references": []}],
                             structures={}, now=NOW)
    assert dna[0]["kind"] == K_DNA_CONFLICT and dna[0]["rule_id"] == "R"
    lab.close()


def test_research_snapshot_contents(tmp_path):
    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    lab.run()
    snap = json.loads((lab.research.root / SNAPSHOT_FILE).read_text(encoding="utf-8"))
    for key in ("corpus_count", "eligible_count", "date_range", "milestone", "coverage", "analyzer_versions",
                "patterns_by_status", "top_supported_candidates", "new_candidates", "conflicts", "similar_documents",
                "benchmark", "review_queue", "limitations", "acquisition_recommendations"):
        assert key in snap
    assert snap["patterns_by_status"]["APPROVED"] == 0 and snap["max_status_allowed_in_phase_3_8"] == lc.STRONG_PATTERN_CANDIDATE
    assert any(l.startswith("CORPUS_SIZE") for l in snap["limitations"])
    lab.close()


def test_coverage_guided_acquisition():
    report = {"dimensions": {"yen_direction": {"counts": {"YEN_WEAKER": 1}}},
              "missing_regimes": ["yen_direction=YEN_STRONGER", "breadth_state=BROAD"],
              "underrepresented_regimes": ["yen_direction=YEN_WEAKER"]}
    recs = recommendations(report)
    assert recs[0]["priority"] == "HIGH" and recs[0]["label"] == "YEN_STRONGER" and "円高" in recs[0]["description_ja"]
    assert any(r["priority"] == "DATA_SUPPLY" for r in recs) and any(r["priority"] == "MEDIUM" and r["current_count"] == 1 for r in recs)
    assert all(r["kind"] == "research_acquisition" for r in recs)


# ============================================================ incremental / rebuild / versions / idempotency

def test_incremental_update_touches_only_affected(tmp_path):
    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    r1 = lab.run()
    assert len(r1.new_documents) == 3 and r1.similarities_added == 3
    lab.add(3)
    r2 = lab.run(1)
    assert r2.new_documents == [lab.docs[3]] and r2.structures_added == 1 and r2.similarities_added == 3
    assert r2.assignments_added >= 1 and r2.affected_patterns >= r2.pattern_records_added >= 1
    assert len(lab.structures()) == 4
    lab.close()


def test_full_rebuild_equals_incremental(tmp_path):
    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    lab.run()
    lab.add(3)
    lab.run(1)
    rebuilt, report = lab.engine.run_full_rebuild(lab.root / "rebuild", NOW + timedelta(minutes=2))
    assert report.mode == MODE_FULL_REBUILD and report.structures_added == 4
    eq = lab.engine.equivalence(rebuilt)
    assert eq["equal"] and eq["differing_sections"] == [] and eq["structures"] == 4
    lab.close()


def test_idempotent_rerun_adds_nothing(tmp_path):
    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    r1 = lab.run()
    before = lab.research.counts()
    r2 = lab.run(1)
    after = lab.research.counts()
    assert r2.structures_added == 0 and r2.similarities_added == 0 and r2.assignments_added == 0
    assert r2.pattern_records_added == 0 and r2.review_items_added == 0 and not r2.benchmark_added
    assert {k: v for k, v in after.items() if k != "runs"} == {k: v for k, v in before.items() if k != "runs"}
    assert r1.digest == r2.digest
    lab.close()


def test_new_analyzer_version_appends_and_never_mixes(tmp_path):
    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    lab.run()
    old_structs = dict(lab.structures())
    bumped = dataclasses.replace(RCFG, pattern_version="1.0.1", salience_version="1.1.0")
    engine2 = ResearchEngine(lab.corpus, lab.research, bumped, CCFG, lab.connector)
    r = engine2.run_incremental(NOW + timedelta(minutes=1))
    assert r.structures_added == 3                                                    # 新 version set で再解析
    assert lab.research.current_structures(RCFG.version_key) == old_structs             # 旧結果は保持
    new = lab.research.current_structures(bumped.version_key)
    assert set(new) == set(old_structs) and all(s["versions"]["salience_version"] == "1.1.0" for s in new.values())
    assert lab.research.pattern_records_current(RCFG.pattern_version)                  # 旧 registry も残る
    assert all(rec["pattern_version"] == "1.0.1" for rec in lab.research.pattern_records_current("1.0.1").values())
    state = lab.research.state()["analyzed"]
    assert RCFG.version_key in state and bumped.version_key in state
    lab.close()


# ============================================================ intake integration / failure isolation / batch

def test_intake_success_with_research_failure_and_bounded_retry(tmp_path):
    lab = Lab(tmp_path)
    doc = lab.add(0)
    calls = []

    class Boom:
        def run_incremental(self, now=None):
            calls.append(1)
            raise RuntimeError("boom")

    trig = ResearchTrigger(lambda: Boom(), max_attempts=2, ledger_dir=lab.research.root)
    out = trig.on_corpus_ingested(doc, NOW)
    assert out["corpus"] == "CORPUS_SUCCESS" and out["research"] == RESEARCH_ANALYSIS_FAILED
    assert out["attempts"] == 2 == len(calls) and out["error_type"] == "RuntimeError"
    assert lab.corpus.document(doc) is not None and lab.corpus.current_status(doc) == "ANALYZED"   # roll back しない
    assert (lab.research.root / "research_failures.jsonl").exists()
    ok = ResearchTrigger(lambda: lab.engine, max_attempts=2).on_corpus_ingested(doc, NOW)
    assert ok["research"] == RESEARCH_OK and ok["attempts"] == 1
    lab.close()


def test_processor_hook_boundary_keeps_corpus_result(tmp_path):
    from src.intelligence.mobile_intake import adapters
    from src.intelligence.mobile_intake.config import MobileIntakeConfig
    from src.intelligence.mobile_intake.local_config import LocalConfig
    from src.intelligence.mobile_intake.processor import InboxProcessor

    lab = Lab(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    lab.texts["phone.pdf"] = research_pages(1)
    p = make_pdf(inbox / "phone.pdf", "phone")
    import os
    ts = NOW.timestamp() - 100
    os.utime(p, (ts, ts))
    local = LocalConfig(home=tmp_path / "home", inbox_dir=inbox, data_root=lab.root, provider=adapters.LOCAL_FOLDER)
    seen = []

    def failing_hook(document_id):
        seen.append(document_id)
        raise RuntimeError("research down")

    proc = InboxProcessor(MobileIntakeConfig(sample_interval_seconds=0.0), local, CCFG, lab.corpus, lab.extractor,
                          sleeper=lambda s: None, post_ingest=failing_hook)
    report = proc.run_once(NOW)
    res = report.results[0]
    assert res.result == "SUCCESS" and res.research["research"] == RESEARCH_ANALYSIS_FAILED and seen
    assert lab.corpus.document(res.document_id) is not None
    text = (PKG.parent / "mobile_intake" / "adapters.py").read_text(encoding="utf-8")
    assert "corpus_research" not in text                                              # adapter は research を知らない
    lab.close()


def test_batch_import_dedup_bounded_and_failure_isolated(tmp_path, monkeypatch):
    lab = Lab(tmp_path)
    src = tmp_path / "batch"
    for i in range(3):
        name = f"hist{i}.pdf"
        lab.texts[name] = research_pages(i)
        make_pdf(src / name, name)
    (src / "junk.pdf").write_bytes(b"not pdf")
    dup = src / "hist0_copy.pdf"
    dup.write_bytes((src / "hist0.pdf").read_bytes())
    lab.texts["hist0_copy.pdf"] = research_pages(0)
    progress = []
    report = batch_import(src, lab.corpus, corpus_config=CCFG, extractor=lab.extractor, max_files=10, now=NOW,
                          on_progress=lambda i, n, name: progress.append(name), research_engine=lab.engine)
    assert report.scanned == 5 and report.added == 3 and report.duplicates == 1 and report.failed == 1
    assert report.research["structures_added"] == 3 and len(progress) == 5
    bounded = batch_import(src, lab.corpus, corpus_config=CCFG, extractor=lab.extractor, max_files=2, now=NOW)
    assert bounded.processed == 2 and bounded.skipped_over_limit == 3
    import src.intelligence.corpus_research.batch_import as bi

    def explode(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(bi, "ingest_path", explode)
    isolated = batch_import(src, lab.corpus, corpus_config=CCFG, extractor=lab.extractor, max_files=10, now=NOW)
    assert isolated.errors == 5 and isolated.processed == 5                            # 1 件の失敗が batch を止めない
    lab.close()


def test_fixture_run_does_not_touch_real_corpus_or_research(tmp_path):
    import shutil

    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    lab.run()
    real_digest = lab.research.digest(RCFG.version_key, RCFG.pattern_version, RCFG.similarity_version)
    real_docs = len(lab.corpus.documents())
    lab.corpus.close()
    shutil.copytree(lab.root / "corpus", tmp_path / "fx" / "corpus")
    shutil.copytree(lab.root / "research", tmp_path / "fx" / "research")
    corpus_fx = CorpusStore(tmp_path / "fx" / "corpus")
    research_fx = ResearchStore(tmp_path / "fx" / "research")
    lab.texts["FIXTURE.pdf"] = research_pages(3)
    ingest_path(corpus_fx, make_pdf(tmp_path / "FIXTURE.pdf", "fixture"), config=CCFG, extractor=lab.extractor, now=NOW,
                source_type=SOURCE_HISTORICAL_IMPORT)
    ResearchEngine(corpus_fx, research_fx, RCFG, CCFG, MarketConnector()).run_incremental(NOW + timedelta(minutes=1))
    corpus_fx.close()
    lab.corpus = CorpusStore(lab.root / "corpus")
    assert len(lab.corpus.documents()) == real_docs
    assert ResearchStore(lab.root / "research").digest(RCFG.version_key, RCFG.pattern_version, RCFG.similarity_version) == real_digest
    lab.close()


# ============================================================ security / offline / config

def test_research_package_offline_secret_free_and_no_pdf_tracked():
    bad = []
    for py in sorted(PKG.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for tok in ("import " + "requests", "import " + "urllib", "from " + "urllib", "import " + "socket",
                    "open" + "ai", "anthro" + "pic", "sentence_" + "transformers", "import " + "torch",
                    "API" + "_KEY", "os." + "environ", "getenv" + "(", "date/" + "rashinban", "research/" + "source_docs"):
            if tok in text:
                bad.append(f"{py.name}:{tok}")
    assert bad == []
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert not [l for l in tracked.splitlines() if l.lower().endswith(".pdf")]
    section = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8").split("compass_research:")[1]
    assert "token" not in section.lower() and "key:" not in section.lower()


def test_engine_runs_with_network_disabled_and_keeps_sources(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    lab = Lab(tmp_path)
    doc = lab.add(0)
    before = sha256_file(lab.root / "src" / "doc0.pdf")
    lab.run()
    assert sha256_file(lab.root / "src" / "doc0.pdf") == before
    src_doc = lab.corpus.document(doc)
    from src.intelligence.corpus.source import verify_original
    assert verify_original(lab.corpus.root, src_doc.storage_locator, src_doc.sha256)
    lab.close()


def test_config_section_loads():
    cfg = load_research_config(REPO_ROOT / "config.yaml")
    assert cfg.pattern_version == "1.0.0" and cfg.strong_support == 5 and cfg.corpus_size_caveat_below == 30
    assert cfg.thresholds()["review_candidate"]["regimes"] == 2
    assert config_from_mapping({"new_candidate_support": 1}).new_candidate_support == 2         # 1 観測で候補にしない
    assert len(cfg.version_key.split("|")) == 10


def test_pilot_offline_on_synthetic_corpus(tmp_path, monkeypatch, capsys):
    from src.intelligence.corpus_research import pilot

    src = tmp_path / "src"
    texts = {}
    for i in range(4):
        name = f"doc{i}.pdf"
        make_pdf(src / name, name)
        texts[name] = research_pages(i)
    texts["FIXTURE_resaved_issue.pdf"] = research_pages(3)
    monkeypatch.setattr(pilot, "PypdfExtractor", lambda version: FakeExtractor(texts, version=version))
    monkeypatch.setattr(pilot, "_resave_pdf", lambda s, d: make_pdf(d, "fixture-bytes"))
    monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path / "prod"))
    rc = pilot.main(["--source", str(src), "--root", str(tmp_path / "pilot_root")])
    out = capsys.readouterr().out
    assert rc == 0
    markers = [m for m in ("P38_INPUT", "P38_CONNECTOR", "P38_RUN", "P38_STRUCTURES", "P38_ALIGNMENT", "P38_PATTERNS",
                           "P38_SIMILARITY", "P38_DNA", "P38_BENCHMARK", "P38_REVIEW_QUEUE", "P38_ACQUISITION",
                           "P38_SNAPSHOT", "P38_IDEMPOTENCY", "P38_N1_FIXTURE", "P38_REBUILD", "P38_VERSION",
                           "P38_FAILURE_ISOLATION", "P38_SECURITY", "P38_SUMMARY") if f"::{m}::" in out]
    assert len(markers) == 19
    summary = json.loads(out.split("::P38_SUMMARY::")[1].splitlines()[0])
    for key in ("idempotent", "n1_incremental_ok", "rebuild_equivalent", "version_isolation", "failure_isolated"):
        assert summary[key], key
    assert summary["real_documents"] == 4
    n1 = json.loads(out.split("::P38_N1_FIXTURE::")[1].splitlines()[0])
    assert n1["fixture_is_real_corpus"] is False and n1["real_corpus_count_unchanged"] == 4 and n1["corpus_count_fixture_root"] == 5
    assert not (tmp_path / "prod" / "compass_research").exists()
    assert "底堅い展開を想定する" not in out
