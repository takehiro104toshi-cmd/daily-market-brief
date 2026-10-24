"""P12-A3 — crash の窓の決定論の分類（証拠を読むだけ ・何も書かない ・回復は A4）。

run_id ごとに、ledger の状態 ・run の directory（final ／ .partial）・checkpoint ・status を見て 1 つの分類を返す:
- `NOT_STARTED`                ledger に無く ・directory も無い
- `IN_FLIGHT`                  ledger の最後が PLANNED ／ RUNNING で、final も .partial も無い（crash か実行中）
- `PARTIAL_PRESENT`            `.partial` が在る（finalize の途中で止まった。A4 の分類に予約）
- `ORPHANED_FINALIZATION`      final の directory が在るのに ledger に SUCCEEDED ／ ORPHANED_FINALIZATION の終端が無い（窓 A。A4 で回復済みを除外）
- `LEDGER_COMMITTED_CHECKPOINT_STALE`  ledger に正しい新しい尾があり checkpoint が追いついていない（窓 B）
- `STATUS_STALE`               ledger と checkpoint は一致し、status が無い ・古い（窓 C）
- `COMMITTED`                  終端の record ・checkpoint ・status が全て一致（SUCCEEDED の時は final が在る）
- `FINAL_MISSING`              ledger は SUCCEEDED なのに final の directory が無い（外からの削除 ・移動）
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .finalization import PARTIAL_SUFFIX, run_directory
from .head_checkpoint import CHECKPOINT_STALE
from .ledger_store import LedgerState
from .run_state import RunState, is_terminal
from .status_store import STATUS_OK, classify_status

CLASSIFICATIONS = ("NOT_STARTED", "IN_FLIGHT", "PARTIAL_PRESENT", "ORPHANED_FINALIZATION", "LEDGER_COMMITTED_CHECKPOINT_STALE",
                   "STATUS_STALE", "COMMITTED", "FINAL_MISSING")


@dataclass(frozen=True)
class RunEvidence:
    run_id: str
    ledger_state: Optional[str]            # run の最後の状態（無ければ None）
    final_present: bool
    partial_present: bool
    checkpoint_class: str
    status_class: str
    classification: str

    def to_dict(self) -> Dict[str, Any]:
        return {"run_id": self.run_id, "ledger_state": self.ledger_state, "final_present": self.final_present,
                "partial_present": self.partial_present, "checkpoint_class": self.checkpoint_class,
                "status_class": self.status_class, "classification": self.classification}


def classify_run(p12_root: Any, run_id: str, state: LedgerState) -> RunEvidence:
    final = run_directory(p12_root, run_id)
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    final_present, partial_present = final.is_dir(), partial.exists()
    run_state = state.run_states.get(run_id)
    status_class = classify_status(p12_root, state)
    if partial_present:
        classification = "PARTIAL_PRESENT"
    elif final_present and run_state not in (RunState.SUCCEEDED, RunState.ORPHANED_FINALIZATION):
        classification = "ORPHANED_FINALIZATION"                                       # A4: 回復済み（終端 ORPHANED_FINALIZATION）は孤児ではない
    elif run_state is None:
        classification = "NOT_STARTED"
    elif not is_terminal(run_state):
        classification = "IN_FLIGHT"
    elif run_state is RunState.SUCCEEDED and not final_present:
        classification = "FINAL_MISSING"
    elif state.checkpoint_class == CHECKPOINT_STALE:
        classification = "LEDGER_COMMITTED_CHECKPOINT_STALE"
    elif status_class != STATUS_OK:
        classification = "STATUS_STALE"
    else:
        classification = "COMMITTED"
    return RunEvidence(run_id=run_id, ledger_state=None if run_state is None else run_state.value, final_present=final_present,
                       partial_present=partial_present, checkpoint_class=state.checkpoint_class, status_class=status_class,
                       classification=classification)


__all__ = ["CLASSIFICATIONS", "RunEvidence", "classify_run"]
