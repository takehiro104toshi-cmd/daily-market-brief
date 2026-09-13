"""Phase 3.9.5 candidate #1 pilot（Windows 実機を 1 操作で・dry-run only・fail closed）。

`python -m src.intelligence.formal_review.pilot --require-commit <sha> --expect-<layer> <digest> ...`

現在の queue を再 build し、**queue_rank == 1 の 1 件だけ**を提示して 2 種類の dry-run を行う。
real Decision は書かない（この module は `dry_run=True` 以外で `decide` を呼ばない。test で静的にも検査する）。
candidate #2 以降は一切表示しない。人間の Shadow Review reason 本文・原文・ファイル名・path は出さない。
出力は ASCII の key=value 行と `::P395C_*::` marker。exit 0 = ok / 3 = FormalReviewError / 4 = pilot 失敗 / 5 = 想定外。
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..corpus.store import corpus_root
from ..corpus_research.store import research_root
from ..decision.corpus_state import CorpusState
from ..decision.store import DECISIONS_FILE, DecisionStoreCorrupt, decisions_root
from ..evaluation.models import APPROVE_RECOMMENDED, REJECT_RECOMMENDED
from ..evaluation.store import EvaluationStore, EvaluationStoreCorrupt, evaluation_root
from ..replay.snapshot import live_corpus_observation
from ..shadow_review.events import EVENTS_FILE as REVIEW_EVENTS_FILE, ShadowReviewStoreCorrupt, shadow_review_root
from ..shadow_review.models import find_forbidden_keys
from .config import APPROVED, KEEP_REVIEWING, REJECTED
from .errors import FormalReviewError
from .ordering import SECTION_APPROVE, SECTION_REJECT, SECTION_REOPEN
from .service import FormalDecisionRequest, FormalReviewService
from .session import candidate_brief, decision_commands, explanation, review_questions, sibling_status
from .store import BUILD_MANIFEST_FILE, QUEUE_FILE, SUMMARY_FILE, formal_review_root
from .validation import DNA_FILES, POLICY_LAYERS, dir_digest, file_identity, git, pdf_digest

EXIT_OK, EXIT_FORMAL_REVIEW, EXIT_PILOT, EXIT_UNEXPECTED = 0, 3, 4, 5
PILOT_ACTOR = "P395_HUMAN_PILOT_PREP"
REASON_MACHINE = ("P395 candidate 1 pilot dry-run of the packet-bound formal action path; "
                  "this run writes nothing and selects nothing on the human's behalf.")
REASON_KEEP = ("P395 candidate 1 pilot dry-run of the keep-reviewing pause path; "
               "this run writes nothing and selects nothing on the human's behalf.")
#: dry-run で出てもよい正当な guard 結果（人間判断が要るだけで pilot の失敗ではない）。
LEGITIMATE_GUARD_RESULTS = ("SIBLING_CONFLICT_BLOCKED", "SIBLING_ACKNOWLEDGEMENT_REQUIRED")
#: 出たら pilot を BLOCKED にする（guard を弱めない）。
BLOCKING_GUARD_RESULTS = ("REPLAY_EVIDENCE_REQUIRED", "STALE_REVIEW_PACKET", "RECOMMENDATION_MISMATCH",
                          "MATERIAL_DIGEST_CHANGED", "PACKET_EVIDENCE_DIGEST_CHANGED", "POLICY_DIGEST_MISMATCH",
                          "DECISION_HEAD_CHANGED", "FORMAL_GATE_NOT_REACHED")
MACHINE_ACTION = {APPROVE_RECOMMENDED: (APPROVED, "approve"), REJECT_RECOMMENDED: (REJECTED, "reject")}


class PilotFailure(Exception):
    def __init__(self, section: str, reason: str) -> None:
        super().__init__(f"{section}: {reason}")
        self.section = section
        self.reason = reason


def _emit(key: str, value: Any) -> None:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    print(f"{key}={value}", flush=True)


def _marker(name: str) -> None:
    print(f"::P395C_{name}::", flush=True)


class CandidateOnePilot:
    def __init__(self, data_root: Path, repo_root: Path, *, require_commit: str = "",
                 expected_digests: Optional[Mapping[str, str]] = None, historical_head: str = "",
                 actor: str = PILOT_ACTOR, skip_git: bool = False,
                 corpus_state_resolver: Optional[Callable[[], CorpusState]] = None,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self.data_root = Path(data_root)
        self.repo = Path(repo_root)
        self.require_commit = require_commit
        self.expected = dict(expected_digests or {})
        self.historical_head = str(historical_head or "")
        self.actor = actor
        self.skip_git = skip_git
        self.resolver = corpus_state_resolver
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.t0 = time.perf_counter()
        self.baseline: Dict[str, Any] = {}
        self.tracked_before = ""
        self.packet: Dict[str, Any] = {}
        self.row: Dict[str, Any] = {}
        self.results: Dict[str, str] = {}

    # ------------------------------------------------------------- generic
    def fail(self, section: str, reason: str) -> None:
        raise PilotFailure(section, reason)

    def check(self, section: str, cond: bool, reason: str) -> None:
        if not cond:
            self.fail(section, reason)

    def service(self) -> FormalReviewService:
        kw: Dict[str, Any] = {"clock": self.clock}
        if self.resolver is not None:
            kw["corpus_state_resolver"] = self.resolver
        return FormalReviewService(self.data_root, **kw)

    def _capture(self) -> Dict[str, Any]:
        dna = {}
        if not self.skip_git:
            for rel in DNA_FILES:
                _, blob = git(self.repo, "rev-parse", f"HEAD:{rel}")
                code, _ = git(self.repo, "diff", "--quiet", "HEAD", "--", rel)
                dna[rel] = {"head_blob": blob[:16], "match": code == 0}
        croot = corpus_root(self.data_root)
        live = live_corpus_observation(croot) if (croot / "index" / "corpus.sqlite3").is_file() else {}
        state = self.service().corpus_state_resolver()
        return {"decisions": file_identity(decisions_root(self.data_root) / DECISIONS_FILE),
                "review_events": file_identity(shadow_review_root(self.data_root) / REVIEW_EVENTS_FILE),
                "dna": dna, "pdfs": pdf_digest(self.data_root),
                "derived_research": dir_digest(research_root(self.data_root)),
                "derived_evaluation": dir_digest(evaluation_root(self.data_root)),
                "derived_shadow_review": dir_digest(shadow_review_root(self.data_root)),
                "corpus": {"documents": live.get("documents", state.documents), "eligible": int(state.eligible),
                           "milestone": state.milestone}}

    # ------------------------------------------------------------- sections
    def head(self) -> None:
        _marker("HEAD")
        if self.skip_git:
            _emit("git", "SKIPPED")
        else:
            code, head = git(self.repo, "rev-parse", "HEAD")
            self.check("HEAD", code == 0 and bool(head), "git rev-parse HEAD failed")
            _emit("head", head)
            _emit("branch", git(self.repo, "rev-parse", "--abbrev-ref", "HEAD")[1])
            if self.require_commit:
                code, _ = git(self.repo, "merge-base", "--is-ancestor", self.require_commit, "HEAD")
                _emit("head_contains_required_commit", "YES" if code == 0 else "NO")
                self.check("HEAD", code == 0, "HEAD does not contain the required commit")
            code, status = git(self.repo, "status", "--porcelain", "--untracked-files=no")
            self.check("HEAD", code == 0, "git status failed")
            self.tracked_before = status
            _emit("tracked_worktree_clean", "YES" if not status else "NO")
            self.check("HEAD", not status, "tracked working tree is not clean")
            for ref in ("origin/main", "main"):
                code, _ = git(self.repo, "rev-parse", "--verify", "--quiet", ref)
                if code != 0:
                    _emit(f"{ref}_contains_head", "ABSENT")
                    continue
                code, _ = git(self.repo, "merge-base", "--is-ancestor", "HEAD", ref)
                _emit(f"{ref}_contains_head", "YES" if code == 0 else "NO")
                self.check("HEAD", code != 0, f"{ref} already contains HEAD (main merged)")
        _emit("data_root_leaf", self.data_root.name)
        _emit("evaluation_store_exists", EvaluationStore(evaluation_root(self.data_root)).exists())
        self.check("HEAD", EvaluationStore(evaluation_root(self.data_root)).exists(), "evaluation store not found")

    def policy(self) -> None:
        _marker("POLICY")
        svc = self.service()
        digests, versions = svc.policy_digests(), svc.policy_versions()
        for layer in POLICY_LAYERS:
            _emit(f"{layer}_version", versions[layer])
            _emit(f"{layer}_digest", digests[layer])
            want = self.expected.get(layer, "")
            if want:
                self.check("POLICY", digests[layer] == want, f"{layer} digest {digests[layer]} != expected {want}")
        _emit("policy_check", "PASSED")

    def baseline_section(self) -> None:
        _marker("BASELINE")
        self.baseline = self._capture()
        for key in ("decisions", "review_events", "dna", "pdfs", "corpus"):
            _emit(key, self.baseline[key])
        self.check("BASELINE", all(v["match"] for v in self.baseline["dna"].values()) or self.skip_git,
                   "DNA working tree differs from HEAD before the pilot")
        _emit("real_decisions_at_start", self.baseline["decisions"]["lines"])
        _emit("baseline_check", "PASSED")

    def build(self) -> None:
        _marker("BUILD")
        svc = self.service()
        t0 = time.perf_counter()
        out = svc.build()
        _emit("build_seconds", round(time.perf_counter() - t0, 3))
        store = svc.store
        manifest, queue = store.manifest(), store.queue()
        pop = manifest.get("population") or {}
        _emit("corpus_documents", (manifest.get("corpus") or {}).get("documents"))
        _emit("corpus_eligible", (manifest.get("corpus") or {}).get("eligible"))
        _emit("primary_candidates", len(pop.get("primary") or []))
        _emit("approve_candidates", (pop.get("by_recommendation") or {}).get(APPROVE_RECOMMENDED, 0))
        _emit("reject_candidates", (pop.get("by_recommendation") or {}).get(REJECT_RECOMMENDED, 0))
        _emit("context_patterns", len(pop.get("context") or []))
        _emit("deferred_candidates", len(queue.get("deferred") or []))
        inputs = manifest.get("inputs") or {}
        _emit("replay_run_id", inputs.get("replay_run_id"))
        _emit("replay_run_digest", inputs.get("replay_run_digest"))
        _emit("replay_run_policy_digests", inputs.get("replay_run_policy_digests"))
        _emit("replay_captured_eligible", inputs.get("replay_captured_eligible"))
        compatible = sum(1 for pid in (pop.get("primary") or [])
                         if ((store.packet(pid) or {}).get("replay") or {}).get("current_compatible"))
        _emit("replay_compatible_candidates", compatible)
        _emit("replay_incompatible_candidates", len(pop.get("primary") or []) - compatible)
        found = find_forbidden_keys(queue) + find_forbidden_keys(manifest)
        self.check("BUILD", not found, f"forbidden keys in derived output: {sorted(set(found))}")
        _emit("forbidden_key_scan", "CLEAN")
        self.check("BUILD", out["mutation"].startswith("DERIVED_ONLY"), "build reported a non-derived mutation")
        after = self._capture()
        self.check("BUILD", after["decisions"] == self.baseline["decisions"], "decision store changed during build")
        _emit("build_check", "PASSED")

    def candidate(self) -> None:
        """queue_rank == 1 を fresh build の結果から選ぶ（historical head は比較にだけ使う）。"""
        _marker("CANDIDATE")
        svc = self.service()
        queue = svc.store.queue()
        rows = [r for name in (SECTION_REJECT, SECTION_APPROVE, SECTION_REOPEN)
                for r in (queue.get("sections") or {}).get(name, [])]
        self.check("CANDIDATE", bool(rows), "the fresh queue has no candidate")
        row = next((r for r in rows if int(r.get("queue_rank", 0)) == 1), None)
        self.check("CANDIDATE", row is not None, "the fresh queue has no queue_rank 1 row")
        self.row = dict(row)
        packet = svc.store.packet(str(row["pattern_id"]))
        self.check("CANDIDATE", packet is not None, "queue_rank 1 has no built packet")
        self.packet = dict(packet)
        _emit("queue_rank", row.get("queue_rank"))
        _emit("pattern_id", row.get("pattern_id"))
        _emit("pattern_type", row.get("pattern_type"))
        _emit("recommendation", row.get("recommendation"))
        _emit("lifecycle", self.packet["identity"].get("lifecycle_status"))
        _emit("allowed_actions", list(self.packet["decision"].get("allowed_next_actions") or []))
        _emit("warnings", [w["code"] for w in self.packet.get("warnings") or []])
        _emit("eligible_support", self.packet["axes"].get("eligible_support"))
        _emit("stability_class", (self.packet.get("replay") or {}).get("stability_class"))
        _emit("first_recommendation_position", (self.packet.get("replay") or {}).get("first_recommendation_position"))
        if self.historical_head:
            changed = str(row.get("pattern_id")) != self.historical_head
            _emit("historical_head_compared", self.historical_head)
            _emit("QUEUE_HEAD_CHANGED", "true" if changed else "false")
            _emit("queue_head_note", "a changed head is not an error; the pilot proceeds with the fresh rank 1")
        _emit("candidates_shown", 1)
        _emit("candidate_check", "PASSED")

    def freshness(self) -> None:
        _marker("FRESHNESS")
        svc = self.service()
        pid = str(self.packet["identity"]["pattern_id"])
        current = svc.current_packet(pid)
        fresh = current["freshness"]["packet_evidence_digest"] == self.packet["freshness"]["packet_evidence_digest"]
        _emit("material_digest_present", bool(self.packet["freshness"]["material_digest"]))
        _emit("packet_evidence_digest_present", bool(self.packet["freshness"]["packet_evidence_digest"]))
        _emit("fresh", fresh)
        if not fresh:
            from .guard import evidence_diff
            _emit("changed_blocks", evidence_diff(self.packet, current))
        self.check("FRESHNESS", fresh, "candidate 1 packet is stale; rebuild and re-review before any decision")
        replay = dict(self.packet.get("replay") or {})
        _emit("replay_compatible", bool(replay.get("available") and replay.get("current_compatible")))
        _emit("replay_evidence_age_eligible_docs", replay.get("evidence_age_eligible_docs"))
        _emit("freshness_check", "PASSED")

    def brief(self) -> None:
        _marker("BRIEF")
        brief = candidate_brief(self.packet, queue_rank=self.row.get("queue_rank"), section=self.row.get("section", ""))
        for key in sorted(k for k in brief if k[0].isdigit()):
            _emit(f"brief_{key}", brief[key])
        _emit("brief_freshness", brief["freshness"])
        found = find_forbidden_keys(brief)
        self.check("BRIEF", not found, f"forbidden keys in the human brief: {sorted(set(found))}")
        _marker("EXPLANATION")
        for line in explanation(self.packet):
            _emit("explanation", line)
        _marker("QUESTIONS")
        for q in review_questions(self.packet):
            _emit(q["id"], q["question"])

    def _dry_run(self, marker: str, action: str, reason: str, *, blocking: bool) -> str:
        _marker(marker)
        svc = self.service()
        pid = str(self.packet["identity"]["pattern_id"])
        acks = tuple(sibling_status(self.packet)["C3_acknowledgement_required_for"]) if action == "approve" else ()
        request = FormalDecisionRequest(pattern_id=pid, action=action, packet_id=self.packet["identity"]["packet_id"],
                                        reason=reason, actor=self.actor, acknowledge_siblings=acks)
        _emit("action", action)
        _emit("acknowledge_siblings", list(acks))
        try:
            result = svc.decide(request, dry_run=True)          # pilot は dry-run 以外で decide を呼ばない
        except FormalReviewError as exc:
            _emit("result", exc.code)
            _emit("mutation", "NONE (guard failed closed)")
            if exc.code in BLOCKING_GUARD_RESULTS:
                self.fail(marker, f"{exc.code} blocks the pilot; do not weaken the guard")
            self.check(marker, exc.code in LEGITIMATE_GUARD_RESULTS, f"unexpected guard result {exc.code}")
            self.results[marker] = exc.code
            return exc.code
        self.check(marker, result["mutation"] == "NONE (dry run)", "dry-run reported a mutation")
        self.check(marker, bool(result["validation"]["ok"]),
                   f"DecisionService.validate rejected the dry-run: {[e.get('code') for e in result['validation']['errors']]}")
        md = dict(result["metadata"])
        _emit("result", "DRY_RUN_PASS")
        _emit("guard_checks_passed", len(result["guard"]["checks_passed"]))
        _emit("metadata_key_count", len(md))
        _emit("metadata_packet_binding", {k: md.get(k) for k in ("packet_id", "packet_evidence_digest", "material_digest")})
        _emit("promotion_status", result["promotion_status"])
        _emit("mutation", result["mutation"])
        self.results[marker] = "DRY_RUN_PASS"
        return "DRY_RUN_PASS"

    def machine_action_dry_run(self) -> None:
        recommendation = str(self.packet["recommendation"]["recommendation"])
        decision_type, action = MACHINE_ACTION.get(recommendation, ("", ""))
        self.check("DRY_RUN_MACHINE_ACTION", bool(action), f"candidate 1 recommendation {recommendation} has no machine action")
        self._dry_run("DRY_RUN_MACHINE_ACTION", action, REASON_MACHINE, blocking=True)
        _emit("machine_consistent_decision_type", decision_type)

    def keep_reviewing_dry_run(self) -> None:
        self._dry_run("DRY_RUN_KEEP_REVIEWING", "keep-reviewing", REASON_KEEP, blocking=False)

    def human_boundary(self) -> None:
        _marker("HUMAN_DECISION")
        recommendation = str(self.packet["recommendation"]["recommendation"])
        _emit("machine_recommendation", recommendation)
        _emit("machine_recommended_formal_action", MACHINE_ACTION.get(recommendation, ("", ""))[0])
        _emit("technical_dry_run_result", self.results.get("DRY_RUN_MACHINE_ACTION", ""))
        _emit("keep_reviewing_dry_run_result", self.results.get("DRY_RUN_KEEP_REVIEWING", ""))
        _emit("human_selected_action", "PENDING")
        _emit("human_reason", "PENDING")
        _emit("note", "the dry-run is a technical proof only and is not the human's chosen action")

    def commands(self) -> None:
        _marker("COMMANDS")
        for entry in decision_commands(self.packet, actor="<human-actor-id>"):
            _emit("stage_1_dry_run", {"decision_type": entry["decision_type"], "command": entry["stage_1_dry_run"]})
            _emit("stage_2_real_write", {"decision_type": entry["decision_type"], "command": entry["stage_2_real_write"],
                                         "confirmation_token": entry["confirmation_token"],
                                         "acknowledge_siblings_required": entry["acknowledge_siblings_required"]})
        _emit("stage_2_authorisation", "NOT AUTHORISED IN THIS PILOT; stage 2 waits for the Supervisor and the human decision")

    def safety(self) -> None:
        _marker("SAFETY")
        after = self._capture()
        before = self.baseline
        for key in ("decisions", "review_events"):
            same = before[key] == after[key]
            _emit(f"{key}_before", before[key])
            _emit(f"{key}_after", after[key])
            _emit(f"{key}_unchanged", same)
            self.check("SAFETY", same, f"{key} changed during the pilot")
        dna_ok = self.skip_git or (after["dna"] == before["dna"] and all(v["match"] for v in after["dna"].values()))
        _emit("dna_blob_unchanged", dna_ok)
        self.check("SAFETY", dna_ok, "DNA blob identity changed")
        _emit("pdf_inventory_unchanged", before["pdfs"] == after["pdfs"])
        self.check("SAFETY", before["pdfs"] == after["pdfs"], "PDF inventory changed")
        intake = before["corpus"] != after["corpus"] or before["derived_evaluation"] != after["derived_evaluation"]
        _emit("intake_activity_observed", intake)
        for key in ("derived_research", "derived_evaluation", "derived_shadow_review"):
            changed = before[key] != after[key]
            verdict = "NONE" if not changed else ("INTAKE_ATTRIBUTED" if intake else "UNEXPECTED")
            _emit(f"{key}_change", verdict)
            self.check("SAFETY", verdict != "UNEXPECTED", f"{key} changed without intake activity")
        root = formal_review_root(self.data_root)
        present = {p.name for p in root.iterdir()} if root.is_dir() else set()
        _emit("formal_review_files", sorted(present))
        self.check("SAFETY", {BUILD_MANIFEST_FILE, QUEUE_FILE, SUMMARY_FILE} <= present
                   and present <= {BUILD_MANIFEST_FILE, QUEUE_FILE, SUMMARY_FILE, "packets"},
                   "unexpected files under compass_formal_review")
        _emit("real_decisions_written", after["decisions"]["lines"] - before["decisions"]["lines"])
        _emit("promotion_status_written", "NONE (no decision written)")
        if not self.skip_git:
            code, status = git(self.repo, "status", "--porcelain", "--untracked-files=no")
            _emit("tracked_worktree_unchanged", code == 0 and status == self.tracked_before)
            self.check("SAFETY", code == 0 and status == self.tracked_before, "tracked working tree changed")
        _emit("safety_check", "PASSED")

    # ------------------------------------------------------------- orchestration
    def run_all(self) -> int:
        try:
            self.head()
            self.policy()
            self.baseline_section()
            self.build()
            self.candidate()
            self.freshness()
            self.brief()
            self.machine_action_dry_run()
            self.keep_reviewing_dry_run()
            self.human_boundary()
            self.commands()
            self.safety()
            _marker("PILOT_OK")
            _emit("candidates_reviewed", 1)
            _emit("total_pilot_seconds", round(time.perf_counter() - self.t0, 1))
            return EXIT_OK
        except PilotFailure as exc:
            _marker("FAIL")
            _emit("section", exc.section)
            _emit("reason", self._redact(exc.reason))
            return EXIT_PILOT
        except FormalReviewError as exc:
            _marker("FAIL")
            _emit("section", "FORMAL_REVIEW")
            _emit("reason", self._redact(f"{exc.code}: {exc.message}"))
            return EXIT_FORMAL_REVIEW
        except (DecisionStoreCorrupt, EvaluationStoreCorrupt, ShadowReviewStoreCorrupt) as exc:
            _marker("FAIL")
            _emit("section", "STORE_CORRUPT")
            _emit("reason", self._redact(f"{type(exc).__name__}: {exc}"))
            return EXIT_PILOT
        except Exception as exc:  # noqa: BLE001
            _marker("FAIL")
            _emit("section", "UNEXPECTED")
            _emit("reason", self._redact(f"{type(exc).__name__}: {exc}"))
            return EXIT_UNEXPECTED

    def _redact(self, text: str) -> str:
        out = text.replace(str(self.data_root), "<data_root>").replace(str(self.repo), "<repo>")
        tokens = []
        for tok in out.split():
            low = tok.lower()
            if ".pdf" in low or "\\" in tok or ("/" in tok and len(tok) > 24):
                tokens.append("<redacted>")
            else:
                tokens.append(tok)
        return " ".join(tokens)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.9.5 candidate #1 pilot (read-only, dry-run only, fail closed)")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--require-commit", default="")
    for layer in POLICY_LAYERS:
        parser.add_argument(f"--expect-{layer.replace('_', '-')}", default="", dest=f"expect_{layer}")
    parser.add_argument("--historical-head", default="", help="informational comparison only; never used for selection")
    parser.add_argument("--actor", default=PILOT_ACTOR)
    parser.add_argument("--skip-git", action="store_true", help="test harness only")
    args = parser.parse_args(list(argv) if argv is not None else None)
    from .cli import resolve_root

    root = resolve_root(args.data_root)
    repo = Path(__file__).resolve().parents[3]
    expected = {layer: getattr(args, f"expect_{layer}") for layer in POLICY_LAYERS}
    return CandidateOnePilot(root, repo, require_commit=args.require_commit, expected_digests=expected,
                             historical_head=args.historical_head, actor=args.actor, skip_git=args.skip_git).run_all()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
