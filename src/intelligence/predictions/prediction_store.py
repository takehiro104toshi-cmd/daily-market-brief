"""PredictionStore — Phase 5 P5-1B（凍結 PredictionRecord の追記専用 JSONL journal）。

答える問い: 「不変の PredictionRecord を、上書き・黙った改変・意味論の再解釈なしに
どう永続化し、どう読むか」。P4 出力の ingestion（P5-1C）・EvaluationRecord（P5-2）・
較正（P5-3）・runtime 統合は**含まない**。

権威と layout（`docs/databank/PHASE5_ENTRY_CONTRACT.md` §8 / §8.1）:

    <data_root>/predictions/predictions.jsonl     canonical・追記専用・不変（JSONL が唯一の権威）

- **data_root は呼び出し側が明示する。** 既定値・環境変数・config・production root への
  暗黙 fallback を持たない（`core.paths` を import しない）。repository path も持たない。
- **追記専用。** open mode は `"a"` のみ。上書き・truncate・rename・削除・rewrite の経路が無い。
  Git 操作・network・SQLite を持たない。in-memory index は JSONL から毎回再構築する導出物。
- **append 契約（§4 / §5）:**
    - 未知 `prediction_id`                        → 1 行だけ追記（`APPENDED`, wrote_line=True）
    - 既知 id ＋ canonical 行が byte 一致           → 冪等 no-op（`ALREADY_PRESENT`, wrote_line=False）
    - 既知 id ＋ 保存内容のいずれかの field が異なる → `PredictionConflict`（fail closed。
      provenance を merge しない・audit を更新しない・2 行目を書かない）
  N-1 により provenance / audit は `prediction_id` に入らない。従って **同じ id だけでは冪等と
  みなさず**、保存済み canonical 行との完全一致を要求する。
- **同一 session_date に複数記録があってよい**（意味論が異なれば id が異なる）。
  「1 日 1 行」も「最新が勝つ」も持たない。LIVE / REPLAY は id が異なり共存する。
- **journal 直列化**は identity 直列化と別の関心事: `PredictionRecord.as_dict()` を
  key 昇順・compact separators・`ensure_ascii=False`・UTF-8・`"\\n"` 終端で 1 行に書く。
  表示文字列・machine path・secret は schema 上存在しない。
- **load は fail closed（§8）。** 不正 JSON・空行・未知 field・schema 違反・偽造 id・
  非 canonical 行・物理重複（同一内容でも）・終端改行の無い最終行・UTF-8 でない bytes は
  `PredictionJournalCorrupt`（行番号と理由コード付き）。黙って読み飛ばさず、黙って畳まず、
  「修復」しない。migration-on-read / mutation-on-read を行わない。
  （既存 store は破損行を skip し物理重複を set で畳むが、Phase 5 契約はそれを継承しない。
  物理重複は append API が冪等である以上、履歴 / 手動の破損を意味する。）
- **書き込み規律（§9）:** 親ディレクトリ作成 → `open("a", encoding="utf-8", newline="\\n")`
  → 1 行を 1 回の write → `flush()` → `os.fsync()`。既存 store（identity_ledger /
  normalization / raw_store）と同じ最小規律で、hash chain・transaction・lock service を
  持ち込まない。`newline="\\n"` は OS による CRLF 変換を止め bytes を決定論的にする。
- **SINGLE WRITER（§10）。** 同時書き込みを直列化する仕組みは持たない。開いてから
  （または最後の append から）journal の byte 長が外部要因で変わっていれば、append は
  `ConcurrentModificationDetected` で fail closed する（`reload()` で権威から再構築できる）。
  これは検知であって排他ではない。runtime 同時実行は別の認可 gate。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple, Union

from .prediction_record import InvalidPredictionRecord, PredictionRecord

#: layout（契約 §8 凍結）
PREDICTIONS_DIRNAME = "predictions"
JOURNAL_FILENAME = "predictions.jsonl"
JOURNAL_ENCODING = "utf-8"
LINE_TERMINATOR = "\n"

#: 書き込み契約（§10）。True は「単一 writer のみを支援する」という**制限**の宣言であり、
#: 同時書き込み安全性の主張ではない。
SINGLE_WRITER_ONLY = True

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
)


class AppendStatus(str, Enum):
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True)
class AppendResult:
    status: AppendStatus
    prediction_id: str
    wrote_line: bool
    line_number: int  # 1 始まりの物理行（既存行 or 追記行）


class PredictionJournalError(Exception):
    """journal 操作の fail-closed 基底。"""


class PredictionJournalCorrupt(PredictionJournalError):
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


class PredictionConflict(PredictionJournalError):
    """同じ prediction_id で保存内容が異なる（provenance / audit を merge・更新しない）。"""

    def __init__(self, prediction_id: str, differing_fields: Tuple[str, ...]) -> None:
        self.prediction_id = prediction_id
        self.differing_fields = differing_fields
        super().__init__(
            f"prediction_id {prediction_id} already stored with different "
            f"{', '.join(differing_fields) or 'bytes'}")


class ConcurrentModificationDetected(PredictionJournalError):
    """開いてから journal が外部要因で変わった（単一 writer 境界の違反を検知）。"""


# ---------------------------------------------------------------- path / serialization

def journal_path(data_root: Union[str, "os.PathLike[str]"]) -> Path:
    """`<data_root>/predictions/predictions.jsonl`（data_root は呼び出し側が明示する）。"""
    if data_root is None or str(data_root) == "":
        raise ValueError("data_root must be an explicit, non-empty path")
    return Path(data_root) / PREDICTIONS_DIRNAME / JOURNAL_FILENAME


def serialize_record(record: PredictionRecord) -> str:
    """journal 1 行（canonical・決定論的・`\\n` 終端）。identity 直列化とは別の関心事。"""
    if not isinstance(record, PredictionRecord):
        raise TypeError("only PredictionRecord can be journaled")
    return json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + LINE_TERMINATOR


def parse_line(line: str, *, path: Path, line_number: int) -> PredictionRecord:
    """1 行 → PredictionRecord（凍結境界で検証。非 canonical は拒否・修復しない）。"""
    if not line.endswith(LINE_TERMINATOR):
        raise PredictionJournalCorrupt(path, line_number, "TRUNCATED_FINAL_LINE")
    body = line[:-1]
    if body.strip() == "":
        raise PredictionJournalCorrupt(path, line_number, "BLANK_LINE")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PredictionJournalCorrupt(path, line_number, "MALFORMED_JSON",
                                       f"col {exc.colno}") from None
    if not isinstance(data, dict):
        raise PredictionJournalCorrupt(path, line_number, "NOT_AN_OBJECT")
    try:
        record = PredictionRecord.from_dict(data)
    except (InvalidPredictionRecord, ValueError, TypeError, KeyError) as exc:
        raise PredictionJournalCorrupt(path, line_number, "INVALID_RECORD", str(exc)) from exc
    if serialize_record(record) != line:
        raise PredictionJournalCorrupt(path, line_number, "NON_CANONICAL_LINE")
    return record


# ---------------------------------------------------------------- store

@dataclass(frozen=True)
class _Entry:
    line_number: int
    line: str
    record: PredictionRecord


class PredictionStore:
    """追記専用 PredictionRecord journal（JSONL が権威。index は導出物）。"""

    def __init__(self, data_root: Union[str, "os.PathLike[str]"]) -> None:
        self.data_root = Path(data_root)
        self.path = journal_path(data_root)
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
            raise PredictionJournalCorrupt(self.path, 0, "INVALID_ENCODING",
                                           f"byte {exc.start}") from None
        if text and not text.endswith(LINE_TERMINATOR):
            last_number = text.count(LINE_TERMINATOR) + 1
            raise PredictionJournalCorrupt(self.path, last_number, "TRUNCATED_FINAL_LINE")
        for line_number, body in enumerate(text.split(LINE_TERMINATOR)[:-1] if text else (), 1):
            line = body + LINE_TERMINATOR
            record = parse_line(line, path=self.path, line_number=line_number)
            previous = entries.get(record.prediction_id)
            if previous is not None:
                reason = ("PHYSICAL_DUPLICATE_IDENTICAL" if previous.line == line
                          else "PHYSICAL_DUPLICATE_CONFLICTING")
                raise PredictionJournalCorrupt(
                    self.path, line_number, reason,
                    f"{record.prediction_id} first seen at line {previous.line_number}")
            entries[record.prediction_id] = _Entry(line_number, line, record)
        self._entries = entries
        self._expected_size = len(raw)
        return len(entries)

    # ------------------------------------------------------------ append（追記専用）

    def append(self, record: PredictionRecord) -> AppendResult:
        line = serialize_record(record)
        # 書いた bytes がそのまま同じ記録として読めることを、書く前に凍結境界で確かめる
        if parse_line(line, path=self.path, line_number=0) != record:
            raise PredictionJournalError("record does not survive its own canonical round-trip")
        existing = self._entries.get(record.prediction_id)
        if existing is not None:
            if existing.line == line:
                return AppendResult(AppendStatus.ALREADY_PRESENT, record.prediction_id,
                                    wrote_line=False, line_number=existing.line_number)
            raise PredictionConflict(record.prediction_id,
                                     _differing_fields(existing.record, record))
        self._assert_unchanged_since_load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = line.encode(JOURNAL_ENCODING)
        with self.path.open("a", encoding=JOURNAL_ENCODING, newline=LINE_TERMINATOR) as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        line_number = len(self._entries) + 1
        self._entries[record.prediction_id] = _Entry(line_number, line, record)
        self._expected_size += len(payload)
        return AppendResult(AppendStatus.APPENDED, record.prediction_id,
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

    def __contains__(self, prediction_id: object) -> bool:
        return prediction_id in self._entries

    def get(self, prediction_id: str) -> Optional[PredictionRecord]:
        entry = self._entries.get(prediction_id)
        return None if entry is None else entry.record

    def iter_records(self) -> Iterator[PredictionRecord]:
        """物理行順（追記順）。日付 / origin による絞り込み・並べ替え・dedup を行わない。"""
        for entry in sorted(self._entries.values(), key=lambda e: e.line_number):
            yield entry.record


def _differing_fields(stored: PredictionRecord, offered: PredictionRecord) -> Tuple[str, ...]:
    a, b = stored.as_dict(), offered.as_dict()
    return tuple(sorted(key for key in a if a[key] != b.get(key)))
