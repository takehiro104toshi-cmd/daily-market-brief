"""TOPIX NEUTRAL-BAND 実測 runner（Phase 5 Entry Contract A0.5R / 監督者決定 N-2 の材料）。

A0.7B-R2 で取得した **隔離 research dataset だけ**を入力に、TOPIX の実現
close-to-close 日次 return 分布を測り、候補 band ごとの UP / RANGE / DOWN 件数を
機械的に数える。**threshold は決めない。推奨も出さない。**

    <research-root>/acquisition.json                                  … 取得 metadata（権威）
    <research-root>/databank/market/normalized/observations.jsonl     … canonical 観測（権威）
      → raw TOPIX close（latest_revisions 適用・trading_date 昇順）
      → realized_return = close(t) / close(prev Tokyo session) - 1   （Decimal・丸めない）
      → 独立再計算 == 保存済み derived return_1d の検証
      → 分布統計 / band 表 / 年別表
      → ::P5_TOPIX_NEUTRAL_BAND::{json}

規律:

- **OFFLINE / READ-ONLY。** ネットワーク module を import しない。J-Quants も
  legacy journal も MarketSignal も CompassDraft も公開 /v2 も読まない。
- **research root は読むだけ。** SQLite index を開かない（journal file を作らない）。
  canonical JSONL を直接読む。実行前後で root 配下全 file の sha256 が一致することを
  runner 自身が検証する。
- **暗黙の production fallback を持たない。** `--research-root` は絶対 path 必須。
  `data_root()` を読まない。出力先（任意）は research root 外・リポジトリ外に限る。
- **取得 marker と食い違えば黙って続けない。** `acquisition.json` の件数・範囲と
  実データが一致しなければ fail closed。監督者が承認した値は `--expect-*` で
  明示的に pin できる（runner が期待値を勝手に作らない）。
- 分類境界は **RANGE が閉区間**（`-X <= r <= +X`）。return は分類前に丸めない。
- percentile は **nearest-rank**（`ceil(p/100 * N)` 番目の昇順値・補間なし）。
  標準偏差は **標本（N-1）**。いずれも出力へ method 名として記録する。
- 年の PARTIAL / FULL は dataset の端の年を PARTIAL とし、内側の年を FULL とする。
  FULL 年だけで RANGE% の min / max / spread を要約する（記述のみ。最適化しない）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..core import serialization
from ..market.model import Observation, latest_revisions

MEASUREMENT_SCHEMA_VERSION = "topix_neutral_band_measurement:0.1.0"

#: 契約上の系列 identity（catalog と一致することを test が固定する）
TOPIX_SERIES_ID = "index:topix.close.closing.tokyo"
RETURN_1D_SERIES_ID = "index:topix.return_1d.derived_metric.tokyo"
EXPECTED_SOURCE_ID = "jquants"
EXPECTED_API_VERSION = "v2"
EXPECTED_ACQUISITION_RESULT = "ACQUISITION_OK"

#: 正式候補 4 本 ＋ 文脈用 4 本（**percent**。分類は fraction で行う）
PRIMARY_THRESHOLDS_PCT: Tuple[str, ...] = ("0.20", "0.30", "0.40", "0.50")
CONTEXT_THRESHOLDS_PCT: Tuple[str, ...] = ("0.10", "0.60", "0.75", "1.00")
ALL_THRESHOLDS_PCT: Tuple[str, ...] = ("0.10", "0.20", "0.30", "0.40", "0.50", "0.60", "0.75", "1.00")

PERCENTILE_METHOD = "nearest_rank: value at index ceil(p/100*N) of ascending sorted |return| (1-indexed, no interpolation)"
STDEV_METHOD = "sample standard deviation (divisor N-1), Decimal sqrt"
MEDIAN_METHOD = "middle value; mean of the two middle values for even N"
RETURN_DEFINITION = "close(session) / close(previous Tokyo trading session) - 1, Decimal, unrounded before classification"
CLASSIFICATION_RULE = "UP: r > +X ; RANGE: -X <= r <= +X (inclusive) ; DOWN: r < -X"

#: derived `return_1d` と同じ丸め（cross-check 専用。分類には使わない）
_DERIVED_Q = Decimal("0.000001")
#: 表示用の percent 丸め（統計・表の値のみ。分類には使わない）
_DISPLAY_Q = Decimal("0.000001")

FORBIDDEN_PATH_PARTS: Tuple[Tuple[str, ...], ...] = (
    ("data", "vnext"), ("output",), ("docs",), ("knowledge",), (".git",),
)

RESULT_OK = "MEASUREMENT_OK"
RESULT_INVALID_ARGS = "INVALID_ARGUMENTS"
RESULT_INVALID_ROOT = "INVALID_RESEARCH_ROOT"
RESULT_INVALID_OUTPUT = "INVALID_OUTPUT_PATH"
RESULT_VALIDATION_FAILED = "MEASUREMENT_VALIDATION_FAILED"

MARKER = "::P5_TOPIX_NEUTRAL_BAND::"


class MeasurementError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _contains_parts(path: Path, needle: Sequence[str]) -> bool:
    parts = tuple(path.parts)
    n = len(needle)
    return any(parts[i:i + n] == tuple(needle) for i in range(len(parts) - n + 1))


def _outside_repository(path: Path, repo: Path) -> bool:
    return not (path == repo or repo in path.parents)


# ---------------------------------------------------------------- argument contract

def validate_research_root(raw: str, *, repo_root: Optional[Path] = None) -> Path:
    """読む root の contract（絶対 / リポジトリ外 / 禁止断片なし / 実在する dataset）。"""
    if not raw:
        raise MeasurementError(RESULT_INVALID_ROOT, "--research-root is required")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise MeasurementError(RESULT_INVALID_ROOT, "--research-root must be absolute")
    resolved = candidate.resolve()
    repo = (repo_root or repository_root()).resolve()
    if not _outside_repository(resolved, repo):
        raise MeasurementError(RESULT_INVALID_ROOT, "--research-root must be outside the repository")
    for needle in FORBIDDEN_PATH_PARTS:
        if _contains_parts(resolved, needle):
            raise MeasurementError(RESULT_INVALID_ROOT, f"forbidden path segment: {'/'.join(needle)}")
    if not (resolved / "acquisition.json").is_file():
        raise MeasurementError(RESULT_INVALID_ROOT, "acquisition.json not found in research root")
    if not observations_path(resolved).is_file():
        raise MeasurementError(RESULT_INVALID_ROOT, "canonical observations.jsonl not found")
    return resolved


def validate_output_path(raw: Optional[str], *, research_root: Path,
                         repo_root: Optional[Path] = None) -> Optional[Path]:
    """任意の出力先。research root 外・リポジトリ外のみ。既存 file は上書きしない。"""
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise MeasurementError(RESULT_INVALID_OUTPUT, "--output must be absolute")
    resolved = candidate.resolve()
    repo = (repo_root or repository_root()).resolve()
    if not _outside_repository(resolved, repo):
        raise MeasurementError(RESULT_INVALID_OUTPUT, "--output must be outside the repository")
    if resolved == research_root or research_root in resolved.parents:
        raise MeasurementError(RESULT_INVALID_OUTPUT, "--output must be outside the research root")
    if resolved.exists():
        raise MeasurementError(RESULT_INVALID_OUTPUT, "--output already exists (not overwritten)")
    return resolved


def observations_path(root: Path) -> Path:
    return root / "databank" / "market" / "normalized" / "observations.jsonl"


# ---------------------------------------------------------------- read-only loading

def tree_digest(root: Path) -> Dict[str, str]:
    """root 配下 **全 file** の sha256（read-only 検証用。除外なし）。"""
    out: Dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def load_acquisition(root: Path) -> Dict[str, object]:
    return json.loads((root / "acquisition.json").read_text(encoding="utf-8"))


def load_series(root: Path) -> Tuple[Tuple[Observation, ...], Tuple[Observation, ...]]:
    """canonical JSONL を直接読み、(raw TOPIX close, derived return_1d) を返す。

    SQLite index は開かない（journal file を作らないため）。壊れた行は黙って
    読み飛ばさず fail closed。
    """
    serialization.register(Observation)
    raw: List[Observation] = []
    derived: List[Observation] = []
    with observations_path(root).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                raise MeasurementError(RESULT_VALIDATION_FAILED,
                                       f"observations.jsonl line {line_no} is not valid JSON")
            if data.get("_type") != "Observation":
                continue
            obs = serialization.decode(data)
            if obs.series_id == TOPIX_SERIES_ID and obs.kind.value == "raw":
                raw.append(obs)
            elif obs.series_id == RETURN_1D_SERIES_ID:
                derived.append(obs)
    return latest_revisions(tuple(raw)), latest_revisions(tuple(derived))


# ---------------------------------------------------------------- measurement

@dataclass(frozen=True)
class ReturnSample:
    session_date: str
    previous_session: str
    realized_return: Decimal          # fraction, unrounded


def realized_returns(raw: Sequence[Observation]) -> Tuple[ReturnSample, ...]:
    """凍結定義: close(t) / close(prev) - 1（Decimal・丸めない）。"""
    ordered = sorted((o for o in raw if o.trading_date), key=lambda o: o.trading_date)
    out: List[ReturnSample] = []
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.value is None or cur.value is None or prev.value == 0:
            continue
        out.append(ReturnSample(
            session_date=cur.trading_date, previous_session=prev.trading_date,
            realized_return=(cur.value / prev.value) - Decimal(1)))
    return tuple(out)


def recompute_derived(raw: Sequence[Observation]) -> Dict[str, Decimal]:
    """derived.py と同じ式・同じ丸めで再計算（cross-check 専用）。"""
    ordered = sorted((o for o in raw if o.trading_date and o.value is not None),
                     key=lambda o: o.trading_date)
    out: Dict[str, Decimal] = {}
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.value == 0:
            continue
        out[cur.trading_date] = ((cur.value - prev.value) / prev.value * Decimal(100)
                                 ).quantize(_DERIVED_Q, rounding=ROUND_HALF_EVEN)
    return out


def classify(r: Decimal, x: Decimal) -> str:
    """UP: r > +X / RANGE: -X <= r <= +X（閉区間）/ DOWN: r < -X。"""
    if r > x:
        return "UP"
    if r < -x:
        return "DOWN"
    return "RANGE"


def nearest_rank(sorted_values: Sequence[Decimal], p: int) -> Decimal:
    if not sorted_values:
        raise MeasurementError(RESULT_VALIDATION_FAILED, "percentile of empty sample")
    rank = max(1, math.ceil(p / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def _pct(value: Decimal) -> str:
    """fraction → percent 表示（6 桁）。分類には使わない。"""
    return str((value * Decimal(100)).quantize(_DISPLAY_Q, rounding=ROUND_HALF_EVEN))


def _ratio_pct(count: int, total: int) -> str:
    if total == 0:
        return "0.00"
    return str((Decimal(count) / Decimal(total) * Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def distribution_statistics(samples: Sequence[ReturnSample]) -> Dict[str, object]:
    values = [s.realized_return for s in samples]
    n = len(values)
    if n == 0:
        raise MeasurementError(RESULT_VALIDATION_FAILED, "no realized returns")
    ordered = sorted(values)
    mean = sum(values, Decimal(0)) / Decimal(n)
    if n % 2:
        median = ordered[n // 2]
    else:
        median = (ordered[n // 2 - 1] + ordered[n // 2]) / Decimal(2)
    if n > 1:
        var = sum(((v - mean) ** 2 for v in values), Decimal(0)) / Decimal(n - 1)
        stdev = var.sqrt()
    else:
        stdev = Decimal(0)
    abs_sorted = sorted(abs(v) for v in values)
    mean_abs = sum(abs_sorted, Decimal(0)) / Decimal(n)
    return {
        "sample_n": n,
        "earliest_return_session": samples[0].session_date,
        "latest_return_session": samples[-1].session_date,
        "mean_pct": _pct(mean),
        "median_pct": _pct(median),
        "stdev_pct": _pct(stdev),
        "mean_abs_return_pct": _pct(mean_abs),
        "min_pct": _pct(ordered[0]),
        "max_pct": _pct(ordered[-1]),
        "abs_return_percentiles_pct": {
            f"P{p}": _pct(nearest_rank(abs_sorted, p)) for p in (25, 50, 75, 90, 95)},
        "percentile_method": PERCENTILE_METHOD,
        "stdev_method": STDEV_METHOD,
        "median_method": MEDIAN_METHOD,
    }


def threshold_table(samples: Sequence[ReturnSample]) -> List[Dict[str, object]]:
    n = len(samples)
    rows: List[Dict[str, object]] = []
    for x_pct in ALL_THRESHOLDS_PCT:
        x = Decimal(x_pct) / Decimal(100)
        counts = {"UP": 0, "RANGE": 0, "DOWN": 0}
        for s in samples:
            counts[classify(s.realized_return, x)] += 1
        directional = counts["UP"] + counts["DOWN"]
        rows.append({
            "threshold_pct": x_pct,
            "role": "primary" if x_pct in PRIMARY_THRESHOLDS_PCT else "context",
            "up": counts["UP"], "range": counts["RANGE"], "down": counts["DOWN"],
            "up_pct": _ratio_pct(counts["UP"], n),
            "range_pct": _ratio_pct(counts["RANGE"], n),
            "down_pct": _ratio_pct(counts["DOWN"], n),
            "directional": directional,
            "directional_pct": _ratio_pct(directional, n),
            "n": n,
            "sum_ok": counts["UP"] + counts["RANGE"] + counts["DOWN"] == n,
        })
    return rows


def yearly_table(samples: Sequence[ReturnSample]) -> Dict[str, object]:
    by_year: Dict[str, List[ReturnSample]] = {}
    for s in samples:
        by_year.setdefault(s.session_date[:4], []).append(s)
    years = sorted(by_year)
    first, last = years[0], years[-1]
    rows: List[Dict[str, object]] = []
    for year in years:
        group = by_year[year]
        n = len(group)
        entry: Dict[str, object] = {
            "year": year,
            "coverage": "PARTIAL" if year in (first, last) else "FULL",
            "first_session": group[0].session_date,
            "last_session": group[-1].session_date,
            "n": n,
            "bands": {},
        }
        for x_pct in PRIMARY_THRESHOLDS_PCT:
            x = Decimal(x_pct) / Decimal(100)
            counts = {"UP": 0, "RANGE": 0, "DOWN": 0}
            for s in group:
                counts[classify(s.realized_return, x)] += 1
            entry["bands"][x_pct] = {
                "up": counts["UP"], "range": counts["RANGE"], "down": counts["DOWN"],
                "up_pct": _ratio_pct(counts["UP"], n),
                "range_pct": _ratio_pct(counts["RANGE"], n),
                "down_pct": _ratio_pct(counts["DOWN"], n),
            }
        rows.append(entry)
    full_years = [r for r in rows if r["coverage"] == "FULL"]
    summary: Dict[str, object] = {}
    for x_pct in PRIMARY_THRESHOLDS_PCT:
        vals = [Decimal(r["bands"][x_pct]["range_pct"]) for r in full_years]
        if vals:
            lo, hi = min(vals), max(vals)
            summary[x_pct] = {"full_years": len(vals), "min_range_pct": str(lo),
                              "max_range_pct": str(hi), "spread_pp": str(hi - lo)}
        else:
            summary[x_pct] = {"full_years": 0, "min_range_pct": "", "max_range_pct": "", "spread_pp": ""}
    return {"years": rows, "full_year_range_summary": summary,
            "yearly_sum_ok": sum(int(r["n"]) for r in rows) == len(samples)}


# ---------------------------------------------------------------- validation

def validate(
    *,
    acquisition: Mapping[str, object],
    raw: Sequence[Observation],
    derived: Sequence[Observation],
    samples: Sequence[ReturnSample],
    thresholds: Sequence[Mapping[str, object]],
    yearly: Mapping[str, object],
    digest_before: Mapping[str, str],
    digest_after: Mapping[str, str],
    expect: Mapping[str, Optional[str]],
    output_text: str,
) -> Dict[str, object]:
    checks: Dict[str, object] = {}
    ordered = sorted((o for o in raw if o.trading_date), key=lambda o: o.trading_date)
    days = [o.trading_date for o in ordered]
    acq_checks = acquisition.get("checks") or {}

    checks["acquisition_result_ok"] = acquisition.get("result") == EXPECTED_ACQUISITION_RESULT
    checks["acquisition_checks_all_true"] = bool(acq_checks) and all(
        v is True for v in acq_checks.values())
    checks["source_is_jquants_v2"] = (
        acquisition.get("api_version") == EXPECTED_API_VERSION
        and bool(ordered) and all(o.source_id == EXPECTED_SOURCE_ID for o in ordered))
    checks["observation_count_matches_acquisition"] = (
        len(ordered) == int(acquisition.get("topix_observations") or -1))
    checks["derived_count_matches_acquisition"] = (
        len(derived) == int(acquisition.get("derived_return_1d") or -1))
    checks["coverage_matches_acquisition"] = bool(days) and (
        days[0] == acquisition.get("topix_earliest")
        and days[-1] == acquisition.get("topix_latest"))
    if expect.get("observations") is not None:
        checks["observation_count_matches_expected"] = len(ordered) == int(expect["observations"])
    if expect.get("returns") is not None:
        checks["return_count_matches_expected"] = len(samples) == int(expect["returns"])
    if expect.get("earliest") is not None:
        checks["earliest_matches_expected"] = bool(days) and days[0] == expect["earliest"]
    if expect.get("latest") is not None:
        checks["latest_matches_expected"] = bool(days) and days[-1] == expect["latest"]
    checks["no_duplicate_trading_date"] = len(days) == len(set(days))
    checks["no_missing_or_nonpositive_close"] = bool(ordered) and all(
        o.value is not None and o.value > 0 for o in ordered)
    stored = {o.trading_date: o.value for o in derived if o.value is not None}
    checks["recomputed_returns_match_stored_derived"] = (
        bool(stored) and recompute_derived(ordered) == stored)
    checks["return_count_equals_observations_minus_one"] = len(samples) == max(len(ordered) - 1, 0)
    checks["classification_counts_sum_to_n"] = all(bool(row["sum_ok"]) for row in thresholds)
    checks["yearly_counts_sum_to_n"] = bool(yearly.get("yearly_sum_ok"))
    checks["no_network_module_in_runner"] = not _network_modules_present()
    checks["research_root_unmodified"] = digest_before == digest_after
    checks["no_secret_in_output"] = _no_secret(output_text)
    return checks


def _network_modules_present() -> bool:
    module = sys.modules[__name__]
    names = set()
    for value in vars(module).values():
        name = getattr(value, "__name__", "") if hasattr(value, "__spec__") else ""
        if name:
            names.add(name.split(".")[0])
    return bool(names & {"urllib", "http", "socket", "requests", "ssl"})


def _no_secret(text: str) -> bool:
    if "x-api-key" in text or "api_key=" in text:
        return False
    secret = os.environ.get("JQUANTS_API_KEY", "").strip()
    return not (secret and secret in text)


# ---------------------------------------------------------------- orchestration

def measure(root: Path, *, expect: Mapping[str, Optional[str]]) -> Tuple[str, Dict[str, object]]:
    digest_before = tree_digest(root)
    acquisition = load_acquisition(root)
    raw, derived = load_series(root)
    samples = realized_returns(raw)
    if not samples:
        raise MeasurementError(RESULT_VALIDATION_FAILED, "no realized returns in dataset")
    stats = distribution_statistics(samples)
    thresholds = threshold_table(samples)
    yearly = yearly_table(samples)
    ordered_days = sorted(o.trading_date for o in raw if o.trading_date)

    payload: Dict[str, object] = {
        "schema_version": MEASUREMENT_SCHEMA_VERSION,
        "result": "",
        "source_acquisition": {
            "schema_version": acquisition.get("schema_version"),
            "result": acquisition.get("result"),
            "research_root": acquisition.get("research_root"),   # basename のみ（絶対 path は持たない）
            "requested_start": acquisition.get("requested_start"),
            "requested_end": acquisition.get("requested_end"),
            "api_version": acquisition.get("api_version"),
            "topix_observations": acquisition.get("topix_observations"),
            "derived_return_1d": acquisition.get("derived_return_1d"),
            "topix_pages": acquisition.get("topix_pages"),
            "calendar_rows": acquisition.get("calendar_rows"),
        },
        "sample_coverage": {
            "topix_observations": len(ordered_days),
            "first_session": ordered_days[0] if ordered_days else "",
            "last_session": ordered_days[-1] if ordered_days else "",
            "realized_returns": len(samples),
        },
        "definitions": {
            "realized_return": RETURN_DEFINITION,
            "classification": CLASSIFICATION_RULE,
            "thresholds_primary_pct": list(PRIMARY_THRESHOLDS_PCT),
            "thresholds_context_pct": list(CONTEXT_THRESHOLDS_PCT),
        },
        "distribution": stats,
        "thresholds": thresholds,
        "yearly": yearly,
        "checks": {},
    }
    digest_after = tree_digest(root)
    provisional = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    checks = validate(
        acquisition=acquisition, raw=raw, derived=derived, samples=samples,
        thresholds=thresholds, yearly=yearly, digest_before=digest_before,
        digest_after=digest_after, expect=expect, output_text=provisional)
    payload["checks"] = checks
    failed = sorted(k for k, v in checks.items() if v is not True)
    result = RESULT_OK if not failed else RESULT_VALIDATION_FAILED
    payload["result"] = result
    payload["failed_checks"] = failed
    return result, payload


def human_table(payload: Mapping[str, object]) -> str:
    lines: List[str] = []
    cov = payload["sample_coverage"]
    dist = payload["distribution"]
    lines.append(f"TOPIX close-to-close realized returns  N={cov['realized_returns']}  "
                 f"{dist['earliest_return_session']} .. {dist['latest_return_session']}")
    lines.append(f"  mean={dist['mean_pct']}%  median={dist['median_pct']}%  "
                 f"stdev={dist['stdev_pct']}%  mean|r|={dist['mean_abs_return_pct']}%  "
                 f"min={dist['min_pct']}%  max={dist['max_pct']}%")
    p = dist["abs_return_percentiles_pct"]
    lines.append(f"  |r| percentiles (nearest-rank): P25={p['P25']} P50={p['P50']} "
                 f"P75={p['P75']} P90={p['P90']} P95={p['P95']} (%)")
    lines.append("")
    lines.append(f"  {'band':>7} {'role':<8} {'UP':>5} {'RANGE':>6} {'DOWN':>5} "
                 f"{'UP%':>7} {'RANGE%':>7} {'DOWN%':>7} {'DIR%':>7} {'N':>5}")
    for row in payload["thresholds"]:
        lines.append(f"  ±{row['threshold_pct']:>5}% {row['role']:<8} {row['up']:>5} "
                     f"{row['range']:>6} {row['down']:>5} {row['up_pct']:>7} "
                     f"{row['range_pct']:>7} {row['down_pct']:>7} "
                     f"{row['directional_pct']:>7} {row['n']:>5}")
    lines.append("")
    lines.append(f"  {'year':<6}{'cov':<9}{'N':>5}  " + "  ".join(
        f"±{x}% RANGE%" for x in PRIMARY_THRESHOLDS_PCT))
    for y in payload["yearly"]["years"]:
        lines.append(f"  {y['year']:<6}{y['coverage']:<9}{y['n']:>5}  " + "  ".join(
            f"{y['bands'][x]['range_pct']:>12}" for x in PRIMARY_THRESHOLDS_PCT))
    summary = payload["yearly"]["full_year_range_summary"]
    lines.append("  FULL-year RANGE% min/max/spread(pp): " + "  ".join(
        f"±{x}%: {summary[x]['min_range_pct']}/{summary[x]['max_range_pct']}/{summary[x]['spread_pp']}"
        for x in PRIMARY_THRESHOLDS_PCT))
    lines.append("")
    lines.append(f"  result={payload['result']}  failed_checks={payload.get('failed_checks')}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5 TOPIX neutral-band OFFLINE measurement (read-only; no threshold decision)")
    parser.add_argument("--research-root", required=True, help="絶対 path。A0.7B-R2 の research root")
    parser.add_argument("--output", default="", help="任意。JSON 出力先（research root 外・リポジトリ外・未存在）")
    parser.add_argument("--expect-observations", type=int, default=None)
    parser.add_argument("--expect-returns", type=int, default=None)
    parser.add_argument("--expect-earliest", default=None)
    parser.add_argument("--expect-latest", default=None)
    args = parser.parse_args(argv)
    try:
        root = validate_research_root(args.research_root)
        output = validate_output_path(args.output, research_root=root)
        expect = {"observations": args.expect_observations, "returns": args.expect_returns,
                  "earliest": args.expect_earliest, "latest": args.expect_latest}
        result, payload = measure(root, expect=expect)
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        print(human_table(payload))
        print(MARKER + text)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
        return 0 if result == RESULT_OK else 1
    except MeasurementError as exc:
        print(MARKER + json.dumps({"schema_version": MEASUREMENT_SCHEMA_VERSION,
                                   "result": exc.code, "detail": exc.detail}, ensure_ascii=False))
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
