"""P9-A1 — 凍結の Phase 8 の完了した run の read-only の再構成（引き渡し）の test。合成の P8 の run だけ（実 request なし）。

pin するもの: 完了した run の決定論の再構成 ・P8 root の file の集合 ／ byte の不変 ・無い store を作らずに fail closed ・credential の
環境変数が無くてもよい ・transport ／ client ／ HTTPS ／ socket ／ 実行の経路 ／ store の初期化は呼ばれない（罠）・閉じていない呼び出し ・
PARTIAL ・違う run_id ・spec の不一致 ・台帳の破損は拒む ・drift は P8_RESULT_DRIFT ・P9 の private root の規約。
"""
from __future__ import annotations

import http.client
import json
import socket
from pathlib import Path

import pytest

from src.intelligence import jquants_local_transport as lt
from src.intelligence import jquants_screen_local as sl
from src.intelligence.screener_intelligence import (acquisition_event_store, acquisition_manifest_store,
                                                    held_observation_store, identity_store, observation_store,
                                                    provider_holdings_store, screener_policy_authority_store,
                                                    screener_universe_store, semantic_metadata_store)
from src.intelligence.screener_intelligence.identity_model import canonical_json
from src.intelligence.screener_intelligence.jquants_live_client import JQuantsLiveClient
from src.intelligence.screener_intelligence.jquants_live_model import SyntheticTransport, TransportResponse
from src.intelligence.screener_intelligence.screener_result_set import ExecutionCompleteness
from src.intelligence.watchlist_thesis_intelligence import p8_handoff as ho
from src.intelligence.watchlist_thesis_intelligence import private_root as pr
from src.intelligence.watchlist_thesis_intelligence.p8_handoff import (HandoffError, reconstruct_bound,
                                                                        reconstruct_completed_run, require_binding)
from tests.intelligence.test_screener_jquants_live import master_key
from tests.intelligence.test_screener_multi_issuer_executor import (ACQ, authorities, fins, fins_row, identity, master,
                                                                    run, transport)

CODES = ["90010", "90020"]
STORE_MODULES = (identity_store.IdentityStore, observation_store.ObservationStore,
                 semantic_metadata_store.SemanticMetadataStore, held_observation_store.HeldObservationStore,
                 acquisition_event_store.AcquisitionEventStore, acquisition_manifest_store.ManifestStore,
                 provider_holdings_store.ProviderHoldingsStore, screener_policy_authority_store.PolicyAuthorityStore,
                 screener_universe_store.UniverseAuthorityStore)


def _trap(*_args, **_kwargs):
    raise AssertionError("TRAPPED: forbidden network / credential / write path")


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return tmp_path / "p8_private_root"


@pytest.fixture
def traps(monkeypatch):
    """再構成の間だけ: credential なし ・transport ／ client ／ HTTPS ／ socket ／ 実行 ／ store の作成を罠にする。"""
    def arm() -> None:
        monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
        monkeypatch.setattr(lt.LocalHttpsTransport, "__init__", _trap)
        monkeypatch.setattr(lt.LocalHttpsTransport, "get", _trap)
        monkeypatch.setattr(JQuantsLiveClient, "__init__", _trap)
        monkeypatch.setattr(http.client.HTTPSConnection, "__init__", _trap)
        monkeypatch.setattr(http.client.HTTPConnection, "__init__", _trap)
        monkeypatch.setattr(socket, "create_connection", _trap)
        monkeypatch.setattr(socket.socket, "connect", _trap)
        monkeypatch.setattr(sl, "execute_screen", _trap)
        monkeypatch.setattr(sl, "_store_integrity", _trap)
        monkeypatch.setattr(sl, "_create_ledger", _trap)
        monkeypatch.setattr(sl.LedgerWriter, "append", _trap)
        for store in STORE_MODULES:
            monkeypatch.setattr(store, "initialize", classmethod(_trap))
            monkeypatch.setattr(store, "append", _trap)
    return arm


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


def complete_run(root: Path, *, budget_limit: int = 8):
    ids = identity(root, [(f"issuer-{c}", [c]) for c in CODES])
    universe, pol = authorities(root, CODES)
    out = run(root, universe, pol, transport([master(c) for c in CODES], {c: fins(c) for c in CODES}), ACQ[0],
              budget_limit=budget_limit)
    return out, ids, universe, pol


def fails(code: str, fn, *args, **kwargs) -> HandoffError:
    with pytest.raises(HandoffError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


# ================================================ A 完了した run の決定論の再構成（no-network ・no-credential ・no-write）


def test_a_a_a_complete_run_rebuilds_deterministically_without_network_credential_or_writes(root: Path, traps) -> None:
    out, ids, universe, pol = complete_run(root)
    assert out.result.execution_completeness is ExecutionCompleteness.COMPLETE
    before = snapshot(root)
    traps()
    first = reconstruct_completed_run(root, out.run_id)
    second = reconstruct_completed_run(str(root), out.run_id)
    assert first.screen_result_id == second.screen_result_id == out.result.screen_result_id
    assert first.result == out.result and second.result == out.result              # 凍結 B4A ／ B5B の結果そのもの
    meta = first.metadata
    assert (meta.run_id, meta.universe_id, meta.universe_version, meta.policy_id, meta.policy_version) == (
        out.run_id, universe.universe_id, 1, pol.policy_id, 1)
    assert (meta.member_count, meta.issuer_count, meta.execution_completeness) == (2, 2, "COMPLETE")
    assert meta.authority_mode == "RETROSPECTIVE_PROVIDER_AUTHORITY" and meta.ledger_event_count == 6
    assert meta.as_dict() == second.metadata.as_dict()
    assert not any(c in json.dumps(meta.as_dict()) for c in CODES)                # code を持たない
    assert snapshot(root) == before                                                  # P8 root の file ／ byte は不変


def test_a_a_b_bound_reconstruction_accepts_the_exact_binding(root: Path, traps) -> None:
    out, *_ = complete_run(root)
    traps()
    bound = reconstruct_bound(root, run_id=out.run_id, screen_result_id=out.result.screen_result_id)
    assert bound.screen_result_id == out.result.screen_result_id


# ================================================ B fail closed（作らない ・修復しない ・書かない）


@pytest.mark.parametrize("store", ["held", "identity", "policy", "universe"])
def test_b_a_a_missing_required_store_fails_closed_and_is_not_created(root: Path, traps, store: str) -> None:
    out, *_ = complete_run(root)
    cls = {"held": held_observation_store.HeldObservationStore, "identity": identity_store.IdentityStore,
           "policy": screener_policy_authority_store.PolicyAuthorityStore,
           "universe": screener_universe_store.UniverseAuthorityStore}[store]
    path = cls.open(root, read_only=True).path
    path.unlink()
    before = snapshot(root)
    traps()
    fails("P8_STORE_MISSING", reconstruct_completed_run, root, out.run_id)
    assert not path.exists() and snapshot(root) == before


def test_b_a_b_open_invocation_is_refused(root: Path, traps) -> None:
    out, *_ = complete_run(root)
    path = sl.ledger_path(root, out.run_id)
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:-1]))                                           # INVOCATION_ENDED の前（鎖は正しい）
    before = snapshot(root)
    traps()
    fails("P8_RUN_OPEN_INVOCATION", reconstruct_completed_run, root, out.run_id)
    assert snapshot(root) == before


def test_b_a_c_partial_runs_are_refused(root: Path, traps) -> None:
    out, *_ = complete_run(root, budget_limit=2)                                     # master ＋ 1 fins → 予算の延期
    assert out.result.execution_completeness is ExecutionCompleteness.PARTIAL
    traps()
    fails("P8_RUN_NOT_COMPLETE", reconstruct_completed_run, root, out.run_id)


def test_b_a_d_master_not_assessed_is_refused(root: Path, traps) -> None:
    identity(root, [(f"issuer-{c}", [c]) for c in CODES])
    universe, pol = authorities(root, CODES)
    failing = SyntheticTransport({master_key("2026-06-30"): TransportResponse(500, "{}")})   # master の失敗
    out = run(root, universe, pol, failing, ACQ[0])
    assert out.result.execution_completeness is ExecutionCompleteness.PARTIAL
    traps()
    fails("P8_RUN_NOT_COMPLETE", reconstruct_completed_run, root, out.run_id)


def test_b_a_e_wrong_or_malformed_run_id_is_refused(root: Path, traps) -> None:
    out, *_ = complete_run(root)
    traps()
    fails("P8_LEDGER_INVALID", reconstruct_completed_run, root, "p8run_" + "0" * 24)
    for bad in ("../" + out.run_id, out.run_id + ".jsonl", "", None, 7, out.run_id.upper()):
        fails("RUN_ID_INVALID", reconstruct_completed_run, root, bad)


def _rewrite_spec(path: Path, change) -> None:
    """台帳の spec を変え、digest ・鎖を正しく再計算する（台帳の検査は通るが、spec と run_id が一致しない）。"""
    events, prev = [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["event"] == "RUN_STARTED":
            change(event["payload"]["spec"])
        event["prev_digest"] = prev
        event.pop("digest")
        event["digest"] = sl._event_digest(event)
        prev = event["digest"]
        events.append(canonical_json(event))
    path.write_bytes("".join(e + "\n" for e in events).encode("utf-8"))           # 正準の byte（LF ・OS の変換なし）


@pytest.mark.parametrize("change", [
    lambda spec: spec.update(policy_version=spec["policy_version"] + 1),
    lambda spec: spec.update(evaluation_as_of="2026-06-30T23:00:00+09:00"),
    lambda spec: spec["bindings"].update(result_set_rules_version="p8_result_set:9.9.9"),
    lambda spec: spec.update(extra="x"),
    lambda spec: spec.pop("policy_id"),
])
def test_b_a_f_spec_mismatch_is_refused(root: Path, traps, change) -> None:
    out, *_ = complete_run(root)
    _rewrite_spec(sl.ledger_path(root, out.run_id), change)
    sl.load_ledger(sl.ledger_path(root, out.run_id), out.run_id)                    # 台帳の形 ・鎖は正しい
    traps()
    fails("P8_SPEC_MISMATCH", reconstruct_completed_run, root, out.run_id)


@pytest.mark.parametrize("corrupt", ["flip", "truncate", "append_garbage"])
def test_b_a_g_corrupted_ledger_is_refused_and_not_repaired(root: Path, traps, corrupt: str) -> None:
    out, *_ = complete_run(root)
    path = sl.ledger_path(root, out.run_id)
    data = path.read_bytes()
    path.write_bytes({"flip": data.replace(b'"seq":2', b'"seq":3', 1), "truncate": data[:-5],
                      "append_garbage": data + b"not json\n"}[corrupt])
    before = snapshot(root)
    traps()
    fails("P8_LEDGER_INVALID", reconstruct_completed_run, root, out.run_id)
    assert snapshot(root) == before


def test_b_a_h_root_must_be_explicit_absolute_and_existing(root: Path, traps, tmp_path: Path) -> None:
    out, *_ = complete_run(root)
    traps()
    fails("P8_ROOT_NOT_ABSOLUTE", reconstruct_completed_run, "relative/root", out.run_id)
    fails("P8_ROOT_REQUIRED", reconstruct_completed_run, "", out.run_id)
    fails("P8_ROOT_REQUIRED", reconstruct_completed_run, None, out.run_id)
    missing = tmp_path / "missing_root"
    fails("P8_ROOT_MISSING", reconstruct_completed_run, missing, out.run_id)
    assert not missing.exists()


# ================================================ C drift（P9-OBS-002: 結び付いた screen_result_id と違えば P8_RESULT_DRIFT）


def test_c_a_a_binding_helper_is_pure_and_fails_closed_on_mismatch(root: Path, traps) -> None:
    out, *_ = complete_run(root)
    traps()
    handoff = reconstruct_completed_run(root, out.run_id)
    srid = out.result.screen_result_id
    assert require_binding(handoff, run_id=out.run_id, screen_result_id=srid) is handoff
    fails("P8_RESULT_DRIFT", require_binding, handoff, run_id=out.run_id, screen_result_id="p8srs_" + "0" * 24)
    fails("P8_RESULT_DRIFT", require_binding, handoff, run_id="p8run_" + "0" * 24, screen_result_id=srid)
    fails("SCREEN_RESULT_ID_INVALID", require_binding, handoff, run_id=out.run_id, screen_result_id="x")
    fails("HANDOFF_INVALID", require_binding, handoff.result, run_id=out.run_id, screen_result_id=srid)


def test_c_a_b_a_later_same_day_run_in_the_same_root_is_detected_as_drift(root: Path, traps) -> None:
    out, ids, universe, pol = complete_run(root)
    srid = out.result.screen_result_id
    newer = fins(CODES[0]) + [fins_row(Code=CODES[0], DiscNo=f"20260512{CODES[0]}", DiscDate="2026-05-12",
                                       CurPerSt="2025-04-01", CurPerEn="2026-03-31", CurFYSt="2025-04-01",
                                       CurFYEn="2026-03-31", Sales="500000000000", OP="5000000000",
                                       NP="30000000000", TA="900000000000",
                                       DocType="FYFinancialStatements_Consolidated_JP")]
    universe2, pol2 = authorities(root, CODES, version=2)                           # 違う run（同じ root ・同じ D0）
    run(root, universe2, pol2, transport([master(c) for c in CODES], {CODES[0]: newer, CODES[1]: fins(CODES[1])}),
        ACQ[1])                                                                      # 取得 ≤ 前の run の評価の瞬間
    traps()
    fresh = reconstruct_completed_run(root, out.run_id)
    assert fresh.screen_result_id != srid                                           # 台帳は結果を封じない（P9-OBS-002）
    fails("P8_RESULT_DRIFT", reconstruct_bound, root, run_id=out.run_id, screen_result_id=srid)


# ================================================ D P9 の private root の規約（定義だけ ・filesystem に触れない）


def test_d_a_a_private_root_convention_is_pure_and_keeps_p8_and_p9_separate(tmp_path: Path) -> None:
    p9 = tmp_path / "p9_root"
    assert pr.phase9_authority_dir(p9) == p9 / "watchlist_thesis_intelligence" and not p9.exists()
    pr.require_separate_roots(tmp_path / "p8", tmp_path / "p9")
    for p8_root, p9_root in ((tmp_path / "a", tmp_path / "a"), (tmp_path / "a", tmp_path / "a" / "b"),
                             (tmp_path / "a" / "b", tmp_path / "a"), (tmp_path / "a", tmp_path / "x" / ".." / "a")):
        with pytest.raises(pr.PrivateRootError) as exc:
            pr.require_separate_roots(p8_root, p9_root)
        assert exc.value.code == "ROOTS_NOT_SEPARATE"
    for bad in ("relative", "", None):
        with pytest.raises(pr.PrivateRootError):
            pr.phase9_authority_dir(bad)
    assert not any(tmp_path.iterdir())                                               # 何も作らない
    assert ho.RUN_PER_ROOT_PROCEDURE == "ONE_P8_RUN_PER_PRIVATE_ROOT_PER_D0"
