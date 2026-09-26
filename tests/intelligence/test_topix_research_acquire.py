"""Phase 5 ONE-TIME TOPIX research acquisition driver の offline ガード。

実 API を一切使わない（HTTP は注入した fake のみ）。ネットワーク・credential・
production data root・repository には触れない。

検査の柱:

- research root の contract（絶対 path / リポジトリ外 / 空のみ / 非空は fail closed）
- credential 未設定なら **ネットワーク 0 回・ディレクトリ作成 0 回**
- 到達する endpoint が **TOPIX と取引カレンダーの 2 つだけ**
- pagination の追跡と、凍結 20 page 上限到達時の fail closed
- 欠測 close / カレンダー不整合 / session gap が validation で落ちること
- raw close からの独立再計算が既存 derived `return_1d` と一致すること
- credential が成果物へ永続化されないこと
- production isolation（legacy journal / publication / Pages / governance /
  Compass DNA / workflow / producer / data_root fallback への非依存）
"""
from __future__ import annotations

import ast
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.predictions import topix_research_acquire as drv

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / "knowledge" / "market_series" / "core_series.yaml"
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "predictions" / "topix_research_acquire.py"

#: 決定論的な fixture（5 営業日＋週末 2 日）。値は string トークンのまま渡す。
SESSIONS = (
    ("2026-09-01", "2700"),
    ("2026-09-02", "2718.25"),
    ("2026-09-03", "2705.5"),
    ("2026-09-04", "2705.5"),
    ("2026-09-07", "2660"),
)
NON_SESSIONS = ("2026-09-05", "2026-09-06")
START = date(2026, 9, 1)
END = date(2026, 9, 7)


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return tree


def executable_source(path: Path = MODULE_PATH) -> str:
    """docstring と comment を除いた**実行される内容だけ**（散文で検査を汚さない）。"""
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


# ---------------------------------------------------------------- fixtures / helpers

def topix_rows(sessions=SESSIONS):
    return [{"Date": d, "O": c, "H": c, "L": c, "C": c} for d, c in sessions]


def calendar_rows(sessions=SESSIONS, non_sessions=NON_SESSIONS, division="1"):
    rows = [{"Date": d, "HolDiv": division} for d, _ in sessions]
    rows += [{"Date": d, "HolDiv": "0"} for d in non_sessions]
    return sorted(rows, key=lambda r: r["Date"])


class FakeHttp:
    """URL を記録し、path ごとに固定 body を返す（ネットワークを使わない）。"""

    def __init__(self, *, topix_pages=None, calendar_pages=None):
        self.topix_pages = topix_pages or [{"data": topix_rows()}]
        self.calendar_pages = calendar_pages or [{"data": calendar_rows()}]
        self.urls = []
        self._topix_seen = 0
        self._calendar_seen = 0

    def __call__(self, url, method, headers, payload):
        self.urls.append(url)
        if drv.TOPIX_PATH in url:
            page = self.topix_pages[min(self._topix_seen, len(self.topix_pages) - 1)]
            self._topix_seen += 1
            return 200, json.dumps(page).encode("utf-8")
        if drv.CALENDAR_PATH in url:
            page = self.calendar_pages[min(self._calendar_seen, len(self.calendar_pages) - 1)]
            self._calendar_seen += 1
            return 200, json.dumps(page).encode("utf-8")
        raise AssertionError(f"driver reached a non-allowlisted endpoint: {url}")

    @property
    def paths(self):
        out = []
        for url in self.urls:
            for endpoint in drv.ALLOWED_ENDPOINTS:
                if endpoint in url:
                    out.append(endpoint)
                    break
            else:  # pragma: no cover - FakeHttp raises first
                out.append(url)
        return out


def run_acquire(root: Path, http: FakeHttp, *, start=START, end=END):
    from src.intelligence.market.jquants_v2 import JQuantsV2TopixProvider
    from src.intelligence.market.jquants_v2_client import JQuantsV2Client

    env = {"JQUANTS_API_KEY": "offline-fixture-key"}
    provider = JQuantsV2TopixProvider(http, env=env)
    client = JQuantsV2Client(http, env=env, sleeper=lambda _s: None)
    outcome, bank, light = drv.acquire(
        research_root=root, start=start, end=end, catalog_path=CATALOG,
        provider=provider, client=client)
    bank.close()
    light.close()
    return outcome


@pytest.fixture()
def research_root(tmp_path_factory):
    """リポジトリ外・空の research root（pytest tmp は repo 配下ではない）。"""
    root = tmp_path_factory.mktemp("p5research") / "topix-neutral-band"
    return root


# ---------------------------------------------------------------- root contract

def test_research_root_is_required() -> None:
    with pytest.raises(SystemExit):
        drv.main(["--start-date", "2026-09-01", "--end-date", "2026-09-07"])


def test_relative_research_root_is_rejected() -> None:
    with pytest.raises(drv.ResearchAcquisitionError) as exc:
        drv.validate_research_root("relative/path")
    assert exc.value.code == drv.RESULT_INVALID_ROOT


def test_repository_root_is_rejected() -> None:
    with pytest.raises(drv.ResearchAcquisitionError) as exc:
        drv.validate_research_root(str(REPO_ROOT))
    assert exc.value.code == drv.RESULT_INVALID_ROOT


def test_paths_inside_the_repository_are_rejected(tmp_path) -> None:
    for inside in ("data/vnext", "output", "docs", "knowledge", ".git", "src", "tests"):
        with pytest.raises(drv.ResearchAcquisitionError) as exc:
            drv.validate_research_root(str(REPO_ROOT / inside))
        assert exc.value.code == drv.RESULT_INVALID_ROOT, inside


def test_production_data_root_is_rejected_even_outside_the_repository(tmp_path) -> None:
    """別 checkout の `data/vnext` を指しても拒否する（名前断片で二重に守る）。"""
    with pytest.raises(drv.ResearchAcquisitionError) as exc:
        drv.validate_research_root(str(tmp_path / "somewhere" / "data" / "vnext"))
    assert exc.value.code == drv.RESULT_INVALID_ROOT


def test_non_empty_research_root_fails_closed(tmp_path) -> None:
    root = tmp_path / "already-used"
    root.mkdir()
    (root / "acquisition.json").write_text("{}", encoding="utf-8")
    with pytest.raises(drv.ResearchAcquisitionError) as exc:
        drv.validate_research_root(str(root))
    assert exc.value.code == drv.RESULT_NON_EMPTY_ROOT


def test_rerun_against_a_populated_root_is_refused(research_root) -> None:
    """2 回目は黙って追記・混合せず NON_EMPTY_RESEARCH_ROOT。"""
    run_acquire(research_root, FakeHttp())
    with pytest.raises(drv.ResearchAcquisitionError) as exc:
        drv.validate_research_root(str(research_root))
    assert exc.value.code == drv.RESULT_NON_EMPTY_ROOT


def test_empty_existing_directory_is_accepted(tmp_path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    assert drv.validate_research_root(str(root)) == root.resolve()


# ---------------------------------------------------------------- window contract

def test_start_must_precede_end() -> None:
    with pytest.raises(drv.ResearchAcquisitionError) as exc:
        drv.validate_window(date(2026, 9, 7), date(2026, 9, 1), today=date(2026, 9, 16))
    assert exc.value.code == drv.RESULT_INVALID_ARGS


def test_future_end_date_is_rejected() -> None:
    with pytest.raises(drv.ResearchAcquisitionError) as exc:
        drv.validate_window(date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 16))
    assert exc.value.code == drv.RESULT_INVALID_ARGS


def test_driver_does_not_compute_the_ten_year_window_itself() -> None:
    """研究条件は実行ログから再現できなければならない（driver が期間を作らない）。"""
    source = executable_source()
    for forbidden in ("timedelta(days=", "365", "3650", "default_range"):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------- credential contract

def test_missing_credential_makes_zero_network_calls_and_creates_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    root = tmp_path / "never-created"
    calls = []
    monkeypatch.setattr(
        "src.intelligence.market.jquants_v2._default_http",
        lambda *a, **k: calls.append(a) or (200, b"{}"))
    code = drv.main(["--research-root", str(root), "--start-date", "2026-09-01",
                     "--end-date", "2026-09-07"])
    assert code == 1
    assert calls == []
    assert not root.exists()


def test_credential_is_never_a_cli_argument() -> None:
    source = executable_source()
    for forbidden in ("--api-key", "--jquants", "--credential", "--token"):
        assert forbidden not in source, forbidden


def test_credential_is_not_persisted_into_the_research_dataset(research_root, monkeypatch) -> None:
    secret = "offline-fixture-key"
    monkeypatch.setenv("JQUANTS_API_KEY", secret)
    outcome = run_acquire(research_root, FakeHttp())
    assert outcome.checks["no_secret_leakage"] is True
    for path in research_root.rglob("*"):
        if path.is_file():
            assert secret.encode("utf-8") not in path.read_bytes(), path


# ---------------------------------------------------------------- endpoint allowlist

def test_exactly_two_endpoint_families_are_reached(research_root) -> None:
    http = FakeHttp()
    run_acquire(research_root, http)
    assert set(http.paths) == set(drv.ALLOWED_ENDPOINTS)
    assert len(drv.ALLOWED_ENDPOINTS) == 2


def test_no_other_provider_or_entrypoint_is_reachable() -> None:
    source = executable_source()
    for forbidden in ("yfinance", "stooq", "treasury", "mof_jgb", "MofJgb",
                      "pilot_runner", "fred", "Stooq", "Yfinance"):
        assert forbidden not in source, forbidden


def test_not_entitled_endpoints_are_never_referenced() -> None:
    source = executable_source()
    for forbidden in ("/indices/bars/daily\"", "/fins/", "/markets/short-ratio",
                      "/equities/", "/markets/breakdown"):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------- pagination

def test_pagination_is_followed_and_rows_are_merged(research_root) -> None:
    first = {"data": topix_rows(SESSIONS[:3]), "pagination_key": "p2"}
    second = {"data": topix_rows(SESSIONS[3:])}
    http = FakeHttp(topix_pages=[first, second])
    outcome = run_acquire(research_root, http)
    assert outcome.topix_pages == 2
    assert outcome.topix_observations == len(SESSIONS)


def test_reaching_the_frozen_page_cap_fails_closed(research_root) -> None:
    """20 page 上限に達したら truncation を否定できないので停止する。"""
    endless = {"data": topix_rows(SESSIONS[:1]), "pagination_key": "more"}
    http = FakeHttp(topix_pages=[endless])
    with pytest.raises(drv.ResearchAcquisitionError) as exc:
        run_acquire(research_root, http)
    assert exc.value.code == drv.RESULT_PAGINATION


def test_the_frozen_page_cap_is_not_modified() -> None:
    from src.intelligence.market import jquants_v2

    source = Path(jquants_v2.__file__).read_text(encoding="utf-8")
    assert "for _page in range(20):" in source
    assert drv.PROVIDER_PAGE_CAP == 20


# ---------------------------------------------------------------- data quality validation

def test_clean_acquisition_passes_every_check(research_root) -> None:
    outcome = run_acquire(research_root, FakeHttp())
    assert outcome.result == drv.RESULT_OK, outcome.checks
    assert outcome.topix_observations == len(SESSIONS)
    assert outcome.topix_earliest == SESSIONS[0][0]
    assert outcome.topix_latest == SESSIONS[-1][0]
    assert outcome.calendar_rows == len(SESSIONS) + len(NON_SESSIONS)
    assert all(v is True for v in outcome.checks.values()), outcome.checks


def test_duplicate_trading_dates_never_become_duplicate_observations(research_root) -> None:
    duplicated = SESSIONS + (SESSIONS[0],)
    http = FakeHttp(topix_pages=[{"data": topix_rows(duplicated)}])
    outcome = run_acquire(research_root, http)
    assert outcome.checks["no_duplicate_trading_date"] is True
    assert outcome.topix_observations == len(SESSIONS)


def test_missing_close_fails_validation(research_root) -> None:
    rows = topix_rows()
    rows[2]["C"] = ""
    http = FakeHttp(topix_pages=[{"data": rows}])
    outcome = run_acquire(research_root, http)
    assert outcome.result == drv.RESULT_VALIDATION_FAILED
    assert outcome.checks["no_missing_close"] is False
    assert outcome.checks["no_nonpositive_close"] is False


def test_unvalidated_calendar_divisions_fail_closed(research_root) -> None:
    """観測がある日の HolDiv が営業日区分でなければカレンダーを信用しない。"""
    http = FakeHttp(calendar_pages=[{"data": calendar_rows(division="9")}])
    outcome = run_acquire(research_root, http)
    assert outcome.result == drv.RESULT_VALIDATION_FAILED
    assert outcome.checks["calendar_validated"] is False


def test_session_gap_is_detected(research_root) -> None:
    """カレンダー上の営業日に TOPIX 行が無ければ gap として落とす。"""
    http = FakeHttp(topix_pages=[{"data": topix_rows(SESSIONS[:-1])}])
    outcome = run_acquire(research_root, http)
    assert outcome.result == drv.RESULT_VALIDATION_FAILED
    assert outcome.checks["no_session_gap"] is False


def test_weekday_arithmetic_is_never_used() -> None:
    """営業日は取引カレンダーだけで決める（weekday fallback を持たない）。"""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "weekday" not in names
    assert "isoweekday" not in names


# ---------------------------------------------------------------- derived cross-check

def test_derived_return_matches_independent_decimal_recomputation(research_root) -> None:
    outcome = run_acquire(research_root, FakeHttp())
    assert outcome.checks["derived_return_matches_recomputation"] is True
    assert outcome.derived_return_1d == len(SESSIONS) - 1


def test_recomputation_uses_decimal_not_float(research_root) -> None:
    """期待値を Decimal で手計算し、driver が保存した derived と厳密一致させる。"""
    from src.intelligence.market.series_catalog import load_catalog, derived_series_id_for
    from src.intelligence.market.store import MarketBankStore

    run_acquire(research_root, FakeHttp())
    spec = load_catalog(CATALOG).get(drv.TOPIX_SERIES_ID)
    bank = MarketBankStore(research_root / "databank" / "market")
    try:
        stored = {o.trading_date: o.value
                  for o in bank.observations_for_series(derived_series_id_for(spec, "return_1d"))
                  if o.value is not None}
    finally:
        bank.close()
    expected = {}
    for (prev_day, prev_close), (day, close) in zip(SESSIONS, SESSIONS[1:]):
        prev_value, value = Decimal(prev_close), Decimal(close)
        expected[day] = ((value - prev_value) / prev_value * Decimal(100)).quantize(
            Decimal("0.000001"))
    assert stored == expected


def test_synthetic_source_contamination_is_checked(research_root) -> None:
    outcome = run_acquire(research_root, FakeHttp())
    assert outcome.checks["no_synthetic_source"] is True
    assert outcome.checks["provider_is_jquants_v2"] is True


# ---------------------------------------------------------------- production isolation

def test_no_legacy_or_publication_or_governance_dependency() -> None:
    imports = imported_modules()
    source = executable_source()
    forbidden_modules = (
        "analysis", "investment_journal", "notifiers", "main",
        "reports", "pages_parallel", "delivery", "market_signal", "morning_brief",
        "decision", "formal_review", "shadow_review", "evaluation", "corpus",
        "corpus_research", "replay",
    )
    for name in imports:
        for forbidden in forbidden_modules:
            assert forbidden not in name, (name, forbidden)
    for forbidden in ("pages-site", "upload-pages-artifact", "deploy-pages",
                      ".github", "workflows", "decisions.jsonl", "patterns.jsonl"):
        assert forbidden not in source, forbidden


def test_no_compass_dna_write() -> None:
    source = executable_source()
    for forbidden in ("knowledge/compass_dna", "market_rules.yaml", "market_principles"):
        assert forbidden not in source, forbidden


def test_no_production_data_root_fallback() -> None:
    """`data_root()` を読まない＝暗黙の production fallback を持たない。"""
    imports = imported_modules()
    assert not any("paths" in name for name in imports)
    # 関数呼び出しとしての `data_root(` が無いこと（check 名の部分一致は拾わない）
    assert "data_root(" not in executable_source()
    assert "market_bank_root(" not in executable_source()


def test_driver_is_not_reachable_from_the_production_runtime() -> None:
    """production entry point 3 本は `predictions` を import しない。"""
    entrypoints = (
        REPO_ROOT / "src" / "intelligence" / "market" / "pilot_runner.py",
        REPO_ROOT / "src" / "intelligence" / "reports" / "delivery_pilot.py",
        REPO_ROOT / "src" / "intelligence" / "reports" / "pages_parallel.py",
    )
    for path in entrypoints:
        assert not any("predictions" in name for name in imported_modules(path)), path
        assert "predictions" not in executable_source(path), path


def test_acquisition_metadata_carries_provenance_without_secrets(research_root) -> None:
    outcome = run_acquire(research_root, FakeHttp())
    payload = outcome.as_dict()
    assert payload["schema_version"] == drv.RESEARCH_SCHEMA_VERSION
    for key in ("requested_start", "requested_end", "topix_earliest", "topix_latest",
                "topix_observations", "calendar_rows", "topix_pages", "research_root"):
        assert key in payload, key
    blob = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("api_key", "x-api-key", "JQUANTS_API_KEY"):
        assert forbidden not in blob, forbidden


def test_api_version_is_recorded_and_is_v2(research_root) -> None:
    """provenance の API 版数は実際に使った provider から取る（決め打ちしない）。"""
    from src.intelligence.market.jquants_v2 import JQuantsV2TopixProvider

    outcome = run_acquire(research_root, FakeHttp())
    assert outcome.api_version == "v2"
    assert JQuantsV2TopixProvider().api_version == "v2"
    assert outcome.as_dict()["api_version"] == "v2"


def test_failed_acquisition_closes_its_stores(research_root) -> None:
    """失敗しても sqlite handle を開いたままにしない（Windows の lock を残さない）。"""
    endless = {"data": topix_rows(SESSIONS[:1]), "pagination_key": "more"}
    with pytest.raises(drv.ResearchAcquisitionError):
        run_acquire(research_root, FakeHttp(topix_pages=[endless]))
    # 同じ root を再度開けること（handle が残っていれば Windows では失敗する）
    from src.intelligence.market.store import MarketBankStore

    reopened = MarketBankStore(research_root / "databank" / "market")
    reopened.close()


def test_forbidden_segments_match_the_frozen_list() -> None:
    """拒否する path 断片は監督者が列挙したものだけ（勝手に広げない）。"""
    assert drv.FORBIDDEN_PATH_PARTS == (
        ("data", "vnext"), ("output",), ("docs",), ("knowledge",), (".git",))
