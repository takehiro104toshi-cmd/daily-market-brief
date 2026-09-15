"""P4-3b2b artifact handoff の構造ガード（Phase 4 P4-3b2b）。

検証するのは **cross-run handoff の境界だけ**である:

- workflow が到達可能で、権限・trigger・隔離先が最小であること
- producer run / artifact の選定が曖昧な「最新」に依存しないこと
- 信頼判定が baseline ancestry に基づき、想定外の応答で fail closed すること
- 凍結済み b2a を呼ぶだけで、検証ロジックを複製していないこと
- 公開（Pages deploy / リポジトリ書き込み / notifier）を一切行わないこと

**pytest から実 GitHub API を呼ばない。** selector は mock 応答だけで検査する。
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

HANDOFF_WORKFLOW = WORKFLOW_DIR / "p43b2b-delivery-handoff.yml"
PRODUCER_WORKFLOW = WORKFLOW_DIR / "p43b1-morning-delivery-producer.yml"
LEGACY_WORKFLOW = WORKFLOW_DIR / "daily-market-brief.yml"
TRIGGER_FILE = REPO_ROOT / ".github" / "p43b2b_handoff_trigger"
SELECTOR_PATH = REPO_ROOT / "scripts" / "p43b2b_select_run.py"

CLOSEOUT_TEST = REPO_ROOT / "tests" / "intelligence" / "test_live_run_closeout.py"
CLOSEOUT_DOC = REPO_ROOT / "docs" / "databank" / "LIVE_RUN_CLOSEOUT_PROTOCOL.md"
IMPORT_BOUNDARY_TEST = REPO_ROOT / "tests" / "intelligence" / "test_import_boundary.py"
B2A_MODULE = REPO_ROOT / "src" / "intelligence" / "reports" / "pages_parallel.py"
INDEX_TEMPLATE = REPO_ROOT / "docs" / "pages" / "v2_index.html"

FEATURE_BRANCH = "claude/investment-intelligence-phase0-rvdplu"
TRIGGER_PATH = ".github/p43b2b_handoff_trigger"
PREVIEW_ARTIFACT = "morning-delivery-v2-pages-preview"
PRODUCER_ARTIFACT = "morning-delivery-v2"
EXPECTED_TIMEOUT = 5
TRUST_BASELINE = "a2a6222"

#: 展開先。`artifact-ids` 指定の download はこの直下へ artifact 名の wrapper を作る
#: （run 34958591500 で実測）。b2a の入力は wrapper 自身であり、この root ではない。
DOWNLOAD_ROOT_DIRNAME = "p43b2_download"
DOWNLOAD_ROOT = "${RUNNER_TEMP}/" + DOWNLOAD_ROOT_DIRNAME

WRAPPER_CHECK_STEP = "Verify the observed download wrapper shape"
B2A_STEP = "Assemble /v2 with the frozen P4-3b2a validator"
EVIDENCE_STEP = "Verify isolation and emit evidence"


def _load_selector():
    spec = importlib.util.spec_from_file_location("p43b2b_select_run", SELECTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selector = _load_selector()


def workflow() -> dict:
    return yaml.safe_load(HANDOFF_WORKFLOW.read_text(encoding="utf-8")) or {}


def triggers() -> dict:
    data = workflow()
    raw = data.get("on", data.get(True))
    return raw if isinstance(raw, dict) else {str(raw): None}


def job() -> dict:
    jobs = workflow().get("jobs") or {}
    assert len(jobs) == 1, f"job は 1 つ: {sorted(jobs)}"
    return next(iter(jobs.values()))


def steps() -> list:
    return job().get("steps") or []


def step_using(fragment: str) -> dict:
    for step in steps():
        if fragment in str(step.get("uses", "")):
            return step
    raise AssertionError(f"step not found: {fragment}")


def executable_text() -> str:
    """実行される内容のみ（コメントは落ちる）。散文で「〜しない」検査を汚さない。"""
    return yaml.safe_dump(workflow(), allow_unicode=True, sort_keys=True)


def run_bodies() -> str:
    return "\n".join(str(step.get("run", "")) for step in steps())


# ---------------------------------------------------------------- workflow contract

def test_handoff_workflow_exists() -> None:
    assert HANDOFF_WORKFLOW.is_file()
    assert workflow().get("name") == "p43b2b-delivery-handoff"


def test_triggers_are_exactly_dispatch_and_scoped_push() -> None:
    assert set(triggers()) == {"workflow_dispatch", "push"}, sorted(triggers())
    push = triggers()["push"]
    assert push.get("branches") == [FEATURE_BRANCH]
    assert push.get("paths") == [TRIGGER_PATH]
    assert set(push) == {"branches", "paths"}, sorted(push)


def test_no_schedule_or_chained_triggers() -> None:
    for forbidden in ("schedule", "workflow_run", "workflow_call", "pull_request"):
        assert forbidden not in triggers(), forbidden
    assert "workflow_call" not in executable_text()


def test_permissions_are_exactly_read_only() -> None:
    assert workflow().get("permissions") == {"contents": "read", "actions": "read"}


def test_job_declares_the_expected_timeout() -> None:
    assert job().get("timeout-minutes") == EXPECTED_TIMEOUT


def test_no_dependency_on_other_workflows() -> None:
    assert "needs" not in job()
    text = executable_text()
    assert "daily-market-brief" not in text
    assert PRODUCER_WORKFLOW.stem not in text, "producer workflow を呼び出さない"


def test_no_continue_on_error() -> None:
    assert "continue-on-error" not in executable_text()


def test_trigger_file_exists_and_is_inert() -> None:
    assert TRIGGER_FILE.is_file()
    text = TRIGGER_FILE.read_text(encoding="utf-8")
    assert 0 < len(text) < 1024
    for forbidden in ("api_key", "secret", "password", "bearer", "$(", "`",
                      "curl ", "python ", "rm ", "http://", "https://"):
        assert forbidden not in text.lower(), forbidden
    assert TRIGGER_PATH not in run_bodies(), "workflow は trigger file の内容を読まない"


# ---------------------------------------------------------------- download contract

def step_index(name: str) -> int:
    for index, step in enumerate(steps()):
        if step.get("name") == name:
            return index
    raise AssertionError(f"step not found: {name}")


def step_named(name: str) -> dict:
    return steps()[step_index(name)]


def test_download_uses_artifact_ids_not_name() -> None:
    download = step_using("actions/download-artifact@v4")
    with_ = download.get("with") or {}
    assert "artifact-ids" in with_, "id 直指定を使う（名前一致に依存しない）"
    assert "name" not in with_, "download の name 指定に依存しない"
    assert "pattern" not in with_ and "merge-multiple" not in with_


def test_download_pins_run_id_and_token_and_isolated_path() -> None:
    with_ = step_using("actions/download-artifact@v4").get("with") or {}
    assert "selected_run_id" in str(with_.get("run-id")), with_.get("run-id")
    assert "secrets.GITHUB_TOKEN" in str(with_.get("github-token"))
    assert str(with_.get("path")) == "${{ runner.temp }}/" + DOWNLOAD_ROOT_DIRNAME, \
        with_.get("path")


def test_download_root_is_isolated_and_checked_empty() -> None:
    assert DOWNLOAD_ROOT_DIRNAME in executable_text()
    assert f'test -z "$(ls -A "{DOWNLOAD_ROOT}")"' in run_bodies(), \
        "展開前に download root が空であることを確かめる"
    assert "p43b2_artifact" not in executable_text(), \
        "wrapper を生む展開先を b2a の入力として再利用しない"


def test_download_root_is_not_the_b2a_input() -> None:
    """実測した wrapper 形（run 34958591500）を前提に、b2a へは wrapper 自身を渡す。"""
    body = run_bodies()
    assert f'--artifact-dir "{DOWNLOAD_ROOT}/${{ARTIFACT_NAME}}"' in body, body
    assert f'--artifact-dir "{DOWNLOAD_ROOT}"' not in body, \
        "download root をそのまま b2a へ渡すと wrapper で必ず落ちる"


def test_wrapper_name_comes_from_the_selector_contract() -> None:
    """artifact 名の第 2 の定数を作らない（selector が完全一致で検証した値を使う）。"""
    assert selector.ARTIFACT_NAME == PRODUCER_ARTIFACT
    for name in (WRAPPER_CHECK_STEP, B2A_STEP, EVIDENCE_STEP):
        env = step_named(name).get("env") or {}
        assert env.get("ARTIFACT_NAME") == "${{ steps.select.outputs.artifact_name }}", name
    assert f"{DOWNLOAD_ROOT}/{PRODUCER_ARTIFACT}" not in executable_text(), \
        "wrapper 名を shell へ直書きしない（selector output が唯一の出所）"


def test_wrapper_shape_is_verified_between_download_and_b2a() -> None:
    download_at = next(index for index, step in enumerate(steps())
                       if "download-artifact@v4" in str(step.get("uses", "")))
    assert download_at < step_index(WRAPPER_CHECK_STEP) < step_index(B2A_STEP)


def test_wrapper_check_verifies_every_shape_condition() -> None:
    """download root の存在・entry 数 1・名前一致・ディレクトリ・sibling 皆無。"""
    body = str(step_named(WRAPPER_CHECK_STEP).get("run", ""))
    assert 'pathlib.Path(os.environ["RUNNER_TEMP"]) / "p43b2_download"' in body
    assert "root.is_dir()" in body, "download root の存在を確かめる"
    assert "len(entries) != 1" in body, "entry はちょうど 1 つ"
    assert "entries[0] != expected" in body, "entry 名は artifact 名と完全一致"
    assert "(root / expected).is_dir()" in body, "その entry はディレクトリ"
    assert "sibling" in body, "sibling が無いことを証跡に残す"
    assert "sys.exit(1 if problems else 0)" in body, "期待と違えば fail closed"


def test_wrapper_check_does_not_validate_the_publication_files() -> None:
    """4 点の公開物検証は凍結 b2a の責務。ここで複製も先取りもしない。"""
    body = str(step_named(WRAPPER_CHECK_STEP).get("run", ""))
    for duplicated in ("latest_morning_brief", "session_date", "reference_session",
                       ".md", ".json", "sha256", "exactly 4"):
        assert duplicated not in body, duplicated


def test_extracted_files_are_never_moved_copied_or_flattened() -> None:
    body = run_bodies()
    for forbidden in ("mv ", "cp ", "rsync", "shutil", "copytree", "os.rename",
                      "os.replace", "os.walk", "rglob", ".glob(", "find ",
                      "next(root.iterdir())", "p43b2_download/*"):
        assert forbidden not in body, forbidden


def test_observed_wrapper_shape_is_documented_with_its_evidence() -> None:
    """README の記述ではなく実測を根拠として残す（憶測で戻さないため）。"""
    text = HANDOFF_WORKFLOW.read_text(encoding="utf-8")
    assert "34958591500" in text, "実測 run を根拠として明記する"
    assert "artifact-ids" in text and "wrapper" in text


# ---------------------------------------------------------------- b2a reuse

def test_frozen_b2a_cli_is_invoked() -> None:
    body = run_bodies()
    assert "-m src.intelligence.reports.pages_parallel" in body
    assert "--artifact-dir" in body and "--v2-destination" in body
    assert "--jst-today" in body and "--index-template docs/pages/v2_index.html" in body


def test_v2_destination_is_runner_temp_and_named_v2() -> None:
    assert '"${RUNNER_TEMP}/p43b2_pages_site/v2"' in run_bodies()
    upload = step_using("actions/upload-artifact@v4").get("with") or {}
    assert str(upload.get("path")).startswith("${{ runner.temp }}/")


def test_runner_context_is_never_used_at_job_level() -> None:
    """`jobs.<id>.env` は runner context を受け付けない（invalid workflow file になる）。

    実測: この規約を破った版は job ゼロのまま conclusion=failure の run を作った。
    shell では runner 既定の `RUNNER_TEMP` を使い、`runner.*` 式は step の
    `with` / `env` に限る（既存 workflow もすべてその形）。
    """
    for name, spec in (workflow().get("jobs") or {}).items():
        assert "runner." not in yaml.safe_dump(spec.get("env") or {}), name
        for key in ("runs-on", "timeout-minutes", "concurrency", "container", "services"):
            assert "runner." not in str(spec.get(key, "")), (name, key)
    for other in WORKFLOW_DIR.glob("*.yml"):
        data = yaml.safe_load(other.read_text(encoding="utf-8")) or {}
        for name, spec in (data.get("jobs") or {}).items():
            assert "runner." not in yaml.safe_dump(spec.get("env") or {}), (other.name, name)


def test_jst_date_is_derived_like_the_frozen_pilot() -> None:
    body = run_bodies()
    assert "timedelta(hours=9)" in body, "凍結 Compass pilot と同じ導出を使う"
    assert "datetime.now(timezone.utc)" in body
    assert "date -u" not in body, "runner の UTC 日付をそのまま使わない"


def test_validation_logic_is_not_duplicated() -> None:
    """公開契約の再実装を workflow へ持ち込まない（b2a が権威）。"""
    body = run_bodies()
    for duplicated in ("PUBLIC_KEYS", "FORBIDDEN_PUBLIC", "SIGNAL_LEVEL_JA",
                       "unavailable_reason not in", "上昇寄り", "下落寄り"):
        assert duplicated not in body, duplicated


# ---------------------------------------------------------------- publication safety

def test_no_pages_deployment() -> None:
    text = executable_text()
    for forbidden in ("upload-pages-artifact", "deploy-pages", "configure-pages",
                      "pages-site", "github-pages"):
        assert forbidden not in text, forbidden
    assert "pages" not in (workflow().get("permissions") or {})
    assert "id-token" not in (workflow().get("permissions") or {})


def test_no_repository_writes() -> None:
    text = executable_text()
    for forbidden in ("git add", "git commit", "git push", "output/v2",
                      "notifiers", "main.py"):
        assert forbidden not in text, forbidden


def test_preview_artifact_is_distinctly_named_and_v2_only() -> None:
    upload = step_using("actions/upload-artifact@v4")
    with_ = upload.get("with") or {}
    assert with_.get("name") == PREVIEW_ARTIFACT
    assert with_.get("name") != PRODUCER_ARTIFACT, "producer artifact と混同しない"
    assert str(with_.get("path")).endswith("/p43b2_pages_site/v2"), with_.get("path")
    assert with_.get("retention-days") == 14
    assert with_.get("if-no-files-found") == "error"
    assert len([s for s in steps() if "upload-artifact" in str(s.get("uses", ""))]) == 1


def test_safety_evidence_reports_the_download_root_shape() -> None:
    body = str(step_named(EVIDENCE_STEP).get("run", ""))
    assert "download_root_entry_names" in body, "展開形を証跡に残す"
    assert "download_root_holds_only_the_wrapper" in body
    assert "download_root_holds_only_the_wrapper" in body.split("safety_check", 1)[1], \
        "wrapper 以外が現れたら SAFETY を PASSED にしない"


def test_synthetic_legacy_root_is_verified() -> None:
    body = run_bodies()
    assert "synthetic legacy root" in body and "synthetic history sentinel" in body
    assert "synthetic_root_unchanged" in body and "synthetic_history_unchanged" in body


# ---------------------------------------------------------------- selector: constants

def test_selector_pins_the_producer_identity() -> None:
    assert selector.PRODUCER_WORKFLOW_PATH == \
        ".github/workflows/p43b1-morning-delivery-producer.yml"
    assert selector.PRODUCER_BRANCH == FEATURE_BRANCH
    assert selector.ARTIFACT_NAME == PRODUCER_ARTIFACT
    assert selector.TRUST_BASELINE == TRUST_BASELINE
    assert selector.ELIGIBLE_EVENTS == ("push", "workflow_dispatch")
    assert selector.REQUIRED_RUN_ATTEMPT == 1
    assert selector.MAX_ARTIFACT_BYTES == 1024 * 1024


# ---------------------------------------------------------------- selector: run filter

def a_run(**overrides):
    run = {"id": 111, "run_number": 7, "run_attempt": 1, "event": "push",
           "status": "completed", "conclusion": "success",
           "head_branch": FEATURE_BRANCH, "head_sha": "f" * 40,
           "path": ".github/workflows/p43b1-morning-delivery-producer.yml"}
    run.update(overrides)
    return run


def test_eligible_run_is_accepted() -> None:
    ok, reason = selector.run_is_eligible(a_run())
    assert ok and reason == ""


@pytest.mark.parametrize("override,fragment", [
    ({"path": ".github/workflows/p2d-market-pilot.yml"}, "not the producer"),
    ({"head_branch": "main"}, "not the validation branch"),
    ({"status": "in_progress"}, "not completed"),
    ({"conclusion": "failure"}, "did not succeed"),
    ({"conclusion": None}, "did not succeed"),
    ({"event": "schedule"}, "not eligible"),
    ({"event": "workflow_run"}, "not eligible"),
    ({"run_attempt": 2}, "run_attempt is not 1"),
    ({"head_sha": ""}, "head_sha is unusable"),
])
def test_ineligible_runs_are_rejected(override, fragment) -> None:
    ok, reason = selector.run_is_eligible(a_run(**override))
    assert not ok and fragment in reason, reason


def test_workflow_dispatch_event_is_eligible() -> None:
    ok, _ = selector.run_is_eligible(a_run(event="workflow_dispatch"))
    assert ok


# ---------------------------------------------------------------- selector: trust

def _patch_request(monkeypatch, responses):
    """`_request` を差し替える（実 API を呼ばない）。

    `/runs` は `.../runs/<id>/artifacts` の部分文字列でもあるため、
    素朴な substring 一致ではなく**最も具体的な種別から**判定する。
    """
    def kind(path):
        if path.endswith("/artifacts"):
            return "/artifacts"
        if "/compare/" in path:
            return "/compare/"
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


def _executable_source(path):
    """docstring と comment を除いた実行内容（散文で「〜しない」検査を汚さない）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            del body[0]
    return ast.unparse(tree)


@pytest.mark.parametrize("status", ["identical", "ahead"])
def test_trusted_compare_statuses_are_accepted(monkeypatch, status) -> None:
    _patch_request(monkeypatch, {"/compare/": {"status": status, "behind_by": 0}})
    assert selector.trust_status("https://api", "o/r", "f" * 40, auth="x") == status


@pytest.mark.parametrize("status", ["behind", "diverged", "unknown", "AHEAD", ""])
def test_untrusted_or_unknown_compare_status_fails_closed(monkeypatch, status) -> None:
    _patch_request(monkeypatch, {"/compare/": {"status": status, "behind_by": 0}})
    with pytest.raises(selector.SelectionRejected, match="not trusted"):
        selector.trust_status("https://api", "o/r", "f" * 40, auth="x")


def test_nonzero_behind_by_fails_closed_even_with_ok_status(monkeypatch) -> None:
    _patch_request(monkeypatch, {"/compare/": {"status": "ahead", "behind_by": 3}})
    with pytest.raises(selector.SelectionRejected, match="is behind"):
        selector.trust_status("https://api", "o/r", "f" * 40, auth="x")


@pytest.mark.parametrize("payload", [
    {"behind_by": 0}, {"status": "ahead"}, {"status": 1, "behind_by": 0},
    {"status": "ahead", "behind_by": "0"}, {"status": "ahead", "behind_by": True}, {},
])
def test_unusable_compare_response_fails_closed(monkeypatch, payload) -> None:
    _patch_request(monkeypatch, {"/compare/": payload})
    with pytest.raises(selector.SelectionRejected):
        selector.trust_status("https://api", "o/r", "f" * 40, auth="x")


def test_trust_uses_the_baseline_as_compare_base(monkeypatch) -> None:
    seen = {}

    def fake(api_base, path, *, auth, query=None, timeout=30.0):
        seen["path"] = path
        return {"status": "ahead", "behind_by": 0}

    monkeypatch.setattr(selector, "_request", fake)
    selector.trust_status("https://api", "o/r", "abc123", auth="x")
    assert seen["path"] == f"/repos/o/r/compare/{TRUST_BASELINE}...abc123"


# ---------------------------------------------------------------- selector: artifact

def an_artifact(**overrides):
    artifact = {"id": 999, "name": PRODUCER_ARTIFACT, "size_in_bytes": 2958,
                "expired": False, "created_at": "2026-09-15T06:52:28Z",
                "digest": "sha256:" + "d" * 64}
    artifact.update(overrides)
    return artifact


def test_single_matching_artifact_is_selected(monkeypatch) -> None:
    _patch_request(monkeypatch, {"/artifacts": {"artifacts": [
        an_artifact(), {"id": 1, "name": "something-else", "size_in_bytes": 5,
                        "expired": False}]}})
    chosen = selector.select_artifact("https://api", "o/r", 111, auth="x")
    assert chosen["id"] == 999


@pytest.mark.parametrize("artifacts,fragment", [
    ([], "found 0"),
    ([an_artifact(), an_artifact(id=1000)], "found 2"),
    ([an_artifact(expired=True)], "expired"),
    ([an_artifact(size_in_bytes=0)], "empty"),
    ([an_artifact(size_in_bytes=1024 * 1024 + 1)], "implausibly large"),
    ([an_artifact(size_in_bytes="2958")], "size is unusable"),
    ([an_artifact(id="999")], "id is unusable"),
])
def test_artifact_selection_fails_closed(monkeypatch, artifacts, fragment) -> None:
    _patch_request(monkeypatch, {"/artifacts": {"artifacts": artifacts}})
    with pytest.raises(selector.SelectionRejected, match=fragment):
        selector.select_artifact("https://api", "o/r", 111, auth="x")


def test_artifact_listing_shape_is_validated(monkeypatch) -> None:
    _patch_request(monkeypatch, {"/artifacts": {"artifacts": "not a list"}})
    with pytest.raises(selector.SelectionRejected, match="unusable"):
        selector.select_artifact("https://api", "o/r", 111, auth="x")


# ---------------------------------------------------------------- selector: end to end

def test_select_skips_ineligible_and_takes_the_first_eligible(monkeypatch) -> None:
    _patch_request(monkeypatch, {
        "/runs": {"workflow_runs": [a_run(id=222, run_attempt=2),
                                    a_run(id=333, head_branch="main"),
                                    a_run(id=444)]},
        "/compare/": {"status": "ahead", "behind_by": 0},
        "/artifacts": {"artifacts": [an_artifact()]}})
    chosen = selector.select("https://api", "o/r", auth="x")
    assert chosen["run"]["id"] == 444
    assert chosen["trust_status"] == "ahead"
    assert chosen["candidates_examined"] == 3


def test_select_fails_closed_when_no_run_is_eligible(monkeypatch) -> None:
    _patch_request(monkeypatch, {
        "/runs": {"workflow_runs": [a_run(run_attempt=2), a_run(conclusion="failure")]}})
    with pytest.raises(selector.SelectionRejected, match="no eligible producer run"):
        selector.select("https://api", "o/r", auth="x")


def test_select_fails_closed_on_unusable_run_listing(monkeypatch) -> None:
    _patch_request(monkeypatch, {"/runs": {"workflow_runs": None}})
    with pytest.raises(selector.SelectionRejected, match="unusable"):
        selector.select("https://api", "o/r", auth="x")


def test_main_exits_non_zero_without_eligible_run(monkeypatch, capsys) -> None:
    _patch_request(monkeypatch, {"/runs": {"workflow_runs": []}})
    monkeypatch.setenv("GITHUB_TOKEN", "sentinel-credential-value")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert selector.main(["--repository", "o/r"]) == 1
    out = capsys.readouterr().out
    assert "::P43B2B_REJECTED::" in out


def test_main_requires_credential_and_repository(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert selector.main(["--repository", "o/r"]) == 1
    monkeypatch.setenv("GITHUB_TOKEN", "sentinel-credential-value")
    assert selector.main(["--repository", "not-a-repo"]) == 1
    assert "::P43B2B_REJECTED::" in capsys.readouterr().out


def test_main_emits_selection_and_never_prints_the_credential(monkeypatch, capsys,
                                                              tmp_path) -> None:
    sentinel = "sentinel-credential-value"
    _patch_request(monkeypatch, {
        "/runs": {"workflow_runs": [a_run(id=444)]},
        "/compare/": {"status": "identical", "behind_by": 0},
        "/artifacts": {"artifacts": [an_artifact()]}})
    output = tmp_path / "gh_output"
    output.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", sentinel)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert selector.main(["--repository", "o/r"]) == 0

    out = capsys.readouterr().out
    assert sentinel not in out, "認証値を出力しない"
    assert "::P43B2B_SELECTION::" in out and "::P43B2B_ARTIFACT::" in out
    selection = json.loads(out.split("::P43B2B_SELECTION::", 1)[1].split("\n", 1)[0])
    assert selection["selected_run_id"] == 444
    assert selection["run_attempt"] == 1
    assert selection["trust_baseline"] == TRUST_BASELINE
    assert selection["trust_status"] == "identical"

    written = output.read_text(encoding="utf-8")
    assert sentinel not in written
    assert "artifact_id=999" in written and "selected_run_id=444" in written
    assert "trust_status=identical" in written


# ---------------------------------------------------------------- selector: boundary

def test_selector_uses_stdlib_only_and_never_imports_vnext() -> None:
    source = SELECTOR_PATH.read_text(encoding="utf-8")
    tops = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            tops.update(a.name.split(".")[0] for a in node.names)
    assert "src" not in tops, "selector は vNext を import しない"
    assert "src.intelligence" not in _executable_source(SELECTOR_PATH)
    assert tops <= set(sys.stdlib_module_names), sorted(tops - set(sys.stdlib_module_names))
    for forbidden in ("requests", "yaml", "pandas"):
        assert forbidden not in tops


def test_selector_does_not_download_or_write() -> None:
    code = _executable_source(SELECTOR_PATH)
    for forbidden in ("zipfile", "shutil", "archive_download_url", "subprocess",
                      "urlretrieve", "os.system", "Popen"):
        assert forbidden not in code, forbidden
    # file への書き込みは GITHUB_OUTPUT への追記 1 箇所だけ
    # （`urlopen(` が `open(` を部分文字列として含むため除いてから数える）
    file_opens = code.replace("urlopen(", "").count("open(")
    assert file_opens == 1, f"file を開くのは GITHUB_OUTPUT だけ: {file_opens}"
    assert "GITHUB_OUTPUT" in code


# ---------------------------------------------------------------- frozen assets

def test_producer_workflow_is_unchanged_by_b2b() -> None:
    data = yaml.safe_load(PRODUCER_WORKFLOW.read_text(encoding="utf-8"))
    assert data.get("permissions") == {"contents": "read"}, "producer 権限を広げない"
    text = PRODUCER_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("actions: read", "download-artifact", "p43b2b", "pages_parallel"):
        assert forbidden not in text, forbidden


def test_b2a_module_and_template_are_unchanged() -> None:
    import re
    source = B2A_MODULE.read_text(encoding="utf-8")
    assert 'PAGES_PARALLEL_VERSION = "0.1.0"' in source
    for symbol in ("def validate_publication_artifacts(", "def assemble_v2_publication("):
        assert symbol in source, symbol
    for forbidden in ("requests", "urllib", "github", "download"):
        assert forbidden not in source.lower().split('"""')[-1], forbidden
    template = INDEX_TEMPLATE.read_text(encoding="utf-8")
    assert re.findall(r'href="([^"]+)"', template) == [
        "latest_morning_brief.md", "latest_morning_brief.json", "../"]


def test_import_boundary_and_legacy_workflow_are_unchanged() -> None:
    boundary = IMPORT_BOUNDARY_TEST.read_text(encoding="utf-8")
    assert ('LEGACY_FORBIDDEN_PREFIXES = (\n'
            '    "src.analysis", "src.report", "src.collectors", "src.data", "src.date",\n'
            '    "notifiers", "main", "scripts",\n'
            ')') in boundary
    assert "p43b2b" not in boundary, "境界テストへ例外を作らない"
    legacy = LEGACY_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("p43b2b", "p43b1", "pages_parallel", "output/v2", "download-artifact"):
        assert forbidden not in legacy, forbidden
    assert "cp output/latest_market_brief.html pages-site/index.html" in legacy


# ---------------------------------------------------------------- closeout

def test_handoff_workflow_is_registered_for_closeout() -> None:
    text = CLOSEOUT_TEST.read_text(encoding="utf-8")
    assert f'"{HANDOFF_WORKFLOW.name}"' in text
    assert "set(documented) == set(CLOSEOUT_WORKFLOWS)" in text, \
        "完全一致 assertion を弱めない"


def test_closeout_protocol_documents_the_handoff_timeout() -> None:
    import re
    doc = CLOSEOUT_DOC.read_text(encoding="utf-8")
    row = re.search(rf"^\|\s*`?{re.escape(HANDOFF_WORKFLOW.name)}`?\s*\|\s*(\d+)\s*\|",
                    doc, re.MULTILINE)
    assert row, "待機上限表へ追記すること"
    assert int(row.group(1)) == EXPECTED_TIMEOUT
    assert "::P43B2B_" in doc, "evidence 用 marker を protocol へ記載すること"
