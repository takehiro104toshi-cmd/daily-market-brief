"""P12-A2 — 凍結の P11 の read-only adapter で、明示の PIT の Personal Intelligence の snapshot を導く（派生だけ ・昇格しない）。

- `build_snapshot(request, roots)`: `read_ui_model(p10_root, p9_root, at=scheduled_for, as_of_date=as_of_date)`（P11-A1 の governed な
  read の面だけ。P10 の store ・P9 の snapshot は直接触れない）→ `ui_model_json_bytes`（P11 の正準な byte）。
- `AutomationSnapshot`: 安全な metadata（run_id ・scheduled_for ・as_of_date ・P11 の runtime anchor ・adapter の版 ・model の digest ・
  件数）と private な body（P11 の UI model の byte。P12 の private な run の directory にだけ置く）。
- P11 の型つきの失敗は `SOURCE_INCOMPLETE:<P11 code>` に写す（detail は P11 の大文字の code だけ）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict

from ..personal_ui.p10_read_adapter import ADAPTER_RULES_VERSION, read_ui_model
from ..personal_ui.ui_model import UiModel, UiReadError, ui_model_json_bytes
from .canonical import date_iso, utc_iso
from .execution_request import AutomationExecutionRequest
from .failure_codes import AutomationError
from .frozen_anchors import P11_FROZEN_ANCHOR
from .preconditions import PrivateRoots

SNAPSHOT_SCHEMA_VERSION = "p12_automation_snapshot:0.1.0"


@dataclass(frozen=True, repr=False)
class AutomationSnapshot:
    run_id: str
    scheduled_for: str
    as_of_date: str
    p11_runtime_anchor: str
    adapter_rules_version: str
    model_schema_version: str
    model_digest: str
    entry_count: int
    focus_count: int
    mute_count: int
    excluded_count: int
    unmatched_live_marks: int
    body: bytes                                      # private: P11 の UI model の正準な byte

    def __repr__(self) -> str:
        return f"AutomationSnapshot(run_id={self.run_id!r}, model_digest={self.model_digest!r})"

    def to_safe_dict(self) -> Dict[str, Any]:
        return {"schema_version": SNAPSHOT_SCHEMA_VERSION, "run_id": self.run_id, "scheduled_for": self.scheduled_for,
                "as_of_date": self.as_of_date, "p11_runtime_anchor": self.p11_runtime_anchor,
                "adapter_rules_version": self.adapter_rules_version, "model_schema_version": self.model_schema_version,
                "model_digest": self.model_digest, "entry_count": self.entry_count, "focus_count": self.focus_count,
                "mute_count": self.mute_count, "excluded_count": self.excluded_count,
                "unmatched_live_marks": self.unmatched_live_marks}


def snapshot_from_model(request: AutomationExecutionRequest, model: UiModel) -> AutomationSnapshot:
    body = ui_model_json_bytes(model)
    return AutomationSnapshot(run_id=request.run_id, scheduled_for=utc_iso(request.scheduled_for),
                              as_of_date=date_iso(request.as_of_date), p11_runtime_anchor=P11_FROZEN_ANCHOR,
                              adapter_rules_version=ADAPTER_RULES_VERSION, model_schema_version=model.schema_version,
                              model_digest=hashlib.sha256(body).hexdigest(), entry_count=len(model.entries),
                              focus_count=sum(1 for e in model.entries if e.attention == "FOCUS"),
                              mute_count=sum(1 for e in model.entries if e.attention == "MUTE"),
                              excluded_count=sum(1 for e in model.entries if e.surface_group == "EXCLUDED_BY_PROFILE"),
                              unmatched_live_marks=model.unmatched_live_mark_count, body=body)


def build_snapshot(request: AutomationExecutionRequest, roots: PrivateRoots) -> AutomationSnapshot:
    if not isinstance(request, AutomationExecutionRequest) or not isinstance(roots, PrivateRoots):
        raise AutomationError("SCHEMA_INVALID", "SNAPSHOT_INPUT")
    try:
        model = read_ui_model(roots.p10_root, roots.p9_root, at=request.scheduled_for, as_of_date=request.as_of_date)
    except UiReadError as exc:
        raise AutomationError("SOURCE_INCOMPLETE", exc.code) from None               # P11 の code だけ（detail の id ・path は捨てる）
    return snapshot_from_model(request, model)


__all__ = ["SNAPSHOT_SCHEMA_VERSION", "AutomationSnapshot", "build_snapshot", "snapshot_from_model"]
