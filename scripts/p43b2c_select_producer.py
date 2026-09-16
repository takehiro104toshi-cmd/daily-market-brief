#!/usr/bin/env python3
"""GitHub Actions 用（P4-3b2c）: **本番公開向け**の producer run / artifact 選定。

P4-3b2b の `p43b2b_select_run.py` は **validation 用**として凍結済みであり、
feature branch / baseline `a2a6222` / attempt 1 固定という**検証専用の定数**を持つ。
本番公開はそれを流用できないため、実証済みの**信頼原則だけ**を引き継ぎ、
**明示的な本番契約**として書き直したのが本 module である（定数の複写ではない）。

責務は 4 つだけ:

  1. 与えられた producer workflow の run を列挙する（新しい順は探索順序であって信頼ではない）
  2. 明示された契約で各候補を検証する（workflow 同一性 / branch / 成功 / event / attempt）
  3. head_sha が**明示された trust baseline** を含むかを compare API で確かめる
  4. その run の artifact metadata を 1 件だけ選び、機械可読に出力する

**やらないこと**: artifact の download / 公開内容の検証（凍結 P4-3b2a の責務）/
鮮度判定（`p43b2c_v2_gate.py` の責務）/ `/v2` の組み立て / リポジトリへの書き込み /
`src.intelligence` の import / git 書き込み。

mode は **production と preview で構造的に分かれる**。production は branch が `main`
であることと、**main 上の承認済み commit** である trust baseline が明示されていることの
両方を要求し、どちらも既定値を持たない。preview から production へ、あるいはその逆へ
**暗黙に落ちることはない**。`github.ref` から branch や baseline を推測しない。

標準ライブラリのみを使う。認証は環境変数から受け取り、**値は絶対に出力しない**。

読み取る環境変数:
  GITHUB_TOKEN        API 認証（必須。値は出力しない）
  GITHUB_REPOSITORY   "owner/repo"（--repository で上書き可）
  GITHUB_API_URL      API base（既定 https://api.github.com）
  GITHUB_OUTPUT       追記先（任意。無ければ marker のみ）

出力する result（`$GITHUB_OUTPUT` の `result`）:
  SELECTED             信頼できる artifact を 1 件選べた
  V2_UNAVAILABLE       適格な run / artifact が無い（safe-skip。legacy は publish する）
  V2_INTERNAL_ERROR    設定不備・API 異常（safe-skip。ただし警告を出す）

**期待された失敗では exit 0 する**（legacy 配信を落とさないため）。分類は必ず
`result` に出るので、呼び出し側は戻り値ではなく `result` で分岐する。
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

#: 本番の producer（workflow file 名で URL を固定し、応答の path でも再確認する）
DEFAULT_PRODUCER_WORKFLOW = "p43b1-morning-delivery-producer.yml"
#: producer が upload する artifact 名（完全一致）
DEFAULT_ARTIFACT_NAME = "morning-delivery-v2"
#: **本番公開で唯一許す branch。** feature branch の artifact を本番 Pages へ載せない。
PRODUCTION_BRANCH = "main"
#: P4-3b2b validation 専用の baseline。**本番 trust をこれに縛らない。**
VALIDATION_ONLY_BASELINE = "a2a6222"

MODES = ("production", "preview")
#: compare API が返してよい status（head が baseline を含む形）
TRUSTED_COMPARE_STATUS = ("identical", "ahead")
#: event allowlist の語彙。schedule は**将来**の producer cron 用に語彙だけ用意する
#: （本 beta では production scheduled producer を有効化しない＝渡さない）。
KNOWN_EVENTS = ("push", "workflow_dispatch", "schedule", "repository_dispatch")

#: attempt 方針。GitHub の artifact record は attempt を持たないため、
#: 既定は「attempt 1 のみ」。`verified-attempt` は attempt 開始時刻との前後関係で
#: 帰属を**実際に確かめられた場合だけ**通し、確かめられなければ fail closed する。
ATTEMPT_POLICIES = ("first-attempt-only", "verified-attempt")
DEFAULT_ATTEMPT_POLICY = "first-attempt-only"

MIN_ARTIFACT_BYTES = 1
MAX_ARTIFACT_BYTES = 1024 * 1024
DEFAULT_MAX_CANDIDATES = 20

RESULT_SELECTED = "SELECTED"
RESULT_UNAVAILABLE = "V2_UNAVAILABLE"
RESULT_INTERNAL_ERROR = "V2_INTERNAL_ERROR"


class SelectionRejected(RuntimeError):
    """信頼契約を満たさない（safe-skip の V2_UNAVAILABLE になる）。"""


class ConfigurationInvalid(RuntimeError):
    """mode / branch / baseline の指定が本番契約を満たさない（fail closed）。"""


# ---------------------------------------------------------------- contract

class ProducerContract:
    """選定に使う**明示的な**契約（既定値で本番を成立させない）。"""

    def __init__(self, *, mode: str, workflow_file: str, branch: str, baseline: str,
                 eligible_events: Sequence[str], artifact_name: str,
                 attempt_policy: str) -> None:
        if mode not in MODES:
            raise ConfigurationInvalid(f"mode must be one of {list(MODES)}: {mode!r}")
        if not workflow_file.endswith(".yml"):
            raise ConfigurationInvalid(f"producer workflow must be a .yml file name: "
                                       f"{workflow_file!r}")
        if not branch:
            raise ConfigurationInvalid("producer branch must be given explicitly")
        if not baseline:
            raise ConfigurationInvalid("trust baseline must be given explicitly")
        if not eligible_events:
            raise ConfigurationInvalid("eligible events must be given explicitly")
        unknown = [e for e in eligible_events if e not in KNOWN_EVENTS]
        if unknown:
            raise ConfigurationInvalid(f"unknown producer events: {unknown}")
        if attempt_policy not in ATTEMPT_POLICIES:
            raise ConfigurationInvalid(
                f"attempt policy must be one of {list(ATTEMPT_POLICIES)}: {attempt_policy!r}")
        if mode == "production":
            if branch != PRODUCTION_BRANCH:
                raise ConfigurationInvalid(
                    f"production publication requires branch {PRODUCTION_BRANCH!r}, "
                    f"got {branch!r}")
            if baseline == VALIDATION_ONLY_BASELINE:
                raise ConfigurationInvalid(
                    "production trust must not be bound to the P4-3b2b validation baseline; "
                    "supply an approved producer commit on main")
        self.mode = mode
        self.workflow_file = workflow_file
        self.workflow_path = f".github/workflows/{workflow_file}"
        self.branch = branch
        self.baseline = baseline
        self.eligible_events: Tuple[str, ...] = tuple(eligible_events)
        self.artifact_name = artifact_name
        self.attempt_policy = attempt_policy

    def as_dict(self) -> Dict[str, object]:
        return {"mode": self.mode, "producer_workflow": self.workflow_path,
                "producer_branch": self.branch, "trust_baseline": self.baseline,
                "eligible_events": list(self.eligible_events),
                "artifact_name": self.artifact_name,
                "attempt_policy": self.attempt_policy}


# ---------------------------------------------------------------- transport

def _request(api_base: str, path: str, *, auth: str,
             query: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> Dict:
    url = api_base.rstrip("/") + path
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "p43b2c-select-producer")
    request.add_header("Authorization", f"Bearer {auth}")     # 値は決して出力しない
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------- eligibility

def run_is_eligible(run: Dict, contract: ProducerContract) -> Tuple[bool, str]:
    """1 件の run が契約を満たすか（満たさない理由を必ず返す）。"""
    if run.get("path") != contract.workflow_path:
        return False, "not the producer workflow"
    if run.get("head_branch") != contract.branch:
        return False, f"not the {contract.branch} branch"
    if run.get("status") != "completed":
        return False, "not completed"
    if run.get("conclusion") != "success":
        return False, "did not succeed"
    if run.get("event") not in contract.eligible_events:
        return False, "event is not eligible"
    head_sha = run.get("head_sha")
    if not isinstance(head_sha, str) or len(head_sha) < 7:
        return False, "head_sha is unusable"
    attempt = run.get("run_attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        return False, "run_attempt is unusable"
    if contract.attempt_policy == "first-attempt-only" and attempt != 1:
        return False, "run_attempt is not 1 under first-attempt-only"
    return True, ""


def attempt_started_at(api_base: str, repository: str, run_id: int, attempt: int, *,
                       auth: str) -> str:
    """その attempt の開始時刻を取る。取れなければ fail closed。"""
    payload = _request(
        api_base, f"/repos/{repository}/actions/runs/{run_id}/attempts/{attempt}", auth=auth)
    started = payload.get("run_started_at")
    if not isinstance(started, str) or not started:
        raise SelectionRejected(
            f"attempt {attempt} carries no usable run_started_at; rerun attribution "
            f"cannot be established")
    return started


def artifact_belongs_to_attempt(artifact: Dict, started_at: str) -> bool:
    """artifact がその attempt で作られたと**実際に言えるか**（推測しない）。

    artifact record は attempt を持たないため、唯一使える手掛かりは
    `created_at >= attempt.run_started_at` という時系列である。どちらかが
    読めなければ帰属は確立できない。
    """
    created = artifact.get("created_at")
    if not isinstance(created, str) or not created:
        return False
    return created >= started_at


# ---------------------------------------------------------------- trust

def trust_status(api_base: str, repository: str, head_sha: str, *, auth: str,
                 baseline: str) -> str:
    """head_sha が baseline を含むことを compare API で確かめる。

    承認済み `status` 語彙であること **かつ** `behind_by == 0` の**両方**を要求する。
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
        raise SelectionRejected(f"producer head_sha is behind {baseline} by {behind} commits")
    return status


# ---------------------------------------------------------------- artifact

def select_artifact(api_base: str, repository: str, run_id: int, *, auth: str,
                    contract: ProducerContract) -> Dict[str, object]:
    """その run の artifact を**完全一致名でちょうど 1 件**選ぶ。"""
    payload = _request(api_base, f"/repos/{repository}/actions/runs/{run_id}/artifacts",
                       auth=auth, query={"per_page": "100"})
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise SelectionRejected("artifact listing is unusable")
    matching = [a for a in artifacts
                if isinstance(a, dict) and a.get("name") == contract.artifact_name]
    if len(matching) != 1:
        raise SelectionRejected(
            f"expected exactly one artifact named {contract.artifact_name}, "
            f"found {len(matching)}")
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
    created = artifact.get("created_at")
    if not isinstance(created, str) or not created:
        raise SelectionRejected("artifact carries no usable created_at")
    return artifact


# ---------------------------------------------------------------- selection

def select(api_base: str, repository: str, *, auth: str, contract: ProducerContract,
           max_candidates: int = DEFAULT_MAX_CANDIDATES) -> Dict[str, object]:
    """契約を満たす run と artifact を 1 組だけ選ぶ。"""
    payload = _request(
        api_base, f"/repos/{repository}/actions/workflows/{contract.workflow_file}/runs",
        auth=auth,
        query={"branch": contract.branch, "status": "success",
               "per_page": str(max_candidates)})
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise SelectionRejected("producer run listing is unusable")

    examined: List[str] = []
    for run in runs[:max_candidates]:
        if not isinstance(run, dict):
            continue
        ok, reason = run_is_eligible(run, contract)
        if not ok:
            examined.append(f"{run.get('id')}:{reason}")
            continue
        status = trust_status(api_base, repository, str(run["head_sha"]),
                              auth=auth, baseline=contract.baseline)
        artifact = select_artifact(api_base, repository, int(run["id"]),
                                   auth=auth, contract=contract)
        attempt = int(run["run_attempt"])
        attribution = "first-attempt"
        if attempt != 1:
            started = attempt_started_at(api_base, repository, int(run["id"]), attempt,
                                         auth=auth)
            if not artifact_belongs_to_attempt(artifact, started):
                raise SelectionRejected(
                    f"artifact cannot be attributed to attempt {attempt}; refusing to guess")
            attribution = "verified-attempt"
        return {"run": run, "artifact": artifact, "trust_status": status,
                "attempt_attribution": attribution,
                "candidates_examined": len(examined) + 1}

    raise SelectionRejected(
        f"no eligible producer run among {len(runs)} candidates: {examined}")


# ---------------------------------------------------------------- CLI

def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P43B2C_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _github_output(values: Dict[str, object]) -> None:
    path = os.environ.get("GITHUB_OUTPUT", "")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as stream:        # 単純なスカラーのみ書く
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def _finish(result: str, reason_code: str, reason: str) -> int:
    """期待された失敗を typed result として返す（exit 0 で legacy 配信を守る）。"""
    _emit("SELECTION_RESULT", {"result": result, "reason_code": reason_code,
                               "reason": reason})
    _github_output({"result": result, "reason_code": reason_code})
    return 0


def _parse_events(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P4-3b2c: 本番公開向けの producer run / artifact 選定")
    # 必須項目も argparse では required にしない（分類を自分で制御して exit 0 を保つ）
    parser.add_argument("--mode", default="")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--producer-workflow", default=DEFAULT_PRODUCER_WORKFLOW)
    parser.add_argument("--producer-branch", default="")
    parser.add_argument("--trust-baseline", default="")
    parser.add_argument("--eligible-events", default="")
    parser.add_argument("--artifact-name", default=DEFAULT_ARTIFACT_NAME)
    parser.add_argument("--attempt-policy", default=DEFAULT_ATTEMPT_POLICY)
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    args = parser.parse_args(argv)

    try:
        contract = ProducerContract(
            mode=args.mode, workflow_file=args.producer_workflow,
            branch=args.producer_branch, baseline=args.trust_baseline,
            eligible_events=_parse_events(args.eligible_events),
            artifact_name=args.artifact_name, attempt_policy=args.attempt_policy)
    except ConfigurationInvalid as exc:
        return _finish(RESULT_INTERNAL_ERROR, "CONFIGURATION_INVALID", str(exc))

    _emit("HEAD", dict(contract.as_dict(), selector="scripts/p43b2c_select_producer.py",
                       downloads_artifact=False, validates_delivery_content=False,
                       evaluates_freshness=False, writes_repository=False))

    auth = os.environ.get("GITHUB_TOKEN", "")
    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    if not auth:
        return _finish(RESULT_INTERNAL_ERROR, "CREDENTIAL_MISSING",
                       "GitHub API credential is not configured")
    if not args.repository or "/" not in args.repository:
        return _finish(RESULT_INTERNAL_ERROR, "REPOSITORY_INVALID",
                       "repository must be given as owner/repo")

    try:
        chosen = select(api_base, args.repository, auth=auth, contract=contract,
                        max_candidates=args.max_candidates)
    except SelectionRejected as exc:
        return _finish(RESULT_UNAVAILABLE, "NO_TRUSTED_ARTIFACT", str(exc))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return _finish(RESULT_INTERNAL_ERROR, "API_UNAVAILABLE",
                       f"producer lookup failed: {exc.__class__.__name__}")

    run = chosen["run"]
    artifact = chosen["artifact"]
    _emit("SELECTION", {
        "mode": contract.mode,
        "selected_run_id": run["id"], "run_number": run.get("run_number"),
        "run_attempt": run.get("run_attempt"), "event": run.get("event"),
        "head_branch": run.get("head_branch"), "head_sha": run.get("head_sha"),
        "workflow_path": run.get("path"), "conclusion": run.get("conclusion"),
        "status": run.get("status"), "trust_baseline": contract.baseline,
        "trust_status": chosen["trust_status"],
        "attempt_policy": contract.attempt_policy,
        "attempt_attribution": chosen["attempt_attribution"],
        "candidates_examined": chosen["candidates_examined"],
    })
    _emit("ARTIFACT", {
        "artifact_id": artifact["id"], "artifact_name": artifact.get("name"),
        "size_in_bytes": artifact.get("size_in_bytes"),
        "expired": artifact.get("expired"), "created_at": artifact.get("created_at"),
        "digest": artifact.get("digest", ""),
    })
    _github_output({
        "result": RESULT_SELECTED, "reason_code": "OK",
        "selected_run_id": run["id"], "run_attempt": run.get("run_attempt"),
        "head_sha": run.get("head_sha"), "head_branch": run.get("head_branch"),
        "artifact_id": artifact["id"], "artifact_name": artifact.get("name"),
        "artifact_size": artifact.get("size_in_bytes"),
        "artifact_created_at": artifact.get("created_at"),
        "trust_status": chosen["trust_status"],
    })
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
