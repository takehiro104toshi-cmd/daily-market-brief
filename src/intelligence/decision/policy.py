"""Decision policy（Phase 3.9.1）— config.yaml `compass_decision`。versioned。silent change 禁止。

frozen policy（PHASE_3_9_SPECIFICATION_FREEZE_V1）:
- formal APPROVED は CORPUS_100（eligible document ≥ 100）まで禁止（SHADOW MODE）。
- auto approval は無い（False 以外は fail closed）。
- formal decision は人間の明示 action と非空 reason を要求する。
Phase 3.9.2 の評価 threshold はここに入れない。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

CONFIG_SECTION = "compass_decision"

#: frozen policy の下限。config で 100 未満にはできない（変更は policy freeze の改訂 = version bump が必要）。
FORMAL_REVIEW_MIN_CORPUS_FLOOR = 100

KEEP_REVIEWING = "KEEP_REVIEWING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
REOPENED_FOR_REVIEW = "REOPENED_FOR_REVIEW"
SUPERSEDED = "SUPERSEDED"
RETIRED = "RETIRED"
DECISION_STATES: Tuple[str, ...] = (KEEP_REVIEWING, APPROVED, REJECTED, REOPENED_FOR_REVIEW, SUPERSEDED, RETIRED)

#: previous effective state（None = 履歴なし）→ 許される次の decision_type。frozen policy §12 の最小集合。
#: SUPERSEDED / RETIRED は v1 では terminal（reopen 可否は監督者判断: 勝手に広げない）。
ALLOWED_TRANSITIONS: Dict[Optional[str], FrozenSet[str]] = {
    None: frozenset({KEEP_REVIEWING, APPROVED, REJECTED}),
    KEEP_REVIEWING: frozenset({KEEP_REVIEWING, APPROVED, REJECTED}),
    APPROVED: frozenset({SUPERSEDED, RETIRED}),
    REJECTED: frozenset({REOPENED_FOR_REVIEW}),
    REOPENED_FOR_REVIEW: frozenset({KEEP_REVIEWING, APPROVED, REJECTED}),
    SUPERSEDED: frozenset(),
    RETIRED: frozenset(),
}

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class PolicyError(ValueError):
    """policy が frozen 仕様に反する（fail closed）。"""


@dataclass(frozen=True)
class DecisionPolicy:
    policy_version: str = "1.0.0"
    formal_review_min_corpus: int = 100                 # CORPUS_100 gate（eligible_for_pattern_evidence）
    auto_approval: bool = False                         # 常に False（True は PolicyError）
    reason_required_states: Tuple[str, ...] = DECISION_STATES      # 保守的: 全 decision に非空 reason
    human_only_states: Tuple[str, ...] = DECISION_STATES           # 保守的: 全 decision は HUMAN actor のみ

    def as_dict(self) -> Dict[str, Any]:
        return {"policy_version": self.policy_version,
                "formal_review_min_corpus": self.formal_review_min_corpus,
                "auto_approval": self.auto_approval,
                "reason_required_states": list(self.reason_required_states),
                "human_only_states": list(self.human_only_states),
                "allowed_transitions": {str(k or "NONE"): sorted(v) for k, v in ALLOWED_TRANSITIONS.items()}}

    def digest(self) -> str:
        """policy 内容の content hash。同じ policy_version で digest が変わる = silent change（append 拒否）。"""
        blob = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def validate(self) -> None:
        if not _SEMVER.match(self.policy_version or ""):
            raise PolicyError(f"policy_version must be semver: {self.policy_version!r}")
        if self.auto_approval is not False:
            raise PolicyError("auto_approval must be false (frozen policy: no auto approval)")
        if int(self.formal_review_min_corpus) < FORMAL_REVIEW_MIN_CORPUS_FLOOR:
            raise PolicyError(f"formal_review_min_corpus must be >= {FORMAL_REVIEW_MIN_CORPUS_FLOOR}")
        for s in self.reason_required_states + self.human_only_states:
            if s not in DECISION_STATES:
                raise PolicyError(f"unknown decision state in policy: {s}")
        if APPROVED not in self.reason_required_states or APPROVED not in self.human_only_states:
            raise PolicyError("APPROVED must require a human actor and a reason")


def config_from_mapping(section: Optional[Mapping[str, Any]]) -> DecisionPolicy:
    s = dict(section or {})
    base = DecisionPolicy()
    raw_auto = s.get("auto_approval", base.auto_approval)
    if isinstance(raw_auto, str):
        raw_auto = raw_auto.strip().lower() in ("true", "1", "yes")
    try:
        min_corpus = int(s.get("formal_review_min_corpus", base.formal_review_min_corpus))
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"formal_review_min_corpus must be an integer: {exc}") from exc
    policy = DecisionPolicy(policy_version=str(s.get("policy_version", base.policy_version) or base.policy_version),
                            formal_review_min_corpus=min_corpus, auto_approval=bool(raw_auto))
    policy.validate()
    return policy


def load_decision_policy(config_path: Path = Path("config.yaml")) -> DecisionPolicy:
    """config.yaml の `compass_decision` を読む（無ければ既定値）。不正値は PolicyError（fail closed）。"""
    section: Mapping[str, Any] = {}
    if config_path.is_file():
        try:
            import yaml

            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            section = raw.get(CONFIG_SECTION) or {}
        except Exception:  # noqa: BLE001 設定ファイル破損 → 既定 policy（frozen 値）へ
            section = {}
    return config_from_mapping(section)
