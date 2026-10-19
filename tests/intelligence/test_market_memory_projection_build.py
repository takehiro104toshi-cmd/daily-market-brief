"""P13-A4b — Obsidian 投影の export の orchestration の試験（合成の一時 root ・合成の vault ・合成の A3 の generation だけ）。

A3 の公開の読みの handoff ・A4a1 の後継の契約の消費（public な版 ・private な binding ・NO_CHANGE の binding の記録 ・CONTINUE_STAGING ・
明示の保存）・最初 ／ 2 つ目の公開と前の版の保持 ・決定論の再生 ・全ての書き込みの操作の前 ／ 後 ／ 途中で切れた失敗と回復（回復の中の 2 つ目の
失敗を含む）・作業中の残り ・lock の所有の喪失 ・容量の境界 ・改竄 ・2 つの private な root ・人の file の隔離 ・private な FAILED の証拠を
固定する。0.1.0 の A4a の状態機械ではなく後継の契約を試す。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path

import pytest

from src.intelligence.market_memory import memory_projection as frozen_a4a
from src.intelligence.market_memory import memory_store as ms
from src.intelligence.market_memory import projection_build as pb
from src.intelligence.market_memory import projection_contract as pc
from src.intelligence.market_memory import projection_store as ps
from src.intelligence.market_memory.canonical import domain_digest
from tests.intelligence.test_market_memory_projection_contract import GEN_A, GEN_A_TWIN, GEN_B, GEN_C, target_of, variant
from tests.intelligence.test_market_memory_projection_store import (HUMAN_FILES, MUTATIONS, FakeShutil, _no_network_credentials_or_processes,
                                                                    a3_publish, inject, make_private, make_vault, tree)

GEN_ONE, GEN_ONE_B = variant(days=(10,)), variant(days=(11,))                                     # 1 つの cutoff（note 2 つ）の小さな版
UNIT = ps.SIZE_UNIT
MIB = 1024 * 1024
assert _no_network_credentials_or_processes                                                       # autouse の fixture を取り込む


class Env:
    """1 つの合成の環境（composition root ・A3 の公開 ・人が用意した vault）。"""

    def __init__(self, base: Path, gen=GEN_A, *, vault_name: str = "vault", private_name: str = "private", vault: Path = None) -> None:
        base.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.private = make_private(base, private_name)
        self.vault = vault if vault is not None else make_vault(base, vault_name)
        self.gen = gen
        self.outcome = a3_publish(self.private, gen)
        self.preserved = []                                                                       # 人の手順の模擬が移した残りの台帳

    @property
    def generated(self) -> Path:
        return self.vault / ps.GENERATED_DIRECTORY

    @property
    def projection(self) -> Path:
        return self.private / ps.PROJECTION_CHILD

    def use(self, gen) -> "Env":
        self.gen, self.outcome = gen, a3_publish(self.private, gen)
        return self

    def publish(self, *, limits=None, protected=None, generation_digest=None, manifest_digest=None) -> pb.ExportResult:
        return pb.publish_projection(str(self.private), str(self.vault), protected_roots={} if protected is None else protected,
                                     generation_digest=generation_digest or self.outcome.generation_digest,
                                     manifest_digest=manifest_digest or self.outcome.manifest_digest, limits=limits)

    def preserve(self, action) -> pb.ExportResult:
        return pb.preserve_projection_staging(str(self.private), str(self.vault), protected_roots={}, action=action,
                                              generation_digest=self.outcome.generation_digest, manifest_digest=self.outcome.manifest_digest)

    def versions(self) -> dict:
        return {p.name: {n.name: n.read_bytes() for n in sorted(p.iterdir())} for p in sorted(self.generated.glob("p13pvn_*"))}

    def evidence(self) -> dict:
        return {p.relative_to(self.projection).as_posix(): p.read_bytes() for p in sorted(self.projection.rglob("*"))
                if p.is_file() and ps.LOCKS_DIRECTORY not in p.parts and ps.STAGING_DIRECTORY not in p.parts}


def published_label(gen) -> str:
    return target_of(gen).version_label


def private_digests(gen) -> list:
    verified = pc.PrivateSourceInput(verified=_verified(gen), generation_digest=gen.generation_digest,
                                     manifest_digest=gen.manifest().manifest_digest).verified
    return [gen.generation_digest, gen.plan_digest, verified.manifest_digest, *(s.sample_digest for s in gen.samples),
            *(c.change_digest for c in gen.changes)]


def _verified(gen):
    from src.intelligence.market_memory import memory_generation as mg
    return mg.verify_generation_records({**gen.records(), mg.MANIFEST_RECORD_NAME: gen.manifest().to_bytes()},
                                        expected_generation_digest=gen.generation_digest)


POINTER_TEMP = re.compile(r"^" + re.escape(ps.POINTER_NOTE_NAME[:-len(".md")]) + r"\.[0-9a-f]{64}\.tmp$")
FAILURE_TEMP = re.compile(r"^failure\.[0-9a-f]{64}\.tmp$")
COMPLETION_TEMP = re.compile(r"^completion\.[0-9a-f]{64}\.tmp$")
EVIDENCE_PARTIAL = re.compile(r"^(?:bundle|binding)\.[0-9a-f]{64}\.partial$")


def deterministic_staging(reference: Env, export_digest: str) -> dict:
    """同じ履歴を故障なしで公開した参照の確定した byte から、runtime が各作業中の名前に書く決定論の byte を引く表（作業中の名前と確定の
    名前の対応は store と同じ）。人の手順の模擬が「決定論の byte と違う残り」を一意に特定するためだけに使う。"""
    table = {}
    for area, kind in ((ps.BUNDLES_DIRECTORY, "bundle"), (ps.BINDINGS_DIRECTORY, "binding")):
        for bundle in sorted((reference.projection / area).iterdir()):
            for record in sorted(bundle.iterdir()):
                table[("private", f"{kind}.{bundle.name}{ps.PARTIAL_SUFFIX}/{record.name}")] = record.read_bytes()
    for record in sorted((reference.projection / ps.COMPLETIONS_DIRECTORY).iterdir()):
        table[("private", f"completion.{record.name[:-len(ps.RECORD_SUFFIX)]}{ps.TEMP_SUFFIX}")] = record.read_bytes()
    pointer_temp = f"{ps.POINTER_NOTE_NAME[:-len('.md')]}.{export_digest}{ps.TEMP_SUFFIX}"
    table[("vault", pointer_temp)] = (reference.generated / ps.POINTER_NOTE_NAME).read_bytes()
    return table


def _plain_file(location: Path) -> bool:
    return stat.S_ISREG(location.lstat().st_mode)                                                # symlink ・directory は特定しない


def _differs(location: Path, expected) -> bool:
    return expected is not None and _plain_file(location) and location.read_bytes() != expected      # 期待が分からなければ特定しない


def _private_residue(env: Env, deterministic) -> list:
    found = []
    for entry in sorted((env.projection / ps.STAGING_DIRECTORY).iterdir()):
        if FAILURE_TEMP.match(entry.name) and _plain_file(entry):
            found.append(entry)                                                                  # R2: 残った FAILED の一時 file は決して採られない
        elif deterministic is None:
            continue
        elif EVIDENCE_PARTIAL.match(entry.name) and stat.S_ISDIR(entry.lstat().st_mode):
            found += [record for record in sorted(entry.iterdir())                               # 切れた record だけ（byte 一致の record は残す）
                      if _differs(record, deterministic.get(("private", f"{entry.name}/{record.name}")))]
        elif COMPLETION_TEMP.match(entry.name) and _differs(entry, deterministic.get(("private", entry.name))):
            found.append(entry)
    return found


def _pointer_residue(env: Env, deterministic) -> list:
    staging = env.generated / ps.VAULT_STAGING_DIRECTORY
    if deterministic is None or not staging.is_dir():
        return []
    return [entry for entry in sorted(staging.iterdir())                                         # staging の label の folder には触れない
            if POINTER_TEMP.match(entry.name) and _differs(entry, deterministic.get(("vault", entry.name)))]


def _surroundings(env: Env) -> dict:
    """2 つの root の全ての entry の identity と byte（人の手順の模擬の前後で、移した残り以外が何も替わらないことを確かめる）。"""
    seen = {}
    for side, root in (("private", env.private), ("vault", env.vault)):
        for location in sorted(root.rglob("*")):
            st = location.lstat()
            seen[(side, location.relative_to(root).as_posix())] = (
                stat.S_IFMT(st.st_mode), st.st_dev, st.st_ino, location.read_bytes() if stat.S_ISREG(st.st_mode) else None)
    return seen


def check_preserved(env: Env) -> None:
    """移した全ての残りが、同じ identity ・byte ・digest のまま合成の fixture が所有する保存先に在る（消えない ・替わらない ・増えない）。"""
    quarantine = env.base / "quarantine"
    present = sorted(p.name for p in quarantine.iterdir()) if quarantine.exists() else []
    assert present == sorted(record["destination"].name for record in env.preserved)
    for record in env.preserved:
        st = record["destination"].lstat()
        data = record["destination"].read_bytes()
        assert stat.S_ISREG(st.st_mode) and (st.st_dev, st.st_ino) == record["identity"], record["source"]
        assert data == record["data"] and hashlib.sha256(data).hexdigest() == record["sha256"], record["source"]


def human_procedure(env: Env, code: str, deterministic=None) -> list:
    """記録した人の手順の模擬（設計だけ ・software には無い）。HOLD の code が名指す残りのうち、一意に特定でき安全を確かめたものだけを
    root の外の合成の保存先へ移す: code が名指す 1 つの残った lock ・残った FAILED の一時 file（runtime は決して採らない）・決定論の byte が
    分かっていてそれと違う作業中の file（private な bundle の record ・完了の一時 file ・vault の pointer の一時 file）。byte 一致の
    （続きに使える）record ・期待が分からない残り ・版 ・確定した証拠 ・pointer ・staging の label の folder には触れず、何も消さない。
    移す前の identity ・byte ・digest を台帳に記録し、移した後に保存先で同じであること ・移した物以外が何も替わらないことを確かめる。
    何も特定できなければ何も移さず空を返す（HOLD のまま）。"""
    candidates = []
    if code == ps.PRIVATE_LOCK_PRESENT:
        candidates.append(env.projection / ps.LOCKS_DIRECTORY / ps.EXPORT_LOCK_NAME)
    elif code == ps.VAULT_LOCK_PRESENT:
        candidates.append(env.generated / ps.VAULT_LOCK_NAME)
    if code in (ps.STAGING_CONFLICT, pb.EVIDENCE_STAGING_RESIDUE):
        candidates += _private_residue(env, deterministic)
    if code in (ps.STAGING_CONFLICT, pb.VAULT_STAGING_RESIDUE):
        candidates += _pointer_residue(env, deterministic)
    candidates = [location for location in candidates if os.path.lexists(location) and _plain_file(location)]
    if not candidates:
        return []
    quarantine = env.base / "quarantine"                                                         # 合成の fixture が所有する ・2 つの root の外
    assert all(root not in (quarantine, *quarantine.parents) for root in (env.private, env.vault))
    quarantine.mkdir(exist_ok=True)
    pointer = env.generated / ps.POINTER_NOTE_NAME
    versions, evidence, pointer_bytes = env.versions(), env.evidence(), pointer.read_bytes() if pointer.exists() else None
    before, moved = _surroundings(env), []
    for location in candidates:
        side, root = ("private", env.private) if env.private in location.parents else ("vault", env.vault)
        source = (side, location.relative_to(root).as_posix())
        st, data = location.lstat(), location.read_bytes()
        destination = quarantine / f"{len(env.preserved):03d}.{location.name}"
        assert not os.path.lexists(destination)
        record = {"source": source, "destination": destination, "identity": (st.st_dev, st.st_ino), "data": data,
                  "sha256": hashlib.sha256(data).hexdigest()}
        os.rename(location, destination)                                                         # 移すだけ（消さない ・置き換えない）
        assert not os.path.lexists(location)
        env.preserved.append(record)
        moved.append(source)
    check_preserved(env)
    after = _surroundings(env)
    assert after == {key: value for key, value in before.items() if key not in moved}, moved      # 他の版 ・証拠 ・pointer ・staging は不変
    assert env.versions() == versions and env.evidence() == evidence                               # 前の版 ・確定した証拠は移さない
    assert (pointer.read_bytes() if pointer.exists() else None) == pointer_bytes
    return [path for _, path in moved]


HUMAN_CODES = {ps.PRIVATE_LOCK_PRESENT, ps.VAULT_LOCK_PRESENT, ps.STAGING_CONFLICT, pb.EVIDENCE_STAGING_RESIDUE, pb.VAULT_STAGING_RESIDUE}


def converge(env: Env, monkeypatch=None, *, second_fault: int = 0, deterministic=None) -> list:
    """回復: 公開を繰り返し、A4a1 が明示の保存だけと言えば保存を、記録した人の手順が要る残りにはその模擬を行う（最大 8 回）。人の手順の
    模擬が何も特定できなければ ("HELD", code) で止まる（触らずに HOLD のまま ・広い片付けで迂回しない）。"""
    outcomes = []

    def human(code: str) -> bool:
        moved = human_procedure(env, code, deterministic)
        outcomes.append(("HUMAN", tuple(moved)) if moved else ("HELD", code))
        return bool(moved)

    for attempt in range(8):
        if second_fault and attempt == 0:
            inject(monkeypatch, nth=second_fault)                                                    # 回復の中の 2 つ目の失敗
        try:
            result = env.publish()
        finally:
            if second_fault and attempt == 0:
                monkeypatch.undo()
        outcomes.append((result.status.value, result.code))
        if result.status in (pb.ExportStatus.PUBLISHED, pb.ExportStatus.NO_CHANGE):
            return outcomes
        if result.proposed_action is not None:
            preserved = env.preserve(result.proposed_action)
            if preserved.status is not pb.ExportStatus.PRESERVED and preserved.code in HUMAN_CODES:
                if not human(preserved.code):                                                    # 残りが在る間は保存もしない（先に人の手順）
                    return outcomes
                continue
            assert preserved.status is pb.ExportStatus.PRESERVED, preserved
            outcomes.append(("PRESERVED", preserved.state))
        elif result.code in HUMAN_CODES:
            if not human(result.code):
                return outcomes
        elif not (attempt == 0 and second_fault):
            raise AssertionError((outcomes, result))
    raise AssertionError(outcomes)


AUTO, HELD, MANUAL, UNEXPECTED = ("AUTO_RECOVERED", "HELD_AS_DESIGNED", "MANUAL_INTERVENTION_REQUIRED", "FAILED_UNEXPECTEDLY")
CLASS_LETTER = {AUTO: "A", HELD: "H", MANUAL: "M", UNEXPECTED: "F"}


def recovery_class(outcomes: list, intact: bool) -> str:
    """runtime だけの収束（AUTO）・runtime の安全な HOLD と明示の保存 ／ 特定できない残りで HOLD のまま（HELD）・人の手順の模擬が要った
    （MANUAL ・その後の収束も自動の回復とは数えない）・それ以外（不変条件の破れ ・想定外の結果）を分ける。"""
    kinds = [kind for kind, _ in outcomes]
    if not intact or not kinds:
        return UNEXPECTED
    if kinds[-1] == "HELD":
        return HELD
    if kinds[-1] not in ("PUBLISHED", "NO_CHANGE"):
        return UNEXPECTED
    if "HUMAN" in kinds:
        return MANUAL
    return HELD if "PRESERVED" in kinds else AUTO


# ================================================ 公開 ・NO_CHANGE ・決定論


def test_first_publication_writes_versioned_notes_pointer_and_complete_private_evidence(tmp_path: Path) -> None:
    env = Env(tmp_path)
    result = env.publish()
    target = target_of(GEN_A)
    assert result.status is pb.ExportStatus.PUBLISHED and result.code == "PUBLISHED" and result.binding_recorded is True
    assert result.transitions == ("PREPARE_INTENT", "STAGE_VERSION", "MOVE_STAGED_TO_VERSION", "REPLACE_POINTER", "RECORD_COMPLETION")
    assert result.lock_release == (ps.LOCK_RELEASED, ps.LOCK_RELEASED) and result.failure_evidence == pb.FAILURE_NOT_REQUIRED
    assert (result.public_export_digest, result.version_label) == (target.public_export_digest, target.version_label)
    assert env.versions() == {target.version_label: dict(target.public_export.notes)}               # A4a1 の描画と byte 一致
    assert (env.generated / ps.POINTER_NOTE_NAME).read_bytes() == target.public_export.pointer_note()
    assert sorted(p.name for p in env.generated.iterdir()) == sorted([ps.POINTER_NOTE_NAME, ps.VAULT_STAGING_DIRECTORY, target.version_label])
    intent = pc.intent_for(target, None)
    bundle = env.projection / ps.BUNDLES_DIRECTORY / intent.intent_digest
    assert {p.name: p.read_bytes() for p in bundle.iterdir()} == {
        ps.INTENT_RECORD: intent.to_evidence_bytes(), ps.PUBLIC_EXPORT_RECORD: target.public_export.manifest.to_public_bytes(),
        ps.BINDING_RECORD: target.binding.to_evidence_bytes(), ps.SCAN_RECORD: pb.scan_record(target),
        ps.SOURCE_RECORD: pb.source_record(target.binding)}
    completion = pc.completion_for(intent)
    assert (env.projection / ps.COMPLETIONS_DIRECTORY / f"{completion.completion_digest}.json").read_bytes() == completion.to_evidence_bytes()
    scan = json.loads(pb.scan_record(target))
    assert scan["result"] == "PASSED" and scan["detected_count"] == 0 and scan["file_count"] == len(target.public_export.notes) + 1
    assert [f[0] for f in scan["files"]] == [*(n for n, _ in target.public_export.notes), ps.POINTER_NOTE_NAME]
    assert all(f[3] == 0 for f in scan["files"]) and scan["projection_rules_version"] == pc.CONTRACT_RULES_VERSION
    source = json.loads(pb.source_record(target.binding))
    assert source["private_generation_digest"] == env.outcome.generation_digest and source["generation_read_status"] == "VERIFIED"
    assert source["attestation"] == pb.SOURCE_READ_ATTESTATION and target.binding.source_attestation == pc.SOURCE_ATTESTATION
    assert not any((env.projection / ps.STAGING_DIRECTORY).iterdir()) and not any((env.generated / ps.VAULT_STAGING_DIRECTORY).iterdir())
    assert not (env.projection / ps.LOCKS_DIRECTORY / ps.EXPORT_LOCK_NAME).exists() and not (env.generated / ps.VAULT_LOCK_NAME).exists()


def test_vault_bytes_names_and_links_hold_no_private_digest_window_instant_or_location(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.publish()
    env.use(GEN_A_TWIN).publish()
    vault_text = "\n".join([p.relative_to(env.vault).as_posix() for p in env.generated.rglob("*")]
                           + [p.read_bytes().decode("utf-8") for p in env.generated.rglob("*") if p.is_file()])
    for digest in private_digests(GEN_A) + private_digests(GEN_A_TWIN):
        for start in range(0, 64 - 16 + 1):
            assert digest[start:start + 16] not in vault_text                                      # 16 hex の窓も無い
    assert str(env.base) not in vault_text and "T00:" not in vault_text and "watch-" not in vault_text and "issuer-" not in vault_text
    for path in env.generated.rglob("*.md"):
        data = path.read_bytes()
        assert pc.validate_public_note(data, name=path.name)                                       # 全ての公開の note は後継の検証を通る


def test_a_second_publication_keeps_every_previous_version_byte_and_mtime_identical(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.publish()
    first = tree(env.generated / published_label(GEN_A))
    evidence = env.evidence()
    result = env.use(GEN_B).publish()
    assert result.status is pb.ExportStatus.PUBLISHED
    assert tree(env.generated / published_label(GEN_A)) == first                                    # 前の版は消さない ・移さない ・上書きしない
    assert {k: v for k, v in env.evidence().items() if k in evidence} == evidence
    assert set(env.versions()) == {published_label(GEN_A), published_label(GEN_B)}
    assert (env.generated / ps.POINTER_NOTE_NAME).read_bytes() == target_of(GEN_B).public_export.pointer_note()
    third = env.use(GEN_C).publish()
    assert third.status is pb.ExportStatus.PUBLISHED and len(env.versions()) == 3
    assert tree(env.generated / published_label(GEN_A)) == first


def test_a_replay_is_no_change_and_writes_nothing_but_the_locks(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.publish()
    vault, private = tree(env.vault), tree(env.projection)
    for _ in range(2):
        result = env.publish()
        assert (result.status, result.code, result.transitions, result.binding_recorded) == (pb.ExportStatus.NO_CHANGE, "NO_CHANGE", (), True)
    assert tree(env.vault) == {k: v for k, v in vault.items()} or set(tree(env.vault)) == set(vault)
    assert {k: v[0] for k, v in tree(env.vault).items()} == {k: v[0] for k, v in vault.items()}
    assert {k: v[0] for k, v in tree(env.projection).items()} == {k: v[0] for k, v in private.items()}


def test_public_identical_generations_are_no_change_and_record_the_new_private_binding_once(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.publish()
    vault = {k: v[0] for k, v in tree(env.vault).items()}
    twin = env.use(GEN_A_TWIN).publish()
    target = target_of(GEN_A_TWIN)
    assert (twin.status, twin.transitions, twin.binding_recorded) == (pb.ExportStatus.NO_CHANGE, ("RECORD_PRIVATE_BINDING",), True)
    assert twin.public_export_digest == target_of(GEN_A).public_export_digest                       # 公開は同じ
    assert {k: v[0] for k, v in tree(env.vault).items()} == vault                                   # vault は不変
    binding = env.projection / ps.BINDINGS_DIRECTORY / target.binding.binding_digest
    assert {p.name: p.read_bytes() for p in binding.iterdir()} == {ps.BINDING_RECORD: target.binding.to_evidence_bytes(),
                                                                  ps.SCAN_RECORD: pb.scan_record(target),
                                                                  ps.SOURCE_RECORD: pb.source_record(target.binding)}
    assert target.binding.binding_digest != target_of(GEN_A).binding.binding_digest                # provenance は違う（区別して残す）
    again = env.publish()
    assert (again.status, again.transitions) == (pb.ExportStatus.NO_CHANGE, ())                     # 記録の後は何も書かない


@pytest.mark.parametrize("operation", ["rename", "create", "mkdir"])
def test_a_failure_to_record_the_new_binding_is_never_a_successful_no_change(monkeypatch, tmp_path: Path, operation: str) -> None:
    env = Env(tmp_path)
    env.publish()
    env.use(GEN_A_TWIN)
    marker = {"rename": "binding.", "create": "binding.", "mkdir": "binding."}[operation]
    inject(monkeypatch, faults={operation: lambda location: marker in location and ps.STAGING_DIRECTORY in location})
    failed = env.publish()
    monkeypatch.undo()
    assert failed.status is pb.ExportStatus.FAILED and failed.binding_recorded is None and failed.code == ps.STORE_IO_FAILED
    assert not (env.projection / ps.BINDINGS_DIRECTORY / target_of(GEN_A_TWIN).binding.binding_digest).exists()
    recovered = converge(env)
    assert recovered[-1] == ("NO_CHANGE", "NO_CHANGE")
    assert (env.projection / ps.BINDINGS_DIRECTORY / target_of(GEN_A_TWIN).binding.binding_digest).is_dir()


def test_replay_is_byte_identical_across_roots_working_directories_and_timezones(monkeypatch, tmp_path: Path) -> None:
    snapshots = []
    for index, zone in enumerate(("UTC", "Asia/Tokyo")):
        monkeypatch.setenv("TZ", zone)
        time.tzset()
        env = Env(tmp_path.joinpath(f"run{index}", *(["nested"] * index)), GEN_A)
        monkeypatch.chdir(env.base if index else tmp_path)                                         # 作業の directory を変えても同じ
        env.publish()
        env.use(GEN_B).publish()
        env.use(GEN_A_TWIN)
        snapshots.append(({p.relative_to(env.generated).as_posix(): p.read_bytes() for p in env.generated.rglob("*") if p.is_file()},
                          env.evidence()))
    monkeypatch.delenv("TZ")
    time.tzset()
    assert snapshots[0] == snapshots[1]                                                            # 名前 ・byte ・証拠が完全一致（時刻 ・位置は無い）


# ================================================ A3 の公開の読みの handoff ・入力


def test_the_source_must_be_the_a3_verified_publication_of_the_explicit_generation(tmp_path: Path) -> None:
    env = Env(tmp_path)
    old = env.outcome
    env.use(GEN_B)
    stale = env.publish(generation_digest=old.generation_digest, manifest_digest=old.manifest_digest)
    assert (stale.status, stale.code) == (pb.ExportStatus.REFUSED, pb.SOURCE_NOT_PUBLISHED_GENERATION)   # 公開でない generation は拒む
    assert stale.failure_evidence == pb.FAILURE_RECORDED and not env.versions()
    mismatch = env.publish(manifest_digest="ab" * 32)
    assert mismatch.code == pb.SOURCE_NOT_PUBLISHED_GENERATION
    unknown = env.publish(generation_digest="ab" * 32, manifest_digest="cd" * 32)
    assert unknown.code == pb.SOURCE_NOT_PUBLISHED_GENERATION
    empty = Env(tmp_path / "empty", GEN_A)
    (empty.private / ps.MEMORY_CHILD / ms.MEMORY_DIRECTORY / ms.PUBLICATION_NAME).unlink()          # A3 が未公開
    unpublished = empty.publish()
    assert (unpublished.status, unpublished.code) == (pb.ExportStatus.REFUSED, pb.SOURCE_NOT_VERIFIED)
    corrupt = Env(tmp_path / "corrupt", GEN_A)
    generation = corrupt.private / ps.MEMORY_CHILD / ms.MEMORY_DIRECTORY / ms.GENERATIONS_DIRECTORY / corrupt.outcome.generation_digest
    (generation / "generation.json").write_bytes((generation / "generation.json").read_bytes() + b" ")
    assert corrupt.publish().code == pb.SOURCE_NOT_VERIFIED                                         # A3 の厳密な読みが壊れを検出
    staged = Env(tmp_path / "staged", GEN_A)
    (staged.private / ps.MEMORY_CHILD / ms.MEMORY_DIRECTORY / ms.STAGING_DIRECTORY / ("ab" * 32 + ms.PARTIAL_SUFFIX)).mkdir()
    assert staged.publish().code == pb.SOURCE_STAGING_PRESENT                                       # A3 の中断の build が在れば書かない
    missing = Env(tmp_path / "missing", GEN_A)
    os.rename(missing.private / ps.MEMORY_CHILD, missing.base / "memory-moved")
    gone = missing.publish()
    assert gone.status is pb.ExportStatus.REFUSED and gone.code in (ps.LAYOUT_INVALID, ps.UNSAFE_ENTRY)
    for case in (env, empty, corrupt, staged):
        assert not any(case.generated.glob("p13pvn_*")) or case is env


@pytest.mark.parametrize("kwargs, code", [
    ({"generation_digest": "abc"}, pb.EXPORT_INPUT_INVALID), ({"manifest_digest": "AB" * 32}, pb.EXPORT_INPUT_INVALID),
    ({"protected": {ps.VAULT_ROOT_LABEL: "/x"}}, pb.EXPORT_INPUT_INVALID), ({"limits": {"retained_versions": 1}}, pb.EXPORT_INPUT_INVALID),
])
def test_inputs_require_full_digests_unreserved_labels_and_typed_limits(tmp_path: Path, kwargs, code) -> None:
    env = Env(tmp_path)
    with pytest.raises(pb.ExportInputError) as exc:
        env.publish(**kwargs)
    assert exc.value.code == code and not env.versions()


@pytest.mark.parametrize("field, value", [("retained_versions", 65), ("vault_export_bytes", 256 * MIB + 1),
                                          ("private_evidence_bytes", 64 * MIB + 1), ("observation_objects", 4097),
                                          ("free_margin_bytes", 512 * MIB - 1)])
def test_caller_limits_may_only_tighten(field: str, value: int) -> None:
    with pytest.raises(pb.ExportInputError) as exc:
        pb.ExportLimits(**{field: value})
    assert exc.value.code == pb.LIMIT_LOOSENED
    with pytest.raises(pb.ExportInputError):
        pb.ExportLimits(**{field: True})
    assert pb.ExportLimits(retained_versions=1, free_margin_bytes=1024 * MIB).retained_versions == 1


def test_preservation_takes_only_the_explicit_a4a1_actions(tmp_path: Path) -> None:
    env = Env(tmp_path)
    for action in ("STAGE_VERSION", "REPLACE_POINTER", "ARCHIVE", "HOLD"):
        with pytest.raises(pb.ExportInputError):
            env.preserve(action)
    env.publish()
    refused = env.preserve("PRESERVE_STAGING")                                                       # 公開済みの状態では保存は無い
    assert (refused.status, refused.code) == (pb.ExportStatus.HELD, pc.UNSAFE_PRESERVATION_PROPOSAL)
    assert set(env.versions()) == {published_label(GEN_A)}


# ================================================ 中断 ・回復（全ての書き込みの操作の前 ／ 後 ／ 途中）


def _mutation_count(base: Path) -> int:
    env = Env(base, GEN_ONE)
    assert env.publish().status is pb.ExportStatus.PUBLISHED
    env.use(GEN_ONE_B)
    from tests.intelligence.test_market_memory_projection_store import FaultyOs
    proxy = FaultyOs()
    original = ps.os
    ps.os = proxy
    try:
        assert env.publish().status is pb.ExportStatus.PUBLISHED
    finally:
        ps.os = original
    return proxy.count


#: 監査した 252 の場合（42 の書き込みの操作 × 6 つの故障の形: 前 ／ 後 ／ 切れ × 1 つの故障 ／ 回復の中の 2 つ目の故障つき）の回復の分類の
#: 基準。1 文字が 1 つの操作（順は無故障の公開の書き込みの順）。A = AUTO_RECOVERED ・H = HELD_AS_DESIGNED ・M = MANUAL_INTERVENTION_REQUIRED
#: ・F = FAILED_UNEXPECTEDLY。結果が違えば期待を黙って書き換えず原因を調べる。
RECOVERY_MATRIX = {
    ("BEFORE", False): "AMMAMMAAMAAMAAMAAMAAMAAAAHAAHAAHAMAAAMAAMM",
    ("AFTER", False): "MMMMMMAMAAMAAMAAMAAMAAAAHAAHAAHAMAAAMAAAAA",
    ("TORN", False): "AMMAMMAAMAAMAAMAAMAAMAAAAHAAHAAHAMAAAMAAMM",
    ("BEFORE", True): "AMMAMMAMMAMMAMMAMMAMMAAAAMAAMAAMAMAAAMAAMM",
    ("AFTER", True): "MMMMMMAMAAMAAMAAMAAMAAAAHHAHHAHMMAAAMAAAAA",
    ("TORN", True): "AMMAMMAMMAMMAMMAMMAMMAAAAMAAMAAMAMAAAMAAMM",
}
FAULT_MODES = {"BEFORE": {"after": False, "torn": False}, "AFTER": {"after": True, "torn": False}, "TORN": {"after": False, "torn": True}}


def _fault_matrix(monkeypatch, tmp_path: Path, *, after: bool, torn: bool, second: bool = True) -> list:
    count = _mutation_count(tmp_path / "count")
    assert count == len(RECOVERY_MATRIX[("BEFORE", False)])                                       # 監査した書き込みの操作の数
    reference = Env(tmp_path / "reference", GEN_ONE)
    reference.publish()
    published = reference.use(GEN_ONE_B).publish()
    expected_versions = reference.versions()
    expected_pointer = (reference.generated / ps.POINTER_NOTE_NAME).read_bytes()
    expected_evidence = {k: v for k, v in reference.evidence().items() if not k.startswith(ps.FAILURES_DIRECTORY)}
    deterministic = deterministic_staging(reference, published.public_export_digest)
    seen = []
    for nth in range(1, count + 1):
        env = Env(tmp_path / f"k{nth:03d}", GEN_ONE)
        env.publish()
        before_versions, before_evidence = env.versions(), env.evidence()
        before_pointer = (env.generated / ps.POINTER_NOTE_NAME).read_bytes()
        env.use(GEN_ONE_B)
        inject(monkeypatch, nth=nth, after=after, torn=torn)
        try:
            faulted = env.publish()
        finally:
            monkeypatch.undo()

        def kept() -> bool:                                                                          # 前の版は不変 ・証拠は消えない
            return ({k: v for k, v in env.versions().items() if k in before_versions} == before_versions
                    and {k: v for k, v in env.evidence().items() if k in before_evidence} == before_evidence)

        intact = kept() and (env.generated / ps.POINTER_NOTE_NAME).read_bytes() in (before_pointer, expected_pointer)
        try:                                                                                         # 2 つの lock の 6 つの操作の後の最初の書き込み
            outcomes = converge(env, monkeypatch, second_fault=(0, 7, 8)[nth % 3] if second else 0, deterministic=deterministic)
        except AssertionError as error:
            outcomes, intact = [("UNEXPECTED", str(error)[:300])], False
        intact = intact and kept()
        if outcomes[-1][0] in ("PUBLISHED", "NO_CHANGE"):                                           # 収束した版 ・pointer ・証拠は参照と byte 一致
            intact = intact and env.versions() == expected_versions and (
                env.generated / ps.POINTER_NOTE_NAME).read_bytes() == expected_pointer and {
                k: v for k, v in env.evidence().items() if not k.startswith(ps.FAILURES_DIRECTORY)} == expected_evidence
        check_preserved(env)                                                                         # 移した残りは最後まで同じ byte で在る
        seen.append((nth, faulted.status.value, faulted.code, tuple(o[0] for o in outcomes), recovery_class(outcomes, intact)))
    return seen


def _assert_recovery_matrix(seen: list, mode: str, second: bool) -> None:
    expected = RECOVERY_MATRIX[(mode, second)]
    observed = "".join(CLASS_LETTER[cls] for *_, cls in seen)
    assert observed == expected, [(row, want) for row, want in zip(seen, expected) if CLASS_LETTER[row[-1]] != want]
    assert all(cls != UNEXPECTED for *_, cls in seen)
    assert all(steps[-1] in ("PUBLISHED", "NO_CHANGE") for *_, steps, _ in seen)                    # 監査した全ての場合は収束する（HOLD のまま無し）


def test_a_fault_before_every_mutation_converges_or_needs_only_a_recorded_human_or_explicit_step(monkeypatch, tmp_path: Path) -> None:
    seen = _fault_matrix(monkeypatch, tmp_path, after=False, torn=False)
    _assert_recovery_matrix(seen, "BEFORE", second=True)                                          # 監査した分類と 1 つずつ一致
    kinds = {status for _, status, *_ in seen}
    assert "FAILED" in kinds and any("PRESERVED" in steps for *_, steps, _ in seen)                 # 明示の保存の経路を通った
    assert any("HUMAN" in steps for *_, steps, _ in seen)                                            # 残った lock ・管理の残り


def test_a_fault_after_every_mutation_converges_or_needs_only_a_recorded_human_or_explicit_step(monkeypatch, tmp_path: Path) -> None:
    seen = _fault_matrix(monkeypatch, tmp_path, after=True, torn=False)
    _assert_recovery_matrix(seen, "AFTER", second=True)
    assert any(steps == ("NO_CHANGE",) or steps[-1] == "NO_CHANGE" for *_, steps, _ in seen)


def test_a_torn_write_at_every_mutation_never_loses_data_and_recovers(monkeypatch, tmp_path: Path) -> None:
    seen = _fault_matrix(monkeypatch, tmp_path, after=False, torn=True)
    _assert_recovery_matrix(seen, "TORN", second=True)
    assert any("PRESERVED" in steps for *_, steps, _ in seen)                                        # 切れた note は明示の保存


@pytest.mark.parametrize("mode", list(FAULT_MODES))
def test_a_single_fault_at_every_mutation_has_exactly_the_audited_recovery_class(monkeypatch, tmp_path: Path, mode: str) -> None:
    seen = _fault_matrix(monkeypatch, tmp_path, **FAULT_MODES[mode], second=False)                  # 回復の中の 2 つ目の故障なし
    _assert_recovery_matrix(seen, mode, second=False)
    for *_, steps, cls in seen:                                                                       # 人の手順の後の収束は自動と数えない
        assert ("HUMAN" in steps) is (cls == MANUAL) and (cls != AUTO or steps in (("PUBLISHED",), ("NO_CHANGE",)))


def _reference_staging(base: Path) -> tuple:
    reference = Env(base, GEN_ONE)
    reference.publish()
    published = reference.use(GEN_ONE_B).publish()
    return reference, deterministic_staging(reference, published.public_export_digest)


def _torn_bundle(monkeypatch, base: Path) -> tuple:
    """3 つ目の bundle の record を書く前に止めた環境（作業中の bundle に byte 一致の record 2 つと空の record 1 つ）。"""
    env = Env(base, GEN_ONE)
    env.publish()
    env.use(GEN_ONE_B)
    inject(monkeypatch, nth=15)
    try:
        assert env.publish().status is pb.ExportStatus.FAILED
    finally:
        monkeypatch.undo()
    partial = next((env.projection / ps.STAGING_DIRECTORY).glob("bundle.*.partial"))
    records = sorted(partial.iterdir())
    assert len(records) == 3 and [r.read_bytes() == b"" for r in records].count(True) == 1
    return env, partial


def test_the_simulated_human_procedure_moves_only_identified_residue_and_keeps_adoptable_records(monkeypatch, tmp_path: Path) -> None:
    reference, deterministic = _reference_staging(tmp_path / "reference")
    env, partial = _torn_bundle(monkeypatch, tmp_path / "env")
    torn = next(r for r in sorted(partial.iterdir()) if r.read_bytes() == b"")
    kept = {r.name: r.read_bytes() for r in sorted(partial.iterdir()) if r != torn}
    leftover = env.projection / ps.STAGING_DIRECTORY / f"failure.{'cd' * 32}.tmp"
    leftover.write_bytes(b"an interrupted failure record")
    held = env.publish()
    assert (held.status, held.code) == (pb.ExportStatus.HELD, pb.EVIDENCE_STAGING_RESIDUE)
    before = _surroundings(env)
    moved = human_procedure(env, held.code, deterministic)
    assert moved == [f"{ps.PROJECTION_CHILD}/{ps.STAGING_DIRECTORY}/{partial.name}/{torn.name}",
                     f"{ps.PROJECTION_CHILD}/{ps.STAGING_DIRECTORY}/{leftover.name}"]                      # 切れた record と FAILED の残りだけ
    assert {r.name: r.read_bytes() for r in sorted(partial.iterdir())} == kept                     # byte 一致の record は移さない
    assert all(deterministic[("private", f"{partial.name}/{name}")] == data for name, data in kept.items())
    assert [(r["source"][1], r["data"], r["sha256"]) for r in env.preserved] == [
        (moved[0], b"", hashlib.sha256(b"").hexdigest()),
        (moved[1], b"an interrupted failure record", hashlib.sha256(b"an interrupted failure record").hexdigest())]
    assert [before[("private", path)][1:3] for path in moved] == [r["identity"] for r in env.preserved]   # 同じ identity のまま保存
    check_preserved(env)
    assert env.publish().status is pb.ExportStatus.PUBLISHED                                       # 残した record で続く
    assert env.versions() == reference.versions()
    check_preserved(env)


def test_residue_that_cannot_be_identified_is_left_untouched_and_the_case_stays_held(monkeypatch, tmp_path: Path) -> None:
    _, deterministic = _reference_staging(tmp_path / "reference")
    env, partial = _torn_bundle(monkeypatch, tmp_path / "env")
    before = _surroundings(env)
    outcomes = converge(env)                                                                         # 決定論の byte が分からない
    assert outcomes[-1] == ("HELD", ps.STAGING_CONFLICT) and recovery_class(outcomes, True) == HELD
    assert {k: v for k, v in _surroundings(env).items() if ps.FAILURES_DIRECTORY not in k[1]} == {
        k: v for k, v in before.items() if ps.FAILURES_DIRECTORY not in k[1]}                       # 失敗の証拠の追加の他は不変
    assert not env.preserved and not (env.base / "quarantine").exists()
    assert [r.read_bytes() == b"" for r in sorted(partial.iterdir())].count(True) == 1               # 切れた record もそのまま
    other = Env(tmp_path / "other", GEN_ONE)
    other.publish()
    unknown = other.projection / ps.STAGING_DIRECTORY / f"completion.{'ef' * 32}.tmp"
    unknown.write_bytes(b"not a known record")                                                     # 期待の byte が無い名前
    held = other.publish()
    assert (held.status, held.code) == (pb.ExportStatus.HELD, pb.EVIDENCE_STAGING_RESIDUE)
    snapshot = _surroundings(other)
    assert human_procedure(other, held.code, deterministic) == [] and _surroundings(other) == snapshot
    assert human_procedure(other, pb.VAULT_STAGING_RESIDUE, deterministic) == []                     # code が名指さない残りは触らない
    assert unknown.read_bytes() == b"not a known record" and not other.preserved


def test_only_the_lock_named_by_the_hold_is_moved_and_each_left_lock_is_preserved(tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_ONE)
    env.publish()
    private_lock, vault_lock = env.projection / ps.LOCKS_DIRECTORY / ps.EXPORT_LOCK_NAME, env.generated / ps.VAULT_LOCK_NAME
    private_lock.write_bytes(b"left private lock")
    vault_lock.write_bytes(b"left vault lock")
    steps = []
    for code, location, data in ((ps.PRIVATE_LOCK_PRESENT, private_lock, b"left private lock"),
                                 (ps.VAULT_LOCK_PRESENT, vault_lock, b"left vault lock")):
        refused = env.publish()
        assert (refused.status, refused.code) == (pb.ExportStatus.REFUSED, code)                    # 奪取しない ・消さない
        other = vault_lock if location == private_lock else private_lock
        other_bytes = other.read_bytes() if other.exists() else None
        steps.append(human_procedure(env, code))
        assert not location.exists() and (other.read_bytes() if other.exists() else None) == other_bytes
        assert env.preserved[-1]["data"] == data
    assert steps == [[f"{ps.PROJECTION_CHILD}/{ps.LOCKS_DIRECTORY}/{ps.EXPORT_LOCK_NAME}"],
                     [f"{ps.GENERATED_DIRECTORY}/{ps.VAULT_LOCK_NAME}"]]
    assert env.publish().status is pb.ExportStatus.NO_CHANGE
    check_preserved(env)


def test_partial_staging_continues_by_creating_only_the_missing_notes(monkeypatch, tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    label = published_label(GEN_A)
    inject(monkeypatch, faults={"create": lambda location: location.endswith("-s002.md") and ps.VAULT_STAGING_DIRECTORY in location})
    failed = env.publish()
    monkeypatch.undo()
    assert failed.status is pb.ExportStatus.FAILED and failed.failure_evidence == pb.FAILURE_RECORDED
    staging = env.generated / ps.VAULT_STAGING_DIRECTORY / label
    present = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns) for p in staging.iterdir()}
    assert present and len(present) < len(target_of(GEN_A).public_export.notes)
    result = env.publish()
    assert result.status is pb.ExportStatus.PUBLISHED and result.transitions[0] == "CONTINUE_STAGING"
    moved = env.generated / label
    assert {n: (moved / n).stat().st_ino for n in present} == {n: v[0] for n, v in present.items()}  # 在った file は触らない


def test_torn_staging_needs_explicit_preservation_and_tampered_or_foreign_staging_holds(monkeypatch, tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    label = published_label(GEN_A)
    inject(monkeypatch, faults={"write": lambda location: location.endswith("-s001.md")}, torn=True)
    env.publish()
    monkeypatch.undo()
    held = env.publish()
    assert (held.status, held.code, held.state, held.proposed_action) == (
        pb.ExportStatus.HELD, pb.EXPLICIT_PRESERVATION_REQUIRED, "STAGING_TORN", "PRESERVE_STAGING")
    assert env.publish().code == pb.EXPLICIT_PRESERVATION_REQUIRED                                  # 自動では決して保存しない
    torn_bytes = (env.generated / ps.VAULT_STAGING_DIRECTORY / label / f"{label}-s001.md").read_bytes()
    preserved = env.preserve("PRESERVE_STAGING")
    assert (preserved.status, preserved.state) == (pb.ExportStatus.PRESERVED, "INTENT_PREPARED")
    kept = env.generated / ps.VAULT_INTERRUPTED_DIRECTORY / f"{label}.001.interrupted" / f"{label}-s001.md"
    assert kept.read_bytes() == torn_bytes                                                          # 消さずに移した
    assert env.publish().status is pb.ExportStatus.PUBLISHED
    tampered = Env(tmp_path / "tampered", GEN_A)
    inject(monkeypatch, faults={"create": lambda location: location.endswith("-s002.md")})
    tampered.publish()
    monkeypatch.undo()
    note = tampered.generated / ps.VAULT_STAGING_DIRECTORY / label / f"{label}-s001.md"
    note.write_bytes(note.read_bytes().replace(b"| 0 |", b"| 7 |", 1))
    hold = tampered.publish()
    assert (hold.status, hold.code, hold.proposed_action) == (pb.ExportStatus.HELD, pc.STAGING_TAMPERED, None)
    assert tampered.preserve("PRESERVE_STAGING").code == pc.UNSAFE_PRESERVATION_PROPOSAL             # 改竄は保存の対象でもない
    (tampered.generated / ps.VAULT_STAGING_DIRECTORY / label / f"{label}-s009.md").write_bytes(b"x")
    assert tampered.publish().code in (pc.STAGING_FOREIGN_ENTRY, pc.STAGING_TAMPERED)


@pytest.mark.skipif(os.name == "nt", reason="POSIX の予約の中断だけ")
def test_an_empty_version_reservation_is_preserved_only_explicitly_and_then_converges(monkeypatch, tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    env.publish()
    env.use(GEN_B)
    label = published_label(GEN_B)
    inject(monkeypatch, faults={"rename": lambda location: location.endswith(os.sep + label) and ps.VAULT_STAGING_DIRECTORY in location})
    failed = env.publish()
    monkeypatch.undo()
    assert failed.status is pb.ExportStatus.FAILED and (env.generated / label).is_dir() and not any((env.generated / label).iterdir())
    held = env.publish()
    assert (held.code, held.state, held.proposed_action) == (pb.EXPLICIT_PRESERVATION_REQUIRED, "VERSION_RESERVED_EMPTY",
                                                             "PRESERVE_EMPTY_RESERVATION")
    assert env.preserve("PRESERVE_STAGING").code == pc.UNSAFE_PRESERVATION_PROPOSAL                  # 次の遷移でない保存は拒む
    preserved = env.preserve("PRESERVE_EMPTY_RESERVATION")
    assert (preserved.status, preserved.state) == (pb.ExportStatus.PRESERVED, "STAGED_VERIFIED")
    assert (env.generated / ps.VAULT_INTERRUPTED_DIRECTORY / f"{label}.001.interrupted").is_dir()
    assert env.publish().status is pb.ExportStatus.PUBLISHED
    assert set(env.versions()) == {published_label(GEN_A), label}


def test_an_interrupted_bundle_resumes_and_torn_private_residue_holds_untouched(monkeypatch, tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    inject(monkeypatch, faults={"create": lambda location: location.endswith(ps.SOURCE_RECORD)})
    env.publish()
    monkeypatch.undo()
    partial = [p.name for p in (env.projection / ps.STAGING_DIRECTORY).iterdir()]
    assert len(partial) == 1 and partial[0].startswith("bundle.")
    assert env.publish().status is pb.ExportStatus.PUBLISHED                                        # byte 一致の残りは続きに使う
    torn = Env(tmp_path / "torn", GEN_A)
    inject(monkeypatch, faults={"write": lambda location: location.endswith(ps.SCAN_RECORD)}, torn=True)
    torn.publish()
    monkeypatch.undo()
    residue = {p.name: p.read_bytes() for p in (torn.projection / ps.STAGING_DIRECTORY).rglob("*") if p.is_file()}
    held = torn.publish()
    assert held.code == ps.STAGING_CONFLICT and not torn.versions()                                 # 違う残りは触らずに止まる
    assert {p.name: p.read_bytes() for p in (torn.projection / ps.STAGING_DIRECTORY).rglob("*") if p.is_file()} == residue
    other = Env(tmp_path / "other", GEN_A)
    (other.projection / ps.STAGING_DIRECTORY / f"completion.{'ab' * 32}.tmp").write_bytes(b"{}\n")  # 今の遷移と関係ない残り
    blocked = other.publish()
    assert (blocked.status, blocked.code) == (pb.ExportStatus.HELD, pb.EVIDENCE_STAGING_RESIDUE) and not other.versions()


def test_a_pointer_temp_resumes_only_with_identical_bytes_and_foreign_temps_hold(monkeypatch, tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    inject(monkeypatch, faults={"replace": lambda location: location.endswith(".tmp")})
    failed = env.publish()
    monkeypatch.undo()
    assert failed.code == ps.STORE_IO_FAILED and not (env.generated / ps.POINTER_NOTE_NAME).exists()
    assert len(list((env.generated / ps.VAULT_STAGING_DIRECTORY).glob("*.tmp"))) == 1
    resumed = env.publish()
    assert resumed.status is pb.ExportStatus.PUBLISHED and resumed.transitions == ("REPLACE_POINTER", "RECORD_COMPLETION")
    assert not list((env.generated / ps.VAULT_STAGING_DIRECTORY).glob("*.tmp"))
    stray = env.generated / ps.VAULT_STAGING_DIRECTORY / f"p13-memory.{'ab' * 32}.tmp"
    stray.write_bytes(b"x")
    held = env.publish()
    assert (held.status, held.code) == (pb.ExportStatus.HELD, pb.VAULT_STAGING_RESIDUE) and stray.read_bytes() == b"x"


def test_lost_vault_lock_ownership_mid_run_fails_without_releasing_the_foreign_lock(monkeypatch, tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    lock = env.generated / ps.VAULT_LOCK_NAME
    original = ps.ProjectionStore.stage_notes

    def swap(self, locks, label, notes, existing):
        swapped = lock.with_name("swap")
        swapped.write_bytes(lock.read_bytes())
        os.replace(swapped, lock)                                                                   # 他の誰かが同じ byte の lock に替えた
        return original(self, locks, label, notes, existing)
    monkeypatch.setattr(ps.ProjectionStore, "stage_notes", swap)
    result = env.publish()
    monkeypatch.undo()
    assert (result.status, result.code) == (pb.ExportStatus.FAILED, ps.LOCK_OWNERSHIP_UNVERIFIED)
    assert result.lock_release == (ps.LOCK_OWNERSHIP_UNVERIFIED, ps.LOCK_RELEASED)                   # 所有を検証できない lock は残す
    assert lock.is_file() and not (env.generated / ps.VAULT_STAGING_DIRECTORY / published_label(GEN_A)).exists()
    assert result.failure_evidence == pb.FAILURE_NOT_RECORDED                                        # lock の所有が無ければ証拠も書かない
    assert env.publish().code == ps.VAULT_LOCK_PRESENT


@pytest.mark.parametrize("sabotage", ["drop_note", "extra_note"])
def test_a_write_that_does_not_match_the_prediction_fails_and_is_never_reported_as_success(monkeypatch, tmp_path: Path, sabotage) -> None:
    env = Env(tmp_path, GEN_A)
    original = ps.ProjectionStore.stage_notes
    label = published_label(GEN_A)

    def wrong(self, locks, staged_label, notes, existing):
        changed = dict(notes)
        if sabotage == "drop_note":
            changed.pop(sorted(changed)[-1])                                                         # 1 つ足りない
        else:
            changed[f"{label}-s099.md"] = next(iter(notes.values()))                                # 1 つ多い
        return original(self, locks, staged_label, changed, existing)
    monkeypatch.setattr(ps.ProjectionStore, "stage_notes", wrong)
    result = env.publish()
    monkeypatch.undo()
    assert (result.status, result.code, result.transitions) == (pb.ExportStatus.FAILED, pb.POST_STATE_MISMATCH,
                                                                ("PREPARE_INTENT", "STAGE_VERSION"))   # disk を予測と照らす
    assert not (env.generated / ps.POINTER_NOTE_NAME).exists() and not env.versions()
    assert result.failure_evidence == pb.FAILURE_RECORDED


def test_a_second_private_root_never_adopts_or_touches_another_roots_export(tmp_path: Path) -> None:
    first = Env(tmp_path / "a", GEN_A)
    second = Env(tmp_path / "b", GEN_B, vault=first.vault)
    first.publish()
    vault = {k: v[0] for k, v in tree(first.vault).items()}
    held = second.publish()
    assert (held.status, held.code) == (pb.ExportStatus.HELD, pc.UNREFERENCED_VERSION)               # 他の root の版は採らない
    assert {k: v[0] for k, v in tree(first.vault).items()} == vault and not any((second.projection / ps.BUNDLES_DIRECTORY).iterdir())
    locks = ps.open_projection_store(str(first.private), str(first.vault), protected_roots={}).acquire_locks(operation="PUBLISH")
    try:
        refused = second.publish()
    finally:
        locks.release()
    assert (refused.status, refused.code, refused.lock_release) == (pb.ExportStatus.REFUSED, ps.VAULT_LOCK_PRESENT,
                                                                   (ps.LOCK_NOT_ACQUIRED, ps.LOCK_NOT_ACQUIRED))
    assert not (second.projection / ps.LOCKS_DIRECTORY / ps.EXPORT_LOCK_NAME).exists()


# ================================================ R1: 走査の証拠（承認した全ての pattern ・件数 ・規則の digest ・被覆）


#: 合成の fixture（GEN_A）の走査の証拠の identity（走査の規則 ・描画の byte が変われば変わる ・ここで止まる）
GOLDEN_SCAN_RECORD_DIGEST = "097ce3969671abe1bae2caec344de5548e26a46d070c5b7791afe9dfbecf0afa"


def _bundle_scan(env: Env) -> Path:
    return next((env.projection / ps.BUNDLES_DIRECTORY).glob("*/" + ps.SCAN_RECORD))


def test_scan_evidence_enumerates_every_approved_pattern_with_counts_rules_digest_and_complete_coverage(tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    env.publish()
    data = _bundle_scan(env).read_bytes()
    target = target_of(GEN_A)
    assert data == pb.scan_record(target)
    value = json.loads(data)
    labels = [label for label, _ in frozen_a4a.PRIVATE_SHAPE_PATTERNS]
    assert value["patterns"] == labels and len(labels) == 18                                         # 承認した全ての識別子 ・表の順
    assert value["pattern_counts"] == [[label, 0] for label in labels]                               # pattern ごとの件数
    assert value["scan_rules_version"] == pb.SCAN_RULES_VERSION
    assert value["scan_rules_digest"] == domain_digest(pb.SCAN_RULES_DOMAIN, {
        "scan_rules_version": pb.SCAN_RULES_VERSION, "projection_rules_version": pc.CONTRACT_RULES_VERSION,
        "patterns": [list(pair) for pair in frozen_a4a.PRIVATE_SHAPE_PATTERNS]})                     # 凍結の表から再計算
    covered = {name: (size, sha) for name, size, sha, _ in value["files"]}
    assert covered == {**{f.name: (f.size, f.sha256) for f in target.public_export.manifest.files},
                       ps.POINTER_NOTE_NAME: (len(target.public_export.pointer_note()),
                                              pb.sha256_hex(target.public_export.pointer_note()))}    # 全ての出力の file の digest
    assert (value["result"], value["detected_count"]) == ("PASSED", 0)
    for _, pattern in frozen_a4a.PRIVATE_SHAPE_PATTERNS:
        assert pattern.encode("utf-8") not in data                                                 # 正規表現 ・当たった文字列は記録しない
    digest = pb.scan_record_digest(data)
    assert digest == domain_digest(pb.SCAN_DOMAIN, value) and digest == pb.scan_record_digest(pb.scan_record(target_of(GEN_A)))
    assert digest == GOLDEN_SCAN_RECORD_DIGEST                                                      # 決定論の identity（固定の値）
    twin = Env(tmp_path / "twin", GEN_A)
    twin.publish()
    assert _bundle_scan(twin).read_bytes() == data                                                   # 別の root でも byte 一致


def _forged(value: dict, case: str) -> dict:
    forged = json.loads(json.dumps(value))
    if case == "missing_pattern":
        forged["patterns"] = forged["patterns"][1:]
        forged["pattern_counts"] = forged["pattern_counts"][1:]
    elif case == "altered_pattern":
        forged["patterns"][2] = "SLASHES"
        forged["pattern_counts"][2][0] = "SLASHES"
    elif case == "reordered_patterns":
        forged["patterns"][0], forged["patterns"][1] = forged["patterns"][1], forged["patterns"][0]
    elif case == "nonzero_count":
        forged["pattern_counts"][5][1] = 1
        forged["detected_count"], forged["result"] = 1, "DETECTED"
    elif case == "forged_count_still_passed":
        forged["pattern_counts"][5][1] = 3
    elif case == "file_count_forged":
        forged["files"][0][3] = 2
    elif case == "missing_coverage":
        forged["files"] = forged["files"][:-1]
        forged["file_count"] -= 1
    elif case == "altered_coverage_digest":
        forged["files"][0][2] = "ab" * 32
    elif case == "rules_digest_drift":
        forged["scan_rules_digest"] = "ab" * 32
    elif case == "rules_version_drift":
        forged["scan_rules_version"] = "p13_projection_scan_rules:0.2.0"
    elif case == "result_drift":
        forged["result"] = "DETECTED"
    elif case == "extra_field":
        forged["matched_text"] = "none"
    return forged


@pytest.mark.parametrize("case", ["missing_pattern", "altered_pattern", "reordered_patterns", "nonzero_count", "forged_count_still_passed",
                                  "file_count_forged", "missing_coverage", "altered_coverage_digest", "rules_digest_drift",
                                  "rules_version_drift", "result_drift", "extra_field"])
def test_forged_or_drifted_scan_evidence_is_rejected_on_every_read(tmp_path: Path, case: str) -> None:
    env = Env(tmp_path, GEN_A)
    env.publish()
    from src.intelligence.market_memory.memory_generation import record_bytes
    scan = _bundle_scan(env)
    scan.write_bytes(record_bytes(_forged(json.loads(scan.read_bytes()), case)))                     # 正準の byte のまま内容だけを変える
    vault = {k: v[0] for k, v in tree(env.vault).items()}
    for result in (env.publish(), env.use(GEN_B).publish()):
        assert (result.status, result.code) == (pb.ExportStatus.HELD, pb.SCAN_EVIDENCE_INVALID), case
    assert {k: v[0] for k, v in tree(env.vault).items()} == vault                                   # 何も書かない


def test_a_detected_or_disagreeing_scan_never_produces_a_passed_record(monkeypatch, tmp_path: Path) -> None:
    import re
    env = Env(tmp_path, GEN_A)
    shapes = tuple((label, re.compile(r"\|") if label == "SLASH" else pattern) for label, pattern in pb._SCAN_SHAPES)
    monkeypatch.setattr(pb, "_SCAN_SHAPES", shapes)                                                  # 写しだけが変わった（承認した走査器と違う）
    drift = env.publish()
    assert (drift.status, drift.code, drift.failure_evidence) == (pb.ExportStatus.REFUSED, pb.SCAN_RULES_DRIFT, pb.FAILURE_RECORDED)
    monkeypatch.setattr(pb, "scan_private_shapes", lambda text: ("SLASH",) if "|" in text else ())  # 両方が当てた時
    detected = env.publish()
    monkeypatch.undo()
    assert (detected.status, detected.code) == (pb.ExportStatus.REFUSED, pb.SCAN_FAILED)
    assert not env.versions() and not any((env.projection / ps.BUNDLES_DIRECTORY).iterdir())          # PASSED の record も版も無い
    failures = [json.loads(p.read_bytes()) for p in (env.projection / ps.FAILURES_DIRECTORY).iterdir()]
    assert {(f["stage"], f["code"], f["detail"]) for f in failures} == {("SCAN", pb.SCAN_RULES_DRIFT, "APPROVED_SCANNER_DISAGREES"),
                                                                        ("SCAN", pb.SCAN_FAILED, "SLASH")}   # 識別子だけ ・当たった文字列は無い
    counts = dict(zip([label for label, _ in pb.SCAN_PATTERNS], pb._pattern_counts("a/b a/c")))
    assert counts["SLASH"] == 2 and sum(counts.values()) == 2                                       # 件数は当たりの数だけ（文字列は返さない）


# ================================================ R2: FAILED の証拠の一時 file（確定 ・この操作が書く途中 ・残り）


def _failing_run(env: Env, old) -> pb.ExportResult:
    """公開でない generation を求めて FAILED の証拠を書かせる（source の段の拒否）。"""
    return env.publish(generation_digest=old.generation_digest, manifest_digest=old.manifest_digest)


def _failure_temps(env: Env) -> dict:
    return {p.name: p.read_bytes() for p in (env.projection / ps.STAGING_DIRECTORY).glob("failure.*.tmp")}


def test_finalized_failure_evidence_is_verified_and_kept_through_later_publications(tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    old = env.outcome
    env.use(GEN_B)
    assert _failing_run(env, old).failure_evidence == pb.FAILURE_RECORDED
    history = {p.name: p.read_bytes() for p in (env.projection / ps.FAILURES_DIRECTORY).iterdir()}
    assert len(history) == 1
    assert env.publish().status is pb.ExportStatus.PUBLISHED
    assert env.use(GEN_C).publish().status is pb.ExportStatus.PUBLISHED
    assert {p.name: p.read_bytes() for p in (env.projection / ps.FAILURES_DIRECTORY).iterdir()} == history   # 掃除しない ・上書きしない


@pytest.mark.parametrize("phase, operation, kwargs, residue", [
    ("before_create", "create", {}, False),                                                         # 一時 file を作る前に止まる
    ("during_write", "write", {"torn": True}, True),                                                # 書く途中で切れた一時 file
    ("before_finalize", "rename", {}, True),                                                        # 書き終えた一時 file ・rename の前
    ("after_finalize", "rename", {"after": True}, False),                                           # rename の後（確定した証拠）
])
def test_an_interrupted_failure_record_is_never_adopted_and_leftover_temps_hold_every_operation(monkeypatch, tmp_path: Path, phase,
                                                                                                 operation, kwargs, residue) -> None:
    env = Env(tmp_path, GEN_A)
    old = env.outcome
    env.use(GEN_B)
    inject(monkeypatch, faults={operation: lambda location: os.path.basename(location).startswith("failure.")}, **kwargs)
    first = _failing_run(env, old)
    monkeypatch.undo()
    assert first.status is pb.ExportStatus.REFUSED and first.code == pb.SOURCE_NOT_PUBLISHED_GENERATION
    assert first.failure_evidence == pb.FAILURE_NOT_RECORDED, phase                                  # 確かめられない記録は記録済みと言わない
    temps, finalized = _failure_temps(env), {p.name: p.read_bytes() for p in (env.projection / ps.FAILURES_DIRECTORY).iterdir()}
    assert bool(temps) is residue and bool(finalized) is (phase == "after_finalize")
    if not residue:
        assert env.publish().status is pb.ExportStatus.PUBLISHED                                     # 残りが無ければ続く
        return
    for result in (env.publish(), env.preserve("PRESERVE_STAGING")):
        assert (result.status, result.code) == (pb.ExportStatus.HELD, pb.EVIDENCE_STAGING_RESIDUE), phase   # 公開 ・保存の全てで HOLD
        assert result.failure_evidence == pb.FAILURE_NOT_RECORDED and result.failure_residue == 1
    again = _failing_run(env, old)
    assert (again.status, again.failure_evidence) == (pb.ExportStatus.REFUSED, pb.FAILURE_NOT_RECORDED)   # 残りの横に新しい証拠は書かない
    assert _failure_temps(env) == temps and not any((env.projection / ps.FAILURES_DIRECTORY).iterdir())   # 採らない ・消さない ・移さない
    assert not env.versions() and not any((env.projection / ps.BUNDLES_DIRECTORY).iterdir())          # 公開は何も書かない


@pytest.mark.parametrize("content", ["foreign", "identical", "other_digest"])
def test_a_foreign_or_byte_identical_leftover_failure_temp_is_ambiguous_and_holds(tmp_path: Path, content: str) -> None:
    env = Env(tmp_path, GEN_A)
    old = env.outcome
    env.use(GEN_B)
    expected = pb.failure_record(operation="PUBLISH", stage="SOURCE", code=pb.SOURCE_NOT_PUBLISHED_GENERATION, detail=None,
                                 generation_digest=old.generation_digest, manifest_digest=old.manifest_digest, public_export_digest=None)
    name = f"failure.{'ab' * 32 if content == 'other_digest' else pb._failure_digest(expected)}.tmp"
    temp = env.projection / ps.STAGING_DIRECTORY / name                                              # other_digest: 別の失敗の残り
    temp.write_bytes(b"not a record" if content == "foreign" else expected)                       # 誰が書いたか証明できない
    for result in (_failing_run(env, old), _failing_run(env, old)):
        assert (result.status, result.failure_evidence) == (pb.ExportStatus.REFUSED, pb.FAILURE_NOT_RECORDED)   # 同じ失敗でも採らない
    held = env.publish()
    assert (held.status, held.code, held.failure_evidence) == (pb.ExportStatus.HELD, pb.EVIDENCE_STAGING_RESIDUE, pb.FAILURE_NOT_RECORDED)
    assert temp.read_bytes() == (b"not a record" if content == "foreign" else expected)              # byte 一致でも採らない ・横に書かない
    assert not any((env.projection / ps.FAILURES_DIRECTORY).iterdir()) and not env.versions()


# ================================================ 容量


def _private_need(gen) -> int:
    target = target_of(gen)
    intent = pc.intent_for(target, None)
    bundle = (intent.to_evidence_bytes(), target.public_export.manifest.to_public_bytes(), target.binding.to_evidence_bytes(),
              pb.scan_record(target), pb.source_record(target.binding))
    return 7 * UNIT + sum(ps.storage_units(len(d)) for d in bundle) + UNIT + 2 * UNIT     # 6 つの layout ・lock ＋ bundle ・完了 ・失敗の予備


def _vault_need(gen) -> int:
    target = target_of(gen)
    notes = sum(ps.storage_units(len(d)) for _, d in target.public_export.notes)
    return 2 * UNIT + notes + 3 * UNIT + ps.storage_units(len(target.public_export.pointer_note()))   # generated ・lock ＋ 頂点


@pytest.mark.parametrize("field, exact", [
    ("observation_objects", lambda: len(target_of(GEN_A).public_export.notes) + 5),
    ("vault_export_bytes", lambda: _vault_need(GEN_A)),
    ("private_evidence_bytes", lambda: _private_need(GEN_A)),
])
@pytest.mark.parametrize("offset", [1, 0, -1])
def test_capacity_limits_are_proven_before_the_first_write_one_below_at_and_above(tmp_path: Path, field: str, exact, offset: int) -> None:
    env = Env(tmp_path, GEN_A)
    result = env.publish(limits=pb.ExportLimits(**{field: exact() + offset}))
    if offset >= 0:
        assert result.status is pb.ExportStatus.PUBLISHED, result
    else:
        assert (result.status, result.code) == (pb.ExportStatus.REFUSED, pb.CAPACITY_EXCEEDED)
        assert not env.versions() and not any((env.projection / ps.BUNDLES_DIRECTORY).iterdir())      # 何も書く前に拒む
        assert result.failure_evidence in (pb.FAILURE_RECORDED, pb.FAILURE_NOT_RECORDED)


@pytest.mark.parametrize("limit, ok", [(3, True), (2, True), (1, False)])
def test_retained_versions_accumulate_and_refuse_before_exceeding_without_removing_history(tmp_path: Path, limit: int, ok: bool) -> None:
    env = Env(tmp_path, GEN_A)
    assert env.publish().status is pb.ExportStatus.PUBLISHED
    first = env.versions()
    result = env.use(GEN_B).publish(limits=pb.ExportLimits(retained_versions=limit))
    assert (result.status is pb.ExportStatus.PUBLISHED) is ok
    assert {k: v for k, v in env.versions().items() if k in first} == first                         # 履歴は消さない
    if not ok:
        assert result.code == pb.CAPACITY_EXCEEDED and set(env.versions()) == set(first)


def test_interrupted_residue_counts_toward_the_vault_limit(tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    residue = env.generated / ps.VAULT_INTERRUPTED_DIRECTORY / f"{published_label(GEN_B)}.001.interrupted"
    residue.mkdir(parents=True)
    (residue / f"{published_label(GEN_B)}.md").write_bytes(b"x" * (10 * UNIT))
    overhead = 2 * UNIT + 10 * UNIT
    assert env.publish(limits=pb.ExportLimits(vault_export_bytes=_vault_need(GEN_A) + overhead - 1)).code == pb.CAPACITY_EXCEEDED
    assert env.publish(limits=pb.ExportLimits(vault_export_bytes=_vault_need(GEN_A) + overhead)).status is pb.ExportStatus.PUBLISHED
    assert (residue / f"{published_label(GEN_B)}.md").read_bytes() == b"x" * (10 * UNIT)            # 中断の保存は消さない


@pytest.mark.parametrize("offset, ok", [(1, True), (0, True), (-1, False)])
def test_free_space_must_cover_the_transaction_peak_and_the_margin(monkeypatch, tmp_path: Path, offset: int, ok: bool) -> None:
    env = Env(tmp_path, GEN_A)
    need = (_vault_need(GEN_A) - 2 * UNIT) + (_private_need(GEN_A) - 7 * UNIT) + 512 * MIB
    monkeypatch.setattr(ps, "shutil", FakeShutil(free=need + offset))
    result = env.publish()
    assert (result.status is pb.ExportStatus.PUBLISHED) is ok, result
    if not ok:
        assert result.code == pb.CAPACITY_EXCEEDED and not env.versions()


def test_unknown_or_failing_free_space_refuses_and_reports_that_evidence_could_not_be_written(monkeypatch, tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    monkeypatch.setattr(ps, "shutil", FakeShutil(error=True))
    failing = env.publish()
    monkeypatch.setattr(ps, "shutil", FakeShutil(shape_error=True))
    unknown = env.publish()
    monkeypatch.undo()
    for result in (failing, unknown):
        assert (result.status, result.code) == (pb.ExportStatus.REFUSED, ps.CAPACITY_UNVERIFIED)
        assert result.failure_evidence == pb.FAILURE_NOT_RECORDED                                   # 空きが分からなければ証拠も書かない
    assert not env.versions() and not any((env.projection / ps.FAILURES_DIRECTORY).iterdir())


# ================================================ 改竄 ・証拠 ・隔離


@pytest.mark.parametrize("tamper, code", [
    (lambda e: (e.generated / ps.POINTER_NOTE_NAME).unlink(), pc.POINTER_MISSING),
    (lambda e: (e.generated / ps.POINTER_NOTE_NAME).write_bytes(b"edited\n"), pc.POINTER_INVALID),
    (lambda e: next((e.generated / published_label(GEN_A)).glob("*-s001.md")).write_bytes(b"edited\n"), pc.VERSION_UNVERIFIED),
    (lambda e: next((e.generated / published_label(GEN_A)).glob("*-s001.md")).unlink(), pc.VERSION_UNVERIFIED),
    (lambda e: next((e.projection / ps.BUNDLES_DIRECTORY).glob("*/scan.json")).write_bytes(b"{}\n"), pb.SCAN_EVIDENCE_INVALID),
    (lambda e: next((e.projection / ps.BUNDLES_DIRECTORY).glob("*/source.json")).write_bytes(b"{}\n"), pb.SOURCE_EVIDENCE_INVALID),
    (lambda e: next((e.projection / ps.BUNDLES_DIRECTORY).glob("*/intent.json")).write_bytes(b"{"), pc.RECORD_CORRUPT),
    (lambda e: next((e.projection / ps.BUNDLES_DIRECTORY).glob("*/binding.json")).unlink(), pb.EVIDENCE_INVALID),
    (lambda e: next((e.projection / ps.COMPLETIONS_DIRECTORY).glob("*.json")).write_bytes(b"{}\n"), pc.RECORD_CORRUPT),
    (lambda e: (e.projection / ps.FAILURES_DIRECTORY / f"{'ab' * 32}.json").write_bytes(b"{}\n"), pb.FAILURE_EVIDENCE_INVALID),
])
def test_edited_or_deleted_published_output_and_tampered_evidence_hold_and_nothing_is_repaired(tmp_path: Path, tamper, code) -> None:
    env = Env(tmp_path, GEN_A)
    env.publish()
    tamper(env)
    vault, evidence = {k: v[0] for k, v in tree(env.vault).items()}, env.evidence()
    result = env.use(GEN_B).publish()
    assert (result.status, result.code) == (pb.ExportStatus.HELD, code)
    assert {k: v[0] for k, v in tree(env.vault).items()} == vault                                   # 修復 ・再公開 ・削除はしない
    assert {k: v for k, v in env.evidence().items() if not k.startswith(ps.FAILURES_DIRECTORY)} == {
        k: v for k, v in evidence.items() if not k.startswith(ps.FAILURES_DIRECTORY)}


def test_failure_evidence_is_private_deduplicated_and_holds_only_codes_and_requested_digests(tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    old = env.outcome
    env.use(GEN_B)
    for _ in range(2):
        result = env.publish(generation_digest=old.generation_digest, manifest_digest=old.manifest_digest)
    assert result.failure_evidence == pb.FAILURE_ALREADY_RECORDED                                   # 同じ失敗は同じ byte（時刻は無い）
    records = list((env.projection / ps.FAILURES_DIRECTORY).iterdir())
    assert len(records) == 1
    value = json.loads(records[0].read_bytes())
    assert value == {"schema_version": pb.FAILURE_SCHEMA_VERSION, "operation": "PUBLISH", "stage": "SOURCE",
                     "code": pb.SOURCE_NOT_PUBLISHED_GENERATION, "detail": None, "requested_generation_digest": old.generation_digest,
                     "requested_manifest_digest": old.manifest_digest, "public_export_digest": None,
                     "authority_class": pb.FAILURE_AUTHORITY_CLASS}
    assert not any(env.generated.iterdir())                                                         # 失敗は generated/ に触れない
    full = Env(tmp_path / "full", GEN_A)
    result = full.publish(limits=pb.ExportLimits(private_evidence_bytes=8 * UNIT))
    assert (result.code, result.failure_evidence) == (pb.CAPACITY_EXCEEDED, pb.FAILURE_NOT_RECORDED)  # 書けなければ書けないと報告


def test_human_notes_and_obsidian_files_are_never_read_listed_or_changed(monkeypatch, tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    before = {relative: ((env.vault / relative).read_bytes(), (env.vault / relative).stat().st_mtime_ns) for relative in HUMAN_FILES}
    proxy = inject(monkeypatch)
    env.publish()
    env.use(GEN_B).publish()
    monkeypatch.undo()
    assert {relative: ((env.vault / relative).read_bytes(), (env.vault / relative).stat().st_mtime_ns) for relative in HUMAN_FILES} == before
    human = [str(env.vault / relative) for relative in HUMAN_FILES] + [str(env.vault / "notes")]
    assert not any(location.startswith(h) for _, location in proxy.calls for h in human)            # 人の file は lstat もしない
    assert str(env.vault) not in {location for op, location in proxy.calls if op == "listdir"}
    generated, projection = str(env.generated), str(env.projection)
    assert all(location.startswith((generated, projection)) for op, location in proxy.calls if op in MUTATIONS)


def test_results_hold_no_locations_or_private_digests(tmp_path: Path) -> None:
    env = Env(tmp_path, GEN_A)
    results = [env.publish(), env.publish(), env.use(GEN_A_TWIN).publish()]
    for result in results:
        text = repr(result)
        assert str(env.base) not in text
        for digest in private_digests(GEN_A) + private_digests(GEN_A_TWIN):
            assert digest[:16] not in text
    assert results[0].public_export_digest == target_of(GEN_A).public_export_digest
