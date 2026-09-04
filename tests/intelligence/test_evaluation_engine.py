"""Phase 3.9.2 Evaluation Engine（frozen 6 axis / Reference Score / Recommendation）。

必須 25 ケース: axis 分類・構造的 N/A・contradiction 派生・score 再正規化と NOT_COMPARABLE floor・
recommendation precedence・孤立矛盾では reject しない・outlook-free / FULL は approve できない・
shadow APPROVE 可・Decision を書かない・policy drift fail closed・replay 決定性・dry-run 無書き込み・
source research artifact 不変・decision store 不変。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.corpus.identity import sha256_file
from src.intelligence.evaluation import axes as ax
from src.intelligence.evaluation import config as cfg
from src.intelligence.evaluation import models as md
from src.intelligence.evaluation import rules as rl
from src.intelligence.evaluation.contradiction import build_contradiction_index
from src.intelligence.evaluation.engine import EvaluationEngine
from src.intelligence.evaluation.score import reference_score
from src.intelligence.evaluation.store import EvaluationStore, evaluation_root

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "src" / "intelligence" / "evaluation"
DNA_FILES = (REPO_ROOT / "knowledge" / "compass_dna" / "market_rules.yaml",
             REPO_ROOT / "src" / "intelligence" / "compass" / "market_principles.py")
NOW = datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc)
EP, RP = cfg.EvaluationPolicy(), cfg.RecommendationPolicy()


def doc(day: int, equity="UP", yen="FLAT", us_rate="UP", direction="UP", quality="VALID", eligible=True,
        month=6, schema="1.0.0", analysis="1.0.0"):
    date = f"2026-{month:02d}-{day:02d}"
    return {"document_id": f"cmp_{month:02d}{day:02d}", "document_date": date, "created_at": date + "T00:00:00+00:00",
            "market_state": {"equity_direction": equity, "yen_direction": yen, "us_rate_direction": us_rate},
            "outlook_summary": {"primary_direction": direction}, "quality": quality, "eligible": eligible,
            "schema_version": schema, "corpus_analysis_version": analysis}


def pattern(pid, ptype="EVIDENCE_OUTLOOK", docs=(), support=None, span=0, direction="UP", evidence=("MACRO", "FX"),
            target="JAPAN_EQUITY", theme="", risk="", why="", valid_ratio="1.00", status="OBSERVED",
            eligible_support=None):
    outlook = ([f"dir={direction}"] if direction else []) + ([f"target={target}"] if target else [])
    n = support if support is not None else len(docs)
    return {"pattern_id": pid, "pattern_version": "1.0.0", "pattern_type": ptype,
            "components": {"pattern_type": ptype, "market_state": [], "evidence": list(evidence), "theme": theme,
                           "why": why, "outlook": outlook, "risk": risk},
            "supporting_document_ids": [d["document_id"] for d in docs],
            "support_count": n, "eligible_support": n if eligible_support is None else eligible_support,
            "regime_count": n, "span_days": span, "valid_ratio": valid_ratio, "status": status,
            "first_seen": docs[0]["document_date"] if docs else "", "last_seen": docs[-1]["document_date"] if docs else "",
            "date_range": [docs[0]["document_date"], docs[-1]["document_date"]] if docs else ["", ""],
            "evidence_references": [], "limitations": []}


class Lab:
    """synthetic Phase 3.8 research root（実 artifact と同じ file 名・field）。"""

    def __init__(self, tmp_path: Path, eligible=10, milestone="CORPUS_10"):
        self.root = tmp_path / "root"
        self.research = self.root / "compass_research"
        self.research.mkdir(parents=True)
        self.docs, self.patterns, self.comparisons, self.conflicts = [], [], [], []
        self.corpus_state = {"eligible": eligible, "milestone": milestone}
        self.ticks = 0

    def add_docs(self, *docs):
        self.docs.extend(docs)
        return docs

    def add(self, rec, comparison=None, conflicts=0):
        self.patterns.append(rec)
        self.comparisons.append(dict({"pattern_id": rec["pattern_id"], "classification": "PARTIALLY_EXPLAINED",
                                      "evidence_overlap": ["MACRO"], "target_match": False,
                                      "direction_relation": "UNKNOWN", "candidate_rule_ids": ["r1"]},
                                     **(comparison or {})))
        for i in range(conflicts):
            self.conflicts.append({"conflict_id": f"c{len(self.conflicts)}", "pattern_id": rec["pattern_id"]})
        return rec

    def flush(self):
        def w(name, rows):
            (self.research / name).write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        w("patterns.jsonl", self.patterns)
        w("structures.jsonl", self.docs)
        w("dna_comparisons.jsonl", self.comparisons)
        w("conflicts.jsonl", self.conflicts)

    def clock(self):
        self.ticks += 1
        return NOW + timedelta(seconds=self.ticks)

    def engine(self, ep=EP, rp=RP, lookup=None):
        self.flush()
        return EvaluationEngine(self.research, EvaluationStore(evaluation_root(self.root)), ep, rp,
                                corpus_state=self.corpus_state, decision_state_lookup=lookup, clock=self.clock)

    def run(self, dry_run=False, **kw):
        return self.engine(**kw).evaluate_all(dry_run=dry_run)

    def by_id(self, records):
        return {r.pattern_id: r for r in records}


# ============================================================ 1-3 axis states

def test_1_evidence_strength_bands(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(*[doc(8 + i) for i in range(5)])
    for pid, n in (("cpt_low", 1), ("cpt_med2", 2), ("cpt_med3", 3), ("cpt_high", 4)):
        lab.add(pattern(pid, docs=d[:n]))
    got = {k: v.axis_states["evidence_strength"] for k, v in lab.by_id(lab.run(dry_run=True)[1]).items()}
    assert got == {"cpt_low": "LOW", "cpt_med2": "MEDIUM", "cpt_med3": "MEDIUM", "cpt_high": "HIGH"}
    assert ax.evidence_strength(pattern("x", eligible_support=9), EP).state == "HIGH"


def test_2_full_evidence_strength_not_applicable(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8))
    lab.add(pattern("cpt_full", ptype="FULL", docs=d))
    rec = lab.run(dry_run=True)[1][0]
    assert rec.axis_applicability["evidence_strength"] == md.NOT_APPLICABLE
    assert rec.axis_states["evidence_strength"] == "LOW"                      # 4 つ目の state は作らない
    assert "SUPPORT_NOT_RANKED" in rec.axis_reasons["evidence_strength"]
    assert rec.axis_metrics["evidence_strength"]["support_ranked"] is False


def test_3_time_stability_bands(tmp_path):
    lab = Lab(tmp_path)
    a, b = lab.add_docs(doc(8, month=6), doc(9, month=6))
    c = lab.add_docs(doc(10, month=7))[0]
    e = lab.add_docs(doc(11, month=8))[0]
    lab.add(pattern("cpt_low_span", docs=[a, b], span=1))
    lab.add(pattern("cpt_low_month", docs=[a, b], span=40))                   # span 十分でも 1 か月なら LOW
    lab.add(pattern("cpt_medium", docs=[a, c], span=30))
    lab.add(pattern("cpt_high", docs=[a, c, e], span=61))
    got = {k: v.axis_states["time_stability"] for k, v in lab.by_id(lab.run(dry_run=True)[1]).items()}
    assert got == {"cpt_low_span": "LOW", "cpt_low_month": "LOW", "cpt_medium": "MEDIUM", "cpt_high": "HIGH"}


# ============================================================ 4-6 cross-regime

def test_4_unknown_regime_documents_are_excluded(tmp_path):
    lab = Lab(tmp_path)
    known = lab.add_docs(doc(8, equity="UP"), doc(9, equity="DOWN", month=7))
    unknown = lab.add_docs(doc(10, equity="UNKNOWN", month=8), doc(11, yen="UNKNOWN", month=8))
    lab.add(pattern("cpt_x", docs=list(known) + list(unknown), span=61))
    rec = lab.run(dry_run=True)[1][0]
    m = rec.axis_metrics["cross_regime"]
    assert m["documents_counted"] == 2 and m["documents_excluded_unknown"] == 2
    assert m["distinct_2d_cells"] == 2 and rec.axis_states["cross_regime"] == "MEDIUM"   # UNKNOWN は regime ではない


def test_5_cross_regime_high_gate(tmp_path):
    lab = Lab(tmp_path)
    cells = [doc(8, equity="UP", month=6), doc(9, equity="UP", month=6),
             doc(10, equity="DOWN", month=7), doc(11, equity="DOWN", month=7),
             doc(12, equity="FLAT", month=8)]
    lab.add_docs(*cells)
    lab.add(pattern("cpt_gate", docs=cells, span=61))                          # 3 cells + confirmed + support/span
    lab.add(pattern("cpt_no_confirm", docs=[cells[0], cells[2], cells[4]], span=61))   # 3 cells, confirmed 0
    lab.add(pattern("cpt_short", docs=cells, span=10))                         # span 不足
    got = lab.by_id(lab.run(dry_run=True)[1])
    assert got["cpt_gate"].axis_states["cross_regime"] == "HIGH"
    assert got["cpt_gate"].axis_metrics["cross_regime"]["confirmed_2d_cells"] == 2
    assert got["cpt_no_confirm"].axis_states["cross_regime"] == "LOW"           # cell 数だけでは HIGH にしない
    assert got["cpt_short"].axis_states["cross_regime"] == "LOW"
    assert got["cpt_gate"].confirmation_3d["role"] == "SECONDARY_CONFIRMATION_ONLY"


def test_6_full_and_state_outlook_cross_regime_not_applicable(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8), doc(9, equity="DOWN", month=7))
    lab.add(pattern("cpt_full", ptype="FULL", docs=d, span=40))
    lab.add(pattern("cpt_state", ptype="STATE_OUTLOOK", docs=d, span=40, evidence=()))
    lab.add(pattern("cpt_eo", docs=d, span=40))
    got = lab.by_id(lab.run(dry_run=True)[1])
    assert got["cpt_full"].axis_applicability["cross_regime"] == md.NOT_APPLICABLE
    assert got["cpt_state"].axis_applicability["cross_regime"] == md.NOT_APPLICABLE
    assert got["cpt_eo"].axis_applicability["cross_regime"] == md.APPLICABLE
    assert "REGIME_BEARING_IDENTITY" in got["cpt_state"].axis_reasons["cross_regime"]


# ============================================================ 7-9 consistency

def test_7_narrow_contradiction_only_marks_committed_directions(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8), doc(9, month=7))
    up = lab.add(pattern("cpt_up", docs=d, direction="UP", span=40))
    down = lab.add(pattern("cpt_down", docs=d, direction="DOWN", span=40))
    lab.add(pattern("cpt_range", docs=d, direction="RANGE", span=40))          # 同 group だが巻き込まない
    lab.add(pattern("cpt_other", docs=d, direction="UP", evidence=("SECTOR",), span=40))
    index = build_contradiction_index(lab.patterns, EP, RP.reject_min_sibling_support)
    assert index.narrow_sibling == {"cpt_up", "cpt_down"} and index.conflicting_groups == 1
    assert index.narrow_sibling_repeated == {"cpt_up", "cpt_down"}             # 双方 support 2
    got = lab.by_id(lab.run(dry_run=True)[1])
    assert got["cpt_up"].axis_states["evidence_consistency"] == "LOW"
    assert got["cpt_range"].axis_states["evidence_consistency"] == "MEDIUM"
    assert got["cpt_other"].axis_states["evidence_consistency"] == "HIGH"


def test_8_supporting_document_up_down_contradiction(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8, direction="UP"), doc(9, direction="DOWN", month=7))
    lab.add(pattern("cpt_why", ptype="EVIDENCE_WHY", docs=d, direction="", target="", why="EXPLICIT_WHY", span=40))
    rec = lab.run(dry_run=True)[1][0]
    assert rec.axis_states["evidence_consistency"] == "LOW"
    assert rec.axis_reasons["evidence_consistency"] == "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION"
    assert rec.axis_metrics["evidence_consistency"]["contradiction_repeated"] is False   # 各 1 件のみ


def test_9_non_directional_and_soft_direction_capped_at_medium(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8), doc(9, month=7))
    lab.add(pattern("cpt_why", ptype="EVIDENCE_WHY", docs=d, direction="", target="", why="NO_WHY", span=40))
    lab.add(pattern("cpt_risk", ptype="EVIDENCE_RISK", docs=d, direction="", target="", risk="EXPLICIT_RISK", span=40))
    lab.add(pattern("cpt_range", docs=d, direction="RANGE", span=40))
    soft = lab.add_docs(doc(12, direction="RANGE", month=8))
    lab.add(pattern("cpt_soft", docs=list(d) + list(soft), direction="UP", span=61))
    got = lab.by_id(lab.run(dry_run=True)[1])
    for pid in ("cpt_why", "cpt_risk", "cpt_range", "cpt_soft"):
        assert got[pid].axis_states["evidence_consistency"] == "MEDIUM", pid
    assert got["cpt_why"].axis_metrics["evidence_consistency"]["direction_class"] == "NON_DIRECTIONAL"
    assert got["cpt_range"].axis_metrics["evidence_consistency"]["direction_class"] == "CONDITIONAL_DIRECTIONAL"
    assert got["cpt_soft"].axis_reasons["evidence_consistency"] == "DIRECTION_SOFTENED"


# ============================================================ 10 novelty

def test_10_dna_novelty_applicability_and_bands(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8))
    lab.add(pattern("cpt_state", ptype="STATE_OUTLOOK", docs=d, evidence=()))                    # evidence 無し
    lab.add(pattern("cpt_why", ptype="EVIDENCE_WHY", docs=d, direction="", target=""))           # target 無し
    lab.add(pattern("cpt_low", docs=d), comparison={"classification": "EXPLAINED_BY_EXISTING_RULE"})
    lab.add(pattern("cpt_low2", docs=d), comparison={"evidence_overlap": ["MACRO"], "target_match": True,
                                                     "direction_relation": "CONDITIONAL"})
    lab.add(pattern("cpt_med", docs=d))
    lab.add(pattern("cpt_high", docs=d), comparison={"classification": "NEW_PATTERN_CANDIDATE",
                                                     "evidence_overlap": [], "candidate_rule_ids": []})
    got = lab.by_id(lab.run(dry_run=True)[1])
    assert got["cpt_state"].axis_applicability["dna_novelty"] == md.NOT_APPLICABLE
    assert got["cpt_why"].axis_applicability["dna_novelty"] == md.NOT_APPLICABLE
    assert [got[p].axis_states["dna_novelty"] for p in ("cpt_low", "cpt_low2", "cpt_med", "cpt_high")] == \
        ["LOW", "LOW", "MEDIUM", "HIGH"]
    assert got["cpt_high"].axis_metrics["dna_novelty"]["candidate_rule_count"] == 0


# ============================================================ 11 data quality

def test_11_data_quality_high_medium_low(tmp_path):
    lab = Lab(tmp_path)
    ok = lab.add_docs(doc(8), doc(9, month=7))
    partial = lab.add_docs(doc(10, quality="PARTIAL", month=8))
    limited = lab.add_docs(doc(11, quality="LIMITED_USE", month=8))
    bad_version = lab.add_docs(doc(12, analysis="9.9.9", month=8))
    lab.add(pattern("cpt_high", docs=ok, span=40))
    lab.add(pattern("cpt_partial", docs=list(ok) + list(partial), span=40))
    lab.add(pattern("cpt_ratio", docs=ok, span=40, valid_ratio="0.90"))
    lab.add(pattern("cpt_elig", docs=ok, span=40, eligible_support=1))
    lab.add(pattern("cpt_limited", docs=list(ok) + list(limited), span=40))
    lab.add(pattern("cpt_lowratio", docs=ok, span=40, valid_ratio="0.50"))
    lab.add(pattern("cpt_version", docs=list(ok) + list(bad_version), span=40))
    unresolved = pattern("cpt_missing", docs=ok, span=40)
    unresolved["supporting_document_ids"] = unresolved["supporting_document_ids"] + ["cmp_absent"]
    lab.add(unresolved)
    got = {k: v.axis_states["data_quality"] for k, v in lab.by_id(lab.run(dry_run=True)[1]).items()}
    assert got["cpt_high"] == "HIGH"
    assert got["cpt_partial"] == got["cpt_ratio"] == got["cpt_elig"] == "MEDIUM"
    assert got["cpt_limited"] == got["cpt_lowratio"] == got["cpt_version"] == got["cpt_missing"] == "LOW"


def test_11b_market_alignment_absence_is_not_a_defect(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8))                                   # market_alignment を一切持たない structure
    lab.add(pattern("cpt_x", docs=d))
    rec = lab.run(dry_run=True)[1][0]
    assert rec.axis_states["data_quality"] == "HIGH"
    assert rec.axis_metrics["data_quality"]["market_alignment_absent_by_design"] is True


# ============================================================ 12-13 reference score

def test_12_score_renormalises_over_applicable_axes(tmp_path):
    axes = {cfg.A_STRENGTH: md.AxisResult(cfg.A_STRENGTH, "HIGH"),
            cfg.A_TIME: md.AxisResult(cfg.A_TIME, "HIGH"),
            cfg.A_CROSS: md.AxisResult(cfg.A_CROSS, "LOW", md.NOT_APPLICABLE),
            cfg.A_CONSISTENCY: md.AxisResult(cfg.A_CONSISTENCY, "HIGH"),
            cfg.A_NOVELTY: md.AxisResult(cfg.A_NOVELTY, "MEDIUM", md.NOT_APPLICABLE)}
    score, comparable, applicable, wsum = reference_score(axes, EP)
    assert wsum == 70 and set(applicable) == {cfg.A_STRENGTH, cfg.A_TIME, cfg.A_CONSISTENCY}
    assert comparable and score == 100.0                        # N/A は減点にならない（tautological LOW を課さない）
    axes[cfg.A_CROSS] = md.AxisResult(cfg.A_CROSS, "LOW")
    score2, _, _, wsum2 = reference_score(axes, EP)
    assert wsum2 == 90 and score2 < 100.0                       # applicable な LOW は当然減点になる


def test_13_score_not_comparable_below_floor(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8))
    lab.add(pattern("cpt_full", ptype="FULL", docs=d))
    rec = lab.run(dry_run=True)[1][0]
    assert rec.applicable_weight_sum == 50 and rec.reference_score_comparable is False
    assert rec.reference_score is None                          # 薄い score を権威に見せない
    assert rec.recommendation != md.NOT_READY                   # ただし評価自体は有効
    assert any(l.startswith("REFERENCE_SCORE_NOT_COMPARABLE") for l in rec.limitations)
    profiles = {"EVIDENCE_OUTLOOK": 100, "THEME_OUTLOOK": 100, "EVIDENCE_WHY": 90,
                "EVIDENCE_RISK": 90, "STATE_OUTLOOK": 70, "FULL": 50}
    lab2 = Lab(tmp_path / "b")
    d2 = lab2.add_docs(doc(8))
    for t in profiles:
        lab2.add(pattern(f"cpt_{t}", ptype=t, docs=d2, evidence=() if t == "STATE_OUTLOOK" else ("MACRO", "FX"),
                         direction="" if t in ("EVIDENCE_WHY", "EVIDENCE_RISK") else "UP",
                         target="" if t in ("EVIDENCE_WHY", "EVIDENCE_RISK") else "JAPAN_EQUITY"))
    got = lab2.by_id(lab2.run(dry_run=True)[1])
    assert {t: got[f"cpt_{t}"].applicable_weight_sum for t in profiles} == profiles


# ============================================================ 14-16 recommendation rules

def approvable(lab, pid="cpt_ok", ptype="EVIDENCE_OUTLOOK", **kw):
    """3 cells + confirmed + span 61 + 3 months + committed direction + all VALID の approve 可能 pattern。"""
    cells = [doc(8, equity="UP", month=6), doc(9, equity="UP", month=6),
             doc(10, equity="DOWN", month=7), doc(11, equity="DOWN", month=7),
             doc(12, equity="FLAT", month=8)]
    lab.add_docs(*cells)
    return lab.add(pattern(pid, ptype=ptype, docs=cells, span=61, status="REVIEW_CANDIDATE", **kw))


def test_14_recommendation_precedence_and_states(tmp_path):
    lab = Lab(tmp_path)
    approvable(lab, "cpt_approve")
    bad = lab.add_docs(doc(20, quality="LIMITED_USE", month=8))
    lab.add(pattern("cpt_not_ready", docs=bad, span=61))
    lab.add(pattern("cpt_keep", docs=lab.add_docs(doc(21, month=8)), span=0))
    d = lab.add_docs(doc(22, month=6), doc(23, month=7))
    lab.add(pattern("cpt_review", ptype="EVIDENCE_WHY", docs=d, direction="", target="", why="NO_WHY", span=40))
    got = lab.by_id(lab.run(dry_run=True)[1])
    assert got["cpt_not_ready"].recommendation == md.NOT_READY
    assert got["cpt_approve"].recommendation == md.APPROVE_RECOMMENDED
    assert got["cpt_review"].recommendation == md.REVIEW_RECOMMENDED
    assert got["cpt_keep"].recommendation == md.KEEP_REVIEWING
    assert got["cpt_keep"].blocking_rules                       # なぜ上位に届かなかったかを必ず残す
    assert RP.precedence == ("NOT_READY", "REJECT_RECOMMENDED", "APPROVE_RECOMMENDED",
                             "REVIEW_RECOMMENDED", "KEEP_REVIEWING")


def test_15_isolated_contradiction_never_rejects(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8, direction="UP"), doc(9, direction="DOWN", month=7),
                     doc(10, direction="UP", month=8), doc(11, direction="UP", month=8))
    lab.add(pattern("cpt_iso", ptype="EVIDENCE_RISK", docs=d, direction="", target="", risk="EXPLICIT_RISK", span=61))
    rec = lab.run(dry_run=True)[1][0]
    assert rec.axis_states["evidence_consistency"] == "LOW" and rec.axis_states["evidence_strength"] == "HIGH"
    assert rec.recommendation == md.KEEP_REVIEWING             # DOWN が 1 件だけ = 孤立矛盾
    assert rl.B_CONTRADICTION_NOT_REPEATED in rec.blocking_rules


def test_16_repeated_contradiction_can_reject(tmp_path):
    lab = Lab(tmp_path)
    d = lab.add_docs(doc(8, direction="UP"), doc(9, direction="UP", month=6),
                     doc(10, direction="DOWN", month=7), doc(11, direction="DOWN", month=8))
    lab.add(pattern("cpt_rej", ptype="EVIDENCE_WHY", docs=d, direction="", target="", why="NO_WHY", span=61))
    rec = lab.run(dry_run=True)[1][0]
    assert rec.axis_metrics["evidence_consistency"]["contradiction_repeated"] is True
    assert rec.recommendation == md.REJECT_RECOMMENDED
    assert rec.triggered_rule == rl.R_REJECT
    weak = Lab(tmp_path / "w")
    d2 = weak.add_docs(doc(8, direction="UP"), doc(9, direction="DOWN", month=7))
    weak.add(pattern("cpt_weak", ptype="EVIDENCE_WHY", docs=d2, direction="", target="", why="NO_WHY", span=40))
    assert weak.run(dry_run=True)[1][0].recommendation == md.KEEP_REVIEWING   # support 不足では reject しない


# ============================================================ 17-19 approval policy

def test_17_outlook_free_types_cannot_approve_but_can_review(tmp_path):
    lab = Lab(tmp_path)
    approvable(lab, "cpt_why", ptype="EVIDENCE_WHY", direction="", target="", why="EXPLICIT_WHY")
    approvable(lab, "cpt_risk", ptype="EVIDENCE_RISK", direction="", target="", risk="EXPLICIT_RISK")
    got = lab.by_id(lab.run(dry_run=True)[1])
    for pid in ("cpt_why", "cpt_risk"):
        assert got[pid].recommendation == md.REVIEW_RECOMMENDED
        assert rl.B_TYPE_NOT_ELIGIBLE in got[pid].blocking_rules
        assert got[pid].axis_states["evidence_consistency"] == "MEDIUM"


def test_18_full_cannot_approve(tmp_path):
    lab = Lab(tmp_path)
    approvable(lab, "cpt_full", ptype="FULL")
    rec = lab.run(dry_run=True)[1][0]
    assert rec.recommendation != md.APPROVE_RECOMMENDED
    assert rl.B_TYPE_NOT_ELIGIBLE in rec.blocking_rules


def test_19_shadow_approve_recommended_is_allowed_and_labelled(tmp_path):
    lab = Lab(tmp_path, eligible=55, milestone="CORPUS_50")
    approvable(lab, "cpt_approve")
    report, records = lab.run(dry_run=True)
    rec = records[0]
    assert rec.recommendation == md.APPROVE_RECOMMENDED           # shadow でも出る（replay 価値を残す）
    assert rec.shadow_mode is True and rec.formal_review_gate_reached is False
    assert any(l.startswith(RP.shadow_label) for l in rec.limitations)
    assert report.shadow_mode is True
    lab2 = Lab(tmp_path / "g", eligible=100, milestone="CORPUS_100")
    approvable(lab2, "cpt_approve")
    rec2 = lab2.run(dry_run=True)[1][0]
    assert rec2.recommendation == md.APPROVE_RECOMMENDED
    assert rec2.shadow_mode is False and rec2.formal_review_gate_reached is True


# ============================================================ 20, 25 decision separation

def test_20_and_25_engine_never_writes_a_decision(tmp_path):
    from src.intelligence.decision.store import DecisionStore, decisions_root
    lab = Lab(tmp_path, eligible=150, milestone="CORPUS_100")
    approvable(lab, "cpt_approve")
    lab.run(dry_run=False)
    assert not decisions_root(lab.root).exists()                  # decision store は作られてすらいない
    assert DecisionStore(decisions_root(lab.root)).records() == []
    #: 境界: evaluation package のどこも Decision の書き込み API を import しない（prose ではなく AST で確認）
    import ast
    write_apis = {"DecisionService", "DecisionRequest"}
    for py in sorted(PKG.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        imported, modules = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules.add(node.module or "")
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
        assert not (imported & write_apis), (py.name, imported & write_apis)
        from_decision = {a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                         and "decision" in (node.module or "") for a in node.names}
        if from_decision:
            assert py.name == "cli.py", (py.name, from_decision)      # 参照は CLI の read-only 配線だけ
            assert from_decision <= {"DecisionStore", "derive_current_states", "decisions_root",
                                     "corpus_state_from_data_root"}, from_decision


def test_20b_reopen_signals_are_read_only_and_optional(tmp_path):
    lab = Lab(tmp_path, eligible=150)
    approvable(lab, "cpt_approve")
    rec = lab.run(dry_run=True)[1][0]
    assert rec.reopen_signal is None and rec.decision_state == ""          # 未注入なら decision 層と無関係
    lab2 = Lab(tmp_path / "b", eligible=150)
    approvable(lab2, "cpt_approve")
    rec2 = lab2.run(dry_run=True, lookup=lambda pid: "REJECTED")[1][0]
    assert rec2.decision_state == "REJECTED" and rec2.reopen_signal is True
    assert rec2.approved_adverse_signal is False


# ============================================================ 21-24 policy / replay / store

def test_21_policy_same_version_content_drift_fails_closed(tmp_path):
    lab = Lab(tmp_path)
    approvable(lab, "cpt_approve")
    lab.run(dry_run=False)
    drifted = cfg.EvaluationPolicy(policy_version="1.0.0", strength_medium_max=5)   # 同 version で中身だけ変更
    with pytest.raises(cfg.PolicyError):
        lab.engine(ep=drifted).evaluate_all()
    bumped = cfg.EvaluationPolicy(policy_version="1.1.0", strength_medium_max=5)
    assert lab.engine(ep=bumped).evaluate_all(dry_run=True)[0].evaluated == 1
    with pytest.raises(cfg.PolicyError):
        cfg.RecommendationPolicy(approve_requires_novelty=True).validate()
    with pytest.raises(cfg.PolicyError):
        cfg.RecommendationPolicy(score_allowed_for_state_transition=True).validate()
    with pytest.raises(cfg.PolicyError):
        cfg.EvaluationPolicy(weights={cfg.A_STRENGTH: 50}).validate()


def test_22_deterministic_replay_and_inputs_digest(tmp_path):
    lab = Lab(tmp_path)
    approvable(lab, "cpt_approve")
    lab.add(pattern("cpt_other", docs=lab.docs[:2], span=40))
    first = {r.pattern_id: r for r in lab.run(dry_run=True)[1]}
    second = {r.pattern_id: r for r in lab.run(dry_run=True)[1]}
    for pid in first:
        assert first[pid].inputs_digest == second[pid].inputs_digest
        assert first[pid].evaluation_id == second[pid].evaluation_id      # id は timestamp を含まない
        assert first[pid].evaluated_at != second[pid].evaluated_at        # timestamp だけが動く
    lab.run(dry_run=False)
    digest_a = EvaluationStore(evaluation_root(lab.root)).derived_digest()
    lab.run(dry_run=False)
    assert EvaluationStore(evaluation_root(lab.root)).derived_digest() == digest_a   # 再実行で derived state 不変


def test_23_dry_run_writes_nothing(tmp_path):
    lab = Lab(tmp_path)
    approvable(lab, "cpt_approve")
    report, _ = lab.run(dry_run=True)
    assert report.dry_run is True and report.written == 0
    assert not evaluation_root(lab.root).exists()
    report2, _ = lab.run(dry_run=False)
    assert report2.written == 1 and EvaluationStore(evaluation_root(lab.root)).exists()


def test_24_derived_store_does_not_mutate_source_artifacts(tmp_path):
    lab = Lab(tmp_path)
    approvable(lab, "cpt_approve")
    lab.flush()
    before = {p.name: sha256_file(p) for p in sorted(lab.research.glob("*.jsonl"))}
    dna_before = tuple(sha256_file(p) for p in DNA_FILES)
    lab.run(dry_run=False)
    lab.run(dry_run=False)
    assert {p.name: sha256_file(p) for p in sorted(lab.research.glob("*.jsonl"))} == before
    assert tuple(sha256_file(p) for p in DNA_FILES) == dna_before
    assert (evaluation_root(lab.root) / "evaluations.jsonl").is_file()
    assert not (lab.research / "evaluations.jsonl").exists()


def test_evaluation_package_hygiene_and_cli(tmp_path, capsys):
    from src.intelligence.evaluation import cli
    for py in sorted(PKG.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for token in ("API" + "_KEY", "os." + "environ", "date/" + "rashinban", "research/" + "source_docs",
                      "CompassData", "Users" + "\\\\"):
            assert token not in text, (py.name, token)
    lab = Lab(tmp_path, eligible=55)
    approvable(lab, "cpt_approve")
    lab.run(dry_run=False)
    argv = ["--data-root", str(lab.root)]
    assert cli.main(argv + ["validate-policy"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["compass_evaluation"]["digest"] and out["compass_recommendation"]["digest"]
    assert cli.main(argv + ["summary"]) == 0
    assert json.loads(capsys.readouterr().out)["evaluated"] == 1
    assert cli.main(argv + ["show", "--pattern", "cpt_approve"]) == 0
    assert json.loads(capsys.readouterr().out)["recommendation"] == md.APPROVE_RECOMMENDED
    assert cli.main(argv + ["show", "--pattern", "cpt_missing"]) == 1
    capsys.readouterr()
    assert cli.main(argv + ["list", "--limit", "5"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1
    digest = sha256_file(evaluation_root(lab.root) / "evaluations.jsonl")
    assert cli.main(argv + ["evaluate", "--dry-run"]) == 0
    assert "dry run" in capsys.readouterr().out
    assert sha256_file(evaluation_root(lab.root) / "evaluations.jsonl") == digest   # read/dry-run は書かない
