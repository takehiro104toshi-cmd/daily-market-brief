"""Phase 5 P5-1C — OFFLINE P4 → PredictionRecord ingestion adapter の凍結ガード。

gate §17 の 45 項目を、**合成した P4 意味論オブジェクト**（P4 自身の `make_brief_id` /
`build_market_signal` で作る本物の frozen object）と `tmp_path` 隔離 store だけで証明する。
本番 data root・研究 root・実 Compass データ・公開 artifact には触れない。
"""
from __future__ import annotations

import dataclasses
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.compass.model import (
    ClaimRole,
    ClaimType,
    CompassDraft,
    CompassOutlook,
    Confidence,
    GroundingStatus,
    OutlookDirection,
    QualityVerdict,
)
from src.intelligence.predictions import prediction_ingest as pi
from src.intelligence.predictions.prediction_ingest import (
    P4_SEMANTIC_SOURCE,
    GenerationPackage,
    IngestionRejected,
    IngestResult,
    build_prediction_record,
    ingest_prediction,
    validate_sources,
)
from src.intelligence.predictions.prediction_record import (
    PredictionOrigin,
    PredictionRecord,
    make_prediction_id,
)
from src.intelligence.predictions.prediction_store import (
    AppendStatus,
    PredictionConflict,
    PredictionStore,
)
from src.intelligence.reports.market_signal import (
    MARKET_SIGNAL_SCHEMA_VERSION,
    MarketSignal,
    SignalLevel,
    build_market_signal,
    make_signal_id,
    signal_payload,
)
from src.intelligence.reports.model import (
    MORNING_BRIEF_SCHEMA_VERSION,
    BriefOutlook,
    BriefPoint,
    BriefTier1,
    BriefTier2,
    BriefTier3,
    MorningBrief,
    make_brief_id,
    projection_payload,
)
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "prediction_ingest.py"

GENERATED_AT = datetime(2026, 9, 17, 6, 30, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)
SESSION, REFERENCE = "2026-09-17", "2026-09-16"
IDS = dict(draft_id="draft_" + "d" * 24, package_id="evpkg_" + "e" * 24, plan_id="plan_" + "f" * 24)
LIVE, REPLAY = PredictionOrigin.LIVE, PredictionOrigin.REPLAY


# ---------------------------------------------------------------- synthetic P4 objects

def point(role: ClaimRole, cid: str, text: str, *, ref: str = "MP-01",
          version: str = "market_rules:1.0.0") -> BriefPoint:
    return BriefPoint(claim_id=cid, claim_role=role, claim_type=ClaimType.INTERPRETIVE,
                      text=text, display_text=text, grounding_status=GroundingStatus.GROUNDED,
                      rule_ref=ref, market_principle_version=version)


def compass_outlook(direction=OutlookDirection.UPWARD_BIAS, confidence=Confidence.HIGH,
                    horizon="next_tokyo_session", rule_version="outlook:1.0.0") -> CompassOutlook:
    return CompassOutlook(direction=direction, confidence=confidence, horizon=horizon,
                          rule_version=rule_version)


def draft(*, outlook=compass_outlook(), verdict=QualityVerdict.VALID, abstain_reason="",
          generated_at=GENERATED_AT, **override) -> CompassDraft:
    kwargs = dict(session_date=SESSION, reference_session=REFERENCE, generator="deterministic",
                  verdict=verdict, outlook=outlook, abstain_reason=abstain_reason,
                  generated_at=generated_at, **IDS)
    kwargs.update(override)
    return CompassDraft(**kwargs)


class Package:
    """EvidencePackage のうち adapter が読む 4 属性だけを持つ合成 package。"""

    def __init__(self, *, package_id=IDS["package_id"], session_date=SESSION,
                 reference_session=REFERENCE, cutoff=CUTOFF) -> None:
        self.package_id, self.session_date = package_id, session_date
        self.reference_session, self.cutoff = reference_session, cutoff


def brief(*, outlook=compass_outlook(), verdict=QualityVerdict.VALID, abstain_reason="",
          versions=("market_rules:1.0.0", "market_rules:1.0.0"), tier1_text="one-liner",
          schema_version=MORNING_BRIEF_SCHEMA_VERSION, **override) -> MorningBrief:
    """draft() と整合する MorningBrief（P4 の `make_brief_id` で content-address する）。"""
    usable = verdict in (QualityVerdict.VALID, QualityVerdict.VALID_WITH_WARNINGS)
    if usable:
        tier1 = BriefTier1(available=True, text=tier1_text, display_text=tier1_text)
        tier2 = BriefTier2(available=True,
                           points=(point(ClaimRole.HEADLINE, "claim_h", "h", version=versions[0]),))
        tier3 = BriefTier3(
            available=True,
            outlook=BriefOutlook(direction=outlook.direction.value,
                                 confidence=outlook.confidence.value, horizon=outlook.horizon),
            outlook_points=(point(ClaimRole.OUTLOOK, "claim_o", "o", version=versions[1]),),
            risk=(point(ClaimRole.RISK, "claim_r", "r", ref="MP-07", version=versions[0]),),
            principle_refs=("MP-01", "MP-07"))
    else:
        reason = abstain_reason or "draft_not_usable"
        tier1 = BriefTier1(available=False, unavailable_reason=reason)
        tier2 = BriefTier2(available=False, unavailable_reason=reason)
        tier3 = BriefTier3(available=False, unavailable_reason=reason)
    kwargs = dict(schema_version=schema_version, session_date=SESSION,
                  reference_session=REFERENCE, draft_id=IDS["draft_id"],
                  package_id=IDS["package_id"], verdict=verdict, generator="deterministic",
                  abstain_reason=abstain_reason, tier1=tier1, tier2=tier2, tier3=tier3)
    kwargs.update(override)
    return MorningBrief(brief_id=make_brief_id(projection_payload(**kwargs)), **kwargs)


def quartet(kind: str = "available"):
    """(brief, signal, draft, package) — 全て P4 自身の builder / id 関数で整合させる。"""
    if kind == "available":
        b, d = brief(), draft()
    elif kind == "neutral":
        o = compass_outlook(OutlookDirection.RANGE_BOUND, Confidence.LOW)
        b, d = brief(outlook=o), draft(outlook=o)
    elif kind == "mixed":
        o = compass_outlook(OutlookDirection.MIXED, Confidence.MEDIUM)
        b, d = brief(outlook=o), draft(outlook=o)
    elif kind == "abstained":
        b = brief(verdict=QualityVerdict.ABSTAINED, abstain_reason="draft_abstained")
        d = draft(verdict=QualityVerdict.ABSTAINED, abstain_reason="draft_abstained", outlook=None)
    else:
        raise AssertionError(kind)
    return b, build_market_signal(b), d, Package()


def build(kind: str = "available", origin: PredictionOrigin = LIVE, **override) -> PredictionRecord:
    b, s, d, p = quartet(kind)
    kwargs = dict(brief=b, signal=s, draft=d, package=p, origin=origin)
    kwargs.update(override)
    return build_prediction_record(**kwargs)


def forged_signal(base: MarketSignal, **override) -> MarketSignal:
    """payload を変えて signal_id を整合させた別 signal（id 検査を通し、他の検査で落とす）。"""
    data = {k: v for k, v in base.as_dict().items() if k != "signal_id"}
    data.update(override)
    level = data["level"]
    payload = signal_payload(schema_version=data["schema_version"],
                             session_date=data["session_date"],
                             reference_session=data["reference_session"],
                             available=data["available"],
                             level=None if not level else SignalLevel(level),
                             confidence=data["confidence"], horizon=data["horizon"],
                             brief_id=data["brief_id"],
                             unavailable_reason=data["unavailable_reason"])
    return MarketSignal(signal_id=make_signal_id(payload), session_date=payload["session_date"],
                        reference_session=payload["reference_session"],
                        available=payload["available"],
                        level=None if not level else SignalLevel(level),
                        confidence=payload["confidence"], horizon=payload["horizon"],
                        brief_id=payload["brief_id"],
                        unavailable_reason=payload["unavailable_reason"],
                        schema_version=payload["schema_version"])


def source() -> str:
    return executable_source(MODULE_PATH)


# ---------------------------------------------------------------- 1–5 copy semantics

def test_valid_available_pair_builds_a_record() -> None:                                   # 1
    rec = build("available")
    assert isinstance(rec, PredictionRecord)
    assert rec.available is True and rec.level is SignalLevel.UPWARD_LEAN
    assert rec.confidence == "HIGH" and rec.horizon == "next_tokyo_session"
    assert rec.unavailable_reason == "" and rec.is_abstention is False


def test_neutral_range_remains_available() -> None:                                        # 2
    rec = build("neutral")
    assert rec.available is True and rec.level is SignalLevel.NEUTRAL_RANGE
    assert rec.confidence == "LOW" and rec.is_abstention is False


def test_unavailable_signal_is_journaled(tmp_path: Path) -> None:                          # 3
    b, s, d, p = quartet("abstained")
    assert s.available is False
    result = ingest_prediction(PredictionStore(tmp_path), brief=b, signal=s, draft=d,
                               package=p, origin=LIVE)
    assert result.append.status is AppendStatus.APPENDED and result.append.wrote_line
    assert PredictionStore(tmp_path).get(result.record.prediction_id) == result.record


def test_unavailable_is_not_normalized() -> None:                                          # 4
    mixed = build("mixed")
    assert mixed.available is False and mixed.level is None
    assert mixed.unavailable_reason == "direction_mixed"
    assert mixed.confidence == "MEDIUM" and mixed.horizon == "next_tokyo_session"
    abstained = build("abstained")
    assert abstained.available is False and abstained.level is None
    assert abstained.unavailable_reason == "draft_abstained"
    assert abstained.confidence == "" and abstained.horizon == ""
    assert SignalLevel.NEUTRAL_RANGE not in (mixed.level, abstained.level)


@pytest.mark.parametrize("kind", ["available", "neutral", "mixed", "abstained"])
def test_exact_p4_fields_are_copied(kind: str) -> None:                                    # 5
    b, s, d, p = quartet(kind)
    rec = build_prediction_record(brief=b, signal=s, draft=d, package=p, origin=LIVE)
    assert (rec.session_date, rec.reference_session) == (b.session_date, b.reference_session)
    assert (rec.available, rec.level, rec.confidence, rec.horizon, rec.unavailable_reason) == \
        (s.available, s.level, s.confidence, s.horizon, s.unavailable_reason)
    assert (rec.brief_id, rec.signal_id, rec.package_id, rec.draft_id) == \
        (b.brief_id, s.signal_id, b.package_id, b.draft_id)
    assert (rec.morning_brief_schema_version, rec.market_signal_schema_version) == \
        (b.schema_version, s.schema_version)
    assert rec.recorded_at == d.generated_at and rec.cutoff == p.cutoff
    assert rec.principle_refs == tuple(b.tier3.principle_refs)
    assert rec.origin is LIVE


# ---------------------------------------------------------------- 6–11 cross-object consistency

def test_brief_id_linkage_is_checked() -> None:                                            # 6
    b, s, d, p = quartet()
    assert s.brief_id == b.brief_id
    validate_sources(brief=b, signal=s, draft=d, package=p, origin=LIVE)
    assert "signal.brief_id == brief.brief_id" in source()


def test_mismatched_brief_and_signal_fail() -> None:                                       # 7
    b, _, d, p = quartet()
    other_signal = build_market_signal(brief(tier1_text="another one-liner"))
    assert other_signal.brief_id != b.brief_id
    with pytest.raises(IngestionRejected, match="brief_id"):
        build_prediction_record(brief=b, signal=other_signal, draft=d, package=p, origin=LIVE)


@pytest.mark.parametrize("which", ["signal", "draft", "package"])
def test_session_date_mismatch_fails(which: str) -> None:                                  # 8
    b, s, d, p = quartet()
    if which == "signal":
        s = forged_signal(s, session_date="2026-09-18")
    elif which == "draft":
        d = draft(session_date="2026-09-18")
    else:
        p = Package(session_date="2026-09-18")
    with pytest.raises(IngestionRejected, match="session_date"):
        build_prediction_record(brief=b, signal=s, draft=d, package=p, origin=LIVE)


@pytest.mark.parametrize("which", ["signal", "draft", "package"])
def test_reference_session_mismatch_fails(which: str) -> None:                             # 9
    b, s, d, p = quartet()
    if which == "signal":
        s = forged_signal(s, reference_session="2026-09-15")
    elif which == "draft":
        d = draft(reference_session="2026-09-15")
    else:
        p = Package(reference_session="2026-09-15")
    with pytest.raises(IngestionRejected, match="reference_session"):
        build_prediction_record(brief=b, signal=s, draft=d, package=p, origin=LIVE)


def test_unsupported_morning_brief_schema_fails() -> None:                                 # 10
    b = brief(schema_version="0.1.0")
    s = build_market_signal(b)
    with pytest.raises(IngestionRejected, match="MorningBrief schema"):
        build_prediction_record(brief=b, signal=s, draft=draft(), package=Package(), origin=LIVE)


def test_unsupported_market_signal_schema_fails() -> None:                                 # 11
    b, s, d, p = quartet()
    s = forged_signal(s, schema_version="0.2.0")
    assert s.schema_version != MARKET_SIGNAL_SCHEMA_VERSION
    with pytest.raises(IngestionRejected, match="MarketSignal schema"):
        build_prediction_record(brief=b, signal=s, draft=d, package=p, origin=LIVE)


# ---------------------------------------------------------------- 12–15 origin

def test_explicit_live_is_required_and_accepted() -> None:                                 # 12
    assert build("available", origin=LIVE).origin is LIVE
    b, s, d, p = quartet()
    with pytest.raises(TypeError):
        build_prediction_record(brief=b, signal=s, draft=d, package=p)   # type: ignore[call-arg]


def test_explicit_replay_is_supported() -> None:                                           # 13
    assert build("available", origin=REPLAY).origin is REPLAY


def test_live_and_replay_ids_differ() -> None:                                             # 14
    assert build("available", origin=LIVE).prediction_id != \
        build("available", origin=REPLAY).prediction_id


@pytest.mark.parametrize("bad", ["LIVE", "REPLAY", None, "", 1])
def test_no_default_or_inferred_origin(bad) -> None:                                       # 15
    for fn in (build_prediction_record, ingest_prediction, validate_sources):
        assert inspect.signature(fn).parameters["origin"].default is inspect.Parameter.empty
    b, s, d, p = quartet()
    with pytest.raises(IngestionRejected, match="origin"):
        build_prediction_record(brief=b, signal=s, draft=d, package=p, origin=bad)


# ---------------------------------------------------------------- 16–22 audit provenance

def test_recorded_at_is_the_p4_generation_timestamp() -> None:                             # 16
    stamped = GENERATED_AT + timedelta(days=2, hours=3)
    b, s, _, p = quartet()
    rec = build_prediction_record(brief=b, signal=s, draft=draft(generated_at=stamped),
                                  package=p, origin=LIVE)
    assert rec.recorded_at == stamped


def test_no_datetime_now_fabrication() -> None:                                            # 17
    b, s, _, p = quartet()
    with pytest.raises(IngestionRejected, match="generated_at"):
        build_prediction_record(brief=b, signal=s, draft=draft(generated_at=None),
                                package=p, origin=LIVE)
    src = source()
    for token in ("now(", "utcnow", "time.time", "perf_counter", "date.today"):
        assert token not in src, token


def test_cutoff_is_copied_truthfully() -> None:                                            # 18
    other = CUTOFF - timedelta(minutes=45)
    b, s, d, _ = quartet()
    rec = build_prediction_record(brief=b, signal=s, draft=d, package=Package(cutoff=other),
                                  origin=LIVE)
    assert rec.cutoff == other
    with pytest.raises(ValueError):                       # naive cutoff は捏造せず拒否
        build_prediction_record(brief=b, signal=s, draft=d,
                                package=Package(cutoff=datetime(2026, 9, 17, 6, 0)), origin=LIVE)
    with pytest.raises(IngestionRejected):
        build_prediction_record(brief=b, signal=s, draft=d,
                                package=Package(cutoff="2026-09-17T06:00:00+00:00"),  # type: ignore[arg-type]
                                origin=LIVE)


def test_principle_refs_are_copied_truthfully() -> None:                                   # 19
    assert build("available").principle_refs == ("MP-01", "MP-07")
    assert build("abstained").principle_refs == ()


def test_market_principle_version_is_copied_truthfully() -> None:                          # 20
    assert build("available").market_principle_version == "market_rules:1.0.0"
    b = brief(versions=("", ""))
    rec = build_prediction_record(brief=b, signal=build_market_signal(b), draft=draft(),
                                  package=Package(), origin=LIVE)
    assert rec.market_principle_version == ""                   # 無いものは作らない
    mixed = brief(versions=("market_rules:1.0.0", "market_rules:2.0.0"))
    with pytest.raises(IngestionRejected, match="market principle versions"):
        build_prediction_record(brief=mixed, signal=build_market_signal(mixed), draft=draft(),
                                package=Package(), origin=LIVE)


def test_outlook_rule_version_is_copied_truthfully() -> None:                              # 21
    assert build("available").outlook_rule_version == "outlook:1.0.0"
    o = compass_outlook(rule_version="outlook:9.9.9")
    b = brief(outlook=o)
    rec = build_prediction_record(brief=b, signal=build_market_signal(b), draft=draft(outlook=o),
                                  package=Package(), origin=LIVE)
    assert rec.outlook_rule_version == "outlook:9.9.9"
    assert build("abstained").outlook_rule_version == ""        # outlook 無しは空


def test_package_and_draft_ids_are_copied_as_provenance() -> None:                         # 22
    rec = build("available")
    assert rec.package_id == IDS["package_id"] and rec.draft_id == IDS["draft_id"]
    for key in ("package_id", "draft_id"):
        assert key not in rec.identity_payload()


# ---------------------------------------------------------------- 23–27 store interaction

def test_first_ingest_is_appended(tmp_path: Path) -> None:                                 # 23
    b, s, d, p = quartet()
    result = ingest_prediction(PredictionStore(tmp_path), brief=b, signal=s, draft=d,
                               package=p, origin=LIVE)
    assert isinstance(result, IngestResult)
    assert result.append.status is AppendStatus.APPENDED and result.append.line_number == 1
    assert result.record.prediction_id == result.append.prediction_id


def test_exact_second_ingest_is_already_present(tmp_path: Path) -> None:                   # 24
    store = PredictionStore(tmp_path)
    b, s, d, p = quartet()
    ingest_prediction(store, brief=b, signal=s, draft=d, package=p, origin=LIVE)
    before = store.path.read_bytes()
    again = ingest_prediction(store, brief=b, signal=s, draft=d, package=p, origin=LIVE)
    assert again.append.status is AppendStatus.ALREADY_PRESENT and not again.append.wrote_line
    assert store.path.read_bytes() == before and len(store) == 1


def test_provenance_conflict_propagates(tmp_path: Path) -> None:                           # 25
    store = PredictionStore(tmp_path)
    b, s, d, p = quartet()
    ingest_prediction(store, brief=b, signal=s, draft=d, package=p, origin=LIVE)
    other = brief(tier1_text="same semantics, different projection")
    other_signal = build_market_signal(other)
    assert other.brief_id != b.brief_id and other_signal.signal_id != s.signal_id
    with pytest.raises(PredictionConflict) as info:
        ingest_prediction(store, brief=other, signal=other_signal, draft=d, package=p, origin=LIVE)
    assert set(info.value.differing_fields) == {"brief_id", "signal_id"}
    assert len(store) == 1


def test_audit_conflict_propagates(tmp_path: Path) -> None:                                # 26
    store = PredictionStore(tmp_path)
    b, s, d, p = quartet()
    ingest_prediction(store, brief=b, signal=s, draft=d, package=p, origin=LIVE)
    later = draft(generated_at=GENERATED_AT + timedelta(minutes=5))
    with pytest.raises(PredictionConflict) as info:
        ingest_prediction(store, brief=b, signal=s, draft=later, package=p, origin=LIVE)
    assert info.value.differing_fields == ("recorded_at",)
    assert "except" not in source().replace("except (", "")   # conflict を握り潰す except が無い


def test_no_same_date_overwrite(tmp_path: Path) -> None:                                   # 27
    store = PredictionStore(tmp_path)
    for kind in ("available", "neutral", "abstained"):
        b, s, d, p = quartet(kind)
        assert ingest_prediction(store, brief=b, signal=s, draft=d, package=p,
                                 origin=LIVE).append.wrote_line
    b, s, d, p = quartet("available")
    ingest_prediction(store, brief=b, signal=s, draft=d, package=p, origin=REPLAY)
    assert len(store) == 4 and len({r.session_date for r in store.iter_records()}) == 1


# ---------------------------------------------------------------- 28–40 prohibited dependencies

def test_no_public_v2_reverse_mapping() -> None:                                           # 28
    src = source()
    for token in ("delivery", "public", "PUBLIC_KEYS", "/v2", "v2/", "delivery_id",
                  "markdown_sha256", "artifact", "notification"):
        assert token not in src, token
    for module in imported_modules(MODULE_PATH):
        assert "delivery" not in module and "pages" not in module and "render" not in module


def test_no_display_label_parsing() -> None:                                               # 29
    src = source()
    for token in ("label", "SIGNAL_LEVEL_JA", "REASON_JA", "customer", "display_text",
                  "上昇", "下落", "中立"):
        assert token not in src, token


def test_no_markdown_or_html_parser() -> None:                                             # 30
    src = source()
    for token in ("markdown", "html", "re.compile", "re.match", "re.search", "regex", "parse",
                  "BeautifulSoup", "loads(", "read_text", "open("):
        assert token not in src, token
    assert imported_modules(MODULE_PATH).isdisjoint({"json", "re", "html", "xml"})


def test_no_market_observation_dependency() -> None:                                       # 31
    src = source()
    for token in ("market.", "Observation", "observation", "MarketBank", "series", "close"):
        assert token not in src, token


def test_no_topix_dependency() -> None:                                                    # 32
    assert "topix" not in source().lower()


def test_no_calendar_runtime_dependency() -> None:                                         # 33
    src = source()
    for token in ("calendar", "trading_days", "weekday", "timedelta", "latest_completed"):
        assert token not in src, token


def test_no_jquants() -> None:                                                             # 34
    assert "jquants" not in source().lower() and "JQUANTS" not in source()


def test_no_evaluation_record() -> None:                                                   # 35
    src = source()
    for token in ("EvaluationRecord", "evaluation", "evaluations.jsonl", "realized", "outcome"):
        assert token not in src, token


def test_no_topix_neutral_band() -> None:                                                  # 36
    assert "neutral_band" not in source() and "topix_neutral_band" not in source()


def test_no_calibration_dependency() -> None:                                              # 37
    src = source()
    for token in ("calibration", "accuracy", "hit_rate", "score", "brier"):
        assert token not in src, token


def test_no_network() -> None:                                                             # 38
    src = source()
    for token in ("urllib", "requests", "http", "socket", "environ", "getenv"):
        assert token not in src, token


def test_no_git() -> None:                                                                 # 39
    src = source()
    for token in ("git", "subprocess", "os.system"):
        assert token not in src, token


def test_no_production_publication_reaches_the_adapter() -> None:                          # 40
    assert "predictions" in EXCLUDED_PACKAGES
    offenders = []
    for path in list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py")):
        if path.parent == MODULE_PATH.parent:
            continue
        if "prediction_ingest" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
    for token in ("pages", "publish", "emit_morning_delivery", "workflow", "argparse", "__main__"):
        assert token not in source(), token


def test_imports_are_limited_to_frozen_p4_types_and_phase5_modules() -> None:
    allowed = {"__future__", "dataclasses", "datetime", "typing",
               "..compass.model", "..core.time", "..reports.market_signal", "..reports.model",
               ".prediction_record", ".prediction_store"}
    assert imported_modules(MODULE_PATH) <= allowed
    assert "..compass.evidence_package" not in imported_modules(MODULE_PATH)
    assert "..compass.pipeline" not in imported_modules(MODULE_PATH)
    assert "..compass.outlook" not in imported_modules(MODULE_PATH)


def test_no_recalculation_of_p4_semantics() -> None:
    src = source().replace(repr(P4_SEMANTIC_SOURCE), "")     # 宣言文字列は呼び出しではない
    for token in ("build_market_signal", "build_morning_brief", "run_pipeline",
                  "LEVEL_BY_STATE", "UNAVAILABLE_BY_DIRECTION", "SignalLevel(",
                  "derive", "compute", "score"):
        assert token not in src, token


# ---------------------------------------------------------------- 41–45 authority / purity

def test_prediction_store_remains_the_persistence_authority(tmp_path: Path) -> None:       # 41
    src = source()
    for token in ("open(", "write", "jsonl", "Path(", "mkdir", "fsync"):
        assert token not in src, token
    b, s, d, p = quartet()
    result = ingest_prediction(PredictionStore(tmp_path), brief=b, signal=s, draft=d,
                               package=p, origin=LIVE)
    assert [r.prediction_id for r in PredictionStore(tmp_path).iter_records()] == \
        [result.record.prediction_id]
    with pytest.raises(IngestionRejected, match="PredictionStore"):
        ingest_prediction(object(), brief=b, signal=s, draft=d, package=p, origin=LIVE)  # type: ignore[arg-type]


def test_prediction_record_remains_the_identity_authority() -> None:                       # 42
    rec = build("available")
    assert rec.prediction_id == make_prediction_id(rec.identity_payload())
    src = source()
    for token in ("hashlib", "sha256", "content_id", "pred_", "prediction_id="):
        assert token not in src, token


def test_source_objects_are_not_mutated() -> None:                                         # 43
    b, s, d, p = quartet()
    before = (json.dumps(b.as_dict(), sort_keys=True), json.dumps(s.as_dict(), sort_keys=True),
              json.dumps(d.as_dict(), sort_keys=True, default=str), vars(p).copy())
    build_prediction_record(brief=b, signal=s, draft=d, package=p, origin=LIVE)
    build_prediction_record(brief=b, signal=s, draft=d, package=p, origin=REPLAY)
    after = (json.dumps(b.as_dict(), sort_keys=True), json.dumps(s.as_dict(), sort_keys=True),
             json.dumps(d.as_dict(), sort_keys=True, default=str), vars(p).copy())
    assert before == after
    for frozen in (b, s, d):
        with pytest.raises(dataclasses.FrozenInstanceError):
            frozen.session_date = "2026-01-01"          # type: ignore[misc]


def test_ingestion_is_deterministic(tmp_path: Path) -> None:                              # 44
    assert build("available") == build("available")
    assert build("mixed").prediction_id == build("mixed").prediction_id
    for root in (tmp_path / "a", tmp_path / "b"):
        store = PredictionStore(root)
        for kind in ("available", "neutral", "mixed", "abstained"):
            b, s, d, p = quartet(kind)
            ingest_prediction(store, brief=b, signal=s, draft=d, package=p, origin=LIVE)
    assert (tmp_path / "a" / "predictions" / "predictions.jsonl").read_bytes() == \
        (tmp_path / "b" / "predictions" / "predictions.jsonl").read_bytes()


def _forged_brief_id() -> MorningBrief:
    b = brief()
    return dataclasses.replace(b, brief_id="brief_" + "0" * 24)


@pytest.mark.parametrize("label,mutate", [
    ("forged brief_id", lambda b, s, d, p: (_forged_brief_id(), s, d, p)),
    ("forged signal_id", lambda b, s, d, p: (b, dataclasses.replace(s, signal_id="signal_" + "0" * 24), d, p)),
    ("draft_id mismatch", lambda b, s, d, p: (b, s, draft(draft_id="draft_" + "1" * 24), p)),
    ("package_id mismatch", lambda b, s, d, p: (b, s, d, Package(package_id="evpkg_" + "1" * 24))),
    ("draft/package mismatch", lambda b, s, d, p: (b, s, draft(package_id="evpkg_" + "1" * 24),
                                                   Package(package_id="evpkg_" + "1" * 24))),
    ("verdict mismatch", lambda b, s, d, p: (b, s, draft(verdict=QualityVerdict.VALID_WITH_WARNINGS), p)),
    ("generator mismatch", lambda b, s, d, p: (b, s, draft(generator="llm"), p)),
    ("outlook direction mismatch", lambda b, s, d, p: (
        b, s, draft(outlook=compass_outlook(OutlookDirection.DOWNWARD_BIAS)), p)),
    ("outlook confidence mismatch", lambda b, s, d, p: (
        b, s, draft(outlook=compass_outlook(confidence=Confidence.MEDIUM)), p)),
    ("outlook horizon mismatch", lambda b, s, d, p: (
        b, s, draft(outlook=compass_outlook(horizon="next_week")), p)),
    ("draft without outlook", lambda b, s, d, p: (b, s, draft(outlook=None), p)),
    ("not a MorningBrief", lambda b, s, d, p: (b.as_dict(), s, d, p)),
    ("not a MarketSignal", lambda b, s, d, p: (b, s.as_dict(), d, p)),
    ("not a CompassDraft", lambda b, s, d, p: (b, s, d.as_dict(), p)),
    ("package without cutoff", lambda b, s, d, p: (b, s, d, object())),
])
def test_unsupported_or_contradictory_source_state_fails_closed(label: str, mutate) -> None:  # 45
    b, s, d, p = mutate(*quartet())
    with pytest.raises(IngestionRejected):
        build_prediction_record(brief=b, signal=s, draft=d, package=p, origin=LIVE)


# ---------------------------------------------------------------- source boundary declarations

def test_real_evidence_package_is_accepted_through_the_protocol() -> None:
    from src.intelligence.compass.evidence_package import EvidencePackage
    real = EvidencePackage(package_id=IDS["package_id"], session_date=SESSION,
                           reference_session=REFERENCE, cutoff=CUTOFF, contexts=(), facts=())
    assert isinstance(real, GenerationPackage)
    b, s, d, _ = quartet()
    rec = build_prediction_record(brief=b, signal=s, draft=d, package=real, origin=LIVE)
    assert rec == build("available")


def test_p4_source_boundary_is_declared_and_ingest_result_is_frozen(tmp_path: Path) -> None:
    assert "build_morning_brief" in P4_SEMANTIC_SOURCE and "build_market_signal" in P4_SEMANTIC_SOURCE
    b, s, d, p = quartet()
    result = ingest_prediction(PredictionStore(tmp_path), brief=b, signal=s, draft=d,
                               package=p, origin=LIVE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.record = None                                # type: ignore[misc]
