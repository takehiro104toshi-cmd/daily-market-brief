"""P13-A4a1 — 後継の投影の契約の試験（合成の値だけ ・file ・vault ・network ・時計は使わない）。

public の identity が公開の欄だけから導かれること（private な digest ・その接頭が public の byte ・名前 ・link に無い ・cutoff の瞬間 ・項目の id
を変えても public の byte は不変 ・note だけから public の digest を再計算できる）、frontmatter の完全な形、公開が同じなら NO_CHANGE で
private な binding は別に残ること、中断した staging の継続 ・明示の保存 ・HOLD、前の版の保持を固定する。A4b の I/O の効果は試験の中の
純粋な写像の更新（`apply`）で模擬する。
"""
from __future__ import annotations

import builtins
import dataclasses
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import time
from datetime import timedelta

import pytest

from src.intelligence.market_memory import memory_generation as mg
from src.intelligence.market_memory import memory_projection as a4a
from src.intelligence.market_memory import projection_contract as pc
from src.intelligence.market_memory.canonical import domain_digest
from src.intelligence.market_memory.review_state_sample import (PROVENANCE_CLASS, SAMPLE_DOMAIN, AttentionMark, OutcomeStatus,
                                                                SampleCutoff, build_sample)
from tests.intelligence.test_market_memory_model import VIEW, cutoff, make_counts, watch

ADAPTER = "p13_governed_review_source:0.1.0"
#: 合成の fixture の public な identity（描画の byte が変われば規則の version を上げる ・ここで止まる）
GOLDEN_PUBLIC_VERSION_DIGEST = "1ddd17bc8b55b47fc6b241ef5accad452b67b696af1322e58210ce3704beafa6"
GOLDEN_PUBLIC_EXPORT_DIGEST = "54da657e130ddd41e875772f9432f323bac88b9663e9ec84dd7fc81362030361"
ENTRY_VALUES = ("watch-a", "watch-b", "watch-c", "issuer-a", "issuer-b", "issuer-c", "rev-1")
HEX_RUN = re.compile(r"(?<![0-9a-f])[0-9a-f]{16,}(?![0-9a-f])")


def sample_with(cut, roots, *, mute_b=False, extra=False, lookahead=7, empty=False):
    entries = [] if empty else [watch(roots[0], roots[0].replace("watch", "issuer"), attention=AttentionMark.FOCUS),
                                watch(roots[1], roots[1].replace("watch", "issuer"),
                                      attention=AttentionMark.MUTE if mute_b else AttentionMark.NORMAL)]
    if extra and not empty:
        entries.append(watch(roots[2], roots[2].replace("watch", "issuer")))
    outcome = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=make_counts(entries, cut, lookahead=lookahead),
                           rules_version=ADAPTER)
    assert outcome.status is OutcomeStatus.SAMPLED, outcome.failure_code
    return outcome.sample


def variant(*, hour=0, roots=("watch-a", "watch-b", "watch-c"), lookahead=7, days=(10, 11, 12), empty=False, extra_at=2):
    plan = tuple(cutoff(day, hour) for day in days)
    samples = [sample_with(c, roots, mute_b=i >= 1, extra=i >= extra_at, lookahead=lookahead, empty=empty) for i, c in enumerate(plan)]
    return mg.build_generation(plan, VIEW, adapter_rules_version=ADAPTER, samples=samples)


def verified_of(gen):
    return mg.verify_generation_records({**gen.records(), mg.MANIFEST_RECORD_NAME: gen.manifest().to_bytes()},
                                        expected_generation_digest=gen.generation_digest)


def target_of(gen) -> pc.ProjectionTarget:
    verified = verified_of(gen)
    return pc.build_projection_target(verified, generation_digest=verified.generation_digest, manifest_digest=verified.manifest_digest)


GEN_A, GEN_B, GEN_C = variant(), variant(days=(10, 11, 12, 13)), variant(extra_at=1)
TARGET_A, TARGET_B, TARGET_C = target_of(GEN_A), target_of(GEN_B), target_of(GEN_C)
GEN_A_TWIN = variant(hour=9, roots=("watch-x", "watch-y", "watch-z"), lookahead=3)       # 公開の欄が同じ ・瞬間 ・項目 ・窓が違う
TARGET_A_TWIN = target_of(GEN_A_TWIN)


def code_of(call, *args, **kwargs) -> str:
    with pytest.raises(a4a.ProjectionError) as exc:
        call(*args, **kwargs)
    assert exc.value.code in pc.CONTRACT_CODES, exc.value.code
    return exc.value.code


def observe(**groups) -> pc.PublicationObservation:
    return pc.PublicationObservation(**groups)


def apply(observation: pc.PublicationObservation, plan: pc.TransitionPlan) -> pc.PublicationObservation:
    """A4b の I/O の効果の純粋な模擬（追加 ・pointer の置換 ・開いた intent の staging の移動 ・明示の保存だけ。削除 ・上書きは無い）。"""
    versions = {k: dict(v) for k, v in observation.versions.items()}
    staging = {k: dict(v) for k, v in observation.staging.items()}
    groups = {pc.EVIDENCE_PUBLIC_EXPORT: dict(observation.public_exports), pc.EVIDENCE_PRIVATE_BINDING: dict(observation.private_bindings),
              pc.EVIDENCE_INTENT: dict(observation.intents), pc.EVIDENCE_COMPLETION: dict(observation.completions),
              pc.EVIDENCE_ABORT: dict(observation.aborts)}
    pointer = observation.pointer
    A = pc.ProposedAction
    if plan.action in (A.PREPARE_INTENT, A.RECORD_COMPLETION, A.RECORD_PRIVATE_BINDING):
        for kind, digest, data in plan.evidence:
            assert digest not in groups[kind]                                      # 証拠は追加だけ
            groups[kind][digest] = data
    elif plan.action is A.STAGE_VERSION:
        assert plan.version_label not in staging and plan.version_label not in versions
        staging[plan.version_label] = dict(plan.staged_notes)
    elif plan.action is A.CONTINUE_STAGING:
        assert set(plan.existing_notes) == set(staging[plan.version_label])
        for name, data in plan.staged_notes:
            assert name not in staging[plan.version_label]                         # 足りない file の排他の作成だけ
            staging[plan.version_label][name] = data
    elif plan.action is A.MOVE_STAGED_TO_VERSION:
        assert plan.version_label not in versions                                  # 置き換えない移動
        versions[plan.version_label] = staging.pop(plan.version_label)
    elif plan.action is A.REPLACE_POINTER:
        assert pointer == plan.expected_pointer
        pointer = plan.replacement_pointer
    elif plan.action is A.PRESERVE_STAGING:
        staging.pop(plan.preserve_label)                                           # A4b は interrupted の場所へ移す（観測の外）
    elif plan.action is A.PRESERVE_EMPTY_RESERVATION:
        assert versions.pop(plan.preserve_label) == {}
    else:
        raise AssertionError(plan.action)
    return pc.PublicationObservation(pointer=pointer, versions=versions, staging=staging,
                                     public_exports=groups[pc.EVIDENCE_PUBLIC_EXPORT],
                                     private_bindings=groups[pc.EVIDENCE_PRIVATE_BINDING], intents=groups[pc.EVIDENCE_INTENT],
                                     completions=groups[pc.EVIDENCE_COMPLETION], aborts=groups[pc.EVIDENCE_ABORT])


def drive(observation, target):
    before = dict(observation.versions)
    states = []
    for _ in range(10):
        result = pc.classify_publication(observation, target=target)
        states.append((result.state, result.action, result.recovery))
        assert set(before) <= set(result.retained_versions)
        if result.action is pc.ProposedAction.NONE:
            return observation, result, states
        assert result.action is not pc.ProposedAction.HOLD, result.code
        if result.recovery is pc.RecoveryEligibility.AUTO_CONVERGE_ELIGIBLE:
            assert pc.check_recovery_proposal(observation, result.action, target=target) == result.transition
        observation = apply(observation, result.transition)
        for label, notes in before.items():
            assert observation.versions[label] == notes                          # 前の版の byte は不変
    raise AssertionError("did not converge")


def prepared(base, target, steps):
    observation = base
    for _ in range(steps):
        observation = apply(observation, pc.classify_publication(observation, target=target).transition)
    return observation


def classify_code(observation, target=None) -> str:
    result = pc.classify_publication(observation, target=target)
    assert result.state is pc.PublicationState.FAIL_CLOSED and result.action is pc.ProposedAction.HOLD
    assert result.recovery is pc.RecoveryEligibility.HOLD_FAIL_CLOSED and result.transition is None
    return result.code


PUBLISHED_A = drive(observe(), TARGET_A)[0]
PUBLISHED_AB = drive(PUBLISHED_A, TARGET_B)[0]


def public_surface(target: pc.ProjectionTarget) -> str:
    """public な面の全て: note の byte ・file 名 ・link ・pointer ・public な manifest の byte。"""
    export = target.public_export
    parts = [data.decode("utf-8") for _, data in export.notes] + [name for name, _ in export.notes]
    parts += [export.pointer_note().decode("utf-8"), export.manifest.to_public_bytes().decode("utf-8"), export.version_label]
    return "\n".join(parts)


def private_digests(gen, target) -> set:
    legacy = a4a.render_projection(a4a.build_projection_input(verified_of(gen), generation_digest=gen.generation_digest,
                                                              manifest_digest=gen.manifest().manifest_digest))
    found = {gen.generation_digest, gen.plan_digest, gen.manifest().manifest_digest, target.binding.binding_digest,
             legacy.manifest.projection_digest, legacy.export_digest}
    found |= {s.sample_digest for s in gen.samples} | {c.change_digest for c in gen.changes}
    found |= {a4a.interval_digest(x.sample_digest, y.sample_digest) for x, y in zip(gen.samples, gen.samples[1:])}
    found |= {mg.sha256_hex(data) for data in gen.records().values()}
    return found


# ================================================ 再利用の面 ・語彙


def test_reuse_from_the_frozen_a4a_is_limited_to_unchanged_constants_text_scanner_and_error_class() -> None:
    assert pc.ProjectionError is a4a.ProjectionError
    assert pc.scan_private_shapes is a4a.scan_private_shapes
    assert pc.APPROVED_CATEGORY_CODES is a4a.APPROVED_CATEGORY_CODES
    assert set(pc.ProposedAction.__members__) == {"NONE", "PREPARE_INTENT", "RECORD_PRIVATE_BINDING", "STAGE_VERSION", "CONTINUE_STAGING",
                                                  "MOVE_STAGED_TO_VERSION", "REPLACE_POINTER", "RECORD_COMPLETION", "PRESERVE_STAGING",
                                                  "PRESERVE_EMPTY_RESERVATION", "HOLD"}
    for word in ("ARCHIVE", "DELETE", "REMOVE", "PRUNE", "CLEAN", "RETENTION", "RELOCATE", "PREVIOUS", "REPAIR", "OVERWRITE"):
        assert not any(word in name for name in pc.ProposedAction.__members__), word
    assert pc.EXPLICIT_PRESERVATION_ACTIONS == (pc.ProposedAction.PRESERVE_STAGING, pc.ProposedAction.PRESERVE_EMPTY_RESERVATION)
    assert not set(pc.EXPLICIT_PRESERVATION_ACTIONS) & set(pc.AUTO_CONVERGE_ACTIONS)                      # 保存は決して自動ではない
    assert {f.name for f in dataclasses.fields(pc.TransitionPlan)} == {
        "action", "intent_digest", "version_label", "evidence", "staged_notes", "existing_notes", "preserve_area", "preserve_label",
        "expected_pointer", "replacement_pointer", "retained_versions"}
    public_fields = {f.name for cls in (pc.PublicSample, pc.PublicInterval, pc.PublicVersion, pc.PublicExportManifest, pc.PublicFile)
                     for f in dataclasses.fields(cls)}
    assert not {name for name in public_fields if "private" in name or "generation" in name or "binding" in name or "sample_digest" in name}
    assert {f.name for f in dataclasses.fields(pc.PrivateBinding)} >= {"private_generation_digest", "private_source_manifest_digest"}
    assert not hasattr(pc.PrivateBinding, "to_public_bytes") and not hasattr(pc.PublicExportManifest, "to_evidence_bytes")


def test_the_source_input_requires_explicit_full_digests_and_rechecks_the_records() -> None:
    verified = verified_of(GEN_A)
    with pytest.raises(TypeError):
        pc.build_projection_target(verified)                                       # 既定 ・「最新」は無い
    assert code_of(pc.build_projection_target, verified, generation_digest=GEN_A.generation_id,
                   manifest_digest=verified.manifest_digest) == pc.PROJECTION_INPUT_INVALID
    other = verified_of(GEN_C)
    assert code_of(pc.build_projection_target, verified, generation_digest=verified.generation_digest,
                   manifest_digest=other.manifest_digest) == pc.SOURCE_DIGEST_MISMATCH
    forged = mg.VerifiedGeneration(generation=verified.generation, manifest=other.manifest)
    assert code_of(pc.build_projection_target, forged, generation_digest=verified.generation_digest,
                   manifest_digest=other.manifest_digest) == pc.SOURCE_UNVERIFIED
    source = pc.PrivateSourceInput(verified=verified, generation_digest=verified.generation_digest, manifest_digest=verified.manifest_digest)
    assert source.source_attestation == "A4A1_RECHECKED_RECORD_BYTES_STORE_READ_NOT_ATTESTED" and source.verified is not verified
    assert verified.generation_digest not in repr(source) and verified.generation_digest not in repr(TARGET_A)


# ================================================ frontmatter ・counts-only ・日付の意味


def test_every_note_kind_has_the_exact_quoted_frontmatter_with_honest_identities_and_dates() -> None:
    export = TARGET_A.public_export
    digest = export.manifest.public_version_digest
    notes = export.note_map()
    common = ['generated: "true"', 'authority: "DERIVED"', None, f'build_id: "{digest}"',
              'p13_build_basis: "PUBLIC_EXPORT_BUILD_IDENTITY_PRIVATE_MEMORY_BUILD_WITHHELD"', None, None, 'known_at: "NOT_AVAILABLE"',
              'acquisition_time: "NOT_AVAILABLE"', f'p13_provenance: "{PROVENANCE_CLASS}"', 'p13_source_ref: "PRIVATE_EVIDENCE_ONLY"']

    def head(data):
        lines = data.decode("utf-8").split("\n")
        return lines[1:lines.index("---", 1)]

    cases = ((export.version_label + ".md", "VERSION_INDEX", "p13pvn_", 0, "2026-01-12", "GENERATION_FINAL_CUTOFF_AS_OF_DATE", []),
             (export.version_label + "-s002.md", "SAMPLE", "p13psm_", 2, "2026-01-11", "SAMPLE_CUTOFF_AS_OF_DATE", ['p13_ordinal: "002"']),
             (export.version_label + "-i002.md", "INTERVAL", "p13piv_", 2, "2026-01-12",
              "INTERVAL_THROUGH_CUTOFF_AS_OF_DATE_NOT_TRANSITION_TIME", ['p13_ordinal: "002"']))
    for name, kind, prefix, ordinal, as_of, basis, extra in cases:
        expected = [f'p13_schema: "{pc.CONTRACT_SCHEMA_VERSION}"', f'p13_rules: "{pc.CONTRACT_RULES_VERSION}"', f'p13_note: "{kind}"']
        filled = list(common)
        filled[2] = f'item_id: "{prefix}{pc.public_note_identity(digest, kind, ordinal)}"'
        filled[5], filled[6] = f'as_of: "{as_of}"', f'p13_as_of_basis: "{basis}"'
        assert head(notes[name]) == expected + filled + extra, name
    pointer = head(export.pointer_note())
    assert pointer[0] == f'p13_schema: "{pc.POINTER_SCHEMA_VERSION}"' and pointer[2] == 'p13_note: "POINTER"'
    assert pointer[5] == f'item_id: "p13ptr_{pc.pointer_slot_identity()}"' and pointer[-1] == f'p13_export: "{export.public_export_digest}"'
    assert pc.pointer_slot_identity() == target_of(GEN_B).public_export.pointer_note().decode().split('item_id: "p13ptr_')[1][:64]  # slot は定数
    for name, data in notes.items():
        text = data.decode("utf-8")
        assert "known_at（source が知られた時刻）ではない" in text and pc.SOURCE_NOTICE in text
        for value in ENTRY_VALUES:
            assert value not in text, (name, value)                                 # 項目の id ・発行体 ・revision は出ない
        assert "T00:00" not in text and "+00:00" not in text                        # 瞬間は出ない（日だけ）
        assert not re.search(r'^[a-z_0-9]+: [^"]', text, re.MULTILINE)              # 全ての frontmatter の値は quote


def test_public_output_contains_no_private_digest_or_prefix_anywhere() -> None:
    for gen, target in ((GEN_A, TARGET_A), (GEN_B, TARGET_B), (GEN_C, TARGET_C), (GEN_A_TWIN, TARGET_A_TWIN)):
        surface = public_surface(target)
        for digest in private_digests(gen, target):
            for start in range(0, 64 - 16 + 1):
                assert digest[start:start + 16] not in surface, start              # 完全な digest も 16 hex 以上の部分列も無い
        public = {target.public_export.manifest.public_version_digest, target.public_export_digest, pc.pointer_slot_identity()}
        public |= {pc.public_note_identity(target.public_export.manifest.public_version_digest, k, n)
                   for k, n in [("VERSION_INDEX", 0)] + [("SAMPLE", i) for i in range(1, 6)] + [("INTERVAL", i) for i in range(1, 6)]}
        for run in HEX_RUN.findall(surface):                                        # 正の検査: 全ての hex の列は public な値だけ
            assert any(run == p or run == p[:24] for p in public) or run in {f.sha256 for f in target.public_export.manifest.files}, run


def test_public_identities_are_recomputable_from_public_fields_alone() -> None:
    export = TARGET_A.public_export
    rebuilt = pc.parse_public_version(export.note_map())                           # note だけから
    assert rebuilt == export.public_version and pc.render_public_export(rebuilt).notes == export.notes
    canonical = json.dumps(rebuilt.content(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(("p13.projection_public_version.v2\0" + canonical).encode("utf-8")).hexdigest() == \
        export.manifest.public_version_digest
    manifest = json.dumps(export.manifest.content(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(("p13.projection_public_export.v2\0" + manifest).encode("utf-8")).hexdigest() == export.public_export_digest
    assert export.manifest.public_version_digest == GOLDEN_PUBLIC_VERSION_DIGEST and export.public_export_digest == GOLDEN_PUBLIC_EXPORT_DIGEST
    content = rebuilt.content()
    assert set(content) == {"schema_version", "rules_version", "authority_class", "adapter_rules_version", "view_versions", "samples",
                            "intervals"}
    assert {k for s in content["samples"] for k in s} == {"ordinal", "as_of_date", "active_profile_present", "review_counts", "p9_counts",
                                                          "category_counts"}                       # 公開の欄だけ
    assert pc.verify_public_version(export.note_map(), export.manifest) == rebuilt


# ================================================ 攻撃の回帰（候補の列挙 ・項目の推論）


def test_cutoff_instant_window_and_entry_ids_cannot_be_recovered_by_public_digest_candidate_matching() -> None:
    assert TARGET_A_TWIN.public_export.notes == TARGET_A.public_export.notes                                   # 公開は byte 一致
    assert TARGET_A_TWIN.public_export_digest == TARGET_A.public_export_digest
    assert TARGET_A_TWIN.binding.binding_digest != TARGET_A.binding.binding_digest                            # private な provenance は別
    assert GEN_A_TWIN.generation_digest != GEN_A.generation_digest
    empty = variant(empty=True, hour=6, lookahead=7)
    surface = public_surface(target_of(empty))
    runs = set(HEX_RUN.findall(surface))
    candidates_tried, matched = 0, 0
    base = SampleCutoff(at=cutoff(9, 12).at, as_of_date=cutoff(10).as_of_date)
    for step in range(0, 36 * 60, 30):                                             # 0.1.0 の攻撃 1 の再現: 瞬間 × 窓の候補
        for window in range(0, 31, 5):
            cut = SampleCutoff(at=base.at + timedelta(minutes=step), as_of_date=base.as_of_date)
            content = sample_with(cut, (), lookahead=window, empty=True).content()
            candidates_tried += 1
            matched += domain_digest(SAMPLE_DOMAIN, content) in runs or domain_digest(SAMPLE_DOMAIN, content)[:24] in runs
    assert candidates_tried > 400 and matched == 0                                 # 照らす相手の digest が public に無い
    outputs = {target_of(variant(empty=True, hour=h, lookahead=w)).public_export_digest for h in (0, 6, 13, 23) for w in (0, 7, 30)}
    assert len(outputs) == 1                                                       # 瞬間 ・窓は public な identity に情報を与えない
    issuers = {target_of(variant(roots=r)).public_export_digest for r in (("watch-a", "watch-b", "watch-c"), ("watch-p", "watch-q", "watch-r"))}
    assert len(issuers) == 1                                                       # 項目 ・発行体の id も同じ


def test_forged_public_digests_and_injected_private_bindings_are_rejected() -> None:
    export = TARGET_A.public_export
    name = export.version_label + "-s001.md"
    data = export.note_map()[name]
    digest = export.manifest.public_version_digest
    fake = "ab" * 32 if digest != "ab" * 32 else "cd" * 32
    item = 'item_id: "p13psm_' + pc.public_note_identity(digest, "SAMPLE", 1)
    for old, new, code in ((item, 'item_id: "p13psm_' + fake, pc.PUBLIC_DIGEST_INVALID),
                           (f'build_id: "{digest}"', f'build_id: "{fake}"', pc.PUBLIC_DIGEST_INVALID),
                           ('p13_source_ref: "PRIVATE_EVIDENCE_ONLY"', f'p13_source_ref: "{GEN_A.generation_digest}"', pc.NOTE_INVALID)):
        assert code_of(pc.validate_public_note, data.replace(old.encode(), new.encode(), 1)) == code, old
    for leak in (GEN_A.generation_digest, GEN_A.samples[0].sample_digest, TARGET_A.binding.binding_digest, GEN_A.samples[0].sample_digest[:24]):
        injected = data[:-1] + f"\n| sample_cutoff_date | {leak} |\n".encode()
        assert code_of(pc.validate_public_note, injected) in (pc.PUBLIC_DIGEST_INVALID, pc.NOTE_INVALID), leak   # 64 hex ／ 24 hex の接頭
    index = export.note_map()[export.version_label + ".md"]
    smuggled = index.replace(f"| adapter_rules | {ADAPTER} |".encode(), b"| adapter_rules | p" + GEN_A.generation_digest[:20].encode()
                             + b"x:0.1.0 |")                                       # version の形の cell に private な hex の列
    assert smuggled != index and code_of(pc.validate_public_note, smuggled) == pc.PUBLIC_DIGEST_INVALID     # 正の hex の検査だけが捕まえる
    swapped = index.replace(f"| public_version_digest | {digest} |".encode(), f"| public_version_digest | {GEN_A.generation_digest} |".encode())
    assert code_of(pc.validate_public_note, swapped) == pc.PUBLIC_DIGEST_INVALID
    tampered = dict(export.note_map())
    tampered[name] = data.replace(b"| live_focus_marks | 1 |", b"| live_focus_marks | 2 |")
    assert code_of(pc.parse_public_version, tampered) == pc.PUBLIC_DIGEST_INVALID                              # 再描画の不一致
    assert "private_generation_digest" not in public_surface(TARGET_A)
    assert TARGET_A.binding.to_evidence_bytes().decode().count(GEN_A.generation_digest) == 1                    # private な面にだけ在る


def test_wrong_frontmatter_types_keys_values_and_unsupported_legacy_artifacts_are_rejected() -> None:
    export = TARGET_A.public_export
    data = export.note_map()[export.version_label + "-s001.md"]
    for old, new, detail in ((b'generated: "true"', b"generated: true", "FRONTMATTER_LINE"),
                             (b'generated: "true"', b'generated: "yes"', "FRONTMATTER_VALUE"),
                             (b'as_of: "2026-01-10"', b'as_of: "2026-01-10T06:00"', "PRIVATE"),
                             (b'as_of: "2026-01-10"', b'as_of: "2026-02-30"', "FRONTMATTER_VALUE"),
                             (b'known_at: "NOT_AVAILABLE"', b'known_at: "2026-01-10"', "FRONTMATTER_VALUE"),
                             (b'p13_as_of_basis: "SAMPLE_CUTOFF_AS_OF_DATE"', b'p13_as_of_basis: "SOURCE_KNOWN_AT"', "FRONTMATTER_VALUE"),
                             (b'acquisition_time: "NOT_AVAILABLE"\n', b"", "FRONTMATTER_KEYS"),
                             (b'p13_ordinal: "001"', b'p13_ordinal: "001"\nextra_key: "x"', "FRONTMATTER_KEYS"),
                             (b'authority: "DERIVED"\n', b"", "FRONTMATTER_KEYS")):
        mutated = data.replace(old, new, 1)
        assert mutated != data, old
        with pytest.raises(a4a.ProjectionError) as exc:
            pc.validate_public_note(mutated)
        assert exc.value.detail == detail or (detail == "PRIVATE" and exc.value.code == pc.PRIVATE_SHAPE_DETECTED), (old, exc.value.detail)
    swapped = data.replace(b'generated: "true"\nauthority: "DERIVED"', b'authority: "DERIVED"\ngenerated: "true"')
    assert code_of(pc.validate_public_note, swapped) == pc.NOTE_INVALID                                         # 順序つきの完全一致
    legacy = a4a.render_projection(a4a.build_projection_input(verified_of(GEN_A), generation_digest=GEN_A.generation_digest,
                                                              manifest_digest=GEN_A.manifest().manifest_digest))
    for _, note in legacy.notes:
        assert code_of(pc.validate_public_note, note) in (pc.NOTE_INVALID, pc.PUBLIC_DIGEST_INVALID)            # 0.1.0 の note は受けない
    assert code_of(pc.parse_pointer, legacy.pointer_note()) == pc.POINTER_INVALID
    assert code_of(pc.parse_public_export_manifest, legacy.manifest.to_bytes()) == pc.SCHEMA_UNSUPPORTED
    assert code_of(pc.parse_public_version, legacy.note_map()) == pc.NOTE_INVALID
    for parse, record in ((pc.parse_private_binding, TARGET_A.binding.to_evidence_bytes()),
                          (pc.parse_public_export_manifest, export.manifest.to_public_bytes())):
        value = json.loads(record)
        value["schema_version"] = value["schema_version"].replace("0.2.0", "0.1.0")
        assert code_of(parse, mg.record_bytes(value)) == pc.SCHEMA_UNSUPPORTED
        assert code_of(parse, record + b" ") == pc.RECORD_CORRUPT


def test_determinism_is_byte_identical_across_order_timezone_and_working_directory(monkeypatch, tmp_path) -> None:
    again = target_of(variant())
    assert again.public_export.notes == TARGET_A.public_export.notes and again.binding == TARGET_A.binding
    shuffled = dict(reversed(list({**GEN_A.records(), mg.MANIFEST_RECORD_NAME: GEN_A.manifest().to_bytes()}.items())))
    verified = mg.verify_generation_records(shuffled, expected_generation_digest=GEN_A.generation_digest)
    assert pc.build_projection_target(verified, generation_digest=verified.generation_digest,
                                      manifest_digest=verified.manifest_digest).public_export.notes == TARGET_A.public_export.notes
    with monkeypatch.context() as patch:
        patch.setenv("TZ", "Pacific/Kiritimati")
        time.tzset()
        patch.chdir(tmp_path)
        assert target_of(variant()).public_export.notes == TARGET_A.public_export.notes
    time.tzset()
    assert list(tmp_path.iterdir()) == []


def test_malformed_categories_and_out_of_range_counts_fail_closed() -> None:
    def single(entries, **counts):
        cut = cutoff(10)
        outcome = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=make_counts(entries, cut, **counts), rules_version=ADAPTER)
        gen = mg.build_generation((cut,), VIEW, adapter_rules_version=ADAPTER, samples=[outcome.sample])
        return verified_of(gen), gen
    for entries, counts, code in (([watch("watch-a", "issuer-a", status="ARCHIVED")], {}, pc.CATEGORY_UNAPPROVED),
                                  ([watch("watch-a", "issuer-a")], {"cleared": 10000}, pc.COUNT_OUT_OF_RANGE)):
        verified, gen = single(entries, **counts)
        assert code_of(pc.build_projection_target, verified, generation_digest=gen.generation_digest,
                       manifest_digest=verified.manifest_digest) == code
    verified, gen = single([watch("watch-a", "issuer-a")])
    one = pc.build_projection_target(verified, generation_digest=gen.generation_digest, manifest_digest=verified.manifest_digest)
    assert a4a.NO_INTERVALS_LINE.encode() in one.public_export.note_map()[one.version_label + ".md"]


# ================================================ 公開の状態の分類 ・NO_CHANGE と private な provenance


def test_first_publication_and_a_second_version_keep_the_previous_version_immutable() -> None:
    observation, final, states = drive(observe(), TARGET_A)
    S, A, R = pc.PublicationState, pc.ProposedAction, pc.RecoveryEligibility
    assert states == [(S.FIRST_PUBLICATION, A.PREPARE_INTENT, R.NOT_REQUIRED), (S.INTENT_PREPARED, A.STAGE_VERSION, R.AUTO_CONVERGE_ELIGIBLE),
                      (S.STAGED_VERIFIED, A.MOVE_STAGED_TO_VERSION, R.AUTO_CONVERGE_ELIGIBLE),
                      (S.VERSION_VERIFIED, A.REPLACE_POINTER, R.AUTO_CONVERGE_ELIGIBLE),
                      (S.POINTER_SWITCHED, A.RECORD_COMPLETION, R.AUTO_CONVERGE_ELIGIBLE), (S.NO_CHANGE, A.NONE, R.NOT_REQUIRED)]
    assert final.target_binding_recorded is True and final.code == "NO_CHANGE"
    second, done, _ = drive(PUBLISHED_A, TARGET_B)
    assert done.completed_intent_count == 2 and second.versions[TARGET_A.version_label] == TARGET_A.public_export.note_map()
    assert second.pointer == TARGET_B.public_export.pointer_note()
    assert pc.classify_publication(PUBLISHED_AB, target=TARGET_A).code == pc.REPUBLICATION_OF_KNOWN_VERSION


def test_public_identical_inputs_yield_no_change_and_record_the_distinct_private_binding() -> None:
    result = pc.classify_publication(PUBLISHED_A, target=TARGET_A_TWIN)
    assert (result.state, result.action, result.code) == (pc.PublicationState.NO_CHANGE, pc.ProposedAction.RECORD_PRIVATE_BINDING,
                                                          pc.NO_CHANGE_BINDING_UNRECORDED)
    assert result.target_binding_recorded is False                                 # provenance が同じとは主張しない
    plan = result.transition
    assert plan.evidence == ((pc.EVIDENCE_PRIVATE_BINDING, TARGET_A_TWIN.binding.binding_digest, TARGET_A_TWIN.binding.to_evidence_bytes()),)
    recorded = apply(PUBLISHED_A, plan)
    after = pc.classify_publication(recorded, target=TARGET_A_TWIN)
    assert (after.state, after.action, after.target_binding_recorded) == (pc.PublicationState.NO_CHANGE, pc.ProposedAction.NONE, True)
    assert recorded.versions == PUBLISHED_A.versions and recorded.pointer == PUBLISHED_A.pointer           # vault は不変
    assert len(recorded.private_bindings) == 2                                     # 2 つの provenance が両方残る
    assert pc.classify_publication(recorded, target=TARGET_A).target_binding_recorded is True
    stray = pc.PrivateBinding(public_version_digest=TARGET_B.binding.public_version_digest,
                              public_export_digest=TARGET_B.public_export_digest,
                              private_generation_digest=GEN_B.generation_digest, private_source_manifest_digest="e" * 64)
    unreferenced = dataclasses.replace(PUBLISHED_A, private_bindings={**PUBLISHED_A.private_bindings,
                                                                      stray.binding_digest: stray.to_evidence_bytes()})
    assert classify_code(unreferenced) == pc.UNREFERENCED_BINDING                  # 公開していない版への binding は受けない


def test_classification_is_deterministic_across_input_ordering() -> None:
    for steps in range(5):
        observation = prepared(PUBLISHED_A, TARGET_B, steps)
        reordered = pc.PublicationObservation(
            pointer=observation.pointer, versions={k: dict(reversed(list(v.items()))) for k, v in reversed(list(observation.versions.items()))},
            staging={k: dict(reversed(list(v.items()))) for k, v in observation.staging.items()},
            public_exports=dict(reversed(list(observation.public_exports.items()))),
            private_bindings=dict(reversed(list(observation.private_bindings.items()))),
            intents=dict(reversed(list(observation.intents.items()))), completions=dict(observation.completions), aborts={})
        assert pc.classify_publication(reordered, target=TARGET_B) == pc.classify_publication(observation, target=TARGET_B)


# ================================================ 中断の staging ・明示の保存 ・HOLD


def test_verified_partial_staging_continues_by_creating_only_the_missing_files() -> None:
    staged = prepared(PUBLISHED_A, TARGET_B, 2)
    label = TARGET_B.version_label
    full = staged.staging[label]
    names = sorted(full)
    for keep in ([], names[:1], names[:3], names[:-1]):
        partial = dataclasses.replace(staged, staging={label: {n: full[n] for n in keep}})
        result = pc.classify_publication(partial, target=TARGET_B)
        assert (result.state, result.action, result.recovery) == (pc.PublicationState.STAGING_PARTIAL_VERIFIED,
                                                                  pc.ProposedAction.CONTINUE_STAGING, pc.RecoveryEligibility.AUTO_CONVERGE_ELIGIBLE)
        assert result.transition.existing_notes == tuple(keep)
        assert {n for n, _ in result.transition.staged_notes} == set(names) - set(keep)          # 足りない file だけ
        continued = apply(partial, pc.check_recovery_proposal(partial, "CONTINUE_STAGING", target=TARGET_B))
        assert pc.classify_publication(continued, target=TARGET_B).state is pc.PublicationState.STAGED_VERIFIED
        held = pc.classify_publication(partial)
        assert (held.action, held.code) == (pc.ProposedAction.HOLD, pc.TARGET_REQUIRED_FOR_STAGING)     # 対象が無ければ書かない
    _, final, _ = drive(dataclasses.replace(staged, staging={label: {}}), TARGET_B)
    assert final.state is pc.PublicationState.NO_CHANGE


def test_torn_staging_needs_explicit_preservation_and_tampered_or_foreign_staging_holds() -> None:
    staged = prepared(PUBLISHED_A, TARGET_B, 2)
    label = TARGET_B.version_label
    full = dict(staged.staging[label])
    first = sorted(full)[0]
    for torn_bytes in (b"", full[first][:10], full[first][:-1]):
        torn = dataclasses.replace(staged, staging={label: {**full, first: torn_bytes}})
        result = pc.classify_publication(torn, target=TARGET_B)
        assert (result.state, result.action, result.recovery) == (pc.PublicationState.STAGING_TORN, pc.ProposedAction.PRESERVE_STAGING,
                                                                  pc.RecoveryEligibility.EXPLICIT_PRESERVATION_ONLY)
        with pytest.raises(a4a.ProjectionError) as exc:
            pc.check_recovery_proposal(torn, "PRESERVE_STAGING", target=TARGET_B)                    # 自動では進めない
        assert exc.value.code == pc.UNSAFE_RECOVERY_PROPOSAL
        plan = pc.check_preservation_proposal(torn, "PRESERVE_STAGING", target=TARGET_B)
        assert (plan.preserve_area, plan.preserve_label) == (pc.PRESERVE_AREA_STAGING, label)
        after = apply(torn, plan)
        assert pc.classify_publication(after, target=TARGET_B).state is pc.PublicationState.INTENT_PREPARED
        assert classify_code(torn) == pc.STAGING_UNVERIFIED                        # 対象が無ければ切れと改竄を区別しない
    for mutated, code in (({**full, first: full[first].replace(b"| ", b"|x", 1)}, pc.STAGING_TAMPERED),
                          ({**full, first: full[first] + b"x\n"}, pc.STAGING_TAMPERED),
                          ({**full, "notes.md": b"human\n"}, pc.STAGING_FOREIGN_ENTRY),
                          ({first: full[first][:5], "other.md": b"x"}, pc.STAGING_FOREIGN_ENTRY)):
        observation = dataclasses.replace(staged, staging={label: mutated})
        assert classify_code(observation, TARGET_B) == code
        with pytest.raises(a4a.ProjectionError):
            pc.check_preservation_proposal(observation, "PRESERVE_STAGING", target=TARGET_B)
    moved = prepared(PUBLISHED_A, TARGET_B, 3)
    assert classify_code(dataclasses.replace(moved, staging={label: full}), TARGET_B) == pc.AMBIGUOUS_STAGING_AND_VERSION


def test_empty_reservation_preservation_is_explicit_only_and_requires_complete_verified_staging() -> None:
    staged = prepared(PUBLISHED_A, TARGET_B, 2)
    label = TARGET_B.version_label
    reserved = dataclasses.replace(staged, versions={**staged.versions, label: {}})
    result = pc.classify_publication(reserved, target=TARGET_B)
    assert (result.state, result.action, result.recovery) == (pc.PublicationState.VERSION_RESERVED_EMPTY,
                                                              pc.ProposedAction.PRESERVE_EMPTY_RESERVATION,
                                                              pc.RecoveryEligibility.EXPLICIT_PRESERVATION_ONLY)
    with pytest.raises(a4a.ProjectionError):
        pc.check_recovery_proposal(reserved, "PRESERVE_EMPTY_RESERVATION", target=TARGET_B)
    plan = pc.check_preservation_proposal(reserved, "PRESERVE_EMPTY_RESERVATION", target=TARGET_B)
    assert (plan.preserve_area, plan.preserve_label) == (pc.PRESERVE_AREA_RESERVATION, label)
    assert pc.classify_publication(apply(reserved, plan), target=TARGET_B).state is pc.PublicationState.STAGED_VERIFIED
    partial = dataclasses.replace(reserved, staging={label: dict(list(staged.staging[label].items())[:2])})
    assert classify_code(partial, TARGET_B) == pc.VERSION_UNVERIFIED               # 揃っていない staging と空の予約
    assert classify_code(dataclasses.replace(reserved, staging={}), TARGET_B) == pc.VERSION_UNVERIFIED
    published_empty = dataclasses.replace(PUBLISHED_A, versions={TARGET_A.version_label: {}})
    assert classify_code(published_empty) == pc.VERSION_UNVERIFIED                 # 公開済みの版の空は決して予約ではない


def test_preservation_never_targets_a_published_or_pointed_version() -> None:
    corpus = [prepared(PUBLISHED_AB, TARGET_C, steps) for steps in range(5)]
    staged = prepared(PUBLISHED_AB, TARGET_C, 2)
    label = TARGET_C.version_label
    first = sorted(staged.staging[label])[0]
    corpus += [dataclasses.replace(staged, staging={label: {**staged.staging[label], first: b""}}),
               dataclasses.replace(staged, versions={**staged.versions, label: {}})]
    published = {TARGET_A.version_label, TARGET_B.version_label}
    for observation in corpus:
        result = pc.classify_publication(observation, target=TARGET_C)
        plan = result.transition
        if plan is None:
            continue
        assert published <= set(plan.retained_versions)
        assert plan.preserve_label not in published and plan.version_label not in published
        if plan.preserve_area == pc.PRESERVE_AREA_RESERVATION:
            assert observation.versions[plan.preserve_label] == {}
    for proposal in ("PRESERVE_STAGING", "PRESERVE_EMPTY_RESERVATION"):
        with pytest.raises(a4a.ProjectionError) as exc:
            pc.check_preservation_proposal(PUBLISHED_AB, proposal)
        assert exc.value.code == pc.UNSAFE_PRESERVATION_PROPOSAL
    with pytest.raises(a4a.ProjectionError):
        pc.check_preservation_proposal(PUBLISHED_AB, "ARCHIVE_PREVIOUS_VERSION")


def test_closed_intent_staging_is_explicitly_preserved_only_when_verified() -> None:
    staged = prepared(PUBLISHED_A, TARGET_B, 2)
    open_digest = pc.classify_publication(staged).open_intent_digest
    abort = pc.abort_for(pc.parse_intent(staged.intents[open_digest]), "OPERATOR_ABORT")
    aborted = dataclasses.replace(staged, aborts={abort.abort_digest: abort.to_evidence_bytes()})
    result = pc.classify_publication(aborted)
    assert (result.state, result.recovery) == (pc.PublicationState.STAGING_OF_CLOSED_INTENT, pc.RecoveryEligibility.EXPLICIT_PRESERVATION_ONLY)
    after = apply(aborted, pc.check_preservation_proposal(aborted, "PRESERVE_STAGING"))
    assert pc.classify_publication(after).state is pc.PublicationState.PUBLISHED_VERIFIED
    label = TARGET_B.version_label
    first = sorted(staged.staging[label])[0]
    torn = dataclasses.replace(aborted, staging={label: {**staged.staging[label], first: b""}})
    assert classify_code(torn) == pc.STAGING_OF_CLOSED_INTENT                     # 閉じた intent の切れは確かめられない
    assert classify_code(observe(staging={label: staged.staging[label]})) == pc.ORPHAN_STAGING


def test_invalid_pointers_altered_versions_unknown_entries_and_torn_evidence_hold() -> None:
    assert classify_code(dataclasses.replace(PUBLISHED_A, pointer=b"garbage")) == pc.POINTER_INVALID
    assert classify_code(dataclasses.replace(PUBLISHED_A, pointer=None)) == pc.POINTER_MISSING
    assert classify_code(dataclasses.replace(PUBLISHED_A, pointer=TARGET_B.public_export.pointer_note())) == pc.POINTER_UNEXPECTED
    assert classify_code(observe(pointer=TARGET_A.public_export.pointer_note())) == pc.POINTER_WITHOUT_EVIDENCE
    notes = dict(PUBLISHED_A.versions[TARGET_A.version_label])
    first = sorted(notes)[0]
    notes[first] = notes[first].replace(b"| 0 |", b"| 1 |", 1)
    assert classify_code(dataclasses.replace(PUBLISHED_A, versions={TARGET_A.version_label: notes})) == pc.VERSION_UNVERIFIED
    assert classify_code(dataclasses.replace(PUBLISHED_A, versions={})) == pc.PREVIOUS_VERSION_MISSING
    assert classify_code(dataclasses.replace(PUBLISHED_A, versions={**PUBLISHED_A.versions, "notes": {}})) == pc.UNKNOWN_OBJECT
    key = sorted(PUBLISHED_A.intents)[0]
    assert classify_code(dataclasses.replace(PUBLISHED_A, intents={key: PUBLISHED_A.intents[key][:-5] + b"\n"})) == pc.RECORD_CORRUPT
    assert classify_code(dataclasses.replace(PUBLISHED_A, private_bindings={})) == pc.BINDING_MISSING
    assert classify_code(dataclasses.replace(PUBLISHED_A, public_exports={})) == pc.MANIFEST_MISSING
    rekeyed = dataclasses.replace(PUBLISHED_A, intents={"0" * 64: PUBLISHED_A.intents[key]})
    assert classify_code(rekeyed) == pc.EVIDENCE_DIGEST_MISMATCH


# ================================================ I/O の不在（動的）


def test_the_successor_performs_no_filesystem_network_process_or_clock_access(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("I/O attempted")
    for owner, names in ((builtins, ("open",)), (io, ("open",)), (os, ("open", "stat", "lstat", "listdir", "scandir", "replace", "rename",
                                                                       "mkdir", "makedirs", "unlink", "remove", "rmdir", "getcwd")),
                         (socket, ("socket", "create_connection")), (subprocess, ("Popen", "run")), (time, ("time", "time_ns", "sleep"))):
        for name in names:
            monkeypatch.setattr(owner, name, refuse)
    target = target_of(variant())
    observation, final, _ = drive(observe(), target)
    assert final.state is pc.PublicationState.NO_CHANGE and target.public_export.notes == TARGET_A.public_export.notes
    assert pc.parse_public_version(observation.versions[target.version_label]) == target.public_export.public_version
