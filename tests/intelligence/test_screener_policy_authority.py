"""P8-B3 — 人が審査した Screener の方針の private authority store の test。

合成の方針だけ（閾値は model の検証のための合成の値で、投資の方針ではない）。pin するもの: 凍結 B1 の constructor ・validator を
通る復元 ・policy_id ・criterion_id の再計算 ・追記専用 ・byte 一致の REUSED ・同じ (鍵, 版) の衝突 ・版の規則（高い版 ・歴史の
backfill ・欠番）・正確な解決だけ（latest ・current ・default なし）・fail closed の journal ・時計 ・既定の path なし ・評価 ・A3 ・
A3-RA ・JQ の import なし。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import screener_policy_authority_model as pm
from src.intelligence.screener_intelligence import screener_policy_authority_store as ps
from src.intelligence.screener_intelligence.screener_criteria_model import (CriteriaComposition, CriteriaPolicy,
                                                                            Criterion, CriterionOperator,
                                                                            ScreenerAuthorityMode,
                                                                            ScreenerModelError)
from src.intelligence.screener_intelligence.screener_policy_authority_model import (PolicyAuthorityModelError,
                                                                                    PolicyAuthorityRecord,
                                                                                    PolicyMetadata)
from src.intelligence.screener_intelligence.screener_policy_authority_store import (AppendStatus, IntegrityStatus,
                                                                                    PolicyAppendRejected,
                                                                                    PolicyAuthorityStore,
                                                                                    PolicyConcurrentModification,
                                                                                    PolicyStoreCorrupt,
                                                                                    PolicyStoreMissing)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_criteria_model import REVIEWED, criterion, policy

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
MODEL = PACKAGE_DIR / "screener_policy_authority_model.py"
STORE = PACKAGE_DIR / "screener_policy_authority_store.py"
JOURNAL = Path("screener_intelligence") / "screener_policy_authority.jsonl"
JST = timezone(timedelta(hours=9))
STRICT = ScreenerAuthorityMode.STRICT_PIT
#: 合成の閾値（投資の閾値ではない）
T1, T2, T3 = "0.0200", "0.0300", "0.0400"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    private = tmp_path / "private_root"
    PolicyAuthorityStore.initialize(private)
    return private


def record(*criteria, **overrides) -> PolicyAuthorityRecord:
    return PolicyAuthorityRecord(policy=policy(*(criteria or (criterion(threshold=T1),)), **overrides))


def journal(root: Path) -> Path:
    return root / JOURNAL


def rejects_model(code: str, fn, *args, **kwargs) -> None:
    with pytest.raises(PolicyAuthorityModelError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, exc.value.code


# ================================================ A record（凍結 B1 を包む ・identity は policy_id）


def test_a_the_record_binds_to_the_frozen_policy_id_and_round_trips_canonically() -> None:
    rec = record(criterion(threshold=T1), criterion(threshold=T2, operator=CriterionOperator.LT))
    assert rec.record_id == rec.policy.policy_id and rec.policy_key == "synthetic-model-test" and rec.version == 1
    assert rec.authority_class == "HUMAN_REVIEWED_SCREENING_POLICY"
    line = rec.canonical_line()
    assert line.endswith("\n") and line == json.dumps(rec.as_dict(), sort_keys=True, separators=(",", ":"),
                                                      ensure_ascii=False) + "\n"
    assert set(rec.as_dict()) == {"record_kind", "schema_version", "rules_version", "authority_class", "policy"}
    assert rec.as_dict()["policy"] == rec.policy.as_dict()                                   # 第二の identity は無い
    back = PolicyAuthorityRecord.from_dict(json.loads(line))
    assert back == rec and back.policy == rec.policy and back.canonical_line() == line
    assert ps.parse_policy_line(line) == rec
    with pytest.raises(FrozenInstanceError):
        rec.authority_class = "OTHER"                                                        # type: ignore[misc]
    rejects_model("AUTHORITY_CLASS_MISMATCH", PolicyAuthorityRecord, policy=rec.policy, authority_class="OTHER")
    rejects_model("SCHEMA_MISMATCH", PolicyAuthorityRecord, policy=rec.policy, schema_version="x:9")
    rejects_model("RULES_VERSION_MISMATCH", PolicyAuthorityRecord, policy=rec.policy, rules_version="x:9")
    rejects_model("INVALID_POLICY", PolicyAuthorityRecord, policy=rec.policy.as_dict())


def test_a_reconstruction_goes_through_frozen_b1_and_recomputes_every_id() -> None:
    rec = record(criterion(threshold=T1), criterion(threshold=T2, metric=criterion().metric))
    data = json.loads(rec.canonical_line())
    assert pm.policy_from_dict(data["policy"]) == rec.policy                                  # E: 復元 ＝ 元の凍結の方針
    forged = json.loads(rec.canonical_line())
    forged["policy"]["policy_id"] = "p8pol_" + "0" * 24                                      # F: policy_id の再計算
    rejects_model("POLICY_ID_MISMATCH", PolicyAuthorityRecord.from_dict, forged)
    forged = json.loads(rec.canonical_line())
    forged["policy"]["criteria"][0]["criterion_id"] = "p8crt_" + "0" * 24                   # G: criterion_id の再計算（B1）
    rejects_model("POLICY_INVALID", PolicyAuthorityRecord.from_dict, forged)
    forged = json.loads(rec.canonical_line())
    forged["policy"]["criterion_ids"] = list(reversed(forged["policy"]["criterion_ids"]))
    rejects_model("CRITERION_IDS_MISMATCH", PolicyAuthorityRecord.from_dict, forged)         # 順序も identity
    forged = json.loads(rec.canonical_line())
    forged["policy"]["criteria"][0]["threshold"] = T3                                        # 内容を変えると id が合わない
    rejects_model("POLICY_INVALID", PolicyAuthorityRecord.from_dict, forged)


@pytest.mark.parametrize("mutate, code", [
    (lambda d: d.__setitem__("record_kind", "OTHER"), "INVALID_RECORD"),
    (lambda d: d.__setitem__("schema_version", "x:9"), "SCHEMA_MISMATCH"),
    (lambda d: d.__setitem__("rules_version", "x:9"), "RULES_VERSION_MISMATCH"),
    (lambda d: d.__setitem__("authority_class", "VALIDATED_ALPHA"), "AUTHORITY_CLASS_MISMATCH"),
    (lambda d: d.__setitem__("extra", 1), "UNKNOWN_FIELD"),
    (lambda d: d.pop("policy"), "MISSING_FIELD"),
    (lambda d: d["policy"].__setitem__("schema_version", "x:9"), "SCHEMA_MISMATCH"),
    (lambda d: d["policy"].__setitem__("score", 1), "UNKNOWN_FIELD"),
    (lambda d: d["policy"].pop("reviewed_at"), "MISSING_FIELD"),
    (lambda d: d["policy"].__setitem__("reviewed_at", "2026-10-06T09:30:00"), "INVALID_RECORD"),       # Q: naive
    (lambda d: d["policy"].__setitem__("reviewed_at", 20261006), "INVALID_RECORD"),
    (lambda d: d["policy"].__setitem__("version", "1"), "POLICY_INVALID"),                   # P: B1 が拒む
    (lambda d: d["policy"].__setitem__("intent", "buy the dip, guaranteed alpha"), "POLICY_INVALID"),
    (lambda d: d["policy"].__setitem__("composition", "ANY_OF"), "INVALID_RECORD"),
    (lambda d: d["policy"].__setitem__("criteria", []), "INVALID_RECORD"),
    (lambda d: d["policy"]["criteria"][0].__setitem__("threshold", "0.1"), "POLICY_INVALID"),  # O: B1 が id を拒む
    (lambda d: d["policy"]["criteria"][0].__setitem__("threshold", 0.1), "POLICY_INVALID"),
    (lambda d: d["policy"]["criteria"][0].__setitem__("operator", "APPROX"), "POLICY_INVALID"),
    (lambda d: d["policy"]["criteria"][0].pop("criterion_id"), "MISSING_FIELD")])
def test_a_malformed_or_forged_rows_fail_closed_through_frozen_b1(mutate, code) -> None:
    data = json.loads(record().canonical_line())
    mutate(data)
    rejects_model(code, PolicyAuthorityRecord.from_dict, data)


def test_a_naive_reviewed_at_and_implicit_clock_are_impossible() -> None:
    with pytest.raises(ScreenerModelError) as exc:
        policy(reviewed_at=datetime(2026, 10, 6, 9, 30))
    assert exc.value.code == "NAIVE_OR_MISSING_DATETIME"
    with pytest.raises(TypeError):
        CriteriaPolicy(policy_key="k", version=1, author_ref="human:r", intent="synthetic", criteria=(criterion(),),
                       authority_mode=criterion().authority_mode)                           # reviewed_at は必須（既定なし）
    for module in (MODEL, STORE):
        source = executable_source(module)
        for token in ("now(", "today(", "utcnow", "time.", "datetime.now", "default_factory"):
            assert token not in source, (module.name, token)


def test_a_the_authority_means_only_human_review() -> None:
    assert pm.HUMAN_REVIEWED_SCREENING_POLICY == "HUMAN_REVIEWED_SCREENING_POLICY" == ps.AUTHORITY_CLASS
    assert set(pm.NOT_IMPLIED_BY_AUTHORITY) == {"PRODUCTION_INVESTMENT_RECOMMENDATION", "VALIDATED_ALPHA",
                                                "PROVEN_PREDICTIVE_RULE", "PRODUCTION_COMPASS_DNA", "THEME_AUTHORITY",
                                                "WATCHLIST_AUTHORITY", "THESIS_AUTHORITY"}
    assert pm.VERSION_RULE == "EXPLICIT_HUMAN_LABEL_UNIQUE_PER_KEY_NO_SEQUENCE_NO_CURRENT"
    assert ps.RESOLUTION_RULE == "EXACT_POLICY_ID_OR_EXACT_KEY_VERSION_ONLY"
    meta = PolicyMetadata.of(record(criterion(threshold=T1), criterion(threshold=T2)))
    assert meta.criterion_count == 2 and meta.version == 1 and meta.reviewed_at == REVIEWED
    assert not any(word in set(PolicyMetadata.__dataclass_fields__) for word in ("threshold", "current", "active",
                                                                                   "default", "score", "rank"))


# ================================================================ B append ・REUSED ・再開


def test_b_append_replay_reopen_and_exact_reads(root: Path) -> None:
    store = PolicyAuthorityStore.open(root)
    rec = record(criterion(threshold=T1), criterion(threshold=T2))
    first = store.append(rec)
    assert first.status is AppendStatus.APPENDED and first.policy_id == rec.record_id              # A
    assert store.append(rec).status is AppendStatus.REUSED                                         # B
    assert store.append(PolicyAuthorityRecord(policy=rec.policy)).status is AppendStatus.REUSED
    assert journal(root).read_bytes() == rec.canonical_line().encode()
    fresh = PolicyAuthorityStore.open(root, read_only=True)                                        # 再開
    assert fresh.get_by_policy_id(rec.record_id) == rec                                            # C
    assert fresh.get_by_policy_id(rec.record_id).policy == rec.policy                              # E
    assert fresh.get_by_key_version(rec.policy_key, 1) == rec                                      # D
    assert fresh.get_by_key_version(rec.policy_key, 2) is None and fresh.get_by_policy_id("p8pol_" + "0" * 24) is None
    assert fresh.records() == (rec,) and fresh.canonical_lines() == (rec.canonical_line(),)
    with pytest.raises(PolicyAppendRejected) as exc:
        fresh.append(rec)
    assert exc.value.code == "READ_ONLY"
    writer = PolicyAuthorityStore.open(root)
    assert writer.append(rec).status is AppendStatus.REUSED
    assert journal(root).read_bytes() == rec.canonical_line().encode()
    with pytest.raises(PolicyAppendRejected) as exc:
        writer.append(rec.policy)
    assert exc.value.code == "INVALID_TYPE"
    with pytest.raises(PolicyAppendRejected) as exc:
        writer.get_by_key_version(rec.policy_key, "1")                                          # type: ignore[arg-type]
    assert exc.value.code == "INVALID_VERSION"


def test_b_same_key_version_with_different_content_fails_closed(root: Path) -> None:
    store = PolicyAuthorityStore.open(root)
    store.append(record(criterion(threshold=T1)))
    for other in (record(criterion(threshold=T2)),                                                 # 閾値が違う
                  record(criterion(threshold=T1), author_ref="human:reviewer-2"),                  # 著者が違う
                  record(criterion(threshold=T1), reviewed_at=REVIEWED + timedelta(hours=1)),      # 審査の瞬間が違う
                  record(criterion(threshold=T1), intent="another synthetic intent")):
        assert other.record_id != store.records()[0].record_id
        with pytest.raises(PolicyAppendRejected) as exc:
            store.append(other)
        assert exc.value.code == "POLICY_VERSION_CONFLICT"                                          # H
    assert len(store.records()) == 1 and journal(root).read_bytes() == store.records()[0].canonical_line().encode()


def test_b_same_policy_id_with_different_stored_content_fails_closed(root: Path, monkeypatch) -> None:
    store = PolicyAuthorityStore.open(root)
    rec = record()
    store.append(rec)
    other = replace(rec, policy=record(criterion(threshold=T2)).policy)
    claimed = rec.record_id
    monkeypatch.setattr(type(other), "record_id", property(lambda self: claimed))              # 同じ id を主張する行
    with pytest.raises(PolicyAppendRejected) as exc:
        store.append(other)
    assert exc.value.code == "POLICY_CONTENT_CONFLICT"                                              # I


# ================================================ C 版の規則（明示の label ・順序の保証なし）


def test_c_higher_version_lower_backfill_and_gaps_are_separately_reviewed_policies(root: Path) -> None:
    store = PolicyAuthorityStore.open(root)
    v3 = record(criterion(threshold=T3), version=3, reviewed_at=REVIEWED + timedelta(days=2))
    v1 = record(criterion(threshold=T1), version=1)
    v2 = record(criterion(threshold=T2), version=2, reviewed_at=REVIEWED + timedelta(days=9))     # 審査は v3 より後
    assert store.append(v3).status is AppendStatus.APPENDED                                         # L: 欠番（v1 なし）
    assert store.append(v1).status is AppendStatus.APPENDED                                         # K: 歴史の backfill
    assert store.append(v2).status is AppendStatus.APPENDED                                         # J: 版は label
    assert store.append(v1).status is AppendStatus.REUSED
    fresh = PolicyAuthorityStore.open(root, read_only=True)
    assert {fresh.get_by_key_version("synthetic-model-test", n) for n in (1, 2, 3)} == {v1, v2, v3}
    assert fresh.get_by_key_version("synthetic-model-test", 4) is None
    assert [r.version for r in fresh.records()] == [3, 1, 2]                                        # append の順 ≠ 版の順
    assert [m.version for m in fresh.list_metadata()] == [1, 2, 3]                                  # 鍵 ・版の辞書順（現在ではない）
    assert fresh.list_metadata()[1].reviewed_at > fresh.list_metadata()[2].reviewed_at             # 版の順 ≠ 審査の順
    with pytest.raises(PolicyAppendRejected) as exc:
        fresh_writer = PolicyAuthorityStore.open(root)
        fresh_writer.append(record(criterion(threshold=T3), version=2))                            # 占有された版
    assert exc.value.code == "POLICY_VERSION_CONFLICT"
    other_key = record(criterion(threshold=T1), policy_key="another-synthetic-key")
    assert PolicyAuthorityStore.open(root).append(other_key).status is AppendStatus.APPENDED       # 別の鍵は別の名前空間
    assert [(m.policy_key, m.version) for m in PolicyAuthorityStore.open(root).list_metadata()] == [
        ("another-synthetic-key", 1), ("synthetic-model-test", 1), ("synthetic-model-test", 2),
        ("synthetic-model-test", 3)]


def test_c_there_is_no_latest_current_default_or_search_resolver() -> None:
    public = {name for name in dir(PolicyAuthorityStore) if not name.startswith("_")}
    assert public == {"initialize", "open", "reload", "validate", "verify_unchanged", "append", "records",
                      "get_by_policy_id", "get_by_key_version", "list_metadata", "canonical_lines"}
    source = executable_source(STORE) + executable_source(MODEL)
    for token in ("latest", "current_policy", "Current", "active_policy", "default_policy", "highest", "newest", "max(",
                  "min(", "sorted(v", "threshold_search", "search(", "find_by_threshold", "recommend", "rank", "score",
                  "best"):
        assert token not in source, token
    assert "sorted(" in executable_source(STORE)                                                  # metadata の辞書順だけ
    assert executable_source(STORE).count("sorted(") == 1


# ================================================================ D fail closed の journal


@pytest.mark.parametrize("tail, code", [
    (b'{"record_kind": "SCREENER_POLICY_AUTHORITY"', "TRUNCATED_FINAL_LINE"), (b"\n", "BLANK_LINE"),
    (b"not json\n", "INVALID_RECORD"), (b'{"record_kind": "OTHER"}\n', "INVALID_RECORD"),
    (b'{"record_kind": "SCREENER_POLICY_AUTHORITY"}\n', "INVALID_RECORD"),
    (b"\xff\xfe\n", "INVALID_ENCODING")])
def test_d_malformed_journal_fails_closed_and_is_never_repaired(root: Path, tail: bytes, code: str) -> None:
    store = PolicyAuthorityStore.open(root)
    store.append(record())
    with journal(root).open("ab") as handle:
        handle.write(tail)
    before = journal(root).read_bytes()
    with pytest.raises(PolicyStoreCorrupt) as exc:
        PolicyAuthorityStore.open(root)                                                            # M
    assert exc.value.code == code and journal(root).read_bytes() == before
    report = PolicyAuthorityStore.validate(root)
    assert report.status is IntegrityStatus.STORE_CORRUPTION and report.failure_code == code
    assert report.record_count == 0 and journal(root).read_bytes() == before                      # 修復しない


def test_d_duplicate_conflicting_forged_and_non_canonical_rows_fail_closed(root: Path) -> None:
    store = PolicyAuthorityStore.open(root)
    one = record(criterion(threshold=T1))
    store.append(one)
    original = journal(root).read_bytes()
    forged_id = json.loads(one.canonical_line())
    forged_id["policy"]["policy_id"] = "p8pol_" + "f" * 24
    forged_criterion = json.loads(one.canonical_line())
    forged_criterion["policy"]["criteria"][0]["criterion_id"] = "p8crt_" + "f" * 24
    not_canonical = json.dumps(one.as_dict(), separators=(", ", ": ")).encode() + b"\n"
    for tail, code in ((one.canonical_line().encode(), "PHYSICAL_DUPLICATE"),                     # N: 同じ行
                       (record(criterion(threshold=T2)).canonical_line().encode(), "KEY_VERSION_DUPLICATE"),
                       (not_canonical, "NON_CANONICAL_LINE"),
                       ((json.dumps(forged_id, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                        .encode(), "POLICY_ID_MISMATCH"),
                       ((json.dumps(forged_criterion, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                         + "\n").encode(), "POLICY_INVALID")):
        with journal(root).open("ab") as handle:
            handle.write(tail)
        with pytest.raises(PolicyStoreCorrupt) as exc:
            PolicyAuthorityStore.open(root)
        assert exc.value.code == code, (code, exc.value.code)
        assert exc.value.line_number == 2
        report = PolicyAuthorityStore.validate(root)
        assert report.status is IntegrityStatus.STORE_CORRUPTION and report.failure_code == code
        assert report.line_number == 2
        journal(root).write_bytes(original)
    with journal(root).open("ab") as handle:                                                       # 外からの変更 → 書かない
        handle.write(record(criterion(threshold=T2), version=2).canonical_line().encode())
    with pytest.raises(PolicyConcurrentModification):
        store.append(record(criterion(threshold=T3), version=3))
    assert PolicyAuthorityStore.validate(root).status is IntegrityStatus.OK


def test_d_integrity_validation_reports_without_repairing(root: Path) -> None:
    assert PolicyAuthorityStore.validate(root) == ps.IntegrityReport(IntegrityStatus.OK, 0)
    store = PolicyAuthorityStore.open(root)
    store.append(record(criterion(threshold=T1)))
    store.append(record(criterion(threshold=T2), version=2))
    assert PolicyAuthorityStore.validate(root) == ps.IntegrityReport(IntegrityStatus.OK, 2)
    missing = PolicyAuthorityStore.validate(root / "nowhere")
    assert missing.status is IntegrityStatus.STORE_MISSING and missing.failure_code == "STORE_MISSING"
    assert set(ps.CORRUPTION_REASONS) >= {"STORE_MISSING", "INVALID_ENCODING", "TRUNCATED_FINAL_LINE", "BLANK_LINE",
                                          "INVALID_RECORD", "NON_CANONICAL_LINE", "POLICY_INVALID",
                                          "POLICY_ID_MISMATCH", "CRITERION_IDS_MISMATCH", "PHYSICAL_DUPLICATE",
                                          "KEY_VERSION_DUPLICATE"}
    assert {s.value for s in IntegrityStatus} == {"OK", "STORE_MISSING", "STORE_CORRUPTION"}


# ================================================================ E private の root ・既定の path なし


def test_e_the_store_needs_an_explicit_private_root_and_never_touches_the_repository(tmp_path: Path) -> None:
    with pytest.raises(PolicyStoreMissing):
        PolicyAuthorityStore.open(tmp_path / "nowhere")
    for empty in ("", "  ", None):
        with pytest.raises(PolicyAppendRejected) as exc:
            PolicyAuthorityStore.open(empty)
        assert exc.value.code == "DATA_ROOT_REQUIRED"
    assert ps.policy_path(tmp_path) == tmp_path / "screener_intelligence" / "screener_policy_authority.jsonl"
    source = executable_source(STORE) + executable_source(MODEL)
    for token in ("config.yaml", "knowledge/", "data/", "cwd(", "Path.home", "expanduser", "getcwd", "__file__",
                  "resolve(", "DEFAULT_ROOT", "DEFAULT_PATH"):
        assert token not in source, token
    assert not list(REPO_ROOT.glob("**/screener_policy_authority.jsonl"))                        # S: repo に journal は無い
    tree = ast.parse(STORE.read_text(encoding="utf-8"))
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not any(c.startswith("/") or c.startswith("~") or "\\" in c for c in constants)


# ================================================ F 表面の guard（評価 ・A3 ・A3-RA ・JQ ・P5〜P7 なし）


def test_f_the_authority_layer_imports_nothing_from_evaluation_metrics_or_providers() -> None:
    for module, allowed in ((MODEL, {"__future__", "dataclasses", "datetime", "typing", "..core.time",
                                     ".identity_model", ".screener_criteria_model"}),
                            (STORE, {"__future__", "json", "os", "dataclasses", "enum", "pathlib", "typing",
                                     ".screener_policy_authority_model"})):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {"." * node.level + (node.module or "") for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert imported == allowed, (module.name, imported ^ allowed)
        source = executable_source(module)
        for token in ("screener_evaluator", "fundamental_metrics", "retrospective_metric", "provider_holdings",
                      "observation_", "jquants", "theme", "Theme", "narrative", "p5", "P5", "feedback", "backtest",
                      "optimi", "llm", "prompt", "://", "sqlite", "pickle", "shutil", "unlink", "truncate", "rename",
                      "compact", "migrat", "repair", "universe", "security_projection", "exposure"):
            assert token not in source, (module.name, token)
        for line in module.read_text(encoding="utf-8").splitlines():
            assert len(line) <= 120, line
    store_source = executable_source(STORE)
    assert store_source.count("open('ab')") == 2 and "fsync" in store_source and "'wb'" not in store_source
    assert "write_bytes" not in store_source and "write_text" not in store_source
    assert pm.__all__ == sorted(pm.__all__, key=lambda n: (n.lower(), n)) or set(pm.__all__) >= {
        "PolicyAuthorityRecord", "PolicyMetadata", "policy_from_dict", "is_policy_authority_record"}
    assert set(ps.__all__) >= {"PolicyAuthorityStore", "AppendStatus", "AppendResult", "IntegrityReport",
                               "IntegrityStatus", "parse_policy_line", "policy_path"}


def test_f_documents_and_changelog_carry_no_private_threshold_values() -> None:
    doc = (REPO_ROOT / "docs/databank/PHASE8_B3_PRIVATE_POLICY_AUTHORITY_STORE.md").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = changelog[changelog.index("## v5.87"):changelog.index("## v5.86")]
    assert "合成" in doc and "HUMAN_REVIEWED_SCREENING_POLICY" in doc
    for text, name in ((doc, "doc"), (section, "CHANGELOG v5.87")):
        assert '"threshold":"' not in text and "threshold=" not in text and "reviewer-1" not in text, name
        assert "p8pol_" not in text.replace("p8pol_…", "") and T1 not in text and T2 not in text, name
        assert "get_latest(" not in text and "current_policy(" not in text, name
