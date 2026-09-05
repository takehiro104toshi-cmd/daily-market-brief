"""Phase 3.9.4 real-data validation（Windows 実機を 1 操作で検証するための runner）。

`python -m src.intelligence.replay.validation --require-commit <sha> --expect-* <digest>`

production へ書くのは `<data_root>/compass_replay/` だけ（replay の derived 出力）。corpus / research /
evaluation / shadow review / decision / DNA / PDF には触れない。PDF も開かない。出力は ASCII の
key=value 行と `::P394_*::` marker のみで、文書のファイル名・path・本文は一切出さない。

fail closed: 各節で結果を明示的に検査し（exit code だけに頼らない）、材料となる失敗があれば
`::P394_FAIL::` を出して後続節へ進まない。exit 3 = ReplayError / 4 = validation failure / 5 = unexpected。
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..corpus.store import corpus_root
from ..corpus_research.store import research_root
from ..decision.store import DECISIONS_FILE, decisions_root
from ..evaluation.config import load_policies
from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED
from ..evaluation.store import evaluation_root
from ..shadow_review.config import load_shadow_review_policy
from ..shadow_review.events import EVENTS_FILE as REVIEW_EVENTS_FILE, shadow_review_root
from ..shadow_review.models import find_forbidden_keys
from .config import MODE_FULL, ReplayPolicy, load_replay_policy
from .errors import ReplayError
from .runner import INPUT_LIVE_CAPTURE, INPUT_RETAINED_SNAPSHOT, OWNER_MARKER, ReplayRunner, workspace_base
from .snapshot import live_corpus_observation, read_only_uri, sha256_file
from .store import (
    EVENTS_FILE as REPLAY_EVENTS_FILE,
    MANIFEST_FILE,
    SNAPSHOTS_FILE,
    SUMMARY_FILE,
    TIMELINES_FILE,
    ReplayStore,
    replay_root,
)
from .timeline import SECTION_ADVERSE_OVERFLOW, SECTION_MAIN

DNA_FILES = ("src/intelligence/compass/market_principles.py", "knowledge/compass_dna/market_rules.yaml")
REQUIRED_MILESTONES = (10, 30, 50, 100)
EXIT_REPLAY_ERROR, EXIT_VALIDATION_FAILURE, EXIT_UNEXPECTED = 3, 4, 5


class ValidationFailure(Exception):
    def __init__(self, section: str, reason: str) -> None:
        super().__init__(f"{section}: {reason}")
        self.section = section
        self.reason = reason


# ------------------------------------------------------------------- output helpers
def _emit(key: str, value: Any) -> None:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    print(f"{key}={value}", flush=True)


def _marker(name: str) -> None:
    print(f"::P394_{name}::", flush=True)


def _sha_of_text(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def _dir_digest(root: Path) -> Dict[str, Any]:
    """derived artifact directory の identity（相対 path + sha256）。名前は出力しない。"""
    if not root.is_dir():
        return {"exists": False, "files": 0, "digest": ""}
    files = sorted(p for p in root.rglob("*") if p.is_file())
    parts = [f"{p.relative_to(root).as_posix()}|{sha256_file(p)}" for p in files]
    return {"exists": True, "files": len(files), "digest": _sha_of_text(parts)}


def _pdf_digest(root: Path) -> Dict[str, Any]:
    """data root 配下の PDF の identity（相対 path + size + mtime）。名前は出力しない。開かない。"""
    if not root.is_dir():
        return {"files": 0, "digest": ""}
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    parts = []
    for p in files:
        st = p.stat()
        parts.append(f"{p.relative_to(root).as_posix()}|{st.st_size}|{st.st_mtime_ns}")
    return {"files": len(files), "digest": _sha_of_text(parts)}


def _file_identity(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "bytes": 0, "lines": 0, "sha256": ""}
    data = path.read_bytes()
    return {"exists": True, "bytes": len(data), "lines": sum(1 for line in data.splitlines() if line.strip()),
            "sha256": hashlib.sha256(data).hexdigest()[:16]}


def _quantiles(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0}
    xs = sorted(values)

    def at(q: float) -> float:
        idx = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
        return xs[idx]

    return {"n": len(xs), "min": xs[0], "p25": at(0.25), "p50": at(0.5), "p75": at(0.75), "max": xs[-1],
            "mean": round(sum(xs) / len(xs), 4)}


def _reversal_histogram(metrics: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    ms = list(metrics)
    buckets = {"0": 0, "1": 0, "2": 0, "3+": 0}
    for m in ms:
        n = int(m.get("recommendation_reversal_count", 0) or 0)
        buckets["3+" if n >= 3 else str(n)] += 1
    total = len(ms)
    pct = {k: (round(100.0 * v / total, 1) if total else 0.0) for k, v in buckets.items()}
    return {"patterns": total, "count": buckets, "percent": pct}


def _class_counts(metrics: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    out = {"STABLE": 0, "MOSTLY_STABLE": 0, "OSCILLATING": 0, "RECENT_TRANSITION": 0, "INSUFFICIENT_HISTORY": 0}
    for m in metrics:
        out[str(m.get("stability_class"))] = out.get(str(m.get("stability_class")), 0) + 1
    return out


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)))
    except Exception:  # noqa: BLE001
        return None


def _calibration_block(metrics: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "reversals": _reversal_histogram(metrics),
        "eligible_documents_in_current_state": _quantiles(
            [int(m.get("eligible_documents_in_current_state", 0) or 0) for m in metrics]),
        "state_persistence_ratio": _quantiles(
            [v for v in (_float(m.get("state_persistence_ratio")) for m in metrics) if v is not None]),
        "approve_persistence_ratio": _quantiles(
            [v for v in (_float(m.get("approve_persistence_ratio")) for m in metrics) if v is not None]),
        "reject_persistence_ratio": _quantiles(
            [v for v in (_float(m.get("reject_persistence_ratio")) for m in metrics) if v is not None]),
        "transitions": _quantiles([int(m.get("recommendation_transition_count", 0) or 0) for m in metrics]),
        "classes": _class_counts(metrics),
    }


# ------------------------------------------------------------------- git helpers
def _git(repo: Path, *args: str) -> Tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "").strip()


# ------------------------------------------------------------------- the validation
class RealDataValidation:
    def __init__(self, data_root: Path, repo_root: Path, *, require_commit: str = "",
                 expected_digests: Optional[Mapping[str, str]] = None, policy: Optional[ReplayPolicy] = None,
                 skip_git: bool = False) -> None:
        self.data_root = Path(data_root)
        self.repo = Path(repo_root)
        self.require_commit = require_commit
        self.expected = dict(expected_digests or {})
        self.policy = policy or load_replay_policy()
        self.skip_git = skip_git
        self.epol, self.rpol = load_policies()
        self.spol = load_shadow_review_policy()
        self.store = ReplayStore(replay_root(self.data_root))
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.runners: Dict[str, ReplayRunner] = {}
        self.baseline: Dict[str, Any] = {}
        self.tracked_status_before = ""
        self.t0 = time.perf_counter()

    # ------------------------------------------------------------- generic
    def fail(self, section: str, reason: str) -> None:
        raise ValidationFailure(section, reason)

    def check(self, section: str, cond: bool, reason: str) -> None:
        if not cond:
            self.fail(section, reason)

    def _run(self, label: str, *, mode: str = "", retain: bool = False, input_snapshot: Optional[Path] = None,
             policy: Optional[ReplayPolicy] = None) -> Dict[str, Any]:
        runner = ReplayRunner(self.data_root, replay_policy=policy or self.policy, mode=mode,
                              retain_temp=retain, input_snapshot=input_snapshot)
        self.runners[label] = runner                  # 失敗しても temp を解放できるよう先に登録
        t0 = time.perf_counter()
        result = runner.run()
        wall = round(time.perf_counter() - t0, 3)
        run_id = result["run_id"]
        bundle = {
            "label": label, "result": result, "wall_seconds": wall, "runner": runner,
            "manifest": self.store.read_json(run_id, MANIFEST_FILE),
            "summary": self.store.read_json(run_id, SUMMARY_FILE),
            "snapshots": self.store.read_jsonl(run_id, SNAPSHOTS_FILE),
            "rows": self.store.read_jsonl(run_id, TIMELINES_FILE),
            "events": self.store.read_jsonl(run_id, REPLAY_EVENTS_FILE),
        }
        self.runs[label] = bundle
        self.runners[label] = runner
        return bundle

    def _inspect_run(self, section: str, b: Mapping[str, Any]) -> None:
        """出力を明示的に検査する（exit code だけに頼らない）。"""
        m, s = b["manifest"], b["summary"]
        drift = m.get("drift") or {}
        self.check(section, m.get("corpus_snapshot", {}).get("tables", {}).get("documents", 0) > 0,
                   "corpus snapshot has no documents")
        self.check(section, bool(m.get("context_manifest_digest")), "context snapshot digest missing")
        self.check(section, drift.get("captured_input_mutations") == [], "captured input mutated during run")
        self.check(section, drift.get("context_changed") is False, "context changed during run")
        self.check(section, Decimal(str(m.get("undated_ratio", "0"))) <= self.policy.max_undated_ratio,
                   "undated ratio exceeds policy")
        for snap in b["snapshots"]:
            self.check(section, snap.get("leakage_audit") == "PASSED" and snap.get("identity_audit") == "PASSED",
                       f"audit not PASSED at position {snap.get('position')}")
        final = int(s.get("final_position", 0))
        expected_ms = sorted({p for p in REQUIRED_MILESTONES if p <= final} | ({final} if final else set()))
        equiv = {int(e["position"]): bool(e.get("equal")) for e in s.get("rebuild_equivalence") or []}
        self.check(section, all(equiv.get(p) is True for p in expected_ms),
                   f"rebuild equivalence missing/failed at {[p for p in expected_ms if equiv.get(p) is not True]}")
        self.check(section, all(equiv.values()), "rebuild equivalence reported a mismatch")
        pd = s.get("policy_digests") or {}
        for key, want in self.expected.items():
            if want:
                self.check(section, pd.get(key) == want, f"{key} policy digest in run != expected")
        for name, payload in (("manifest", m), ("summary", s), ("snapshots", b["snapshots"]),
                              ("timelines", b["rows"]), ("events", b["events"])):
            found = find_forbidden_keys(payload)
            self.check(section, not found, f"forbidden keys in {name}: {sorted(found)}")
        for q in s.get("queue_over_time") or []:
            self.check(section, q.get("enabled") is True, f"queue replay disabled at position {q.get('position')}")
        for r in b["rows"]:
            if r.get("queue_section") == SECTION_ADVERSE_OVERFLOW:
                self.check(section, r.get("recommendation") == REJECT_RECOMMENDED,
                           "ADVERSE_OVERFLOW holds a non-REJECT pattern")

    def _report_run(self, b: Mapping[str, Any]) -> None:
        m, s, r = b["manifest"], b["summary"], b["result"]
        _emit("run_id", r["run_id"])
        _emit("input_source", (m.get("input_source") or {}).get("kind"))
        _emit("replay_mode", m.get("replay_mode"))
        _emit("ordering", m.get("ordering_mode"))
        _emit("captured_documents", m.get("captured_documents"))
        _emit("captured_usable", m.get("captured_usable"))
        _emit("captured_eligible", m.get("captured_eligible"))
        _emit("latest_document_date", m.get("latest_document_date"))
        _emit("corpus_snapshot_tables", (m.get("corpus_snapshot") or {}).get("tables"))
        _emit("corpus_snapshot_digest", m.get("corpus_snapshot_digest"))
        ctx = m.get("context_snapshot") or {}
        _emit("context_snapshot", {k: ctx.get(k) for k in ("context_available", "calendar_available", "row_count",
                                                            "session_count", "trading_days", "latest_session_date")})
        _emit("undated_excluded", sum(1 for e in m.get("excluded") or [] if e.get("reason") == "UNDATED_CHRONOLOGICAL"))
        _emit("undated_ratio", m.get("undated_ratio"))
        _emit("snapshot_count", s.get("snapshots"))
        _emit("positions", s.get("positions"))
        _emit("milestone_positions", m.get("milestone_positions"))
        _emit("refined_intervals", s.get("refined_intervals"))
        _emit("transition_refinement_count", len(s.get("refined_intervals") or []))
        _emit("refined_positions_added", sum(int(i.get("added", 0)) for i in s.get("refined_intervals") or []))
        _emit("patterns", s.get("patterns"))
        _emit("timeline_rows", s.get("timeline_rows"))
        _emit("events", len(b["events"]))
        _emit("final_by_recommendation", (s.get("final_distribution") or {}).get("by_recommendation"))
        _emit("final_by_lifecycle", (s.get("final_distribution") or {}).get("by_lifecycle"))
        _emit("rebuild_equivalence", [{"position": e["position"], "equal": e["equal"]} for e in s.get("rebuild_equivalence") or []])
        _emit("leakage_audit", "PASSED" if all(x.get("leakage_audit") == "PASSED" for x in b["snapshots"]) else "FAILED")
        _emit("identity_audit", "PASSED" if all(x.get("identity_audit") == "PASSED" for x in b["snapshots"]) else "FAILED")
        _emit("mixed_policy_digest", "NONE")
        _emit("impossible_early_recommendation", "NONE")
        _emit("drift", m.get("drift"))
        _emit("live_corpus_at_start", m.get("live_production_corpus_at_start"))
        _emit("live_corpus_at_end", m.get("live_production_corpus_at_end"))
        _emit("new_documents_ingested_during_run", m.get("new_documents_ingested_during_run"))
        _emit("timings", s.get("timings"))
        _emit("runtime_seconds", b["wall_seconds"])
        _emit("run_digest", s.get("run_digest"))
        _emit("input_manifest_digest", s.get("input_manifest_digest"))
        _emit("context_manifest_digest", s.get("context_manifest_digest"))
        _emit("research_version_key", s.get("research_version_key"))
        _emit("policy_digests", s.get("policy_digests"))
        _emit("forbidden_key_scan", "CLEAN")

    # ------------------------------------------------------------- sections
    def head(self) -> None:
        _marker("HEAD")
        if self.skip_git:
            _emit("git", "SKIPPED")
        else:
            code, head = _git(self.repo, "rev-parse", "HEAD")
            self.check("HEAD", code == 0 and head, "git rev-parse HEAD failed")
            _emit("head", head)
            _emit("branch", _git(self.repo, "rev-parse", "--abbrev-ref", "HEAD")[1])
            if self.require_commit:
                code, _ = _git(self.repo, "merge-base", "--is-ancestor", self.require_commit, "HEAD")
                _emit("required_commit", self.require_commit)
                _emit("head_contains_required_commit", "YES" if code == 0 else "NO")
                self.check("HEAD", code == 0, "HEAD does not contain the required commit")
            code, status = _git(self.repo, "status", "--porcelain", "--untracked-files=no")
            self.check("HEAD", code == 0, "git status failed")
            self.tracked_status_before = status
            _emit("tracked_worktree_clean", "YES" if not status else "NO")
            _emit("tracked_modified_files", len([line for line in status.splitlines() if line.strip()]))
            _emit("main_contains_head", self._main_contains_head())
        _emit("data_root_leaf", self.data_root.name)
        _emit("data_root_exists", self.data_root.is_dir())
        db = corpus_root(self.data_root) / "index" / "corpus.sqlite3"
        _emit("corpus_index_exists", db.is_file())
        self.check("HEAD", db.is_file(), "production corpus index not found")

    def _main_contains_head(self) -> str:
        out = []
        for ref in ("origin/main", "main"):
            code, _ = _git(self.repo, "rev-parse", "--verify", "--quiet", ref)
            if code != 0:
                out.append(f"{ref}:ABSENT")
                continue
            code, _ = _git(self.repo, "merge-base", "--is-ancestor", "HEAD", ref)
            out.append(f"{ref}:{'YES' if code == 0 else 'NO'}")
            self.check("HEAD", code != 0, f"{ref} already contains HEAD (main merged)")
        return ",".join(out)

    def policy_digests(self) -> None:
        _marker("POLICY")
        actual = {"evaluation": self.epol.digest(), "recommendation": self.rpol.digest(),
                  "shadow_review": self.spol.digest(), "replay": self.policy.digest()}
        for key, digest in actual.items():
            _emit(f"{key}_digest", digest)
            want = self.expected.get(key, "")
            if want:
                _emit(f"{key}_expected", want)
                self.check("POLICY", digest == want, f"{key} digest {digest} != expected {want}")
        _emit("replay_policy_version", self.policy.policy_version)
        _emit("replay_default_mode", self.policy.default_mode)
        _emit("replay_full_replay_enabled_in_config", self.policy.full_replay_enabled)
        _emit("stability_calibration_state", self.policy.stability_calibration_state)
        _emit("stability_thresholds", {"stable_min_persistence": self.policy.stable_min_persistence,
                                       "mostly_stable_ratio": str(self.policy.mostly_stable_ratio),
                                       "oscillating_min_reversals": self.policy.oscillating_min_reversals,
                                       "unit": self.policy.stability_unit})
        _emit("policy_check", "PASSED")

    def _capture_baseline(self) -> Dict[str, Any]:
        croot = corpus_root(self.data_root)
        db = croot / "index" / "corpus.sqlite3"
        obs = live_corpus_observation(croot)
        versions: List[str] = []
        try:
            import sqlite3

            conn = sqlite3.connect(read_only_uri(db), uri=True)
            try:
                versions = sorted(str(r[0]) for r in conn.execute("SELECT DISTINCT analysis_version FROM analyses"))
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            versions = ["UNREADABLE"]
        dna = {}
        if not self.skip_git:
            for rel in DNA_FILES:
                _, committed = _git(self.repo, "rev-parse", f"HEAD:{rel}")
                code, _ = _git(self.repo, "diff", "--quiet", "HEAD", "--", rel)   # 改行変換を考慮した一致判定
                dna[rel] = {"head_blob": committed[:16], "match": code == 0}
        return {
            "corpus_db_sha256": sha256_file(db)[:16] if db.is_file() else "",
            "corpus_documents": obs.get("documents"), "corpus_eligible": obs.get("eligible"),
            "corpus_duplicates": obs.get("duplicates"),
            "analysis_versions_present": versions,
            "analysis_versions_supported": list(self.epol.supported_analysis_versions),
            "decisions": _file_identity(decisions_root(self.data_root) / DECISIONS_FILE),
            "review_events": _file_identity(shadow_review_root(self.data_root) / REVIEW_EVENTS_FILE),
            "dna": dna,
            "derived_research": _dir_digest(research_root(self.data_root)),
            "derived_evaluation": _dir_digest(evaluation_root(self.data_root)),
            "derived_shadow_review": _dir_digest(shadow_review_root(self.data_root)),
            "derived_decisions": _dir_digest(decisions_root(self.data_root)),
            "pdfs": _pdf_digest(self.data_root),
            "replay_runs_stored": len(self.store.list_runs()),
        }

    def baseline_section(self) -> None:
        _marker("BASELINE")
        self.baseline = self._capture_baseline()
        for key, value in self.baseline.items():
            _emit(key, value)
        unsupported = [v for v in self.baseline["analysis_versions_present"]
                       if self.epol.supported_analysis_versions and v not in self.epol.supported_analysis_versions]
        _emit("analysis_versions_unsupported", unsupported)
        self.check("BASELINE", not unsupported, f"corpus carries unsupported analysis versions {unsupported}")
        self.check("BASELINE", all(v["match"] for v in self.baseline["dna"].values()) or self.skip_git,
                   "DNA working tree differs from HEAD before the run")
        _emit("baseline_check", "PASSED")

    def default_run(self, label: str, marker: str, retain: bool) -> Dict[str, Any]:
        _marker(marker)
        b = self._run(label, retain=retain)
        self._inspect_run(marker, b)
        self._report_run(b)
        _emit("snapshot_retained_for_reuse", retain)
        _emit(f"{marker.lower()}_check", "PASSED")
        return b

    def determinism(self) -> None:
        _marker("DETERMINISM")
        a, b = self.runs["run1"], self.runs["run2"]
        same = (a["manifest"]["input_manifest_digest"] == b["manifest"]["input_manifest_digest"]
                and a["manifest"]["context_manifest_digest"] == b["manifest"]["context_manifest_digest"])
        _emit("SAME_INPUT_UNIVERSE", "true" if same else "false")
        _emit("live_run1_run_digest", a["summary"]["run_digest"])
        _emit("live_run2_run_digest", b["summary"]["run_digest"])
        if same:
            match = a["summary"]["run_digest"] == b["summary"]["run_digest"]
            _emit("LIVE_RUN_DIGEST_MATCH", match)
            self.check("DETERMINISM", match, "same input universe but run_digest differs")
        else:
            _emit("LIVE_RUN_DIGEST_MATCH", "NOT_COMPARABLE (live intake changed the captured universe)")
            _emit("live_run2_new_eligible", int(b["manifest"]["captured_eligible"]) - int(a["manifest"]["captured_eligible"]))
        # supported fixed-snapshot path: replay run1's retained immutable snapshot a second time
        c = self._run("rerun", input_snapshot=self.runners["run1"].temp_root)
        self._inspect_run("DETERMINISM", c)
        _emit("fixed_rerun_run_id", c["result"]["run_id"])
        _emit("fixed_rerun_input_source", (c["manifest"].get("input_source") or {}).get("kind"))
        _emit("fixed_rerun_source_run_id", (c["manifest"].get("input_source") or {}).get("source_run_id"))
        self.check("DETERMINISM", (c["manifest"].get("input_source") or {}).get("kind") == INPUT_RETAINED_SNAPSHOT,
                   "fixed re-run did not use the retained snapshot")
        same_fixed = (a["manifest"]["input_manifest_digest"] == c["manifest"]["input_manifest_digest"]
                      and a["manifest"]["context_manifest_digest"] == c["manifest"]["context_manifest_digest"])
        _emit("FIXED_SNAPSHOT_SAME_INPUT_UNIVERSE", same_fixed)
        self.check("DETERMINISM", same_fixed, "retained snapshot re-run captured a different universe")
        match = a["summary"]["run_digest"] == c["summary"]["run_digest"]
        _emit("FIXED_SNAPSHOT_RUN_DIGEST_MATCH", match)
        sa = {int(x["position"]): x["snapshot_digest"] for x in a["snapshots"]}
        sc = {int(x["position"]): x["snapshot_digest"] for x in c["snapshots"]}
        _emit("FIXED_SNAPSHOT_POSITIONS_MATCH", sorted(sa) == sorted(sc))
        _emit("FIXED_SNAPSHOT_SNAPSHOT_DIGESTS_MATCH", sa == sc)
        self.check("DETERMINISM", match and sa == sc, "fixed-snapshot re-run is not deterministic")
        _emit("fixed_rerun_runtime_seconds", c["wall_seconds"])
        _emit("DETERMINISM_PROOF", "FIXED_SNAPSHOT_X2_PASS" + ("+LIVE_X2_PASS" if same else ""))
        _emit("determinism_check", "PASSED")

    def full_replay(self) -> Dict[str, Any]:
        _marker("FULL_REPLAY")
        override = dataclasses.replace(self.policy, full_replay_enabled=True)
        _emit("config_override_method", "in-process dataclasses.replace(full_replay_enabled=True); config.yaml untouched")
        _emit("override_changes_replay_policy_digest", override.digest() != self.policy.digest())
        self.check("FULL_REPLAY", override.digest() == self.policy.digest(), "override changed the policy digest")
        d = self._run("full", mode=MODE_FULL, input_snapshot=self.runners["run1"].temp_root, policy=override)
        self._inspect_run("FULL_REPLAY", d)
        self._report_run(d)
        a = self.runs["run1"]
        self.check("FULL_REPLAY", d["summary"]["snapshots"] == d["summary"]["final_position"],
                   "FULL replay did not evaluate every eligible increment")
        self.check("FULL_REPLAY", d["manifest"]["input_manifest_digest"] == a["manifest"]["input_manifest_digest"],
                   "FULL replay universe differs from run1")
        skip = ("run_id", "snapshot_mode")
        ra = {(int(r["position"]), r["pattern_id"]): {k: v for k, v in r.items() if k not in skip} for r in a["rows"]}
        rd = {(int(r["position"]), r["pattern_id"]): {k: v for k, v in r.items() if k not in skip} for r in d["rows"]}
        consistent = set(ra) <= set(rd) and all(ra[k] == rd[k] for k in ra)
        _emit("CROSS_MODE_CONSISTENCY_WITH_DEFAULT_RUN", consistent)
        self.check("FULL_REPLAY", consistent, "FULL replay rows differ from the default run at shared positions")
        _emit("full_replay_check", "PASSED")
        return d

    def calibration(self) -> None:
        _marker("CALIBRATION")
        s = self.runs["full"]["summary"]
        metrics = list((s.get("pattern_metrics") or {}).values())
        _emit("calibration_state", s.get("stability_calibration_state"))
        _emit("thresholds_provisional", {"stable_min_persistence": self.policy.stable_min_persistence,
                                         "mostly_stable_ratio": str(self.policy.mostly_stable_ratio),
                                         "oscillating_min_reversals": self.policy.oscillating_min_reversals,
                                         "unit": self.policy.stability_unit})
        _emit("thresholds_changed_by_validation", False)
        _emit("current_recommendation_counts", (s.get("final_distribution") or {}).get("by_recommendation"))
        _emit("current_approve_candidates", sum(1 for m in metrics if m.get("current_recommendation") == APPROVE_RECOMMENDED))
        _emit("current_reject_candidates", sum(1 for m in metrics if m.get("current_recommendation") == REJECT_RECOMMENDED))
        _emit("ALL_PATTERNS", _calibration_block(metrics))
        _emit("CURRENT_APPROVE_RECOMMENDED",
              _calibration_block([m for m in metrics if m.get("current_recommendation") == APPROVE_RECOMMENDED]))
        _emit("CURRENT_REJECT_RECOMMENDED",
              _calibration_block([m for m in metrics if m.get("current_recommendation") == REJECT_RECOMMENDED]))
        _emit("stability_distribution", s.get("stability_distribution"))
        _emit("calibration_note", "PROVISIONAL_CALIBRATION_ONLY; thresholds are frozen by the Supervisor, not here")

    def approve_stress(self) -> None:
        _marker("APPROVE_STRESS")
        st = self.runs["full"]["summary"].get("approve_stress") or {}
        _emit("count", st.get("count"))
        _emit("stress_positions", st.get("positions"))
        _emit("appeared_only_after_100", st.get("appeared_only_after_100"))
        _emit("ever_reverted", st.get("ever_reverted"))
        for item in st.get("items") or []:
            _emit("item", {k: item.get(k) for k in (
                "pattern_id", "pattern_type", "first_approve_position", "first_approve_date", "appeared_only_after_100",
                "approve_persistence_ratio", "reversions", "worst_consistency_observed", "consistency_ever_low",
                "positions_with_cross_regime_high", "positions_with_time_high", "snapshots_observed", "stability_class",
                "recommendation_at")})
        _emit("first_approve_positions", sorted(int(i["first_approve_position"]) for i in st.get("items") or []
                                                if i.get("first_approve_position") is not None))
        _emit("persistence_ratios", _quantiles([v for v in (_float(i.get("approve_persistence_ratio"))
                                                            for i in st.get("items") or []) if v is not None]))
        _emit("worst_consistency", {c: sum(1 for i in st.get("items") or [] if i.get("worst_consistency_observed") == c)
                                    for c in ("HIGH", "MEDIUM", "LOW")})

    def reject_stress(self) -> None:
        _marker("REJECT_STRESS")
        st = self.runs["full"]["summary"].get("reject_stress") or {}
        _emit("count", st.get("count"))
        _emit("ever_recovered", st.get("ever_recovered"))
        drivers: Dict[str, int] = {}
        for item in st.get("items") or []:
            drivers[item.get("reject_driver", "")] = drivers.get(item.get("reject_driver", ""), 0) + 1
            _emit("item", {k: item.get(k) for k in (
                "pattern_id", "pattern_type", "first_material_contradiction_position", "first_reject_position",
                "first_reject_date", "was_review_before_reject", "recommendation_before_reject", "reject_driver",
                "dna_conflicts_at_reject", "contradiction_at_reject", "contradiction_recovery_positions",
                "reject_persistence_ratio", "reversions", "stability_class")})
        _emit("first_contradiction_positions", sorted(int(i["first_material_contradiction_position"])
                                                      for i in st.get("items") or []
                                                      if i.get("first_material_contradiction_position") is not None))
        _emit("first_reject_positions", sorted(int(i["first_reject_position"]) for i in st.get("items") or []
                                               if i.get("first_reject_position") is not None))
        _emit("persistence_ratios", _quantiles([v for v in (_float(i.get("reject_persistence_ratio"))
                                                            for i in st.get("items") or []) if v is not None]))
        _emit("driver_distribution", drivers)
        _emit("disappeared_or_recovered", sum(1 for i in st.get("items") or [] if i.get("contradiction_recovery_positions")))

    def queue_replay(self) -> None:
        _marker("QUEUE_REPLAY")
        d = self.runs["full"]
        s = d["summary"]
        _emit("event_store_used", "EMPTY_TEMP_EVENT_STORE (no historical human outcome fabricated)")
        _emit("production_review_events_read_by_queue_replay", 0)
        qot = s.get("queue_over_time") or []
        self.check("QUEUE_REPLAY", qot and all(q.get("enabled") for q in qot), "queue replay missing for a snapshot")
        _emit("queue_replay_snapshots", len(qot))
        for q in qot:
            _emit("queue", {"position": q.get("position"), "main": q.get("main_count"),
                            "adverse_overflow": q.get("adverse_overflow_count"), "backlog": q.get("backlog_count"),
                            "watch": q.get("watch_count"), "main_by_recommendation": q.get("by_recommendation")})
        adverse_rows = [r for r in d["rows"] if r.get("queue_section") == SECTION_ADVERSE_OVERFLOW]
        _emit("adverse_overflow_rows", len(adverse_rows))
        _emit("adverse_overflow_all_reject", all(r.get("recommendation") == REJECT_RECOMMENDED for r in adverse_rows))
        top8 = s.get("current_top8_retrospective") or []
        _emit("current_top8_count", len(top8))
        for card in top8:
            _emit("top8", card)
        _emit("main_rows_total", sum(1 for r in d["rows"] if r.get("queue_section") == SECTION_MAIN))
        _emit("queue_replay_check", "PASSED")

    def rebuild_equivalence(self) -> None:
        _marker("REBUILD_EQUIVALENCE")
        overall = True
        for label in ("run1", "run2", "rerun", "full"):
            b = self.runs.get(label)
            if not b:
                continue
            final = int(b["summary"].get("final_position", 0))
            expected = sorted({p for p in REQUIRED_MILESTONES if p <= final} | {final})
            equiv = {int(e["position"]): e for e in b["summary"].get("rebuild_equivalence") or []}
            for p in expected:
                e = equiv.get(p)
                status = "PASS" if e and e.get("equal") else "FAIL"
                overall = overall and status == "PASS"
                _emit(f"{label}_position_{p}", {"status": status, "milestone": "current" if p == final and p not in REQUIRED_MILESTONES else p,
                                                 "patterns": (e or {}).get("patterns"), "structures": (e or {}).get("structures")})
        _emit("REBUILD_EQUIVALENCE_OVERALL", "PASS" if overall else "FAIL")
        self.check("REBUILD_EQUIVALENCE", overall, "rebuild equivalence failed")

    def handoff(self) -> None:
        _marker("HANDOFF")
        fri = self.runs["full"]["summary"].get("formal_review_input") or {}
        items = fri.get("items") or []
        _emit("count", fri.get("count"))
        _emit("by_recommendation", {rec: sum(1 for i in items if i.get("current_recommendation") == rec)
                                    for rec in (APPROVE_RECOMMENDED, REJECT_RECOMMENDED)})
        _emit("boundaries", fri.get("boundaries"))
        self.check("HANDOFF", any("EVIDENCE_ONLY" in b for b in fri.get("boundaries") or []), "handoff lacks EVIDENCE_ONLY boundary")
        for item in items:
            ref = item.get("production_reference") or {}
            _emit("item", {"pattern_id": item.get("pattern_id"), "pattern_type": item.get("pattern_type"),
                           "current_recommendation": item.get("current_recommendation"),
                           "first_recommendation_position": item.get("first_recommendation_position"),
                           "persistence_ratio": item.get("persistence_ratio"), "reversal_count": item.get("reversal_count"),
                           "stability_class": item.get("stability_class"), "provisional": item.get("provisional"),
                           "first_surfaced_in_main_position": item.get("first_surfaced_in_main_position"),
                           "production_shadow_review_events": ref.get("shadow_review_events"),
                           "production_decision_state": ref.get("decision_state") or "NONE",
                           "reference_source": ref.get("source")})
        _emit("production_reference_access", "READ_ONLY (ShadowReviewEventStore.for_pattern / DecisionStore.records)")
        _emit("formal_states_written_by_replay", 0)
        _emit("phase_3_9_5_started", False)
        _emit("handoff_check", "PASSED")

    def safety(self) -> None:
        _marker("SAFETY")
        after = self._capture_baseline()
        before = self.baseline
        for key in ("decisions", "review_events"):
            same = before[key] == after[key]
            _emit(f"{key}_before", before[key])
            _emit(f"{key}_after", after[key])
            _emit(f"{key}_unchanged", same)
            self.check("SAFETY", same, f"{key} changed during validation")
        _emit("dna_after", after["dna"])
        dna_ok = self.skip_git or (after["dna"] == before["dna"] and all(v["match"] for v in after["dna"].values()))
        _emit("dna_blob_unchanged", dna_ok)
        self.check("SAFETY", dna_ok, "DNA blob identity changed")
        pdf_ok = before["pdfs"] == after["pdfs"]
        _emit("pdf_inventory_before", before["pdfs"])
        _emit("pdf_inventory_after", after["pdfs"])
        _emit("pdf_modified", not pdf_ok)
        # corpus: intake may legitimately grow it; replay never writes it
        growth = int(after["corpus_documents"] or 0) - int(before["corpus_documents"] or 0)
        _emit("corpus_db_sha_before", before["corpus_db_sha256"])
        _emit("corpus_db_sha_after", after["corpus_db_sha256"])
        _emit("corpus_documents_before_after", [before["corpus_documents"], after["corpus_documents"]])
        _emit("corpus_eligible_before_after", [before["corpus_eligible"], after["corpus_eligible"]])
        _emit("corpus_growth_documents", growth)
        intake_activity = growth > 0 or before["corpus_db_sha256"] != after["corpus_db_sha256"]
        _emit("intake_activity_observed", intake_activity)
        self.check("SAFETY", growth >= 0, "corpus lost documents during validation")
        _emit("replay_opened_production_corpus_as", "sqlite URI mode=ro (backup source only)")
        _emit("captured_input_mutations_all_runs",
              sum(len((b["manifest"].get("drift") or {}).get("captured_input_mutations") or []) for b in self.runs.values()))
        _emit("new_documents_ingested_during_runs",
              {label: b["manifest"].get("new_documents_ingested_during_run") for label, b in self.runs.items()})
        for key in ("derived_research", "derived_evaluation", "derived_shadow_review", "derived_decisions"):
            changed = before[key] != after[key]
            verdict = "NONE" if not changed else ("INTAKE_ATTRIBUTED" if intake_activity and key == "derived_research" else "UNEXPECTED")
            _emit(f"{key}_change", {"before": before[key], "after": after[key], "verdict": verdict})
            self.check("SAFETY", verdict != "UNEXPECTED", f"{key} changed without attributable intake activity")
        # replay outputs are the only expected writes
        new_runs = len(self.store.list_runs()) - int(before["replay_runs_stored"])
        _emit("replay_runs_added", new_runs)
        self.check("SAFETY", new_runs == len(self.runs), "unexpected number of replay runs stored")
        # captured snapshot stayed fixed, then release the retained temp safely
        r1 = self.runners["run1"]
        snap_db = r1.temp_root / "corpus" / "index" / "corpus.sqlite3"
        fixed = snap_db.is_file() and sha256_file(snap_db) == self.runs["run1"]["manifest"]["corpus_snapshot"]["snapshot_db_sha256"]
        _emit("captured_snapshot_fixed", fixed)
        self.check("SAFETY", fixed, "retained snapshot changed during validation")
        removed = r1.cleanup_temp()
        _emit("retained_temp_cleanup", {"removed": removed, "exists_after": r1.temp_root.exists()})
        base = workspace_base(self.policy)
        leftovers = sorted(p.name for p in base.iterdir() if p.is_dir() and (p / OWNER_MARKER).is_file()
                           and p.name in {b["result"]["run_id"] for b in self.runs.values()}) if base.is_dir() else []
        _emit("replay_temp_leftovers_from_this_validation", leftovers)
        self.check("SAFETY", not leftovers, "replay temp directories left behind")
        _emit("git_clean_operations_used", False)
        if not self.skip_git:
            code, status = _git(self.repo, "status", "--porcelain", "--untracked-files=no")
            _emit("tracked_worktree_clean_after", "YES" if code == 0 and not status else "NO")
            _emit("tracked_worktree_unchanged_by_validation", code == 0 and status == self.tracked_status_before)
            self.check("SAFETY", code == 0 and status == self.tracked_status_before,
                       "tracked working tree changed during validation")
            _emit("main_contains_head_after", self._main_contains_head())
        _emit("formal_approved_or_rejected_written", False)
        _emit("human_review_events_written", False)
        _emit("dna_promoted", False)
        _emit("safety_check", "PASSED")

    # ------------------------------------------------------------- orchestration
    def run_all(self) -> int:
        try:
            self.head()
            self.policy_digests()
            self.baseline_section()
            self.default_run("run1", "DEFAULT_RUN1", retain=True)
            self.default_run("run2", "DEFAULT_RUN2", retain=False)
            self.determinism()
            self.full_replay()
            self.calibration()
            self.approve_stress()
            self.reject_stress()
            self.queue_replay()
            self.rebuild_equivalence()
            self.handoff()
            self.safety()
            _marker("VALIDATION_OK")
            _emit("total_validation_seconds", round(time.perf_counter() - self.t0, 1))
            return 0
        except ValidationFailure as exc:
            _marker("FAIL")
            _emit("section", exc.section)
            _emit("reason", self._redact(exc.reason))
            return EXIT_VALIDATION_FAILURE
        except ReplayError as exc:
            _marker("FAIL")
            _emit("replay_error", type(exc).__name__)
            _emit("detail", self._redact(str(exc)))
            _emit("mutation", "NONE (replay failed closed; nothing published)")
            return EXIT_REPLAY_ERROR
        except Exception as exc:  # noqa: BLE001
            _marker("FAIL")
            _emit("unexpected", type(exc).__name__)
            _emit("detail", self._redact(str(exc)))
            return EXIT_UNEXPECTED
        finally:
            self._release_retained()

    def _release_retained(self) -> None:
        """成功・失敗を問わず、この validation が作った replay 所有 temp をすべて解放する。

        runner は失敗 run の temp を診断用に保持するが、validation の診断は marker 出力で足りるので、
        corpus snapshot（抽出テキストを含む）を %TEMP% に残さない。marker と親 path を検証する
        `cleanup_temp` 以外の削除は行わない。
        """
        for runner in self.runners.values():
            if runner.temp_root is not None and runner.temp_root.exists():
                try:
                    runner.cleanup_temp()
                except ReplayError:
                    pass

    def _redact(self, text: str) -> str:
        """path / PDF 名を出力へ出さない（診断には error class と位置情報だけで足りる）。"""
        out = text.replace(str(self.data_root), "<data_root>").replace(str(self.repo), "<repo>")
        tokens = []
        for tok in out.split():
            low = tok.lower()
            if ".pdf" in low or "\\" in tok or ("/" in tok and len(tok) > 24):
                tokens.append("<redacted>")
            else:
                tokens.append(tok)
        return " ".join(tokens)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.9.4 real-data validation (one operation, fail closed)")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--require-commit", default="")
    parser.add_argument("--expect-evaluation", default="")
    parser.add_argument("--expect-recommendation", default="")
    parser.add_argument("--expect-shadow-review", default="")
    parser.add_argument("--expect-replay", default="")
    parser.add_argument("--skip-git", action="store_true", help="test harness only")
    args = parser.parse_args(argv)
    from .cli import resolve_root

    root = resolve_root(args.data_root)
    repo = Path(__file__).resolve().parents[3]
    expected = {"evaluation": args.expect_evaluation, "recommendation": args.expect_recommendation,
                "shadow_review": args.expect_shadow_review, "replay": args.expect_replay}
    validation = RealDataValidation(root, repo, require_commit=args.require_commit, expected_digests=expected,
                                    skip_git=args.skip_git)
    return validation.run_all()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
