"""P10-A4 — 管理の初期化と private ・local の CLI の test（明示の root ・瞬間 ・日だけ ・既定の出力は件数 ／ 受領だけ）。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.intelligence.personal_intelligence import store_io
from src.intelligence.personal_intelligence.admin_init import InitRefusal, InitStatus, init_personal_root
from src.intelligence.personal_intelligence.local_cli import main
from tests.intelligence.test_personal_intelligence_executor import AUTHOR, MARKER, build_p9, tree
from tests.intelligence.test_watchlist_thesis_semantics import HOUR, ISSUER2, T0

REPO_ROOT = Path(__file__).resolve().parents[2]
DIR = store_io.PERSONAL_DIRNAME


def run(*argv: str):
    out = io.StringIO()
    code = main(list(argv), stdout=out)
    lines = out.getvalue().splitlines()
    assert len(lines) == 1, lines
    return code, json.loads(lines[0]), lines[0]


def decision_file(tmp: Path, name: str, payload: dict) -> str:
    path = tmp / name
    path.write_bytes(json.dumps(payload).encode("utf-8"))
    return str(path)


def profile_payload(**over) -> dict:
    payload = dict(operation="PROFILE_CREATE", author_ref=AUTHOR, reviewed_at=(T0 + 4 * HOUR).isoformat(),
                   horizon_note=MARKER, liquidity_note="", risk_context_note="", review_lookahead_days=14,
                   excluded_issuer_ids=[ISSUER2], exclusion_reason_note="personal constraint")
    return {**payload, **over}


@pytest.fixture
def roots(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    p10 = tmp_path / "p10_private_root"
    p10.mkdir()
    p9 = build_p9(tmp_path / "p9_private_root")
    return dict(p10=p10, p9=p9["root"], world=p9, tmp=tmp_path)


def test_a_a_init_fresh_existing_partial_and_refused_layouts(roots) -> None:
    p10 = roots["p10"]
    assert run("init", "--p10-root", str(p10))[:2] == (0, {"command": "init", "status": "INITIALIZED"})
    before = tree(p10)
    assert run("init", "--p10-root", str(p10))[1]["status"] == "ALREADY_INITIALIZED" and tree(p10) == before
    (p10 / DIR / store_io.ATTENTION_FILENAME).unlink()
    partial = tree(p10)
    code, payload, _ = run("init", "--p10-root", str(p10))
    assert (code, payload["code"]) == (2, "PARTIAL_LAYOUT") and tree(p10) == partial   # 横に作らない
    with pytest.raises(InitRefusal) as exc:
        init_personal_root(p10)
    assert exc.value.code == "PARTIAL_LAYOUT"
    absent = roots["tmp"] / "absent"
    assert run("init", "--p10-root", str(absent))[1]["code"] == "INIT_REFUSED:STORE_MISSING:P10_ROOT_MISSING"
    assert not absent.exists()
    assert run("init", "--p10-root", "relative/root")[1]["code"] == "INIT_REFUSED:ROOT_REJECTED:ROOT_NOT_ABSOLUTE"
    (p10 / DIR / store_io.ATTENTION_FILENAME).write_bytes(b"{\n")
    assert run("init", "--p10-root", str(p10))[1]["code"] == "INIT_REFUSED:STORE_CORRUPTION:MALFORMED_JSON"
    fresh = roots["tmp"] / "fresh"
    fresh.mkdir()
    (fresh / DIR).mkdir()                                                            # 空の directory は初期化してよい
    assert init_personal_root(fresh) is InitStatus.INITIALIZED


def test_a_b_dry_run_apply_receipts_hold_no_ids_unless_private(roots) -> None:
    p10, tmp = roots["p10"], roots["tmp"]
    run("init", "--p10-root", str(p10))
    path = decision_file(tmp, "create.json", profile_payload())
    before = tree(p10)
    code, payload, line = run("dry-run", "--p10-root", str(p10), "--decision", path)
    assert (code, payload) == (0, {"command": "dry-run", "operation": "PROFILE_CREATE", "status": "VALID",
                                   "refusal": ""}) and tree(p10) == before
    code, payload, line = run("apply", "--p10-root", str(p10), "--decision", path)
    assert (code, payload) == (0, {"command": "apply", "operation": "PROFILE_CREATE", "status": "APPENDED"})
    for leak in ("p10prf_", "p10prv_", "p8iss_", MARKER, "human:", "personal constraint"):
        assert leak not in line, leak
    code, payload, _ = run("apply", "--p10-root", str(p10), "--decision", path, "--private")
    assert payload["status"] == "REUSED" and payload["root_id"].startswith("p10prf_")
    second = decision_file(tmp, "second.json", profile_payload(reviewed_at=(T0 + 5 * HOUR).isoformat()))
    code, payload, line = run("apply", "--p10-root", str(p10), "--decision", second)
    assert (code, payload["code"]) == (2, "AUTHORITY_WORLD_INVALID:MULTIPLE_ACTIVE_PROFILES")
    assert run("dry-run", "--p10-root", str(p10), "--decision", second)[1]["status"] == "WOULD_BE_REJECTED"


def test_a_c_decision_files_are_local_exact_schema_and_utf8_only(roots) -> None:
    p10, tmp = roots["p10"], roots["tmp"]
    run("init", "--p10-root", str(p10))
    before = tree(p10)
    surrogate = tmp / "surrogate.json"
    surrogate.write_bytes(json.dumps(profile_payload(horizon_note="\ud800")).encode("ascii"))   # JSON の \ud800
    attention = dict(operation="ATTENTION_CREATE", target_kind="P9_WATCH_ENTRY",
                     target_root_id=roots["world"]["w1"].watch_entry_id,
                     observed_p9_revision_id=roots["world"]["w1b"].revision_id, state="NORMAL", author_ref=AUTHOR,
                     reviewed_at=(T0 + 4 * HOUR).isoformat())
    not_json = tmp / "not.json"
    not_json.write_bytes(b"\xff{")
    cases = ((str(surrogate), "INPUT_REJECTED:UNENCODABLE_TEXT"),
             (decision_file(tmp, "extra.json", {**profile_payload(), "risk_score": 1}), "INPUT_REJECTED:UNKNOWN_FIELDS"),
             (decision_file(tmp, "missing.json", {k: v for k, v in profile_payload().items() if k != "author_ref"}),
              "INPUT_REJECTED:MISSING_FIELDS"),
             (decision_file(tmp, "normal.json", attention), "INPUT_REJECTED:INVALID_ENUM"),
             (decision_file(tmp, "naive.json", profile_payload(reviewed_at="2026-07-01T09:00:00")),
              "INPUT_REJECTED:INSTANT_NOT_AWARE"),
             (decision_file(tmp, "correction.json", {**attention, "operation": "ATTENTION_CORRECTION"}),
              "INPUT_REJECTED:UNKNOWN_OPERATION"),
             (str(not_json), "INPUT_REJECTED:DECISION_NOT_JSON"),
             ("relative.json", "INPUT_REJECTED:DECISION_PATH_REJECTED"),
             (str(tmp / "a" / ".." / "create.json"), "INPUT_REJECTED:DECISION_PATH_REJECTED"),
             (str(tmp / "absent.json"), "INPUT_REJECTED:DECISION_FILE_MISSING"))
    for path, expected in cases:
        code, payload, line = run("apply", "--p10-root", str(p10), "--decision", path, "--p9-root", str(roots["p9"]))
        assert (code, payload["code"]) == (2, expected), (path, payload)
        assert "\\ud800" not in line and MARKER not in line
    assert tree(p10) == before


def test_a_d_review_and_summary_are_counts_only_by_default(roots) -> None:
    p10, tmp, w = roots["p10"], roots["tmp"], roots["world"]
    run("init", "--p10-root", str(p10))
    run("apply", "--p10-root", str(p10), "--decision", decision_file(tmp, "c.json", profile_payload()))
    focus = dict(operation="ATTENTION_CREATE", target_kind="P9_WATCH_ENTRY", target_root_id=w["w1"].watch_entry_id,
                 observed_p9_revision_id=w["w1b"].revision_id, state="FOCUS", author_ref=AUTHOR,
                 reviewed_at=(T0 + 4 * HOUR).isoformat())
    assert run("apply", "--p10-root", str(p10), "--p9-root", str(roots["p9"]), "--decision",
               decision_file(tmp, "f.json", focus))[1]["status"] == "APPENDED"
    args = ("--p10-root", str(p10), "--p9-root", str(roots["p9"]), "--at", (T0 + 5 * HOUR).isoformat(),
            "--as-of-date", "2026-09-25")
    code, summary, line = run("summary", *args)
    assert code == 0 and summary["counts"]["review_entry_count"] == 3 and summary["counts"]["live_focus_mark_count"] == 1
    assert summary["counts"]["excluded_by_profile_count"] == 1 and set(summary) == {"command", "counts"}
    code, review, review_line = run("review", *args)
    assert review == {"command": "review", "entries": 3, "groups": {"EXCLUDED_BY_PROFILE": 1, "REVIEW": 2},
                      "due_classes": {"UPCOMING": 3}}                                # 窓 14 日
    for text in (line, review_line):
        for leak in ("p9wat_", "p9ths_", "p8iss_", "p10", "human:", MARKER, "2026-10"):
            assert leak not in text, leak
    private = run("review", *args, "--private")[1]
    assert {e["p9_root_id"] for e in private["private_entries"]} >= {w["w1"].watch_entry_id}
    assert run("review", "--p10-root", str(p10), "--p9-root", str(roots["p9"]), "--at", "2026-07-01T09:00:00",
               "--as-of-date", "2026-09-25")[1]["code"] == "INPUT_REJECTED:INSTANT_NOT_AWARE"
    for missing in (("review", "--p10-root", str(p10), "--p9-root", str(roots["p9"]), "--as-of-date", "2026-09-25"),
                    ("summary", "--p9-root", str(roots["p9"]), "--at", "x", "--as-of-date", "y"),
                    ("init",)):
        with pytest.raises(SystemExit):                                               # 既定の root ・時計は無い
            main(list(missing), stdout=io.StringIO())


def test_a_e_module_entry_runs_without_credentials_or_network(roots) -> None:
    env = {k: v for k, v in os.environ.items() if k != "JQUANTS_API_KEY"}
    result = subprocess.run([sys.executable, "-m", "src.intelligence.personal_intelligence.local_cli", "init",
                             "--p10-root", str(roots["p10"])], cwd=REPO_ROOT, env=env, capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0 and json.loads(result.stdout) == {"command": "init", "status": "INITIALIZED"}
