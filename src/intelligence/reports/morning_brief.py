"""Morning Brief 三段 projection（Phase 4 P4-1A）。

`CompassDraft`（Phase 3-C の quality gate を通過済み）と、その `EvidencePackage` だけを入力に、
三段の Morning Brief を **決定論的に射影**する純関数。

    Tier 1  30 秒版「今日のお客様向け一言」   … draft.one_liner をそのまま
    Tier 2  3 分版「今日のポイント」          … grounded HEADLINE / WHAT_HAPPENED ＋ COVERAGE
    Tier 3  詳細版「相場の見通し＋なぜ」      … grounded OUTLOOK / WHY / RISK ＋ outlook header

規律（`docs/databank/PHASE4_ENTRY_CONTRACT.md`）:
- **純関数**。I/O・store・data root・時刻・乱数・外部サービスに触れない。
- **生成しない**。新しい文を書かず、言い換えず、事実を足さない。claim.text をそのまま運ぶ。
- **再検証しない**。grounding status も verdict も Compass の判定をそのまま使う。
- **再ランクしない**。並びは claim の `order`、同点は `claim_id` で決める。
- **fail closed**。材料が無ければ散文で埋めず、tier を落として機械可読な理由を残す。
- `rule_ref` は claim から**そのまま**運ぶ（ここで作らない・直さない・置き換えない）。
- customer-facing 本文（`display_text`）は、逐語 `text` から**固定の言い換え規則**だけで作る。
  内部語彙（経験則 ID / Evidence Package / 因果注記の内部表現 / 次元キーの再掲 /
  無効化条件の定型に現れる Context 統制語彙）を外すだけで、
  事実・含意・注意喚起の意味は変えない。新しい市場判断も新しい claim も作らない。
- Decision / formal_review / corpus / replay / shadow_review / evaluation と legacy は import しない。
"""
from __future__ import annotations

import re
from typing import Dict, List, Sequence, Tuple

from ..compass.evidence_package import EvidencePackage
from ..compass.model import ClaimRole, CompassClaim, CompassDraft, CompassOutlook
from ..compass.one_liner import strip_provenance
from ..context.model import Direction
from .model import (
    MORNING_BRIEF_SCHEMA_VERSION,
    R_DRAFT_NOT_USABLE,
    R_NO_GROUNDED_COUNTER_CASE,
    R_NO_GROUNDED_OUTLOOK,
    R_NO_GROUNDED_POINTS,
    R_ONE_LINER_UNAVAILABLE,
    TIER2_COVERAGE_ROLES,
    TIER2_POINT_ROLES,
    USABLE_VERDICTS,
    BriefOutlook,
    BriefPoint,
    BriefTier1,
    BriefTier2,
    BriefTier3,
    MorningBrief,
    make_brief_id,
    projection_payload,
)


# ---------------------------------------------------------------- customer-safe 言い換え
#: 内部語 → 顧客向け語（**固定文字列の置換のみ**。判断も語順も変えない）
DISPLAY_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    ("本Evidence Packageに含まれない", "現在の確認対象には含まれない"),
    ("（因果関係は特定しない）", "（因果関係を示すものではありません）"),
)
#: COVERAGE claim が再掲する次元一覧。構造化された missing / unreliable が正なので本文からは外す
_COVERAGE_DIMENSION_SENTENCE = re.compile(r"語れない次元: [^。]*。")

#: Context 統制語彙（`context.model.Direction`）→ 顧客向け日本語。
#:
#: 無効化条件の定型文（`compass.outlook.invalidation_conditions`）は方向を統制語彙の生値で
#: 埋め込む。生値は監査用の語であり顧客向けの語ではないため、表示層でだけ日本語へ写像する。
#: **主語に依存しない語**を選ぶ（例: STRONGER を「円高／円安」と読み替えない）。
#: 読み替えで新しい市場判断を足さないためであり、分析層の意味づけは変えない。
#: `Direction` の全値を明示的に持つ（既定値・総称フォールバックは持たない）。
CONTEXT_DIRECTION_JA: Dict[str, str] = {
    Direction.UP.value: "上昇",
    Direction.DOWN.value: "下落",
    Direction.FLAT.value: "横ばい",
    Direction.STRONGER.value: "強含み",
    Direction.WEAKER.value: "弱含み",
    Direction.STEEPENING.value: "スティープ化",
    Direction.FLATTENING.value: "フラット化",
    Direction.OUTPERFORM.value: "相対的に上回る",
    Direction.UNDERPERFORM.value: "相対的に下回る",
    Direction.ABOVE.value: "上回る",
    Direction.BELOW.value: "下回る",
    Direction.MIXED.value: "強弱混在",
    Direction.UNKNOWN.value: "不明",
}

#: 統制語彙が本文に現れる**唯一の定型**（`…前営業日の方向（UP）と逆に…` / `…の方向（UP）が反転…`）。
#: 全文置換はしない。この構造の内側だけを見るので TOPIX・USDJPY・数値・他の claim 本文は触らない。
_DIRECTION_IN_PROSE = re.compile(r"方向（([A-Z][A-Z_]*)）")


class UnmappedContextDirection(KeyError):
    """`方向（…）` の内側に写像を持たない統制語彙が現れた（fail closed）。

    生値のまま顧客へ出すことも、その場で語を作ることもしない。
    """


def _direction_label(match: "re.Match[str]") -> str:
    """定型の内側にある統制語彙 1 個だけを顧客向け日本語へ置き換える。"""
    raw = match.group(1)
    try:
        return f"方向（{CONTEXT_DIRECTION_JA[raw]}）"
    except KeyError:
        raise UnmappedContextDirection(raw) from None


def customer_text(text: str) -> str:
    """逐語 claim text → 顧客向け表示テキスト（決定論的・冪等）。

    行うのは次の 4 つだけ:
      1. 経験則 ID の出典タグを外す（`根拠（経験則 JP_DIR_001）:` → `根拠:`）
      2. 内部語の固定置換（`DISPLAY_REPLACEMENTS`）
      3. COVERAGE 本文の次元再掲を外す（構造化フィールドと重複するため）
      4. 無効化条件の定型 `方向（…）` の中の Context 統制語彙だけを日本語へ写像する
    事実・数値・含意・注意喚起は一切変更しない。
    4 の写像後は日本語になり定型に再び一致しないため、二度通しても結果は変わらない。
    """
    out = strip_provenance(text)
    for src, dst in DISPLAY_REPLACEMENTS:
        out = out.replace(src, dst)
    out = _COVERAGE_DIMENSION_SENTENCE.sub("", out)
    out = _DIRECTION_IN_PROSE.sub(_direction_label, out)
    return out.strip()


def _to_point(claim: CompassClaim) -> BriefPoint:
    """claim → projection。**値を作り替えない**（text も rule_ref もそのまま）。"""
    return BriefPoint(
        claim_id=claim.claim_id,
        claim_role=claim.claim_role,
        claim_type=claim.claim_type,
        text=claim.text,
        display_text=customer_text(claim.text),
        grounding_status=claim.grounding_status,
        order=claim.order,
        supporting_fact_ids=tuple(claim.supporting_fact_ids),
        supporting_context_ids=tuple(claim.supporting_context_ids),
        rule_ref=claim.rule_ref,
        interpretation_type=claim.interpretation_type,
        market_principle_version=claim.market_principle_version,
    )


def _grounded(claims: Sequence[CompassClaim], *roles: ClaimRole) -> Tuple[BriefPoint, ...]:
    """指定 role の **grounded claim だけ**を決定論的順序で射影する。"""
    wanted = set(roles)
    selected = [c for c in claims if c.is_grounded and c.claim_role in wanted]
    selected.sort(key=lambda c: (c.order, c.claim_id))
    return tuple(_to_point(c) for c in selected)


def _tier1(draft: CompassDraft, usable: bool) -> BriefTier1:
    """one_liner をそのまま。無ければ**散文で代替せず**理由だけ残す。"""
    if not usable:
        return BriefTier1(available=False,
                          unavailable_reason=draft.abstain_reason or R_DRAFT_NOT_USABLE)
    text = draft.one_liner
    if not text.strip():
        return BriefTier1(available=False,
                          unavailable_reason=draft.abstain_reason or R_ONE_LINER_UNAVAILABLE)
    return BriefTier1(available=True, text=text, display_text=customer_text(text))


def _dimension_status(package: EvidencePackage, dimensions: Sequence[str]) -> Dict[str, str]:
    """表示に出す次元の充足状況（key -> ContextStatus の値）。信頼性の意味を構造で保持する。"""
    known = dict(package.dimension_status)
    return {dim: str(getattr(known.get(dim), "value", "") or "") for dim in dimensions}


def _tier2(draft: CompassDraft, package: EvidencePackage, usable: bool) -> BriefTier2:
    """substantive point は usable な draft のときだけ。coverage / 欠落次元は常に残す。"""
    coverage = _grounded(draft.claims, *TIER2_COVERAGE_ROLES)
    missing = tuple(package.missing_dimensions)
    unreliable = tuple(package.unreliable_dimensions)
    status = _dimension_status(package, missing + unreliable)
    if not usable:
        return BriefTier2(available=False, coverage=coverage, missing_dimensions=missing,
                          unreliable_dimensions=unreliable, dimension_status=status,
                          unavailable_reason=draft.abstain_reason or R_DRAFT_NOT_USABLE)
    points = _grounded(draft.claims, *TIER2_POINT_ROLES)
    if not points:
        return BriefTier2(available=False, coverage=coverage, missing_dimensions=missing,
                          unreliable_dimensions=unreliable, dimension_status=status,
                          unavailable_reason=R_NO_GROUNDED_POINTS)
    return BriefTier2(available=True, points=points, coverage=coverage,
                      missing_dimensions=missing, unreliable_dimensions=unreliable,
                      dimension_status=status)


def _brief_outlook(outlook: CompassOutlook) -> BriefOutlook:
    return BriefOutlook(
        direction=outlook.direction.value,
        confidence=outlook.confidence.value,
        horizon=outlook.horizon,
        supporting_context_ids=tuple(outlook.supporting_context_ids),
        counter_context_ids=tuple(outlook.counter_context_ids),
        invalidation_conditions=tuple(outlook.invalidation_conditions),
    )


def _tier3(draft: CompassDraft, usable: bool) -> BriefTier3:
    """見通しは**反対材料（RISK）が grounded で残っているときだけ**出す。"""
    if not usable:
        return BriefTier3(available=False,
                          unavailable_reason=draft.abstain_reason or R_DRAFT_NOT_USABLE)
    outlook_points = _grounded(draft.claims, ClaimRole.OUTLOOK)
    risk = _grounded(draft.claims, ClaimRole.RISK)
    if not outlook_points or draft.outlook is None:
        return BriefTier3(available=False, unavailable_reason=R_NO_GROUNDED_OUTLOOK)
    if not risk:
        return BriefTier3(available=False, unavailable_reason=R_NO_GROUNDED_COUNTER_CASE)
    why = _grounded(draft.claims, ClaimRole.WHY)
    refs: List[str] = sorted({p.rule_ref for p in outlook_points + why + risk if p.rule_ref})
    return BriefTier3(available=True, outlook=_brief_outlook(draft.outlook),
                      outlook_points=outlook_points, why=why, risk=risk,
                      principle_refs=tuple(refs))


def build_morning_brief(draft: CompassDraft, package: EvidencePackage) -> MorningBrief:
    """検証済み `CompassDraft` を三段 Morning Brief へ射影する（純関数）。

    `package` は欠落・不確かな次元（missingness）の出所としてだけ使う。
    package と draft の `package_id` が食い違う入力は projection として成立しないため拒否する。
    """
    if draft.package_id != package.package_id:
        raise ValueError(
            f"draft/package mismatch: {draft.package_id!r} != {package.package_id!r}")
    usable = draft.verdict in USABLE_VERDICTS
    tier1 = _tier1(draft, usable)
    tier2 = _tier2(draft, package, usable)
    tier3 = _tier3(draft, usable)
    payload = projection_payload(
        schema_version=MORNING_BRIEF_SCHEMA_VERSION,
        session_date=draft.session_date,
        reference_session=draft.reference_session,
        draft_id=draft.draft_id,
        package_id=draft.package_id,
        verdict=draft.verdict,
        generator=draft.generator,
        abstain_reason=draft.abstain_reason,
        tier1=tier1, tier2=tier2, tier3=tier3)
    return MorningBrief(
        brief_id=make_brief_id(payload),
        session_date=draft.session_date,
        reference_session=draft.reference_session,
        draft_id=draft.draft_id,
        package_id=draft.package_id,
        verdict=draft.verdict,
        generator=draft.generator,
        abstain_reason=draft.abstain_reason,
        tier1=tier1, tier2=tier2, tier3=tier3,
        schema_version=MORNING_BRIEF_SCHEMA_VERSION)
