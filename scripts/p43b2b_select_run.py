#!/usr/bin/env python3
"""GitHub Actions 用（P4-3b2b）: 信頼できる producer run と artifact を 1 つだけ選ぶ。

**CI 配管専用**であり、配信物の内容には一切関与しない。責務は次の 4 つだけ:

  1. p43b1 producer の run を列挙する（新しい順は**探索順序であって信頼ではない**）
  2. 各候補を厳密条件で検証する（workflow 同一性 / branch / 成功 / event / attempt）
  3. head_sha が信頼 baseline を含むかを compare API で確かめる
  4. その run の artifact metadata を 1 件だけ選び、機械可読に出力する

**やらないこと**: artifact の download / MorningDelivery 内容の検証 / v2 の組み立て /
リポジトリへの書き込み / `src.intelligence` の import / git 書き込み。
内容の権威は凍結済み P4-3b2a（`src.intelligence.reports.pages_parallel`）のままである。

標準ライブラリのみを使う。認証は環境変数から受け取り、**値は絶対に出力しない**。

読み取る環境変数:
  GITHUB_TOKEN        API 認証（必須。値は出力しない）
  GITHUB_REPOSITORY   "owner/repo"（GitHub Actions が設定。--repository で上書き可）
  GITHUB_API_URL      API base（既定 https://api.github.com）
  GITHUB_OUTPUT       追記先（任意。無ければ marker のみ）

出力:
  ::P43B2B_SELECTION::  選定した run の証跡
  ::P43B2B_ARTIFACT::   選定した artifact の metadata
  GITHUB_OUTPUT         selected_run_id / run_number / run_attempt / event /
                        head_sha / head_branch / artifact_id / artifact_name /
                        artifact_size / artifact_created_at / artifact_digest /
                        trust_status / candidates_examined

適格な run / artifact が無ければ**非ゼロ終了**する（検証 proof なので fail closed）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

#: 対象 producer（workflow file 名で URL を固定し、応答の path でも再確認する）
PRODUCER_WORKFLOW_FILE = "p43b1-morning-delivery-producer.yml"
PRODUCER_WORKFLOW_PATH = f".github/workflows/{PRODUCER_WORKFLOW_FILE}"
PRODUCER_BRANCH = "claude/investment-intelligence-phase0-rvdplu"

#: producer が upload する artifact 名（完全一致）
ARTIFACT_NAME = "morning-delivery-v2"

#: 信頼 baseline（P4-3b1 reachability。これ自体が b1 実装 feb960d を含む）
TRUST_BASELINE = "a2a6222"

#: 適格な event（明示 allowlist。schedule など他は拒否）
ELIGIBLE_EVENTS: Tuple[str, ...] = ("push", "workflow_dispatch")

#: **本 validation proof 限定**の制約。artifact の attempt 帰属を API から確立できないため
#: attempt 1 のみを採る。恒久的な本番方針ではない（P4-3b2c で別途見直す）。
REQUIRED_RUN_ATTEMPT = 1

#: compare API（base=baseline, head=候補）で信頼とみなす status。
#: **この語彙は初回 real run で実応答により確認する。**想定外の値は fail closed。
#: 文字列語彙に依存しきらないよう `behind_by == 0` も併せて必須にする。
TRUSTED_COMPARE_STATUS: Tuple[str, ...] = ("identical", "ahead")

MIN_ARTIFACT_BYTES = 1
MAX_ARTIFACT_BYTES = 1024 * 1024          # 実測 2,958 bytes に対する十分な上限
DEFAULT_MAX_CANDIDATES = 20


class SelectionRejected(RuntimeError):
    """適格な run / artifact が無い（fail closed）。理由に秘匿値を含めない。"""


def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P43B2B_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _request(api_base: str, path: str, *, auth: str, query: Optional[Dict[str, str]] = None,
             timeout: float = 30.0) -> Dict[str, object]:
    """GitHub API の GET。失敗理由に認証値を含めない。"""
    url = f"{api_base.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("Authorization", f"Bearer {auth}")
    request.add_header("User-Agent", "p43b2b-select-run")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:                      # 応答本文は出さない
        raise SelectionRejected(f"GitHub API returned HTTP {exc.code} for {path}") from None
    except urllib.error.URLError as exc:
        raise SelectionRejected(f"GitHub API is unreachable for {path}: "
                                f"{exc.__class__.__name__}") from None
    except (ValueError, OSError) as exc:
        raise SelectionRejected(f"GitHub API response is unusable for {path}: "
                                f"{exc.__class__.__name__}") from None


def run_is_eligible(run: Dict[str, object]) -> Tuple[bool, str]:
    """trust 以外の構造条件。探索順序ではなくこの判定が適格性を決める。"""
    if run.get("path") != PRODUCER_WORKFLOW_PATH:
        return False, f"workflow path is not the producer: {run.get('path')!r}"
    if run.get("head_branch") != PRODUCER_BRANCH:
        return False, f"head_branch is not the validation branch: {run.get('head_branch')!r}"
    if run.get("status") != "completed":
        return False, f"run is not completed: {run.get('status')!r}"
    if run.get("conclusion") != "success":
        return False, f"run did not succeed: {run.get('conclusion')!r}"
    if run.get("event") not in ELIGIBLE_EVENTS:
        return False, f"event is not eligible: {run.get('event')!r}"
    if run.get("run_attempt") != REQUIRED_RUN_ATTEMPT:
        return False, (f"run_attempt is not {REQUIRED_RUN_ATTEMPT} "
                       f"(artifact-attempt provenance is not establishable): "
                       f"{run.get('run_attempt')!r}")
    head_sha = run.get("head_sha")
    if not isinstance(head_sha, str) or len(head_sha) < 7:
        return False, f"head_sha is unusable: {head_sha!r}"
    return True, ""


def trust_status(api_base: str, repository: str, head_sha: str, *, auth: str,
                 baseline: str = TRUST_BASELINE) -> str:
    """head_sha が baseline を含むかを compare API で確かめる。

    `base...head` の `status` が承認済み語彙であること **かつ** `behind_by == 0`
    （head が baseline に対して遅れていない）であることの**両方**を要求する。
    どちらかでも確かめられなければ fail closed（推測しない）。
    """
    payload = _request(api_base, f"/repos/{repository}/compare/{baseline}...{head_sha}",
                       auth=auth)
    status = payload.get("status")
    behind = payload.get("behind_by")
    if not isinstance(status, str):
        raise SelectionRejected("compare response carries no usable status")
    if not isinstance(behind, int) or isinstance(behind, bool):
        raise SelectionRejected("compare response carries no usable behind_by")
    if status not in TRUSTED_COMPARE_STATUS:
        raise SelectionRejected(
            f"producer head_sha is not trusted under {baseline}: compare status {status!r}")
    if behind != 0:
        raise SelectionRejected(
            f"producer head_sha is behind {baseline} by {behind} commits")
    return status


def select_artifact(api_base: str, repository: str, run_id: int, *,
                    auth: str) -> Dict[str, object]:
    """その run の artifact を**完全一致名でちょうど 1 件**選ぶ。"""
    payload = _request(api_base, f"/repos/{repository}/actions/runs/{run_id}/artifacts",
                       auth=auth, query={"per_page": "100"})
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise SelectionRejected("artifact listing is unusable")
    matching = [a for a in artifacts
                if isinstance(a, dict) and a.get("name") == ARTIFACT_NAME]
    if len(matching) != 1:
        raise SelectionRejected(
            f"expected exactly one artifact named {ARTIFACT_NAME}, found {len(matching)}")
    artifact = matching[0]
    if artifact.get("expired") is not False:
        raise SelectionRejected(f"artifact is expired: {artifact.get('expired')!r}")
    size = artifact.get("size_in_bytes")
    if not isinstance(size, int) or isinstance(size, bool):
        raise SelectionRejected(f"artifact size is unusable: {size!r}")
    if size < MIN_ARTIFACT_BYTES:
        raise SelectionRejected("artifact is empty")
    if size > MAX_ARTIFACT_BYTES:
        raise SelectionRejected(f"artifact is implausibly large: {size} bytes")
    artifact_id = artifact.get("id")
    if not isinstance(artifact_id, int) or isinstance(artifact_id, bool):
        raise SelectionRejected(f"artifact id is unusable: {artifact_id!r}")
    return artifact


def select(api_base: str, repository: str, *, auth: str,
           max_candidates: int = DEFAULT_MAX_CANDIDATES) -> Dict[str, object]:
    """適格な run と artifact を 1 組だけ選ぶ。見つからなければ SelectionRejected。"""
    payload = _request(
        api_base,
        f"/repos/{repository}/actions/workflows/{PRODUCER_WORKFLOW_FILE}/runs",
        auth=auth,
        query={"branch": PRODUCER_BRANCH, "status": "success",
               "per_page": str(max_candidates)})
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise SelectionRejected("producer run listing is unusable")

    examined: List[str] = []
    for run in runs[:max_candidates]:
        if not isinstance(run, dict):
            continue
        ok, reason = run_is_eligible(run)
        if not ok:
            examined.append(f"{run.get('id')}:{reason}")
            continue
        status = trust_status(api_base, repository, str(run["head_sha"]), auth=auth)
        artifact = select_artifact(api_base, repository, int(run["id"]), auth=auth)
        return {"run": run, "artifact": artifact, "trust_status": status,
                "candidates_examined": len(examined) + 1}

    raise SelectionRejected(
        f"no eligible producer run among {len(runs)} candidates: {examined}")


def _github_output(values: Dict[str, object]) -> None:
    path = os.environ.get("GITHUB_OUTPUT", "")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as stream:      # 単純なスカラーのみ書く
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P4-3b2b: 信頼できる producer run / artifact を 1 つ選ぶ")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""),
                        help='"owner/repo"（既定は GITHUB_REPOSITORY）')
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES,
                        help="新しい順に見る候補数の上限（探索順序は信頼ではない）")
    args = parser.parse_args(argv)

    auth = os.environ.get("GITHUB_TOKEN", "")
    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com")

    _emit("HEAD", {
        "selector": "scripts/p43b2b_select_run.py",
        "producer_workflow": PRODUCER_WORKFLOW_PATH,
        "producer_branch": PRODUCER_BRANCH,
        "artifact_name": ARTIFACT_NAME,
        "trust_baseline": TRUST_BASELINE,
        "eligible_events": list(ELIGIBLE_EVENTS),
        "required_run_attempt": REQUIRED_RUN_ATTEMPT,
        "downloads_artifact": False,
        "validates_delivery_content": False,
        "writes_repository": False,
    })
    if not auth:
        _emit("REJECTED", {"reason": "GitHub API credential is not configured"})
        return 1
    if not args.repository or "/" not in args.repository:
        _emit("REJECTED", {"reason": "repository must be given as owner/repo"})
        return 1

    try:
        chosen = select(api_base, args.repository, auth=auth,
                        max_candidates=args.max_candidates)
    except SelectionRejected as exc:
        _emit("REJECTED", {"reason": str(exc)})
        return 1

    run = chosen["run"]
    artifact = chosen["artifact"]
    _emit("SELECTION", {
        "selected_run_id": run["id"], "run_number": run.get("run_number"),
        "run_attempt": run.get("run_attempt"), "event": run.get("event"),
        "head_branch": run.get("head_branch"), "head_sha": run.get("head_sha"),
        "workflow_path": run.get("path"), "conclusion": run.get("conclusion"),
        "status": run.get("status"), "trust_baseline": TRUST_BASELINE,
        "trust_status": chosen["trust_status"],
        "candidates_examined": chosen["candidates_examined"],
    })
    _emit("ARTIFACT", {
        "artifact_id": artifact["id"], "artifact_name": artifact.get("name"),
        "size_in_bytes": artifact.get("size_in_bytes"),
        "expired": artifact.get("expired"),
        "created_at": artifact.get("created_at"),
        "digest": artifact.get("digest", ""),
    })
    _github_output({
        "selected_run_id": run["id"], "run_number": run.get("run_number"),
        "run_attempt": run.get("run_attempt"), "event": run.get("event"),
        "head_sha": run.get("head_sha"), "head_branch": run.get("head_branch"),
        "artifact_id": artifact["id"], "artifact_name": artifact.get("name"),
        "artifact_size": artifact.get("size_in_bytes"),
        "artifact_created_at": artifact.get("created_at"),
        "artifact_digest": artifact.get("digest", ""),
        "trust_status": chosen["trust_status"],
        "candidates_examined": chosen["candidates_examined"],
    })
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
