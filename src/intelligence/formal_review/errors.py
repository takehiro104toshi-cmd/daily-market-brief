"""Phase 3.9.5 formal review の失敗クラス。すべて fail closed（部分出力・部分書き込みをしない）。

code は CLI 出力・test で照合する安定した識別子。message には path / PDF 名 / 原文を入れない。
"""
from __future__ import annotations


class FormalReviewError(Exception):
    code = "FORMAL_REVIEW_ERROR"

    def __init__(self, message: str = "") -> None:
        super().__init__(f"{self.code}: {message}" if message else self.code)
        self.message = message


class FormalReviewPolicyError(FormalReviewError):
    code = "FORMAL_REVIEW_POLICY_ERROR"


class PacketMissing(FormalReviewError):
    code = "PACKET_MISSING"


class PacketPatternMismatch(FormalReviewError):
    code = "PACKET_PATTERN_MISMATCH"


class CandidateMissing(FormalReviewError):
    code = "CANDIDATE_MISSING"


class StaleReviewPacket(FormalReviewError):
    code = "STALE_REVIEW_PACKET"


class RecommendationMismatch(StaleReviewPacket):
    code = "RECOMMENDATION_MISMATCH"


class MaterialDigestChanged(StaleReviewPacket):
    code = "MATERIAL_DIGEST_CHANGED"


class PacketEvidenceDigestChanged(StaleReviewPacket):
    code = "PACKET_EVIDENCE_DIGEST_CHANGED"


class PolicyDigestMismatch(StaleReviewPacket):
    code = "POLICY_DIGEST_MISMATCH"


class DecisionHeadChanged(StaleReviewPacket):
    code = "DECISION_HEAD_CHANGED"


class FormalGateNotReached(FormalReviewError):
    code = "FORMAL_GATE_NOT_REACHED"


class LifecycleIncompatible(FormalReviewError):
    code = "LIFECYCLE_INCOMPATIBLE"


class ActionNotAllowed(FormalReviewError):
    code = "ACTION_NOT_ALLOWED"


class ApproveAgainstRecommendationBlocked(ActionNotAllowed):
    code = "APPROVE_AGAINST_RECOMMENDATION_BLOCKED"


class RejectAgainstRecommendationBlocked(ActionNotAllowed):
    code = "REJECT_AGAINST_RECOMMENDATION_BLOCKED"


class SiblingConflictBlocked(FormalReviewError):
    code = "SIBLING_CONFLICT_BLOCKED"


class SiblingAcknowledgementRequired(FormalReviewError):
    code = "SIBLING_ACKNOWLEDGEMENT_REQUIRED"


class ReplacementPatternRequired(FormalReviewError):
    code = "REPLACEMENT_PATTERN_REQUIRED"


class ReopenNotEligible(FormalReviewError):
    code = "REOPEN_NOT_ELIGIBLE"


class ReplayEvidenceRequired(FormalReviewError):
    code = "REPLAY_EVIDENCE_REQUIRED"


class ReasonTooShort(FormalReviewError):
    code = "REASON_TOO_SHORT"


class ReasonNotSubstantive(FormalReviewError):
    code = "REASON_NOT_SUBSTANTIVE"


class NonHumanActor(FormalReviewError):
    code = "NON_HUMAN_ACTOR"


class MetadataInvalid(FormalReviewError):
    code = "METADATA_INVALID"


class ForbiddenKeyInPacket(FormalReviewError):
    code = "FORBIDDEN_KEY_IN_PACKET"


class BatchForbidden(FormalReviewError):
    code = "BATCH_FORBIDDEN"


class ReplayEvidenceUnavailable(FormalReviewError):
    code = "REPLAY_EVIDENCE_UNAVAILABLE"
