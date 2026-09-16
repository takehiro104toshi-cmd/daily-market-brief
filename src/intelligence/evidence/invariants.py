"""Evidence不変条件の導出関数（Phase 1-A）。

構築時に強制できない「グラフ横断の不変条件」を純関数として提供する。
ストレージやエンジンに埋め込まず、どの実装からも同じ判定が得られるようにする。

- FACT RULE: SUPPORTSリンクを1つも持たないFactStatementは UNSUPPORTED。
  AI生成文を自動的にFACT扱いしない（リンクが張られるまで裏付け無しと判定される）。
- CONFLICT RULE: SUPPORTSとCONTRADICTSが併存する言明は CONFLICTING。
  どちらのEvidenceも削除しない。
- STALE / RETRACTED は導出しない（明示的に設定される状態。valid_untilの経過判定は
  Clock依存のためis_stale()で別途提供）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from ..core.time import ensure_aware
from ..core.types import StatementType, VerificationState
from .model import EvidenceLink, EvidenceRelation, FactStatement, Statement


def links_by_claim(links: Iterable[EvidenceLink]) -> Dict[str, Tuple[EvidenceLink, ...]]:
    grouped: Dict[str, list] = {}
    for link in links:
        grouped.setdefault(link.claim_id, []).append(link)
    return {k: tuple(v) for k, v in grouped.items()}


def derive_verification(
    statement: Statement, links: Sequence[EvidenceLink]
) -> VerificationState:
    """言明1件の検証状態をEvidenceリンクから導出する。

    明示的にRETRACTED/STALEが設定済みの言明はそれを維持する（導出で上書きしない）。
    """
    if statement.verification in (VerificationState.RETRACTED, VerificationState.STALE):
        return statement.verification
    own = [l for l in links if l.claim_id == statement.statement_id]
    supports = [l for l in own if l.relation is EvidenceRelation.SUPPORTS]
    contradicts = [l for l in own if l.relation is EvidenceRelation.CONTRADICTS]
    if supports and contradicts:
        return VerificationState.CONFLICTING
    if contradicts and not supports:
        # 裏付けが無く反証のみ: 矛盾状態として保持（自動削除しない）
        return VerificationState.CONFLICTING
    if supports:
        return VerificationState.VERIFIED
    if statement.statement_type is StatementType.FACT:
        return VerificationState.UNSUPPORTED
    return VerificationState.UNVERIFIED


def unsupported_facts(
    statements: Iterable[Statement], links: Iterable[EvidenceLink]
) -> Tuple[FactStatement, ...]:
    """SUPPORTSリンクを持たないFACTを機械的に列挙する（UNSUPPORTED検出）。"""
    grouped = links_by_claim(links)
    result = []
    for stmt in statements:
        if not isinstance(stmt, FactStatement):
            continue
        if derive_verification(stmt, grouped.get(stmt.statement_id, ())) is (
            VerificationState.UNSUPPORTED
        ):
            result.append(stmt)
    return tuple(result)


def conflicting_statements(
    statements: Iterable[Statement], links: Iterable[EvidenceLink]
) -> Tuple[Statement, ...]:
    """相反Evidenceを併せ持つ言明を列挙する（両Evidenceは保持されたまま）。"""
    grouped = links_by_claim(links)
    return tuple(
        s
        for s in statements
        if derive_verification(s, grouped.get(s.statement_id, ()))
        is VerificationState.CONFLICTING
    )


def is_stale(statement: Statement, now: datetime) -> bool:
    """valid_untilを過ぎた言明か（STALE付与の判断材料。付与自体は呼び出し側）。"""
    ensure_aware(now, "now")
    return statement.valid_until is not None and now > statement.valid_until


def trace_analysis(
    analysis_inputs: Mapping[str, Tuple[str, ...]], statement_id: str, depth: int = 10
) -> Tuple[str, ...]:
    """分析の入力を再帰的に辿り、根まで（Fact/Observation ID列）を返す。

    analysis_inputs: statement_id -> inputs のマップ（AnalysisStatement.inputsを集約したもの）。
    入力を持たないIDが「根」（fact/observation）。深さ上限で循環を防ぐ。
    """
    trail: list = []
    frontier = [statement_id]
    for _ in range(depth):
        next_frontier: list = []
        for sid in frontier:
            for input_id in analysis_inputs.get(sid, ()):
                trail.append(input_id)
                next_frontier.append(input_id)
        if not next_frontier:
            break
        frontier = next_frontier
    # 順序保持のまま重複除去
    seen = set()
    unique = []
    for x in trail:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return tuple(unique)
