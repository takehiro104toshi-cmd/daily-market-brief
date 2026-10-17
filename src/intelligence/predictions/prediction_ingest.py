"""prediction_ingest — Phase 5 P5-1C（OFFLINE: 凍結 P4 意味論 → PredictionRecord → PredictionStore）。

答える問い: 「P4 が**既に生成した**意味論 signal を、再解釈なしに Phase 5 の不変 journal へ
写せるか」。**COPY, DO NOT ANALYZE。** 本 module は adapter であり、第二の市場分析 engine では
ない。MarketSignal / MorningBrief / CompassDraft / EvidencePackage / outlook の再計算、
市場観測・TOPIX・取引カレンダーの参照、採点・較正・閾値適用を**一切行わない**。
P4 signal が正しかったかは評価しない（EvaluationRecord は P5-2）。

権威となる P4 意味論 source（§3 調査結果）:

    reports/delivery_pilot.main():
        result = run_pipeline(...)                     # PipelineResult(draft, package, ...)
        brief  = build_morning_brief(result.draft, result.package)
        signal = build_market_signal(brief)

  MorningBrief と MarketSignal が両方揃うのはこの in-process 境界だけである。P4 は
  `persists_canonical_intelligence: False` であり、`brief.as_dict()` / `signal.as_dict()` を
  内部 artifact に書かない。公開 `/v2` JSON は level / confidence / horizon を意図的に含まず、
  pilot の stdout row も `label`（表示語）を含み confidence / horizon を欠く。従って本 adapter
  は **in-process の凍結オブジェクト**を入力とし、公開 JSON・Markdown・HTML・表示ラベル・
  通知 payload を source にしない（逆写像 parser を持たない）。runtime / artifact への
  handoff は後続の認可 gate に属する（本 gate は file format を発明しない）。

field 対応（`docs/databank/PHASE5_ENTRY_CONTRACT.md` §5.2）:

    session_date / reference_session   ← MorningBrief（MarketSignal / draft / package と一致を要求）
    available / level / confidence /
    horizon / unavailable_reason       ← MarketSignal をそのまま（正規化しない）
    brief_id / signal_id / package_id /
    draft_id                            ← MorningBrief / MarketSignal
    morning_brief_schema_version /
    market_signal_schema_version        ← 各 object の `schema_version`（未対応版は fail closed）
    recorded_at                         ← CompassDraft.generated_at（P4 生成時刻。無ければ拒否。
                                          ingestion 時刻で代用しない）
    cutoff                              ← EvidencePackage.cutoff（look-ahead 境界）
    principle_refs                      ← MorningBrief.tier3.principle_refs
    market_principle_version            ← MorningBrief.points の非空 version（高々 1 種。複数は拒否）
    outlook_rule_version                ← CompassDraft.outlook.rule_version（outlook 無しは空）

cross-object 整合（§6）: `signal.brief_id == brief.brief_id`、draft / package の id・session の
一致、brief_id / signal_id の content-address 再検証、schema 版、verdict / generator の一致、
brief.tier3.outlook と draft.outlook の direction / confidence / horizon の一致。日付だけで
結合しない。「最新」を使わない。fuzzy match しない。provenance を修復しない。

origin（§8）: 呼び出し側が `PredictionOrigin` を明示する。既定値も推定も無い。

EvidencePackage は `compass.evidence_package` を import せず、必要な 4 属性
（package_id / session_date / reference_session / cutoff）だけを `GenerationPackage` Protocol
で受ける。同 module の import closure は context.snapshot → context.builders / facts へ広がり、
adapter に市場 context 生成機構を結合させるため（§16 「定数のために広い生成機構を import
しない」）。真正性は brief / draft との id・session 一致で担保する。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Tuple, runtime_checkable

from ..compass.model import CompassDraft
from ..core.time import ensure_aware
from ..reports.market_signal import MarketSignal, make_signal_id
from ..reports.model import MorningBrief, make_brief_id
from .prediction_record import (
    SUPPORTED_MARKET_SIGNAL_SCHEMA_VERSIONS,
    SUPPORTED_MORNING_BRIEF_SCHEMA_VERSIONS,
    PredictionOrigin,
    PredictionRecord,
    make_prediction_record,
)
from .prediction_store import AppendResult, PredictionStore

#: P5-1C が入力とする P4 境界の宣言（report / guard 用。runtime 参照はしない）
P4_SEMANTIC_SOURCE = "in-process: build_morning_brief(draft, package) + build_market_signal(brief)"


class IngestionRejected(ValueError):
    """source が揃っていない・矛盾している・未対応版・時刻を捏造しなければならない（fail closed）。"""


@runtime_checkable
class GenerationPackage(Protocol):
    """EvidencePackage のうち adapter が読む不変属性（型を import せず結合を狭く保つ）。"""

    package_id: str
    session_date: str
    reference_session: str
    cutoff: datetime


@dataclass(frozen=True)
class IngestResult:
    record: PredictionRecord
    append: AppendResult


# ---------------------------------------------------------------- A. source validation

def validate_sources(*, brief: MorningBrief, signal: MarketSignal, draft: CompassDraft,
                     package: GenerationPackage, origin: PredictionOrigin) -> None:
    """凍結 P4 オブジェクトが**同じ生成物に属する**ことを検証する（値は作らない・直さない）。"""
    _require(isinstance(brief, MorningBrief), "brief must be a frozen MorningBrief")
    _require(isinstance(signal, MarketSignal), "signal must be a frozen MarketSignal")
    _require(isinstance(draft, CompassDraft), "draft must be a frozen CompassDraft")
    _require(isinstance(package, GenerationPackage),
             "package must expose package_id / session_date / reference_session / cutoff")
    _require(isinstance(origin, PredictionOrigin),
             "origin must be an explicit PredictionOrigin (LIVE / REPLAY); no default")

    # schema 版（未対応は migrate せず拒否）
    _require(brief.schema_version in SUPPORTED_MORNING_BRIEF_SCHEMA_VERSIONS,
             f"unsupported MorningBrief schema: {brief.schema_version!r}")
    _require(signal.schema_version in SUPPORTED_MARKET_SIGNAL_SCHEMA_VERSIONS,
             f"unsupported MarketSignal schema: {signal.schema_version!r}")

    # content-address の再検証（偽造・改変された projection を写さない）
    brief_payload = {k: v for k, v in brief.as_dict().items() if k != "brief_id"}
    _require(make_brief_id(brief_payload) == brief.brief_id,
             "brief_id does not match the brief projection")
    signal_payload = {k: v for k, v in signal.as_dict().items() if k != "signal_id"}
    _require(make_signal_id(signal_payload) == signal.signal_id,
             "signal_id does not match the signal payload")

    # 連結（id）
    _require(signal.brief_id == brief.brief_id, "signal.brief_id != brief.brief_id")
    _require(draft.draft_id == brief.draft_id, "draft.draft_id != brief.draft_id")
    _require(package.package_id == brief.package_id, "package.package_id != brief.package_id")
    _require(draft.package_id == package.package_id, "draft.package_id != package.package_id")

    # 連結（session。日付だけで結合しない: id 一致の上で session も一致を要求する）
    for name, obj in (("signal", signal), ("draft", draft), ("package", package)):
        _require(obj.session_date == brief.session_date,
                 f"{name}.session_date != brief.session_date")
        _require(obj.reference_session == brief.reference_session,
                 f"{name}.reference_session != brief.reference_session")

    # draft と projection の一致（再計算ではなく写しの整合）
    _require(draft.verdict is brief.verdict, "draft.verdict != brief.verdict")
    _require(draft.generator == brief.generator, "draft.generator != brief.generator")
    outlook = brief.tier3.outlook
    if outlook is not None:
        _require(draft.outlook is not None, "brief carries an outlook the draft lacks")
        _require((draft.outlook.direction.value, draft.outlook.confidence.value,
                  draft.outlook.horizon)
                 == (outlook.direction, outlook.confidence, outlook.horizon),
                 "brief.tier3.outlook does not match draft.outlook")

    # point-in-time（捏造しない）
    _require(draft.generated_at is not None,
             "draft carries no generated_at; refusing to fabricate recorded_at")
    ensure_aware(draft.generated_at, "CompassDraft.generated_at")
    _require(isinstance(package.cutoff, datetime), "package.cutoff must be a datetime")
    ensure_aware(package.cutoff, "EvidencePackage.cutoff")

    # audit 版（複数の相異なる版が 1 brief に混在していれば矛盾）
    market_principle_versions(brief)


def market_principle_versions(brief: MorningBrief) -> Tuple[str, ...]:
    versions = tuple(sorted({p.market_principle_version for p in brief.points
                             if p.market_principle_version}))
    _require(len(versions) <= 1,
             f"brief mixes market principle versions: {versions!r}")
    return versions


# ---------------------------------------------------------------- B. record construction

def build_prediction_record(*, brief: MorningBrief, signal: MarketSignal, draft: CompassDraft,
                            package: GenerationPackage,
                            origin: PredictionOrigin) -> PredictionRecord:
    """凍結 P4 意味論を PredictionRecord へ**写す**（決定論的・純関数・source を変更しない）。"""
    validate_sources(brief=brief, signal=signal, draft=draft, package=package, origin=origin)
    versions = market_principle_versions(brief)
    return make_prediction_record(
        session_date=brief.session_date,
        reference_session=brief.reference_session,
        origin=origin,
        available=signal.available,
        level=signal.level,
        confidence=signal.confidence,
        horizon=signal.horizon,
        unavailable_reason=signal.unavailable_reason,
        brief_id=brief.brief_id,
        signal_id=signal.signal_id,
        package_id=brief.package_id,
        draft_id=brief.draft_id,
        morning_brief_schema_version=brief.schema_version,
        market_signal_schema_version=signal.schema_version,
        recorded_at=draft.generated_at,
        cutoff=package.cutoff,
        principle_refs=tuple(brief.tier3.principle_refs),
        market_principle_version=versions[0] if versions else "",
        outlook_rule_version="" if draft.outlook is None else draft.outlook.rule_version,
    )


# ---------------------------------------------------------------- C. store append

def ingest_prediction(store: PredictionStore, *, brief: MorningBrief, signal: MarketSignal,
                      draft: CompassDraft, package: GenerationPackage,
                      origin: PredictionOrigin) -> IngestResult:
    """A → B → 凍結 PredictionStore.append。conflict / corruption はそのまま伝播する。"""
    _require(isinstance(store, PredictionStore), "store must be a PredictionStore")
    record = build_prediction_record(brief=brief, signal=signal, draft=draft,
                                     package=package, origin=origin)
    return IngestResult(record=record, append=store.append(record))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IngestionRejected(message)
