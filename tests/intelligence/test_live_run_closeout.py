"""live run待機を必ず終端させるための構造ガード（docs/databank/
LIVE_RUN_CLOSEOUT_PROTOCOL.md）。

Phase 3-Bのcloseoutで、完了待機shellが終わらない事象が起きた。原因は
クライアント側の完了判定だったが、**待機上限を計算できること**自体が
repository側の前提条件なので、全workflowが `timeout-minutes` を宣言している
ことと、protocolドキュメントの表が実ファイルと一致していることを固定する。

ネットワークは使わない（ワークフローYAMLとドキュメントの静的検査のみ）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_DIR = Path(".github/workflows")
PROTOCOL_DOC = Path("docs/databank/LIVE_RUN_CLOSEOUT_PROTOCOL.md")

#: Automated Closeoutが完了を待機するworkflow（本番 daily-market-brief.yml は
#: 対象外——CLAUDE.mdルール15により本番workflowは依頼が無い限り変更しない）
CLOSEOUT_WORKFLOWS = (
    "p1c-live-validation.yml",
    "p2a-e2e-pilot.yml",
    "p2d-market-pilot.yml",
    "p2h-jquants-light.yml",
)

#: protocolの表から `| <workflow>.yml | <分> |` を読む
_TABLE_ROW = re.compile(r"^\|\s*`?([a-z0-9-]+\.yml)`?\s*\|\s*(\d+)\s*\|")


def workflow_files():
    return [WORKFLOW_DIR / name for name in CLOSEOUT_WORKFLOWS]


def documented_timeouts():
    rows = {}
    for line in PROTOCOL_DOC.read_text(encoding="utf-8").splitlines():
        match = _TABLE_ROW.match(line.strip())
        if match:
            rows[match.group(1)] = int(match.group(2))
    return rows


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_every_workflow_job_declares_a_timeout(path):
    """待機上限が計算できない（無期限になり得る）jobを作らせない。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    jobs = data.get("jobs") or {}
    assert jobs, f"{path.name} has no jobs"
    for name, job in jobs.items():
        timeout = job.get("timeout-minutes")
        assert isinstance(timeout, int) and timeout > 0, \
            f"{path.name}:{name} must declare a positive timeout-minutes"


def test_protocol_documents_every_workflow_timeout():
    """ドキュメントの待機上限表が実ファイルと一致していること。"""
    documented = documented_timeouts()
    assert set(documented) == set(CLOSEOUT_WORKFLOWS)
    for path in workflow_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (data.get("jobs") or {}).values():
            assert documented.get(path.name) == job["timeout-minutes"], (
                f"{path.name}: doc says {documented.get(path.name)}, "
                f"workflow says {job['timeout-minutes']}")


def test_protocol_forbids_unbounded_waiting():
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    assert "無期限" in text and "bounded polling" in text
    # 「応答が取れない＝未完了」と誤判定しないことを明記しているか
    assert "未完了" in text


def test_protocol_lists_the_phase3b_markers():
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    for marker in ("::P3B_", "::P3A_", "::P2H_"):
        assert marker in text, marker
