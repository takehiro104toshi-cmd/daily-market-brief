"""QA Assessment永続化（Phase 1-E）。data/vnext/evidence_qa/（git非管理）。

append-only / immutable:
- assessmentは上書き・削除しない。新policy versionでの再評価は**新レコード追記**。
- 「現在の判定」は履歴からの導出（latest_for）——二重保存しない。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from ..core import serialization
from .model import EvidenceAssessment


class JsonlAssessmentStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "assessments.jsonl"
        serialization.register_domain_types()
        self._assessments: List[EvidenceAssessment] = []
        self.recovered_lines = 0
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._assessments.append(serialization.decode(json.loads(line)))
                except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                    self.recovered_lines += 1  # crash-safe: 破損行は読み飛ばし件数申告

    def add_assessment(self, assessment: EvidenceAssessment) -> bool:
        line = json.dumps(serialization.encode(assessment), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._assessments.append(assessment)
        return True

    def iter_assessments(self) -> Iterator[EvidenceAssessment]:
        return iter(list(self._assessments))

    def assessments_for(self, record_id: str) -> Tuple[EvidenceAssessment, ...]:
        """あるレコードの評価履歴（時系列。旧assessmentも保存され続ける）。"""
        # 安定ソート: assessed_at同時刻は追記順を保持（append-onlyログの自然順）
        return tuple(
            sorted(
                (a for a in self._assessments if a.record_id == record_id),
                key=lambda a: a.assessed_at,
            )
        )

    def latest_for(
        self, record_id: str, policy_name: Optional[str] = None
    ) -> Optional[EvidenceAssessment]:
        """現在有効な判定＝履歴からの導出（上書き保存しない）。"""
        candidates = [
            a for a in self.assessments_for(record_id)
            if policy_name is None or a.policy_name == policy_name
        ]
        return candidates[-1] if candidates else None
