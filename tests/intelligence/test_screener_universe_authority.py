"""P8-B5A — 明示の有限な Universe の意味と、人が審査した Universe の private authority store の test。

合成の code だけ（実の発行体 ・実の Universe ・private の pilot root は使わない）。pin するもの: 構文だけの member の検査（正規化 ・identity の
解決 ・適格の実行なし）・宣言の順の保持と非意味 ・重複 ・空 ・上限 ・内容 address の identity ・規則の版の束ね ・単一の authority の日 ・人の
審査（`human:` ・aware な reviewed_at ・既定なし）・追記専用 ・REUSED ・衝突 ・正確な解決だけ ・fail closed の journal ・network ・旧来 ・P5〜P7 ・
評価器への依存なし ・凍結の B1〜B4 の振る舞いの不変。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import jquants_live_model as lm
from src.intelligence.screener_intelligence import jquants_master_ingress as mi
from src.intelligence.screener_intelligence import screener_universe_model as um
from src.intelligence.screener_intelligence import screener_universe_store as us
from src.intelligence.screener_intelligence.screener_universe_model import (UniverseAuthorityRecord,
                                                                            UniverseMetadata, UniverseModelError,
                                                                            UniverseSpec)
from src.intelligence.screener_intelligence.screener_universe_store import (AppendStatus, IntegrityStatus,
                                                                            UniverseAppendRejected,
                                                                            UniverseAuthorityStore,
                                                                            UniverseConcurrentModification,
                                                                            UniverseStoreCorrupt,
                                                                            UniverseStoreMissing)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
MODEL = PACKAGE_DIR / "screener_universe_model.py"
STORE = PACKAGE_DIR / "screener_universe_store.py"
JOURNAL = Path("screener_intelligence") / "screener_universe_authority.jsonl"
JST = timezone(timedelta(hours=9))
REVIEWED = datetime(2026, 10, 6, 9, 30, tzinfo=JST)
#: 合成の code（実の上場物の主張ではない。構文の検査のためだけ）
CODES = ("90010", "90020", "9003A", "90040")
INTENT = "synthetic bounded scope for the universe model tests"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    private = tmp_path / "private_root"
    UniverseAuthorityStore.initialize(private)
    return private


def spec(*members, **overrides) -> UniverseSpec:
    base = dict(universe_key="synthetic-universe", version=1, intent=INTENT, members=tuple(members or CODES))
    return UniverseSpec(**{**base, **overrides})


def record(*members, author_ref: str = "human:synthetic-reviewer", reviewed_at: datetime = REVIEWED,
           **overrides) -> UniverseAuthorityRecord:
    return UniverseAuthorityRecord(universe=spec(*members, **overrides), author_ref=author_ref, reviewed_at=reviewed_at)


def rejects(code: str, fn, *args, **kwargs) -> None:
    with pytest.raises(UniverseModelError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, exc.value.code


def line_of(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


# ================================================ A UniverseSpec（構文 ・順 ・identity ・規則の束ね）


def test_a_a_valid_spec_binds_its_rules_and_has_a_deterministic_content_identity() -> None:
    s = spec()
    assert s.members == CODES and s.member_count == 4
    assert s.universe_id.startswith("p8uni_") and len(s.universe_id) == 30 and um.is_universe_id(s.universe_id)
    assert s.universe_id == spec().universe_id                                              # 決定論
    assert s.eligibility_rules_version == lm.LIVE_RULES_VERSION == "p8_jquants_live:0.1.0"
    assert s.authority_day_rule == "SINGLE_AUTHORITY_DAY_D0_NO_MULTI_DAY_CONTINUITY"
    assert s.member_scheme == "JQUANTS_CODE"
    assert s.member_order_rule == "DECLARED_ORDER_SERIALIZATION_ONLY_NON_SEMANTIC_NOT_A_RANKING"
    assert s.subject_rule == "ISSUER_RESOLVED_LATER_THROUGH_REVIEWED_IDENTITY_NOT_THE_PROVIDER_CODE"
    data = s.as_dict()
    assert set(data) == {"authority_day_rule", "eligibility_rules_version", "intent", "member_order_rule",
                         "member_scheme", "members", "membership_digest", "rules_version", "schema_version",
                         "subject_rule", "universe_id", "universe_key", "version"}
    assert data["members"] == list(CODES) and data["schema_version"] == "p8_screener_universe:0.1.0"
    assert UniverseSpec.from_dict(json.loads(json.dumps(data))) == s
    with pytest.raises(FrozenInstanceError):
        s.members = ("90010",)                                                              # type: ignore[misc]


def test_a_every_semantic_field_changes_the_identity_and_order_is_preserved_but_non_semantic() -> None:
    base = spec()
    for changed in (spec(universe_key="other-universe"), spec(version=2), spec(intent="another synthetic scope"),
                    spec("90010", "90020", "9003A"), spec("90010", "90020", "9003A", "90040", "90050")):
        assert changed.universe_id != base.universe_id
    reordered = spec("90040", "9003A", "90020", "90010")
    assert reordered.members == ("90040", "9003A", "90020", "90010")                       # 宣言の順は保つ（並べ替えない）
    assert reordered.universe_id != base.universe_id                                        # 内容（順を含む）の address
    assert reordered.membership_digest == base.membership_digest                           # 集合としては同じ
    assert spec("90010", "90050").membership_digest != base.membership_digest
    assert "rank" not in um.MEMBER_ORDER_RULE.lower().replace("not_a_ranking", "")
    assert not any(f.name in {"rank", "priority", "score", "weight", "conviction", "position"}
                   for f in fields(UniverseSpec))


@pytest.mark.parametrize("members, code", [
    ((), "EMPTY_UNIVERSE"), (("90010", "90010"), "DUPLICATE_MEMBER"),
    (("9001",), "INVALID_MEMBER_CODE"), (("900100",), "INVALID_MEMBER_CODE"), (("9001a",), "INVALID_MEMBER_CODE"),
    ((" 90010",), "INVALID_MEMBER_CODE"), (("90010 ",), "INVALID_MEMBER_CODE"), (("９００１０",), "INVALID_MEMBER_CODE"),
    ((90010,), "INVALID_MEMBER_CODE"), (("",), "INVALID_MEMBER_CODE"), (("9001-",), "INVALID_MEMBER_CODE")])
def test_a_members_are_validated_structurally_without_normalization(members, code) -> None:
    rejects(code, UniverseSpec, universe_key="k", version=1, intent=INTENT, members=members)


def test_a_structure_bounds_and_closed_rule_bindings_fail_closed() -> None:
    rejects("MEMBERS_NOT_TUPLE", spec, members=list(CODES))
    rejects("UNIVERSE_TOO_LARGE", spec, members=tuple(f"{n:05d}" for n in range(mi.MAX_MASTER_ROWS + 1)))
    assert um.MAX_UNIVERSE_MEMBERS == mi.MAX_MASTER_ROWS == 10000                         # 1 snapshot の上限から導く
    assert um.MAX_UNIVERSE_MEMBERS != lm.PILOT_MAX_REQUESTS                                # 予算 ≠ Universe の大きさ
    assert spec(members=tuple(f"{n:05d}" for n in range(1, 101))).member_count == 100
    rejects("ELIGIBILITY_RULES_VERSION_UNKNOWN", spec, eligibility_rules_version="p8_jquants_live:9.9.9")
    rejects("AUTHORITY_DAY_RULE_UNKNOWN", spec, authority_day_rule="MULTI_DAY")
    rejects("MEMBER_SCHEME_UNKNOWN", spec, member_scheme="LOCAL_CODE")
    rejects("MEMBER_ORDER_RULE_UNKNOWN", spec, member_order_rule="PRIORITY_ORDER")
    rejects("SUBJECT_RULE_UNKNOWN", spec, subject_rule="SECURITY")
    rejects("RULES_VERSION_MISMATCH", spec, rules_version="x:9")
    for key in ("", "Upper", "-lead", "a" * 65, "with space"):
        rejects("INVALID_UNIVERSE_KEY", spec, universe_key=key)
    for version in (0, -1, "1", 1.0, True):
        rejects("INVALID_VERSION", spec, version=version)
    for intent in ("", " padded", "x" * 501, "line\nbreak", "best large caps", "推奨の銘柄", "api_key=abc",
                   "buy list", "watchlist seed"):
        with pytest.raises(UniverseModelError):
            spec(intent=intent)


def test_a_the_forbidden_intent_vocabulary_matches_the_frozen_policy_vocabulary() -> None:
    from src.intelligence.screener_intelligence.screener_criteria_model import FORBIDDEN_INTENT_WORDS
    assert um.FORBIDDEN_UNIVERSE_INTENT_WORDS == FORBIDDEN_INTENT_WORDS


@pytest.mark.parametrize("mutate, code", [
    (lambda d: d.__setitem__("universe_id", "p8uni_" + "0" * 24), "UNIVERSE_ID_MISMATCH"),
    (lambda d: d.__setitem__("membership_digest", "0" * 64), "MEMBERSHIP_DIGEST_MISMATCH"),
    (lambda d: d.__setitem__("members", ["90020", "90010", "9003A", "90040"]), "UNIVERSE_ID_MISMATCH"),
    (lambda d: d.__setitem__("members", "90010"), "INVALID_RECORD"),
    (lambda d: d.__setitem__("extra", 1), "UNKNOWN_FIELD"),
    (lambda d: d.pop("subject_rule"), "MISSING_FIELD"),
    (lambda d: d.__setitem__("schema_version", "x:9"), "SCHEMA_MISMATCH"),
    (lambda d: d.__setitem__("members", ["90010", "90010"]), "DUPLICATE_MEMBER")])
def test_a_reconstruction_recomputes_identity_and_rejects_forged_specs(mutate, code) -> None:
    data = spec().as_dict()
    mutate(data)
    rejects(code, UniverseSpec.from_dict, data)


# ================================================ B 人の審査の authority record


def test_b_the_record_requires_explicit_human_provenance_and_an_aware_review_instant() -> None:
    rec = record()
    assert rec.record_id == rec.universe.universe_id and rec.universe_key == "synthetic-universe" and rec.version == 1
    assert rec.authority_class == "HUMAN_REVIEWED_SCREENING_UNIVERSE"
    assert UniverseAuthorityRecord.from_dict(json.loads(rec.canonical_line())) == rec
    assert rec.canonical_line() == json.dumps(rec.as_dict(), sort_keys=True, separators=(",", ":"),
                                              ensure_ascii=False) + "\n"
    rejects("NAIVE_OR_MISSING_DATETIME", record, reviewed_at=datetime(2026, 10, 6, 9, 30))
    rejects("NAIVE_OR_MISSING_DATETIME", record, reviewed_at="2026-10-06T09:30:00+09:00")
    for author in ("synthetic", "system:auto", "llm:model", "human:", "human: spaced", "", "human:api_key-1"):
        with pytest.raises(UniverseModelError):
            record(author_ref=author)
    with pytest.raises(TypeError):
        UniverseAuthorityRecord(universe=spec())                                            # 既定の著者 ・審査の瞬間は無い
    rejects("AUTHORITY_CLASS_MISMATCH", UniverseAuthorityRecord, universe=spec(), author_ref="human:r",
            reviewed_at=REVIEWED, authority_class="MACHINE_PROPOSED_UNIVERSE")
    rejects("INVALID_UNIVERSE", UniverseAuthorityRecord, universe=spec().as_dict(), author_ref="human:r",
            reviewed_at=REVIEWED)
    assert set(um.NOT_IMPLIED_BY_UNIVERSE) >= {"RECOMMENDED_SECURITIES", "RANKED_SECURITIES", "THEME_BENEFICIARIES",
                                               "WATCHLIST_MEMBERS", "PORTFOLIO_CANDIDATES", "LISTING_CONTINUITY",
                                               "ISSUER_IDENTITY", "PROVIDER_ELIGIBILITY"}


@pytest.mark.parametrize("mutate, code", [
    (lambda d: d.__setitem__("authority_class", "MACHINE_PROPOSED_UNIVERSE"), "AUTHORITY_CLASS_MISMATCH"),
    (lambda d: d.__setitem__("reviewed_at", "2026-10-06T09:30:00"), "NAIVE_OR_MISSING_DATETIME"),
    (lambda d: d.__setitem__("reviewed_at", 20261006), "INVALID_RECORD"),
    (lambda d: d.__setitem__("author_ref", "system:auto"), "INVALID_AUTHOR_REF"),
    (lambda d: d.__setitem__("record_kind", "OTHER"), "INVALID_RECORD"),
    (lambda d: d.__setitem__("schema_version", "x:9"), "SCHEMA_MISMATCH"),
    (lambda d: d.__setitem__("rules_version", "x:9"), "RULES_VERSION_MISMATCH"),
    (lambda d: d.__setitem__("approved_by", "auto"), "UNKNOWN_FIELD"),
    (lambda d: d.pop("reviewed_at"), "MISSING_FIELD")])
def test_b_non_human_or_malformed_authority_cannot_be_reconstructed(mutate, code) -> None:
    data = json.loads(record().canonical_line())
    mutate(data)
    rejects(code, UniverseAuthorityRecord.from_dict, data)


# ================================================ C private store（APPENDED ・REUSED ・衝突 ・正確な解決）


def test_c_append_replay_reopen_and_exact_resolution(root: Path) -> None:
    store = UniverseAuthorityStore.open(root)
    rec = record()
    first = store.append(rec)
    assert first.status is AppendStatus.APPENDED and first.universe_id == rec.record_id
    assert store.append(rec).status is AppendStatus.REUSED
    assert store.append(record()).status is AppendStatus.REUSED                             # 同じ内容の別の object
    assert (root / JOURNAL).read_bytes() == rec.canonical_line().encode()
    fresh = UniverseAuthorityStore.open(root, read_only=True)
    assert fresh.get_by_universe_id(rec.record_id) == rec
    assert fresh.get_by_key_version("synthetic-universe", 1) == rec
    assert fresh.get_by_key_version("synthetic-universe", 2) is None
    assert fresh.get_by_universe_id("p8uni_" + "0" * 24) is None
    assert fresh.get_by_key_version("other-universe", 1) is None
    with pytest.raises(UniverseAppendRejected) as exc:
        fresh.get_by_key_version("synthetic-universe", "1")                                 # type: ignore[arg-type]
    assert exc.value.code == "INVALID_VERSION"
    with pytest.raises(UniverseAppendRejected) as exc:
        fresh.append(rec)
    assert exc.value.code == "READ_ONLY"
    with pytest.raises(UniverseAppendRejected) as exc:
        UniverseAuthorityStore.open(root).append(rec.universe)
    assert exc.value.code == "INVALID_TYPE"
    meta = fresh.list_metadata()
    assert meta == (UniverseMetadata(universe_id=rec.record_id, universe_key="synthetic-universe", version=1,
                                     member_count=4, reviewed_at=REVIEWED),)
    assert not {"members", "intent", "author_ref"} & {f.name for f in fields(UniverseMetadata)}


def test_c_conflicting_authority_fails_closed(root: Path) -> None:
    store = UniverseAuthorityStore.open(root)
    store.append(record())
    for other, code in ((record(author_ref="human:another-reviewer"), "UNIVERSE_CONTENT_CONFLICT"),  # 同じ Universe ・別の審査
                        (record(reviewed_at=REVIEWED + timedelta(hours=1)), "UNIVERSE_CONTENT_CONFLICT"),
                        (record("90010", "90020"), "UNIVERSE_VERSION_CONFLICT"),             # 同じ鍵 ・版に別の集合
                        (record(intent="another synthetic scope"), "UNIVERSE_VERSION_CONFLICT")):
        with pytest.raises(UniverseAppendRejected) as exc:
            store.append(other)
        assert exc.value.code == code, (code, exc.value.code)
    assert len(store.records()) == 1
    assert store.append(record("90010", "90020", version=2)).status is AppendStatus.APPENDED  # 新しい版は別の審査
    assert store.append(record(universe_key="another-synthetic")).status is AppendStatus.APPENDED
    assert [(m.universe_key, m.version) for m in store.list_metadata()] == [
        ("another-synthetic", 1), ("synthetic-universe", 1), ("synthetic-universe", 2)]


@pytest.mark.parametrize("tail, code", [
    (b'{"record_kind": "SCREENER_UNIVERSE_AUTHORITY"', "TRUNCATED_FINAL_LINE"), (b"\n", "BLANK_LINE"),
    (b"not json\n", "INVALID_RECORD"), (b'{"record_kind": "OTHER"}\n', "INVALID_RECORD"),
    (b'{"record_kind": "SCREENER_UNIVERSE_AUTHORITY"}\n', "INVALID_RECORD"), (b"\xff\xfe\n", "INVALID_ENCODING")])
def test_c_malformed_journal_fails_closed_and_is_never_repaired(root: Path, tail: bytes, code: str) -> None:
    UniverseAuthorityStore.open(root).append(record())
    with (root / JOURNAL).open("ab") as handle:
        handle.write(tail)
    before = (root / JOURNAL).read_bytes()
    with pytest.raises(UniverseStoreCorrupt) as exc:
        UniverseAuthorityStore.open(root)
    assert exc.value.code == code and (root / JOURNAL).read_bytes() == before
    report = UniverseAuthorityStore.validate(root)
    assert report.status is IntegrityStatus.STORE_CORRUPTION and report.failure_code == code


def test_c_duplicate_forged_and_non_canonical_rows_fail_closed_with_line_numbers(root: Path) -> None:
    store = UniverseAuthorityStore.open(root)
    one = record()
    store.append(one)
    original = (root / JOURNAL).read_bytes()
    forged_id = json.loads(one.canonical_line())
    forged_id["universe"]["universe_id"] = "p8uni_" + "f" * 24
    forged_members = json.loads(one.canonical_line())
    forged_members["universe"]["members"] = ["90020", "90010", "9003A", "90040"]
    forged_class = json.loads(one.canonical_line())
    forged_class["authority_class"] = "MACHINE_PROPOSED_UNIVERSE"
    for tail, code in ((one.canonical_line().encode(), "PHYSICAL_DUPLICATE"),
                       (record("90010").canonical_line().encode(), "KEY_VERSION_DUPLICATE"),
                       (json.dumps(one.as_dict(), separators=(", ", ": ")).encode() + b"\n", "NON_CANONICAL_LINE"),
                       (line_of(forged_id), "UNIVERSE_ID_MISMATCH"), (line_of(forged_members), "UNIVERSE_ID_MISMATCH"),
                       (line_of(forged_class), "INVALID_RECORD")):
        (root / JOURNAL).write_bytes(original + tail)
        with pytest.raises(UniverseStoreCorrupt) as exc:
            UniverseAuthorityStore.open(root)
        assert exc.value.code == code and exc.value.line_number == 2, (code, exc.value.code)
        report = UniverseAuthorityStore.validate(root)
        assert report.status is IntegrityStatus.STORE_CORRUPTION and report.failure_code == code
    (root / JOURNAL).write_bytes(original)
    with (root / JOURNAL).open("ab") as handle:                                              # 外からの変更 → 書かない
        handle.write(record("90010", version=2).canonical_line().encode())
    with pytest.raises(UniverseConcurrentModification):
        store.append(record("90020", version=3))
    assert UniverseAuthorityStore.validate(root).status is IntegrityStatus.OK


def test_c_the_store_needs_an_explicit_private_root(tmp_path: Path) -> None:
    with pytest.raises(UniverseStoreMissing):
        UniverseAuthorityStore.open(tmp_path / "nowhere")
    for empty in ("", "  ", None):
        with pytest.raises(UniverseAppendRejected) as exc:
            UniverseAuthorityStore.open(empty)
        assert exc.value.code == "DATA_ROOT_REQUIRED"
    assert us.universe_path(tmp_path) == tmp_path / "screener_intelligence" / "screener_universe_authority.jsonl"
    assert UniverseAuthorityStore.validate(tmp_path / "nowhere").status is IntegrityStatus.STORE_MISSING
    assert not list(REPO_ROOT.glob("**/screener_universe_authority.jsonl"))


def test_c_there_is_no_latest_current_default_or_whole_market_resolver() -> None:
    public = {n for n in dir(UniverseAuthorityStore) if not n.startswith("_")}
    assert public == {"initialize", "open", "reload", "validate", "verify_unchanged", "append", "records",
                      "get_by_universe_id", "get_by_key_version", "list_metadata", "canonical_lines"}
    assert us.RESOLUTION_RULE == "EXACT_UNIVERSE_ID_OR_EXACT_KEY_VERSION_ONLY"
    model_public = {n for n in dir(um) if not n.startswith("_")}
    assert not any(word in n.lower() for n in model_public | public
                   for word in ("latest", "current", "default", "active", "all_market", "whole_market", "newest"))


# ================================================ D 境界（network ・旧来 ・P5〜P7 ・評価 ・identity の解決 ・適格の実行なし）


def test_d_the_universe_layer_is_pure_private_and_does_not_resolve_identity_or_execute_eligibility() -> None:
    for module, allowed in ((MODEL, {"__future__", "hashlib", "re", "dataclasses", "datetime", "typing", "..core.ids",
                                     "..core.time", ".identity_model", ".jquants_live_model",
                                     ".jquants_master_ingress"}),
                            (STORE, {"__future__", "json", "os", "dataclasses", "enum", "pathlib", "typing",
                                     ".screener_universe_model"})):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {"." * node.level + (node.module or "") for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert imported == allowed, (module.name, imported ^ allowed)
        names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        assert not any(n.startswith("_") for n in names - {"__future__"})
        assert not names & {"assess_master_row", "assess_master_payload", "id1_rows", "JQuantsLiveClient",
                            "Transport", "verify_identity_for_code", "resolve", "IdentityStore"}
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"))), "broad except"
            assert not (isinstance(node, ast.Attribute) and node.attr in {"now", "utcnow", "today"}), node.attr
        negations = {"NOT_IMPLIED_BY_UNIVERSE", "FORBIDDEN_UNIVERSE_INTENT_WORDS", "MEMBER_ORDER_RULE", "__all__"}
        lines = module.read_text(encoding="utf-8").splitlines()
        skipped = {n for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                   for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                   if isinstance(t, ast.Name) and t.id in negations
                   for n in range(node.lineno, node.end_lineno + 1)}                    # 否定の宣言だけを除く（構造で）
        assert skipped or module is STORE
        kept = "\n".join(line for number, line in enumerate(lines, 1) if number not in skipped)
        doc = ast.get_docstring(tree) or ""
        source = kept.replace(doc, "").lower()
        source = "\n".join(line.split("#")[0] for line in source.splitlines())
        for token in ("socket", "urllib", "requests", "http", "jquants_live_client", "transport", "screener_evaluator",
                      "policy_evaluation", "result_summary", "pilot2", "theme", "narrative", "calibration",
                      "score", "rank", "recommend", "watchlist", "portfolio", "latest", "llm", "prompt", "sqlite",
                      "pages", "morning"):
            assert token not in source, (module.name, token)
        for line in module.read_text(encoding="utf-8").splitlines():
            assert len(line) <= 120, line
    for path in sorted(PACKAGE_DIR.glob("*.py")):                                            # 凍結の層は Universe を知らない
        if path.stem not in ("screener_universe_model", "screener_universe_store"):
            assert "screener_universe" not in path.read_text(encoding="utf-8"), path.name
    for outside in ("src/intelligence/jquants_pilot2_local.py", "src/intelligence/jquants_local_transport.py",
                    "main.py"):
        assert "screener_universe" not in (REPO_ROOT / outside).read_text(encoding="utf-8"), outside
