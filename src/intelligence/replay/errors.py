"""Replay の fail-closed 例外（Phase 3.9.4）。すべて明示的な意味を持ち、部分出力を残さない。"""
from __future__ import annotations


class ReplayError(RuntimeError):
    """replay 全体の基底。"""


class ReplayPolicyError(ReplayError):
    """compass_replay policy が仕様に反する / 同一 version で内容が変わった。"""


class ReplayMixedPolicyDigest(ReplayError):
    """run 内で policy digest / analyzer version が混在した。"""


class ReplayAnalyzerVersionMissing(ReplayError):
    """corpus の analysis version に対応する research analyzer が無い。"""


class ReplayIncompleteSnapshot(ReplayError):
    """snapshot の research / evaluation が完了しなかった（errors 非空・件数不一致）。"""


class ReplayIdentityCollision(ReplayError):
    """manifest 内で document_id / sha256 が重複した。"""


class ReplayIdentityAmbiguity(ReplayError):
    """同じ pattern_id で components が snapshot 間で一致しない。"""


class ReplayLeakageDetected(ReplayError):
    """prefix 外の証拠が snapshot に混入した（未来データ漏洩）。"""


class ReplayInputMutated(ReplayError):
    """捕捉済みの入力（文書 identity / Context）が run 中に変化した。"""


class ReplayTempCorrupt(ReplayError):
    """一時 store / checkpoint が読めない。"""


class ReplayUndatedExceeded(ReplayError):
    """CHRONOLOGICAL で除外する undated 文書の比率が閾値を超えた。"""


class ReplaySnapshotCaptureError(ReplayError):
    """corpus の consistent SQLite backup に失敗した。"""


class ReplayContextSnapshotError(ReplayError):
    """Context snapshot の捕捉に失敗した。"""


class ReplayRebuildMismatch(ReplayError):
    """milestone で incremental research と full rebuild が一致しない。"""
