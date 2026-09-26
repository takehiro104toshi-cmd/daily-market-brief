"""EvaluationStore — Phase 5 P5-2B（凍結 EvaluationRecord の追記専用 JSONL journal）。

答える問い: 「不変の EvaluationRecord を、上書き・黙った訂正・supersession 履歴の喪失なしに
どう永続化し、どう読むか」。市場評価 engine・PredictionRecord → EvaluationRecord の自動化・
TOPIX / 取引カレンダー / J-Quants 参照・return 計算・較正・「現在の評価」の解決・runtime 統合は
**含まない**（P5-2C 以降）。

権威と layout（`docs/databank/PHASE5_ENTRY_CONTRACT.md` §8 / §15）:

    <data_root>/predictions/evaluations.jsonl     canonical・追記専用・不変（JSONL が唯一の権威）

predictions.jsonl（PredictionStore）とは**別の**追記専用の権威であり、本 store は
predictions.jsonl を開かず、PredictionStore を import せず、PredictionRecord を変更も補強も
しない（参照は `prediction_id` だけ）。

- **data_root は呼び出し側が明示する。** 既定値・環境変数・config・production / research root
  への暗黙 fallback を持たない。読むだけではディレクトリもファイルも作らない。
- **追記専用。** open mode は `"a"` のみ。上書き・truncate・rename・削除・rewrite の経路が無い。
  Git 操作・network・SQLite・hash chain・transaction を持たない。in-memory index は JSONL から
  毎回再構築する導出物。
- **append 契約（§4）:**
    - 未知 `evaluation_id`                        → 1 行だけ追記（`APPENDED`, wrote_line=True）
    - 既知 id ＋ canonical 行が byte 一致           → 冪等 no-op（`ALREADY_PRESENT`, wrote_line=False）
    - 既知 id ＋ 保存内容のいずれかの field が異なる → `EvaluationConflict`（fail closed。
      provenance の merge・created_at / observation id / close / 検証の更新・DEFERRED の
      EVALUATED への書き換えをしない。2 行目も書かない）
  provenance / audit は `evaluation_id` に入らないため、**同じ id だけでは冪等とみなさない**。
- **supersession は append であって update ではない（§5）。** 訂正 record は
  `supersedes_evaluation_id` を持つ**新しい物理行**として追記され、前の行は物理的にも論理的にも
  変更されない（inactive mark も可変 status も付けない）。「現在の評価」はここで解決しない。
- **supersession の整合（§6 / §9）:** append 時・権威 load 時ともに、前任 record が**同じ journal に
  物理的に先行して存在**し（dangling / forward reference を拒否）、かつ同じ評価 subject
  （`prediction_id` / `target` / `reference_session` / `session_date` / `classification_version`）で
  あることを要求する。値の変化は要求しない（同じ数値への訂正も正当な履歴。§7）。
  DEFERRED → EVALUATED / EVALUATED → EVALUATED / DEFERRED → DEFERRED の履歴を許す（§8）。
  自己 supersession は record 境界が拒否し、後方参照しか許さないため cycle は成立しない。
- **物理順が歴史（§11）。** `iter_records()` は物理行順。session / created_at / id で並べ替えず、
  「最新」を返す API を持たない。
- **journal 直列化（§12）**は identity 直列化と別の関心事: `EvaluationRecord.as_dict()` を
  key 昇順・compact separators・`ensure_ascii=False`・UTF-8・`"\\n"` 終端で 1 行に書く。
  Decimal は P5-2A の canonical 表現のまま（再丸め・再分類・outcome 再計算をしない）。
- **load は fail closed（§10）。** 非 UTF-8・終端切れ・空行・不正 JSON・非 object・未知 field・
  schema 違反・偽造 id・非 canonical 行・物理重複（同一 / 矛盾）・dangling supersession・
  subject 不一致 supersession は `EvaluationJournalCorrupt`（行番号と理由コード付き）。
  skip・修復・dedup・reorder・migration-on-read をしない。
- **書き込み規律（§13）:** 初回 append でのみ親ディレクトリ作成 → `open("a", encoding="utf-8",
  newline="\\n")` → 1 行を 1 回の write → `flush()` → `os.fsync()`。
- **SINGLE WRITER（§14）。** 開いてから（または最後の append から）journal の byte 長が外部要因で
  変わっていれば append は `ConcurrentModificationDetected` で fail closed する（検知であって
  排他ではない。`reload()` で権威から再構築できる）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple, Union

from .evaluation_record import EvaluationRecord, InvalidEvaluationRecord

#: layout（契約 §8 凍結）
PREDICTIONS_DIRNAME = "predictions"
JOURNAL_FILENAME = "evaluations.jsonl"
JOURNAL_ENCODING = "utf-8"
LINE_TERMINATOR = "\n"

#: 書き込み契約（§14）。単一 writer のみを支援するという**制限**の宣言。
SINGLE_WRITER_ONLY = True

#: supersession が同一 subject であるために一致を要求する field（§9）
SUPERSESSION_SUBJECT_FIELDS: Tuple[str, ...] = (
    "prediction_id", "target", "reference_session", "session_date", "classification_version",
)

#: load 時の整合性違反コード（決定論的・fail closed）
CORRUPTION_REASONS: Tuple[str, ...] = (
    "INVALID_ENCODING",
    "TRUNCATED_FINAL_LINE",
    "BLANK_LINE",
    "MALFORMED_JSON",
    "NOT_AN_OBJECT",
    "INVALID_RECORD",
    "NON_CANONICAL_LINE",
    "PHYSICAL_DUPLICATE_IDENTICAL",
    "PHYSICAL_DUPLICATE_CONFLICTING",
    "DANGLING_SUPERSESSION",
    "INCOMPATIBLE_SUPERSESSION",
)

#: append 時の supersession 拒否コード（load 時の同名 corruption と同じ意味）
SUPERSESSION_REJECTIONS: Tuple[str, ...] = ("DANGLING_SUPERSESSION", "INCOMPATIBLE_SUPERSESSION")


class EvaluationAppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class EvaluationAppendResult:
    status: EvaluationAppendStatus
    evaluation_id: str
    wrote_line: bool
    line_number: int  # 1 始まりの物理行（既存行 or 追記行）


class EvaluationJournalError(Exception):
    """journal 操作の fail-closed 基底。"""


class EvaluationJournalCorrupt(EvaluationJournalError):
    """権威 load 時の整合性違反（黙って skip / dedup / 修復しない）。"""

    def __init__(self, path: Path, line_number: int, reason: str, detail: str = "") -> None:
        if reason not in CORRUPTION_REASONS:
            raise ValueError(f"unknown corruption reason: {reason!r}")
        self.path = Path(path)
        self.line_number = line_number
        self.reason = reason
        self.detail = detail
        suffix = f": {detail}" if detail else ""
        super().__init__(f"{reason} at {self.path.name}:{line_number}{suffix}")


class EvaluationConflict(EvaluationJournalError):
    """同じ evaluation_id で保存内容が異なる（provenance / audit を merge・更新しない）。"""

    def __init__(self, evaluation_id: str, differing_fields: Tuple[str, ...]) -> None:
        self.evaluation_id = evaluation_id
        self.differing_fields = differing_fields
        super().__init__(
            f"evaluation_id {evaluation_id} already stored with different "
            f"{', '.join(differing_fields) or 'bytes'}")


class SupersessionRejected(EvaluationJournalError):
    """append 時: 前任が journal に無い / 同じ subject でない（fail closed）。"""

    def __init__(self, evaluation_id: str, reason: str, detail: str = "") -> None:
        if reason not in SUPERSESSION_REJECTIONS:
            raise ValueError(f"unknown supersession rejection: {reason!r}")
        self.evaluation_id = evaluation_id
        self.reason = reason
        self.detail = detail
        suffix = f": {detail}" if detail else ""
        super().__init__(f"{reason} for {evaluation_id}{suffix}")


class ConcurrentModificationDetected(EvaluationJournalError):
    """開いてから journal が外部要因で変わった（単一 writer 境界の違反を検知）。"""


# ---------------------------------------------------------------- path / serialization

def evaluations_path(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    """`<data_root>/predictions/evaluations.jsonl`（data_root は呼び出し側が明示する）。"""
    if data_root is None or str(data_root) == "":
        raise ValueError("data_root must be an explicit, non-empty path")
    return Path(data_root) / PREDICTIONS_DIRNAME / JOURNAL_FILENAME


def serialize_evaluation(record: EvaluationRecord) -> str:
    """journal 1 行（canonical・決定論的・`\\n` 終端）。identity 直列化とは別の関心事。"""
    if not isinstance(record, EvaluationRecord):
        raise TypeError("only EvaluationRecord can be journaled")
    return json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + LINE_TERMINATOR


def parse_evaluation_line(line: str, *, path: Path, line_number: int) -> EvaluationRecord:
    """1 行 → EvaluationRecord（凍結 `from_dict` 境界で検証。非 canonical は拒否・修復しない）。"""
    if not line.endswith(LINE_TERMINATOR):
        raise EvaluationJournalCorrupt(path, line_number, "TRUNCATED_FINAL_LINE")
    body = line[:-1]
    if body.strip() == "":
        raise EvaluationJournalCorrupt(path, line_number, "BLANK_LINE")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise EvaluationJournalCorrupt(path, line_number, "MALFORMED_JSON",
                                       f"col {exc.colno}") from None
    if not isinstance(data, dict):
        raise EvaluationJournalCorrupt(path, line_number, "NOT_AN_OBJECT")
    try:
        record = EvaluationRecord.from_dict(data)
    except (InvalidEvaluationRecord, ValueError, TypeError, KeyError) as exc:
        raise EvaluationJournalCorrupt(path, line_number, "INVALID_RECORD", str(exc)) from exc
    if serialize_evaluation(record) != line:
        raise EvaluationJournalCorrupt(path, line_number, "NON_CANONICAL_LINE")
    return record


def supersession_mismatch(predecessor: EvaluationRecord, successor: EvaluationRecord) -> Tuple[str, ...]:
    """同じ評価 subject でない field 名（空なら同一 subject）。値の変化は問わない（§7）。"""
    return tuple(name for name in SUPERSESSION_SUBJECT_FIELDS
                 if getattr(predecessor, name) != getattr(successor, name))


# ---------------------------------------------------------------- store

@dataclass(frozen=True)
class _Entry:
    line_number: int
    line: str
    record: EvaluationRecord


class EvaluationStore:
    """追記専用 EvaluationRecord journal（JSONL が権威。index は導出物。predictions.jsonl に触れない）。"""

    def __init__(self, data_root: Union[str, "os.PathLike[str]"]) -> None:
        self.data_root = Path(data_root)
        self.path = evaluations_path(data_root)
        self._entries: Dict[str, _Entry] = {}
        self._expected_size = 0
        self.reload()

    # ------------------------------------------------------------ authoritative load

    def reload(self) -> int:
        """JSONL から in-memory index を全再構築する（fail closed）。件数を返す。"""
        entries: Dict[str, _Entry] = {}
        raw = self.path.read_bytes() if self.path.exists() else b""
        try:
            text = raw.decode(JOURNAL_ENCODING)
        except UnicodeDecodeError as exc:
            raise EvaluationJournalCorrupt(self.path, 0, "INVALID_ENCODING",
                                           f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            last_number = text.count(LINE_TERMINATOR) + 1
            raise EvaluationJournalCorrupt(self.path, last_number, "TRUNCATED_FINAL_LINE")
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            record = parse_evaluation_line(line, path=self.path, line_number=line_number)
            previous = entries.get(record.evaluation_id)
            if previous is not None:
                reason = ("PHYSICAL_DUPLICATE_IDENTICAL" if previous.line == line
                          else "PHYSICAL_DUPLICATE_CONFLICTING")
                raise EvaluationJournalCorrupt(
                    self.path, line_number, reason,
                    f"{record.evaluation_id} first seen at line {previous.line_number}")
            if record.supersedes_evaluation_id:
                predecessor = entries.get(record.supersedes_evaluation_id)
                if predecessor is None:                      # dangling / forward reference
                    raise EvaluationJournalCorrupt(
                        self.path, line_number, "DANGLING_SUPERSESSION",
                        f"{record.supersedes_evaluation_id} not physically before line {line_number}")
                mismatch = supersession_mismatch(predecessor.record, record)
                if mismatch:
                    raise EvaluationJournalCorrupt(
                        self.path, line_number, "INCOMPATIBLE_SUPERSESSION",
                        f"differs from predecessor in {', '.join(mismatch)}")
            entries[record.evaluation_id] = _Entry(line_number, line, record)
        self._entries = entries
        self._expected_size = len(raw)
        return len(entries)

    # ------------------------------------------------------------ append（追記専用）

    def append(self, record: EvaluationRecord) -> EvaluationAppendResult:
        line = serialize_evaluation(record)
        # 書いた bytes がそのまま同じ記録として読めることを、書く前に凍結境界で確かめる
        if parse_evaluation_line(line, path=self.path, line_number=0) != record:
            raise EvaluationJournalError("record does not survive its own canonical round-trip")
        existing = self._entries.get(record.evaluation_id)
        if existing is not None:
            if existing.line == line:
                return EvaluationAppendResult(EvaluationAppendStatus.ALREADY_PRESENT,
                                              record.evaluation_id, wrote_line=False,
                                              line_number=existing.line_number)
            raise EvaluationConflict(record.evaluation_id,
                                     _differing_fields(existing.record, record))
        if record.supersedes_evaluation_id:
            predecessor = self._entries.get(record.supersedes_evaluation_id)
            if predecessor is None:
                raise SupersessionRejected(record.evaluation_id, "DANGLING_SUPERSESSION",
                                           f"{record.supersedes_evaluation_id} is not in this journal")
            mismatch = supersession_mismatch(predecessor.record, record)
            if mismatch:
                raise SupersessionRejected(record.evaluation_id, "INCOMPATIBLE_SUPERSESSION",
                                           f"differs from predecessor in {', '.join(mismatch)}")
        self._assert_unchanged_since_load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = line.encode(JOURNAL_ENCODING)
        with self.path.open("a", encoding=JOURNAL_ENCODING, newline=LINE_TERMINATOR) as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        line_number = len(self._entries) + 1
        self._entries[record.evaluation_id] = _Entry(line_number, line, record)
        self._expected_size += len(payload)
        return EvaluationAppendResult(EvaluationAppendStatus.APPENDED, record.evaluation_id,
                                      wrote_line=True, line_number=line_number)

    def _assert_unchanged_since_load(self) -> None:
        actual = self.path.stat().st_size if self.path.exists() else 0
        if actual != self._expected_size:
            raise ConcurrentModificationDetected(
                f"{self.path.name} changed on disk since it was loaded "
                f"(expected {self._expected_size} bytes, found {actual}); "
                f"single-writer boundary violated — reload() before appending")

    # ------------------------------------------------------------ read（最小 API）

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, evaluation_id: object) -> bool:
        return evaluation_id in self._entries

    def get(self, evaluation_id: str) -> Optional[EvaluationRecord]:
        entry = self._entries.get(evaluation_id)
        return None if entry is None else entry.record

    def iter_records(self) -> Iterator[EvaluationRecord]:
        """物理行順（追記順）。並べ替え・dedup・「現在の評価」の解決を行わない。"""
        for entry in sorted(self._entries.values(), key=lambda e: e.line_number):
            yield entry.record


def _differing_fields(stored: EvaluationRecord, offered: EvaluationRecord) -> Tuple[str, ...]:
    a, b = stored.as_dict(), offered.as_dict()
    return tuple(sorted(key for key in a if a[key] != b.get(key)))
