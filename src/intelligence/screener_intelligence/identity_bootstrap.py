"""P8-ID1 — identity bootstrap の手順（純関数）: master snapshot → 機械の提案 manifest → 人の審査の結びつけ → 登録 plan。

- `propose_bootstrap(rows, batch, existing=None)`: snapshot D0 の行から決定論で manifest を作る。普通株の code（5 桁 ・数字 ・5 桁目 `0`）
  ごとに 1 Issuer ＋ 1 Security の提案。曖昧 ・不整合 ・支えない物は提案にせず、保留 ／ 人の審査 ／ 再利用 ／ 衝突として manifest に載せる。
  名前 ・類似で結ばない。`existing`（凍結 A1 の検証済みの履歴）があれば重複 ・衝突 ・code の変更 ／ 廃止 ／ 再上場の疑いを検査する。
- `review_manifest(manifest, reviews, *, accepted_at)`: 人の判断を manifest と提案の digest に結びつける（内容が違えば拒む）。
- `plan_registration(manifest, reviewed, existing=None)`: APPROVE の提案だけから凍結 A1 の record を組み立てる（append しない）。
  凍結の `IdentityHistory` の不変条件で plan を memory 内で検査し、通らなければ fail closed。

書かない ・呼ばない: A1 ・A2 ・注記 ・保留の store、filesystem、network、時計、乱数、UUID、LLM。

記録: `docs/databank/PHASE8_ID1_IDENTITY_BOOTSTRAP.md`。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .identity_bootstrap_model import (BootstrapBatch, BootstrapInputError, BootstrapManifest, BootstrapReason,
                                       IdentityProposal, MasterRow, PlanSkipReason, PlannedRegistration,
                                       ProposalDisposition, ProposalReview, RegistrationPlan, ReviewDisposition,
                                       ReviewItem, ReviewedManifest, ordered_bootstrap_reasons)
from .identity_model import (Coverage, CoverageScope, DisplayName, IDENTIFIER_PATTERNS, IdentifierAssignment,
                             IdentifierScheme, IdentityHistory, IdentityHistoryError, IdentityModelError, IssueClass,
                             IssuerRegistration, ListingStart, ListingVenue, NameKind, NameLanguage,
                             SecurityRegistration, SourceClass, SourceProvenance, SubjectKind, derive_issuer_id,
                             derive_security_id)

_CODE_RE = IDENTIFIER_PATTERNS[IdentifierScheme.JQUANTS_CODE]


class BootstrapPlanError(ValueError):
    """審査の結びつけ ・plan の導出の拒否（fail closed）。detail は code ・field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _rows(rows: Any) -> Tuple[MasterRow, ...]:
    if not isinstance(rows, (list, tuple)):
        raise BootstrapInputError("PROVIDER_ROWS_NOT_SEQUENCE", "rows")
    parsed: Tuple[MasterRow, ...] = ()
    for row in rows:
        parsed += (row if isinstance(row, MasterRow) else MasterRow.from_provider_mapping(row),)
    return parsed


def _existing(existing: Any) -> Optional[IdentityHistory]:
    if existing is None:
        return None
    if not isinstance(existing, IdentityHistory):
        raise BootstrapInputError("INVALID_EXISTING_HISTORY", "existing")
    return existing


def _active_assignments(existing: IdentityHistory, code: str) -> Tuple[List[Any], List[Any]]:
    """code に結ばれた JQUANTS_CODE の割り当て（有効な物 ・退役した物）。"""
    active, retired = [], []
    for record_id, assignment in existing.assignments.items():
        if assignment.scheme is not IdentifierScheme.JQUANTS_CODE or assignment.value != code:
            continue
        if record_id in existing.retirements:
            retired.append(assignment)
        else:
            active.append(assignment)
    return active, retired


def _listing_ended(existing: IdentityHistory, security_id: str) -> bool:
    return any(existing.listings[rid].security_id == security_id for rid in existing.listing_ends)


def _against_existing(existing: IdentityHistory, proposal: IdentityProposal) -> Optional[ReviewItem]:
    """凍結 A1 の現在の状態に照らす。None なら提案のまま（A1 に無い code ・anchor）。"""
    active, retired = _active_assignments(existing, proposal.code)
    if active:
        bound = active[0]
        security = existing.securities.get(bound.security_id)
        issuer_id = security.issuer_id if security else ""
        same = (bound.security_id == proposal.security_id and issuer_id == proposal.issuer_id)
        if same and _listing_ended(existing, bound.security_id):
            reasons = (BootstrapReason.LISTING_ENDED_IN_AUTHORITY,)
            return ReviewItem(code=proposal.code, disposition=ProposalDisposition.HUMAN_REVIEW_REQUIRED,
                              reasons=reasons, provider_record_digest=proposal.provider_record_digest,
                              existing_issuer_id=issuer_id, existing_security_id=bound.security_id)
        if same:
            return ReviewItem(code=proposal.code, disposition=ProposalDisposition.REUSE, reasons=(),
                              provider_record_digest=proposal.provider_record_digest, existing_issuer_id=issuer_id,
                              existing_security_id=bound.security_id)
        reasons = [BootstrapReason.CODE_BOUND_TO_OTHER_IDENTITY]
        if _listing_ended(existing, bound.security_id):
            reasons.append(BootstrapReason.LISTING_ENDED_IN_AUTHORITY)
        return ReviewItem(code=proposal.code, disposition=ProposalDisposition.CONFLICT,
                          reasons=ordered_bootstrap_reasons(reasons),
                          provider_record_digest=proposal.provider_record_digest, existing_issuer_id=issuer_id,
                          existing_security_id=bound.security_id)
    if retired:                                                                  # 以前この code を持った Security がある
        previous = retired[-1]
        security = existing.securities.get(previous.security_id)
        return ReviewItem(code=proposal.code, disposition=ProposalDisposition.HUMAN_REVIEW_REQUIRED,
                          reasons=(BootstrapReason.CODE_PREVIOUSLY_RETIRED,),
                          provider_record_digest=proposal.provider_record_digest,
                          existing_issuer_id=security.issuer_id if security else "",
                          existing_security_id=previous.security_id)
    issuer_known = proposal.issuer_id in existing.issuers
    security_known = proposal.security_id in existing.securities
    if issuer_known or security_known:                                           # anchor は登録済みだが code は結ばれていない
        security = existing.securities.get(proposal.security_id)
        reasons = [BootstrapReason.EXISTING_IDENTITY_INCOMPLETE]
        if security is not None and security.issuer_id != proposal.issuer_id:
            reasons.append(BootstrapReason.ISSUER_SECURITY_RELATION_CONFLICT)
        return ReviewItem(code=proposal.code, disposition=ProposalDisposition.HUMAN_REVIEW_REQUIRED,
                          reasons=ordered_bootstrap_reasons(reasons),
                          provider_record_digest=proposal.provider_record_digest,
                          existing_issuer_id=proposal.issuer_id if issuer_known else "",
                          existing_security_id=proposal.security_id if security_known else "")
    return None


def _absent_codes(existing: IdentityHistory, present: set) -> Tuple[ReviewItem, ...]:
    """A1 で有効に結ばれているのに snapshot に無い code（廃止か code の変更か分からない → 人の審査）。"""
    items: Tuple[ReviewItem, ...] = ()
    seen = set()
    for record_id, assignment in sorted(existing.assignments.items(), key=lambda kv: kv[1].value):
        code = assignment.value
        if assignment.scheme is not IdentifierScheme.JQUANTS_CODE or code in present or code in seen:
            continue
        if record_id in existing.retirements or _listing_ended(existing, assignment.security_id):
            continue
        seen.add(code)
        security = existing.securities.get(assignment.security_id)
        items += (ReviewItem(code=code, disposition=ProposalDisposition.HUMAN_REVIEW_REQUIRED,
                             reasons=(BootstrapReason.CODE_ABSENT_FROM_SNAPSHOT,),
                             existing_issuer_id=security.issuer_id if security else "",
                             existing_security_id=assignment.security_id),)
    return items


def _held(code: str, reasons: List[BootstrapReason], digest: str = "",
          disposition: ProposalDisposition = ProposalDisposition.HELD) -> ReviewItem:
    return ReviewItem(code=code, disposition=disposition, reasons=ordered_bootstrap_reasons(reasons),
                      provider_record_digest=digest)


def propose_bootstrap(rows: Any, batch: Any, existing: Any = None) -> BootstrapManifest:
    """snapshot D0 の行 → 決定論の manifest（提案 ・保留 ・人の審査 ・再利用 ・衝突）。書かない。"""
    if not isinstance(batch, BootstrapBatch):
        raise BootstrapInputError("INVALID_BATCH", "batch")
    parsed = _rows(rows)
    history = _existing(existing)
    by_code: Dict[str, List[MasterRow]] = {}
    for row in parsed:
        if row.Code not in by_code:
            by_code[row.Code] = []
        rows_for_code = by_code[row.Code]
        rows_for_code.append(row)
    stems: Dict[str, List[str]] = {}
    for code in by_code:
        if _CODE_RE.match(code) and code.isdigit():
            if code[:4] not in stems:
                stems[code[:4]] = []
            stem_codes = stems[code[:4]]
            stem_codes.append(code)
    proposals: List[IdentityProposal] = []
    items: List[ReviewItem] = []
    for code in sorted(by_code):
        distinct = sorted({row.canonical_digest() for row in by_code[code]})
        row = by_code[code][0]
        digest = row.canonical_digest() if len(distinct) == 1 else ""
        reasons: List[BootstrapReason] = []
        if len(distinct) > 1:
            reasons.append(BootstrapReason.CODE_CONFLICTING_ROWS)               # 同じ code に内容の違う行
        if not _CODE_RE.match(code):
            reasons.append(BootstrapReason.CODE_MALFORMED)
        elif not code.isdigit() or code[4] != "0":
            reasons.append(BootstrapReason.CODE_NOT_COMMON_EQUITY)              # 5 桁目 `0` だけが普通株（公式 FAQ）
        if row.Date != batch.d0.isoformat():
            reasons.append(BootstrapReason.SNAPSHOT_DATE_MISMATCH)
        if row.CoName == "":
            reasons.append(BootstrapReason.NAME_MISSING)
        if row.Mkt not in batch.supported_markets:
            reasons.append(BootstrapReason.MARKET_UNSUPPORTED)
        if row.provider_record_ref() is None:
            reasons.append(BootstrapReason.PROVIDER_REF_UNAVAILABLE)
        if reasons:
            items.append(_held(code, reasons, digest))
            continue
        if len(stems.get(code[:4], [])) > 1:                                     # 同じ先頭 4 桁を共有 → 複数の上場物の疑い
            items.append(_held(code, [BootstrapReason.MULTIPLE_LISTINGS_SUSPECTED], digest,
                               ProposalDisposition.HUMAN_REVIEW_REQUIRED))
            continue
        proposal = IdentityProposal(batch_id=batch.batch_id, d0=batch.d0, code=code,
                                    issuer_anchor=batch.issuer_anchor(code),
                                    security_anchor=batch.security_anchor(code),
                                    issuer_id=derive_issuer_id(batch.issuer_anchor(code)),
                                    security_id=derive_security_id(batch.security_anchor(code)),
                                    issue_class=IssueClass.COMMON_EQUITY, name_ja=row.CoName, name_en=row.CoNameEn,
                                    market=row.Mkt, provider_record_ref=row.provider_record_ref() or "",
                                    provider_record_digest=digest)
        item = _against_existing(history, proposal) if history is not None else None
        if item is not None:
            items.append(item)
        else:
            proposals.append(proposal)
    if history is not None:
        items.extend(_absent_codes(history, set(by_code)))
    return BootstrapManifest(batch=batch, proposals=tuple(proposals),
                             review_items=tuple(sorted(items, key=lambda i: i.code)))


def review_manifest(manifest: Any, reviews: Any, *, accepted_at: Any) -> ReviewedManifest:
    """人の判断を manifest に結びつける。提案の digest が一致しない ・manifest に無い提案への審査は拒む。"""
    if not isinstance(manifest, BootstrapManifest):
        raise BootstrapPlanError("INVALID_MANIFEST", "manifest")
    if not isinstance(reviews, (tuple, list)) or not all(isinstance(r, ProposalReview) for r in reviews):
        raise BootstrapPlanError("INVALID_REVIEWS", "reviews")
    for review in reviews:
        proposal = manifest.proposal(review.proposal_id)
        if proposal is None:
            raise BootstrapPlanError("REVIEW_TARGET_UNKNOWN", "proposal_id")
        if proposal.digest != review.proposal_digest:
            raise BootstrapPlanError("STALE_REVIEW", "proposal_digest")
    ordered = tuple(sorted(reviews, key=lambda r: r.proposal_id))
    if len({r.proposal_id for r in ordered}) != len(ordered):
        raise BootstrapPlanError("DUPLICATE_REVIEW", "proposal_id")
    try:
        return ReviewedManifest(manifest_digest=manifest.manifest_digest, reviews=ordered, accepted_at=accepted_at)
    except BootstrapInputError as exc:
        raise BootstrapPlanError(exc.code, exc.detail) from None


def _records_for(proposal: IdentityProposal, batch: BootstrapBatch, reviewed: ReviewedManifest) -> Tuple[Any, ...]:
    """承認された 1 提案の凍結 A1 の record（登録は HUMAN_REVIEWED、識別子 ・名前 ・上場は JQUANTS。有効時間は D0）。"""
    review_ref = f"review:{batch.batch_id}.{reviewed.reviewed_digest[:24]}"
    human = SourceProvenance(source_class=SourceClass.HUMAN_REVIEWED, source_record_ref=review_ref,
                             known_at=reviewed.accepted_at)
    provider = SourceProvenance(source_class=SourceClass.JQUANTS, source_record_ref=proposal.provider_record_ref,
                                known_at=reviewed.accepted_at)
    issuer = IssuerRegistration(registration_anchor=proposal.issuer_anchor, provenance=human)
    security = SecurityRegistration(registration_anchor=proposal.security_anchor, issuer_id=issuer.issuer_id,
                                    issue_class=proposal.issue_class, provenance=human)
    records: Tuple[Any, ...] = (
        issuer, security,
        IdentifierAssignment(security_id=security.security_id, scheme=IdentifierScheme.JQUANTS_CODE,
                             value=proposal.code, effective_from=batch.effective_from, provenance=provider),
        DisplayName(subject_kind=SubjectKind.ISSUER, subject_id=issuer.issuer_id, name_kind=NameKind.ISSUER_NAME,
                    language=NameLanguage.JA, value=proposal.name_ja, effective_from=batch.effective_from,
                    provenance=provider),
        DisplayName(subject_kind=SubjectKind.SECURITY, subject_id=security.security_id,
                    name_kind=NameKind.SECURITY_NAME, language=NameLanguage.JA, value=proposal.name_ja,
                    effective_from=batch.effective_from, provenance=provider))
    if proposal.name_en != "":
        records += (DisplayName(subject_kind=SubjectKind.ISSUER, subject_id=issuer.issuer_id,
                                name_kind=NameKind.ISSUER_NAME, language=NameLanguage.EN, value=proposal.name_en,
                                effective_from=batch.effective_from, provenance=provider),)
    records += (ListingStart(security_id=security.security_id, venue=ListingVenue.TSE,
                             effective_from=batch.effective_from, provenance=provider),)
    return records


def plan_registration(manifest: Any, reviewed: Any, existing: Any = None) -> RegistrationPlan:
    """APPROVE の提案だけから登録 plan を導く。manifest ・提案の digest ・凍結 A1 の不変条件を検査する。append しない。"""
    if not isinstance(manifest, BootstrapManifest):
        raise BootstrapPlanError("INVALID_MANIFEST", "manifest")
    if not isinstance(reviewed, ReviewedManifest):
        raise BootstrapPlanError("UNREVIEWED_MANIFEST", "reviewed")
    if reviewed.manifest_digest != manifest.manifest_digest:
        raise BootstrapPlanError("MANIFEST_DIGEST_MISMATCH", "manifest_digest")
    history = _existing(existing)
    entries: List[PlannedRegistration] = []
    skipped: List[Tuple[str, PlanSkipReason]] = []
    for proposal in manifest.proposals:
        review = reviewed.review_for(proposal.proposal_id)
        if review is None:
            skipped.append((proposal.proposal_id, PlanSkipReason.NOT_REVIEWED))
            continue
        if review.proposal_digest != proposal.digest:
            raise BootstrapPlanError("STALE_REVIEW", "proposal_digest")
        if review.disposition is ReviewDisposition.REJECT:
            skipped.append((proposal.proposal_id, PlanSkipReason.REJECTED))
            continue
        if review.disposition is ReviewDisposition.DEFER:
            skipped.append((proposal.proposal_id, PlanSkipReason.DEFERRED))
            continue
        try:
            records = _records_for(proposal, manifest.batch, reviewed)
        except IdentityModelError as exc:
            raise BootstrapPlanError("PLAN_RECORD_INVALID", exc.code) from None
        entries.append(PlannedRegistration(proposal_id=proposal.proposal_id, code=proposal.code,
                                           issuer_id=proposal.issuer_id, security_id=proposal.security_id,
                                           records=records))
    coverage: Tuple[Any, ...] = ()
    if entries:
        provider = SourceProvenance(source_class=SourceClass.JQUANTS,
                                    source_record_ref=f"jq.eq_master:snapshot.{manifest.batch.d0.isoformat()}",
                                    known_at=reviewed.accepted_at)
        coverage = (Coverage(scope=CoverageScope.JP_LISTED_EQUITY_IDENTITY,
                             effective_from=manifest.batch.effective_from, effective_to=manifest.batch.coverage_to,
                             provenance=provider),)
    plan = RegistrationPlan(batch=manifest.batch, manifest_digest=manifest.manifest_digest,
                            reviewed_digest=reviewed.reviewed_digest, entries=tuple(entries), coverage=coverage,
                            skipped=tuple(skipped))
    scratch = IdentityHistory(history.records if history is not None else ())   # memory 内の検査だけ。store に触れない
    try:
        for record in plan.records:
            scratch.add(record)
    except IdentityHistoryError as exc:
        raise BootstrapPlanError("PLAN_REJECTED_BY_AUTHORITY_RULES", exc.code) from None
    return plan


__all__ = ["BootstrapPlanError", "plan_registration", "propose_bootstrap", "review_manifest"]
