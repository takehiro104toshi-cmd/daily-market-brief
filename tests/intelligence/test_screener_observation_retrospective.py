"""P8-A2C — 主語つきの 2 軸 coverage と RETROSPECTIVE_PROVIDER_AUTHORITY の解決の test。

境界 ／ 凍結の guard は `test_screener_intelligence_boundary.py`。
すべて合成。network ・時計 ・実データ ・LLM ・raw の応答は使わない。coverage は test が合成で作る（F1 は未実装。G3 の形
`[P, P＋1 日)` を真似る）。EXE ・EPOCH1 の builder は凍結のまま呼ぶ。tmp_path の private root にだけ書く。
"""
from __future__ import annotations

import ast
import json
from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import observation_model as om
from src.intelligence.screener_intelligence import observation_resolver as orr
from src.intelligence.screener_intelligence import observation_retrospective_resolver as rr
from src.intelligence.screener_intelligence import observation_store as ost
from src.intelligence.screener_intelligence.acquisition_manifest_store import ManifestStore
from src.intelligence.screener_intelligence.identity_correction_model import CorrectionHistory
from src.intelligence.screener_intelligence.identity_model import SourceClass, canonical_json
from src.intelligence.screener_intelligence.jquants_adapter_model import AdapterContext
from src.intelligence.screener_intelligence.observation_model import (CoverageDataset, FundamentalField,
                                                                      ObservationCoverage, ObservationHistory,
                                                                      ObservationModelError, ObservationProvenance,
                                                                      StatementBasis)
from src.intelligence.screener_intelligence.observation_resolver import (ObservationQuery, ObservationResolution,
                                                                         ObservationStatus, resolve)
from src.intelligence.screener_intelligence.observation_retrospective_resolver import resolve_retrospective
from src.intelligence.core.ids import content_id
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_acquisition_manifest import (ACQ1, ACQ2, CTX1, CTX2, I1, I2, IDS, KOREA, MODIFIED,
                                                                   build, built, execute, fins_event)
from tests.intelligence.test_screener_acquisition_manifest import root as manifest_root  # noqa: F401  fixture
from tests.intelligence.test_screener_jquants_adapter import quarterly, row
from tests.intelligence.test_screener_jquants_execution import FOREIGN
from tests.intelligence.test_screener_observation import World

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
JST = timezone(timedelta(hours=9))
S = ObservationStatus
F = FundamentalField
CONS = StatementBasis.CONSOLIDATED
FUND = CoverageDataset.FUNDAMENTAL_DISCLOSURE
P_FY = date(2025, 3, 31)                                                                 # 合成の FY の period_end
P_1Q = date(2024, 6, 30)
ACQ3 = ACQ2 + timedelta(days=7)
FAR = datetime(2030, 1, 1, tzinfo=JST)
A2C_MODULES = ("observation_retrospective_resolver",)
RETRO_KEYS = {"authority_as_of", "coverage_epoch_id", "interpretation", "resolution_mode"}
STRICT_KEYS = {"authority_class", "candidates", "coverage_record_ids", "cutoff", "diagnostic", "identity_status",
               "lineage", "query", "record", "resolver_version", "status"}


@pytest.fixture
def root(manifest_root: Path) -> Path:
    return manifest_root


def jq(ref: str) -> ObservationProvenance:
    return ObservationProvenance(source_class=SourceClass.JQUANTS, source_record_ref=ref)


def legacy_cover(start: date = date(2024, 1, 1), end: date = date(2027, 1, 1), through: datetime = FAR,
                 ref: str = "jq:capture-0001") -> ObservationCoverage:
    return ObservationCoverage(dataset=FUND, data_from=start, data_to=end, complete_through=through, provenance=jq(ref))


def g3_cover(manifest, holdings: datetime, *, period_end: date = P_FY, subject: str = I1,
             through: datetime = None) -> ObservationCoverage:
    """将来の F1 が作る形（G3）: period_end P の 1 日 ・主語つき ・取得の瞬間つき ・provenance は取得の参照。
    `complete_through`（世界の軸）の規則は F1 の監督決定待ち（HOLD）なので、ここでは中立な `P＋1 日 00:00` にする
    （実績は period_end の後にしか知り得ないので、何も矛盾させない）。遡及の解決はこれを読まない。"""
    return ObservationCoverage(dataset=FUND, data_from=period_end, data_to=period_end + timedelta(days=1),
                               complete_through=through or om.day_start(period_end + timedelta(days=1)),
                               provenance=jq(manifest.acquisition_ref), subject_id=subject, holdings_as_of=holdings)


def built_for(root: Path, rows, context: AdapterContext, subject: str):
    result = build(root, rows, execute(root, rows, context), event=fins_event(rows, acquired_at=context.acquired_at),
                   subject=subject)
    assert result.outcome.value == "BUILT", (result.outcome, result.failure_code)
    return result.manifest


def epoch(root: Path, rows, context: AdapterContext, *, period_end: date = P_FY, subject: str = I1):
    """1 つの取得 epoch: EXE → manifest（store に記録）→ 合成の G3 coverage（A2 に append）。"""
    manifest = built(root, rows, context)
    ManifestStore.open(root).append(manifest)
    cover = g3_cover(manifest, context.acquired_at, period_end=period_end, subject=subject)
    ost.ObservationStore.open(root).append(cover)
    return manifest, cover


def history_of(root: Path) -> ObservationHistory:
    return ost.ObservationStore.open(root, read_only=True).history


def period_of(root: Path, manifest, index: int = 0):
    return history_of(root).get(manifest.observation_ids[index]).period


def query(root: Path, manifest, field: F = F.REVENUE, *, subject: str = I1, basis: StatementBasis = CONS,
          period=None) -> ObservationQuery:
    return ObservationQuery.actual(subject, field, basis, period or period_of(root, manifest))


def retro(root: Path, q: ObservationQuery, authority_as_of: datetime, *, identity_valid_at: datetime = None,
          history: ObservationHistory = None, manifests=None, corrections=None) -> ObservationResolution:
    return resolve_retrospective(history or history_of(root), q, authority_as_of=authority_as_of,
                                 identity_valid_at=identity_valid_at or authority_as_of,
                                 manifests=manifests or ManifestStore.open(root, read_only=True),
                                 corrections=corrections or CorrectionHistory(IDS.history()))


# ================================================================ A legacy の互換（byte ・id ・STRICT の直列化）


def test_a_legacy_coverage_round_trips_and_its_record_id_is_unchanged() -> None:
    cover = legacy_cover()
    data = cover.as_dict()
    assert set(data["payload"]) == {"complete_through", "data_from", "data_to", "dataset"}       # 新しい欄は現れない
    assert "subject_id" not in cover.canonical_line() and "holdings_as_of" not in cover.canonical_line()
    frozen_payload = {"schema_version": om.SCHEMA_VERSION, "record_kind": "OBSERVATION_COVERAGE",
                      "payload": {"complete_through": "2029-12-31T15:00:00+00:00", "data_from": "2024-01-01",
                                  "data_to": "2027-01-01", "dataset": "FUNDAMENTAL_DISCLOSURE"},
                      "provenance": {"adjustment_ref": "", "source_class": "JQUANTS", "source_field": "",
                                     "source_record_ref": "jq:capture-0001"}}
    assert cover.record_id == content_id(om.RECORD_ID_PREFIX, canonical_json(frozen_payload))   # 凍結の算法そのまま
    assert om.parse_canonical_line(cover.canonical_line()) == cover
    assert cover.subject_id == "" and cover.holdings_as_of is None and cover.applies_to(I1) and cover.applies_to(I2)
    explicit = ObservationCoverage(dataset=FUND, data_from=date(2024, 1, 1), data_to=date(2027, 1, 1),
                                   complete_through=FAR, provenance=jq("jq:capture-0001"), subject_id="",
                                   holdings_as_of=None)
    assert explicit.record_id == cover.record_id and explicit.canonical_line() == cover.canonical_line()
    assert [f.name for f in fields(ObservationCoverage)][-2:] == ["subject_id", "holdings_as_of"]  # 末尾に足しただけ
    world = World()
    assert world.fundamental_cover.record_id == world.history().coverages[1].record_id


def test_a_strict_result_serialization_and_semantics_are_unchanged() -> None:
    world = World()
    q = ObservationQuery.actual(world.ids.I1.issuer_id, F.REVENUE, CONS, world.revenue.period)
    result = resolve(world.history(), q, cutoff=datetime(2025, 12, 1, tzinfo=JST))
    assert result.status is S.FOUND and result.record == world.revenue_restated
    data = result.as_dict()
    assert set(data) == STRICT_KEYS and not RETRO_KEYS & set(data)                                 # 遡及の印は無い
    assert result.resolution_mode == "" and result.authority_as_of is None and result.coverage_epoch_id == ""
    with pytest.raises(ObservationModelError):
        om.parse_observation_record(data)
    assert result.coverage_record_ids == (world.fundamental_cover.record_id,)
    assert [s.value for s in S][:10] == ["FOUND", "NOT_FOUND", "NOT_YET_KNOWN", "AMBIGUOUS",
                                         "INSUFFICIENT_TIME_PRECISION", "BEFORE_COVERAGE", "OUTSIDE_COVERAGE",
                                         "AUTHORITY_MISSING", "STORE_CORRUPTION", "SUBJECT_NOT_RESOLVED"]
    assert [s.value for s in S][10:] == ["SEMANTIC_HOLD", "VALUE_ABSENT", "MANIFEST_MISSING", "MANIFEST_CONFLICT",
                                         "MEMBERSHIP_INVALID"]


# ================================================================ B 主語つきの coverage（STRICT ・矛盾）


def test_b_subject_scoped_coverage_applies_only_to_its_subject_in_strict_mode() -> None:
    world = World()
    scoped = ObservationCoverage(dataset=FUND, data_from=date(2024, 1, 1), data_to=date(2027, 1, 1),
                                 complete_through=FAR, provenance=jq("jq:capture-0002"),
                                 subject_id=world.ids.I1.issuer_id)
    records = [r for r in world.records if r is not world.fundamental_cover] + [scoped]
    history = world.history(records)
    cutoff = datetime(2025, 12, 1, tzinfo=JST)
    mine = resolve(history, ObservationQuery.actual(world.ids.I1.issuer_id, F.REVENUE, CONS, world.revenue.period),
                   cutoff=cutoff)
    assert mine.status is S.FOUND and mine.coverage_record_ids == (scoped.record_id,)
    other = resolve(history, ObservationQuery.actual(world.ids.I2.issuer_id, F.NET_INCOME, CONS, world.revenue.period),
                    cutoff=cutoff)
    assert other.status is S.OUTSIDE_COVERAGE                                                 # 違う主語には当たらない
    both = world.history(records + [world.fundamental_cover])                                 # dataset 全体は従来どおり
    assert resolve(both, other.query, cutoff=cutoff).status is S.FOUND
    expected_ids = tuple(sorted((scoped.record_id, world.fundamental_cover.record_id)))
    assert resolve(both, mine.query, cutoff=cutoff).coverage_record_ids == expected_ids
    before = resolve(history, ObservationQuery.actual(world.ids.I2.issuer_id, F.NET_INCOME, CONS, world.revenue.period),
                     cutoff=cutoff)
    assert before.status is S.OUTSIDE_COVERAGE                                                # BEFORE は主語の範囲で測る
    scoped_cover = scoped.as_dict()
    assert scoped_cover["payload"]["subject_id"] == world.ids.I1.issuer_id
    assert "holdings_as_of" not in scoped_cover["payload"]
    assert om.parse_canonical_line(scoped.canonical_line()) == scoped


def test_b_coverage_contradiction_is_filtered_by_subject_and_ignores_holdings_as_of() -> None:
    world = World()
    through = datetime(2025, 6, 1, tzinfo=JST)
    scoped = ObservationCoverage(dataset=FUND, data_from=date(2024, 1, 1), data_to=date(2027, 1, 1),
                                 complete_through=through, provenance=jq("jq:capture-0003"),
                                 subject_id=world.ids.I1.issuer_id, holdings_as_of=FAR)                 # 取得の軸は無関係
    base = [r for r in world.records if r.KIND is not om.RecordKind.OBSERVATION_COVERAGE]
    history = world.history([scoped])
    i1_early = world.revenue                                                                  # I1 ・2025-05-12 に既知 → 矛盾
    with pytest.raises(om.ObservationHistoryError) as exc:
        history.add(i1_early)
    assert exc.value.code == "COVERAGE_CONTRADICTION"
    assert history.add(world.i2_net_zero)                                                     # I2 の観測は矛盾しない
    assert history.add(world.revenue_restated.__class__(**{**{f.name: getattr(world.revenue, f.name)
                                                               for f in fields(world.revenue)},
                                                            "knowledge": om.KnowledgeTime.exact(
                                                                datetime(2025, 6, 2, tzinfo=JST))}))  # 範囲の知識より後は足せる
    wide = world.history([world.fundamental_cover])                                            # dataset 全体は全主語に当たる
    for record in (world.revenue, world.i2_net_zero):
        with pytest.raises(om.ObservationHistoryError):
            wide.add(record)
    assert world.history(base) is not None


# ================================================================ C holdings_as_of の検査（STRICT に関わらない）


def test_c_holdings_as_of_validation_and_strict_independence() -> None:
    kwargs = dict(dataset=FUND, data_from=P_FY, data_to=P_FY + timedelta(days=1), complete_through=ACQ1,
                  provenance=jq("jq.acq:" + "1" * 24))
    with pytest.raises(ObservationModelError) as exc:
        ObservationCoverage(**kwargs, holdings_as_of=ACQ1)                                     # 主語なしの取得の瞬間
    assert exc.value.code == "HOLDINGS_REQUIRE_SUBJECT"
    with pytest.raises(ObservationModelError) as exc:
        ObservationCoverage(**kwargs, subject_id=I1, holdings_as_of=datetime(2026, 10, 5, 18, 0))  # naive
    assert exc.value.code == "NAIVE_DATETIME"
    with pytest.raises(ObservationModelError) as exc:
        ObservationCoverage(**kwargs, subject_id="合成一号", holdings_as_of=ACQ1)
    assert exc.value.code == "INVALID_SUBJECT"
    with pytest.raises(ObservationModelError) as exc:
        ObservationCoverage(**kwargs, subject_id=IDS.S1.security_id)                           # Issuer だけ
    assert exc.value.code == "INVALID_SUBJECT"
    earlier_holdings = ObservationCoverage(**{**kwargs, "complete_through": FAR}, subject_id=I1,
                                           holdings_as_of=ACQ1 - timedelta(days=400))          # 軸は独立。大小を要求しない
    assert earlier_holdings.holdings_as_of < earlier_holdings.complete_through
    cover = ObservationCoverage(**kwargs, subject_id=I1, holdings_as_of=ACQ1)
    data = cover.as_dict()
    assert data["payload"]["holdings_as_of"] == "2026-10-05T09:00:00+00:00" and data["payload"]["subject_id"] == I1
    assert om.parse_canonical_line(cover.canonical_line()) == cover
    broken = json.loads(cover.canonical_line())
    broken["payload"]["journal_position"] = 1
    with pytest.raises(ObservationModelError) as exc:
        om.parse_observation_record(broken)
    assert exc.value.code == "UNKNOWN_FIELD"
    world = World()
    history = world.history([r for r in world.records if r is not world.fundamental_cover]
                            + [ObservationCoverage(dataset=FUND, data_from=date(2024, 1, 1), data_to=date(2027, 1, 1),
                                                   complete_through=datetime(2025, 6, 1, tzinfo=JST),
                                                   provenance=jq("jq.acq:" + "2" * 24),
                                                   subject_id=world.ids.I1.issuer_id, holdings_as_of=FAR)])
    q = ObservationQuery.actual(world.ids.I1.issuer_id, F.EPS, CONS, world.eps.period)
    assert resolve(history, q, cutoff=datetime(2025, 7, 1, tzinfo=JST)).status is S.NOT_YET_KNOWN  # holdings は効かない
    assert resolve(history, q, cutoff=datetime(2025, 5, 20, tzinfo=JST)).status is S.FOUND


# ================================================================ D 遡及の入口の要求（既定なし ・時計なし）


def test_d_retrospective_requires_every_axis_explicitly(root: Path) -> None:
    manifest, _ = epoch(root, [row()], CTX1)
    q = query(root, manifest)
    history, store, corr = history_of(root), ManifestStore.open(root, read_only=True), CorrectionHistory(IDS.history())
    for kwargs, code in (({"authority_as_of": None, "identity_valid_at": ACQ1}, "AUTHORITY_AS_OF_REQUIRED"),
                         ({"authority_as_of": ACQ1, "identity_valid_at": None}, "IDENTITY_VALID_AT_REQUIRED"),
                         ({"authority_as_of": datetime(2026, 10, 5), "identity_valid_at": ACQ1}, "NAIVE_DATETIME"),
                         ({"authority_as_of": ACQ1, "identity_valid_at": ACQ1 + timedelta(seconds=1)},
                          "RETROSPECTIVE_REQUIRES_LATER_AUTHORITY")):
        with pytest.raises(ObservationModelError) as exc:
            resolve_retrospective(history, q, manifests=store, corrections=corr, **kwargs)
        assert exc.value.code == code
    for bad, code in (({"manifests": None}, "MANIFEST_VIEW_REQUIRED"),
                      ({"manifests": object()}, "MANIFEST_VIEW_REQUIRED"),
                      ({"corrections": None}, "CORRECTION_AUTHORITY_REQUIRED"), ({"history": "x"}, "INVALID_HISTORY")):
        args = {"history": history, "manifests": store, "corrections": corr, **bad}
        with pytest.raises(ObservationModelError) as exc:
            resolve_retrospective(args["history"], q, authority_as_of=ACQ1, identity_valid_at=ACQ1,
                                  manifests=args["manifests"], corrections=args["corrections"])
        assert exc.value.code == code
    market = ObservationQuery.market(IDS.S1.security_id, om.MarketField.CLOSE, om.PriceBasis.RAW_REPORTED,
                                     date(2025, 6, 2))
    for bad_query in (market, replace(q, source_class=SourceClass.ISSUER_DISCLOSURE), "q"):
        with pytest.raises(ObservationModelError) as exc:
            retro(root, bad_query, ACQ1)
        assert exc.value.code == "INVALID_QUERY"
    assert retro(root, replace(q, source_class=SourceClass.JQUANTS), ACQ1).status is S.FOUND


def test_d_no_clock_no_network_no_io_and_no_journal_position_in_the_retrospective_module() -> None:
    source = executable_source(PACKAGE_DIR / "observation_retrospective_resolver.py")
    lowered = source.lower()
    for token in ("now(", "utcnow", "today(", "time.time", "monotonic", "urllib", "socket", "http", "environ", "getenv",
                  "://", "sqlite", "random", "open(", "path(", "coverage(", "observationcoverage(", "history.add(",
                  "store.append", "line_number", "journal_position", "journal_order", "rowid", "index(", "enumerate(",
                  "latest", "current", "fallback", "fundamental_metrics", "metric_model", "llm", "prompt"):
        assert token not in lowered, token
    tree = ast.parse((PACKAGE_DIR / "observation_retrospective_resolver.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Name) and node.id in {"open", "Path", "os", "getattr", "sorted_by_position"})
    assert rr.RESOLUTION_MODE == "RETROSPECTIVE_PROVIDER_AUTHORITY" and rr.STRICT_RESOLUTION_MODE == "STRICT_PIT"
    assert rr.INTERPRETATION == "ACCORDING_TO_PROVIDER_HOLDINGS_AT_AUTHORITY_AS_OF_NOT_A_WORLD_KNOWLEDGE_CLAIM"
    assert rr.COVERAGE_EPOCH_ID_RULE == "ACQUISITION_MANIFEST_REFERENCE"
    assert rr.EPOCH_SELECTION_RULE == "GREATEST_HOLDINGS_AS_OF_NOT_AFTER_AUTHORITY_AS_OF"


# ================================================================ E epoch の選択


def test_e_epoch_selection_none_future_one_many_and_ambiguous(root: Path) -> None:
    manifest = built(root, [row()], CTX1)
    second = built(root, [row()], CTX2)                                                         # 同じ行の再取得（REUSED）
    third = built(root, [row()], AdapterContext(issuer_id=I1, acquired_at=ACQ3))
    for m in (manifest, second, third):
        ManifestStore.open(root).append(m)
    q = query(root, manifest)
    ost.ObservationStore.open(root).append(legacy_cover())                          # dataset 全体 ＝ 遡及の authority ではない
    none = retro(root, q, ACQ1)
    assert none.status is S.OUTSIDE_COVERAGE and none.diagnostic == "NO_SUBJECT_SCOPED_EPOCH"
    assert none.coverage_record_ids == () and none.coverage_epoch_id == "" and none.record is None
    assert resolve(history_of(root), q, cutoff=ACQ1 + timedelta(hours=1)).status is S.FOUND    # STRICT は legacy で足りる
    e1 = g3_cover(manifest, ACQ1)
    ost.ObservationStore.open(root).append(e1)
    future = retro(root, q, ACQ1 - timedelta(seconds=1))                                       # まだ取得していない
    assert future.status is S.NOT_YET_KNOWN and future.diagnostic == "EPOCHS_AFTER_AUTHORITY_AS_OF"
    before = retro(root, query(root, manifest, period=replace(period_of(root, manifest),
                                                               fiscal_year_start=date(2023, 4, 1),
                                                               fiscal_year_end=date(2024, 3, 31),
                                                               period_start=date(2023, 4, 1),
                                                               period_end=date(2024, 3, 31))), ACQ1)
    assert before.status is S.BEFORE_COVERAGE                                                  # 最初の epoch より前の期間
    one = retro(root, q, ACQ1)
    assert one.status is S.FOUND and one.coverage_record_ids == (e1.record_id,)
    assert one.coverage_epoch_id == manifest.reference
    e2 = g3_cover(second, ACQ2)
    ost.ObservationStore.open(root).append(e2)
    e3 = g3_cover(third, ACQ3)
    ost.ObservationStore.open(root).append(e3)
    assert retro(root, q, ACQ1).coverage_record_ids == (e1.record_id,)
    assert retro(root, q, ACQ2 - timedelta(seconds=1)).coverage_record_ids == (e1.record_id,)
    assert retro(root, q, ACQ2).coverage_record_ids == (e2.record_id,)
    assert retro(root, q, ACQ3 + timedelta(days=365)).coverage_record_ids == (e3.record_id,)      # 最後の適格な epoch
    assert retro(root, q, ACQ3 + timedelta(days=365)).coverage_epoch_id == third.reference
    twin = ObservationCoverage(dataset=FUND, data_from=P_FY, data_to=P_FY + timedelta(days=1), complete_through=FAR,
                               provenance=jq(third.acquisition_ref), subject_id=I1, holdings_as_of=ACQ3)  # 同じ瞬間
    ost.ObservationStore.open(root).append(twin)
    ambiguous = retro(root, q, ACQ3)
    assert ambiguous.status is S.AMBIGUOUS and ambiguous.diagnostic == "AMBIGUOUS_EPOCH"
    assert set(ambiguous.candidates) == {e3.record_id, twin.record_id}
    assert retro(root, q, ACQ2).status is S.FOUND                                              # 前の epoch は影響を受けない


# ================================================================ F manifest の結び付き（membership の唯一の authority）


def test_f_manifest_missing_unbound_wrong_subject_and_wrong_acquisition_fail_closed(root: Path) -> None:
    manifest = built(root, [row()], CTX1)                                                       # store には記録しない
    foreign = built_for(root, [row()], AdapterContext(issuer_id=I2, acquired_at=ACQ3), I2)     # I2 の manifest
    q = query(root, manifest)
    store = ost.ObservationStore.open(root)
    store.append(g3_cover(manifest, ACQ1))
    missing = retro(root, q, ACQ1)
    assert missing.status is S.MANIFEST_MISSING and missing.diagnostic == "NO_MANIFEST_FOR_ACQUISITION"
    assert missing.coverage_record_ids != () and missing.coverage_epoch_id == ""
    unbound = ObservationCoverage(dataset=FUND, data_from=P_FY, data_to=P_FY + timedelta(days=1), complete_through=ACQ2,
                                  provenance=jq("jq:capture-0009"), subject_id=I1, holdings_as_of=ACQ2)
    store.append(unbound)                                                                       # 取得の参照でない provenance
    result = retro(root, q, ACQ2)
    assert result.status is S.MANIFEST_MISSING and result.diagnostic == "NO_MANIFEST_FOR_ACQUISITION"
    human_at = ACQ2 + timedelta(days=1)
    human = ObservationCoverage(dataset=FUND, data_from=P_FY, data_to=P_FY + timedelta(days=1),
                                complete_through=human_at,
                                provenance=ObservationProvenance(source_class=SourceClass.HUMAN_REVIEWED,
                                                                 source_record_ref="review:cov-1"),
                                subject_id=I1, holdings_as_of=human_at)
    store.append(human)
    result = retro(root, q, human_at)
    assert result.status is S.MANIFEST_MISSING and result.diagnostic == "EPOCH_NOT_BOUND_TO_ACQUISITION"
    ManifestStore.open(root).append(manifest)
    assert retro(root, q, ACQ1).status is S.FOUND

    class WrongSubject:
        def by_acquisition(self, reference):
            return replace(manifest, subject_id=I2) if reference == manifest.acquisition_ref else None

    class WrongAcquisition:
        def by_acquisition(self, reference):
            return replace(manifest, acquisition_ref="jq.acq:" + "f" * 24)

    assert retro(root, q, ACQ1, manifests=WrongSubject()).diagnostic == "MANIFEST_SUBJECT_MISMATCH"
    assert retro(root, q, ACQ1, manifests=WrongSubject()).status is S.MANIFEST_CONFLICT
    assert retro(root, q, ACQ1, manifests=WrongAcquisition()).diagnostic == "MANIFEST_ACQUISITION_MISMATCH"
    ManifestStore.open(root).append(foreign)                                         # I2 の manifest ・I1 の coverage
    store.append(g3_cover(foreign, ACQ3, subject=I1))
    crossed = retro(root, q, ACQ3)
    assert crossed.status is S.MANIFEST_CONFLICT and crossed.diagnostic == "MANIFEST_SUBJECT_MISMATCH"


def test_f_membership_comes_only_from_the_selected_manifest_not_from_the_current_a2_journal(root: Path) -> None:
    first, _ = epoch(root, [row(TA="")], CTX1)                                                 # epoch 1: TA は記載なし
    full = built(root, [row()], CTX2)                                                           # 後の取得で TA が A2 に入る
    ManifestStore.open(root).append(full)                                                       # coverage は作らない
    history = history_of(root)
    ta = query(root, first, F.TOTAL_ASSETS)
    assert resolve(history, ta, cutoff=ACQ2 + timedelta(days=1)).status is S.NOT_YET_KNOWN    # STRICT: 取り込み未達
    absent = retro(root, ta, ACQ2 + timedelta(days=365))
    assert absent.status is S.VALUE_ABSENT and absent.diagnostic == "FIELD_NOT_REPORTED_IN_EPOCH"
    assert absent.coverage_epoch_id == first.reference and absent.record is None
    assert any(isinstance(r, om.FundamentalActual) and r.field is F.TOTAL_ASSETS for r in history.records)  # A2 には在る
    found = retro(root, query(root, first, F.REVENUE), ACQ2 + timedelta(days=365))
    assert found.status is S.FOUND and found.record.record_id in first.observation_ids


# ================================================================ G membership の証明（再取得 ・provider の修正 ・新しい DiscNo）


def test_g_reacquisition_selects_the_epoch_but_resolves_the_same_unchanged_observation(root: Path) -> None:
    e1, c1 = epoch(root, [row()], CTX1)
    e2, c2 = epoch(root, [row()], CTX2)
    assert e1.observation_ids == e2.observation_ids and e1.record_id != e2.record_id
    q = query(root, e1)
    first, second = retro(root, q, ACQ1), retro(root, q, ACQ2)
    assert first.record == second.record and first.lineage == second.lineage == (first.record.record_id,)
    assert first.coverage_epoch_id == e1.reference and second.coverage_epoch_id == e2.reference
    assert first.coverage_record_ids == (c1.record_id,) and second.coverage_record_ids == (c2.record_id,)
    assert len(history_of(root).chains[first.record.slot_key]) == 1                            # 新しい revision を作らない


def test_g_provider_fix_is_pinned_on_both_axes_independently(root: Path) -> None:
    e1, _ = epoch(root, [row()], CTX1)                                                          # K/D1 → O1
    e2, _ = epoch(root, [row(**MODIFIED)], CTX2)                                     # K/D2 → O2（EXE-R: 知識 ＝ ACQ2）
    o1, o2 = e1.observation_ids[2], e2.observation_ids[2]                                       # REVENUE（欄名の順で 3 つ目）
    assert o1 != o2
    q = query(root, e1)
    history = history_of(root)
    assert history.get(o2).supersedes == o1 and history.get(o2).knowledge.at == ACQ2
    before, after = retro(root, q, ACQ2 - timedelta(seconds=1)), retro(root, q, ACQ2)         # 取得の軸
    assert before.record.record_id == o1 and before.coverage_epoch_id == e1.reference
    assert after.record.record_id == o2 and after.coverage_epoch_id == e2.reference and after.lineage == (o2,)
    assert retro(root, q, ACQ2 + timedelta(days=400)).record.record_id == o2
    disclosed = history.get(o1).knowledge.at                                                     # 世界の軸（STRICT）
    strict_history = ObservationHistory(IDS.history(), [r for r in history.records
                                                        if r.KIND is not om.RecordKind.OBSERVATION_COVERAGE]
                                        + [legacy_cover()])
    assert resolve(strict_history, q, cutoff=disclosed + timedelta(hours=1)).record.record_id == o1
    assert resolve(strict_history, q, cutoff=ACQ2 - timedelta(seconds=1)).record.record_id == o1
    assert resolve(strict_history, q, cutoff=ACQ2).record.record_id == o2
    assert e1.entries[0].provider_record_ref.rpartition(":")[0] == e2.entries[0].provider_record_ref.rpartition(":")[0]


def test_g_new_discno_correction_is_invisible_before_and_visible_from_the_epoch_that_holds_it(root: Path) -> None:
    corrected = row(DiscNo="20250512000002", DiscDate="2025-05-20", Sales="500000000001")
    e1, _ = epoch(root, [row()], CTX1)                                                          # DiscNo A → O1
    e2, _ = epoch(root, [row(), corrected], CTX2)                                               # A（REUSED）＋ B → O2
    o1, o2 = e1.observation_ids[2], e2.entries[1].observation_ids[2]                            # REVENUE
    history = history_of(root)
    assert history.get(o2).supersedes == o1 and len(history.chains[history.get(o1).slot_key]) == 2
    q = query(root, e1)
    early = retro(root, q, ACQ2 - timedelta(seconds=1))
    assert early.record.record_id == o1 and early.lineage == (o1,)                   # B は epoch 1 の member ではない
    late = retro(root, q, ACQ2)
    assert late.record.record_id == o2 and late.lineage == (o1, o2)                             # 鎖の規律を member に限る
    assert late.coverage_epoch_id == e2.reference
    strict_history = ObservationHistory(IDS.history(), [r for r in history.records
                                                        if r.KIND is not om.RecordKind.OBSERVATION_COVERAGE]
                                        + [legacy_cover()])
    assert resolve(strict_history, q, cutoff=datetime(2025, 5, 20, 16, tzinfo=JST)).record.record_id == o2  # 世界: 開示日時
    assert resolve(strict_history, q, cutoff=datetime(2025, 5, 19, tzinfo=JST)).record.record_id == o1


# ================================================================ H 不在の意味（保留 ・記載なし ・本当の NOT_FOUND）


def test_h_held_and_unsupported_rows_are_semantic_holds_not_not_found(root: Path) -> None:
    held, _ = epoch(root, [row(DocType=FOREIGN)], CTX1)                                         # HELD_SEMANTIC
    assert [e.disposition.value for e in held.entries] == ["HELD_SEMANTIC"]
    period = World().revenue.period                                                             # 2024-04..2025-03-31
    q = ObservationQuery.actual(I1, F.REVENUE, CONS, period)
    result = retro(root, q, ACQ1)
    assert result.status is S.SEMANTIC_HOLD and result.diagnostic == "HELD_ROWS_IN_EPOCH_WITHOUT_CANONICAL_SLOT"
    assert result.record is None and result.coverage_epoch_id == held.reference
    unsupported, _ = epoch(root, [row(DocType=KOREA)], CTX2)                                   # UNSUPPORTED
    assert [e.disposition.value for e in unsupported.entries] == ["UNSUPPORTED"]
    assert retro(root, q, ACQ2).status is S.SEMANTIC_HOLD
    assert retro(root, q, ACQ2).coverage_epoch_id == unsupported.reference
    strict = ObservationHistory(IDS.history(), [legacy_cover()])                                 # STRICT: 世界の知識の答え
    assert resolve(strict, q, cutoff=ACQ2).status is S.NOT_FOUND                                # 保留は A2 に無い → 不在
    assert resolve(history_of(root), q, cutoff=ACQ2).status is S.NOT_YET_KNOWN                  # G3 の世界の軸は P＋1 日まで


def test_h_not_reported_rows_and_missing_fields_are_value_absent_not_not_found(root: Path) -> None:
    empty, _ = epoch(root, [row(Sales="", OP="", NP="", TA="")], CTX1)                           # NOT_REPORTED_ONLY
    period = World().revenue.period
    q = ObservationQuery.actual(I1, F.REVENUE, CONS, period)
    result = retro(root, q, ACQ1)
    assert result.status is S.VALUE_ABSENT and result.diagnostic == "NOT_REPORTED_ROWS_IN_EPOCH_WITHOUT_CANONICAL_SLOT"
    partial, _ = epoch(root, [row(TA="")], CTX2)                                                # CANONICAL ・TA 記載なし
    ta = retro(root, query(root, partial, F.TOTAL_ASSETS), ACQ2)
    assert ta.status is S.VALUE_ABSENT and ta.diagnostic == "FIELD_NOT_REPORTED_IN_EPOCH"
    assert retro(root, query(root, partial, F.REVENUE), ACQ2).status is S.FOUND
    assert ta.as_dict()["record"] is None and ta.as_dict()["status"] == "VALUE_ABSENT"


def test_h_true_retrospective_not_found_only_under_a_covered_g3_slot_with_an_authoritative_manifest(root: Path) -> None:
    manifest, cover = epoch(root, [row()], CTX1)
    q = query(root, manifest, basis=StatementBasis.NON_CONSOLIDATED)                            # covered な日 ・一致しない slot
    result = retro(root, q, ACQ1)
    assert result.status is S.NOT_FOUND and result.diagnostic == "NO_CANONICAL_MEMBER_FOR_COVERED_SLOT"
    assert result.coverage_record_ids == (cover.record_id,) and result.coverage_epoch_id == manifest.reference
    assert result.interpretation == rr.INTERPRETATION and result.resolution_mode == rr.RESOLUTION_MODE
    other_period = retro(root, query(root, manifest, period=replace(period_of(root, manifest),
                                                                     fiscal_year_start=date(2025, 4, 1),
                                                                     fiscal_year_end=date(2026, 3, 31),
                                                                     period_start=date(2025, 4, 1),
                                                                     period_end=date(2026, 3, 31))), ACQ1)
    assert other_period.status is S.OUTSIDE_COVERAGE                                # covered でない日は NOT_FOUND にならない
    quarter, q_cover = epoch(root, [quarterly("1Q")], CTX2, period_end=P_1Q)
    assert retro(root, query(root, quarter), ACQ2).status is S.FOUND
    assert retro(root, q, ACQ2).status is S.NOT_FOUND                               # FY の slot は epoch 1 のまま covered


# ================================================================ I member の検証（像との整合）


def test_i_member_observations_are_verified_against_the_a2_view(root: Path) -> None:
    manifest, cover = epoch(root, [row()], CTX1)
    quarter = built(root, [quarterly("1Q")], CTX1)
    q = query(root, manifest)
    history = history_of(root)
    empty = ObservationHistory(IDS.history(), [cover])
    missing = retro(root, q, ACQ1, history=empty)
    assert missing.status is S.MEMBERSHIP_INVALID and missing.diagnostic == "OBSERVATION_MISSING"
    assert missing.candidates == (manifest.observation_ids[2],)                                 # REVENUE の id

    def view(tampered):
        class View:
            def by_acquisition(self, reference):
                return tampered if reference == manifest.acquisition_ref else None
        return View()

    entry = manifest.entries[0]
    reversed_ids = dict(zip([x for x, _ in entry.fields][::-1], [y for _, y in entry.fields]))
    swapped = replace(entry, fields=tuple((f, reversed_ids[f]) for f, _ in entry.fields))
    wrong_field = retro(root, q, ACQ1, manifests=view(replace(manifest, entries=(swapped,))))
    assert wrong_field.status is S.MEMBERSHIP_INVALID and wrong_field.diagnostic == "OBSERVATION_FIELD_MISMATCH"
    quarter_revenue = quarter.entries[0].fields[2][1]
    retargeted = replace(entry, fields=tuple((f, quarter_revenue if f is F.REVENUE else i) for f, i in entry.fields))
    wrong_provenance = retro(root, q, ACQ1, manifests=view(replace(manifest, entries=(retargeted,))))
    assert wrong_provenance.status is S.MEMBERSHIP_INVALID
    assert wrong_provenance.diagnostic == "OBSERVATION_PROVENANCE_MISMATCH"
    i2 = built_for(root, [row()], AdapterContext(issuer_id=I2, acquired_at=ACQ1), I2)          # I2 の観測を I1 の entry に
    i2_revenue = i2.entries[0].fields[2][1]
    foreign = replace(entry, fields=tuple((f, i2_revenue if f is F.REVENUE else i) for f, i in entry.fields))
    wrong_subject = retro(root, q, ACQ1, manifests=view(replace(manifest, entries=(foreign,))))
    assert wrong_subject.status is S.MEMBERSHIP_INVALID and wrong_subject.diagnostic == "OBSERVATION_SUBJECT_MISMATCH"
    original = history_of(root).get(manifest.observation_ids[2])
    shifted = replace(original, period=replace(original.period, **{name: getattr(original.period, name).replace(
        year=getattr(original.period, name).year - 1) for name in ("fiscal_year_start", "fiscal_year_end",
                                                                    "period_start", "period_end")}))
    tampered_history = ObservationHistory(IDS.history(), [*history.records, shifted])
    moved = replace(entry, fields=tuple((f, shifted.record_id if f is F.REVENUE else i) for f, i in entry.fields))
    mismatch = retro(root, q, ACQ1, history=tampered_history, manifests=view(replace(manifest, entries=(moved,))))
    assert mismatch.status is S.MEMBERSHIP_INVALID and mismatch.diagnostic == "OBSERVATION_PERIOD_BASIS_MISMATCH"
    assert retro(root, q, ACQ1).status is S.FOUND                                              # 本物の manifest は通る


# ================================================================ J identity（凍結 A1R の遡及の authority）


def test_j_identity_is_resolved_by_frozen_a1r_retrospective_authority(root: Path) -> None:
    manifest, _ = epoch(root, [row()], CTX1)
    q = query(root, manifest)
    result = retro(root, q, ACQ1, identity_valid_at=datetime(2026, 10, 5, tzinfo=JST))          # 取得の営業日
    assert result.status is S.FOUND and result.identity_status == "FOUND"
    unknown = ObservationQuery.actual("p8iss_" + "0" * 24, F.REVENUE, CONS, period_of(root, manifest))
    with pytest.raises(om.ObservationHistoryError):                                             # 像に無い主語は A2 が拒む
        ObservationHistory(IDS.history(), [replace(history_of(root).get(manifest.observation_ids[0]),
                                                   subject=unknown.subject_id)])
    not_found = retro(root, unknown, ACQ1)
    assert not_found.status is S.SUBJECT_NOT_RESOLVED and not_found.identity_status == "NOT_FOUND"
    assert not_found.coverage_record_ids == () and not_found.coverage_epoch_id == ""
    too_early = retro(root, q, ACQ1, identity_valid_at=datetime(2019, 1, 1, tzinfo=JST))        # 登録（2020-01-01）より前
    assert too_early.status is S.SUBJECT_NOT_RESOLVED and too_early.identity_status != "FOUND"
    with pytest.raises(ObservationModelError) as exc:
        resolve_retrospective(history_of(root), q, authority_as_of=ACQ1, identity_valid_at=ACQ1,
                              manifests=ManifestStore.open(root, read_only=True), corrections=None)
    assert exc.value.code == "CORRECTION_AUTHORITY_REQUIRED"


# ================================================================ K 結果の metadata ・architecture


def test_k_retrospective_results_carry_explicit_metadata_and_never_become_records(root: Path) -> None:
    manifest, cover = epoch(root, [row()], CTX1)
    result = retro(root, query(root, manifest), ACQ1)
    data = result.as_dict()
    assert set(data) == STRICT_KEYS | RETRO_KEYS
    assert data["resolution_mode"] == "RETROSPECTIVE_PROVIDER_AUTHORITY"
    assert data["authority_as_of"] == "2026-10-05T09:00:00+00:00"
    assert data["coverage_epoch_id"] == manifest.reference and data["coverage_epoch_id"].startswith("jq.man:")
    assert data["interpretation"] == "ACCORDING_TO_PROVIDER_HOLDINGS_AT_AUTHORITY_AS_OF_NOT_A_WORLD_KNOWLEDGE_CLAIM"
    assert data["cutoff"] == data["authority_as_of"] and data["resolver_version"] == rr.RETROSPECTIVE_RESOLVER_VERSION
    assert result.authority_class == orr.DERIVED_NON_AUTHORITY_NON_PERSISTENT and rr.is_retrospective(result)
    assert not rr.is_retrospective(resolve(history_of(root), result.query, cutoff=FAR))
    with pytest.raises(ObservationModelError):
        om.parse_observation_record(data)
    with pytest.raises(ost.ObservationAppendRejected):
        ost.ObservationStore.open(root).append(result)
    assert result.canonical_json() == retro(root, query(root, manifest), ACQ1).canonical_json()  # 決定論の replay


def test_k_frozen_layers_do_not_import_the_retrospective_module_and_a3_is_untouched() -> None:
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        if path.stem not in A2C_MODULES:
            assert "observation_retrospective" not in path.read_text(encoding="utf-8"), path.name
    for path in (REPO_ROOT / "src" / "intelligence" / "jquants_pilot2_local.py",
                 REPO_ROOT / "src" / "intelligence" / "jquants_local_transport.py", REPO_ROOT / "main.py"):
        assert "observation_retrospective" not in path.read_text(encoding="utf-8"), path.name
    for name in ("fundamental_metrics", "fundamental_metrics_extended", "metric_model"):
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert "retrospective" not in source.lower() and "holdings_as_of" not in source, name
    resolver = executable_source(PACKAGE_DIR / "observation_resolver.py")
    assert "holdings_as_of" not in resolver.replace("# holdings_as_of", "")                   # STRICT は取得の軸を読まない
    assert "applies_to(query.subject_id)" in resolver and "resolve_retrospective" not in resolver
