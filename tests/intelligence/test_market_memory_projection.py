"""P13-A4a — Obsidian 投影の純粋な model の試験（合成の値だけ ・file ・vault ・network ・時計は使わない）。

A3 の合成の generation（`test_market_memory_generation` の builder）から counts-only の版を作り、明示の完全な digest ・純粋な再検証 ・
決定論（入力の順序 ・TZ ・作業 directory に依らない byte 一致）・Markdown の文法と private の形の走査 ・identity ・private な証拠の record ・
公開の状態の分類 ・回復の適格 ・前の版の保持を固定する。A4b の I/O の効果は試験の中の純粋な写像の更新（`apply`）で模擬する。
"""
from __future__ import annotations

import builtins
import dataclasses
import hashlib
import io
import json
import os
import socket
import subprocess
import time

import pytest

from src.intelligence.market_memory import memory_generation as mg
from src.intelligence.market_memory import memory_projection as mp
from src.intelligence.market_memory.review_state_sample import AttentionMark, OutcomeStatus, build_sample
from tests.intelligence.test_market_memory_generation import ADAPTER, PLAN, generation, sealed
from tests.intelligence.test_market_memory_model import VIEW, cutoff, make_counts, watch

#: 合成の fixture の版の golden な identity（描画の byte が変われば規則の version を上げる ・ここで止まる）
GOLDEN_PROJECTION_DIGEST = "402c55777a53750b4deaad5362dcef9aea9f847881a910a7604e98463a4278ee"
GOLDEN_EXPORT_DIGEST = "9bc7fc79bee139f063ebef3f6d78dcca159a6121a8799c5d66e6d9da1c1ffb9a"
ENTRY_VALUES = ("watch-a", "watch-b", "watch-c", "issuer-a", "issuer-b", "issuer-c", "rev-1")


def verified_of(gen: mg.MemoryGeneration) -> mg.VerifiedGeneration:
    return mg.verify_generation_records(sealed(gen), expected_generation_digest=gen.generation_digest)


def export_of(gen: mg.MemoryGeneration) -> mp.ProjectionExport:
    verified = verified_of(gen)
    source = mp.build_projection_input(verified, generation_digest=verified.generation_digest, manifest_digest=verified.manifest_digest)
    return mp.render_projection(source)


EXPORT_A = export_of(generation())
EXPORT_B = export_of(generation(PLAN + (cutoff(13),)))
EXPORT_C = export_of(generation(mute_b_at=2))


def code_of(call, *args, **kwargs) -> str:
    with pytest.raises(mp.ProjectionError) as exc:
        call(*args, **kwargs)
    assert exc.value.code in mp.PROJECTION_CODES
    return exc.value.code


def observe(**groups) -> mp.PublicationObservation:
    return mp.PublicationObservation(**groups)


def apply(observation: mp.PublicationObservation, plan: mp.TransitionPlan) -> mp.PublicationObservation:
    """A4b の I/O の効果の純粋な模擬（追加 ・pointer の置換 ・開いた intent の staging の移動だけ。削除 ・上書きは無い）。"""
    versions = {k: dict(v) for k, v in observation.versions.items()}
    staging = {k: dict(v) for k, v in observation.staging.items()}
    groups = {mp.EVIDENCE_MANIFEST: dict(observation.manifests), mp.EVIDENCE_INTENT: dict(observation.intents),
              mp.EVIDENCE_COMPLETION: dict(observation.completions), mp.EVIDENCE_ABORT: dict(observation.aborts)}
    pointer = observation.pointer
    if plan.action in (mp.ProposedAction.PREPARE_INTENT, mp.ProposedAction.RECORD_COMPLETION):
        for kind, digest, data in plan.evidence:
            assert digest not in groups[kind]                                      # 証拠は追加だけ
            groups[kind][digest] = data
    elif plan.action is mp.ProposedAction.STAGE_VERSION:
        assert plan.version_label not in staging and plan.version_label not in versions
        staging[plan.version_label] = dict(plan.staged_notes)
    elif plan.action is mp.ProposedAction.MOVE_STAGED_TO_VERSION:
        assert plan.version_label not in versions                                  # 置き換えない移動
        versions[plan.version_label] = staging.pop(plan.version_label)
    elif plan.action is mp.ProposedAction.REPLACE_POINTER:
        assert pointer == plan.expected_pointer                                    # 観測した pointer の上だけで置き換える
        pointer = plan.replacement_pointer
    else:
        raise AssertionError(plan.action)
    return mp.PublicationObservation(pointer=pointer, versions=versions, staging=staging, manifests=groups[mp.EVIDENCE_MANIFEST],
                                     intents=groups[mp.EVIDENCE_INTENT], completions=groups[mp.EVIDENCE_COMPLETION],
                                     aborts=groups[mp.EVIDENCE_ABORT])


def drive(observation: mp.PublicationObservation, target: mp.ProjectionExport):
    """分類 → 提案 → 模擬を NONE まで繰り返す。各段で前の版が残り ・検証されることを確かめる。"""
    before = dict(observation.versions)
    states = []
    for _ in range(8):
        result = mp.classify_publication(observation, target=target)
        states.append((result.state, result.action, result.recovery))
        assert set(before) <= set(result.retained_versions)                    # 前の版は常に残す
        if result.action is mp.ProposedAction.NONE:
            return observation, result, states
        assert result.action is not mp.ProposedAction.HOLD, result.code
        if result.recovery is mp.RecoveryEligibility.AUTO_CONVERGE_ELIGIBLE:
            assert mp.check_recovery_proposal(observation, result.action, target=target) == result.transition
        assert result.transition.version_label == target.version_label        # 遷移が触るのは新しい版だけ
        observation = apply(observation, result.transition)
        for label, notes in before.items():
            assert observation.versions[label] == notes                          # 前の版の byte は不変
    raise AssertionError("did not converge")


def published(*exports: mp.ProjectionExport) -> mp.PublicationObservation:
    observation = observe()
    for export in exports:
        observation, _, _ = drive(observation, export)
    return observation


PUBLISHED_A = published(EXPORT_A)
PUBLISHED_AB = published(EXPORT_A, EXPORT_B)


def prepared(base: mp.PublicationObservation, target: mp.ProjectionExport, steps: int) -> mp.PublicationObservation:
    """新しい版への公開を `steps` 段だけ進めた観測（中断の模擬）。"""
    observation = base
    for _ in range(steps):
        observation = apply(observation, mp.classify_publication(observation, target=target).transition)
    return observation


def classify_code(observation: mp.PublicationObservation, target=None) -> str:
    result = mp.classify_publication(observation, target=target)
    assert result.state is mp.PublicationState.FAIL_CLOSED and result.action is mp.ProposedAction.HOLD
    assert result.recovery is mp.RecoveryEligibility.HOLD_FAIL_CLOSED and result.transition is None
    return result.code


def with_note(data: bytes, line: str) -> bytes:
    return data[:-1] + b"\n" + line.encode("utf-8") + b"\n"


# ================================================ 分類の語彙 ・入力（明示の完全な digest ・再検証）


def test_approved_categories_equal_the_frozen_p9_enumerations_and_codes_are_structural() -> None:
    from src.intelligence.watchlist_thesis_intelligence.thesis_model import EvidenceKind, InvalidationBasis, ThesisStatus
    from src.intelligence.watchlist_thesis_intelligence.watch_model import ProvenanceKind, WatchStatus
    expected = {"watch_status_counts": WatchStatus, "watch_provenance_kind_counts": ProvenanceKind, "thesis_status_counts": ThesisStatus,
                "thesis_invalidation_basis_counts": InvalidationBasis, "thesis_supporting_evidence_kind_counts": EvidenceKind,
                "thesis_counter_evidence_kind_counts": EvidenceKind}
    approved = dict(mp.APPROVED_CATEGORY_CODES)
    assert set(approved) == set(expected)
    for name, kind in expected.items():
        assert set(approved[name]) == {member.value for member in kind}, name
        assert list(approved[name]) == sorted(approved[name]), name             # 固定の順
    assert set(mp.ProposedAction.__members__) == {"NONE", "PREPARE_INTENT", "STAGE_VERSION", "MOVE_STAGED_TO_VERSION", "REPLACE_POINTER",
                                                  "RECORD_COMPLETION", "HOLD"}
    for word in ("ARCHIVE", "DELETE", "REMOVE", "PRUNE", "CLEAN", "RETENTION", "RELOCATE", "PREVIOUS", "REPAIR"):
        assert not any(word in name for name in mp.ProposedAction.__members__), word   # 前の版を動かす action は無い
    assert {f.name for f in dataclasses.fields(mp.TransitionPlan)} == {
        "action", "intent_digest", "version_label", "evidence", "staged_notes", "expected_pointer", "replacement_pointer",
        "retained_versions"}                                                        # 削除 ・移動の欄は無い


def test_projection_input_requires_explicit_full_digests_and_rechecks_the_records() -> None:
    gen = generation()
    verified = verified_of(gen)
    with pytest.raises(TypeError):
        mp.build_projection_input(verified)                                         # 既定 ・「最新」は無い
    with pytest.raises(TypeError):
        mp.build_projection_input(verified, generation_digest=verified.generation_digest)
    assert code_of(mp.build_projection_input, verified, generation_digest=gen.generation_id,
                   manifest_digest=verified.manifest_digest) == mp.PROJECTION_INPUT_INVALID      # 略記は identity ではない
    assert code_of(mp.build_projection_input, verified, generation_digest=verified.generation_digest,
                   manifest_digest=verified.manifest_digest[:24]) == mp.PROJECTION_INPUT_INVALID
    assert code_of(mp.build_projection_input, "not-verified", generation_digest=verified.generation_digest,
                   manifest_digest=verified.manifest_digest) == mp.PROJECTION_INPUT_INVALID
    source = mp.build_projection_input(verified, generation_digest=verified.generation_digest, manifest_digest=verified.manifest_digest)
    assert source.source_attestation == mp.SOURCE_ATTESTATION == "A4A_RECHECKED_RECORD_BYTES_STORE_READ_NOT_ATTESTED"
    assert source.verified is not verified and source.verified == verified                       # byte から作り直した model
    assert "verified=" not in repr(source)
    with pytest.raises(mp.ProjectionError):
        mp.ProjectionInput(verified=verified, generation_digest=verified.generation_digest, manifest_digest=verified.manifest_digest,
                           source_attestation="STORE_VERIFIED")                                  # 証明の主張は作れない


def test_tampered_or_forged_sources_fail_closed() -> None:
    verified, other = verified_of(generation()), verified_of(generation(mute_b_at=2))
    tampered = verified.generation_digest[:-1] + ("0" if verified.generation_digest[-1] != "0" else "1")
    assert code_of(mp.build_projection_input, verified, generation_digest=tampered,
                   manifest_digest=verified.manifest_digest) == mp.SOURCE_DIGEST_MISMATCH
    assert code_of(mp.build_projection_input, verified, generation_digest=verified.generation_digest,
                   manifest_digest=other.manifest_digest) == mp.SOURCE_DIGEST_MISMATCH
    forged = mg.VerifiedGeneration(generation=verified.generation, manifest=other.manifest)        # 呼び出し側が作った「検証済み」
    assert code_of(mp.build_projection_input, forged, generation_digest=verified.generation_digest,
                   manifest_digest=other.manifest_digest) == mp.SOURCE_UNVERIFIED
    hollow = object.__new__(mg.VerifiedGeneration)                                               # 中身の無い object
    assert code_of(mp.build_projection_input, hollow, generation_digest=verified.generation_digest,
                   manifest_digest=verified.manifest_digest) == mp.SOURCE_UNVERIFIED
    unsupported = object.__new__(mg.MemoryGeneration)
    for name in ("cutoffs", "view_identity", "samples", "changes"):
        object.__setattr__(unsupported, name, getattr(verified.generation, name))
    object.__setattr__(unsupported, "adapter_rules_version", "p13_governed_review_source:9.9.9")
    bogus = mg.VerifiedGeneration(generation=unsupported, manifest=verified.manifest)
    assert code_of(mp.build_projection_input, bogus, generation_digest=verified.generation_digest,
                   manifest_digest=verified.manifest_digest) == mp.SCHEMA_UNSUPPORTED


# ================================================ counts-only の Markdown ・決定論 ・identity


def test_rendering_is_counts_only_and_holds_no_entries_instants_or_free_text() -> None:
    notes = EXPORT_A.note_map()
    label = EXPORT_A.version_label
    gen = generation()
    assert set(notes) == {f"{label}.md"} | {f"{label}-{s.sample_id}.md" for s in gen.samples} | {
        f"{label}-{mp.INTERVAL_ID_PREFIX}{mp.interval_digest(a.sample_digest, b.sample_digest)[:24]}.md"
        for a, b in zip(gen.samples, gen.samples[1:])}
    for name, data in notes.items():
        mp.validate_note(data)
        text = data.decode("utf-8")
        for value in ENTRY_VALUES:
            assert value not in text, (name, value)                                 # 項目の id ・発行体 ・revision は出ない
        for change in gen.changes:
            assert change.change_digest not in text and change.change_id not in text  # 項目ごとの擬名の hash は出ない
        for cut in gen.cutoffs:
            assert cut.content()["at"] not in text and "T00:00" not in text          # 瞬間は出ない（日だけ）
        assert "known_at（source が知られた時刻）ではない" in text
        assert mp.scan_private_shapes(text) == ()
    index = notes[f"{label}.md"].decode("utf-8")
    assert f'p13_generation: "{gen.generation_digest}"' in index and gen.generation_id in index
    assert "| first_sample_cutoff_date | 2026-01-10 |" in index and "| last_sample_cutoff_date | 2026-01-12 |" in index
    first = notes[f"{label}-{gen.samples[0].sample_id}.md"].decode("utf-8")
    assert "| watch_status_counts | ACTIVE | 2 |" in first and "| watch_status_counts | REMOVED | 0 |" in first
    assert "| live_focus_marks | 1 |" in first and "| sample_cutoff_date | 2026-01-10 |" in first
    assert "review_lookahead_days" not in first                                     # 人が宣言した窓は投影しない
    interval = notes[f"{label}-{mp.INTERVAL_ID_PREFIX}{mp.interval_digest(gen.samples[0].sample_digest, gen.samples[1].sample_digest)[:24]}.md"]
    assert b"| WATCH_ENTRY | CHANGED | 1 |" in interval and b"| attention | 1 |" in interval
    assert b"NORMAL" not in interval and b"MUTE" not in interval                     # 変化の前後の値は出ない


def test_equivalent_input_gives_byte_identical_output_independent_of_order_timezone_and_cwd(monkeypatch, tmp_path) -> None:
    again = export_of(generation())
    assert again.notes == EXPORT_A.notes and again.manifest == EXPORT_A.manifest and again.pointer_note() == EXPORT_A.pointer_note()
    shuffled = dict(reversed(list(sealed(generation()).items())))                  # record の写像の順序
    verified = mg.verify_generation_records(shuffled, expected_generation_digest=generation().generation_digest)
    source = mp.build_projection_input(verified, generation_digest=verified.generation_digest, manifest_digest=verified.manifest_digest)
    assert mp.render_projection(source).notes == EXPORT_A.notes
    with monkeypatch.context() as patch:
        patch.setenv("TZ", "Pacific/Kiritimati")
        time.tzset()
        patch.chdir(tmp_path)
        assert export_of(generation()).notes == EXPORT_A.notes                       # host の TZ ・作業 directory に依らない
    time.tzset()
    assert list(tmp_path.iterdir()) == []                                          # 何も書かない


def test_identities_are_stable_full_digests_and_short_ids_are_labels_only() -> None:
    manifest = EXPORT_A.manifest
    assert manifest.projection_digest == GOLDEN_PROJECTION_DIGEST and EXPORT_A.export_digest == GOLDEN_EXPORT_DIGEST
    canonical = json.dumps(manifest.content(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(("p13.memory_projection_export.v1\0" + canonical).encode("utf-8")).hexdigest() == EXPORT_A.export_digest
    plan = json.dumps(EXPORT_A.source.plan_content(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(("p13.memory_projection_plan.v1\0" + plan).encode("utf-8")).hexdigest() == manifest.projection_digest
    assert EXPORT_A.version_label == "p13prj_" + manifest.projection_digest[:24] and manifest.export_id == "p13exp_" + EXPORT_A.export_digest[:24]
    for name, data in EXPORT_A.notes:
        entry = next(f for f in manifest.files if f.name == name)
        assert entry.size == len(data) and entry.sha256 == hashlib.sha256(data).hexdigest()
    assert len({EXPORT_A.export_digest, EXPORT_B.export_digest, EXPORT_C.export_digest}) == 3
    assert mp.parse_export_manifest(manifest.to_bytes()) == manifest
    first_sample = generation().samples[0].sample_id
    a_note = EXPORT_A.note_map()[f"{EXPORT_A.version_label}-{first_sample}.md"]
    b_note = EXPORT_B.note_map()[f"{EXPORT_B.version_label}-{first_sample}.md"]
    assert a_note == b_note                                                           # 標本の note の内容は標本だけで決まる
    with pytest.raises(mp.ProjectionError) as exc:
        mp._no_collision([("p13int_" + "a" * 24, "a" * 64), ("p13int_" + "a" * 24, "a" * 24 + "b" * 40)])
    assert exc.value.code == mp.SHORT_ID_COLLISION


def test_export_manifests_and_evidence_records_are_strict_canonical_and_versioned() -> None:
    data = EXPORT_A.manifest.to_bytes()
    assert code_of(mp.parse_export_manifest, data.replace(b'","', b'", "', 1)) == mp.RECORD_CORRUPT          # 非正準
    for old, new in ((mp.EXPORT_MANIFEST_SCHEMA_VERSION, "p13_projection_manifest:9.9.9"),
                     (mp.PROJECTION_RULES_VERSION, "p13_projection_rules:9.9.9")):
        changed = json.loads(data)
        for key in ("schema_version", "rules_version"):
            changed[key] = new if changed[key] == old else changed[key]
        assert code_of(mp.parse_export_manifest, mg.record_bytes(changed)) == mp.SCHEMA_UNSUPPORTED
    value = json.loads(data)
    for files in (value["files"][::-1], value["files"] + value["files"][:1], [["../escape.md", 1, "a" * 64]],
                  [[value["files"][0][0], True, value["files"][0][2]]], []):
        assert code_of(mp.parse_export_manifest, mg.record_bytes({**value, "files": files})) == mp.RECORD_CORRUPT
    assert code_of(mp.parse_export_manifest, mg.record_bytes({**value, "extra": 1})) == mp.RECORD_CORRUPT
    assert code_of(mp.parse_export_manifest, b"not json") == mp.RECORD_CORRUPT
    assert code_of(mp.parse_export_manifest, mg.record_bytes({"files": []})) == mp.RECORD_CORRUPT
    intent = mp.intent_for(EXPORT_B, EXPORT_A.manifest)
    assert mp.parse_intent(intent.to_bytes()) == intent and intent.previous_export_digest == EXPORT_A.export_digest
    completion, abort = mp.completion_for(intent), mp.abort_for(intent, "OPERATOR_ABORT")
    assert mp.parse_completion(completion.to_bytes()) == completion and mp.parse_abort(abort.to_bytes()) == abort
    for parse, record in ((mp.parse_intent, intent), (mp.parse_completion, completion), (mp.parse_abort, abort)):
        changed = {**record.content(), "schema_version": record.schema_version.replace("0.1.0", "9.9.9")}
        assert code_of(parse, mg.record_bytes(changed)) == mp.SCHEMA_UNSUPPORTED
        assert code_of(parse, record.to_bytes() + b" ") == mp.RECORD_CORRUPT
    assert code_of(mp.abort_for, intent, "free text") == mp.RECORD_CORRUPT
    assert code_of(mp.IntentRecord, to_projection_digest="a" * 64, to_export_digest="b" * 64, generation_digest="c" * 64,
                   source_manifest_digest="d" * 64, previous_export_digest="e" * 64) == mp.RECORD_CORRUPT   # 前の版の片方だけ
    assert code_of(mp.parse_pointer, EXPORT_A.pointer_note().replace(b"p13_projection_pointer:0.1.0", b"p13_projection_pointer:9.9.9")) \
        == mp.POINTER_INVALID
    pointer = mp.parse_pointer(EXPORT_A.pointer_note())
    assert (pointer.projection_digest, pointer.export_digest) == (EXPORT_A.manifest.projection_digest, EXPORT_A.export_digest)


# ================================================ Markdown の文法 ・private の形の走査


LEAKS = (("C:" + "\\Users\\someone", "DRIVE_LOCATION"), ("\\\\server\\share", "BACKSLASH"), ("/home/someone/vault", "SLASH"),
         ("2026-01-10T09:30", "INSTANT"), ("cutoff 09:30", "TIME_OF_DAY"), ("code 72030", "LONG_NUMBER"),
         ("p9wat_" + "0" * 8, "FROZEN_ID_PREFIX"), ("p8iss_x", "FROZEN_ID_PREFIX"), ("hu" + "man: someone", "AUTHOR_PREFIX"),
         ("X-API-" + "KEY header", "KEY_HEADER"), ("api." + "jquants" + ".example", "PROVIDER"), ("JQ" + "UANTS_X", "PROVIDER"),
         ("the password", "ACCESS_WORD"), ("S-1-5-21", "SID"), ("https" + "://example.invalid", "URL"), ("www.example.invalid", "URL"),
         ("javascript:alert", "URL"), ("<script>", "HTML"), ("&lt;", "HTML"), ("![[p13prj_x]]", "EMBED"), ("`= this.file.name`", "CODE"),
         ("~~~", "CODE"), ("<% tp.date.now() %>", "TEMPLATE"), ("${secretless}", "TEMPLATE"), ("$= dv.pages()", "TEMPLATE"),
         ("%%hidden%%", "COMMENT_OR_FOOTNOTE"), ("[^1]", "COMMENT_OR_FOOTNOTE"))


def test_private_identifiers_paths_instants_urls_html_embeds_and_executable_syntax_are_rejected() -> None:
    base = EXPORT_A.note_map()[f"{EXPORT_A.version_label}.md"]
    for leak, label in LEAKS:
        assert label in mp.scan_private_shapes(leak), leak
        with pytest.raises(mp.ProjectionError) as exc:
            mp.validate_note(with_note(base, f"| generation_digest | {leak} |"))
        assert exc.value.code == mp.PRIVATE_SHAPE_DETECTED, leak
    for clean in ("p13_memory_projection:0.1.0", "p10_p9_view:0.1.0", "p9_safe_view_schema_version", "2026-01-10", "9999",
                  EXPORT_A.export_digest, EXPORT_A.version_label, mp.TITLE_INDEX, *mp.DERIVED_NOTICE, *mp.POINTER_NOTICE):
        assert mp.scan_private_shapes(clean) == (), clean                         # 承認した形は当たらない


def test_the_note_grammar_rejects_free_text_malformed_cells_frontmatter_and_byte_shapes() -> None:
    base = EXPORT_A.note_map()[f"{EXPORT_A.version_label}.md"]
    mp.validate_note(base)
    for line, detail in (("自由な文", "LINE"), ("# 任意の見出し", "LINE"), ("> [!note] callout", "LINE"), ("---", "LINE"),
                         ("- [[Other note]]", "LINE"), ("- [ ] task", "LINE"), ("| generation_digest | someone |", "TABLE_CELL"),
                         ("| watch_status_counts | ARCHIVED | 1 |", "TABLE_CELL"), ("| sample_cutoff_date | 2026-02-30 |", "TABLE_CELL"),
                         ("| watch_count | 10000 |", "PRIVATE"), ("| watch_count | -1 |", "TABLE_CELL"), ("| a | b | c | d |", "LINE"),
                         (" leading", "LINE_SHAPE"), ("x" * 600, "LINE_SHAPE")):
        with pytest.raises(mp.ProjectionError) as exc:
            mp.validate_note(with_note(base, line))
        assert exc.value.code in (mp.NOTE_INVALID, mp.PRIVATE_SHAPE_DETECTED), line
        assert exc.value.detail == detail or detail == "PRIVATE", (line, exc.value.detail)
    for old, new, detail in ((b'p13_note: "VERSION_INDEX"', b'p13_note: "FREE"', "FRONTMATTER_VALUE"),
                             (b'p13_schema: "p13_memory_projection:0.1.0"', b'p13_schema: "p13_memory_projection:9.9.9"', "FRONTMATTER_VALUE"),
                             (b'p13_note: "VERSION_INDEX"', b'tags: "x"', "FRONTMATTER_LINE"),
                             (b'p13_note: "VERSION_INDEX"', b'p13_extra: "x"', "FRONTMATTER_VALUE"),
                             (b'p13_rules: "p13_projection_rules:0.1.0"\n', b"", "FRONTMATTER_VALUE")):
        mutated = base.replace(old, new, 1)
        assert mutated != base, old
        with pytest.raises(mp.ProjectionError) as exc:
            mp.validate_note(mutated)
        assert (exc.value.code, exc.value.detail) in ((mp.NOTE_INVALID, detail), (mp.NOTE_INVALID, "FRONTMATTER_KEYS")), old
    for mutated, detail in ((base.replace(b"\n", b"\r\n"), "CONTROL_CHARACTER"), (base.replace(b"| ", b"|\t", 1), "CONTROL_CHARACTER"),
                            (b"\xef\xbb\xbf" + base, "BOM"), (base[:-1], "LINE_END"), (base + b"\n", "LINE_END"),
                            (base.replace(b"## ", "​## ".encode("utf-8"), 1), "CONTROL_CHARACTER"),
                            (base[:-1] + b"\xff\n", "UTF8"), (b"", "SIZE"), (base[4:], "FRONTMATTER")):
        with pytest.raises(mp.ProjectionError) as exc:
            mp.validate_note(mutated)
        assert exc.value.code == mp.NOTE_INVALID and exc.value.detail == detail, detail
    assert code_of(mp.validate_note, "text not bytes") == mp.NOTE_INVALID


def test_malformed_categories_and_out_of_range_counts_fail_closed() -> None:
    def single(entries, **counts):
        cut = cutoff(10)
        outcome = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=make_counts(entries, cut, **counts), rules_version=ADAPTER)
        assert outcome.status is OutcomeStatus.SAMPLED, outcome.failure_code
        gen = mg.build_generation((cut,), VIEW, adapter_rules_version=ADAPTER, samples=[outcome.sample])
        verified = verified_of(gen)
        return mp.build_projection_input(verified, generation_digest=verified.generation_digest, manifest_digest=verified.manifest_digest)
    archived = single([watch("watch-a", "issuer-a", status="ARCHIVED")])           # A1 は受けるが承認した分類ではない
    assert code_of(mp.render_projection, archived) == mp.CATEGORY_UNAPPROVED
    unknown = single([watch("watch-a", "issuer-a", provenance="IMPORTED")])
    assert code_of(mp.render_projection, unknown) == mp.CATEGORY_UNAPPROVED
    assert code_of(mp.render_projection, single([watch("watch-a", "issuer-a")], cleared=10000)) == mp.COUNT_OUT_OF_RANGE
    one = mp.render_projection(single([watch("watch-a", "issuer-a", attention=AttentionMark.FOCUS)]))
    assert mp.NO_INTERVALS_LINE.encode("utf-8") in one.note_map()[f"{one.version_label}.md"]   # 標本が 1 つなら区間は無い
    assert code_of(mp.render_projection, "not an input") == mp.PROJECTION_INPUT_INVALID


# ================================================ 公開の状態の分類 ・遷移（純粋 ・提案だけ）


def test_first_publication_runs_through_every_verified_state_and_then_reports_no_change() -> None:
    observation, final, states = drive(observe(), EXPORT_A)
    S, A, R = mp.PublicationState, mp.ProposedAction, mp.RecoveryEligibility
    assert states == [(S.FIRST_PUBLICATION, A.PREPARE_INTENT, R.NOT_REQUIRED), (S.INTENT_PREPARED, A.STAGE_VERSION, R.AUTO_CONVERGE_ELIGIBLE),
                      (S.STAGED_VERIFIED, A.MOVE_STAGED_TO_VERSION, R.AUTO_CONVERGE_ELIGIBLE),
                      (S.VERSION_VERIFIED, A.REPLACE_POINTER, R.AUTO_CONVERGE_ELIGIBLE),
                      (S.POINTER_SWITCHED, A.RECORD_COMPLETION, R.AUTO_CONVERGE_ELIGIBLE), (S.NO_CHANGE, A.NONE, R.NOT_REQUIRED)]
    assert final == mp.PublicationClassification(state=S.NO_CHANGE, action=A.NONE, recovery=R.NOT_REQUIRED, code="NO_CHANGE",
                                                 published_export_digest=EXPORT_A.export_digest, open_intent_digest=None,
                                                 completed_intent_count=1, aborted_intent_count=0,
                                                 retained_versions=(EXPORT_A.version_label,))
    assert observation.pointer == EXPORT_A.pointer_note() and observation.staging == {}
    assert observation.versions == {EXPORT_A.version_label: EXPORT_A.note_map()}
    assert mp.classify_publication(observe()) == mp.PublicationClassification(
        state=S.FIRST_PUBLICATION, action=A.NONE, recovery=R.NOT_REQUIRED, code="FIRST_PUBLICATION")
    published_only = mp.classify_publication(observation)                             # 完了を記録した状態 ＝ PUBLISHED_VERIFIED
    assert (published_only.state, published_only.action, published_only.code) == (S.PUBLISHED_VERIFIED, A.NONE, "PUBLISHED_VERIFIED")
    first_intent = mp.classify_publication(observe(), target=EXPORT_A).transition
    assert first_intent.evidence[0] == (mp.EVIDENCE_MANIFEST, EXPORT_A.export_digest, EXPORT_A.manifest.to_bytes())
    assert mp.parse_intent(first_intent.evidence[1][2]).previous_export_digest is None


def test_a_new_version_is_published_beside_the_previous_one_which_stays_immutable_and_verified() -> None:
    observation, final, _ = drive(PUBLISHED_A, EXPORT_B)
    assert final.state is mp.PublicationState.NO_CHANGE and final.completed_intent_count == 2
    assert observation.versions[EXPORT_A.version_label] == EXPORT_A.note_map()          # 前の版は消さず ・移さず ・byte 一致
    assert set(final.retained_versions) == {EXPORT_A.version_label, EXPORT_B.version_label}
    assert observation.pointer == EXPORT_B.pointer_note()
    switching = prepared(PUBLISHED_A, EXPORT_B, 3)                                   # 新しい版を準備する間、pointer は前の有効な版
    result = mp.classify_publication(switching, target=EXPORT_B)
    assert result.state is mp.PublicationState.VERSION_VERIFIED and switching.pointer == EXPORT_A.pointer_note()
    assert result.published_export_digest == EXPORT_A.export_digest
    assert (result.transition.expected_pointer, result.transition.replacement_pointer) == (EXPORT_A.pointer_note(), EXPORT_B.pointer_note())
    assert EXPORT_A.version_label in result.transition.retained_versions
    assert mp.classify_publication(PUBLISHED_AB, target=EXPORT_A).code == mp.REPUBLICATION_OF_KNOWN_VERSION   # 戻す再公開は HOLD
    observation, final, _ = drive(PUBLISHED_AB, EXPORT_C)
    assert final.completed_intent_count == 3 and len(observation.versions) == 3


def test_classification_is_deterministic_across_input_ordering_and_replay() -> None:
    for steps in range(5):
        observation = prepared(PUBLISHED_A, EXPORT_B, steps)
        reordered = mp.PublicationObservation(
            pointer=observation.pointer, versions={k: dict(reversed(list(v.items()))) for k, v in reversed(list(observation.versions.items()))},
            staging={k: dict(reversed(list(v.items()))) for k, v in observation.staging.items()},
            manifests=dict(reversed(list(observation.manifests.items()))), intents=dict(reversed(list(observation.intents.items()))),
            completions=dict(reversed(list(observation.completions.items()))), aborts=dict(observation.aborts))
        first = mp.classify_publication(observation, target=EXPORT_B)
        assert mp.classify_publication(reordered, target=EXPORT_B) == first == mp.classify_publication(observation, target=EXPORT_B)
        assert first.transition == mp.classify_publication(reordered, target=EXPORT_B).transition
    assert published(EXPORT_A, EXPORT_B) == PUBLISHED_AB                               # 同じ入力の再生は同じ観測


def test_interrupted_operations_resume_only_from_verified_unambiguous_states() -> None:
    held = mp.classify_publication(prepared(PUBLISHED_A, EXPORT_B, 1))               # intent だけ ・書く byte が無い
    assert (held.state, held.action, held.code) == (mp.PublicationState.INTENT_PREPARED, mp.ProposedAction.HOLD, mp.TARGET_REQUIRED_FOR_STAGING)
    for steps, state in ((2, mp.PublicationState.STAGED_VERIFIED), (3, mp.PublicationState.VERSION_VERIFIED),
                         (4, mp.PublicationState.POINTER_SWITCHED)):
        result = mp.classify_publication(prepared(PUBLISHED_A, EXPORT_B, steps))     # 対象を渡さなくても検証済みの続きは進める
        assert (result.state, result.recovery) == (state, mp.RecoveryEligibility.AUTO_CONVERGE_ELIGIBLE), steps
        conflict = mp.classify_publication(prepared(PUBLISHED_A, EXPORT_B, steps), target=EXPORT_C)
        assert (conflict.state, conflict.action, conflict.code) == (state, mp.ProposedAction.HOLD, mp.TARGET_CONFLICTS_WITH_OPEN_INTENT)
    staged = prepared(PUBLISHED_A, EXPORT_B, 2)
    partial = dict(staged.staging[EXPORT_B.version_label])
    partial.pop(sorted(partial)[0])
    assert classify_code(dataclasses.replace(staged, staging={EXPORT_B.version_label: partial})) == mp.STAGING_UNVERIFIED
    torn = {**staged.staging[EXPORT_B.version_label]}
    torn[sorted(torn)[0]] = torn[sorted(torn)[0]][:-2] + b"\n"
    assert classify_code(dataclasses.replace(staged, staging={EXPORT_B.version_label: torn})) == mp.STAGING_UNVERIFIED
    moved = prepared(PUBLISHED_A, EXPORT_B, 3)
    both = dataclasses.replace(moved, staging={EXPORT_B.version_label: EXPORT_B.note_map()})
    assert classify_code(both) == mp.AMBIGUOUS_STAGING_AND_VERSION


def test_orphans_unknown_objects_and_unreferenced_versions_fail_closed_without_a_verified_intent() -> None:
    assert classify_code(observe(staging={EXPORT_A.version_label: EXPORT_A.note_map()})) == mp.ORPHAN_STAGING
    assert classify_code(dataclasses.replace(PUBLISHED_A, staging={EXPORT_B.version_label: EXPORT_B.note_map()})) == mp.ORPHAN_STAGING
    assert classify_code(observe(versions={EXPORT_A.version_label: EXPORT_A.note_map()})) == mp.UNREFERENCED_VERSION
    assert classify_code(dataclasses.replace(PUBLISHED_A, versions={**PUBLISHED_A.versions, EXPORT_B.version_label: EXPORT_B.note_map()})) \
        == mp.UNREFERENCED_VERSION
    assert classify_code(observe(manifests={EXPORT_A.export_digest: EXPORT_A.manifest.to_bytes()})) == mp.UNREFERENCED_MANIFEST
    assert classify_code(dataclasses.replace(PUBLISHED_A, versions={**PUBLISHED_A.versions, "notes": {}})) == mp.UNKNOWN_OBJECT
    assert classify_code(observe(intents={"not-a-digest": b"{}"})) == mp.OBSERVATION_INVALID
    assert classify_code("not an observation") == mp.OBSERVATION_INVALID
    held = mp.classify_publication(dataclasses.replace(PUBLISHED_A, staging={EXPORT_B.version_label: EXPORT_B.note_map()}))
    assert held.retained_versions == (EXPORT_A.version_label,)                        # fail closed でも前の版は「残す」


def test_invalid_missing_or_ambiguous_pointers_fail_closed() -> None:
    assert classify_code(dataclasses.replace(PUBLISHED_A, pointer=b"garbage")) == mp.POINTER_INVALID
    assert classify_code(dataclasses.replace(PUBLISHED_A, pointer=EXPORT_A.pointer_note() + b"x\n")) == mp.POINTER_INVALID
    assert classify_code(dataclasses.replace(PUBLISHED_A, pointer=None)) == mp.POINTER_MISSING
    assert classify_code(observe(pointer=EXPORT_A.pointer_note())) == mp.POINTER_WITHOUT_EVIDENCE
    assert classify_code(dataclasses.replace(PUBLISHED_A, pointer=EXPORT_B.pointer_note())) == mp.POINTER_UNEXPECTED
    intent_only = prepared(PUBLISHED_A, EXPORT_B, 1)                                 # 版を作る前の pointer の切り替え
    assert classify_code(dataclasses.replace(intent_only, pointer=EXPORT_B.pointer_note())) == mp.POINTER_UNEXPECTED
    previous = dataclasses.replace(PUBLISHED_AB, pointer=EXPORT_A.pointer_note())    # 鎖の頭ではない前の版を指す
    assert classify_code(previous) == mp.POINTER_UNEXPECTED


def test_missing_contradictory_or_tampered_intents_and_conflicting_manifests_fail_closed() -> None:
    observation = prepared(PUBLISHED_A, EXPORT_B, 4)
    intent_digest = next(d for d in observation.intents if d not in {mp.parse_completion(c).intent_digest for c in observation.completions.values()})
    intent = mp.parse_intent(observation.intents[intent_digest])
    completion, abort = mp.completion_for(intent), mp.abort_for(intent, "OPERATOR_ABORT")
    both = dataclasses.replace(observation, completions={**observation.completions, completion.completion_digest: completion.to_bytes()},
                               aborts={abort.abort_digest: abort.to_bytes()})
    assert classify_code(both) == mp.CONTRADICTORY_INTENT
    dangling = dataclasses.replace(PUBLISHED_A, intents={})
    assert classify_code(dangling) == mp.INTENT_REFERENCE_MISSING
    no_manifest = dataclasses.replace(observation, manifests={k: v for k, v in observation.manifests.items() if k != EXPORT_B.export_digest})
    assert classify_code(no_manifest) == mp.MANIFEST_MISSING
    rekeyed = dataclasses.replace(observation, intents={("0" * 64 if k == intent_digest else k): v for k, v in observation.intents.items()})
    assert classify_code(rekeyed) == mp.EVIDENCE_DIGEST_MISMATCH                      # digest で番地を付けた record の改竄
    second = mp.intent_for(EXPORT_C, EXPORT_A.manifest)
    two_open = dataclasses.replace(observation, intents={**observation.intents, second.intent_digest: second.to_bytes()},
                                   manifests={**observation.manifests, EXPORT_C.export_digest: EXPORT_C.manifest.to_bytes()})
    assert classify_code(two_open) == mp.MULTIPLE_OPEN_INTENTS
    stale = mp.intent_for(EXPORT_C, None)                                            # 鎖の頭から始まらない開いた intent
    wrong_previous = dataclasses.replace(PUBLISHED_A, intents={**PUBLISHED_A.intents, stale.intent_digest: stale.to_bytes()},
                                         manifests={**PUBLISHED_A.manifests, EXPORT_C.export_digest: EXPORT_C.manifest.to_bytes()})
    assert classify_code(wrong_previous) == mp.INTENT_CHAIN_INVALID
    mismatched = mp.IntentRecord(to_projection_digest=EXPORT_C.manifest.projection_digest, to_export_digest=EXPORT_B.export_digest,
                                 generation_digest=EXPORT_B.manifest.generation_digest,
                                 source_manifest_digest=EXPORT_B.manifest.source_manifest_digest,
                                 previous_projection_digest=EXPORT_A.manifest.projection_digest, previous_export_digest=EXPORT_A.export_digest)
    conflicting = dataclasses.replace(PUBLISHED_A, intents={**PUBLISHED_A.intents, mismatched.intent_digest: mismatched.to_bytes()},
                                      manifests={**PUBLISHED_A.manifests, EXPORT_B.export_digest: EXPORT_B.manifest.to_bytes()})
    assert classify_code(conflicting) == mp.MANIFEST_CONFLICT
    rival = mp.ExportManifest(projection_digest=EXPORT_A.manifest.projection_digest, generation_digest=EXPORT_A.manifest.generation_digest,
                              source_manifest_digest=EXPORT_A.manifest.source_manifest_digest, files=EXPORT_A.manifest.files[:-1]
                              + (dataclasses.replace(EXPORT_A.manifest.files[-1], size=EXPORT_A.manifest.files[-1].size + 1),))
    rival_intent = mp.IntentRecord(to_projection_digest=rival.projection_digest, to_export_digest=rival.export_digest,
                                   generation_digest=rival.generation_digest, source_manifest_digest=rival.source_manifest_digest)
    abort_rival = mp.abort_for(rival_intent, "VERIFICATION_FAILED")
    same_plan = dataclasses.replace(PUBLISHED_A, manifests={**PUBLISHED_A.manifests, rival.export_digest: rival.to_bytes()},
                                    intents={**PUBLISHED_A.intents, rival_intent.intent_digest: rival_intent.to_bytes()},
                                    aborts={abort_rival.abort_digest: abort_rival.to_bytes()})
    assert classify_code(same_plan) == mp.MANIFEST_CONFLICT                          # 同じ計画の別の byte
    assert mp.classify_publication(PUBLISHED_A, target=EXPORT_A).state is mp.PublicationState.NO_CHANGE


def test_short_id_collisions_between_versions_fail_closed() -> None:
    def fake(projection: str) -> mp.ExportManifest:
        label = "p13prj_" + projection[:24]
        return mp.ExportManifest(projection_digest=projection, generation_digest="c" * 64, source_manifest_digest="d" * 64,
                                 files=(mp.ExportFile(name=label + ".md", size=1, sha256="e" * 64),))
    one, two = fake("a" * 24 + "b" * 40), fake("a" * 24 + "f" * 40)
    assert one.version_label == two.version_label and one.projection_digest != two.projection_digest
    intents = [mp.IntentRecord(to_projection_digest=m.projection_digest, to_export_digest=m.export_digest, generation_digest="c" * 64,
                               source_manifest_digest="d" * 64) for m in (one, two)]
    aborts = [mp.abort_for(i, "OPERATOR_ABORT") for i in intents]
    colliding = observe(manifests={m.export_digest: m.to_bytes() for m in (one, two)}, intents={i.intent_digest: i.to_bytes() for i in intents},
                        aborts={a.abort_digest: a.to_bytes() for a in aborts})
    assert classify_code(colliding) == mp.SHORT_ID_COLLISION


def test_archival_or_deletion_of_a_previous_valid_version_is_never_proposed_and_its_absence_fails_closed() -> None:
    archived = dataclasses.replace(PUBLISHED_AB, versions={EXPORT_B.version_label: EXPORT_B.note_map()})
    assert classify_code(archived) == mp.PREVIOUS_VERSION_MISSING                   # 前の版を移した ・消した状態は fail closed
    tampered = {**EXPORT_A.note_map()}
    tampered[sorted(tampered)[0]] = tampered[sorted(tampered)[0]].replace(b"| 0 |", b"| 1 |", 1)
    assert tampered != EXPORT_A.note_map()
    assert classify_code(dataclasses.replace(PUBLISHED_AB, versions={**PUBLISHED_AB.versions, EXPORT_A.version_label: tampered})) \
        == mp.VERSION_UNVERIFIED
    for steps in range(5):
        result = mp.classify_publication(prepared(PUBLISHED_AB, EXPORT_C, steps), target=EXPORT_C)
        plan = result.transition
        assert {EXPORT_A.version_label, EXPORT_B.version_label} <= set(plan.retained_versions)
        assert plan.version_label == EXPORT_C.version_label                           # 遷移が触るのは新しい版だけ
        assert all(name.startswith(EXPORT_C.version_label) for name, _ in plan.staged_notes)


def test_aborted_operations_keep_their_evidence_and_versions_and_never_auto_move_staging() -> None:
    staged = prepared(PUBLISHED_A, EXPORT_B, 2)
    intent = mp.parse_intent(next(v for k, v in staged.intents.items() if k not in {mp.parse_completion(c).intent_digest
                                                                                    for c in staged.completions.values()}))
    abort = mp.abort_for(intent, "OPERATOR_ABORT")
    aborted_staging = dataclasses.replace(staged, aborts={abort.abort_digest: abort.to_bytes()})
    assert classify_code(aborted_staging) == mp.STAGING_OF_CLOSED_INTENT               # 残った staging は A4b の判断（自動で移さない）
    moved = prepared(PUBLISHED_A, EXPORT_B, 3)
    aborted_version = dataclasses.replace(moved, aborts={abort.abort_digest: abort.to_bytes()})
    result = mp.classify_publication(aborted_version)
    assert (result.state, result.aborted_intent_count) == (mp.PublicationState.PUBLISHED_VERIFIED, 1)
    assert set(result.retained_versions) == {EXPORT_A.version_label, EXPORT_B.version_label}   # 中止した版も残す
    assert mp.classify_publication(aborted_version, target=EXPORT_B).code == mp.REPUBLICATION_OF_KNOWN_VERSION
    observation, final, _ = drive(aborted_version, EXPORT_C)
    assert final.state is mp.PublicationState.NO_CHANGE and set(observation.versions) == {
        EXPORT_A.version_label, EXPORT_B.version_label, EXPORT_C.version_label}


def test_unsafe_automatic_recovery_proposals_are_rejected() -> None:
    staged = prepared(PUBLISHED_A, EXPORT_B, 2)
    assert mp.check_recovery_proposal(staged, "MOVE_STAGED_TO_VERSION").action is mp.ProposedAction.MOVE_STAGED_TO_VERSION
    for proposal, detail in (("ARCHIVE_PREVIOUS_VERSION", "UNKNOWN_ACTION"), ("DELETE_VERSION", "UNKNOWN_ACTION"),
                             ("REPLACE_POINTER", "NOT_THE_NEXT_TRANSITION"), ("HOLD", "NOT_THE_NEXT_TRANSITION"),
                             ("RECORD_COMPLETION", "NOT_THE_NEXT_TRANSITION")):
        with pytest.raises(mp.ProjectionError) as exc:
            mp.check_recovery_proposal(staged, proposal)
        assert (exc.value.code, exc.value.detail) == (mp.UNSAFE_RECOVERY_PROPOSAL, detail), proposal
    for observation, proposal, target in ((prepared(PUBLISHED_A, EXPORT_B, 1), "STAGE_VERSION", None),       # byte が無い
                                          (observe(staging={EXPORT_A.version_label: EXPORT_A.note_map()}), "MOVE_STAGED_TO_VERSION", None),
                                          (PUBLISHED_A, "PREPARE_INTENT", EXPORT_B),                          # 新しい intent は回復ではない
                                          (prepared(PUBLISHED_A, EXPORT_B, 2), "MOVE_STAGED_TO_VERSION", EXPORT_C)):
        with pytest.raises(mp.ProjectionError) as exc:
            mp.check_recovery_proposal(observation, proposal, target=target)
        assert (exc.value.code, exc.value.detail) == (mp.UNSAFE_RECOVERY_PROPOSAL, "NOT_ELIGIBLE"), proposal


# ================================================ I/O の不在（動的）


def test_the_pure_model_performs_no_filesystem_network_process_or_clock_access(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise AssertionError("I/O attempted")
    for owner, names in ((builtins, ("open",)), (io, ("open",)), (os, ("open", "stat", "lstat", "listdir", "scandir", "replace", "rename",
                                                                       "mkdir", "makedirs", "unlink", "remove", "rmdir", "getcwd")),
                         (socket, ("socket", "create_connection")), (subprocess, ("Popen", "run")), (time, ("time", "time_ns", "sleep"))):
        for name in names:
            monkeypatch.setattr(owner, name, refuse)
    export = export_of(generation())
    observation, final, _ = drive(observe(), export)
    assert final.state is mp.PublicationState.NO_CHANGE and export.notes == EXPORT_A.notes
    assert mp.classify_publication(dataclasses.replace(observation, pointer=b"garbage")).code == mp.POINTER_INVALID
