"""P13-A3 — Memory の generation ・manifest ・pointer ・試行の証拠の純粋な model の試験（file ・時計 ・環境は使わない）。

標本は A1 の試験と同じ合成の値（`test_market_memory_model` の builder）で作る。3 つの identity の分離 ・REUSED の決定論 ・厳密な
検証（manifest の完全一致 ・正準性 ・完全な digest ・変化の再生 ・版）・略記 id の衝突 ・telemetry の不在を固定する。
"""
from __future__ import annotations

import dataclasses
import json
from datetime import timedelta

import pytest

from src.intelligence.market_memory import memory_generation as mg
from src.intelligence.market_memory.canonical import CanonicalError, domain_digest
from src.intelligence.market_memory.review_state_change import CHANGE_SCHEMA_VERSION, ChangeKind, detect_changes_over
from src.intelligence.market_memory.review_state_sample import (FORBIDDEN_FIELD_NAMES, SAMPLE_SCHEMA_VERSION, AttentionMark,
                                                                OutcomeStatus, SampleCutoff, SampleOutcome, StalenessLabel,
                                                                build_digest, build_sample)
from tests.intelligence.test_market_memory_model import VIEW, cutoff, make_counts, watch

ADAPTER = "p13_governed_review_source:0.1.0"
TELEMETRY_KEYS = ("sampled_at", "host", "pid", "built_at", "recorded_at", "hostname", "user", "cwd", "root")


def sample_at(cut: SampleCutoff, *, mute_b: bool = False, extra: bool = False, rules: str = ADAPTER):
    entries = [watch("watch-a", "issuer-a", attention=AttentionMark.FOCUS),
               watch("watch-b", "issuer-b", attention=AttentionMark.MUTE if mute_b else AttentionMark.NORMAL)]
    if extra:
        entries.append(watch("watch-c", "issuer-c"))
    outcome = build_sample(cutoff=cut, view_identity=VIEW, entries=entries, counts=make_counts(entries, cut), rules_version=rules)
    assert outcome.status is OutcomeStatus.SAMPLED, outcome.failure_code
    return outcome.sample


PLAN = (cutoff(10), cutoff(11), cutoff(12))


def generation(plan=PLAN, *, mute_b_at=1, extra_at=2) -> mg.MemoryGeneration:
    samples = [sample_at(c, mute_b=i >= mute_b_at, extra=i >= extra_at) for i, c in enumerate(plan)]
    return mg.build_generation(plan, VIEW, adapter_rules_version=ADAPTER, samples=samples)


def sealed(gen: mg.MemoryGeneration) -> dict:
    records = dict(gen.records())
    records[mg.MANIFEST_RECORD_NAME] = gen.manifest().to_bytes()
    return records


def reseal(records: dict, name: str, data: bytes) -> dict:
    """1 つの file を替え、manifest をそれに合わせて作り直す（manifest だけの検査を越えた改竄の模擬）。"""
    changed = {**records, name: data}
    manifest = mg.parse_manifest(records[mg.MANIFEST_RECORD_NAME])
    entries = tuple(mg.ManifestEntry(name=n, size=len(changed[n]), sha256=mg.sha256_hex(changed[n]))
                    for n in sorted(set(changed) - {mg.MANIFEST_RECORD_NAME}))
    changed[mg.MANIFEST_RECORD_NAME] = mg.GenerationManifest(generation_digest=manifest.generation_digest, entries=entries).to_bytes()
    return changed


def verify_code(records: dict, digest: str) -> str:
    with pytest.raises(mg.MemoryGenerationError) as exc:
        mg.verify_generation_records(records, expected_generation_digest=digest)
    assert exc.value.code in mg.GENERATION_CODES
    return exc.value.code


# ================================================ 計画 ・3 つの identity


def test_the_adapter_rules_literal_equals_the_accepted_adapter_constant() -> None:
    from src.intelligence.market_memory.governed_review_source import ADAPTER_RULES_VERSION
    assert mg.SUPPORTED_ADAPTER_RULES_VERSIONS == frozenset({ADAPTER_RULES_VERSION}) == frozenset({ADAPTER})


def test_plans_reject_empty_duplicate_non_increasing_and_unsupported_inputs() -> None:
    assert mg.validate_plan(list(PLAN)) == PLAN
    for bad, code in (((), mg.PLAN_INVALID), ([PLAN[0], "x"], mg.PLAN_INVALID), ((PLAN[0], PLAN[0]), mg.CUTOFF_ORDER_INVALID),
                      ((PLAN[1], PLAN[0]), mg.CUTOFF_ORDER_INVALID), ((cutoff(10, 1), cutoff(10, 2, as_of_day=9)), mg.CUTOFF_ORDER_INVALID),
                      (tuple(cutoff(1) for _ in range(2)), mg.CUTOFF_ORDER_INVALID), ("not-a-plan", mg.PLAN_INVALID)):
        with pytest.raises(mg.MemoryGenerationError) as exc:
            mg.validate_plan(bad)
        assert exc.value.code == code, bad
    too_many = tuple(SampleCutoff(at=PLAN[0].at + timedelta(minutes=i), as_of_date=PLAN[0].as_of_date)
                     for i in range(mg.MAX_PLAN_CUTOFFS + 1))
    with pytest.raises(mg.MemoryGenerationError):
        mg.validate_plan(too_many)
    with pytest.raises(mg.MemoryGenerationError) as exc:
        mg.plan_digest(PLAN, VIEW, adapter_rules_version="p13_governed_review_source:9.9.9")
    assert exc.value.code == mg.SCHEMA_UNSUPPORTED


def test_plan_digest_is_the_a1_build_digest_with_memory_rules_and_version_descriptors_only() -> None:
    expected = build_digest(PLAN, VIEW, rules_version=mg.MEMORY_RULES_VERSION, input_descriptors=(
        ("ADAPTER_RULES", ADAPTER), ("CHANGE_SCHEMA", CHANGE_SCHEMA_VERSION), ("GENERATION_SCHEMA", mg.GENERATION_SCHEMA_VERSION),
        ("STORE_SCHEMA", mg.STORE_SCHEMA_VERSION)))
    assert mg.plan_digest(PLAN, VIEW, adapter_rules_version=ADAPTER) == expected
    assert mg.plan_digest(PLAN[:2], VIEW, adapter_rules_version=ADAPTER) != expected                    # 計画が違えば別
    assert generation().plan_digest == expected == generation(mute_b_at=0).plan_digest                  # 結果が違っても計画は同じ


def test_generation_identity_is_deterministic_separate_from_plan_and_manifest_and_tracks_results() -> None:
    first, second = generation(), generation()
    assert first == second and first.records() == second.records()                                      # 同じ結果 → 同じ byte（REUSED）
    assert first.generation_digest == second.generation_digest and first.generation_id.startswith(mg.GENERATION_ID_PREFIX)
    assert first.generation_id == mg.GENERATION_ID_PREFIX + first.generation_digest[:24]
    assert first.generation_digest == domain_digest(mg.GENERATION_DOMAIN, first.content())
    manifest = first.manifest()
    assert manifest.manifest_digest == domain_digest(mg.MANIFEST_DOMAIN, manifest.content())
    assert len({first.plan_digest, first.generation_digest, manifest.manifest_digest}) == 3                # 3 つの identity は別
    changed = generation(mute_b_at=0)
    assert changed.plan_digest == first.plan_digest and changed.generation_digest != first.generation_digest
    content = first.content()
    assert content["sample_digests"] == [s.sample_digest for s in first.samples]
    assert content["change_digests"] == [c.change_digest for c in first.changes]
    assert {content[k] for k in ("store_schema_version", "memory_rules_version", "adapter_rules_version", "sample_schema_version",
                                 "change_schema_version")} == {mg.STORE_SCHEMA_VERSION, mg.MEMORY_RULES_VERSION, ADAPTER,
                                                               SAMPLE_SCHEMA_VERSION, CHANGE_SCHEMA_VERSION}
    assert content["source_integrity_class"] == mg.SOURCE_INTEGRITY_CLASS                               # source の完全性は主張しない


def test_changes_are_the_replayed_endpoint_differences_and_a_single_cutoff_has_none() -> None:
    gen = generation()
    assert gen.changes == detect_changes_over(gen.samples)
    assert {c.kind for c in gen.changes} == {ChangeKind.CHANGED, ChangeKind.APPEARED}
    single = generation(PLAN[:1])
    assert single.changes == () and single.records()[mg.CHANGES_RECORD_NAME] == b""
    with pytest.raises(mg.MemoryGenerationError) as exc:
        mg.MemoryGeneration(cutoffs=gen.cutoffs, view_identity=VIEW, adapter_rules_version=ADAPTER, samples=gen.samples,
                            changes=gen.changes[:-1])
    assert exc.value.code == mg.CHANGES_INCONSISTENT


def test_samples_must_match_the_plan_view_identity_and_adapter_rules() -> None:
    samples = [sample_at(c) for c in PLAN]
    for bad in ([sample_at(cutoff(13))] + samples[1:], samples[:2], [sample_at(PLAN[0], rules="p13_other_rules:0.1.0")] + samples[1:]):
        with pytest.raises(mg.MemoryGenerationError) as exc:
            mg.build_generation(PLAN, VIEW, adapter_rules_version=ADAPTER, samples=bad)
        assert exc.value.code == mg.SAMPLES_INCONSISTENT
    other_view = dataclasses.replace(VIEW, personal_projection_schema_version="p10_personal_projection:9.9.9")
    with pytest.raises(mg.MemoryGenerationError) as exc:
        mg.build_generation(PLAN, other_view, adapter_rules_version=ADAPTER, samples=samples)
    assert exc.value.code == mg.SAMPLES_INCONSISTENT


def test_forged_short_id_collisions_fail_closed(monkeypatch) -> None:
    def collide(*_args, **_kwargs):
        raise CanonicalError("SHORT_ID_COLLISION", "p13smp_x")
    monkeypatch.setattr(mg, "check_sample_ids", collide)
    with pytest.raises(mg.MemoryGenerationError) as exc:
        generation()
    assert exc.value.code == mg.SHORT_ID_COLLISION
    monkeypatch.undo()
    monkeypatch.setattr(mg, "detect_changes_over", collide)
    with pytest.raises(mg.MemoryGenerationError) as exc:
        generation()
    assert exc.value.code == mg.SHORT_ID_COLLISION


# ================================================ byte ・厳密な検証


def test_records_are_canonical_lf_only_and_hold_no_telemetry_paths_or_text() -> None:
    gen = generation()
    records = sealed(gen)
    assert set(records) == {mg.MANIFEST_RECORD_NAME, mg.GENERATION_RECORD_NAME, mg.CHANGES_RECORD_NAME,
                            *(mg.sample_record_name(s.sample_digest) for s in gen.samples)}
    for name, data in records.items():
        assert b"\r" not in data and (data == b"" or data.endswith(b"\n")), name
        for line in data.splitlines():
            value = json.loads(line)
            assert mg.record_bytes(value) == line + b"\n", name                                        # 正準 JSON ＋ LF
        text = data.decode("utf-8")
        for key in TELEMETRY_KEYS:
            assert f'"{key}"' not in text, (name, key)
    for kind in (mg.MemoryGeneration, mg.ManifestEntry, mg.GenerationManifest, mg.PublicationRecord, mg.AttemptRecord, mg.VerifiedGeneration):
        names = {f.name for f in dataclasses.fields(kind)}
        assert not names & FORBIDDEN_FIELD_NAMES and not names & set(TELEMETRY_KEYS), kind               # telemetry の欄は無い
    assert json.loads(mg.lock_bytes("BUILD", gen.plan_digest)) == {"schema_version": mg.LOCK_SCHEMA_VERSION, "operation": "BUILD",
                                                                   "plan_digest": gen.plan_digest}
    assert json.loads(mg.marker_bytes()) == {"schema_version": mg.STORE_SCHEMA_VERSION, "root_class": mg.ROOT_CLASS}


def test_strict_verification_reconstructs_the_generation_from_bytes() -> None:
    gen = generation()
    verified = mg.verify_generation_records(sealed(gen), expected_generation_digest=gen.generation_digest)
    assert verified.generation == gen and verified.generation_digest == gen.generation_digest
    assert verified.manifest_digest == gen.manifest().manifest_digest
    assert "watch-a" not in repr(verified)                                                             # repr に標本は出ない
    assert verify_code(sealed(gen), generation(mute_b_at=0).generation_digest) == mg.GENERATION_DIGEST_MISMATCH


def test_manifest_tampering_missing_and_extra_files_fail_closed() -> None:
    gen = generation()
    digest = gen.generation_digest
    records = sealed(gen)
    sample_name = mg.sample_record_name(gen.samples[0].sample_digest)
    flipped = bytearray(records[sample_name])
    flipped[10] ^= 1
    assert verify_code({**records, sample_name: bytes(flipped)}, digest) == mg.MANIFEST_MISMATCH          # byte の改竄
    assert verify_code({k: v for k, v in records.items() if k != sample_name}, digest) == mg.GENERATION_INCOMPLETE   # 欠落
    assert verify_code({k: v for k, v in records.items() if k != mg.MANIFEST_RECORD_NAME}, digest) == mg.GENERATION_INCOMPLETE
    extra = mg.sample_record_name("f" * 64)
    assert verify_code({**records, extra: b"{}\n"}, digest) == mg.UNAUTHORIZED_ENTRY                       # manifest に無い file
    assert verify_code({**records, "notes.md": b"x"}, digest) == mg.UNAUTHORIZED_ENTRY                     # layout の外の名前
    assert verify_code(reseal(records, extra, b"{}\n"), digest) == mg.UNAUTHORIZED_ENTRY                   # 参照されない標本
    manifest = json.loads(records[mg.MANIFEST_RECORD_NAME])
    manifest["files"].append(manifest["files"][0])
    assert verify_code({**records, mg.MANIFEST_RECORD_NAME: mg.record_bytes(manifest)}, digest) == mg.MANIFEST_INVALID   # 重複
    manifest = json.loads(records[mg.MANIFEST_RECORD_NAME])
    manifest["extra"] = 1
    assert verify_code({**records, mg.MANIFEST_RECORD_NAME: mg.record_bytes(manifest)}, digest) == mg.MANIFEST_INVALID   # 余分な鍵
    pretty = json.dumps(json.loads(records[mg.MANIFEST_RECORD_NAME]), indent=1).encode("utf-8") + b"\n"
    assert verify_code({**records, mg.MANIFEST_RECORD_NAME: pretty}, digest) == mg.MANIFEST_INVALID         # 非正準


def test_record_tampering_behind_a_consistent_manifest_is_still_detected() -> None:
    gen = generation()
    digest = gen.generation_digest
    records = sealed(gen)
    first, second = (mg.sample_record_name(s.sample_digest) for s in gen.samples[:2])
    assert verify_code(reseal(records, first, records[second]), digest) == mg.RECORD_DIGEST_MISMATCH      # 名前と内容の digest の不一致
    assert verify_code(reseal(records, first, b"{not json}\n"), digest) == mg.RECORD_CORRUPT
    pretty = json.dumps(json.loads(records[first]), indent=1).encode("utf-8") + b"\n"
    assert verify_code(reseal(records, first, pretty), digest) == mg.RECORD_CORRUPT                       # 非正準
    lines = records[mg.CHANGES_RECORD_NAME].splitlines(keepends=True)
    assert verify_code(reseal(records, mg.CHANGES_RECORD_NAME, b"".join(lines[:-1])), digest) == mg.CHANGES_INCONSISTENT   # 変化の欠落
    assert verify_code(reseal(records, mg.CHANGES_RECORD_NAME, b"".join(lines + lines[:1])), digest) == mg.CHANGES_INCONSISTENT
    assert verify_code(reseal(records, mg.CHANGES_RECORD_NAME, records[mg.CHANGES_RECORD_NAME][:-1]), digest) == mg.RECORD_CORRUPT
    record = json.loads(records[mg.GENERATION_RECORD_NAME])
    record["plan_digest"] = "0" * 64
    assert verify_code(reseal(records, mg.GENERATION_RECORD_NAME, mg.record_bytes(record)), digest) == mg.PLAN_DIGEST_MISMATCH
    record = json.loads(records[mg.GENERATION_RECORD_NAME])
    record["change_digests"] = list(reversed(record["change_digests"]))
    assert verify_code(reseal(records, mg.GENERATION_RECORD_NAME, mg.record_bytes(record)), digest) == mg.GENERATION_DIGEST_MISMATCH
    record = json.loads(records[mg.GENERATION_RECORD_NAME])
    record["authority_class"] = "AUTHORITY"
    assert verify_code(reseal(records, mg.GENERATION_RECORD_NAME, mg.record_bytes(record)), digest) == mg.RECORD_CORRUPT


def test_unsupported_schema_versions_fail_closed_as_schema_unsupported() -> None:
    gen = generation()
    digest = gen.generation_digest
    records = sealed(gen)
    for name, key in ((mg.GENERATION_RECORD_NAME, "schema_version"), (mg.GENERATION_RECORD_NAME, "store_schema_version"),
                      (mg.GENERATION_RECORD_NAME, "memory_rules_version"), (mg.GENERATION_RECORD_NAME, "adapter_rules_version"),
                      (mg.GENERATION_RECORD_NAME, "change_schema_version"), (mg.sample_record_name(gen.samples[0].sample_digest), "schema_version")):
        value = json.loads(records[name])
        value[key] = "p13_future:9.9.9"
        assert verify_code(reseal(records, name, mg.record_bytes(value)), digest) == mg.SCHEMA_UNSUPPORTED, (name, key)
    manifest = json.loads(records[mg.MANIFEST_RECORD_NAME])
    manifest["schema_version"] = "p13_memory_manifest:9.9.9"
    assert verify_code({**records, mg.MANIFEST_RECORD_NAME: mg.record_bytes(manifest)}, digest) == mg.SCHEMA_UNSUPPORTED
    pointer = mg.PublicationRecord(generation_digest=digest, manifest_digest=gen.manifest().manifest_digest)
    assert mg.parse_publication(pointer.to_bytes()) == pointer
    for data, code in ((mg.record_bytes({**pointer.content(), "schema_version": "p13_memory_publication:9.9.9"}), mg.SCHEMA_UNSUPPORTED),
                       (mg.record_bytes({**pointer.content(), "extra": 1}), mg.PUBLICATION_INVALID),
                       (mg.record_bytes({**pointer.content(), "manifest_digest": "short"}), mg.PUBLICATION_INVALID),
                       (b"{not json}\n", mg.RECORD_CORRUPT), (pointer.to_bytes()[:-1], mg.RECORD_CORRUPT)):
        with pytest.raises(mg.MemoryGenerationError) as exc:
            mg.parse_publication(data)
        assert exc.value.code == code, data
    mg.check_marker(mg.marker_bytes())
    for data, code in ((mg.record_bytes({"schema_version": "p13_memory_store:9.9.9", "root_class": mg.ROOT_CLASS}), mg.SCHEMA_UNSUPPORTED),
                       (mg.record_bytes({"schema_version": mg.STORE_SCHEMA_VERSION, "root_class": "OTHER"}), mg.RECORD_CORRUPT)):
        with pytest.raises(mg.MemoryGenerationError) as exc:
            mg.check_marker(data)
        assert exc.value.code == code


# ================================================ 試行の証拠 ・鮮度の label


def test_attempt_evidence_holds_only_plan_cutoffs_statuses_and_safe_codes() -> None:
    plan = mg.plan_digest(PLAN, VIEW, adapter_rules_version=ADAPTER)
    outcomes = (SampleOutcome(status=OutcomeStatus.SAMPLED, failure_code="", sample=sample_at(PLAN[0])),
                SampleOutcome(status=OutcomeStatus.MISSING, failure_code="P10_STORE_MISSING", sample=None),
                SampleOutcome(status=OutcomeStatus.INTEGRITY_FAILURE, failure_code="P9_STORE_CORRUPTION", sample=None))
    attempt = mg.attempt_from_outcomes(plan, PLAN, outcomes)
    assert attempt.content() == {"schema_version": mg.ATTEMPT_SCHEMA_VERSION, "plan_digest": plan,
                                 "cutoffs": [c.content() for c in PLAN], "disposition": mg.ATTEMPT_DISPOSITION,
                                 "outcomes": [["SAMPLED", ""], ["MISSING", "P10_STORE_MISSING"], ["INTEGRITY_FAILURE", "P9_STORE_CORRUPTION"]]}
    assert mg.parse_attempt(attempt.to_bytes()) == attempt and attempt.attempt_digest == domain_digest(mg.ATTEMPT_DOMAIN, attempt.content())
    text = attempt.to_bytes().decode("utf-8")
    assert "watch-a" not in text and "issuer-a" not in text and outcomes[0].sample.sample_digest not in text   # 標本は残さない
    complete = tuple(SampleOutcome(status=OutcomeStatus.SAMPLED, failure_code="", sample=sample_at(c)) for c in PLAN)
    with pytest.raises(mg.MemoryGenerationError) as exc:
        mg.attempt_from_outcomes(plan, PLAN, complete)
    assert exc.value.code == mg.ATTEMPT_INVALID                                                         # 完全な計画は試行の証拠ではない
    with pytest.raises(mg.MemoryGenerationError):
        mg.AttemptRecord(plan_digest=plan, cutoffs=PLAN, outcomes=(("MISSING", "lower case detail"),) * 3)


def test_staleness_is_a_label_from_an_explicit_evaluation_cutoff_not_a_clock() -> None:
    gen = generation()
    verified = mg.verify_generation_records(sealed(gen), expected_generation_digest=gen.generation_digest)
    assert mg.staleness_of(verified, evaluation_cutoff=cutoff(13), window_days=3) is StalenessLabel.FRESH
    assert mg.staleness_of(verified, evaluation_cutoff=cutoff(20), window_days=3) is StalenessLabel.STALE
    with pytest.raises(mg.MemoryGenerationError) as exc:
        mg.staleness_of(verified, evaluation_cutoff=cutoff(11), window_days=3)
    assert exc.value.code == mg.CUTOFF_ORDER_INVALID
