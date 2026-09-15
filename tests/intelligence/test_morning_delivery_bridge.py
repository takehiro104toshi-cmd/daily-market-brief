"""P4-3b1 production producer の構造ガード（Phase 4 P4-3b1）。

b1 は **producer の実証のみ**であり、公開経路（Pages / 通知 / リポジトリ出力）へは
一切接続しない。その境界を workflow 定義とリポジトリ設定の**静的検査**で固定する。

- ネットワークを使わない。GitHub そのものを検証しない（設定と契約だけを見る）。
- 「〜しない」系の検査は **parse 済み YAML**（＝実行される内容）に対して行う。
  ヘッダコメントは実行されないため、コメントの文言で検査を汚さない。
- artifact 検証 step は禁止拡張子を**denylist として列挙する**性質上、
  同じ token を含む。当該 step 本文は除外してから走査する。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

PRODUCER_WORKFLOW = WORKFLOW_DIR / "p43b1-morning-delivery-producer.yml"
P2D_WORKFLOW = WORKFLOW_DIR / "p2d-market-pilot.yml"
LEGACY_WORKFLOW = WORKFLOW_DIR / "daily-market-brief.yml"

CLOSEOUT_TEST = REPO_ROOT / "tests" / "intelligence" / "test_live_run_closeout.py"
CLOSEOUT_DOC = REPO_ROOT / "docs" / "databank" / "LIVE_RUN_CLOSEOUT_PROTOCOL.md"
IMPORT_BOUNDARY_TEST = REPO_ROOT / "tests" / "intelligence" / "test_import_boundary.py"
ROADMAP = REPO_ROOT / "docs" / "rebuild" / "REBUILD_ROADMAP.md"

#: b1 が起動してよい vNext entrypoint（凍結済みのものだけ。新設しない）
ALLOWED_MODULES = {
    "src.intelligence.market.pilot_runner",
    "src.intelligence.reports.delivery_pilot",
}
#: 隔離 output root（p2d-market-pilot と同一）
DELIVERY_OUTPUT_ROOT = "${{ runner.temp }}/p43_delivery_output/v2"
DATA_ROOT = "${{ runner.temp }}/intelligence_data"
ARTIFACT_NAME = "morning-delivery-v2"
EXPECTED_TIMEOUT = 15

#: reachability 用の専用 trigger（既存 pilot と同一機構・同一 branch 限定）
FEATURE_BRANCH = "claude/investment-intelligence-phase0-rvdplu"
TRIGGER_PATH = ".github/p43b1_producer_trigger"
TRIGGER_FILE = REPO_ROOT / TRIGGER_PATH

#: producer の step 構成（reachability fix で変えてはならない）
EXPECTED_STEP_NAMES = (
    None,                                                    # actions/checkout@v4
    None,                                                    # actions/setup-python@v5
    "Install minimal deps",
    "Security guard (confidential tracking check)",
    "Run market data bank live pilot (1 request per series)",
    "Phase 4 P4-3b1 Morning Delivery producer (isolated artifacts)",
    "Verify exactly the four approved artifacts",
    "Upload Morning Delivery artifacts",
)

_MODULE = re.compile(r"python\b[^\n|;&]*?-m\s+([A-Za-z0-9_.]+)")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def producer() -> dict:
    return _load(PRODUCER_WORKFLOW)


def producer_jobs() -> dict:
    return producer().get("jobs") or {}


def producer_steps() -> list:
    steps: list = []
    for job in producer_jobs().values():
        steps.extend(job.get("steps") or [])
    return steps


def producer_triggers() -> dict:
    """`on:` は PyYAML で True キーになるため両方を見る。"""
    data = producer()
    raw = data.get("on", data.get(True))
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {key: None for key in raw}
    return {str(raw): None}


def _step_named(fragment: str) -> dict:
    for step in producer_steps():
        if fragment in str(step.get("name", "")):
            return step
    raise AssertionError(f"step not found: {fragment}")


def verify_step() -> dict:
    return _step_named("Verify exactly the four approved artifacts")


def executable_text() -> str:
    """実行される内容だけの文字列（コメントは落ちる）。"""
    return yaml.safe_dump(producer(), allow_unicode=True, sort_keys=True)


def executable_text_without_denylist() -> str:
    """artifact 検証 step（禁止拡張子を列挙する）を除いた実行内容。

    `safe_dump` は run 本文を再整形するため、文字列 replace では消えない。
    step ノードごと落としてから dump する。
    """
    data = _load(PRODUCER_WORKFLOW)
    target = verify_step()["name"]
    for job in (data.get("jobs") or {}).values():
        job["steps"] = [s for s in (job.get("steps") or [])
                        if str(s.get("name", "")) != target]
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=True)


# --- 1〜4: workflow の存在と起動条件 -------------------------------------------------

def test_producer_workflow_exists() -> None:
    assert PRODUCER_WORKFLOW.is_file(), "P4-3b1 producer workflow が存在すること"
    assert producer().get("name") == "p43b1-morning-delivery-producer", \
        "workflow name はファイル名と一致させる（既存 pilot の命名規約）"
    assert producer_jobs(), "job が定義されていること"


def test_producer_supports_workflow_dispatch() -> None:
    assert "workflow_dispatch" in producer_triggers(), \
        "手動起動（workflow_dispatch）を必ず持つこと"


def test_producer_declares_no_invented_schedule() -> None:
    """日次時刻は監督者決定事項。推測の cron を置かない。"""
    triggers = producer_triggers()
    assert "schedule" not in triggers, \
        "daily schedule は監督者決定。cron を推測で置かない"
    assert "pull_request" not in triggers
    assert set(triggers) == {"workflow_dispatch", "push"}, \
        f"b1 の trigger は workflow_dispatch と専用 trigger file の push のみ: {sorted(triggers)}"


def test_producer_push_trigger_is_scoped_to_the_dedicated_trigger_file() -> None:
    """reachability 用 push は専用 trigger file 1 本にだけ反応する（既存 pilot と同一機構）。"""
    push = producer_triggers()["push"]
    assert isinstance(push, dict), "push trigger は branches / paths を持つこと"
    assert push.get("paths") == [TRIGGER_PATH], \
        f"push は {TRIGGER_PATH} のみに path 限定すること: {push.get('paths')}"
    assert push.get("branches") == [FEATURE_BRANCH], \
        f"push は feature branch のみに限定すること: {push.get('branches')}"


def test_producer_has_no_broad_push_trigger() -> None:
    """branch 全体・path 無制限・tag への反応を作らない。"""
    push = producer_triggers()["push"]
    assert set(push) == {"branches", "paths"}, \
        f"push trigger の key は branches / paths のみ: {sorted(push)}"
    for widening in ("branches-ignore", "paths-ignore", "tags", "tags-ignore"):
        assert widening not in push, f"push の範囲を広げる {widening} を使わない"
    # 既存 pilot（p1c / p2a / p2d / p2h）と同じ形であること
    for name in ("p1c-live-validation.yml", "p2a-e2e-pilot.yml",
                 "p2d-market-pilot.yml", "p2h-jquants-light.yml"):
        data = _load(WORKFLOW_DIR / name)
        other = (data.get("on", data.get(True)) or {})["push"]
        assert other.get("branches") == [FEATURE_BRANCH], \
            f"{name}: 参照した規約が変わっている"
        assert len(other.get("paths") or []) == 1, \
            f"{name}: 参照した規約が変わっている（trigger file は 1 本）"


def test_trigger_file_exists_and_is_inert() -> None:
    """trigger file は push event を作るためだけのもの。読まれも実行もされない。"""
    assert TRIGGER_FILE.is_file(), f"{TRIGGER_PATH} を作成すること"
    text = TRIGGER_FILE.read_text(encoding="utf-8")
    assert 0 < len(text) < 1024, "trigger file は小さな注記のみ"
    # workflow はこの file を読まない（p1c のように内容を parse しない）
    for step in producer_steps():
        assert TRIGGER_PATH not in str(step.get("run", "")), \
            "producer は trigger file の内容を読まない"
    lowered = text.lower()
    for forbidden in ("api_key", "secret", "token", "password", "bearer",
                      "$(", "`", "curl ", "python -m", "rm ", "http://", "https://"):
        assert forbidden not in lowered, \
            f"trigger file に資格情報・コマンドを書かない: {forbidden}"


def test_producer_steps_are_unchanged_by_the_reachability_fix() -> None:
    """reachability fix は trigger section のみ。step 構成は変えない。"""
    steps = producer_steps()
    assert len(steps) == len(EXPECTED_STEP_NAMES), \
        f"step 数が変わっている: {len(steps)}"
    for step, expected in zip(steps, EXPECTED_STEP_NAMES):
        if expected is None:
            assert "uses" in step and "run" not in step, "先頭 2 step は action のみ"
        else:
            assert step.get("name") == expected, \
                f"step 名/順序が変わっている: {step.get('name')} != {expected}"
    assert steps[0]["uses"] == "actions/checkout@v4"
    assert steps[1]["uses"].startswith("actions/setup-python@")
    assert steps[-1]["uses"].startswith("actions/upload-artifact@")
    job = next(iter(producer_jobs().values()))
    assert set(job) == {"runs-on", "timeout-minutes", "steps"}, \
        f"job の構成要素が変わっている: {sorted(job)}"


def test_producer_declares_explicit_timeout() -> None:
    for name, job in producer_jobs().items():
        timeout = job.get("timeout-minutes")
        assert isinstance(timeout, int) and timeout > 0, \
            f"{name}: 待機上限が計算できるよう timeout-minutes を明示すること"
        assert timeout == EXPECTED_TIMEOUT, \
            f"{name}: 実測（約6分）に対し過大でない上限 {EXPECTED_TIMEOUT} 分を使う"


# --- 5〜9: 実行内容 ------------------------------------------------------------------

def test_producer_runs_the_confidentiality_guard() -> None:
    step = _step_named("Security guard")
    assert "tests/intelligence/test_confidential_guard.py" in step["run"], \
        "本番 workflow と同じ機密ガードを artifact 生成前に走らせること"


def test_producer_reuses_the_proven_market_bank_command() -> None:
    """第二の Market Bank 経路を作らない（p2d と同一コマンド）。"""
    p2d_steps = []
    for job in (_load(P2D_WORKFLOW).get("jobs") or {}).values():
        p2d_steps.extend(job.get("steps") or [])
    proven = [s["run"].strip() for s in p2d_steps
              if "src.intelligence.market.pilot_runner" in str(s.get("run", ""))]
    assert len(proven) == 1, "p2d の Market Bank step は 1 つであること"
    ours = [s["run"].strip() for s in producer_steps()
            if "src.intelligence.market.pilot_runner" in str(s.get("run", ""))]
    assert ours == proven, \
        f"Market Bank コマンドは実証済みのものと同一にする: {ours} != {proven}"


def test_producer_builds_intelligence_data_in_runner_temp() -> None:
    roots = {step.get("env", {}).get("INTELLIGENCE_DATA_ROOT")
             for step in producer_steps() if step.get("env")}
    roots.discard(None)
    assert roots == {DATA_ROOT}, \
        f"INTELLIGENCE_DATA_ROOT は runner.temp 配下のみ: {roots}"


def test_producer_uses_isolated_delivery_output_root() -> None:
    roots = {step.get("env", {}).get("P43_DELIVERY_OUTPUT_ROOT")
             for step in producer_steps() if step.get("env")}
    roots.discard(None)
    assert roots == {DELIVERY_OUTPUT_ROOT}, \
        f"P43_DELIVERY_OUTPUT_ROOT は runner.temp 配下のみ: {roots}"
    assert DELIVERY_OUTPUT_ROOT != DATA_ROOT


def test_producer_invokes_the_frozen_delivery_pilot() -> None:
    runs = [str(step.get("run", "")) for step in producer_steps()]
    assert any("-m src.intelligence.reports.delivery_pilot" in run for run in runs), \
        "凍結済み delivery_pilot を起動すること（D-2）"


# --- 10〜12: artifact 契約 -----------------------------------------------------------

def test_producer_uploads_an_actions_artifact() -> None:
    uploads = [s for s in producer_steps() if "upload-artifact" in str(s.get("uses", ""))]
    assert len(uploads) == 1, "artifact upload は 1 step のみ"
    with_ = uploads[0].get("with") or {}
    assert with_.get("name") == ARTIFACT_NAME, \
        "artifact 名は固定（timestamp・path・credential を含めない）"
    for forbidden in ("${{", "/", "\\"):
        assert forbidden not in str(with_["name"]), "artifact 名に path/式を含めない"


def test_producer_uploads_only_the_isolated_delivery_root() -> None:
    upload = next(s for s in producer_steps() if "upload-artifact" in str(s.get("uses", "")))
    path = str((upload.get("with") or {}).get("path", ""))
    assert path == DELIVERY_OUTPUT_ROOT, \
        f"upload 対象は隔離 delivery root のみ: {path}"
    assert (upload.get("with") or {}).get("if-no-files-found") == "error", \
        "空 artifact を黙って成功させない"


def test_exact_four_file_verification_runs_before_upload() -> None:
    steps = producer_steps()
    names = [str(s.get("name", "")) for s in steps]
    verify_at = names.index(verify_step()["name"])
    upload_at = next(i for i, s in enumerate(steps)
                     if "upload-artifact" in str(s.get("uses", "")))
    assert verify_at < upload_at, "4 file 検証は upload の**前**に行う"
    body = verify_step()["run"]
    assert '!= "4"' in body, "承認済み 4 file ちょうどであることを数で確かめる"
    assert "latest_morning_brief.md" in body and "latest_morning_brief.json" in body
    assert "_morning_brief" in body and "exit 1" in body, \
        "不一致時は job を失敗させること"
    for denied in ("*.html", "*.sqlite3", "*.jsonl", "*.db", "index*", "*.part"):
        assert denied in body, f"想定外 entry の検出に {denied} を含めること"


# --- 13〜21: b1 が「しない」こと ------------------------------------------------------

def test_producer_never_writes_repository_output_v2() -> None:
    # `p43_delivery_output/v2` は runner.temp 配下。これを除いた上で照合する。
    text = executable_text().replace("p43_delivery_output/v2", "")
    assert "output/v2" not in text, "リポジトリの output/v2 へは書かない（b2 の範囲）"


def test_producer_contains_no_git_write_commands() -> None:
    text = executable_text()
    for forbidden in ("git add", "git commit", "git push", "git rebase", "git merge"):
        assert forbidden not in text, f"b1 は生成物を commit/push しない: {forbidden}"


def test_producer_does_not_prepare_or_deploy_pages() -> None:
    text = executable_text()
    for forbidden in ("pages-site", "upload-pages-artifact", "deploy-pages",
                      "github-pages", "actions/configure-pages"):
        assert forbidden not in text, f"b1 は Pages に触れない: {forbidden}"
    permissions = producer().get("permissions") or {}
    assert permissions == {"contents": "read"}, \
        f"権限は読み取りのみ（pages / id-token を持たない）: {permissions}"


def test_producer_does_not_invoke_notifiers_or_legacy_entrypoint() -> None:
    text = executable_text()
    for forbidden in ("notifiers", "main.py", "EmailNotifier", "LineNotifier",
                      "cloudflare", "wrangler"):
        assert forbidden not in text, f"b1 は通知経路・legacy entrypoint を呼ばない: {forbidden}"


def test_producer_generates_no_html() -> None:
    text = executable_text_without_denylist()
    for forbidden in ("html", "legacy.html", "index.html", "html_builder"):
        assert forbidden not in text, f"b1 は HTML を作らない（D-4）: {forbidden}"


# --- 22〜23: 既存の凍結資産を変更していないこと ---------------------------------------

def test_legacy_production_workflow_is_untouched_by_b1() -> None:
    text = LEGACY_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("p43", "delivery_pilot", "morning-delivery", "morning_brief",
                      "output/v2"):
        assert forbidden not in text, \
            f"b1 は本番 workflow を変更しない（b2 で別途承認）: {forbidden}"
    assert "cp output/latest_market_brief.html pages-site/index.html" in text, \
        "legacy の Pages 導線は現状のまま"
    assert set((_load(LEGACY_WORKFLOW).get("jobs") or {})) == {
        "generate-report", "deploy-pages"}, "本番 workflow の job 構成は不変"


def test_import_boundary_contract_is_unchanged() -> None:
    text = IMPORT_BOUNDARY_TEST.read_text(encoding="utf-8")
    assert ('LEGACY_FORBIDDEN_PREFIXES = (\n'
            '    "src.analysis", "src.report", "src.collectors", "src.data", "src.date",\n'
            '    "notifiers", "main", "scripts",\n'
            ')') in text, "LEGACY_FORBIDDEN_PREFIXES を緩和しない"
    for name in ("def test_vnext_does_not_import_legacy(",
                 "def test_vnext_is_llm_vendor_neutral(",
                 "def test_legacy_does_not_import_vnext_yet("):
        assert name in text, f"import 境界テストを削らない: {name}"
    assert "p43" not in text and "delivery" not in text, \
        "b1 は import 境界テストへ例外を追加しない"


# --- 24〜25: Automated Closeout 登録 --------------------------------------------------

def test_producer_is_registered_for_automated_closeout() -> None:
    text = CLOSEOUT_TEST.read_text(encoding="utf-8")
    assert f'"{PRODUCER_WORKFLOW.name}"' in text, \
        "Automated Closeout の追跡対象へ登録すること（D-6）"
    assert "set(documented) == set(CLOSEOUT_WORKFLOWS)" in text, \
        "完全一致の assertion を弱めない"


def test_closeout_protocol_documents_the_producer_timeout() -> None:
    doc = CLOSEOUT_DOC.read_text(encoding="utf-8")
    row = re.search(rf"^\|\s*`?{re.escape(PRODUCER_WORKFLOW.name)}`?\s*\|\s*(\d+)\s*\|",
                    doc, re.MULTILINE)
    assert row, "closeout protocol の待機上限表へ追記すること"
    assert int(row.group(1)) == EXPECTED_TIMEOUT, \
        "doc の timeout は workflow の宣言値と一致させる"
    assert "::P43_HEAD" in doc, "evidence 取得用の marker を protocol へ記載すること"


# --- 26〜29: 隔離と失敗の独立性 -------------------------------------------------------

def test_producer_never_uploads_the_intelligence_data_root() -> None:
    for step in producer_steps():
        path = str((step.get("with") or {}).get("path", ""))
        if not path:
            continue
        assert DATA_ROOT not in path, "Market Bank / Compass internals を upload しない"
        assert "intelligence_data" not in path


def test_producer_never_hides_failure_with_continue_on_error() -> None:
    assert "continue-on-error" not in executable_text(), \
        "producer の失敗を隠さない"
    for job in producer_jobs().values():
        assert "continue-on-error" not in job


def test_producer_failure_is_independent_from_the_legacy_workflow() -> None:
    for name, job in producer_jobs().items():
        assert "needs" not in job, f"{name}: 他 workflow / job へ依存しない"
    text = executable_text()
    for forbidden in ("daily-market-brief", "workflow_call", "workflow_run"):
        assert forbidden not in text, \
            f"legacy workflow と相互依存しない: {forbidden}"
    assert "workflow_run" not in producer_triggers()
    legacy = LEGACY_WORKFLOW.read_text(encoding="utf-8")
    assert PRODUCER_WORKFLOW.stem not in legacy, \
        "本番 workflow から b1 を呼ばない"


def test_producer_uses_only_frozen_vnext_entrypoints() -> None:
    modules: set = set()
    for step in producer_steps():
        modules.update(_MODULE.findall(str(step.get("run", ""))))
    assert modules == ALLOWED_MODULES, \
        f"b1 は凍結済み entrypoint だけを使う（新設しない）: {sorted(modules)}"
    for module in sorted(modules):
        path = REPO_ROOT.joinpath(*module.split(".")).with_suffix(".py")
        assert path.is_file(), f"{module} が実ファイルとして存在すること"


# --- 30: roadmap ---------------------------------------------------------------------

def test_roadmap_keeps_p4_3_incomplete() -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    assert "- [ ] P4-3 (S) 配信" in text, "P4-3 全体は未完のままにする"
    assert "- [x] P4-3 " not in text, "P4-3 を完了扱いにしない"
    assert "P4-3a Morning Delivery packaging / artifact — **完了・凍結" in text, \
        "P4-3a の CLOSED / FROZEN を sub-note として記録すること"
    for evidence in ("03e62d5", "aa5373f", "34927100267",
                     "Morning Delivery schema 0.1.0",
                     "docs/databank/MORNING_DELIVERY_SPEC.md"):
        assert evidence in text, f"closeout の証跡を記載すること: {evidence}"
    assert "P4-3b bridge" in text and "IN PROGRESS" in text
