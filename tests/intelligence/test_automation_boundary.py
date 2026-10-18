"""P12-A1 — Phase 12（自動化の純粋な domain ／ state 層）の境界の guard。

- registry の完全一致 ・P12_BASE 以後の面は登録した P12 の追加だけ ・凍結の P7 〜 P11 の test の差分は宣言した登録の行だけ。
- runtime は stdlib の純粋な model だけ: 時計 ・OS ・path ・file ・環境変数 ・socket ・subprocess ・乱数 ・network ・資格情報 ・
  凍結の phase の import ・free-form な payload ・投資の語彙は無い。CLI ・`__main__` も無い。
- 凍結の Phase 4 〜 11 の runtime は anchor と object 一致（P8 ・P9 ・P10 ・P11）・P12_BASE から不変（src 全体）。
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from tests.intelligence.phase7_runtime_registry import PHASE7_RUNTIME
from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import P9_A5, PHASE9_RUNTIME
from tests.intelligence.phase10_runtime_registry import P10_A4, PHASE10_RUNTIME
from tests.intelligence.phase11_runtime_registry import P11_A5, PHASE11_RUNTIME
from tests.intelligence.phase12_runtime_registry import (FORBIDDEN_P12_IMPORT_PARTS, P12_BASE, PHASE12_A1_RUNTIME,
                                                         PHASE12_DOCS, PHASE12_PACKAGE, PHASE12_RUNTIME,
                                                         PHASE12_TEST_REGISTRATION, PHASE12_TESTS, SANCTIONED_P12_MODULES,
                                                         SANCTIONED_P12_STDLIB, is_phase12_addition,
                                                         only_phase12_registration)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE12_PACKAGE
CONTRACT_DOC = "docs/databank/PHASE12_A1_SCHEDULE_RUN_STATE_MODEL.md"
P11_FREEZE_DOC = "docs/databank/PHASE11_FINAL_FREEZE.md"
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "main.py", "requirements.txt",
                  "pyproject.toml", "cloudflare", "notifiers", "src/report")
#: runtime が呼んではならない名前（file ・OS ・時計 ・環境 ・process ・socket ・乱数 ・出力）
FORBIDDEN_NAMES = {"open", "write", "write_text", "write_bytes", "read_text", "read_bytes", "mkdir", "unlink", "remove",
                   "rename", "environ", "getenv", "now", "today", "utcnow", "fromtimestamp", "utcfromtimestamp", "print",
                   "input", "sleep", "eval", "exec", "setattr", "random", "urandom", "uuid4", "system", "popen",
                   "Popen", "check_output", "socket", "connect", "bind", "listen", "urlopen", "Thread", "Timer",
                   "fork", "spawn", "getcwd", "chdir", "stat", "glob", "rglob", "iterdir", "exists"}
#: identifier の語（camel ／ snake を割った小文字）で禁じる語彙（投資 ・LLM ・時計の相対語 ・scheduler の実装語）
FORBIDDEN_WORDS = {"rank", "ranking", "score", "scoring", "recommend", "recommendation", "buy", "sell", "portfolio",
                   "allocation", "conviction", "priority", "weight", "rating", "position", "trade", "urgency",
                   "confidence", "return", "returns", "price", "holding", "holdings", "rebalance", "suitability", "llm",
                   "prompt", "latest", "current", "now", "cron", "subprocess", "socket", "thread", "push", "notify",
                   "credential", "secret", "apikey", "token", "jquants", "path", "filename", "payload", "message"}
#: 文書 ・直列化に在ってはならない private な値の形（Windows の path ・時刻つきの瞬間 ・5 桁の code ・id の接頭辞 ・著者）
PRIVATE_PATTERNS = (r"[A-Za-z]:\\", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r"\b\d{5}\b", r"p9wat_", r"p9ths_", r"p8iss_", r"p10prf_",
                    r"p10att_", r"human:", r"x-api-key", r"api\.jquants")
STATIC_STRING_BANS = ("x-api-key", "api.jquants.com", "JQUANTS", "config.yaml", "://", "D:\\", "0.0.0.0", "127.0.0.1",
                      "__main__", "argparse", "sys.argv", "schtasks", "Task Scheduler")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, encoding="utf-8", errors="strict",
                          check=True).stdout


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _blob_ids(anchor: str, paths) -> tuple:
    anchored = tuple(_git("rev-parse", *(f"{anchor}:{path}" for path in paths)).split())
    current = tuple(_git("hash-object", "--", *paths).split())
    return anchored, current


def _imports(path: Path):
    relative, absolute = {}, set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + (node.module or ""), set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


# ================================================ registry ・面 ・凍結の test の登録


def test_p12_a1_the_registry_is_exact_and_disjoint_from_earlier_phases() -> None:
    assert P12_BASE == "080d42aa3dad8bfc5ef82400beb6e2c62a873126"
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P12_BASE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert PHASE12_RUNTIME == tuple(sorted(PHASE12_A1_RUNTIME)) and len(PHASE12_RUNTIME) == 11
    assert all(p.startswith(PHASE12_PACKAGE + "/") and p.endswith(".py") for p in PHASE12_RUNTIME)
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE12_RUNTIME}
    for path in (*PHASE12_RUNTIME, *PHASE12_TESTS, *PHASE12_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert not set(PHASE12_RUNTIME) & (set(PHASE11_RUNTIME) | set(PHASE10_RUNTIME) | set(PHASE9_RUNTIME)
                                       | set(PHASE8_RUNTIME) | set(PHASE7_RUNTIME))
    assert not any(_git("ls-tree", P12_BASE, "--", p).strip() for p in (*PHASE12_RUNTIME, *PHASE12_TESTS, *PHASE12_DOCS))
    assert set(SANCTIONED_P12_MODULES) == set(PHASE12_RUNTIME)
    assert is_phase12_addition("A", PHASE12_RUNTIME[0]) and is_phase12_addition("??", PHASE12_RUNTIME[0])
    assert not is_phase12_addition("M", PHASE12_RUNTIME[0])                                # A1 の runtime の修正は受けない
    assert not is_phase12_addition("A", f"{PHASE12_PACKAGE}/other.py") and not is_phase12_addition("A", PHASE11_RUNTIME[0])


def test_p12_a1_since_the_base_only_registered_phase12_files_and_declared_registration_changed() -> None:
    assert _changes("--cached", "--name-status", P12_BASE, "--", "src") == {("A", p) for p in PHASE12_RUNTIME}
    assert _git("diff", "--cached", "--name-status", P12_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P12_BASE, "--", "docs") <= {("A", p) for p in PHASE12_DOCS}
    assert _changes("--cached", "--name-status", P12_BASE, "--", "tests") <= {
        ("A", p) for p in PHASE12_TESTS} | {("M", p) for p in PHASE12_TEST_REGISTRATION}
    assert set(PHASE12_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                              "tests/intelligence/test_narrative_intelligence_boundary.py",
                                              "tests/intelligence/test_screener_intelligence_boundary.py",
                                              "tests/intelligence/test_watchlist_thesis_boundary.py",
                                              "tests/intelligence/test_personal_intelligence_boundary.py",
                                              "tests/intelligence/test_personal_ui_boundary.py"}
    for path in PHASE12_TEST_REGISTRATION:                                            # 凍結の P7 〜 P11 の test の狭い再開
        anchored = _git("show", f"{P12_BASE}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase12_registration(path, anchored, current), path
        assert not only_phase12_registration(path, anchored, current + "assert True\n")
        assert not only_phase12_registration(path, anchored, anchored)
    for registry in ("tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/phase9_runtime_registry.py",
                     "tests/intelligence/phase10_runtime_registry.py", "tests/intelligence/phase11_runtime_registry.py"):
        assert _git("diff", "--name-status", P12_BASE, "--", registry) == "", registry   # 前の phase の registry は不変
    pending = [line for line in _git("status", "--porcelain", "--", "src").splitlines()
               if not is_phase12_addition(line[:2].strip(), line[3:])]
    assert pending == []                                                                  # 作業木に未登録の src の変更なし


def test_p12_a1_frozen_phase4_to_11_runtime_is_object_identical_to_its_anchor_and_unchanged_since_the_base() -> None:
    for anchor, runtime in ((P11_A5, PHASE11_RUNTIME), (P10_A4, PHASE10_RUNTIME), (P9_A5, PHASE9_RUNTIME),
                            (P8_B5C, PHASE8_RUNTIME)):
        anchored, current = _blob_ids(anchor, runtime)
        assert len(anchored) == len(current) == len(runtime)
        assert [p for p, a, c in zip(runtime, anchored, current) if a != c] == []
    assert len(PHASE11_RUNTIME) == 12 and len(PHASE10_RUNTIME) == 17 and len(PHASE9_RUNTIME) == 18 and len(PHASE8_RUNTIME) == 54
    assert P11_A5 == "43c0b856d41efed397de213a1a06178c5e97ab10"
    excluded = [f":(exclude,literal){p}" for p in PHASE12_RUNTIME]
    assert _git("diff", "--name-status", P12_BASE, "--", "src", *excluded) == ""           # Phase 4 〜 11 の src 全体
    assert _git("diff", "--cached", "--name-status", P12_BASE, "--", "src", *excluded) == ""
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME, *PHASE9_RUNTIME, *PHASE10_RUNTIME,
                *PHASE11_RUNTIME) == ""
    assert _git("diff", "--name-status", P12_BASE, "--", P11_FREEZE_DOC, "docs/databank/PHASE10_FINAL_FREEZE.md") == ""
    assert _git("show", f"{P12_BASE}:{P11_FREEZE_DOC}") == (REPO_ROOT / P11_FREEZE_DOC).read_text(encoding="utf-8")


# ================================================ import ・名前 ・語彙 ・直列化


def test_p12_a1_imports_are_stdlib_only_and_never_reach_frozen_phases_os_clock_network_or_process() -> None:
    for path in PHASE12_RUNTIME:
        relative, absolute = _imports(REPO_ROOT / path)
        assert absolute <= SANCTIONED_P12_STDLIB, (path, absolute - SANCTIONED_P12_STDLIB)
        assert set(relative) == SANCTIONED_P12_MODULES[path], (path, set(relative))
        assert not any(m.startswith("..") for m in relative), path                        # package の外へは出ない
        for module in (*relative, *absolute):
            components = set(module.lstrip(".").split("."))
            assert not components & set(FORBIDDEN_P12_IMPORT_PARTS), (path, module)
        assert not any(n.startswith("_") and n != "_require_id" and n != "_require_int" for names in relative.values()
                       for n in names), path
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        for token in STATIC_STRING_BANS:
            assert token not in source, (path, token)
        assert "ZoneInfo" not in source and "zoneinfo" not in source                     # 固定 +09:00 だけ（tzdata に依らない）


def test_p12_a1_the_runtime_never_touches_files_env_clock_process_or_network_and_has_no_investment_vocabulary() -> None:
    for path in PHASE12_RUNTIME:
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_NAMES, (path, node.id)
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_NAMES, (path, node.attr)
                identifiers.add(node.attr)
            elif isinstance(node, ast.arg):
                identifiers.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                identifiers.add(node.name)
            elif isinstance(node, ast.ExceptHandler):
                assert node.type is not None, (path, "bare except")
                names = {node.type.id} if isinstance(node.type, ast.Name) else {
                    e.id for e in getattr(node.type, "elts", ()) if isinstance(e, ast.Name)}
                assert not names & {"Exception", "BaseException"}, (path, "broad except")
            elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                left = node.test.left
                assert not (isinstance(left, ast.Name) and left.id == "__name__"), (path, "__main__")
        words = set()
        for name in identifiers:
            words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}
        assert not words & FORBIDDEN_WORDS, (path, words & FORBIDDEN_WORDS)


def test_p12_a1_serialization_of_every_model_is_canonical_and_free_of_paths_payloads_and_private_shapes() -> None:
    from datetime import datetime, timezone
    from src.intelligence.automation.holiday_calendar import HolidayCalendar
    from src.intelligence.automation.ledger_model import make_record
    from src.intelligence.automation.run_identity import AutomationRun
    from src.intelligence.automation.run_planning import plan_run
    from src.intelligence.automation.run_state import RunState
    from src.intelligence.automation.schedule_model import TIMEZONE_V1, AutomationSchedule, ScheduleSlot
    from src.intelligence.automation.status_projection import project_status

    cal = HolidayCalendar(calendar_id="ops-cal", version=1, dates=())
    slot = ScheduleSlot(slot_id="slot-a", local_time="07:30", weekday_mask=("MON", "TUE", "WED", "THU", "FRI"),
                        late_window_seconds=3600, readiness_on_non_business_day=False, enabled=True)
    sched = AutomationSchedule(schedule_id="ops-daily", version=1, timezone=TIMEZONE_V1, enabled=True, slots=(slot,),
                               holiday_calendar_ref=cal.reference(), created_at="2026-01-01T00:00:00Z")
    planned = plan_run(sched, cal, slot_id="slot-a", selection_clock_at=datetime(2026, 1, 4, 22, 45, tzinfo=timezone.utc))
    run = AutomationRun.from_planned(planned, "a" * 40)
    r0 = make_record(None, run, transition_to=RunState.PLANNED, recorded_at="2026-01-04T22:46:00Z")
    status = project_status([r0], runtime_anchor="a" * 40, schedule_id="ops-daily")
    import json
    rendered = [sched.to_json(), cal.to_json(), json.dumps(planned.to_dict()), json.dumps(run.to_dict()), r0.to_json(),
                json.dumps(status.to_dict())]
    for text in rendered:
        assert json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=False) == text or \
            text == json.dumps(json.loads(text))                                          # 正準（to_json）か json.dumps の形
        for pattern in (r"[A-Za-z]:\\", r"/[a-z]+/", r"\b\d{5}\b", r"p9wat_", r"p10prf_", r"human:", r"Traceback"):
            assert not re.search(pattern, text), (pattern, text[:80])
        assert "payload" not in text and "message" not in text and "exception" not in text.lower()


# ================================================ 公開の面 ・文書


def test_p12_a1_is_outside_production_and_public_code_and_nothing_else_imports_it() -> None:
    assert not any("automation" in module for module in runtime_closure())
    code_roots = [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")), *sorted((REPO_ROOT / "scripts").rglob("*.py"))]
    if (REPO_ROOT / "notifiers").is_dir():
        code_roots += sorted((REPO_ROOT / "notifiers").rglob("*.py"))
    for path in code_roots:
        if PACKAGE_DIR in path.parents:
            continue
        assert "intelligence.automation" not in path.read_text(encoding="utf-8", errors="replace"), path
    for root in (".github", "docs/pages", "cloudflare"):
        if not (REPO_ROOT / root).is_dir():
            continue
        for path in sorted((REPO_ROOT / root).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".yml", ".yaml", ".html", ".js", ".toml", ".md"):
                assert "intelligence/automation" not in path.read_text(encoding="utf-8", errors="replace"), path


def test_p12_a1_the_contract_records_the_required_clauses_and_no_private_values() -> None:
    text = (REPO_ROOT / CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in (P12_BASE, "43c0b856d41efed397de213a1a06178c5e97ab10", "運用の authority", "市場の authority ではない",
                   "実行の証拠", "昇格しない", "projection は authority ではない", "selection_clock_at", "scheduled_for",
                   "started_at", "completed_at", "recorded_at", "hash 鎖", "改変の検出", "認証ではない", "署名ではない",
                   "ORPHANED_FINALIZATION", "黙って消さない", "retry は新しい run", "p12.automation_run.v1", "retry_of",
                   "supersedes", "Asia/Tokyo", "+09:00", "PHASE12_TEST_REGISTRATION", "Phase 12 の凍結ではない",
                   "REPO_NOT_CLEAN", "FROZEN_DRIFT", "SOURCE_INCOMPLETE", "DUPLICATE_INVOCATION", "INTERRUPTED",
                   "scheduler は無い", "subprocess", "P12-A2"):
        assert clause in text, clause
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for banned in ("signed", "署名済み", "D:\\", "0.0.0.0"):
        assert banned not in text, banned
