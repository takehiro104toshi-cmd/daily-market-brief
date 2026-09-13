"""Universe definition（Phase 3.5 §5 / §6）。

breadth等の集計対象を **security master から version付きで定義**する。

- market: プライム（`Mkt` コード。P2-H実測 0111=プライム）
- security type: 普通株のみ（5桁コード末尾 "0"。優先株等の5桁目≠0を除外）。
  ETF / REIT 等は業種コード未設定（S33 = "" / "9999"）で除外する
- listing status: masterに載っている＝上場（endpointは上場銘柄一覧）
- effective date: session_date 以前で最新の master snapshot を使う。
  それが無ければ最古のmasterを**遡って適用**し `master_applied_backwards=True` と
  明示する（survivorship biasの可能性を黙って隠さない——LIMITATION）
- price validity: session当日に有効な価格recordがある銘柄だけを集計に使う
  （universe membership と price availability は別に数える）

Light plan の master は日次snapshot（`Date`）であり、上場廃止日・上場日の履歴は
含まない。過去sessionの正確な構成は**再現できない**ため、その旨をmanifestへ残す。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id, sha256_hex
from .config import UniverseSpec

UNIVERSE_RULE = "universe_membership"

ELIGIBLE = "eligible"
REASON_CODE_MISSING = "code_missing"
REASON_MARKET = "market_not_in_scope"
REASON_NOT_COMMON = "not_common_stock"
REASON_SECTOR = "sector_excluded"


@dataclass(frozen=True, kw_only=True)
class SecurityRef:
    security_id: str
    code: str
    company_name: str = ""
    market_code: str = ""
    sector17_code: str = ""
    sector17_name: str = ""
    sector33_code: str = ""
    sector33_name: str = ""
    scale_category: str = ""
    effective_date: str = ""


@dataclass(frozen=True, kw_only=True)
class EligibilityDecision:
    code: str
    eligible: bool
    reason: str


def _text(row: Mapping, key: str) -> str:
    value = row[key] if key in row.keys() else "" if hasattr(row, "keys") else ""
    return "" if value is None else str(value).strip()


def eligibility(row: Mapping, spec: UniverseSpec) -> EligibilityDecision:
    """master 1行の採否（理由付き。理由は統制語彙）。"""
    code = _text(row, "code")
    if not code:
        return EligibilityDecision(code="", eligible=False, reason=REASON_CODE_MISSING)
    if _text(row, "market_code") not in spec.market_codes:
        return EligibilityDecision(code=code, eligible=False, reason=REASON_MARKET)
    if not any(code.endswith(s) for s in spec.common_stock_code_suffixes):
        return EligibilityDecision(code=code, eligible=False, reason=REASON_NOT_COMMON)
    if _text(row, "sector33_code") in spec.exclude_sector33_codes:
        return EligibilityDecision(code=code, eligible=False, reason=REASON_SECTOR)
    return EligibilityDecision(code=code, eligible=True, reason=ELIGIBLE)


@dataclass(frozen=True, kw_only=True)
class UniverseSnapshot:
    universe_id: str
    version: str
    session_date: str
    master_effective_date: str
    master_applied_backwards: bool
    members: Tuple[SecurityRef, ...]
    excluded_counts: Mapping[str, int] = field(default_factory=dict)
    master_rows: int = 0

    @property
    def token(self) -> str:
        return f"{self.universe_id}:{self.version}"

    @property
    def codes(self) -> Tuple[str, ...]:
        return tuple(m.code for m in self.members)

    @property
    def universe_hash(self) -> str:
        """構成銘柄の内容ハッシュ（同じ構成→同じ値。再現性の確認に使う）。"""
        return sha256_hex("\n".join(sorted(self.codes)).encode("utf-8"))[:24]

    @property
    def snapshot_id(self) -> str:
        return content_id("universe", self.token, self.session_date,
                          self.master_effective_date, self.universe_hash)

    def by_code(self) -> Dict[str, SecurityRef]:
        return {m.code: m for m in self.members}

    def as_dict(self) -> Dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id, "universe_id": self.universe_id,
            "version": self.version, "session_date": self.session_date,
            "master_effective_date": self.master_effective_date,
            "master_applied_backwards": self.master_applied_backwards,
            "master_rows": self.master_rows, "members": len(self.members),
            "universe_hash": self.universe_hash,
            "excluded_counts": dict(self.excluded_counts),
        }


def select_master_for_session(effective_dates: Sequence[str], session_date: str
                              ) -> Tuple[str, bool]:
    """session_date以前で最新のmaster日付。無ければ最古を遡及適用（明示）。"""
    dates = sorted(d for d in effective_dates if d)
    if not dates:
        return "", False
    before = [d for d in dates if d <= session_date]
    if before:
        return before[-1], False
    return dates[0], True


def build_universe(master_rows: Iterable[Mapping], spec: UniverseSpec, *,
                   session_date: str, master_effective_date: str,
                   master_applied_backwards: bool = False) -> UniverseSnapshot:
    """master行 → universe（決定論的。code昇順）。"""
    members: List[SecurityRef] = []
    excluded: Dict[str, int] = {}
    rows = 0
    seen = set()
    for row in master_rows:
        rows += 1
        decision = eligibility(row, spec)
        if not decision.eligible:
            excluded[decision.reason] = excluded.get(decision.reason, 0) + 1
            continue
        if decision.code in seen:
            excluded["duplicate_code"] = excluded.get("duplicate_code", 0) + 1
            continue
        seen.add(decision.code)
        members.append(SecurityRef(
            security_id=_text(row, "security_id") or f"jp:security:{decision.code}",
            code=decision.code, company_name=_text(row, "company_name"),
            market_code=_text(row, "market_code"),
            sector17_code=_text(row, "sector17_code"),
            sector17_name=_text(row, "sector17_name"),
            sector33_code=_text(row, "sector33_code"),
            sector33_name=_text(row, "sector33_name"),
            scale_category=_text(row, "scale_category"),
            effective_date=_text(row, "effective_date") or master_effective_date))
    members.sort(key=lambda m: m.code)
    return UniverseSnapshot(
        universe_id=spec.id, version=spec.version, session_date=session_date,
        master_effective_date=master_effective_date,
        master_applied_backwards=master_applied_backwards,
        members=tuple(members), excluded_counts=excluded, master_rows=rows)
