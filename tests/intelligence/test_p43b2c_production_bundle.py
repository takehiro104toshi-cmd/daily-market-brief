"""P4-3b2c 本番 promotion bundle の自己完結ガード（Phase 4 P4-3b2c / Gate 5A-R）。

`test_pages_integration.py` は開発 branch の広い前提（凍結 b2b selector の定数、
live-run closeout レジストリ）に依存するため、**本番 bundle には持ち込めない**。
本 module はその代替として、promotion bundle だけで完結する不変条件を検査する。

規律:

- **live-run closeout レジストリを読まない**（無関係な pilot workflow を本番へ
  引きずり込まないため）。
- 除外 subsystem の不在は「ファイルが無いこと」ではなく
  **「本番 runtime closure がそれらを import しないこと」**として検査する。
  この形なら feature branch（全 package が存在する）でも bundle でも同じ意味になる。
- 既存の `test_pages_integration.py` / `test_live_run_closeout.py` /
  closeout protocol を変更しない。feature 側の検証はそのまま残す。

ネットワークを使わない。実 GitHub API を呼ばない。Pages へ deploy しない。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

PRODUCTION_WORKFLOW = WORKFLOW_DIR / "daily-market-brief.yml"
PRODUCER_WORKFLOW = WORKFLOW_DIR / "p43b1-morning-delivery-producer.yml"
PREVIEW_WORKFLOW = WORKFLOW_DIR / "p43b2c-pages-preview.yml"
HANDOFF_WORKFLOW = WORKFLOW_DIR / "p43b2b-delivery-handoff.yml"

B2A_MODULE = REPO_ROOT / "src" / "intelligence" / "reports" / "pages_parallel.py"
INDEX_TEMPLATE = REPO_ROOT / "docs" / "pages" / "v2_index.html"
MAIN_PY = REPO_ROOT / "main.py"
CONFIG = REPO_ROOT / "config.yaml"
CONFIDENTIAL_GUARD = REPO_ROOT / "tests" / "intelligence" / "test_confidential_guard.py"
PREVIEW_TRIGGER_PATH = ".github/p43b2c_preview_trigger"
FEATURE_BRANCH = "claude/investment-intelligence-phase0-rvdplu"

B2C_SCRIPTS = ("p43b2c_select_producer", "p43b2c_pages_manifest",
               "p43b2c_v2_gate", "p43b2c_graft_v2")

#: 本番 runtime の入口（producer 2 本 ＋ publication 1 本）
RUNTIME_ENTRY_POINTS = ("src.intelligence.market.pilot_runner",
                        "src.intelligence.reports.delivery_pilot",
                        "src.intelligence.reports.pages_parallel")

#: 本番が実行してはならない subsystem（research / governance / 別 phase）
EXCLUDED_PACKAGES = ("corpus", "corpus_research", "decision", "entities", "evaluation",
                     "formal_review", "jquants_ops", "mobile_intake", "news",
                     "personalization", "pipeline", "predictions", "replay",
                     "screening", "shadow_review", "themes", "thesis")


# ---------------------------------------------------------------- helpers

def workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def executable_text(path: Path) -> str:
    """実行される内容のみ（コメントは落ちる）。散文で「〜しない」検査を汚さない。"""
    return yaml.safe_dump(workflow(path), allow_unicode=True, sort_keys=True)


def triggers(path: Path) -> dict:
    data = workflow(path)
    raw = data.get("on", data.get(True))
    return raw if isinstance(raw, dict) else {str(raw): None}


def steps(path: Path, job: str) -> list:
    return (workflow(path).get("jobs") or {}).get(job, {}).get("steps") or []


def run_bodies(path: Path, job: str) -> str:
    return "\n".join(str(s.get("run", "")) for s in steps(path, job))


def _module_path(module: str) -> Path | None:
    candidate = REPO_ROOT / (module.replace(".", "/") + ".py")
    if candidate.is_file():
        return candidate
    package = REPO_ROOT / module.replace(".", "/") / "__init__.py"
    return package if package.is_file() else None


def runtime_closure() -> set[str]:
    """本番 3 入口から到達する first-party module の集合（相対 POSIX path）。"""
    seen: set[str] = set()
    queue = list(RUNTIME_ENTRY_POINTS)
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        path = _module_path(module)
        if path is None:
            continue
        seen.add(module)
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package
                    for _ in range(node.level - 1):
                        base = base.rsplit(".", 1)[0]
                    target = f"{base}.{node.module}" if node.module else base
                else:
                    target = node.module or ""
                if target.startswith("src."):
                    queue.append(target)
                    queue.extend(f"{target}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                queue.extend(a.name for a in node.names if a.name.startswith("src."))
    return {str(_module_path(m).relative_to(REPO_ROOT)) for m in seen if _module_path(m)}


# ---------------------------------------------------------------- presence

def test_required_production_files_exist() -> None:
    for path in (PRODUCTION_WORKFLOW, PRODUCER_WORKFLOW, PREVIEW_WORKFLOW,
                 B2A_MODULE, INDEX_TEMPLATE, MAIN_PY, CONFIG, CONFIDENTIAL_GUARD):
        assert path.is_file(), path
    for name in B2C_SCRIPTS:
        assert (REPO_ROOT / "scripts" / f"{name}.py").is_file(), name


def test_validation_support_workflow_is_present_and_inert() -> None:
    """retain された b2b は deploy せず Pages 権限も持たない。"""
    if not HANDOFF_WORKFLOW.is_file():
        pytest.skip("b2b validation support is not part of this tree")
    data = workflow(HANDOFF_WORKFLOW)
    assert data.get("permissions") == {"contents": "read", "actions": "read"}
    text = executable_text(HANDOFF_WORKFLOW)
    for forbidden in ("upload-pages-artifact", "deploy-pages", "configure-pages"):
        assert forbidden not in text, forbidden


# ---------------------------------------------------------------- trigger safety

def test_preview_cannot_fire_on_the_production_branch() -> None:
    """trigger file の有無に関わらず、preview は production branch で発火しない。"""
    push = triggers(PREVIEW_WORKFLOW)["push"]
    assert push["branches"] == [FEATURE_BRANCH], push["branches"]
    assert "main" not in push["branches"]
    assert push["paths"] == [PREVIEW_TRIGGER_PATH]
    assert set(push) == {"branches", "paths"}


def test_no_workflow_carries_a_schedule_except_the_legacy_production_one() -> None:
    scheduled = [p.name for p in WORKFLOW_DIR.glob("*.yml") if "schedule" in triggers(p)]
    assert scheduled == [PRODUCTION_WORKFLOW.name], scheduled


def test_producer_has_no_schedule_and_no_write_permission() -> None:
    assert "schedule" not in triggers(PRODUCER_WORKFLOW)
    assert workflow(PRODUCER_WORKFLOW).get("permissions") == {"contents": "read"}
    text = executable_text(PRODUCER_WORKFLOW)
    for forbidden in ("git add", "git commit", "git push", "deploy-pages",
                      "upload-pages-artifact", "id-token"):
        assert forbidden not in text, forbidden


def test_preview_has_no_schedule_and_no_pages_permission() -> None:
    assert "schedule" not in triggers(PREVIEW_WORKFLOW)
    assert workflow(PREVIEW_WORKFLOW).get("permissions") == {"contents": "read",
                                                             "actions": "read"}
    text = executable_text(PREVIEW_WORKFLOW)
    for forbidden in ("upload-pages-artifact", "deploy-pages", "configure-pages",
                      "id-token", "git add", "git commit", "git push"):
        assert forbidden not in text, forbidden


# ---------------------------------------------------------------- single deployer

def test_exactly_one_pages_artifact_and_one_deployment() -> None:
    uploads, deploys = [], []
    for path in WORKFLOW_DIR.glob("*.yml"):
        for job, spec in (workflow(path).get("jobs") or {}).items():
            for step in spec.get("steps") or []:
                uses = str(step.get("uses", ""))
                if "upload-pages-artifact" in uses:
                    uploads.append(f"{path.name}:{job}")
                if "deploy-pages" in uses:
                    deploys.append(f"{path.name}:{job}")
    assert uploads == [f"{PRODUCTION_WORKFLOW.name}:generate-report"], uploads
    assert deploys == [f"{PRODUCTION_WORKFLOW.name}:deploy-pages"], deploys


def test_no_other_workflow_holds_pages_or_oidc_permission() -> None:
    for path in WORKFLOW_DIR.glob("*.yml"):
        if path.name == PRODUCTION_WORKFLOW.name:
            continue
        data = workflow(path)
        for scope in [data.get("permissions") or {}] + [
                (j.get("permissions") or {}) for j in (data.get("jobs") or {}).values()]:
            assert "pages" not in scope, path.name
            assert "id-token" not in scope, path.name


# ---------------------------------------------------------------- production contract

def test_production_permissions_add_only_actions_read() -> None:
    assert workflow(PRODUCTION_WORKFLOW).get("permissions") == {
        "contents": "write", "pages": "write", "id-token": "write", "actions": "read"}


def test_production_trust_baseline_is_empty() -> None:
    for step in steps(PRODUCTION_WORKFLOW, "generate-report"):
        env = step.get("env") or {}
        if "P43B2C_TRUST_BASELINE" in env:
            assert env["P43B2C_TRUST_BASELINE"] == "", env["P43B2C_TRUST_BASELINE"]
            return
    pytest.fail("P43B2C_TRUST_BASELINE is not declared in the production workflow")


def test_production_uses_production_mode_without_the_validation_baseline() -> None:
    body = run_bodies(PRODUCTION_WORKFLOW, "generate-report")
    assert "--mode production" in body and "--producer-branch main" in body
    assert "a2a6222" not in body, "本番 trust を検証専用 baseline へ縛らない"
    assert "--eligible-events push,workflow_dispatch" in body
    assert "schedule" not in body.split("--eligible-events")[1].split()[0]


def test_legacy_pages_preparation_and_deploy_job_are_intact() -> None:
    body = run_bodies(PRODUCTION_WORKFLOW, "generate-report")
    assert "cp output/latest_market_brief.html pages-site/index.html" in body
    assert "cp -r output/history/* pages-site/history/" in body
    job = workflow(PRODUCTION_WORKFLOW)["jobs"]["deploy-pages"]
    assert job["needs"] == "generate-report"
    assert job["permissions"] == {"pages": "write", "id-token": "write"}
    assert job["environment"]["name"] == "github-pages"
    assert len(job["steps"]) == 1


def test_no_root_cutover_and_no_legacy_html() -> None:
    for path in (PRODUCTION_WORKFLOW, PREVIEW_WORKFLOW):
        text = executable_text(path)
        for forbidden in ("legacy.html", "http-equiv", "redirect",
                          "cp pages-site/v2/index.html pages-site/index.html",
                          "rm pages-site/index.html"):
            assert forbidden not in text, (path.name, forbidden)


def test_v2_is_never_persisted_in_the_repository() -> None:
    assert "output/v2" not in executable_text(PRODUCTION_WORKFLOW)
    for step in steps(PRODUCTION_WORKFLOW, "generate-report"):
        if step.get("name") == "Commit and push report":
            assert "v2" not in str(step.get("run", ""))


def test_notification_target_remains_the_legacy_root() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")
    assert 'return f"https://{owner}.github.io/{name}/"' in source
    assert "p43b2c" not in source and "pages_parallel" not in source
    notifiers = REPO_ROOT / "notifiers"
    if notifiers.is_dir():
        for path in notifiers.rglob("*.py"):
            assert "p43b2c" not in path.read_text(encoding="utf-8"), path.name


# ---------------------------------------------------------------- runtime closure

def test_publication_boundary_exists_and_is_the_frozen_one() -> None:
    import re
    source = B2A_MODULE.read_text(encoding="utf-8")
    assert 'PAGES_PARALLEL_VERSION = "0.1.0"' in source
    for symbol in ("def validate_publication_artifacts(", "def assemble_v2_publication("):
        assert symbol in source, symbol
    assert "if session_date > jst_today:" in source, "未来 session の一次拒否を残す"
    assert re.findall(r'href="([^"]+)"', INDEX_TEMPLATE.read_text(encoding="utf-8")) == [
        "latest_morning_brief.md", "latest_morning_brief.json", "../"]


def test_production_runtime_closure_excludes_every_research_subsystem() -> None:
    """ファイルの有無ではなく **import 到達性** で検査する（両 tree で同じ意味）。"""
    closure = runtime_closure()
    assert closure, "runtime closure could not be computed"
    for package in EXCLUDED_PACKAGES:
        reached = sorted(p for p in closure
                         if p.startswith(f"src/intelligence/{package}/"))
        assert reached == [], (package, reached[:3])


def test_production_runtime_closure_touches_no_confidential_tree() -> None:
    closure = runtime_closure()
    for prefix in ("date/", "output/", "data/", "research/"):
        assert not [p for p in closure if p.startswith(prefix)], prefix


def test_b2c_utilities_are_stdlib_only_and_never_import_vnext() -> None:
    for name in B2C_SCRIPTS:
        path = REPO_ROOT / "scripts" / f"{name}.py"
        tops: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                tops.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                tops.update(a.name.split(".")[0] for a in node.names)
        assert "src" not in tops, name
        assert tops <= set(sys.stdlib_module_names), sorted(tops - set(sys.stdlib_module_names))


# ---------------------------------------------------------------- config policy

def test_config_declares_the_pages_parallel_policy_matching_the_gate() -> None:
    """`pages_parallel_publication` は runtime ではなく **policy 記述**であり、
    実効定数との drift をここで止める（Gate 5A-R: runtime は読まない）。"""
    section = yaml.safe_load(CONFIG.read_text(encoding="utf-8")).get(
        "pages_parallel_publication")
    assert section, "pages_parallel_publication section is missing"
    import importlib.util

    def load(name):
        spec = importlib.util.spec_from_file_location(
            name, REPO_ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    gate = load("p43b2c_v2_gate")
    selector = load("p43b2c_select_producer")
    graft = load("p43b2c_graft_v2")
    manifest = load("p43b2c_pages_manifest")
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


def test_confidentiality_guard_is_present_in_the_bundle() -> None:
    source = CONFIDENTIAL_GUARD.read_text(encoding="utf-8")
    for symbol in ("def test_no_pdf_is_git_tracked(",
                   "def test_confidential_paths_are_gitignored(",
                   "def test_sensitive_identifier_files_not_tracked("):
        assert symbol in source, symbol
