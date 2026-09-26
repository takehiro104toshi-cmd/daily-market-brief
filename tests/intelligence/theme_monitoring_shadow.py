"""P6-B6E — monitoring の READ-ONLY shadow validation harness（1 command）。

既存 data_root に対し `run_monitoring()` を **同一 cutoff で 2 回** 実行し、

1. 実行前後の file inventory（相対 path → sha256 / size）を比較して **zero-write** を証明する
2. 2 回の run が完全に一致する（run_id / report bytes / finding 集合 / finding bytes /
   unevaluated / diagnostics / input digests）ことを確認する
3. 件数・安定 id・diagnostic code・version・hash だけの machine-readable summary を出す

**何も書かない。** review を append しない。finding を保存しない。scheduler も notification も持たない。
本文・引用・credential・machine path を summary へ出さない。

**production entry point ではない。** `scripts/` にも workflow にも置かない（Phase 6 は production へ接続しない）。

使い方（1 command）:

    python -m tests.intelligence.theme_monitoring_shadow --data-root <DATA_ROOT> --cutoff 2026-09-30T00:00:00+00:00

任意:

    --knowledge-root knowledge      versioned knowledge の root（既定: repo の knowledge/）
    --ruleset-version 0.1.0         monitoring ruleset の version（既定: 0.1.0）
    --stale-after-days 90           B2 freshness policy（既定: 90）
    --root-id <id>                  監視 scope（省略時は Foundation の roots を read-only で列挙）
    --second-cutoff <iso>           PIT 観測用の追加 cutoff（省略可）
    --out <path>                    summary JSON の出力先（省略時は stdout）

exit code: 0 = zero-write かつ replay 一致 / 1 = 差分あり / 2 = 実行不能（理由は summary に入る）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.intelligence.theme_intelligence.lifecycle_model import LifecyclePolicy          # noqa: E402
from src.intelligence.theme_intelligence.monitoring_model import canonical_monitoring_line  # noqa: E402
from src.intelligence.theme_intelligence.monitoring_runner import run_monitoring         # noqa: E402

HARNESS_VERSION = "p6b6e_monitoring_shadow:0.1.0"
SUMMARY_IS_COUNTS_ONLY = "the shadow summary carries counts, stable ids, codes, versions and hashes only"
EXIT_OK, EXIT_DIFF, EXIT_UNAVAILABLE = 0, 1, 2


def inventory(root: Path) -> dict:
    """data_root 配下の全 file の (相対 path -> sha256:size)。mtime は使わない。"""
    items = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            items[str(path.relative_to(root))] = f"{hashlib.sha256(raw).hexdigest()}:{len(raw)}"
    return items


def inventory_delta(before: dict, after: dict) -> dict:
    return {"new_files": sorted(set(after) - set(before)),
            "deleted_files": sorted(set(before) - set(after)),
            "modified_files": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def discover_root_ids(data_root: Path) -> list:
    """Foundation の roots journal を read-only で開いて root id を列挙する（書かない）。"""
    from src.intelligence.themes.store import ThemeStore
    store = ThemeStore.open(data_root, read_only=True)
    return sorted({json.loads(line)["root_id"] for line in store.canonical_lines("roots")})


def describe(result) -> dict:
    """descriptive metrics のみ。score / rank / 予測 / 本文を含めない。"""
    by_condition, by_category, by_diagnostic, by_review = {}, {}, {}, {}
    for finding in result.findings:
        by_condition[finding.condition_id] = by_condition.get(finding.condition_id, 0) + 1
        by_category[finding.category.value] = by_category.get(finding.category.value, 0) + 1
    for code in result.report.diagnostics:
        by_diagnostic[code] = by_diagnostic.get(code, 0) + 1
    for review in result.reviews:
        by_review[review.resolution.status.value] = by_review.get(review.resolution.status.value, 0) + 1
    unusable = sum(1 for finding in result.findings if finding.condition_id == "AUTHORITY_STATE_UNUSABLE")
    return {
        "run_id": result.report.run_id,
        "status": result.report.status.value,
        "cutoff": result.report.cutoff.isoformat(),
        "ruleset_version": result.report.ruleset_version,
        "knowledge_versions": [list(pair) for pair in result.report.knowledge_versions],
        "input_digests": [list(pair) for pair in result.report.input_digests],
        "finding_count": len(result.findings),
        "finding_ids": sorted(finding.finding_id for finding in result.findings),
        "finding_count_by_condition": dict(sorted(by_condition.items())),
        "finding_count_by_category": dict(sorted(by_category.items())),
        "subject_count": len({finding.subject_ref for finding in result.findings}),
        "unevaluated_conditions": list(result.report.unevaluated_conditions),
        "report_diagnostics": dict(sorted(by_diagnostic.items())),
        "runner_diagnostics": list(result.diagnostics),
        "authority_unusable_findings": unusable,
        "review_lookup_status": result.review_status.value,
        "review_chain_status_counts": dict(sorted(by_review.items())),
        "observation_channels_not_supplied": [code.split(":", 1)[1] for code in result.diagnostics
                                              if code.startswith("OBSERVATION_NOT_SUPPLIED:")],
        "report_canonical_sha256": hashlib.sha256(
            canonical_monitoring_line(result.report).encode("utf-8")).hexdigest(),
        "findings_canonical_sha256": hashlib.sha256(
            "".join(sorted(canonical_monitoring_line(f) for f in result.findings)).encode("utf-8")).hexdigest(),
    }


def replay_delta(first: dict, second: dict) -> list:
    return sorted(key for key in first if first[key] != second[key])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="P6-B6E read-only monitoring shadow validation")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--cutoff", required=True, help="aware ISO-8601（現在時刻は使わない）")
    parser.add_argument("--second-cutoff", default="")
    parser.add_argument("--knowledge-root", default=str(REPO_ROOT / "knowledge"))
    parser.add_argument("--ruleset-version", default="0.1.0")
    parser.add_argument("--stale-after-days", type=int, default=90)
    parser.add_argument("--root-id", action="append", default=[])
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    summary = {"harness_version": HARNESS_VERSION, "wrote_nothing": None, "replay_identical": None}
    data_root = Path(args.data_root)
    if not data_root.is_dir():
        summary["error"] = "DATA_ROOT_NOT_FOUND"
        return _emit(summary, args.out, EXIT_UNAVAILABLE)
    summary["data_root_name"] = data_root.name                      # 絶対 path は出さない
    cutoff = datetime.fromisoformat(args.cutoff)
    if cutoff.tzinfo is None:
        summary["error"] = "CUTOFF_MUST_BE_AWARE"
        return _emit(summary, args.out, EXIT_UNAVAILABLE)

    try:
        root_ids = args.root_id or discover_root_ids(data_root)
    except Exception as exc:                                        # store が読めない＝shadow 不能
        summary["error"] = f"ROOT_DISCOVERY_FAILED:{getattr(exc, 'code', type(exc).__name__)}"
        return _emit(summary, args.out, EXIT_UNAVAILABLE)
    summary["scope_root_count"] = len(root_ids)

    before = inventory(data_root)
    summary["file_count_before"] = len(before)
    policy = LifecyclePolicy(stale_after_days=args.stale_after_days)
    runs = []
    try:
        for _ in range(2):
            runs.append(run_monitoring(data_root=data_root, cutoff=cutoff, recorded_at=cutoff, root_ids=root_ids,
                                       lifecycle_policy=policy, knowledge_root=Path(args.knowledge_root),
                                       ruleset_version=args.ruleset_version))
        if args.second_cutoff:
            other = datetime.fromisoformat(args.second_cutoff)
            summary["second_cutoff_run"] = describe(run_monitoring(
                data_root=data_root, cutoff=other, recorded_at=other, root_ids=root_ids, lifecycle_policy=policy,
                knowledge_root=Path(args.knowledge_root), ruleset_version=args.ruleset_version))
    except Exception as exc:
        summary["error"] = f"RUN_FAILED:{getattr(exc, 'code', type(exc).__name__)}"
        summary["inventory_delta"] = inventory_delta(before, inventory(data_root))
        summary["wrote_nothing"] = not any(summary["inventory_delta"].values())
        return _emit(summary, args.out, EXIT_UNAVAILABLE)

    after = inventory(data_root)
    delta = inventory_delta(before, after)
    first, second = describe(runs[0]), describe(runs[1])
    summary.update({"file_count_after": len(after), "inventory_delta": delta,
                    "wrote_nothing": not any(delta.values()),
                    "replay_identical": replay_delta(first, second) == [],
                    "replay_differences": replay_delta(first, second), "run": first})
    return _emit(summary, args.out, EXIT_OK if summary["wrote_nothing"] and summary["replay_identical"] else EXIT_DIFF)


def _emit(summary: dict, out: str, code: int) -> int:
    text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
