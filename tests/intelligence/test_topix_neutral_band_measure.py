"""Phase 5 TOPIX neutral-band OFFLINE measurement runner の決定論的ガード。

fixture はすべて手組み（synthetic は **test 専用**であり、測定結果としては
一切使わない）。ネットワーク・credential・production data root・repository には
触れない。研究 root は読むだけであることを sha256 で証明する。
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

import pytest

from src.intelligence.core import serialization
from src.intelligence.market.model import Observation, ObservationKind
from src.intelligence.predictions import topix_neutral_band_measure as m

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "topix_neutral_band_measure.py"
CATALOG = REPO_ROOT / "knowledge" / "market_series" / "core_series.yaml"

#: 6 年に跨る決定論的 fixture（端の年は PARTIAL、内側は FULL になる）。値は string トークン。
SESSIONS = (
    ("2021-12-29", "1990"), ("2021-12-30", "2000"),
    ("2022-01-04", "2004"), ("2022-06-01", "2004"), ("2022-12-30", "1990"),
    ("2023-01-04", "1996"), ("2023-06-01", "2020"), ("2023-12-29", "2010"),
    ("2024-01-04", "2010.5"), ("2024-06-03", "2030"), ("2024-12-30", "2030"),
    ("2025-01-06", "2050.15"), ("2025-06-02", "2000"), ("2025-12-30", "2010"),
    ("2026-01-05", "2011"), ("2026-01-06", "2000"),
)


def _raw(day: str, close: str, *, source_id: str = "jquants") -> Observation:
    return Observation(
        observation_id=f"obs_raw_{day}", entity_id="index:topix", metric="close",
        value=Decimal(close), unit="index",
        as_of=datetime.fromisoformat(day + "T06:30:00+00:00"),
        kind=ObservationKind.RAW, calculation_method="provider_daily_close",
        source_id=source_id, series_id=m.TOPIX_SERIES_ID, trading_date=day)


def _derived(prev: Observation, cur: Observation, *, value: Decimal | None = None) -> Observation:
    change = value if value is not None else (
        (cur.value - prev.value) / prev.value * Decimal(100)
    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)
    return Observation(
        observation_id=f"obs_ret_{cur.trading_date}", entity_id="index:topix",
        metric="return_1d", value=change, unit="pct", as_of=cur.as_of,
        kind=ObservationKind.DERIVED, calculation_method="pct_change_1d:1.0.0",
        inputs=(prev.observation_id, cur.observation_id), source_id="derived_calculation",
        series_id=m.RETURN_1D_SERIES_ID, trading_date=cur.trading_date)


def build_root(root: Path, *, sessions=SESSIONS, acquisition_overrides=None,
               derived_tamper: str = "", raw_extra=()) -> Path:
    """research root を手組みする（acquisition.json ＋ canonical observations.jsonl）。"""
    serialization.register(Observation)
    raws = [_raw(d, c) for d, c in sessions] + list(raw_extra)
    ordered = sorted(raws, key=lambda o: o.trading_date)
    deriveds = [_derived(p, c) for p, c in zip(ordered, ordered[1:])]
    if derived_tamper:
        deriveds = [d if d.trading_date != derived_tamper else
                    _derived(ordered[0], ordered[1], value=Decimal("99.999999"))
                    for d in deriveds]
        deriveds = [d if d.trading_date != derived_tamper else Observation(
            **{**{f: getattr(d, f) for f in d.__dataclass_fields__},
               "trading_date": derived_tamper}) for d in deriveds]
    obs_path = m.observations_path(root)
    obs_path.parent.mkdir(parents=True)
    with obs_path.open("w", encoding="utf-8") as handle:
        for obs in raws + deriveds:
            handle.write(json.dumps(serialization.encode(obs), ensure_ascii=False) + "\n")
    days = sorted({o.trading_date for o in raws})
    acquisition = {
        "schema_version": "topix_research_acquisition:0.1.0", "result": "ACQUISITION_OK",
        "research_root": root.name, "requested_start": days[0], "requested_end": days[-1],
        "topix_observations": len(days), "topix_earliest": days[0], "topix_latest": days[-1],
        "topix_pages": 1, "api_version": "v2", "calendar_rows": len(days) + 3,
        "calendar_pages": 1, "derived_return_1d": len(days) - 1,
        "checks": {k: True for k in (
            "topix_observations_present", "no_synthetic_source", "provider_is_jquants_v2",
            "no_duplicate_trading_date", "no_missing_close", "no_nonpositive_close",
            "calendar_validated", "no_session_gap", "no_weekday_fallback",
            "derived_return_matches_recomputation", "no_secret_leakage",
            "no_repository_write", "no_production_data_root_write")},
    }
    acquisition.update(acquisition_overrides or {})
    (root / "acquisition.json").write_text(
        json.dumps(acquisition, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return root


@pytest.fixture()
def research_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("p5measure") / "topix-neutral-band-2026-entitled"
    root.mkdir()
    return build_root(root)


def run_main(root: Path, *extra: str, capsys=None):
    return m.main(["--research-root", str(root), *extra])


def marker_payload(captured: str) -> dict:
    line = [ln for ln in captured.splitlines() if ln.startswith(m.MARKER)][-1]
    return json.loads(line[len(m.MARKER):])


# ---------------------------------------------------------------- classification contract

def test_boundary_is_inclusive_for_range() -> None:
    x = Decimal("0.0020")
    assert m.classify(Decimal("0.0020"), x) == "RANGE"
    assert m.classify(Decimal("-0.0020"), x) == "RANGE"
    assert m.classify(Decimal("0.0020000001"), x) == "UP"
    assert m.classify(Decimal("-0.0020000001"), x) == "DOWN"
    assert m.classify(Decimal("0"), x) == "RANGE"


def test_positive_and_negative_classification() -> None:
    x = Decimal("0.0050")
    assert m.classify(Decimal("0.0123"), x) == "UP"
    assert m.classify(Decimal("-0.0123"), x) == "DOWN"
    assert m.classify(Decimal("0.0049"), x) == "RANGE"


def test_realized_return_is_unrounded_decimal() -> None:
    """1e-6 に丸めると RANGE に落ちる値でも、丸めない実値で UP と判定する。"""
    prev = _raw("2026-01-05", "10000000")
    cur = _raw("2026-01-06", "10020000.001")
    (sample,) = m.realized_returns([prev, cur])
    assert isinstance(sample.realized_return, Decimal)
    assert sample.realized_return == Decimal("10020000.001") / Decimal("10000000") - 1
    assert m.classify(sample.realized_return, Decimal("0.0020")) == "UP"
    rounded = sample.realized_return.quantize(Decimal("0.000001"))
    assert m.classify(rounded, Decimal("0.0020")) == "RANGE"   # 丸めていたら別の答えになる


def test_percentile_is_nearest_rank_without_interpolation() -> None:
    values = [Decimal(v) for v in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10")]
    assert m.nearest_rank(values, 25) == Decimal("3")     # ceil(2.5)=3 番目
    assert m.nearest_rank(values, 50) == Decimal("5")     # ceil(5.0)=5 番目（補間なし）
    assert m.nearest_rank(values, 90) == Decimal("9")
    assert m.nearest_rank(values, 95) == Decimal("10")    # ceil(9.5)=10 番目
    assert "nearest_rank" in m.PERCENTILE_METHOD


def test_median_averages_two_middle_values_for_even_n() -> None:
    samples = m.realized_returns([_raw(d, c) for d, c in SESSIONS[:5]])   # 4 returns
    stats = m.distribution_statistics(samples)
    ordered = sorted(s.realized_return for s in samples)
    expected = ((ordered[1] + ordered[2]) / 2 * 100).quantize(Decimal("0.000001"))
    assert Decimal(stats["median_pct"]) == expected
    assert "N-1" in stats["stdev_method"]


# ---------------------------------------------------------------- tables

def test_threshold_set_and_count_conservation(research_root) -> None:
    _, payload = m.measure(research_root, expect={})
    rows = payload["thresholds"]
    assert [r["threshold_pct"] for r in rows] == list(m.ALL_THRESHOLDS_PCT)
    assert {r["threshold_pct"] for r in rows if r["role"] == "primary"} == set(m.PRIMARY_THRESHOLDS_PCT)
    n = payload["sample_coverage"]["realized_returns"]
    for r in rows:
        assert r["up"] + r["range"] + r["down"] == n == r["n"]
        assert r["directional"] == r["up"] + r["down"]
        assert r["sum_ok"] is True


def test_range_is_monotone_in_threshold(research_root) -> None:
    _, payload = m.measure(research_root, expect={})
    ranges = [r["range"] for r in payload["thresholds"]]
    assert ranges == sorted(ranges)


def test_yearly_grouping_and_partial_full_labels(research_root) -> None:
    _, payload = m.measure(research_root, expect={})
    years = payload["yearly"]["years"]
    labels = {y["year"]: y["coverage"] for y in years}
    assert labels == {"2021": "PARTIAL", "2022": "FULL", "2023": "FULL", "2024": "FULL",
                      "2025": "FULL", "2026": "PARTIAL"}
    assert sum(y["n"] for y in years) == payload["sample_coverage"]["realized_returns"]
    assert payload["yearly"]["yearly_sum_ok"] is True
    for y in years:
        for x in m.PRIMARY_THRESHOLDS_PCT:
            b = y["bands"][x]
            assert b["up"] + b["range"] + b["down"] == y["n"]
    summary = payload["yearly"]["full_year_range_summary"]
    for x in m.PRIMARY_THRESHOLDS_PCT:
        assert summary[x]["full_years"] == 4
        lo, hi = Decimal(summary[x]["min_range_pct"]), Decimal(summary[x]["max_range_pct"])
        assert Decimal(summary[x]["spread_pp"]) == hi - lo


# ---------------------------------------------------------------- fail-closed validation

def test_clean_fixture_passes_all_checks(research_root) -> None:
    result, payload = m.measure(research_root, expect={
        "observations": len(SESSIONS), "returns": len(SESSIONS) - 1,
        "earliest": SESSIONS[0][0], "latest": SESSIONS[-1][0]})
    assert result == m.RESULT_OK, payload["failed_checks"]
    assert all(v is True for v in payload["checks"].values())


def test_acquisition_count_mismatch_fails_closed(tmp_path) -> None:
    root = build_root(tmp_path / "r", acquisition_overrides={"topix_observations": 1223})
    result, payload = m.measure(root, expect={})
    assert result == m.RESULT_VALIDATION_FAILED
    assert "observation_count_matches_acquisition" in payload["failed_checks"]


def test_acquisition_not_ok_fails_closed(tmp_path) -> None:
    root = build_root(tmp_path / "r", acquisition_overrides={"result": "ACQUISITION_FETCH_FAILED"})
    result, payload = m.measure(root, expect={})
    assert result == m.RESULT_VALIDATION_FAILED
    assert "acquisition_result_ok" in payload["failed_checks"]


def test_acquisition_check_false_fails_closed(tmp_path) -> None:
    root = build_root(tmp_path / "r")
    acq = json.loads((root / "acquisition.json").read_text(encoding="utf-8"))
    acq["checks"]["no_session_gap"] = False
    (root / "acquisition.json").write_text(json.dumps(acq), encoding="utf-8")
    result, payload = m.measure(root, expect={})
    assert result == m.RESULT_VALIDATION_FAILED
    assert "acquisition_checks_all_true" in payload["failed_checks"]


def test_derived_return_mismatch_fails_closed(tmp_path) -> None:
    root = build_root(tmp_path / "r", derived_tamper="2023-06-01")
    result, payload = m.measure(root, expect={})
    assert result == m.RESULT_VALIDATION_FAILED
    assert "recomputed_returns_match_stored_derived" in payload["failed_checks"]


def test_expected_pins_mismatch_fails_closed(research_root, capsys) -> None:
    code = run_main(research_root, "--expect-observations", "1223")
    payload = marker_payload(capsys.readouterr().out)
    assert code == 1
    assert payload["result"] == m.RESULT_VALIDATION_FAILED
    assert "observation_count_matches_expected" in payload["failed_checks"]


def test_synthetic_source_is_rejected(tmp_path) -> None:
    root = build_root(tmp_path / "r", sessions=SESSIONS[:3],
                      raw_extra=(_raw("2026-02-02", "2001", source_id="test"),))
    result, payload = m.measure(root, expect={})
    assert result == m.RESULT_VALIDATION_FAILED
    assert "source_is_jquants_v2" in payload["failed_checks"]


def test_revisions_are_resolved_to_latest(tmp_path) -> None:
    """改定行（revision_of）があっても件数は増えず、最新値だけを使う。"""
    root = tmp_path / "r"
    root.mkdir()
    serialization.register(Observation)
    raws = [_raw(d, c) for d, c in SESSIONS[:4]]
    revised = Observation(**{**{f: getattr(raws[1], f) for f in raws[1].__dataclass_fields__},
                             "observation_id": "obs_raw_rev", "value": Decimal("2001"),
                             "revision_of": raws[1].observation_id})
    build_root(root, sessions=SESSIONS[:4])
    with m.observations_path(root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(serialization.encode(revised)) + "\n")
    raw, _ = m.load_series(root)
    assert len(raw) == 4
    assert next(o for o in raw if o.trading_date == raws[1].trading_date).value == Decimal("2001")


# ---------------------------------------------------------------- root / output contract

def test_root_must_be_absolute_and_outside_repository(tmp_path) -> None:
    with pytest.raises(m.MeasurementError) as exc:
        m.validate_research_root("relative/root")
    assert exc.value.code == m.RESULT_INVALID_ROOT
    with pytest.raises(m.MeasurementError) as exc:
        m.validate_research_root(str(REPO_ROOT / "data" / "vnext"))
    assert exc.value.code == m.RESULT_INVALID_ROOT
    with pytest.raises(m.MeasurementError) as exc:
        m.validate_research_root(str(tmp_path / "no-acquisition-here"))
    assert exc.value.code == m.RESULT_INVALID_ROOT


def test_output_path_contract(research_root, tmp_path) -> None:
    with pytest.raises(m.MeasurementError):
        m.validate_output_path(str(research_root / "measurement.json"), research_root=research_root)
    with pytest.raises(m.MeasurementError):
        m.validate_output_path(str(REPO_ROOT / "measurement.json"), research_root=research_root)
    existing = tmp_path / "exists.json"
    existing.write_text("{}", encoding="utf-8")
    with pytest.raises(m.MeasurementError):
        m.validate_output_path(str(existing), research_root=research_root)
    fresh = tmp_path / "out" / "measurement.json"
    assert m.validate_output_path(str(fresh), research_root=research_root) == fresh.resolve()
    assert m.validate_output_path("", research_root=research_root) is None


# ---------------------------------------------------------------- read-only / no network / determinism

def test_research_root_is_never_written(research_root, capsys) -> None:
    before = m.tree_digest(research_root)
    code = run_main(research_root)
    payload = marker_payload(capsys.readouterr().out)
    assert code == 0
    assert m.tree_digest(research_root) == before
    assert payload["checks"]["research_root_unmodified"] is True
    assert not (research_root / "databank" / "market" / "index").exists()   # SQLite を作らない


def test_output_is_deterministic(research_root, capsys) -> None:
    run_main(research_root)
    first = marker_payload(capsys.readouterr().out)
    run_main(research_root)
    second = marker_payload(capsys.readouterr().out)
    assert first == second


def test_optional_output_file_is_written_outside_root(research_root, tmp_path, capsys) -> None:
    out = tmp_path / "measurement" / "result.json"
    code = run_main(research_root, "--output", str(out))
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["result"] == m.RESULT_OK
    assert marker_payload(capsys.readouterr().out)["checks"]["research_root_unmodified"] is True


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return tree


def executable_source(path: Path = MODULE_PATH) -> str:
    return ast.unparse(_strip_docstrings(ast.parse(path.read_text(encoding="utf-8"))))


def imported_modules(path: Path = MODULE_PATH) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(("." * node.level) + node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_no_network_path_in_runner() -> None:
    imports = imported_modules()
    for forbidden in ("urllib", "http", "socket", "requests", "ssl",
                      "jquants", "providers", "backfill", "store", "pilot_runner",
                      "jquants_v2_client", "topix_research_acquire"):
        assert not any(forbidden in name for name in imports), (forbidden, imports)
    assert m._network_modules_present() is False
    src = executable_source()
    for forbidden in ("api.jquants.com", "urlopen", "requests.", "socket."):
        assert forbidden not in src, forbidden


def test_no_production_or_legacy_dependency() -> None:
    imports = imported_modules()
    for forbidden in ("analysis", "investment_journal", "notifiers", "reports", "pages_parallel",
                      "delivery", "market_signal", "morning_brief", "compass", "decision",
                      "formal_review", "shadow_review", "evaluation", "corpus", "replay", "paths"):
        assert not any(forbidden in name for name in imports), (forbidden, imports)
    src = executable_source()
    for forbidden in ("data_root(", "market_bank_root(", "knowledge/compass_dna",
                      "decisions.jsonl", "patterns.jsonl", "MarketSignal", "CompassDraft"):
        assert forbidden not in src, forbidden


def test_series_ids_match_the_catalog() -> None:
    from src.intelligence.market.series_catalog import derived_series_id_for, load_catalog

    spec = load_catalog(CATALOG).get(m.TOPIX_SERIES_ID)
    assert spec is not None
    assert derived_series_id_for(spec, "return_1d") == m.RETURN_1D_SERIES_ID


def test_not_reachable_from_production_entrypoints() -> None:
    for rel in ("market/pilot_runner.py", "reports/delivery_pilot.py", "reports/pages_parallel.py"):
        path = REPO_ROOT / "src" / "intelligence" / rel
        assert not any("predictions" in name for name in imported_modules(path)), path


def test_output_carries_no_recommendation_or_secret(research_root, capsys, monkeypatch) -> None:
    monkeypatch.setenv("JQUANTS_API_KEY", "MEASURE-SECRET-XYZ")
    run_main(research_root)
    out = capsys.readouterr().out
    for forbidden in ("MEASURE-SECRET-XYZ", "x-api-key", "recommend", "best", "preferred",
                      "推奨", "最適", "D:\\", "/home/"):
        assert forbidden not in out, forbidden
    payload = marker_payload(out)
    assert payload["checks"]["no_secret_in_output"] is True
    assert "research_root" in payload["source_acquisition"]
    assert "\\" not in str(payload["source_acquisition"]["research_root"])
