"""P8-A1R — identity の訂正と 2 軸の解決の test matrix A〜BS（境界 ／ 凍結の一部は `test_screener_intelligence_boundary.py`）。

すべて合成の identity（架空の anchor ・code ・名前 ・出所の参照）。J-Quants ・network ・実データ ・LLM は使わない。書き込みは tmp
だけ。A1 ／ A2 の world は凍結の A1 ／ A2 の test の合成の年表をそのまま使う（A1 ／ A2 の code ・test は変えない）。
"""
from __future__ import annotations

import ast
import builtins
import os
import shutil
import subprocess
import sys
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import identity_correction_model as cm
from src.intelligence.screener_intelligence import identity_correction_store as cs
from src.intelligence.screener_intelligence import identity_remediation_resolver as rr
from src.intelligence.screener_intelligence import identity_resolver as r
from src.intelligence.screener_intelligence import identity_store as s
from src.intelligence.screener_intelligence.identity_correction_model import (
    CorrectionAction, CorrectionHistory, CorrectionHistoryError, CorrectionModelError, CorrectionReason,
    CorrectionReview, IdentityCorrection, ReviewEvidence, ReviewerClass)
from src.intelligence.screener_intelligence.identity_model import (IdentifierAssignment, IdentityHistory,
                                                                   IdentityHistoryError, RetirementReason,
                                                                   SecurityRegistration, SourceClass,
                                                                   SourceProvenance)
from src.intelligence.screener_intelligence.identity_remediation_resolver import (RemediationRequestError,
                                                                                  RemediationStatus, ResolutionMode,
                                                                                  resolve_remediated,
                                                                                  resolve_remediated_at_data_root)
from src.intelligence.screener_intelligence.identity_resolver import IdentityQuery, ResolutionStatus
from tests.intelligence.phase8_runtime_registry import (P8_VR, PHASE8_A1R_RUNTIME, PHASE8_A2_RUNTIME, PHASE8_DOCS,
                                                        PHASE8_PACKAGE, PHASE8_RUNTIME, PHASE8_TESTS,
                                                        is_phase8_addition)
from tests.intelligence.phase7_runtime_registry import is_phase7_addition
from tests.intelligence.test_screener_identity import (COMMON, EX, HR, JQ, JQS, PREFERRED, World, assign, at, cover,
                                                       end_listing, issuer, listing, name, retire, security)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
RETRO = ResolutionMode.RETROSPECTIVE_AUTHORITY
STRICT = ResolutionMode.STRICT_KNOWLEDGE
T2 = at(2020, 6, 1)                                  # 過去の問い合わせの時刻
T3 = at(2025, 3, 1)                                  # 人が誤りを見つけて訂正を受け入れた時刻
AFTER = at(2025, 6, 1)
A1R_MODULES = ("identity_correction_model", "identity_correction_store", "identity_remediation_resolver")
PRIOR_DOCS = ("docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md",
              "docs/databank/PHASE8_PIT_OBSERVATION_CONTRACT.md",
              "docs/databank/PHASE8_JQUANTS_REAL_DATA_MAPPING_AUDIT.md",
              "docs/databank/PHASE8_JQUANTS_OFFICIAL_SPEC_VERIFICATION.md",
              "docs/databank/PHASE8_JQUANTS_VERIFICATION_REMEDIATION.md")


# ---------------------------------------------------------------- 合成の訂正


def review(reviewed_at: datetime = at(2025, 2, 1), *refs: str, reviewer: ReviewerClass = ReviewerClass.HUMAN,
           source: SourceClass = EX) -> CorrectionReview:
    refs = refs or ("exchange:notice-9",)
    return CorrectionReview(reviewer_class=reviewer, reviewed_at=reviewed_at,
                            evidence=tuple(ReviewEvidence(source_class=source, source_ref=ref) for ref in refs))


def hr(known_at: datetime, ref: str = "review:correction-1") -> SourceProvenance:
    return SourceProvenance(source_class=HR, source_record_ref=ref, known_at=known_at)


def supersede(pairs, reason: CorrectionReason, accepted: datetime = T3, rev: CorrectionReview = None):
    return IdentityCorrection(action=CorrectionAction.SUPERSEDE_RECORD, reason=reason,
                              targets=tuple(target.record_id for target, _ in pairs),
                              replacements=tuple(replacement for _, replacement in pairs),
                              review=rev or review(), accepted_at=accepted)


def invalidate(targets, reason: CorrectionReason, accepted: datetime = T3, rev: CorrectionReview = None):
    return IdentityCorrection(action=CorrectionAction.INVALIDATE_RECORD, reason=reason,
                              targets=tuple(target.record_id for target in targets), review=rev or review(),
                              accepted_at=accepted)


def remap(world: World, sec: SecurityRegistration, owner, accepted: datetime = T3) -> SecurityRegistration:
    """同じ anchor（同じ SecurityId）で発行体だけを直した置き換えの claim。"""
    return SecurityRegistration(registration_anchor=sec.registration_anchor, issuer_id=owner.issuer_id,
                                issue_class=sec.issue_class, provenance=hr(accepted))


def fix_mapping(world: World, accepted: datetime = T3) -> IdentityCorrection:
    """B1 は本当は C の上場物だった（Security → Issuer の誤り）。"""
    return supersede([(world.B1, remap(world, world.B1, world.C, accepted))], CorrectionReason.WRONG_ISSUER_MAPPING,
                     accepted)


def fix_code(world: World, accepted: datetime = T3) -> IdentityCorrection:
    """A2 の code は 10015 ではなく Z0016 だった（識別子の値の誤り）。"""
    replacement = IdentifierAssignment(security_id=world.A2.security_id, scheme=JQ, value="Z0016",
                                       effective_from=world.a2_code.effective_from, provenance=hr(accepted))
    return supersede([(world.a2_code, replacement)], CorrectionReason.WRONG_IDENTIFIER_VALUE, accepted)


def drop_name(world: World, accepted: datetime = T3) -> IdentityCorrection:
    """2015 年の社名の変更は証拠で支えられなかった（無効化）。"""
    return invalidate([world.a_name_new], CorrectionReason.NOT_SUPPORTED_BY_EVIDENCE, accepted)


def authority(world: World, *corrections) -> CorrectionHistory:
    return CorrectionHistory(world.history(), corrections)


def q_sec(sec) -> IdentityQuery:
    return IdentityQuery.for_security(sec.security_id)


def q_code(value: str) -> IdentityQuery:
    return IdentityQuery.for_identifier(JQ, value)


def names_of(result) -> set:
    view = result.identity.issuer or result.identity.security
    return {n.value for n in view.names}


def write_identity(root: Path, records) -> s.IdentityStore:
    store = s.IdentityStore.initialize(root)
    for record in records:
        store.append(record)
    return store


def write_all(root: Path, world: World, *corrections) -> cs.CorrectionStore:
    write_identity(root, world.records)
    store = cs.CorrectionStore.initialize(root)
    for correction in corrections:
        store.append(correction)
    return store


def tree_state(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*"))
            if p.is_file()}


class Bootstrap:
    """後から作った authority: 2024 年に上場した Security を、authority は 2026 年に初めて知る。"""

    def __init__(self) -> None:
        known = at(2026, 1, 5)
        self.I = issuer("hr:boot-issuer", known)
        self.S = security(self.I, "hr:boot-security", known)
        self.code = assign(self.S, "Z0050", at(2024, 4, 1), known, HR)
        self.list = listing(self.S, at(2024, 4, 1), known, HR)
        self.cover = cover(at(2024, 1, 1), at(2027, 1, 1), known)
        self.records = [self.I, self.S, self.code, self.list, self.cover]

    def authority(self, *corrections) -> CorrectionHistory:
        return CorrectionHistory(IdentityHistory(self.records), corrections)


@pytest.fixture()
def w() -> World:
    return World()


# ================================================================ A〜D mode の契約


def test_a_strict_knowledge_is_the_default_mode(w: World) -> None:
    result = resolve_remediated(authority(w), q_sec(w.A1), cutoff=T2)
    assert rr.DEFAULT_MODE is STRICT and result.mode is STRICT and not result.retrospective
    assert result.effective_at == result.authority_as_of == T2
    assert result.interpretation == "AS_KNOWN_BY_THE_AUTHORITY_AT_THE_CUTOFF"
    assert result.as_dict()["retrospective"] is False and result.as_dict()["mode"] == "STRICT_KNOWLEDGE"


def test_b_retrospective_requires_the_explicit_mode(w: World) -> None:
    auth = authority(w)
    for kwargs in ({"effective_at": T2, "authority_as_of": AFTER}, {"cutoff": T2, "authority_as_of": AFTER},
                   {"cutoff": T2, "effective_at": T2}):
        with pytest.raises(RemediationRequestError) as err:
            resolve_remediated(auth, q_sec(w.A1), **kwargs)                       # 既定は STRICT のまま
        assert err.value.code == "MODE_PARAMETER_MISMATCH"
    with pytest.raises(RemediationRequestError) as err:
        resolve_remediated(auth, q_sec(w.A1), mode=RETRO, cutoff=T2, effective_at=T2, authority_as_of=AFTER)
    assert err.value.code == "MODE_PARAMETER_MISMATCH"
    for bad in ("RETROSPECTIVE_AUTHORITY", None, 1):
        with pytest.raises(RemediationRequestError) as err:
            resolve_remediated(auth, q_sec(w.A1), mode=bad, cutoff=T2)
        assert err.value.code == "INVALID_MODE"
    result = resolve_remediated(auth, q_sec(w.A1), mode=RETRO, effective_at=T2, authority_as_of=AFTER)
    assert result.retrospective and result.mode is RETRO


def test_c_retrospective_requires_authority_as_of(w: World, tmp_path: Path) -> None:
    auth = authority(w)
    cases = [({"effective_at": T2}, "AUTHORITY_AS_OF_REQUIRED"), ({"authority_as_of": AFTER}, "EFFECTIVE_AT_REQUIRED"),
             ({"effective_at": T2, "authority_as_of": "2025-06-01"}, "AUTHORITY_AS_OF_REQUIRED"),
             ({"effective_at": T2, "authority_as_of": AFTER.replace(tzinfo=None)}, "NAIVE_DATETIME"),
             ({"effective_at": AFTER, "authority_as_of": T2}, "RETROSPECTIVE_REQUIRES_LATER_AUTHORITY")]
    for kwargs, code in cases:
        with pytest.raises(RemediationRequestError) as err:
            resolve_remediated(auth, q_sec(w.A1), mode=RETRO, **kwargs)
        assert err.value.code == code
        with pytest.raises(RemediationRequestError) as err:                        # data root でも読む前に止める
            resolve_remediated_at_data_root(tmp_path / "absent", q_sec(w.A1), mode=RETRO, **kwargs)
        assert err.value.code == code


def test_d_no_implicit_latest_or_now(w: World) -> None:
    auth = authority(w)
    for bad in (None, "2020-06-01", T2.replace(tzinfo=None)):
        with pytest.raises(RemediationRequestError):
            resolve_remediated(auth, q_sec(w.A1), cutoff=bad)
    early = resolve_remediated(auth, q_code("30030"), cutoff=at(2015))
    later = resolve_remediated(auth, q_code("30030"), cutoff=at(2024))
    assert early.identity.security.security_id == w.C1.security_id
    assert later.identity.security.security_id == w.D1.security_id                  # 時刻ごとに答える（最新ではない）
    source = (PACKAGE_DIR / "identity_remediation_resolver.py").read_text(encoding="utf-8")
    names = {n.name for n in ast.walk(ast.parse(source))
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert not {n for n in names if "latest" in n.lower() or "current" in n.lower() or "now" in n.lower().split("_")}


# ================================================================ E〜G 2 つの時間軸


def test_e_effective_time_is_distinct_from_authority_time() -> None:
    boot = Bootstrap()
    strict = resolve_remediated(boot.authority(), q_sec(boot.S), cutoff=at(2024, 6, 1))
    assert strict.status is RemediationStatus.NOT_YET_KNOWN                          # 2024 年の authority は知らない
    retro = resolve_remediated(boot.authority(), q_sec(boot.S), mode=RETRO, effective_at=at(2024, 6, 1),
                               authority_as_of=at(2026, 2, 1))
    assert retro.status is RemediationStatus.FOUND and retro.retrospective
    assert retro.identity.security.listing.effective_from == at(2024, 4, 1)          # 有効時間
    assert boot.S.known_at == at(2026, 1, 5)                                          # 知識の時刻（矛盾しない）
    assert retro.effective_at == at(2024, 6, 1) and retro.authority_as_of == at(2026, 2, 1)
    assert retro.identity.cutoff == at(2024, 6, 1)


def test_f_future_authority_is_excluded_in_strict() -> None:
    boot = Bootstrap()
    before = resolve_remediated(boot.authority(), q_sec(boot.S), cutoff=at(2025, 12, 31))
    assert before.status is RemediationStatus.NOT_YET_KNOWN and before.identity.supporting_record_ids == ()
    after = resolve_remediated(boot.authority(), q_sec(boot.S), cutoff=at(2026, 2, 1))
    assert after.status is RemediationStatus.FOUND


def test_g_a_later_authority_is_selectable_retrospectively() -> None:
    boot = Bootstrap()
    early = resolve_remediated(boot.authority(), q_sec(boot.S), mode=RETRO, effective_at=at(2024, 6, 1),
                               authority_as_of=at(2025, 12, 1))
    late = resolve_remediated(boot.authority(), q_sec(boot.S), mode=RETRO, effective_at=at(2024, 6, 1),
                              authority_as_of=at(2026, 2, 1))
    assert early.status is RemediationStatus.NOT_YET_KNOWN and late.status is RemediationStatus.FOUND
    assert early.authority_version != late.authority_version


# ================================================================ H〜L 無効化


def test_h_invalidation_is_append_only(w: World, tmp_path: Path) -> None:
    store = write_all(tmp_path, w)
    identity_bytes = s.identity_path(tmp_path).read_bytes()
    before = cs.correction_path(tmp_path).read_bytes()
    result = store.append(drop_name(w))
    assert result.status is cs.AppendStatus.APPENDED
    after = cs.correction_path(tmp_path).read_bytes()
    assert after.startswith(before) and after[len(before):] == drop_name(w).canonical_line().encode("utf-8")
    assert s.identity_path(tmp_path).read_bytes() == identity_bytes                  # A1 の journal に書かない
    assert store.append(drop_name(w)).status is cs.AppendStatus.ALREADY_PRESENT


def test_i_the_invalidated_record_remains_present(w: World, tmp_path: Path) -> None:
    write_all(tmp_path, w, drop_name(w))
    history = cs.open_correction_history(tmp_path)
    assert history.identity.contains(w.a_name_new.record_id)
    assert w.a_name_new.canonical_line() in s.identity_path(tmp_path).read_text(encoding="utf-8")
    assert history.corrected_by(w.a_name_new.record_id) == drop_name(w).record_id


def test_j_pre_correction_strict_reproduces_the_old_result(w: World) -> None:
    before = resolve_remediated(authority(w), IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2016))
    after = resolve_remediated(authority(w, drop_name(w)), IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2016))
    assert before.canonical_json() == after.canonical_json()                          # 未来の訂正は漏れない
    assert "アルファホールディングス" in names_of(after)


def test_k_post_correction_strict_applies_the_correction(w: World) -> None:
    result = resolve_remediated(authority(w, drop_name(w)), IdentityQuery.for_issuer(w.A.issuer_id), cutoff=AFTER)
    assert names_of(result) == {"アルファ工業"}
    assert result.correction_record_ids == (drop_name(w).record_id,)


def test_l_retrospective_historical_query_applies_the_selected_later_correction(w: World) -> None:
    result = resolve_remediated(authority(w, drop_name(w)), IdentityQuery.for_issuer(w.A.issuer_id), mode=RETRO,
                                effective_at=at(2016), authority_as_of=AFTER)
    assert names_of(result) == {"アルファ工業"} and result.retrospective
    assert result.interpretation.startswith("ACCORDING_TO_THE_SELECTED_LATER_REVIEWED_AUTHORITY_VIEW")
    assert "NOT_A_TRUTH_CLAIM" in result.as_dict()["interpretation"]
    assert [link.target_record_id for link in result.correction_chain] == [w.a_name_new.record_id]


# ================================================================ M〜S 置き換えと訂正の鎖


def test_m_supersession_requires_explicit_targets(w: World) -> None:
    replacement = remap(w, w.B1, w.C)
    bad = [dict(targets=(), replacements=()), dict(targets=(w.B1.record_id,), replacements=()),
           dict(targets=(w.B1.record_id, w.C1.record_id), replacements=(replacement,)),
           dict(targets=(w.B1.security_id,), replacements=(replacement,))]
    for kwargs in bad:
        with pytest.raises(CorrectionModelError) as err:
            IdentityCorrection(action=CorrectionAction.SUPERSEDE_RECORD, reason=CorrectionReason.WRONG_ISSUER_MAPPING,
                               review=review(), accepted_at=T3, **kwargs)
        assert err.value.code in ("INVALID_TARGETS", "INVALID_REPLACEMENTS")
    with pytest.raises(CorrectionModelError) as err:
        IdentityCorrection(action=CorrectionAction.INVALIDATE_RECORD, reason=CorrectionReason.DUPLICATE_IDENTITY,
                           targets=(w.B1.record_id,), replacements=(replacement,), review=review(), accepted_at=T3)
    assert err.value.code == "INVALID_REPLACEMENTS"


def test_n_no_append_order_latest_wins(w: World) -> None:
    first = fix_mapping(w)
    other = supersede([(w.B1, remap(w, w.B1, w.A, at(2025, 4, 1)))], CorrectionReason.WRONG_ISSUER_MAPPING,
                      at(2025, 4, 1))
    with pytest.raises(CorrectionHistoryError) as err:
        authority(w, first, other)                                                   # 後の append が勝たない
    assert err.value.code == "CONFLICTING_CORRECTION"
    chained = supersede([(first.replacements[0], remap(w, w.B1, w.A, at(2025, 4, 1)))],
                        CorrectionReason.WRONG_ISSUER_MAPPING, at(2025, 4, 1))       # 置き換えを明示で訂正する
    result = resolve_remediated(authority(w, first, chained), q_sec(w.B1), cutoff=AFTER)
    assert result.identity.security.issuer_id == w.A.issuer_id
    assert [link.correction_record_id for link in result.correction_chain] == [first.record_id, chained.record_id]


def test_o_a_missing_target_is_rejected(w: World) -> None:
    ghost = issuer("hr:never-registered", at(2010))
    with pytest.raises(CorrectionHistoryError) as err:
        authority(w, invalidate([ghost], CorrectionReason.DUPLICATE_IDENTITY))
    assert err.value.code == "MISSING_TARGET"


def test_p_a_future_target_is_rejected(w: World) -> None:
    with pytest.raises(CorrectionHistoryError) as err:
        authority(w, invalidate([w.D1], CorrectionReason.DUPLICATE_IDENTITY, at(2020, 1, 1),
                                review(at(2019, 12, 1))))                            # D1 は 2023 年に知られる
    assert err.value.code == "FUTURE_TARGET"


def _human_world():
    """訂正の受理と同じ時刻に人が登録した record を持つ小さな authority（自己 ・循環の検査用）。"""
    known = at(2010)
    one, two = issuer("hr:loop-one", known), issuer("hr:loop-two", known)
    sec = SecurityRegistration(registration_anchor="hr:loop-security", issuer_id=one.issuer_id, issue_class=COMMON,
                               provenance=hr(T3))
    base = [one, two, cover(at(2010), at(2030), known), sec]
    return one, two, sec, IdentityHistory(base)


def test_q_a_self_target_is_rejected() -> None:
    _, _, sec, _ = _human_world()
    with pytest.raises(CorrectionModelError) as err:
        supersede([(sec, sec)], CorrectionReason.WRONG_ISSUER_MAPPING)
    assert err.value.code == "SELF_TARGET"


def test_r_a_correction_cycle_is_rejected() -> None:
    one, two, sec, history = _human_world()
    moved = SecurityRegistration(registration_anchor=sec.registration_anchor, issuer_id=two.issuer_id,
                                 issue_class=COMMON, provenance=hr(T3, "review:correction-2"))
    first = supersede([(sec, moved)], CorrectionReason.WRONG_ISSUER_MAPPING)
    back = supersede([(moved, sec)], CorrectionReason.WRONG_ISSUER_MAPPING)          # 元の record に戻る
    with pytest.raises(CorrectionHistoryError) as err:
        CorrectionHistory(history, [first, back])
    assert err.value.code == "CORRECTION_CYCLE"


def test_s_competing_supersessions_and_cross_kind_corrections_are_rejected(w: World) -> None:
    with pytest.raises(CorrectionHistoryError) as err:
        authority(w, fix_mapping(w), supersede([(w.B1, remap(w, w.B1, w.A))], CorrectionReason.WRONG_ISSUER_MAPPING))
    assert err.value.code == "CONFLICTING_CORRECTION"
    with pytest.raises(CorrectionModelError) as err:
        IdentityCorrection(action=CorrectionAction.INVALIDATE_RECORD, reason=CorrectionReason.DUPLICATE_IDENTITY,
                           targets=(w.B1.record_id, w.B1.record_id), review=review(), accepted_at=T3)
    assert err.value.code == "DUPLICATE_TARGET"
    wrong_kind = listing(w.B1, at(2010), T3, HR)                                     # 人の審査の出所 ・同じ時刻
    with pytest.raises(CorrectionHistoryError) as err:
        authority(w, supersede([(w.B1, wrong_kind)], CorrectionReason.WRONG_ISSUER_MAPPING))
    assert err.value.code == "CROSS_KIND_CORRECTION"


# ================================================================ T〜W Security → Issuer の対応の訂正


def test_t_a_wrong_security_to_issuer_mapping_is_corrected(w: World) -> None:
    auth = authority(w, fix_mapping(w))
    old = resolve_remediated(auth, q_sec(w.B1), cutoff=T2)
    new = resolve_remediated(auth, q_sec(w.B1), cutoff=AFTER)
    retro = resolve_remediated(auth, q_sec(w.B1), mode=RETRO, effective_at=T2, authority_as_of=AFTER)
    assert old.identity.security.issuer_id == w.B.issuer_id and not old.correction_chain
    assert new.identity.security.issuer_id == w.C.issuer_id
    assert retro.identity.security.issuer_id == w.C.issuer_id and retro.retrospective
    assert retro.status is RemediationStatus.FOUND                                   # 2020 年は上場中


def test_u_the_original_security_id_is_unchanged(w: World) -> None:
    correction = fix_mapping(w)
    assert correction.replacements[0].security_id == w.B1.security_id
    moved_anchor = SecurityRegistration(registration_anchor="hr:security-beta-renamed", issuer_id=w.C.issuer_id,
                                        issue_class=COMMON, provenance=hr(T3))
    with pytest.raises(CorrectionHistoryError) as err:
        authority(w, supersede([(w.B1, moved_anchor)], CorrectionReason.WRONG_ISSUER_MAPPING))
    assert err.value.code == "IDENTITY_CHANGE_NOT_ALLOWED"


def test_v_the_original_issuer_remains_traceable(w: World) -> None:
    auth = authority(w, fix_mapping(w))
    issuer_view = resolve_remediated(auth, IdentityQuery.for_issuer(w.B.issuer_id), cutoff=AFTER)
    assert issuer_view.identity.issuer.issuer_id == w.B.issuer_id                     # 消えない（Security が無いだけ）
    assert issuer_view.identity.issuer.securities == ()
    assert auth.identity.contains(w.B1.record_id) and auth.identity.contains(w.B.record_id)
    link = resolve_remediated(auth, q_sec(w.B1), cutoff=AFTER).correction_chain[0]
    assert link.target_record_id == w.B1.record_id
    assert link.replacement_record_id == fix_mapping(w).replacements[0].record_id


def _a2_world():
    from tests.intelligence.test_screener_observation import World as ObservationWorld
    return ObservationWorld()


def test_w_ba_bb_a2_observations_and_subject_authority_are_untouched(tmp_path: Path) -> None:
    from src.intelligence.screener_intelligence import observation_resolver as orr
    from src.intelligence.screener_intelligence import observation_store as ost
    from tests.intelligence.test_screener_observation import q_market, write_world
    from src.intelligence.screener_intelligence.observation_model import MarketField
    world = _a2_world()
    write_world(tmp_path, world)
    query = q_market(world, MarketField.CLOSE)
    a2_before = orr.resolve_at_data_root(tmp_path, query, cutoff=at(2026, 8, 1)).canonical_json()
    observation_bytes = ost.observation_path(tmp_path).read_bytes()
    identity_bytes = s.identity_path(tmp_path).read_bytes()
    accepted = at(2026, 7, 1)
    moved = SecurityRegistration(registration_anchor=world.ids.S1.registration_anchor, issuer_id=world.ids.I2.issuer_id,
                                 issue_class=world.ids.S1.issue_class, provenance=hr(accepted))
    store = cs.CorrectionStore.initialize(tmp_path)
    store.append(supersede([(world.ids.S1, moved)], CorrectionReason.WRONG_ISSUER_MAPPING, accepted,
                           review(at(2026, 6, 30))))
    assert ost.observation_path(tmp_path).read_bytes() == observation_bytes          # BB: 観測を書き換えない
    assert s.identity_path(tmp_path).read_bytes() == identity_bytes                  # BA: A2 の主語の authority
    assert orr.resolve_at_data_root(tmp_path, query, cutoff=at(2026, 8, 1)).canonical_json() == a2_before
    observation = next(iter(ost.open_observation_history(tmp_path).records))
    assert observation.security_id == world.ids.S1.security_id                       # W: SecurityId に付いたまま
    strict = resolve_remediated_at_data_root(tmp_path, q_sec(world.ids.S1), cutoff=at(2025, 6, 2))
    retro = resolve_remediated_at_data_root(tmp_path, q_sec(world.ids.S1), mode=RETRO, effective_at=at(2025, 6, 2),
                                            authority_as_of=at(2026, 8, 1))
    assert strict.identity.security.issuer_id == world.ids.I1.issuer_id
    assert retro.identity.security.issuer_id == world.ids.I2.issuer_id              # 発行体の読み方だけが変わる


# ================================================================ X〜AA 識別子の割り当ての訂正


def test_x_y_z_aa_identifier_assignment_correction(w: World) -> None:
    auth = authority(w, fix_code(w))
    assert resolve_remediated(auth, q_code("10015"), cutoff=T2).identity.security.security_id == w.A2.security_id  # Y
    assert resolve_remediated(auth, q_code("Z0016"), cutoff=T2).status is RemediationStatus.NOT_FOUND
    assert resolve_remediated(auth, q_code("10015"), cutoff=AFTER).status is RemediationStatus.NOT_FOUND          # Z
    assert resolve_remediated(auth, q_code("Z0016"), cutoff=AFTER).identity.security.security_id == w.A2.security_id
    retro = resolve_remediated(auth, q_code("Z0016"), mode=RETRO, effective_at=T2, authority_as_of=AFTER)         # AA
    assert retro.identity.security.security_id == w.A2.security_id and retro.retrospective
    assert resolve_remediated(auth, q_code("10015"), mode=RETRO, effective_at=T2,
                              authority_as_of=AFTER).status is RemediationStatus.NOT_FOUND
    assert [link.target_record_id for link in retro.correction_chain] == [w.a2_code.record_id]
    assert auth.identity.contains(w.a2_code.record_id)                                # X: 元の割り当ては不変


def _interval_pair(w: World, day: datetime):
    retirement = type(w.a1_code_retire)(assignment_record_id=w.a1_code.record_id, effective_to=day,
                                        reason=w.a1_code_retire.reason, provenance=hr(T3))
    new_code = type(w.a1_code_new)(security_id=w.A1.security_id, scheme=JQ, value="10019", effective_from=day,
                                   provenance=hr(T3))
    return retirement, new_code


def test_x_a_wrong_valid_interval_is_corrected_consistently(w: World) -> None:
    retirement, new_code = _interval_pair(w, at(2022, 10, 1))
    both = supersede([(w.a1_code_retire, retirement), (w.a1_code_new, new_code)],
                     CorrectionReason.WRONG_EFFECTIVE_INTERVAL)
    auth = authority(w, both)
    assert resolve_remediated(auth, q_code("10019"), cutoff=at(2022, 10, 2)).status is RemediationStatus.NOT_FOUND
    retro = resolve_remediated(auth, q_code("10019"), mode=RETRO, effective_at=at(2022, 10, 2), authority_as_of=AFTER)
    assert retro.identity.security.security_id == w.A1.security_id
    with pytest.raises(CorrectionHistoryError) as err:                                # 片側だけでは重なる
        authority(w, supersede([(w.a1_code_new, new_code)], CorrectionReason.WRONG_EFFECTIVE_INTERVAL))
    assert err.value.code == "CORRECTION_BREAKS_AUTHORITY"


# ================================================================ AB〜AD 継続


def _continuity_world():
    known = at(2010)
    owner = issuer("hr:cont-issuer", known)
    old = security(owner, "hr:cont-old", known)
    old_code = assign(old, "Z0040", known, known)
    old_list = listing(old, known, known)
    change = at(2024, 4, 1)
    old_retire = retire(old_code, change, change, RetirementReason.REPLACED)
    new = security(owner, "hr:cont-new", change)
    new_code = assign(new, "Z0041", change, change)
    records = [owner, old, old_code, old_list, cover(at(2010), at(2030), known),
               name(old, "シグマ工業 普通株式", known, known), old_retire, new, new_code,
               name(new, "シグマ工業 普通株式", change, change)]
    return owner, old, new, old_code, new_code, records


def test_ab_continuity_is_not_inferred_from_a_name() -> None:
    _, old, new, _, new_code, records = _continuity_world()
    auth = CorrectionHistory(IdentityHistory(records))
    for mode_kwargs in ({"cutoff": AFTER}, {"mode": RETRO, "effective_at": at(2024, 6, 1), "authority_as_of": AFTER}):
        found = resolve_remediated(auth, q_code("Z0041"), **mode_kwargs)
        assert found.identity.security.security_id == new.security_id != old.security_id   # 同名でも別
    with pytest.raises(IdentityHistoryError) as err:                                  # 同じ Security への 2 本目は権限が要る
        IdentityHistory(records + [assign(old, "Z0041", at(2024, 4, 1), at(2024, 5, 1), JQS)])
    assert err.value.code in ("CONFLICTING_ASSIGNMENT", "CONTINUITY_NOT_AUTHORIZED")
    machine_like = assign(old, "Z0042", at(2024, 4, 1), T3, JQS)
    with pytest.raises(CorrectionModelError) as err:
        supersede([(new_code, machine_like)], CorrectionReason.WRONG_CONTINUITY)
    assert err.value.code == "REPLACEMENT_NOT_HUMAN_REVIEWED"


def test_ac_continuity_is_not_inferred_from_a_code(w: World) -> None:
    auth = authority(w)
    for kwargs in ({"cutoff": at(2015)}, {"mode": RETRO, "effective_at": at(2015), "authority_as_of": AFTER}):
        assert resolve_remediated(auth, q_code("30030"), **kwargs).identity.security.security_id == w.C1.security_id
    for kwargs in ({"cutoff": at(2024)}, {"mode": RETRO, "effective_at": at(2024), "authority_as_of": AFTER}):
        assert resolve_remediated(auth, q_code("30030"), **kwargs).identity.security.security_id == w.D1.security_id
    assert auth.records == () and w.C1.security_id != w.D1.security_id               # 自動の訂正 ・統合なし


def test_ad_explicit_human_continuity_is_accepted() -> None:
    _, old, new, _, new_code, records = _continuity_world()
    continued = type(new_code)(security_id=old.security_id, scheme=JQ, value="Z0041",
                               effective_from=new_code.effective_from, provenance=hr(T3))
    correction = supersede([(new_code, continued)], CorrectionReason.WRONG_CONTINUITY)
    auth = CorrectionHistory(IdentityHistory(records), [correction])
    strict = resolve_remediated(auth, q_code("Z0041"), cutoff=at(2024, 6, 1))
    retro = resolve_remediated(auth, q_code("Z0041"), mode=RETRO, effective_at=at(2024, 6, 1), authority_as_of=AFTER)
    assert strict.identity.security.security_id == new.security_id                   # 訂正の前の知識
    assert retro.identity.security.security_id == old.security_id                    # 人の審査の継続
    assert {i.value for i in retro.identity.security.identifiers} == {"Z0041"}
    assert resolve_remediated(auth, q_sec(new), cutoff=AFTER).identity.security.identifiers == ()   # 消さない


# ================================================================ AE〜AG 統合 ・分割の境界


def test_ae_a_merge_is_never_implicit() -> None:
    known = at(2010)
    first, second = issuer("hr:twin-one", known), issuer("hr:twin-two", known)
    records = [first, second, cover(at(2010), at(2030), known), name(first, "オメガ商事", known, known),
               name(second, "オメガ商事", known, known)]
    auth = CorrectionHistory(IdentityHistory(records))
    one = resolve_remediated(auth, IdentityQuery.for_issuer(first.issuer_id), cutoff=AFTER)
    two = resolve_remediated(auth, IdentityQuery.for_issuer(second.issuer_id), cutoff=AFTER)
    assert one.identity.issuer.issuer_id != two.identity.issuer.issuer_id           # 同名でも別の Issuer
    assert "MERGE" not in {a.value for a in CorrectionAction}
    renamed = issuer("hr:twin-merged", T3)                                           # 人の審査 ・受理と同じ時刻
    with pytest.raises(CorrectionHistoryError) as err:                                # 訂正で id を変えない
        CorrectionHistory(IdentityHistory(records), [supersede([(second, renamed)], CorrectionReason.DUPLICATE_IDENTITY)])
    assert err.value.code == "IDENTITY_CHANGE_NOT_ALLOWED"


def test_af_a_merge_like_cycle_is_rejected_but_an_explicit_revert_is_a_new_claim() -> None:
    one, two, sec, history = _human_world()
    moved = SecurityRegistration(registration_anchor=sec.registration_anchor, issuer_id=two.issuer_id,
                                 issue_class=COMMON, provenance=hr(T3, "review:correction-2"))
    first = supersede([(sec, moved)], CorrectionReason.WRONG_ISSUER_MAPPING)
    with pytest.raises(CorrectionHistoryError) as err:
        CorrectionHistory(history, [first, supersede([(moved, sec)], CorrectionReason.WRONG_ISSUER_MAPPING)])
    assert err.value.code == "CORRECTION_CYCLE"
    revert = SecurityRegistration(registration_anchor=sec.registration_anchor, issuer_id=one.issuer_id,
                                  issue_class=COMMON, provenance=hr(AFTER, "review:correction-3"))
    auth = CorrectionHistory(history, [first, supersede([(moved, revert)], CorrectionReason.WRONG_ISSUER_MAPPING,
                                                        AFTER, review(AFTER))])
    assert resolve_remediated(auth, q_sec(sec), cutoff=AFTER).identity.security.issuer_id == one.issuer_id


def test_ag_a_corporate_spin_off_is_not_modeled_as_identity_correction(w: World) -> None:
    members = {m.value for m in CorrectionAction} | {m.value for m in CorrectionReason}
    assert not any(word in value for value in members for word in ("SPIN", "SPLIT", "MERGE", "RESTRUCTUR"))
    auth = authority(w, fix_mapping(w))
    early = resolve_remediated(auth, q_sec(w.B1), mode=RETRO, effective_at=at(2011), authority_as_of=AFTER)
    assert early.identity.security.issuer_id == w.C.issuer_id                        # 登録の訂正は全期間（日付で分けない）
    assert "effective_from" not in {f.name for f in fields(IdentityCorrection)}


# ================================================================ AH〜AN authority の版


def test_ah_ai_the_authority_version_is_deterministic_and_content_addressed(w: World) -> None:
    one = authority(w, fix_mapping(w)).pin(AFTER)
    two = authority(World(), fix_mapping(World())).pin(AFTER)
    assert one.version == two.version and cm.is_authority_version(one.version)
    assert one.version == cm.authority_version(one.identity_record_ids, one.correction_record_ids)
    assert authority(w).pin(AFTER).version != one.version


def test_aj_an_append_known_by_the_cutoff_changes_the_version(w: World) -> None:
    base = authority(w).pin(at(2030)).version
    extra = IdentityHistory(w.records + [name(w.B, "ベータ", at(2027, 1, 1), at(2027, 1, 1))])
    assert CorrectionHistory(extra).pin(at(2030)).version != base
    correction = invalidate([w.a_name_new], CorrectionReason.NOT_SUPPORTED_BY_EVIDENCE, at(2028), review(at(2028)))
    assert authority(w, correction).pin(at(2030)).version != base


def test_ak_path_and_mtime_are_irrelevant(w: World, tmp_path: Path) -> None:
    write_all(tmp_path / "one", w, fix_mapping(w))
    shutil.copytree(tmp_path / "one", tmp_path / "two")
    for path in (tmp_path / "two").rglob("*.jsonl"):
        os.utime(path, (1, 1))
    versions = {resolve_remediated_at_data_root(tmp_path / name, q_sec(w.B1), cutoff=AFTER).authority_version
                for name in ("one", "two")}
    assert len(versions) == 1


def test_al_clock_and_randomness_are_irrelevant(w: World) -> None:
    code = ("from tests.intelligence.test_screener_identity_remediation import authority, fix_mapping, AFTER\n"
            "from tests.intelligence.test_screener_identity import World\n"
            "w = World()\nprint(authority(w, fix_mapping(w)).pin(AFTER).version)\n")
    outputs = {subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                              env={"PYTHONPATH": str(REPO_ROOT), "PYTHONHASHSEED": seed, "PATH": ""}).stdout
               for seed in ("1", "2", "3")}
    assert outputs == {authority(w, fix_mapping(w)).pin(AFTER).version + "\n"}


def test_am_a_pinned_version_replays_and_a_mismatch_fails_closed(w: World) -> None:
    auth = authority(w, fix_mapping(w))
    free = resolve_remediated(auth, q_sec(w.B1), mode=RETRO, effective_at=T2, authority_as_of=AFTER)
    pinned = resolve_remediated(auth, q_sec(w.B1), mode=RETRO, effective_at=T2, authority_as_of=AFTER,
                                expected_authority_version=free.authority_version)
    assert pinned.canonical_json() == free.canonical_json()
    other = authority(w).pin(AFTER).version
    mismatch = resolve_remediated(auth, q_sec(w.B1), mode=RETRO, effective_at=T2, authority_as_of=AFTER,
                                  expected_authority_version=other)
    assert mismatch.status is RemediationStatus.AUTHORITY_VERSION_MISMATCH and mismatch.identity is None
    with pytest.raises(RemediationRequestError) as err:
        resolve_remediated(auth, q_sec(w.B1), cutoff=T2, expected_authority_version="latest")
    assert err.value.code == "INVALID_AUTHORITY_VERSION"


def test_an_a_future_append_does_not_change_a_pinned_retrospective_result(w: World) -> None:
    before = resolve_remediated(authority(w, fix_mapping(w)), q_sec(w.B1), mode=RETRO, effective_at=T2,
                                authority_as_of=AFTER)
    later_records = w.records + [name(w.C, "ガンマ", at(2026, 2, 1), at(2026, 2, 1))]
    later = CorrectionHistory(IdentityHistory(later_records),
                              [fix_mapping(w), invalidate([w.a_name_new], CorrectionReason.NOT_SUPPORTED_BY_EVIDENCE,
                                                          at(2026, 3, 1), review(at(2026, 3, 1)))])
    after = resolve_remediated(later, q_sec(w.B1), mode=RETRO, effective_at=T2, authority_as_of=AFTER,
                               expected_authority_version=before.authority_version)
    assert after.canonical_json() == before.canonical_json()


# ================================================================ AO〜AS 出所と人の審査


def test_ao_correction_provenance_is_exposed(w: World) -> None:
    correction = fix_mapping(w)
    result = resolve_remediated(authority(w, correction), q_sec(w.B1), mode=RETRO, effective_at=T2,
                                authority_as_of=AFTER)
    link = result.correction_chain[0].as_dict()
    assert link == {"accepted_at": "2025-03-01T00:00:00+00:00", "action": "SUPERSEDE_RECORD",
                    "correction_record_id": correction.record_id, "evidence_refs": ["exchange:notice-9"],
                    "reason": "WRONG_ISSUER_MAPPING", "replacement_record_id": correction.replacements[0].record_id,
                    "reviewed_at": "2025-02-01T00:00:00+00:00", "reviewer_class": "HUMAN",
                    "target_record_id": w.B1.record_id}
    assert correction.record_id in result.authority_record_ids
    assert correction.replacements[0].record_id in result.authority_record_ids
    for key in ("mode", "effective_at", "authority_as_of", "authority_version", "correction_chain", "status",
                "retrospective", "interpretation", "authority_record_ids"):
        assert key in result.as_dict()


def test_ap_human_review_is_required(w: World) -> None:
    machine_source = remap(w, w.B1, w.C)
    machine_source = SecurityRegistration(registration_anchor=machine_source.registration_anchor,
                                          issuer_id=machine_source.issuer_id, issue_class=COMMON,
                                          provenance=SourceProvenance(source_class=EX, source_record_ref="exchange:x",
                                                                      known_at=T3))
    cases = [(lambda: supersede([(w.B1, machine_source)], CorrectionReason.WRONG_ISSUER_MAPPING),
              "REPLACEMENT_NOT_HUMAN_REVIEWED"),
             (lambda: supersede([(w.B1, remap(w, w.B1, w.C, AFTER))], CorrectionReason.WRONG_ISSUER_MAPPING),
              "REPLACEMENT_KNOWN_AT_MISMATCH"),
             (lambda: fix_mapping(w, at(2025, 1, 1)), "ACCEPTED_BEFORE_REVIEW"),
             (lambda: CorrectionReview(reviewer_class=ReviewerClass.HUMAN, reviewed_at=T3, evidence=()),
              "INVALID_EVIDENCE")]
    for build, code in cases:
        with pytest.raises(CorrectionModelError) as err:
            build()
        assert err.value.code == code


def test_aq_machine_authority_is_rejected(w: World, tmp_path: Path) -> None:
    with pytest.raises(CorrectionModelError) as err:
        review(reviewer=ReviewerClass.MACHINE)
    assert err.value.code == "REVIEWER_NOT_AUTHORIZED"
    assert cm.AUTHORIZED_REVIEWERS == frozenset({ReviewerClass.HUMAN})
    line = drop_name(w).canonical_line().replace('"reviewer_class":"HUMAN"', '"reviewer_class":"MACHINE"')
    with pytest.raises(CorrectionModelError) as err:
        cm.parse_correction_line(line)
    assert err.value.code == "REVIEWER_NOT_AUTHORIZED"
    write_all(tmp_path, w)
    cs.correction_path(tmp_path).write_text(line, encoding="utf-8")
    result = resolve_remediated_at_data_root(tmp_path, q_sec(w.A1), cutoff=AFTER)
    assert result.status is RemediationStatus.STORE_CORRUPTION


def test_ar_raw_payload_is_rejected(w: World) -> None:
    for ref, code in [('{"raw": "payload"}', "INVALID_EVIDENCE_REF"), ("exchange/notice", "INVALID_EVIDENCE_REF"),
                      ("x" * 200, "INVALID_EVIDENCE_REF"), ("review:api_key-1", "CREDENTIAL_LIKE_TEXT")]:
        with pytest.raises(CorrectionModelError) as err:
            ReviewEvidence(source_class=EX, source_ref=ref)
        assert err.value.code == code
    with pytest.raises(CorrectionModelError) as err:
        ReviewEvidence(source_class=EX, source_ref="exchange:notice-9", digest="not-a-digest")
    assert err.value.code == "INVALID_DIGEST"
    assert ReviewEvidence(source_class=EX, source_ref="exchange:notice-9", digest="a" * 64).digest == "a" * 64
    line = drop_name(w).canonical_line().replace('"payload":{', '"payload":{"raw_payload":"x",')
    with pytest.raises(CorrectionModelError) as err:
        cm.parse_correction_line(line)
    assert err.value.code == "UNKNOWN_FIELD"


def test_as_reviewer_identity_is_not_needed(w: World) -> None:
    assert {f.name for f in fields(CorrectionReview)} == {"reviewer_class", "reviewed_at", "evidence"}
    assert {f.name for f in fields(IdentityCorrection)} == {"action", "reason", "targets", "replacements", "review",
                                                            "accepted_at"}
    line = drop_name(w).canonical_line().replace('"reviewer_class":"HUMAN"',
                                                 '"reviewer_class":"HUMAN","reviewer_name":"x"')
    with pytest.raises(CorrectionModelError) as err:
        cm.parse_correction_line(line)
    assert err.value.code == "UNKNOWN_FIELD"


# ================================================================ AT〜AU coverage


def test_at_coverage_is_enforced_in_strict_mode(w: World) -> None:
    assert resolve_remediated(authority(w), q_sec(w.A1), cutoff=at(2009)).status is RemediationStatus.NOT_YET_KNOWN
    boot = Bootstrap()
    assert resolve_remediated(boot.authority(), q_sec(boot.S), cutoff=at(2027, 6, 1)).status is \
        RemediationStatus.NOT_YET_KNOWN


def test_au_retrospective_mode_cannot_bypass_coverage() -> None:
    boot = Bootstrap()
    before = resolve_remediated(boot.authority(), q_sec(boot.S), mode=RETRO, effective_at=at(2023, 6, 1),
                                authority_as_of=at(2026, 2, 1))
    assert before.status is RemediationStatus.BEFORE_COVERAGE                        # 過去へ埋めない
    beyond = resolve_remediated(boot.authority(), q_sec(boot.S), mode=RETRO, effective_at=at(2027, 6, 1),
                                authority_as_of=at(2027, 7, 1))
    assert beyond.status is RemediationStatus.NOT_YET_KNOWN
    dropped = invalidate([boot.cover], CorrectionReason.WRONG_COVERAGE, at(2026, 3, 1), review(at(2026, 3, 1)))
    gone = resolve_remediated(boot.authority(dropped), q_sec(boot.S), mode=RETRO, effective_at=at(2024, 6, 1),
                              authority_as_of=at(2026, 4, 1))
    assert gone.status is RemediationStatus.NOT_YET_KNOWN
    assert [link.target_record_id for link in gone.correction_chain] == [boot.cover.record_id]


# ================================================================ AV〜AY A1 との互換


QUERIES = ["A1", "A2", "B1", "C1", "D1", "issuer:A", "issuer:B", "issuer:D", "code:10010", "code:10019", "code:30030",
           "code:10015", "class:A:COMMON", "class:A:PREFERRED", "class:B:COMMON"]
CUTOFFS = [at(2009, 6, 1), at(2010), at(2015, 6, 1), at(2018, 4, 2), at(2019, 4, 1), at(2021, 6, 30), at(2021, 7, 1),
           at(2022, 10, 3), at(2023, 4, 3), at(2026, 6, 1), at(2027, 6, 1)]


def _query(w: World, key: str) -> IdentityQuery:
    kind, _, rest = key.partition(":")
    if kind == "issuer":
        return IdentityQuery.for_issuer(getattr(w, rest).issuer_id)
    if kind == "code":
        return q_code(rest)
    if kind == "class":
        owner, klass = rest.split(":")
        return IdentityQuery.for_issuer_security(getattr(w, owner).issuer_id, COMMON if klass == "COMMON" else PREFERRED)
    return q_sec(getattr(w, key))


@pytest.mark.parametrize("key", QUERIES)
def test_av_without_corrections_strict_is_identical_to_frozen_a1(w: World, key: str) -> None:
    history, auth = w.history(), authority(w)
    for cutoff in CUTOFFS:
        a1 = r.resolve(history, _query(w, key), cutoff=cutoff)
        a1r = resolve_remediated(auth, _query(w, key), cutoff=cutoff)
        assert a1r.identity.canonical_json() == a1.canonical_json(), (key, cutoff)
        assert a1r.status.value == a1.status.value and a1r.correction_chain == ()


def test_av_without_corrections_the_data_root_path_matches_frozen_a1(w: World, tmp_path: Path) -> None:
    write_all(tmp_path, w)
    for key in QUERIES:
        for cutoff in CUTOFFS:
            a1 = r.resolve_at_data_root(tmp_path, _query(w, key), cutoff=cutoff)
            a1r = resolve_remediated_at_data_root(tmp_path, _query(w, key), cutoff=cutoff)
            assert a1r.identity.canonical_json() == a1.canonical_json(), (key, cutoff)


def test_aw_code_reuse_semantics_are_preserved(w: World) -> None:
    auth = authority(w)
    expected = {at(2015): w.C1.security_id, at(2020): None, at(2024): w.D1.security_id}
    for cutoff, security_id in expected.items():
        result = resolve_remediated(auth, q_code("30030"), cutoff=cutoff)
        assert (result.identity.security.security_id if result.identity.security else None) == security_id


def test_ax_delisting_semantics_are_preserved(w: World) -> None:
    auth = authority(w)
    listed = resolve_remediated(auth, q_sec(w.C1), cutoff=at(2019, 3, 31))
    ended = resolve_remediated(auth, q_sec(w.C1), cutoff=at(2020))
    assert listed.status is RemediationStatus.FOUND
    assert ended.status is RemediationStatus.NOT_ACTIVE_AT_CUTOFF and ended.identity.security is not None


def test_ay_multiple_securities_semantics_are_preserved(w: World) -> None:
    auth = authority(w)
    issuer_view = resolve_remediated(auth, IdentityQuery.for_issuer(w.A.issuer_id), cutoff=at(2020)).identity.issuer
    assert {s_.security_id for s_ in issuer_view.securities} == {w.A1.security_id, w.A2.security_id}
    preferred = resolve_remediated(auth, IdentityQuery.for_issuer_security(w.A.issuer_id, PREFERRED), cutoff=at(2020))
    assert preferred.identity.security.security_id == w.A2.security_id


# ================================================================ AZ A2 の凍結


def test_az_a2_and_a1_runtime_are_byte_frozen() -> None:
    reopened = (f"{PHASE8_PACKAGE}/observation_model.py", f"{PHASE8_PACKAGE}/observation_resolver.py")  # P8-A2C
    for path in (p for p in PHASE8_A2_RUNTIME if p not in reopened):
        shown = subprocess.run(["git", "show", f"{P8_VR}:{path}"], cwd=REPO_ROOT, capture_output=True, text=True,
                               check=True).stdout
        assert shown == (REPO_ROOT / path).read_text(encoding="utf-8"), path


# ================================================================ BC〜BF fail closed


def test_bc_missing_authority_fails_closed(w: World, tmp_path: Path) -> None:
    missing = resolve_remediated_at_data_root(tmp_path, q_sec(w.A1), cutoff=AFTER)
    assert missing.status is RemediationStatus.AUTHORITY_MISSING and missing.identity is None
    assert missing.diagnostic == "IDENTITY_AUTHORITY_MISSING"
    with pytest.raises(cs.CorrectionAuthorityMissing):
        cs.CorrectionStore.initialize(tmp_path)
    write_identity(tmp_path, w.records)
    no_corrections = resolve_remediated_at_data_root(tmp_path, q_sec(w.A1), cutoff=AFTER)
    assert no_corrections.status is RemediationStatus.AUTHORITY_MISSING                  # 空の訂正として扱わない
    assert no_corrections.diagnostic == "CORRECTIONS_MISSING"
    assert not cs.correction_path(tmp_path).exists()


@pytest.mark.parametrize("damage,reason", [
    (lambda text: text[:-1], "TRUNCATED_FINAL_LINE"),
    (lambda text: text + "\n", "BLANK_LINE"),
    (lambda text: text.replace('"action":', '"action" :', 1), "INVALID_RECORD"),
    (lambda text: text.replace("p8idc_", "p8idc_0", 1), "INVALID_RECORD"),
    (lambda text: text + text, "PHYSICAL_DUPLICATE"),
])
def test_bd_corruption_fails_closed(w: World, tmp_path: Path, damage, reason: str) -> None:
    write_all(tmp_path, w, drop_name(w))
    path = cs.correction_path(tmp_path)
    path.write_text(damage(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(cs.CorrectionStoreCorrupt) as err:
        cs.CorrectionStore.open(tmp_path, read_only=True)
    assert err.value.code == reason
    result = resolve_remediated_at_data_root(tmp_path, q_sec(w.A1), cutoff=AFTER)
    assert result.status is RemediationStatus.STORE_CORRUPTION and result.diagnostic.startswith(reason)
    identity_path = s.identity_path(tmp_path)
    identity_path.write_bytes(identity_path.read_bytes()[:-1])
    corrupt = resolve_remediated_at_data_root(tmp_path, q_sec(w.A1), cutoff=AFTER)
    assert corrupt.status is RemediationStatus.STORE_CORRUPTION and corrupt.diagnostic.startswith("IDENTITY_")


def test_be_conflicting_corrections_fail_closed(w: World, tmp_path: Path) -> None:
    store = write_all(tmp_path, w)
    retirement, new_code = _interval_pair(w, at(2022, 10, 1))
    with pytest.raises(cs.CorrectionAppendRejected) as err:
        store.append(supersede([(w.a1_code_new, new_code)], CorrectionReason.WRONG_EFFECTIVE_INTERVAL))
    assert err.value.code == "CORRECTION_BREAKS_AUTHORITY"
    store.append(fix_code(w))                                                         # A2 は Z0016 になった
    identity = s.IdentityStore.open(tmp_path)
    late = at(2026, 2, 1)
    clash_issuer = issuer("hr:clash-issuer", late)
    clash = security(clash_issuer, "hr:clash-security", late)
    for record in (clash_issuer, clash, assign(clash, "Z0016", late, late, JQS)):
        identity.append(record)                                                       # A1 は訂正を知らないので受け付ける
    ok = resolve_remediated_at_data_root(tmp_path, q_code("Z0016"), cutoff=at(2025, 4, 1))
    assert ok.status is RemediationStatus.FOUND
    clash_result = resolve_remediated_at_data_root(tmp_path, q_code("Z0016"), cutoff=at(2026, 3, 1))
    assert clash_result.status is RemediationStatus.CORRECTION_CONFLICT and clash_result.identity is None
    with pytest.raises(cs.CorrectionAppendRejected):                                  # 以後の訂正も fail closed
        cs.CorrectionStore.open(tmp_path).append(drop_name(w, at(2026, 4, 1)))


def test_bf_no_auto_repair(w: World, tmp_path: Path) -> None:
    write_all(tmp_path, w, drop_name(w))
    path = cs.correction_path(tmp_path)
    path.write_bytes(path.read_bytes()[:-5])
    state = tree_state(tmp_path)
    for _ in range(2):
        assert resolve_remediated_at_data_root(tmp_path, q_sec(w.A1), cutoff=AFTER).status is \
            RemediationStatus.STORE_CORRUPTION
        with pytest.raises(cs.CorrectionStoreCorrupt):
            cs.CorrectionStore.open(tmp_path)
    assert tree_state(tmp_path) == state


def test_bf_append_detects_concurrent_modification_and_read_only(w: World, tmp_path: Path) -> None:
    store = write_all(tmp_path, w)
    with pytest.raises(cs.CorrectionAppendRejected) as err:
        cs.CorrectionStore.open(tmp_path, read_only=True).append(drop_name(w))
    assert err.value.code == "READ_ONLY"
    with cs.correction_path(tmp_path).open("ab") as handle:
        handle.write(drop_name(w).canonical_line().encode("utf-8"))
    with pytest.raises(cs.CorrectionConcurrentModification):
        store.append(fix_mapping(w))


# ================================================================ BG〜BH 書き込みなし ・再生


def test_bg_resolution_writes_nothing(w: World, tmp_path: Path, monkeypatch) -> None:
    write_all(tmp_path, w, fix_mapping(w))
    state = tree_state(tmp_path)
    real_open = builtins.open

    def guarded(file, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in "wax+"), mode
        return real_open(file, mode, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.setattr(os, "fsync", lambda *_: (_ for _ in ()).throw(AssertionError("fsync")))
    expected = {"cutoff": RemediationStatus.NOT_ACTIVE_AT_CUTOFF, "mode": RemediationStatus.FOUND}
    for kwargs in ({"cutoff": AFTER}, {"mode": RETRO, "effective_at": T2, "authority_as_of": AFTER}):
        status = resolve_remediated_at_data_root(tmp_path, q_sec(w.B1), **kwargs).status
        assert status is expected[next(iter(kwargs))]
    monkeypatch.undo()
    assert tree_state(tmp_path) == state


def test_bh_resolution_replays_deterministically(w: World, tmp_path: Path) -> None:
    write_all(tmp_path, w, fix_mapping(w), fix_code(w, at(2025, 4, 1)))
    runs = {resolve_remediated_at_data_root(tmp_path, q_sec(w.B1), mode=RETRO, effective_at=T2,
                                            authority_as_of=AFTER).canonical_json() for _ in range(3)}
    assert len(runs) == 1
    assert runs == {resolve_remediated(authority(w, fix_mapping(w), fix_code(w, at(2025, 4, 1))), q_sec(w.B1),
                                       mode=RETRO, effective_at=T2, authority_as_of=AFTER).canonical_json()}


# ================================================================ BI〜BO 境界（A1R の module）


FORBIDDEN = {"jquants": ("jquants", "jquants_ops", "market", "providers", "provider"),
             "network": ("urllib", "socket", "http", "requests", "httpx", "anthropic", "openai", "sqlite3"),
             "screening": ("screening", "compass", "facts", "internals"),
             "theme_narrative": ("themes", "theme_intelligence", "narrative_intelligence"),
             "p5_dna": ("predictions", "evaluation", "calibration", "knowledge"),
             "public_trading": ("pages", "public", "notifiers", "delivery", "trading", "portfolio", "reports")}


def _imports(path: Path) -> set:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


@pytest.mark.parametrize("group", sorted(FORBIDDEN))
@pytest.mark.parametrize("module", A1R_MODULES)
def test_bi_to_bo_the_remediation_modules_import_no_forbidden_domain(module: str, group: str) -> None:
    for imported in _imports(PACKAGE_DIR / f"{module}.py"):
        assert not set(imported.split(".")) & set(FORBIDDEN[group]), (module, imported)


def test_bk_bl_no_screening_or_derived_metric_vocabulary() -> None:
    for module in A1R_MODULES:
        source = (PACKAGE_DIR / f"{module}.py").read_text(encoding="utf-8").lower()
        for token in ("revenue", "margin", "per_", "pbr", "roe", "market_cap", "rank", "score", "screen(",
                      "criterion", "candidate_result"):
            assert token not in source, (module, token)


# ================================================================ BP〜BS registry ・凍結


def test_bp_the_phase8_registry_is_exact_for_a1r() -> None:
    assert PHASE8_A1R_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in A1R_MODULES)
    assert set(PHASE8_A1R_RUNTIME) <= set(PHASE8_RUNTIME)
    assert "tests/intelligence/test_screener_identity_remediation.py" in PHASE8_TESTS
    assert "docs/databank/PHASE8_IDENTITY_REMEDIATION_CONTRACT.md" in PHASE8_DOCS
    for path in (*PHASE8_A1R_RUNTIME, "docs/databank/PHASE8_IDENTITY_REMEDIATION_CONTRACT.md"):
        assert (REPO_ROOT / path).is_file(), path


def test_bq_an_unregistered_runtime_is_rejected() -> None:
    for fake in (f"{PHASE8_PACKAGE}/identity_merge_engine.py", f"{PHASE8_PACKAGE}/identity_correction_cache.py"):
        for status in ("A", "??"):
            assert not is_phase8_addition(status, fake) and not is_phase7_addition(status, fake)
    for path in PHASE8_A1R_RUNTIME:
        assert is_phase8_addition("A", path) and is_phase7_addition("A", path)
        assert not is_phase8_addition("M", path)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def test_br_phase6_and_phase7_are_frozen() -> None:
    assert _git("diff", "--name-status", P8_VR, "--", "src/intelligence/themes", "src/intelligence/theme_intelligence",
                "src/intelligence/narrative_intelligence", "knowledge") == ""


def test_bs_prior_phase8_audit_documents_are_frozen() -> None:
    for path in PRIOR_DOCS:
        assert _git("show", f"{P8_VR}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
