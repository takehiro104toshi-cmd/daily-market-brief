"""P4-3b2c 並走公開（`/v2`）の構造ガード（Phase 4 P4-3b2c）。

検証するのは **公開統合の境界だけ**である:

- legacy Pages tree が `/v2` 追加の前後で byte 単位に不変であること
- `/v2` が承認済み 5 file ちょうどで、名前指定でのみ接ぎ木されること
- 本番の Pages writer / deployer が**1 本のまま**であること
- 期待された `/v2` の失敗が legacy 配信を止めず、legacy の破損は必ず止めること
- 鮮度契約（24 時間 / 3 暦日）が境界値で効くこと
- 本番選定が main 限定であり、明示 baseline 無しでは成立しないこと
- root 切替・notifier・`main.py`・schedule・concurrency に触れていないこと

**実 GitHub API を呼ばない。ネットワークを使わない。** 実 Pages へも deploy しない。
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

PRODUCTION_WORKFLOW = WORKFLOW_DIR / "daily-market-brief.yml"
PREVIEW_WORKFLOW = WORKFLOW_DIR / "p43b2c-pages-preview.yml"
HANDOFF_WORKFLOW = WORKFLOW_DIR / "p43b2b-delivery-handoff.yml"

MANIFEST_PATH = REPO_ROOT / "scripts" / "p43b2c_pages_manifest.py"
SELECTOR_PATH = REPO_ROOT / "scripts" / "p43b2c_select_producer.py"
GATE_PATH = REPO_ROOT / "scripts" / "p43b2c_v2_gate.py"
GRAFT_PATH = REPO_ROOT / "scripts" / "p43b2c_graft_v2.py"
FROZEN_SELECTOR_PATH = REPO_ROOT / "scripts" / "p43b2b_select_run.py"

B2A_MODULE = REPO_ROOT / "src" / "intelligence" / "reports" / "pages_parallel.py"
INDEX_TEMPLATE = REPO_ROOT / "docs" / "pages" / "v2_index.html"
MAIN_PY = REPO_ROOT / "main.py"
CONFIG = REPO_ROOT / "config.yaml"
PREVIEW_TRIGGER = REPO_ROOT / ".github" / "p43b2c_preview_trigger"

PREVIEW_ARTIFACT = "full-pages-site-preview"
SESSION = "2026-09-15"
APPROVED_NAMES = sorted(["index.html", "latest_morning_brief.md", "latest_morning_brief.json",
                         f"{SESSION}_morning_brief.md", f"{SESSION}_morning_brief.json"])


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manifest = _load(MANIFEST_PATH, "p43b2c_pages_manifest")
selector = _load(SELECTOR_PATH, "p43b2c_select_producer")
gate = _load(GATE_PATH, "p43b2c_v2_gate")
graft = _load(GRAFT_PATH, "p43b2c_graft_v2")


# ---------------------------------------------------------------- helpers

def workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def executable_text(path: Path) -> str:
    """実行される内容のみ（コメントは落ちる）。散文で「〜しない」検査を汚さない。"""
    return yaml.safe_dump(workflow(path), allow_unicode=True, sort_keys=True)


def steps(path: Path, job: str) -> list:
    return (workflow(path).get("jobs") or {}).get(job, {}).get("steps") or []


def run_bodies(path: Path, job: str) -> str:
    return "\n".join(str(step.get("run", "")) for step in steps(path, job))


def step_named(path: Path, job: str, name: str) -> dict:
    for step in steps(path, job):
        if step.get("name") == name:
            return step
    raise AssertionError(f"step not found: {name}")


def step_index(path: Path, job: str, name: str) -> int:
    for index, step in enumerate(steps(path, job)):
        if step.get("name") == name:
            return index
    raise AssertionError(f"step not found: {name}")


def _executable_source(path: Path) -> str:
    """docstring と comment を除いた実行内容（散文で「〜しない」検査を汚さない）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            del body[0]
    return ast.unparse(tree)


def make_legacy_site(tmp_path, *, name="pages-site", days=2):
    """本番 `Prepare GitHub Pages site` と同じ形の legacy tree を作る。"""
    site = tmp_path / name
    (site / "history").mkdir(parents=True)
    (site / "index.html").write_text("<html>legacy root</html>\n", encoding="utf-8")
    for day in range(days):
        date_dir = site / "history" / f"2026-09-{10 + day:02d}"
        date_dir.mkdir()
        for slot in ("pre_market", "evening"):
            (date_dir / f"{slot}.html").write_text(f"<html>{slot}</html>\n", encoding="utf-8")
    return site


def make_staged_v2(tmp_path, *, names=None, name="stage"):
    staged = tmp_path / name / "v2"
    staged.mkdir(parents=True)
    for filename in (names or APPROVED_NAMES):
        (staged / filename).write_text(f"content of {filename}\n", encoding="utf-8")
    return staged


def gate_verdict(tmp_path, names=None, *, result="PASS"):
    path = tmp_path / "gate.json"
    path.write_text(json.dumps({"result": result,
                                "published_names": names or APPROVED_NAMES}),
                    encoding="utf-8")
    return path


def b2a_output(*, ok=True, session=SESSION, names=None, rejected_reason=""):
    """凍結 b2a の stdout を模した marker 列（内容そのものは作らない）。"""
    if not ok:
        return ("::P43B2A_REJECTED::" + json.dumps({"reason": rejected_reason}) + "\n"
                + "::P43B2A_END::" + json.dumps({"result": "REJECTED"}) + "\n")
    published = sorted(names or APPROVED_NAMES)
    return ("::P43B2A_INPUT::" + json.dumps({"session_date": session,
                                             "reference_session": "2026-09-14"}) + "\n"
            + "::P43B2A_PUBLISHED::" + json.dumps({"count": len(published),
                                                   "names": published}) + "\n"
            + "::P43B2A_END::" + json.dumps({"result": "OK", "session_date": session}) + "\n")


# ================================================================ legacy manifest

def test_manifest_is_deterministic_and_carries_path_sha_and_size(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    entries = manifest.build_manifest(site)
    assert entries == manifest.build_manifest(site), "同じ tree からは同じ manifest"
    assert [e["path"] for e in entries] == sorted(e["path"] for e in entries)
    for entry in entries:
        assert set(entry) == {"path", "sha256", "bytes"}
        assert not entry["path"].startswith("/")
    index = next(e for e in entries if e["path"] == "index.html")
    assert index["sha256"] == hashlib.sha256(
        (site / "index.html").read_bytes()).hexdigest()
    assert index["bytes"] == len((site / "index.html").read_bytes())


def test_legacy_manifest_equality_excludes_only_v2(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    before = manifest.build_manifest(site)
    (site / "v2").mkdir()
    for filename in APPROVED_NAMES:
        (site / "v2" / filename).write_text("v2\n", encoding="utf-8")
    after = manifest.build_manifest(site, exclude_top_level=["v2"])
    assert manifest.compare_manifests(before, after)["equal"]
    assert manifest.manifest_digest(before) == manifest.manifest_digest(after)


def test_legacy_index_and_history_stay_byte_identical(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    before = {e["path"]: e["sha256"] for e in manifest.build_manifest(site)}
    graft.graft(staging_v2=make_staged_v2(tmp_path), pages_site=site, names=APPROVED_NAMES)
    after = {e["path"]: e["sha256"]
             for e in manifest.build_manifest(site, exclude_top_level=["v2"])}
    assert after == before
    assert before["index.html"] == after["index.html"]
    history = [p for p in before if p.startswith("history/")]
    assert history, "history 配下を検査対象に含めること"
    for path in history:
        assert before[path] == after[path]


def test_any_legacy_mutation_is_detected(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    before = manifest.build_manifest(site)
    (site / "index.html").write_text("<html>tampered</html>\n", encoding="utf-8")
    difference = manifest.compare_manifests(before, manifest.build_manifest(site))
    assert not difference["equal"]
    assert "index.html" in difference["changed"]


def test_symlinks_are_rejected(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    outside = tmp_path / "outside.html"
    outside.write_text("<html>outside</html>\n", encoding="utf-8")
    (site / "linked.html").symlink_to(outside)
    with pytest.raises(manifest.ManifestRejected, match="symlink"):
        manifest.build_manifest(site)


def test_symlinked_directories_are_rejected(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    (site / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(manifest.ManifestRejected, match="symlink"):
        manifest.build_manifest(site)


def test_path_escape_is_rejected(tmp_path) -> None:
    """root の外を指す entry を manifest へ載せない。"""
    site = make_legacy_site(tmp_path)
    (site / "history" / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(manifest.ManifestRejected):
        manifest.build_manifest(site)


def test_dot_residue_is_rejected(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    staging_residue = site / ".v2.tmp-abcd"
    staging_residue.mkdir()
    (staging_residue / "leftover.html").write_text("x\n", encoding="utf-8")
    entries = manifest.build_manifest(site)
    assert manifest.dot_entries(entries), "dot entry を検出すること"
    with pytest.raises(manifest.ManifestRejected, match="dot entry"):
        manifest.require_legacy_invariants(entries)


def test_legacy_invariants_do_not_hardcode_a_file_count(tmp_path) -> None:
    """history は毎日増えるため、件数を固定しない。"""
    small = manifest.build_manifest(make_legacy_site(tmp_path, name="a", days=1))
    large = manifest.build_manifest(make_legacy_site(tmp_path, name="b", days=9))
    manifest.require_legacy_invariants(small)
    manifest.require_legacy_invariants(large)
    assert len(small) != len(large)
    assert "271" not in _executable_source(MANIFEST_PATH)


def test_missing_legacy_index_is_fatal(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    (site / "index.html").unlink()
    with pytest.raises(manifest.ManifestRejected, match="index.html"):
        manifest.require_legacy_invariants(manifest.build_manifest(site))


def test_legacy_manifest_must_not_contain_v2(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    (site / "v2").mkdir()
    (site / "v2" / "index.html").write_text("v2\n", encoding="utf-8")
    with pytest.raises(manifest.ManifestRejected, match="v2"):
        manifest.require_legacy_invariants(manifest.build_manifest(site))


# ================================================================ v2 graft

def test_graft_places_exactly_the_five_approved_files(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    record = graft.graft(staging_v2=make_staged_v2(tmp_path), pages_site=site,
                         names=APPROVED_NAMES)
    assert record["count"] == 5 and record["names"] == APPROVED_NAMES
    assert record["session_date"] == SESSION
    assert sorted(p.name for p in (site / "v2").iterdir()) == APPROVED_NAMES


def test_graft_rejects_a_sixth_file(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    staged = make_staged_v2(tmp_path)
    (staged / "extra.html").write_text("x\n", encoding="utf-8")
    with pytest.raises(graft.GraftRejected, match="approved set"):
        graft.graft(staging_v2=staged, pages_site=site, names=APPROVED_NAMES)
    assert not (site / "v2").exists(), "拒否時に pages-site を汚さない"


def test_graft_rejects_a_missing_file(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    staged = make_staged_v2(tmp_path)
    (staged / "latest_morning_brief.md").unlink()
    with pytest.raises(graft.GraftRejected):
        graft.graft(staging_v2=staged, pages_site=site, names=APPROVED_NAMES)
    assert not (site / "v2").exists()


def test_graft_rejects_a_subdirectory(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    staged = make_staged_v2(tmp_path)
    (staged / "nested").mkdir()
    with pytest.raises(graft.GraftRejected):
        graft.graft(staging_v2=staged, pages_site=site, names=APPROVED_NAMES)


def test_graft_rejects_a_symlinked_member(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    staged = make_staged_v2(tmp_path)
    target = tmp_path / "target.md"
    target.write_text("elsewhere\n", encoding="utf-8")
    (staged / "latest_morning_brief.md").unlink()
    (staged / "latest_morning_brief.md").symlink_to(target)
    with pytest.raises(graft.GraftRejected, match="symlink"):
        graft.graft(staging_v2=staged, pages_site=site, names=APPROVED_NAMES)
    assert not (site / "v2").exists()


def test_graft_rejects_an_existing_destination(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    (site / "v2").mkdir()
    with pytest.raises(graft.GraftRejected, match="already exists"):
        graft.graft(staging_v2=make_staged_v2(tmp_path), pages_site=site,
                    names=APPROVED_NAMES)


@pytest.mark.parametrize("names,fragment", [
    (APPROVED_NAMES[:4], "exactly 5"),
    (APPROVED_NAMES + ["sixth.md"], "exactly 5"),
    (["index.html", "latest_morning_brief.md", "latest_morning_brief.json",
      f"{SESSION}_morning_brief.md", "2026-09-14_morning_brief.json"], "session date"),
    (["index.html", "latest_morning_brief.md", "latest_morning_brief.json",
      f"{SESSION}_morning_brief.md", f"{SESSION}_morning_brief.txt"], "dated pair"),
    (["../escape.md", "latest_morning_brief.md", "latest_morning_brief.json",
      f"{SESSION}_morning_brief.md", f"{SESSION}_morning_brief.json"], "plain file name"),
])
def test_graft_name_contract_fails_closed(names, fragment) -> None:
    with pytest.raises(graft.GraftRejected, match=fragment):
        graft.approved_names(names)


def test_graft_never_discovers_files_by_wildcard_or_recursion() -> None:
    code = _executable_source(GRAFT_PATH)
    for forbidden in ("glob(", "rglob", "os.walk", "copytree", "shutil.copytree",
                      "*.md", "*.json", "fnmatch"):
        assert forbidden not in code, forbidden
    assert "shutil.copyfile" in code, "論理名を 1 つずつ copy する"


def test_graft_verifies_bytes_after_copying(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    staged = make_staged_v2(tmp_path)
    record = graft.graft(staging_v2=staged, pages_site=site, names=APPROVED_NAMES)
    for name in APPROVED_NAMES:
        assert (site / "v2" / name).read_bytes() == (staged / name).read_bytes()
        assert record["sha256"][name] == hashlib.sha256(
            (staged / name).read_bytes()).hexdigest()


def test_verify_v2_shape_rejects_a_mismatched_set(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    graft.graft(staging_v2=make_staged_v2(tmp_path), pages_site=site, names=APPROVED_NAMES)
    manifest.verify_v2_shape(site, APPROVED_NAMES)
    (site / "v2" / "sixth.html").write_text("x\n", encoding="utf-8")
    with pytest.raises(manifest.ManifestRejected, match="approved set"):
        manifest.verify_v2_shape(site, APPROVED_NAMES)


# ================================================================ freshness gate

def _selection(created_at="2026-09-15T06:52:28Z"):
    return {"artifact_created_at": created_at}


def test_gate_passes_a_fresh_artifact_and_current_session() -> None:
    verdict = gate.classify(selection=_selection(), b2a_output=b2a_output(),
                            now_utc="2026-09-15T11:24:00Z", jst_today=SESSION)
    assert verdict["result"] == gate.RESULT_PASS
    assert verdict["session_lag_days"] == 0
    assert verdict["published_names"] == APPROVED_NAMES


def test_frozen_beta_freshness_limits() -> None:
    assert gate.MAX_ARTIFACT_AGE_HOURS == 24
    assert gate.MAX_SESSION_LAG_DAYS == 3


@pytest.mark.parametrize("now,expected", [
    ("2026-09-16T06:52:28Z", gate.RESULT_PASS),           # ちょうど 24h（境界は通す）
    ("2026-09-16T06:52:29Z", gate.RESULT_UNAVAILABLE),    # 24h を 1 秒でも超えたら不可
])
def test_artifact_age_boundary(now, expected) -> None:
    verdict = gate.classify(selection=_selection(), b2a_output=b2a_output(),
                            now_utc=now, jst_today="2026-09-16")
    assert verdict["result"] == expected
    if expected == gate.RESULT_UNAVAILABLE:
        assert verdict["reason_code"] == "ARTIFACT_TOO_OLD"


@pytest.mark.parametrize("jst_today,expected", [
    ("2026-09-18", gate.RESULT_PASS),                     # ちょうど 3 暦日
    ("2026-09-19", gate.RESULT_UNAVAILABLE),              # 4 暦日は不可
])
def test_session_lag_boundary(jst_today, expected) -> None:
    verdict = gate.classify(selection=_selection(created_at="2026-09-18T23:00:00Z"),
                            b2a_output=b2a_output(session=SESSION),
                            now_utc="2026-09-19T00:00:00Z", jst_today=jst_today)
    assert verdict["result"] == expected
    if expected == gate.RESULT_UNAVAILABLE:
        assert verdict["reason_code"] == "SESSION_TOO_OLD"


def test_stale_artifact_is_never_published_as_current() -> None:
    verdict = gate.classify(selection=_selection(created_at="2026-09-01T00:00:00Z"),
                            b2a_output=b2a_output(session="2026-09-01"),
                            now_utc="2026-09-15T00:00:00Z", jst_today=SESSION)
    assert verdict["result"] == gate.RESULT_UNAVAILABLE
    assert verdict["result"] != gate.RESULT_PASS


def test_b2a_rejection_becomes_v2_rejected() -> None:
    verdict = gate.classify(
        selection=_selection(),
        b2a_output=b2a_output(ok=False, rejected_reason="artifact set is not the approved four"),
        now_utc="2026-09-15T11:24:00Z", jst_today=SESSION)
    assert verdict["result"] == gate.RESULT_REJECTED
    assert verdict["reason_code"] == "B2A_REJECTED"


def test_unreadable_b2a_output_becomes_internal_error() -> None:
    verdict = gate.classify(selection=_selection(), b2a_output="nothing useful here",
                            now_utc="2026-09-15T11:24:00Z", jst_today=SESSION)
    assert verdict["result"] == gate.RESULT_INTERNAL_ERROR


@pytest.mark.parametrize("now,jst,expected", [
    ("", SESSION, gate.RESULT_INTERNAL_ERROR),
    ("2026-09-15T11:24:00Z", "", gate.RESULT_INTERNAL_ERROR),
    ("2026-09-15T00:00:00Z", "not-a-date", gate.RESULT_INTERNAL_ERROR),
])
def test_unusable_clock_inputs_fail_closed(now, jst, expected) -> None:
    verdict = gate.classify(selection=_selection(), b2a_output=b2a_output(),
                            now_utc=now, jst_today=jst)
    assert verdict["result"] == expected


def test_future_session_would_still_be_rejected_here() -> None:
    """未来 session の一次拒否は凍結 b2a。ここは通過してきた場合の防御。"""
    verdict = gate.classify(selection=_selection(),
                            b2a_output=b2a_output(session="2026-09-20"),
                            now_utc="2026-09-15T11:24:00Z", jst_today=SESSION)
    assert verdict["result"] == gate.RESULT_REJECTED
    assert verdict["reason_code"] == "FUTURE_SESSION"


def test_b2a_still_rejects_future_sessions_itself() -> None:
    """凍結 b2a 側の一次防御が残っていること（b2c で緩めていない）。"""
    source = B2A_MODULE.read_text(encoding="utf-8")
    assert "if session_date > jst_today:" in source


def test_gate_does_not_duplicate_b2a_or_signal_contracts() -> None:
    code = _executable_source(GATE_PATH)
    for duplicated in ("PUBLIC_KEYS", "FORBIDDEN_PUBLIC", "SIGNAL_LEVEL_JA", "markdown_sha256",
                       "上昇寄り", "下落寄り", "reference_session ==", "claim_id"):
        assert duplicated not in code, duplicated
    assert "holiday" not in code.lower(), "祝日カレンダーを実装しない"


def test_gate_never_reads_the_clock_itself() -> None:
    code = _executable_source(GATE_PATH)
    for forbidden in ("datetime.now(", "date.today(", "time.time("):
        assert forbidden not in code, forbidden


def test_gate_results_are_the_four_typed_values() -> None:
    assert set(gate.RESULTS) == {"PASS", "V2_UNAVAILABLE", "V2_REJECTED", "V2_INTERNAL_ERROR"}


# ================================================================ production selector

def _contract(**overrides):
    values = {"mode": "production", "workflow_file": "p43b1-morning-delivery-producer.yml",
              "branch": "main", "baseline": "abc1234",
              "eligible_events": ["push", "workflow_dispatch"],
              "artifact_name": "morning-delivery-v2",
              "attempt_policy": "first-attempt-only"}
    values.update(overrides)
    return selector.ProducerContract(**values)


def test_production_mode_requires_the_main_branch() -> None:
    with pytest.raises(selector.ConfigurationInvalid, match="main"):
        _contract(branch="claude/investment-intelligence-phase0-rvdplu")


def test_production_mode_requires_an_explicit_baseline() -> None:
    with pytest.raises(selector.ConfigurationInvalid, match="baseline"):
        _contract(baseline="")


def test_production_trust_must_not_use_the_validation_baseline() -> None:
    """feature branch 検証用 baseline へ本番 trust を縛らない。"""
    with pytest.raises(selector.ConfigurationInvalid, match="validation baseline"):
        _contract(baseline=selector.VALIDATION_ONLY_BASELINE)


def test_preview_mode_may_use_explicit_feature_branch_values() -> None:
    contract = _contract(mode="preview",
                         branch="claude/investment-intelligence-phase0-rvdplu",
                         baseline=selector.VALIDATION_ONLY_BASELINE)
    assert contract.mode == "preview"


def test_modes_are_structurally_distinct_and_never_inferred() -> None:
    assert selector.MODES == ("production", "preview")
    with pytest.raises(selector.ConfigurationInvalid, match="mode"):
        _contract(mode="")
    code = _executable_source(SELECTOR_PATH)
    for forbidden in ("github.ref", "GITHUB_REF", "GITHUB_HEAD_REF", "GITHUB_BASE_REF"):
        assert forbidden not in code, f"branch/baseline を推測しない: {forbidden}"


def test_event_policy_is_explicit_and_extensible() -> None:
    with pytest.raises(selector.ConfigurationInvalid, match="explicitly"):
        _contract(eligible_events=[])
    with pytest.raises(selector.ConfigurationInvalid, match="unknown"):
        _contract(eligible_events=["push", "pull_request"])
    assert "schedule" in selector.KNOWN_EVENTS, "将来の cron 対応で trust を書き換えない"
    assert "schedule" not in _contract().eligible_events, "beta では schedule を渡さない"


def test_attempt_policy_is_explicit() -> None:
    assert selector.ATTEMPT_POLICIES == ("first-attempt-only", "verified-attempt")
    assert selector.DEFAULT_ATTEMPT_POLICY == "first-attempt-only"
    with pytest.raises(selector.ConfigurationInvalid, match="attempt policy"):
        _contract(attempt_policy="whatever")


def a_run(**overrides):
    run = {"id": 111, "run_number": 7, "run_attempt": 1, "event": "push",
           "status": "completed", "conclusion": "success",
           "head_branch": "main", "head_sha": "f" * 40,
           "path": ".github/workflows/p43b1-morning-delivery-producer.yml"}
    run.update(overrides)
    return run


def test_eligible_production_run_is_accepted() -> None:
    ok, reason = selector.run_is_eligible(a_run(), _contract())
    assert ok and reason == ""


@pytest.mark.parametrize("override,fragment", [
    ({"path": ".github/workflows/p2d-market-pilot.yml"}, "not the producer"),
    ({"head_branch": "claude/investment-intelligence-phase0-rvdplu"}, "not the main branch"),
    ({"status": "in_progress"}, "not completed"),
    ({"conclusion": "failure"}, "did not succeed"),
    ({"event": "schedule"}, "event is not eligible"),
    ({"run_attempt": 2}, "not 1 under first-attempt-only"),
    ({"head_sha": ""}, "head_sha is unusable"),
])
def test_ineligible_production_runs_are_rejected(override, fragment) -> None:
    ok, reason = selector.run_is_eligible(a_run(**override), _contract())
    assert not ok and fragment in reason, reason


def test_verified_attempt_policy_admits_reruns_only_when_bindable() -> None:
    contract = _contract(attempt_policy="verified-attempt")
    ok, _ = selector.run_is_eligible(a_run(run_attempt=3), contract)
    assert ok, "policy 次第で rerun を候補にできる"
    started = "2026-09-15T06:00:00Z"
    assert selector.artifact_belongs_to_attempt({"created_at": "2026-09-15T06:52:28Z"}, started)
    assert not selector.artifact_belongs_to_attempt({"created_at": "2026-09-15T05:00:00Z"},
                                                    started)
    assert not selector.artifact_belongs_to_attempt({}, started), "帰属不明は推測しない"


def _patch_request(monkeypatch, responses):
    def kind(path):
        if path.endswith("/artifacts"):
            return "/artifacts"
        if "/compare/" in path:
            return "/compare/"
        if "/attempts/" in path:
            return "/attempts/"
        if path.endswith("/runs"):
            return "/runs"
        raise AssertionError(f"unexpected API path: {path}")

    def fake(api_base, path, *, auth, query=None, timeout=30.0):
        payload = responses.get(kind(path))
        if payload is None:
            raise AssertionError(f"unstubbed API path: {path}")
        if isinstance(payload, Exception):
            raise payload
        return payload
    monkeypatch.setattr(selector, "_request", fake)


def test_attempt_start_time_is_required_for_rerun_attribution(monkeypatch) -> None:
    _patch_request(monkeypatch, {"/attempts/": {}})
    with pytest.raises(selector.SelectionRejected, match="cannot be established"):
        selector.attempt_started_at("https://api", "o/r", 111, 2, auth="x")


@pytest.mark.parametrize("status", ["identical", "ahead"])
def test_trusted_compare_statuses_are_accepted(monkeypatch, status) -> None:
    _patch_request(monkeypatch, {"/compare/": {"status": status, "behind_by": 0}})
    assert selector.trust_status("https://api", "o/r", "f" * 40, auth="x",
                                 baseline="abc1234") == status


@pytest.mark.parametrize("payload,fragment", [
    ({"status": "diverged", "behind_by": 0}, "not trusted"),
    ({"status": "behind", "behind_by": 0}, "not trusted"),
    ({"status": "ahead", "behind_by": 3}, "is behind"),
    ({"behind_by": 0}, "status"),
    ({"status": "ahead"}, "behind_by"),
    ({"status": "ahead", "behind_by": True}, "behind_by"),
])
def test_untrusted_head_fails_closed(monkeypatch, payload, fragment) -> None:
    _patch_request(monkeypatch, {"/compare/": payload})
    with pytest.raises(selector.SelectionRejected, match=fragment):
        selector.trust_status("https://api", "o/r", "f" * 40, auth="x", baseline="abc1234")


def an_artifact(**overrides):
    artifact = {"id": 999, "name": "morning-delivery-v2", "size_in_bytes": 2958,
                "expired": False, "created_at": "2026-09-15T06:52:28Z",
                "digest": "sha256:" + "d" * 64}
    artifact.update(overrides)
    return artifact


@pytest.mark.parametrize("artifacts,fragment", [
    ([], "found 0"),
    ([an_artifact(), an_artifact(id=1000)], "found 2"),
    ([an_artifact(expired=True)], "expired"),
    ([an_artifact(size_in_bytes=0)], "empty"),
    ([an_artifact(size_in_bytes=1024 * 1024 + 1)], "implausibly large"),
    ([an_artifact(created_at="")], "created_at"),
])
def test_artifact_selection_fails_closed(monkeypatch, artifacts, fragment) -> None:
    _patch_request(monkeypatch, {"/artifacts": {"artifacts": artifacts}})
    with pytest.raises(selector.SelectionRejected, match=fragment):
        selector.select_artifact("https://api", "o/r", 111, auth="x", contract=_contract())


def test_selection_end_to_end_takes_the_first_eligible(monkeypatch) -> None:
    _patch_request(monkeypatch, {
        "/runs": {"workflow_runs": [a_run(id=222, run_attempt=2),
                                    a_run(id=333, head_branch="release"),
                                    a_run(id=444)]},
        "/compare/": {"status": "ahead", "behind_by": 0},
        "/artifacts": {"artifacts": [an_artifact()]}})
    chosen = selector.select("https://api", "o/r", auth="x", contract=_contract())
    assert chosen["run"]["id"] == 444
    assert chosen["attempt_attribution"] == "first-attempt"


def test_main_reports_configuration_invalid_without_failing(monkeypatch, capsys) -> None:
    """設定不備は safe-skip（legacy 配信を落とさない）。"""
    monkeypatch.setenv("GITHUB_TOKEN", "sentinel-credential-value")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert selector.main(["--mode", "production", "--producer-branch", "main",
                          "--trust-baseline", "", "--eligible-events", "push",
                          "--repository", "o/r"]) == 0
    out = capsys.readouterr().out
    assert "V2_INTERNAL_ERROR" in out and "CONFIGURATION_INVALID" in out


def test_main_reports_unavailable_without_failing(monkeypatch, capsys, tmp_path) -> None:
    _patch_request(monkeypatch, {"/runs": {"workflow_runs": []}})
    output = tmp_path / "gh_output"
    output.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "sentinel-credential-value")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert selector.main(["--mode", "production", "--producer-branch", "main",
                          "--trust-baseline", "abc1234", "--eligible-events", "push",
                          "--repository", "o/r"]) == 0
    assert "result=V2_UNAVAILABLE" in output.read_text(encoding="utf-8")


def test_main_never_prints_the_credential(monkeypatch, capsys, tmp_path) -> None:
    sentinel = "sentinel-credential-value"
    _patch_request(monkeypatch, {
        "/runs": {"workflow_runs": [a_run(id=444)]},
        "/compare/": {"status": "identical", "behind_by": 0},
        "/artifacts": {"artifacts": [an_artifact()]}})
    output = tmp_path / "gh_output"
    output.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", sentinel)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert selector.main(["--mode", "production", "--producer-branch", "main",
                          "--trust-baseline", "abc1234", "--eligible-events", "push",
                          "--repository", "o/r"]) == 0
    out = capsys.readouterr().out
    assert sentinel not in out
    written = output.read_text(encoding="utf-8")
    assert sentinel not in written and "result=SELECTED" in written
    assert "artifact_created_at=2026-09-15T06:52:28Z" in written


# ================================================================ script boundary

@pytest.mark.parametrize("path", [MANIFEST_PATH, SELECTOR_PATH, GATE_PATH, GRAFT_PATH],
                         ids=lambda p: p.name)
def test_b2c_scripts_are_stdlib_only_and_never_import_vnext(path) -> None:
    tops = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            tops.update(a.name.split(".")[0] for a in node.names)
    assert "src" not in tops, "CI 配管は vNext を import しない"
    assert tops <= set(sys.stdlib_module_names), sorted(tops - set(sys.stdlib_module_names))


@pytest.mark.parametrize("path", [MANIFEST_PATH, SELECTOR_PATH, GATE_PATH, GRAFT_PATH],
                         ids=lambda p: p.name)
def test_b2c_scripts_never_write_the_repository_or_deploy(path) -> None:
    code = _executable_source(path)
    for forbidden in ("subprocess", "os.system", "Popen", "git ", "output/v2",
                      "upload-pages", "deploy-pages", "notifiers", "main.py"):
        assert forbidden not in code, forbidden


def test_the_frozen_b2b_selector_is_untouched() -> None:
    source = FROZEN_SELECTOR_PATH.read_text(encoding="utf-8")
    assert 'PRODUCER_BRANCH = "claude/investment-intelligence-phase0-rvdplu"' in source
    assert 'TRUST_BASELINE = "a2a6222"' in source
    assert "REQUIRED_RUN_ATTEMPT = 1" in source
    assert "p43b2c" not in source, "凍結 validation selector へ b2c を混ぜない"


def test_the_production_selector_is_not_a_copy_of_the_frozen_one() -> None:
    code = _executable_source(SELECTOR_PATH)
    assert "claude/investment-intelligence-phase0-rvdplu" not in code, \
        "feature branch を本番 selector へ埋め込まない"
    assert "REQUIRED_RUN_ATTEMPT" not in code, "説明のない永続 invariant を持ち込まない"
    assert selector.PRODUCTION_BRANCH == "main"


def test_b2a_and_its_template_are_unchanged() -> None:
    import re
    source = B2A_MODULE.read_text(encoding="utf-8")
    assert 'PAGES_PARALLEL_VERSION = "0.1.0"' in source
    assert "p43b2c" not in source, "凍結 b2a へ b2c を混ぜない"
    template = INDEX_TEMPLATE.read_text(encoding="utf-8")
    assert re.findall(r'href="([^"]+)"', template) == [
        "latest_morning_brief.md", "latest_morning_brief.json", "../"]


# ================================================================ production workflow

def test_production_permissions_add_only_actions_read() -> None:
    assert workflow(PRODUCTION_WORKFLOW).get("permissions") == {
        "contents": "write", "pages": "write", "id-token": "write", "actions": "read"}


def test_production_schedule_and_concurrency_are_unchanged() -> None:
    data = workflow(PRODUCTION_WORKFLOW)
    triggers = data.get("on", data.get(True))
    assert len(triggers["schedule"]) == 12, "既存 12 本の cron を変えない"
    assert data["concurrency"] == {
        "group": "daily-market-brief-${{ github.ref }}-"
                 "${{ github.event.inputs.report_slot || github.event.schedule || 'manual' }}",
        "cancel-in-progress": False}
    assert set(data["jobs"]) == {"generate-report", "deploy-pages"}


def test_legacy_pages_preparation_is_unchanged() -> None:
    body = str(step_named(PRODUCTION_WORKFLOW, "generate-report",
                          "Prepare GitHub Pages site").get("run", ""))
    assert "cp output/latest_market_brief.html pages-site/index.html" in body
    assert "cp -r output/history/* pages-site/history/" in body
    assert "v2" not in body, "legacy 準備 step に v2 を混ぜない"


def test_assembly_order_is_prepare_manifest_select_stage_graft_verify_upload() -> None:
    order = [step_index(PRODUCTION_WORKFLOW, "generate-report", name) for name in (
        "Prepare GitHub Pages site",
        "Capture the legacy Pages manifest before /v2",
        "Select a trusted producer artifact for /v2",
        "Validate and stage /v2 outside the pages site",
        "Graft the validated /v2 into the pages site",
        "Verify the legacy Pages tree is unchanged",
        "Upload GitHub Pages artifact")]
    assert order == sorted(order), order


def test_b2a_is_staged_outside_the_pages_site() -> None:
    """b2a は destination.parent へ staging を作るため、宛先を pages-site にしない。"""
    body = run_bodies(PRODUCTION_WORKFLOW, "generate-report")
    assert '--v2-destination "${stage}/v2"' in body
    assert "--v2-destination pages-site" not in body
    assert '--artifact-dir "${RUNNER_TEMP}/p43b2c_download/${ARTIFACT_NAME}"' in body


def test_only_the_graft_step_writes_into_the_pages_site() -> None:
    writers = []
    for step in steps(PRODUCTION_WORKFLOW, "generate-report"):
        body = str(step.get("run", ""))
        if "--pages-site pages-site" in body or "mkdir -p pages-site" in body:
            writers.append(step.get("name"))
    assert writers == ["Prepare GitHub Pages site",
                       "Graft the validated /v2 into the pages site"], writers


def test_graft_and_verify_are_strict_while_pre_mutation_steps_are_fail_safe() -> None:
    strict = ("Graft the validated /v2 into the pages site",
              "Verify the legacy Pages tree is unchanged",
              "Capture the legacy Pages manifest before /v2")
    for name in strict:
        step = step_named(PRODUCTION_WORKFLOW, "generate-report", name)
        assert step.get("continue-on-error") is None, name
        assert "set -euo pipefail" in str(step.get("run", "")), name


def test_continue_on_error_is_narrow_and_only_on_the_download_step() -> None:
    """blanket な continue-on-error を使わない。"""
    tolerated = [s.get("name") or s.get("uses")
                 for s in steps(PRODUCTION_WORKFLOW, "generate-report")
                 if s.get("continue-on-error")]
    assert tolerated == ["Download the selected producer artifact"], tolerated
    assert workflow(PRODUCTION_WORKFLOW)["jobs"]["generate-report"].get(
        "continue-on-error") is None
    assert workflow(PRODUCTION_WORKFLOW)["jobs"]["deploy-pages"].get(
        "continue-on-error") is None


def test_v2_steps_are_skipped_when_nothing_was_selected() -> None:
    assert step_named(PRODUCTION_WORKFLOW, "generate-report",
                      "Download the selected producer artifact")["if"] == \
        "steps.p43b2c_select.outputs.result == 'SELECTED'"
    assert step_named(PRODUCTION_WORKFLOW, "generate-report",
                      "Graft the validated /v2 into the pages site")["if"] == \
        "steps.p43b2c_stage.outputs.result == 'PASS'"


def test_verification_always_runs_even_without_v2() -> None:
    step = step_named(PRODUCTION_WORKFLOW, "generate-report",
                      "Verify the legacy Pages tree is unchanged")
    assert "if" not in step, "v2 の採否に関わらず legacy 不変を必ず検証する"
    body = str(step["run"])
    assert "--expect-v2 present" in body and "--expect-v2 absent" in body
    assert "hygiene --root pages-site" in body


def test_v2_status_is_visible_in_the_job_summary() -> None:
    body = str(step_named(PRODUCTION_WORKFLOW, "generate-report",
                          "Record the /v2 publication status").get("run", ""))
    assert "GITHUB_STEP_SUMMARY" in body
    assert "SELECT_RESULT" in body and "STAGE_RESULT" in body
    warnings = run_bodies(PRODUCTION_WORKFLOW, "generate-report")
    assert warnings.count("::warning::") >= 4, "safe-skip を必ず可視化する"


def test_production_uses_production_mode_with_a_non_validation_baseline() -> None:
    body = run_bodies(PRODUCTION_WORKFLOW, "generate-report")
    assert "--mode production" in body
    assert "--producer-branch main" in body
    assert "a2a6222" not in body, "本番 trust を検証 baseline へ縛らない"
    assert "--attempt-policy first-attempt-only" in body
    assert "--eligible-events push,workflow_dispatch" in body


def test_production_does_not_persist_v2_in_the_repository() -> None:
    text = executable_text(PRODUCTION_WORKFLOW)
    assert "output/v2" not in text
    commit = str(step_named(PRODUCTION_WORKFLOW, "generate-report",
                            "Commit and push report").get("run", ""))
    assert "v2" not in commit, "生成物の commit 対象に v2 を足さない"


def test_no_producer_schedule_was_added() -> None:
    producer = workflow(WORKFLOW_DIR / "p43b1-morning-delivery-producer.yml")
    triggers = producer.get("on", producer.get(True))
    assert "schedule" not in triggers, "beta では producer cron を足さない"


# ================================================================ single deployer

def test_exactly_one_pages_artifact_and_one_deployment() -> None:
    uploads, deploys = [], []
    for path in WORKFLOW_DIR.glob("*.yml"):
        data = workflow(path)
        for job, spec in (data.get("jobs") or {}).items():
            for step in spec.get("steps") or []:
                uses = str(step.get("uses", ""))
                if "upload-pages-artifact" in uses:
                    uploads.append(f"{path.name}:{job}")
                if "deploy-pages" in uses:
                    deploys.append(f"{path.name}:{job}")
    assert uploads == ["daily-market-brief.yml:generate-report"], uploads
    assert deploys == ["daily-market-brief.yml:deploy-pages"], deploys


def test_no_second_pages_writer_holds_pages_permissions() -> None:
    for path in WORKFLOW_DIR.glob("*.yml"):
        if path.name == PRODUCTION_WORKFLOW.name:
            continue
        data = workflow(path)
        permissions = data.get("permissions") or {}
        assert "pages" not in permissions, path.name
        assert "id-token" not in permissions, path.name
        for job, spec in (data.get("jobs") or {}).items():
            job_permissions = spec.get("permissions") or {}
            assert "pages" not in job_permissions, (path.name, job)
            assert "id-token" not in job_permissions, (path.name, job)


def test_deploy_job_is_unchanged() -> None:
    job = workflow(PRODUCTION_WORKFLOW)["jobs"]["deploy-pages"]
    assert job["needs"] == "generate-report"
    assert job["permissions"] == {"pages": "write", "id-token": "write"}
    assert job["environment"]["name"] == "github-pages"
    assert len(job["steps"]) == 1
    assert "concurrency" not in job, "本 gate では deploy 側の concurrency を足さない"


# ================================================================ preview workflow

def test_preview_workflow_never_touches_pages_actions() -> None:
    text = executable_text(PREVIEW_WORKFLOW)
    for forbidden in ("upload-pages-artifact", "deploy-pages", "configure-pages"):
        assert forbidden not in text, forbidden


def test_preview_workflow_holds_no_pages_or_oidc_permission() -> None:
    assert workflow(PREVIEW_WORKFLOW).get("permissions") == {
        "contents": "read", "actions": "read"}


def test_preview_uploads_one_ordinary_artifact() -> None:
    uploads = [s for s in steps(PREVIEW_WORKFLOW, "preview")
               if "upload-artifact" in str(s.get("uses", ""))]
    assert len(uploads) == 1
    with_ = uploads[0].get("with") or {}
    assert with_.get("name") == PREVIEW_ARTIFACT
    assert with_.get("retention-days") == 14
    assert with_.get("if-no-files-found") == "error"


def test_preview_uses_preview_mode_and_does_not_write_the_repository() -> None:
    body = run_bodies(PREVIEW_WORKFLOW, "preview")
    assert "--mode preview" in body
    assert "--mode production" not in body
    text = executable_text(PREVIEW_WORKFLOW)
    for forbidden in ("git add", "git commit", "git push", "notifiers", "main.py",
                      "output/v2"):
        assert forbidden not in text, forbidden
    assert "p43b2c_preview_site" in body, "preview tree は runner.temp に作る"


def test_preview_trigger_is_scoped_and_inert() -> None:
    """起動経路は専用 trigger file 1 本だけで、その中身は実行されない。

    Gate 3（監督者承認済みの no-deploy preview 実 run）で trigger file を作った。
    以降の恒久的な不変条件は「存在しないこと」ではなく、**inert であること**と
    **その path でこの workflow **しか**発火しないこと**である（b2b と同じ規律）。
    """
    preview = workflow(PREVIEW_WORKFLOW)
    triggers = preview.get("on", preview.get(True))
    assert set(triggers) == {"workflow_dispatch", "push"}
    assert triggers["push"]["branches"] == ["claude/investment-intelligence-phase0-rvdplu"]
    assert triggers["push"]["paths"] == [".github/p43b2c_preview_trigger"]
    assert set(triggers["push"]) == {"branches", "paths"}, sorted(triggers["push"])
    assert "schedule" not in triggers, "preview に cron を置かない"

    if PREVIEW_TRIGGER.exists():
        body = PREVIEW_TRIGGER.read_text(encoding="utf-8")
        assert 0 < len(body) < 1024
        for forbidden in ("api_key", "secret", "password", "bearer", "$(", "`",
                          "curl ", "python ", "rm ", "http://", "https://"):
            assert forbidden not in body.lower(), forbidden
    assert ".github/p43b2c_preview_trigger" not in run_bodies(PREVIEW_WORKFLOW, "preview"), \
        "workflow は trigger file の内容を読まない"


def test_only_the_preview_workflow_fires_on_its_trigger_path() -> None:
    """trigger file の更新で本番・producer・b2b が巻き添えで動かないこと。"""
    target = ".github/p43b2c_preview_trigger"
    firing = []
    for path in WORKFLOW_DIR.glob("*.yml"):
        data = workflow(path)
        raw = data.get("on", data.get(True)) or {}
        push = raw.get("push") if isinstance(raw, dict) else None
        paths = (push or {}).get("paths") if isinstance(push, dict) else None
        if paths and target in paths:
            firing.append(path.name)
    assert firing == [PREVIEW_WORKFLOW.name], firing
    for other in ("daily-market-brief.yml", "p43b1-morning-delivery-producer.yml",
                  "p43b2b-delivery-handoff.yml"):
        assert other not in firing, other


def test_preview_is_registered_for_closeout() -> None:
    closeout = (REPO_ROOT / "tests" / "intelligence"
                / "test_live_run_closeout.py").read_text(encoding="utf-8")
    assert f'"{PREVIEW_WORKFLOW.name}"' in closeout
    assert "set(documented) == set(CLOSEOUT_WORKFLOWS)" in closeout, \
        "完全一致 assertion を弱めない"


def test_runner_context_is_never_used_at_job_level() -> None:
    for path in WORKFLOW_DIR.glob("*.yml"):
        for job, spec in (workflow(path).get("jobs") or {}).items():
            assert "runner." not in yaml.safe_dump(spec.get("env") or {}), (path.name, job)


# ================================================================ root / notifier

def test_no_root_redirect_and_no_legacy_html() -> None:
    for path in (PRODUCTION_WORKFLOW, PREVIEW_WORKFLOW):
        text = executable_text(path)
        for forbidden in ("legacy.html", "redirect", "http-equiv", "Location:",
                          "index.html.bak"):
            assert forbidden not in text, (path.name, forbidden)
    for script in (MANIFEST_PATH, GRAFT_PATH, GATE_PATH, SELECTOR_PATH):
        code = _executable_source(script)
        assert "legacy.html" not in code, script.name


def test_v2_never_becomes_the_root() -> None:
    body = run_bodies(PRODUCTION_WORKFLOW, "generate-report")
    for forbidden in ("cp pages-site/v2/index.html pages-site/index.html",
                      "mv pages-site/v2", "pages-site/index.html <", "rm pages-site/index.html"):
        assert forbidden not in body, forbidden
    assert graft.V2_DIRNAME == "v2"


def test_main_py_and_notifiers_are_untouched_by_b2c() -> None:
    main_source = MAIN_PY.read_text(encoding="utf-8")
    assert "p43b2c" not in main_source and "pages_parallel" not in main_source
    assert 'return f"https://{owner}.github.io/{name}/"' in main_source, \
        "通知 URL は legacy root のまま"
    for path in (REPO_ROOT / "notifiers").rglob("*.py"):
        assert "p43b2c" not in path.read_text(encoding="utf-8"), path.name


# ================================================================ confidentiality

def test_hygiene_rejects_forbidden_artifacts(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    (site / "compass_raw.pdf").write_bytes(b"%PDF-1.4\n")
    findings = manifest.hygiene_findings(site)
    assert any("forbidden file type .pdf" in f for f in findings), findings


def test_hygiene_rejects_internal_store_paths(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    (site / "corpus").mkdir()
    (site / "corpus" / "page.html").write_text("x\n", encoding="utf-8")
    findings = manifest.hygiene_findings(site)
    assert any("forbidden path segment" in f for f in findings), findings


def test_hygiene_rejects_runner_paths_and_secret_shapes(tmp_path) -> None:
    site = make_legacy_site(tmp_path)
    (site / "leaky.html").write_text("<p>/home/runner/work/x</p>\n", encoding="utf-8")
    findings = manifest.hygiene_findings(site)
    assert any("machine-specific absolute path" in f for f in findings), findings
    (site / "leaky.html").write_text(
        "<p>ghp" + "_" + "A" * 36 + "</p>\n", encoding="utf-8")
    assert any("secret-shaped literal" in f for f in manifest.hygiene_findings(site))


def test_hygiene_does_not_apply_b2a_internal_vocabulary_to_legacy(tmp_path) -> None:
    """legacy 散文へ内部語彙リストを当てない（誤検知を作らない）。"""
    site = make_legacy_site(tmp_path)
    (site / "index.html").write_text(
        "<p>HIGH MEDIUM LOW MIXED UNCERTAIN breadth turnover</p>\n", encoding="utf-8")
    assert manifest.hygiene_findings(site) == []
    code = _executable_source(MANIFEST_PATH)
    for duplicated in ("FORBIDDEN_PUBLIC_SUBSTRINGS", "SIGNAL_LEVEL_JA", "UPWARD_LEAN",
                       "NOT_ENTITLED"):
        assert duplicated not in code, duplicated


def test_v2_content_safety_stays_with_frozen_b2a() -> None:
    """b2c は v2 の内容契約を再実装しない。"""
    for script in (MANIFEST_PATH, GRAFT_PATH, GATE_PATH, SELECTOR_PATH):
        code = _executable_source(script)
        for duplicated in ("PUBLIC_KEYS", "FORBIDDEN_PUBLIC", "PUBLIC_SIGNAL_KEYS",
                           "canonical_delivery", "markdown_sha256 =="):
            assert duplicated not in code, (script.name, duplicated)
    assert "validate_publication_artifacts" in B2A_MODULE.read_text(encoding="utf-8")


# ================================================================ config drift

def test_config_matches_the_enforced_constants() -> None:
    section = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["pages_parallel_publication"]
    assert section["freshness"]["max_artifact_age_hours"] == gate.MAX_ARTIFACT_AGE_HOURS
    assert section["freshness"]["max_session_lag_days"] == gate.MAX_SESSION_LAG_DAYS
    assert section["freshness"]["market_holiday_calendar"] is False
    assert section["producer"]["production_branch"] == selector.PRODUCTION_BRANCH
    assert section["producer"]["artifact_name"] == selector.DEFAULT_ARTIFACT_NAME
    assert section["producer"]["workflow"] == selector.DEFAULT_PRODUCER_WORKFLOW
    assert section["producer"]["attempt_policy"] == selector.DEFAULT_ATTEMPT_POLICY
    assert section["producer"]["eligible_events"] == ["push", "workflow_dispatch"]
    assert section["v2_dirname"] == manifest.V2_DIRNAME
    assert section["published_file_count"] == graft.APPROVED_COUNT
    assert section["repository_persistence"] is False
    assert section["no_valid_v2_policy"] == "LEGACY_ONLY"
