"""P8-ADP0 — J-Quants `/v2/fins/summary` の純 adapter（行 ＋ 文脈 → ELIGIBLE ／ HOLD の派生の材料。書かない ・呼ばない）。

手順（すべて決定論 ・fail closed。store ・filesystem ・network ・API client ・identity の変更 ・A2 の append は無い）:
 1. 厳密な入力（`FinancialSummaryRow`。14 欄 ・文字列）→ provider の record の identity（自然 key ＋ digest）
 2. 知識の時刻: `DiscDate` ＋ `DiscTime` ＝ TDnet の開示日時（JST。公式）→ A2 の `TIMESTAMP(JST)`、`DiscTime` が空 → `DATE`。
    不正 → HOLD（`KNOWLEDGE_TIME_INVALID`）。時刻を作らない ・取得の時刻を知識にしない
 3. 期間: `FY` → `FISCAL_YEAR`、`1Q` ／ `2Q` ／ `3Q` → 年度の初めからの累計（単独の四半期ではない）。`4Q` ・`5Q` ・その他 ・日付の不整合 ・
    不正 → HOLD（`PERIOD_UNSUPPORTED`）。年率化 ・補間 ・TTM なし
 4. 意味: 凍結の A2R `map_row_semantics(DocType, UNPREFIXED_ACTUAL)`（DocType を自分で解釈しない）。表に無い → `DOCTYPE_UNRECOGNIZED`、
    REIT ・予想の修正 → `DOCTYPE_OUT_OF_SCOPE`、基準 UNKNOWN → `ACCOUNTING_STANDARD_UNKNOWN`、
    区分 UNKNOWN → `STATEMENT_BASIS_UNKNOWN`
 5. pilot の適格（監督の決定 D4。P8-ADP0R で改定）: 公式に文書化された 4 つの会計基準（`JP_GAAP` ・`US_GAAP` ・`IFRS` ・`JMIS`）の
    財務諸表の行が適格。金額は **provider の契約（公式: 円単位 ・換算なし）の正規化**として `JPY` ・`Scale.ONE` を付ける。これは
    「発行体の報告通貨が円」という主張ではない（P8-OBS-53 は残る既知の risk）。表の 4 基準の外（UNKNOWN ・Foreign ・REIT ・
    表に無い値）は従来どおり fail closed。FX 換算 ・名前 ／ 国 ／ code ／ 市場からの通貨の推定 ・発行体の除外一覧はしない
 6. identity: 文脈の `issuer_id`（解決済みの A1 の参照）が無い ・形が違う → `IDENTITY_UNRESOLVED`。Code から作らない
 7. 4 欄: `Sales` → `REVENUE`、`OP` → `OPERATING_INCOME`、`NP` → `NET_INCOME`、`TA` → `TOTAL_ASSETS`。
    空文字 → `NOT_REPORTED` の観測（0 にしない）。厳密な 10 進の構文だけ（空白 ・`+` ・桁区切り ・指数 ・NaN ・Infinity →
    `VALUE_UNPARSEABLE`）。円 ・`Scale.ONE`
 8. 結果: 理由が 1 つでもあれば行ごと HOLD（凍結の ST1 `HeldObservation` を作るだけ。append しない）。無ければ ELIGIBLE（凍結の A2 の
    `FundamentalActual`（根の形）と A2R の注記 ・provenance）

EXE は本結果を信用せず、authority の入力 ・文脈から写しと適格を再実行する（監督の決定 D5）。

記録: `docs/databank/PHASE8_ADP0_JQUANTS_FINANCIAL_SUMMARY_ADAPTER.md`。
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional, Tuple

from .held_observation_model import HeldObservation, HeldReason, ordered_reasons
from .identity_model import SourceClass, is_issuer_id
from .jquants_adapter_model import (ADAPTER_RULES_VERSION, AdapterContext, AdapterInputError, AdapterResult,
                                    AdapterStatus, EligibleMaterial, FinancialSummaryRow, ProviderRecordIdentity)
from .observation_model import (TOKYO, Currency, FundamentalActual, FundamentalField, KnowledgeTime, Measure,
                                ObservationModelError, ObservationProvenance, ObservationValue, PeriodBasis,
                                ReportingPeriod, Scale, StatementBasis, ValueState)
from .observation_semantics_mapping import DOCTYPE_MAPPING_VERSION, derive_observation_semantics, map_row_semantics
from .observation_semantics_model import AccountingStandard, DocumentKind, FieldFamily, SchemaFamily

#: 承認済みの 4 欄の写し（provider の欄 → canonical）。他の欄は写さない
FIELD_MAPPING: Tuple[Tuple[str, FundamentalField], ...] = (("Sales", FundamentalField.REVENUE),
                                                           ("OP", FundamentalField.OPERATING_INCOME),
                                                           ("NP", FundamentalField.NET_INCOME),
                                                           ("TA", FundamentalField.TOTAL_ASSETS))
#: pilot で適格な会計基準（監督の決定 D4 ・P8-ADP0R: 公式に文書化された 4 基準。金額の JPY ・ONE は provider の契約の正規化）
PILOT_ELIGIBLE_STANDARDS: Tuple[AccountingStandard, ...] = (AccountingStandard.JP_GAAP, AccountingStandard.US_GAAP,
                                                             AccountingStandard.IFRS, AccountingStandard.JMIS)
#: 支える期間の種類（`4Q` ・`5Q` ・その他は HOLD）
SUPPORTED_PERIOD_TYPES: Tuple[str, ...] = ("FY", "1Q", "2Q", "3Q")
_CUMULATIVE_QUARTER = {"1Q": 1, "2Q": 2, "3Q": 3}
#: 厳密な 10 進の構文（先頭の 0 なし ・`+` なし ・空白なし ・桁区切りなし ・指数なし）
_STRICT_DECIMAL_RE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_TIME_RE = re.compile(r"^([0-9]{1,2}):([0-9]{2}):([0-9]{2})$")


def _parse_date(text: str) -> Optional[date]:
    if not _DATE_RE.match(text):
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def _knowledge(row: FinancialSummaryRow) -> Optional[KnowledgeTime]:
    """TDnet の開示日時（JST）→ A2 の知識の時刻。時刻が空なら日付だけ。不正なら None。"""
    disclosed = _parse_date(row.DiscDate)
    if disclosed is None:
        return None
    if row.DiscTime == "":
        return KnowledgeTime.date_only(disclosed)
    match = _TIME_RE.match(row.DiscTime)
    if not match:
        return None
    hour, minute, second = (int(part) for part in match.groups())
    if hour > 23 or minute > 59 or second > 59:
        return None
    return KnowledgeTime.exact(datetime(disclosed.year, disclosed.month, disclosed.day, hour, minute, second,
                                        tzinfo=TOKYO))


def _period(row: FinancialSummaryRow) -> Optional[ReportingPeriod]:
    """`CurPerType` ＋ 4 つの日付 → A2 の期間。FY ・累計の 1Q〜3Q だけ。不整合 ・不正 ・他の種類は None。"""
    if row.CurPerType not in SUPPORTED_PERIOD_TYPES:
        return None
    values = row.supported_values()
    dates = [_parse_date(values[name]) for name in ("CurFYSt", "CurFYEn", "CurPerSt", "CurPerEn")]
    if any(value is None for value in dates):
        return None
    fy_start, fy_end, per_start, per_end = dates
    if per_start != fy_start:
        return None
    try:
        if row.CurPerType == "FY":
            if per_end != fy_end:
                return None
            return ReportingPeriod(PeriodBasis.FISCAL_YEAR, fy_start, fy_end, per_start, per_end)
        if per_end >= fy_end:
            return None
        return ReportingPeriod(PeriodBasis.CUMULATIVE_YEAR_TO_DATE, fy_start, fy_end, per_start, per_end,
                               _CUMULATIVE_QUARTER[row.CurPerType])
    except ObservationModelError:
        return None


def _value(text: str) -> Tuple[Optional[ObservationValue], bool]:
    """provider の文字列 → 値。空 → NOT_REPORTED（0 にしない）。構文が厳密でなければ (None, True) ＝ 解釈できない。"""
    if text == "":
        return ObservationValue.absent(Measure.MONETARY_AMOUNT, ValueState.NOT_REPORTED), False
    if not _STRICT_DECIMAL_RE.match(text):
        return None, True
    try:
        return ObservationValue.present(Measure.MONETARY_AMOUNT, text, currency=Currency.JPY, scale=Scale.ONE), False
    except ObservationModelError:
        return None, True


def _held(identity: ProviderRecordIdentity, reasons: Tuple[HeldReason, ...], context: AdapterContext,
          basis: Optional[StatementBasis]) -> HeldObservation:
    reference = identity.reference() or f"jq.fins_summary:unreferenceable:{identity.digest[:24]}"
    return HeldObservation(provider=SourceClass.JQUANTS, schema_family=SchemaFamily.JQUANTS_V2_FINS_SUMMARY,
                           provider_record_ref=reference, provider_record_digest=identity.digest,
                           reasons=reasons, mapping_rule_version=DOCTYPE_MAPPING_VERSION,
                           rules_version=ADAPTER_RULES_VERSION,
                           issuer_id=context.issuer_id if is_issuer_id(context.issuer_id) else "",
                           attempted_statement_basis=basis, observed_at=context.acquired_at)


def adapt_financial_summary_row(row: Any, context: Any) -> AdapterResult:
    """1 行を ELIGIBLE ／ HOLD の派生の材料にする（純関数。書かない）。入力の契約の違反は `AdapterInputError`。"""
    if isinstance(row, FinancialSummaryRow):
        parsed = row
    else:
        parsed = FinancialSummaryRow.from_provider_mapping(row)
    if not isinstance(context, AdapterContext):
        raise AdapterInputError("INVALID_CONTEXT", "context")
    identity = ProviderRecordIdentity.of(parsed)
    reasons: Tuple[HeldReason, ...] = ()
    if identity.reference() is None:
        reasons += (HeldReason.MAPPING_UNSUPPORTED,)                            # 参照に入らない token（識別子の形の外）
    if not is_issuer_id(context.issuer_id):
        reasons += (HeldReason.IDENTITY_UNRESOLVED,)
    knowledge = _knowledge(parsed)
    if knowledge is None:
        reasons += (HeldReason.KNOWLEDGE_TIME_INVALID,)
    period = _period(parsed)
    if period is None:
        reasons += (HeldReason.PERIOD_UNSUPPORTED,)
    mapped = map_row_semantics(parsed.DocType, FieldFamily.UNPREFIXED_ACTUAL)
    basis = mapped.statement_basis
    if mapped.document_kind is DocumentKind.UNRECOGNIZED:
        reasons += (HeldReason.DOCTYPE_UNRECOGNIZED,)
    elif mapped.document_kind is not DocumentKind.FINANCIAL_STATEMENTS:
        reasons += (HeldReason.DOCTYPE_OUT_OF_SCOPE,)
    if mapped.accounting_standard is AccountingStandard.UNKNOWN:
        reasons += (HeldReason.ACCOUNTING_STANDARD_UNKNOWN, HeldReason.CURRENCY_UNKNOWN)
    elif mapped.accounting_standard not in PILOT_ELIGIBLE_STANDARDS:           # pilot の方針の外（基準が無効ではない）
        reasons += (HeldReason.ACCOUNTING_STANDARD_UNSUPPORTED, HeldReason.CURRENCY_UNKNOWN)
    if basis is None:
        reasons += (HeldReason.STATEMENT_BASIS_UNKNOWN,)
    provider_values = parsed.supported_values()
    values: Tuple[Tuple[str, FundamentalField, Optional[ObservationValue]], ...] = ()
    for provider_field, canonical in FIELD_MAPPING:
        value, unparseable = _value(provider_values[provider_field])
        if unparseable:
            reasons += (HeldReason.VALUE_UNPARSEABLE,)
        values += ((provider_field, canonical, value),)
    if reasons:
        ordered = ordered_reasons(reasons)
        return AdapterResult(status=AdapterStatus.HOLD, provider_record=identity, reasons=ordered,
                             held=_held(identity, ordered, context, basis),
                             mapping_rule_version=DOCTYPE_MAPPING_VERSION)
    reference = identity.reference()
    observations: Tuple[FundamentalActual, ...] = ()
    try:
        for provider_field, canonical, value in values:
            observations += (FundamentalActual(
                subject=context.issuer_id, field=canonical, statement_basis=basis, period=period, value=value,
                knowledge=knowledge, provenance=ObservationProvenance(source_class=SourceClass.JQUANTS,
                                                                     source_record_ref=reference,
                                                                     source_field=provider_field)),)
    except ObservationModelError as exc:                                        # 例: 期末より前の知識 → 時刻の不正として保留
        code = HeldReason.KNOWLEDGE_TIME_INVALID if exc.code == "ACTUAL_KNOWN_BEFORE_PERIOD_END" \
            else HeldReason.MAPPING_UNSUPPORTED
        ordered = ordered_reasons((code,))
        return AdapterResult(status=AdapterStatus.HOLD, provider_record=identity, reasons=ordered,
                             held=_held(identity, ordered, context, basis),
                             mapping_rule_version=DOCTYPE_MAPPING_VERSION)
    annotations = tuple(derive_observation_semantics(observation.record_id, parsed.DocType,
                                                     FieldFamily.UNPREFIXED_ACTUAL) for observation in observations)
    material = EligibleMaterial(issuer_id=context.issuer_id, knowledge=knowledge, period=period,
                                observations=observations, annotations=annotations)
    return AdapterResult(status=AdapterStatus.ELIGIBLE, provider_record=identity, reasons=(), eligible=material,
                         mapping_rule_version=DOCTYPE_MAPPING_VERSION)


__all__ = ["FIELD_MAPPING", "PILOT_ELIGIBLE_STANDARDS", "SUPPORTED_PERIOD_TYPES", "adapt_financial_summary_row"]
