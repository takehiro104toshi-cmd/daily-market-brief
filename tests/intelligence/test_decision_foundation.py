"""Phase 3.9.1 Decision Foundation（cases A–O）。

append-only history / reason required / CORPUS_100 gate / no auto approval（3.8 analyzer・intake・processor）/
APPROVED ≠ promotion / reopen / supersede / deterministic current state / corruption fail closed /
data-root isolation / evidence snapshot without text / policy & schema version / production DNA immutability / CLI。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.corpus.identity import sha256_file
from src.intelligence.corpus_research import lifecycle as lc
from src.intelligence.decision import cli
from src.intelligence.decision import models as md
from src.intelligence.decision import policy as pol
from src.intelligence.decision.corpus_state import SOURCE_MISSING, CorpusState, corpus_state_from_data_root
from src.intelligence.decision.evidence import build_evidence_snapshot
from src.intelligence.decision.gates import FORMAL_REVIEW_ELIGIBLE, FORMAL_REVIEW_GATE_NOT_REACHED, formal_review_gate
from src.intelligence.decision.service import (
    E_PATTERN_NOT_IN_REGISTRY,
    E_POLICY_CHANGED_WITHOUT_VERSION_BUMP,
    E_TRANSITION_NOT_ALLOWED,
    DecisionRequest,
    DecisionService,
)
from src.intelligence.decision.state import derive_current_states, transition_allowed
from src.intelligence.decision.store import DecisionStore, DecisionStoreCorrupt, DecisionValidationError, decisions_root

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISION_PKG = REPO_ROOT / "src" / "intelligence" / "decision"
DNA_FILES = (REPO_ROOT / "knowledge" / "compass_dna" / "market_rules.yaml",
             REPO_ROOT / "src" / "intelligence" / "compass" / "market_principles.py")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tcr = _load("test_corpus_research")
_tqf = _load("test_processor_queue_fairness")
Lab, Queue = _tcr.Lab, _tqf.Queue

NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
ALL = (pol.KEEP_REVIEWING, pol.APPROVED, pol.REJECTED, pol.REOPENED_FOR_REVIEW, pol.SUPERSEDED, pol.RETIRED)


def _dna_hashes():
    return tuple(sha256_file(p) for p in DNA_FILES)


class Bench:
    """実 Phase 3.8 research root（Lab）+ 注入 corpus state + decision service（temp root のみ）。"""

    def __init__(self, tmp_path: Path, eligible: int = 55, policy: pol.DecisionPolicy = None):
        self.lab = Lab(tmp_path)
        for i in range(3):
            self.lab.add(i)
        self.lab.run()
        self.pids = sorted(self.lab.research.pattern_records_current("1.0.0"))
        self.pid = self.pids[0]
        self.corpus = {"eligible": eligible}
        self.policy = policy or pol.DecisionPolicy()
        self.ticks = 0
        self.store = DecisionStore(decisions_root(self.lab.root))
        self.service = DecisionService(self.store, self.policy, self.corpus_state,
                                       lambda p: build_evidence_snapshot(self.lab.research.root, p), clock=self.clock)

    def corpus_state(self) -> CorpusState:
        e = self.corpus["eligible"]
        return CorpusState(documents=e, usable=e, eligible=e, valid=e, milestone="CORPUS_100" if e >= 100 else "CORPUS_50")

    def clock(self) -> datetime:
        self.ticks += 1
        return NOW + timedelta(minutes=self.ticks)

    def decide(self, dtype: str, reason: str = "documented reason", actor: str = "taro", pid: str = "", **kw):
        return self.service.decide(DecisionRequest(pid or self.pid, dtype, reason, actor, **kw))

    def validate(self, dtype: str, reason: str = "documented reason", actor: str = "taro", pid: str = "", **kw):
        return self.service.validate(DecisionRequest(pid or self.pid, dtype, reason, actor, **kw))

    def lines(self):
        return self.store.path.read_text(encoding="utf-8").splitlines()

    def close(self):
        self.lab.close()


@pytest.fixture
def bench(tmp_path):
    b = Bench(tmp_path)
    yield b
    b.close()


# ============================================================ A. append-only history

def test_a_append_only_history_and_current_state(bench):
    a = bench.decide(pol.KEEP_REVIEWING, "needs more support")
    first_line = bench.lines()[0]
    b = bench.decide(pol.REJECTED, "single regime only")
    assert a.appended and b.appended and len(bench.lines()) == 2
    assert bench.lines()[0] == first_line                                      # A は書き換えられていない
    assert bench.store.get(a.decision_id).as_dict()["decision_type"] == pol.KEEP_REVIEWING
    state = bench.service.current_state(bench.pid)
    assert state.state == pol.REJECTED and state.decision_id == b.decision_id and state.history_length == 2
    assert b.record["previous_state"] == pol.KEEP_REVIEWING and b.record["previous_decision_id"] == a.decision_id
    assert [r["sequence"] for r in bench.service.history(bench.pid)] == [1, 2]
    assert not hasattr(bench.store, "update") and not hasattr(bench.store, "delete")


def test_idempotent_retry_does_not_duplicate(bench):
    o1 = bench.decide(pol.KEEP_REVIEWING, "same command")
    o2 = bench.decide(pol.KEEP_REVIEWING, "same command")                      # retry（同じ内容・同じ head）
    assert o1.appended and not o2.appended and o2.store_reason == "DUPLICATE_OF_HEAD_IDEMPOTENT"
    assert o2.decision_id == o1.decision_id and len(bench.lines()) == 1
    o3 = bench.decide(pol.KEEP_REVIEWING, "different reason later")              # 新情報 → 別 event
    assert o3.appended and o3.decision_id != o1.decision_id and len(bench.lines()) == 2
    assert md.decision_id_for(pattern_id="p", decision_type="APPROVED", reason="r", actor="a", actor_type="HUMAN",
                              policy_version="1.0.0", previous_decision_id="") == md.decision_id_for(
        pattern_id="p", decision_type="APPROVED", reason=" r ", actor="a", actor_type="HUMAN", policy_version="1.0.0",
        previous_decision_id="")                                                  # timestamp を含まない deterministic id


# ============================================================ B. reason validation

@pytest.mark.parametrize("dtype", ALL)
def test_b_reason_required(bench, dtype):
    bench.corpus["eligible"] = 100
    for reason in ("", "   "):
        v = bench.validate(dtype, reason)
        assert not v.ok and "REASON_REQUIRED" in [e["code"] for e in v.errors]
    assert not bench.store.exists()


# ============================================================ C. CORPUS_100 gate

def test_c_corpus_100_gate_99_100_101(bench):
    bench.corpus["eligible"] = 99
    blocked = bench.decide(pol.APPROVED, "looks strong")
    assert not blocked.appended and FORMAL_REVIEW_GATE_NOT_REACHED in [e["code"] for e in blocked.validation.errors]
    assert blocked.validation.gate["review_mode"] == md.MODE_SHADOW and not bench.store.exists()
    keep = bench.decide(pol.KEEP_REVIEWING, "shadow mode note")                 # 他 state は許可
    assert keep.appended and keep.record["review_mode"] == md.MODE_SHADOW and keep.record["corpus_size"] == 99
    bench.corpus["eligible"] = 100
    ok = bench.decide(pol.APPROVED, "human approval at CORPUS_100")
    assert ok.appended and ok.record["review_mode"] == md.MODE_FORMAL and ok.record["corpus_size"] == 100
    assert ok.record["corpus_milestone"] == "CORPUS_100"
    bench.corpus["eligible"] = 101
    ok2 = bench.decide(pol.APPROVED, "approval above the gate", pid=bench.pids[1])
    assert ok2.appended and ok2.validation.gate["code"] == FORMAL_REVIEW_ELIGIBLE
    for n, reached in ((99, False), (100, True), (101, True)):
        assert formal_review_gate(CorpusState(eligible=n), pol.DecisionPolicy()).reached is reached
    reject = bench.decide(pol.REJECTED, "rejected in shadow mode", pid=bench.pids[2])
    bench.corpus["eligible"] = 55
    assert reject.appended                                                        # REJECTED は gate 対象外


# ============================================================ D. no auto approval

def test_d_phase_38_and_intake_paths_cannot_create_decisions(tmp_path):
    lab = Lab(tmp_path / "a")
    for i in range(3):
        lab.add(i)                                                                # corpus intake
    lab.run()                                                                     # analyzer（incremental）
    lab.run()
    assert not decisions_root(lab.root).exists() and DecisionStore(decisions_root(lab.root)).records() == []
    assert not decisions_root(lab.root).exists()                                  # read は mkdir しない
    lab.close()
    q = Queue(tmp_path / "b")                                                     # scheduled processor（3.75）
    q.seed_known(3)
    q.issue("zzz_new.pdf", datetime(2026, 9, 3))
    r = q.run(5)
    assert r.counts().get("SUCCESS") == 1 and not decisions_root(q.root).exists()
    q.close()
    for pkg in ("corpus", "corpus_research", "mobile_intake", "compass"):
        for py in (REPO_ROOT / "src" / "intelligence" / pkg).glob("*.py"):
            text = py.read_text(encoding="utf-8")
            assert "intelligence.decision" not in text and "from ..decision" not in text, py
    assert lc.APPROVED not in lc.PHASE_38_ALLOWED


def test_d_system_actor_cannot_approve_even_after_gate(bench):
    bench.corpus["eligible"] = 150
    v = bench.validate(pol.APPROVED, "scored high", actor="analyzer", actor_type=md.ACTOR_SYSTEM)
    assert not v.ok and "HUMAN_ACTION_REQUIRED" in [e["code"] for e in v.errors] and not bench.store.exists()
    for dtype in ALL:
        assert "HUMAN_ACTION_REQUIRED" in [e["code"] for e in bench.validate(dtype, "x", actor_type=md.ACTOR_SYSTEM).errors]
    with pytest.raises(pol.PolicyError):
        pol.config_from_mapping({"auto_approval": True})
    bench.corpus["eligible"] = 100                                                # store 直叩きでも SYSTEM row は入らない
    ok = bench.validate(pol.APPROVED, "human approval")
    row = dict(ok.proposed)
    row["actor_type"] = md.ACTOR_SYSTEM
    assert "ACTOR_TYPE_NOT_HUMAN_IN_3_9_1" in md.validate_record(row, allow_unsealed=True)
    with pytest.raises(DecisionValidationError):
        bench.store.append(row)
    row = dict(ok.proposed)
    row["reason"] = "  "
    assert "REASON_EMPTY" in md.validate_record(row, allow_unsealed=True)
    with pytest.raises(DecisionValidationError):
        bench.store.append(row)
    assert not bench.store.exists()


# ============================================================ E. APPROVED != promoted / N. production DNA

def test_e_n_approved_is_not_promotion_and_dna_unchanged(bench):
    before = _dna_hashes()
    registry_before = sha256_file(bench.lab.research.root / "pattern_registry.json")
    queue_before = sha256_file(bench.lab.research.root / "review_queue.jsonl")
    bench.corpus["eligible"] = 100
    ok = bench.decide(pol.APPROVED, "formal human approval")
    assert ok.record["promotion_status"] == md.NOT_PROMOTED and ok.current_state["promotion_status"] == md.NOT_PROMOTED
    assert ok.current_state["state"] == pol.APPROVED
    row = dict(ok.record)
    row["promotion_status"] = md.PROMOTED_TO_DNA
    assert "PROMOTION_STATUS_NOT_ALLOWED_IN_3_9_1" in md.validate_record(row)
    assert _dna_hashes() == before
    assert sha256_file(bench.lab.research.root / "pattern_registry.json") == registry_before
    assert sha256_file(bench.lab.research.root / "review_queue.jsonl") == queue_before


# ============================================================ F. reopen / G. supersede & retire

def test_f_rejected_can_be_reopened_without_deleting_history(bench):
    rej = bench.decide(pol.REJECTED, "not generalizable")
    assert bench.service.current_state(bench.pid).reopen_eligible is True
    direct = bench.decide(pol.APPROVED, "skip reopen")
    assert not direct.appended and E_TRANSITION_NOT_ALLOWED in [e["code"] for e in direct.validation.errors]
    reo = bench.decide(pol.REOPENED_FOR_REVIEW, "new material evidence in 5 later issues")
    assert reo.appended and reo.record["reopens_decision_id"] == rej.decision_id
    hist = bench.service.history(bench.pid)
    assert [h["decision_type"] for h in hist] == [pol.REJECTED, pol.REOPENED_FOR_REVIEW]
    st = bench.service.current_state(bench.pid)
    assert st.state == pol.REOPENED_FOR_REVIEW and st.reopen_eligible is False
    assert bench.decide(pol.KEEP_REVIEWING, "review resumed").appended


def test_g_approved_superseded_and_retired(bench):
    bench.corpus["eligible"] = 120
    ap = bench.decide(pol.APPROVED, "approve")
    sup = bench.decide(pol.SUPERSEDED, "replaced by finer pattern")
    assert sup.appended and sup.record["supersedes_decision_id"] == ap.decision_id
    assert [h["decision_type"] for h in bench.service.history(bench.pid)] == [pol.APPROVED, pol.SUPERSEDED]
    assert bench.store.get(ap.decision_id).decision_type == pol.APPROVED           # 元 record は残る
    for dtype in ALL:                                                             # SUPERSEDED は v1 terminal
        assert not bench.validate(dtype, "x").ok
    ap2 = bench.decide(pol.APPROVED, "approve second", pid=bench.pids[1])
    ret = bench.decide(pol.RETIRED, "no longer relevant", pid=bench.pids[1])
    assert ap2.appended and ret.appended and bench.service.current_state(bench.pids[1]).state == pol.RETIRED
    assert transition_allowed(None, pol.SUPERSEDED) is False and transition_allowed(pol.APPROVED, pol.REJECTED) is False


# ============================================================ H. deterministic current state

def test_h_current_state_deterministic(bench):
    bench.corpus["eligible"] = 100
    bench.decide(pol.KEEP_REVIEWING, "k1")
    bench.decide(pol.KEEP_REVIEWING, "k2", pid=bench.pids[1])
    bench.decide(pol.APPROVED, "a1")
    bench.decide(pol.REJECTED, "r2", pid=bench.pids[1])
    records = bench.store.records()
    d1 = derive_current_states(records)
    d2 = derive_current_states(list(reversed(records)))
    assert d1 == d2 and [p for p in d1] == sorted(d1)
    assert d1[bench.pid].state == pol.APPROVED and d1[bench.pids[1]].state == pol.REJECTED
    first = json.dumps(bench.service.current_states(), sort_keys=True)
    assert json.dumps(DecisionService(DecisionStore(bench.store.root), bench.policy, bench.corpus_state,
                                      lambda p: None).current_states(), sort_keys=True) == first


# ============================================================ I. corruption

def test_i_corruption_fails_closed(bench, capsys):
    bench.decide(pol.KEEP_REVIEWING, "k1")
    bench.decide(pol.KEEP_REVIEWING, "k2")
    bench.decide(pol.REJECTED, "r")
    path = bench.store.path
    good = path.read_text(encoding="utf-8")
    lines = good.splitlines()
    row = json.loads(lines[1])
    row["reason"] = "edited after the fact"
    path.write_text("\n".join([lines[0], json.dumps(row, ensure_ascii=False, sort_keys=True), lines[2]]) + "\n", encoding="utf-8")
    with pytest.raises(DecisionStoreCorrupt) as exc:
        DecisionStore(bench.store.root).records()
    assert exc.value.code == "SCHEMA_INVALID" and exc.value.line_no == 2
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")   # 中間行の削除
    with pytest.raises(DecisionStoreCorrupt) as exc:
        DecisionStore(bench.store.root).records()
    assert exc.value.code in ("SEQUENCE_MISMATCH", "CHAIN_BROKEN")
    path.write_text(good + "{not json\n", encoding="utf-8")
    with pytest.raises(DecisionStoreCorrupt) as exc:
        DecisionService(DecisionStore(bench.store.root), bench.policy, bench.corpus_state, lambda p: None).current_states()
    assert exc.value.code == "INVALID_JSON"
    assert cli.main(["--data-root", str(bench.lab.root), "list"]) == 2
    assert "DECISION_STORE_CORRUPT" in capsys.readouterr().out
    path.write_text(good, encoding="utf-8")
    assert len(DecisionStore(bench.store.root).records()) == 3
    with pytest.raises(DecisionValidationError):
        bench.store.append({"decision_id": "cdc_bad"})


# ============================================================ J. data-root isolation

def test_j_data_root_isolation(bench, tmp_path):
    assert decisions_root(tmp_path) == tmp_path / "compass_decisions"
    assert str(bench.store.root).startswith(str(tmp_path))
    assert not (REPO_ROOT / "data" / "vnext" / "compass_decisions").exists()
    assert corpus_state_from_data_root(tmp_path / "nowhere").source == SOURCE_MISSING
    assert not (tmp_path / "nowhere").exists()                                   # resolver は作らない
    bench.decide(pol.KEEP_REVIEWING, "k")
    assert not (REPO_ROOT / "data" / "vnext" / "compass_decisions").exists()


# ============================================================ K. evidence snapshot

def test_k_evidence_snapshot_compact_and_no_text(bench):
    ev = build_evidence_snapshot(bench.lab.research.root, bench.pid)
    assert ev.pattern_found and ev.pattern_status in lc.PHASE_38_ALLOWED and ev.support_count >= 1
    assert ev.dna_classification and ev.research_snapshot_id and ev.analyzer_versions
    d = ev.as_dict()
    assert not any(k in d for k in md.FORBIDDEN_EVIDENCE_KEYS)
    blob = json.dumps(d, ensure_ascii=False)
    assert _tcr.NEW_BODY[:12] not in blob and "昨晩" not in blob and ".pdf" not in blob
    assert md.EvidenceSnapshot.from_dict(json.loads(blob)) == ev                  # round trip
    assert ev.digest() == build_evidence_snapshot(bench.lab.research.root, bench.pid).digest()
    missing = build_evidence_snapshot(bench.lab.research.root, "cpt_does_not_exist")
    assert missing.pattern_found is False
    v = bench.validate(pol.KEEP_REVIEWING, "x", pid="cpt_does_not_exist")
    assert E_PATTERN_NOT_IN_REGISTRY in [e["code"] for e in v.errors]
    o = bench.decide(pol.KEEP_REVIEWING, "k")
    assert o.record["evidence"]["pattern_id"] == bench.pid and o.record["evidence_digest"] == ev.digest()
    assert o.record["evidence"]["evidence_schema_version"] == md.EVIDENCE_SCHEMA_VERSION


# ============================================================ L. policy version / M. schema version

def test_l_policy_version_roundtrip_and_no_silent_change(bench, tmp_path):
    o = bench.decide(pol.KEEP_REVIEWING, "k")
    assert o.record["policy_version"] == "1.0.0" and o.record["policy_digest"] == bench.policy.digest()
    changed = pol.DecisionPolicy(policy_version="1.0.0", formal_review_min_corpus=150)
    svc = DecisionService(bench.store, changed, bench.corpus_state, lambda p: build_evidence_snapshot(bench.lab.research.root, p))
    v = svc.validate(DecisionRequest(bench.pid, pol.REJECTED, "r", "taro"))
    assert E_POLICY_CHANGED_WITHOUT_VERSION_BUMP in [e["code"] for e in v.errors]
    bumped = pol.DecisionPolicy(policy_version="1.1.0", formal_review_min_corpus=150)
    svc2 = DecisionService(bench.store, bumped, bench.corpus_state, lambda p: build_evidence_snapshot(bench.lab.research.root, p))
    o2 = svc2.decide(DecisionRequest(bench.pid, pol.REJECTED, "r", "taro"))
    assert o2.appended and o2.record["policy_version"] == "1.1.0"
    cfg = tmp_path / "config.yaml"
    cfg.write_text("compass_decision:\n  policy_version: '2.0.0'\n  formal_review_min_corpus: 120\n  auto_approval: false\n", encoding="utf-8")
    loaded = pol.load_decision_policy(cfg)
    assert loaded.policy_version == "2.0.0" and loaded.formal_review_min_corpus == 120
    for bad in ({"formal_review_min_corpus": 50}, {"policy_version": "v1"}, {"auto_approval": "true"}):
        with pytest.raises(pol.PolicyError):
            pol.config_from_mapping(bad)
    repo_policy = pol.load_decision_policy(REPO_ROOT / "config.yaml")
    assert repo_policy.formal_review_min_corpus == 100 and repo_policy.auto_approval is False


def test_m_schema_version_explicit_and_validated(bench):
    o = bench.decide(pol.KEEP_REVIEWING, "k")
    assert o.record["schema_version"] == md.SCHEMA_VERSION == "1.0.0"
    row = dict(o.record)
    row["schema_version"] = "0.9.0"
    assert "SCHEMA_VERSION_MISMATCH" in md.validate_record(row)
    assert "MISSING_FIELDS:" in md.validate_record({"decision_id": "x"})[0]
    lines = bench.lines()
    bad = json.loads(lines[0])
    bad["schema_version"] = "0.9.0"
    bench.store.path.write_text(json.dumps(bad, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(DecisionStoreCorrupt):
        DecisionStore(bench.store.root).records()


# ============================================================ CLI

def test_cli_read_commands_do_not_write_and_decide_is_explicit(tmp_path, capsys):
    lab = Lab(tmp_path)
    for i in range(3):
        lab.add(i)
    lab.run()
    pid = sorted(lab.research.pattern_records_current("1.0.0"))[0]
    lab.close()
    root = lab.root
    shutil.copytree(root / "research", root / "compass_research")                # CLI の data-root 規約へ配置
    shutil.copytree(root / "corpus", root / "compass_corpus")
    argv = ["--data-root", str(root)]
    assert cli.main(argv + ["gate"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["gate"]["code"] == FORMAL_REVIEW_GATE_NOT_REACHED and out["corpus"]["eligible"] == 3
    assert cli.main(argv + ["list"]) == 0 and json.loads(capsys.readouterr().out)["patterns"] == []
    assert not decisions_root(root).exists()                                      # read は書かない
    assert cli.main(argv + ["validate", "--pattern", pid, "--type", "APPROVED", "--reason", "r", "--actor", "taro"]) == 1
    assert FORMAL_REVIEW_GATE_NOT_REACHED in capsys.readouterr().out and not decisions_root(root).exists()
    assert cli.main(argv + ["decide", "--dry-run", "--pattern", pid, "--type", "KEEP_REVIEWING", "--reason", "r", "--actor", "taro"]) == 0
    assert "dry run" in capsys.readouterr().out and not decisions_root(root).exists()
    assert cli.main(argv + ["decide", "--pattern", pid, "--type", "KEEP_REVIEWING", "--reason", "r", "--actor", "taro"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["appended"] is True and out["mutation"].startswith("APPEND") and out["record"]["actor_type"] == md.ACTOR_HUMAN
    digest = sha256_file(decisions_root(root) / "decisions.jsonl")
    assert cli.main(argv + ["history", "--pattern", pid]) == 0
    assert len(json.loads(capsys.readouterr().out)["history"]) == 1
    assert cli.main(argv + ["show", "--decision", out["decision_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["decision_id"] == out["decision_id"]
    assert cli.main(argv + ["show", "--decision", "cdc_missing"]) == 1
    capsys.readouterr()
    assert cli.main(argv + ["list"]) == 0
    assert json.loads(capsys.readouterr().out)["patterns"][0]["state"] == pol.KEEP_REVIEWING
    assert sha256_file(decisions_root(root) / "decisions.jsonl") == digest          # read で変わらない
    assert cli.main(argv + ["decide", "--pattern", pid, "--type", "APPROVED", "--reason", "r", "--actor", "taro"]) == 1
    assert sha256_file(decisions_root(root) / "decisions.jsonl") == digest


# ============================================================ hygiene

def test_decision_package_hygiene():
    for py in sorted(DECISION_PKG.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for token in ("API" + "_KEY", "os." + "environ", "getenv" + "(", "date/" + "rashinban", "research/" + "source_docs",
                      "Users" + "\\\\", "C:" + "\\\\", "CompassData"):
            assert token not in text, (py.name, token)
        assert "market_rules.yaml" not in text or "read" in text.lower()
    assert md.PHASE_3_9_1_PROMOTION_STATUSES == (md.NOT_PROMOTED,)
    assert pol.ALLOWED_TRANSITIONS[pol.REJECTED] == frozenset({pol.REOPENED_FOR_REVIEW})
    assert pol.ALLOWED_TRANSITIONS[pol.APPROVED] == frozenset({pol.SUPERSEDED, pol.RETIRED})
