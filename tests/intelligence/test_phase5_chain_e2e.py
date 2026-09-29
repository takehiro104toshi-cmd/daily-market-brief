"""Phase 5 closeout — cross-phase chain の合成証拠（監査用。新しい runtime 統合ではない）。

P4 凍結 object → P5-1 ingest → predictions.jsonl → 権威 reload → P5-2 engine → evaluations.jsonl
→ 権威 reload → P5-3 analyzer → CalibrationReport を、既存の凍結 API と既存 E2E の fixture だけを
組み合わせて 1 本の隔離 root で通す。P5-1D / P5-2D / P5-3C が個別に証明した link が合成しても
成立することを直接示す（実 journal・network・market・runtime scheduler は使わない）。
"""
from __future__ import annotations

import random
from pathlib import Path

from src.intelligence.predictions.calibration_analyzer import analyze_calibration
from src.intelligence.predictions.calibration_contract import CohortBoundary
from src.intelligence.predictions.evaluation_engine import evaluate_and_append
from src.intelligence.predictions.evaluation_record import NEUTRAL_BAND_RULE_VERSION, EvaluationStatus, RealizedOutcome
from src.intelligence.predictions.evaluation_store import EvaluationAppendStatus, EvaluationStore
from src.intelligence.predictions.prediction_record import PredictionOrigin
from src.intelligence.predictions.prediction_store import AppendStatus, PredictionStore
from src.intelligence.reports.market_signal import SignalLevel
from tests.intelligence.test_evaluation_engine import CALENDAR, CREATED_AT, REFERENCE, SESSION, market
from tests.intelligence.test_prediction_journal_e2e import KINDS, p4_set

LIVE = PredictionOrigin.LIVE
COHORT = CohortBoundary(LIVE, "2026-09-01", "2026-09-30")
CORRECTED = market((REFERENCE, "2700"), (SESSION, "2695"))          # 訂正 close: −0.185% → RANGE


def journals(root: Path):
    return (root / "predictions" / "predictions.jsonl").read_bytes(), (root / "predictions" / "evaluations.jsonl").read_bytes()


def build_chain(root: Path):
    """P4 object 4 種（available / neutral / mixed / abstained）→ 予測 journal → 評価 journal（訂正 1 件込み）。"""
    pstore = PredictionStore(root)
    ingested = {}
    for kind in KINDS:
        result = p4_set(kind, session=SESSION, reference=REFERENCE).ingest(pstore, LIVE)
        assert result.append.status is AppendStatus.APPENDED
        ingested[kind] = result.record
    del pstore
    reloaded_predictions = list(PredictionStore(root).iter_records())              # 権威 reload
    assert reloaded_predictions == [ingested[k] for k in KINDS]

    estore = EvaluationStore(root)
    evaluated = []
    for pred in reloaded_predictions:
        record, appended = evaluate_and_append(estore, pred, CALENDAR, market(), created_at=CREATED_AT)
        assert appended.status is EvaluationAppendStatus.APPENDED and record.status is EvaluationStatus.EVALUATED
        evaluated.append(record)
    correction, appended = evaluate_and_append(estore, reloaded_predictions[0], CALENDAR, CORRECTED,
                                               created_at=CREATED_AT,
                                               supersedes_evaluation_id=evaluated[0].evaluation_id)
    assert appended.status is EvaluationAppendStatus.APPENDED and correction.realized_outcome is RealizedOutcome.RANGE
    evaluated.append(correction)
    del estore
    return ingested, evaluated


def test_chain_p4_objects_to_calibration_report_through_both_journals(tmp_path: Path) -> None:
    root = tmp_path / "root"
    ingested, evaluated = build_chain(root)
    before = journals(root)

    pstore, estore = PredictionStore(root), EvaluationStore(root)                   # process 再起動相当
    assert len(pstore) == 4 and len(estore) == 5
    report = analyze_calibration(pstore.iter_records(), estore.iter_records(), COHORT)

    # 同じ report が in-memory の凍結 record（ingest / engine の戻り値）からも得られる ＝ chain 全体の再構築同値
    assert report.as_dict() == analyze_calibration(list(ingested.values()), evaluated, COHORT).as_dict()

    assert report.prediction_count == 4 and report.unique_session_count == 1
    assert (report.abstention.available, report.abstention.abstained) == (2, 2)            # mixed / abstained は棄権
    assert (report.coverage.active_evaluated, report.coverage.active_deferred,
            report.coverage.no_evaluation, report.coverage.unresolved) == (4, 0, 0, 0)
    assert (report.supplied_prediction_count, report.supplied_evaluation_count,
            report.associated_evaluation_count, report.foreign_evaluation_count) == (4, 5, 5, 0)
    # available UPWARD_LEAN は訂正後 RANGE（不一致）、available NEUTRAL_RANGE は UP（不一致）
    assert (report.directional_match.numerator, report.directional_match.denominator) == (0, 2)
    assert report.confusion_matrix.rows[SignalLevel.UPWARD_LEAN].as_dict() == {"UP": 0, "RANGE": 1, "DOWN": 0, "total": 1}
    assert report.confusion_matrix.rows[SignalLevel.NEUTRAL_RANGE].as_dict() == {"UP": 1, "RANGE": 0, "DOWN": 0, "total": 1}
    # 棄権 2 件の市場 outcome（UP）は棄権診断にだけ現れ、方向 exact match には入らない
    assert report.abstention.outcome.outcomes.as_dict() == {"UP": 2, "RANGE": 0, "DOWN": 0, "total": 2}
    assert report.classification_versions == (NEUTRAL_BAND_RULE_VERSION,)
    assert report.as_dict()["versions"]["realized_classification"] == ["topix_neutral_band:1.0.0"]

    # 訂正前の履歴（物理先頭 4 行）だけで分析すると original（UP・一致）が active。journal 自体は不変
    history = list(estore.iter_records())
    earlier = analyze_calibration(pstore.iter_records(), history[:4], COHORT)
    assert (earlier.directional_match.numerator, earlier.directional_match.denominator) == (1, 2)
    assert earlier.lineage.cohort_digest == report.lineage.cohort_digest
    assert earlier.lineage.active_evaluation_digest != report.lineage.active_evaluation_digest
    assert history[0].realized_outcome is RealizedOutcome.UP and history[4].supersedes_evaluation_id == history[0].evaluation_id
    assert journals(root) == before                                                       # 分析は両 journal を変更しない


def test_chain_report_is_order_independent_and_journals_stay_separate(tmp_path: Path) -> None:
    root = tmp_path / "root"
    build_chain(root)
    baseline = analyze_calibration(PredictionStore(root).iter_records(), EvaluationStore(root).iter_records(), COHORT).as_dict()
    preds, evals = list(PredictionStore(root).iter_records()), list(EvaluationStore(root).iter_records())
    for seed in range(4):
        random.Random(seed).shuffle(preds)
        random.Random(seed).shuffle(evals)
        assert analyze_calibration(preds, evals, COHORT).as_dict() == baseline
    pred_bytes, eval_bytes = journals(root)
    assert pred_bytes.count(b"\n") == 4 and eval_bytes.count(b"\n") == 5
    assert b"realized_return" not in pred_bytes and b"evaluation_id" not in pred_bytes      # 予測 journal に outcome は無い
    assert b"brief_id" not in eval_bytes and b'"level"' not in eval_bytes                   # 評価 journal に予測意味論の複製は無い
    replay = analyze_calibration(preds, evals, CohortBoundary(PredictionOrigin.REPLAY, "2026-09-01", "2026-09-30"))
    assert replay.prediction_count == 0 and replay.foreign_evaluation_count == 5             # LIVE / REPLAY は pool しない
