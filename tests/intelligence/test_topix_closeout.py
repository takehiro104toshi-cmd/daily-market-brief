"""P2-G.1 TOPIX CREDENTIALED LIVE CLOSEOUT のオフラインテスト。

監督者指定の最低テスト項目を網羅する:
credential missing graceful stop / secret redaction / auth failure /
auth success fixture / TOPIX schema / TOPIX index identity /
ETF・futures rejection / historical ingestion / freshness calculation /
delayed data blocking / current data acceptance / QA / persistence /
latest query / NT ratio / NT ratio missing input / gap state transition
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.evidence_qa.policy import MARKET_OBSERVATION_V1
from src.intelligence.market.backfill import MarketBackfillEngine
from src.intelligence.market.jquants_topix import (
    ACCEPTED_ENV_VARS,
    METHOD_ID_TOKEN,
    METHOD_MAIL_PASSWORD,
    METHOD_MISSING,
    METHOD_REFRESH_TOKEN,
    EnvCredentialResolver,
    JQuantsTopixProvider,
    Secret,
    credential_status,
    scrub,
    validate_topix_payload,
)
from src.intelligence.market.persistence_check import check as persistence_check
from src.intelligence.market.series_catalog import load_catalog
from src.intelligence.market.store import MarketBankStore, SqliteMarketIndex
from src.intelligence.market.topix_freshness import (
    CURRENT_USABLE,
    DELAYED_NOT_CURRENT,
    G10_BLOCKED,
    G10_HISTORICAL_ONLY,
    G10_PARTIAL,
    G10_RESOLVED,
    NO_DATA,
    TOPIX_SERIES_ID,
    TopixFreshness,
    access_requirement_report,
    evaluate_topix_freshness,
    g10_state,
)

from .market_fixtures import StubTransport

CATALOG = load_catalog(Path("knowledge/market_series/core_series.yaml"))
TOPIX_SPEC = CATALOG.get(TOPIX_SERIES_ID)
NIKKEI_SERIES_ID = "index:nikkei225.close.closing.tokyo"

SECRET_TOKEN = "s3cr3t-refresh-token-value"
SECRET_PASSWORD = "s3cr3t-password-value"
ID_TOKEN = "id-token-value-abc"


# ---------------------------------------------------------------- fixtures

def sessions(count: int, *, end: date = date(2026, 8, 28)):
    """endから遡る平日（土日除外）をcount営業日分、昇順で返す。"""
    days = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def topix_payload(days, *, base=Decimal("2700")):
    rows = [{"Date": d.isoformat(),
             "Open": str(base + i), "High": str(base + i + 5),
             "Low": str(base + i - 5), "Close": str(base + i)}
            for i, d in enumerate(days)]
    return {"topix": rows}


def nikkei_csv(days, *, base=39000):
    lines = ["Date,Open,High,Low,Close,Volume"]
    for i, d in enumerate(days):
        close = base + i * 10
        lines.append(f"{d.isoformat()},{close},{close + 50},{close - 50},{close},1000")
    return ("\n".join(lines) + "\n").encode()


def jquants_http(payload_by_page, *, auth_user_status=200, auth_refresh_status=200,
                 calls=None):
    """auth 2段階＋TOPIX endpointのstub http_fn。callsへ全リクエストを記録。"""
    log = calls if calls is not None else []

    def http_fn(url, method, headers, body):
        log.append({"url": url, "method": method, "headers": dict(headers),
                    "body": body})
        if url.endswith("/token/auth_user"):
            if auth_user_status != 200:
                return auth_user_status, b'{"message":"Forbidden"}'
            return 200, json.dumps({"refreshToken": SECRET_TOKEN}).encode()
        if "/token/auth_refresh" in url:
            if auth_refresh_status != 200:
                return auth_refresh_status, b'{"message":"Unauthorized"}'
            return 200, json.dumps({"idToken": ID_TOKEN}).encode()
        for key, page in payload_by_page.items():
            if (key == "" and "pagination_key" not in url) or (
                    key and f"pagination_key={key}" in url):
                return 200, json.dumps(page).encode()
        raise AssertionError(f"unexpected url {url}")

    return http_fn, log


def fetch_topix(provider, *, start=date(2026, 7, 1), end=date(2026, 8, 28)):
    return provider.fetch_daily_history(TOPIX_SPEC, start=start, end=end)


# ================================================================ STEP 1

class TestCredentialPresence:
    def test_missing_reports_method_and_accepted_names_only(self):
        status = credential_status(EnvCredentialResolver({}))
        assert status["present"] is False
        assert status["auth_method"] == METHOD_MISSING
        assert status["source_env_names"] == []
        assert set(status["accepted_env_names"]) == set(ACCEPTED_ENV_VARS)

    def test_missing_credential_makes_no_network_call(self):
        http_fn, calls = jquants_http({"": topix_payload(sessions(3))})
        provider = JQuantsTopixProvider(http_fn, env={})
        result = fetch_topix(provider)
        assert result.error_kind == "no_credentials"
        assert not result.ok
        assert calls == []  # credential無しでretryしない（1回も叩かない）
        # 報告には受理env名のみ（値は存在しないので出しようがない）
        assert "JQUANTS_" in result.error_detail

    @pytest.mark.parametrize("env,expected,sources", [
        ({"JQUANTS_ID_TOKEN": ID_TOKEN}, METHOD_ID_TOKEN, ("JQUANTS_ID_TOKEN",)),
        ({"JQUANTS_REFRESH_TOKEN": SECRET_TOKEN}, METHOD_REFRESH_TOKEN,
         ("JQUANTS_REFRESH_TOKEN",)),
        ({"JQUANTS_MAIL": "u@example.com", "JQUANTS_PASSWORD": SECRET_PASSWORD},
         METHOD_MAIL_PASSWORD, ("JQUANTS_MAIL", "JQUANTS_PASSWORD")),
    ])
    def test_resolver_methods(self, env, expected, sources):
        resolution = EnvCredentialResolver(env).resolve()
        assert resolution.method == expected
        assert resolution.present
        assert resolution.source_names == sources

    def test_id_token_takes_precedence_and_skips_auth_calls(self):
        http_fn, calls = jquants_http({"": topix_payload(sessions(3))})
        provider = JQuantsTopixProvider(http_fn, env={
            "JQUANTS_ID_TOKEN": ID_TOKEN, "JQUANTS_REFRESH_TOKEN": SECRET_TOKEN})
        result = fetch_topix(provider)
        assert result.ok
        assert all("/token/" not in c["url"] for c in calls)  # 認証往復ゼロ
        assert provider.last_auth_method == METHOD_ID_TOKEN

    def test_refresh_token_skips_auth_user(self):
        http_fn, calls = jquants_http({"": topix_payload(sessions(3))})
        provider = JQuantsTopixProvider(
            http_fn, env={"JQUANTS_REFRESH_TOKEN": SECRET_TOKEN})
        assert fetch_topix(provider).ok
        assert not any("auth_user" in c["url"] for c in calls)
        assert any("auth_refresh" in c["url"] for c in calls)


# ================================================================ 秘密の安全性

class TestCredentialSafety:
    def test_secret_wrapper_never_prints_value(self):
        secret = Secret(SECRET_TOKEN)
        assert SECRET_TOKEN not in repr(secret)
        assert SECRET_TOKEN not in str(secret)
        assert SECRET_TOKEN not in f"{secret}"
        assert secret.reveal() == SECRET_TOKEN

    def test_scrub_removes_known_secrets(self):
        text = f"boom at ?refreshtoken={SECRET_TOKEN}&x=1"
        assert SECRET_TOKEN not in scrub(text, (SECRET_TOKEN,))
        assert "***" in scrub(text, (SECRET_TOKEN,))

    def test_exception_message_containing_token_is_scrubbed(self):
        def http_fn(url, method, headers, body):
            # 実URLを含む例外（urllibが投げ得る形）を模す
            raise RuntimeError(f"HTTP failure for {url}")

        provider = JQuantsTopixProvider(
            http_fn, env={"JQUANTS_REFRESH_TOKEN": SECRET_TOKEN})
        result = fetch_topix(provider)
        assert result.error_kind == "auth_error"
        assert SECRET_TOKEN not in result.error_detail
        assert "***" in result.error_detail

    def test_persisted_url_and_raw_body_carry_no_credentials(self, tmp_path):
        http_fn, _calls = jquants_http({"": topix_payload(sessions(3))})
        provider = JQuantsTopixProvider(http_fn, env={
            "JQUANTS_MAIL": "u@example.com", "JQUANTS_PASSWORD": SECRET_PASSWORD})
        result = fetch_topix(provider)
        assert result.ok
        for secret in (SECRET_PASSWORD, SECRET_TOKEN, ID_TOKEN):
            assert secret not in result.url
            assert secret.encode() not in result.body       # raw payloadへ混入しない
            assert secret not in result.error_detail
        # FetchAttempt/RawItemへも入らない（永続化経路の実検証）
        store = MarketBankStore(tmp_path / "market")
        store.record_provider_fetch(result, "fetch_test")
        for attempt in store.raw.iter_attempts():
            assert all(s not in attempt.url for s in (SECRET_PASSWORD, ID_TOKEN))
        for item in store.raw.iter_raw_items():
            assert all(s not in item.locator for s in (SECRET_PASSWORD, ID_TOKEN))
        store.close()

    def test_auth_response_bodies_are_not_stored(self):
        http_fn, _calls = jquants_http({"": topix_payload(sessions(3))})
        provider = JQuantsTopixProvider(
            http_fn, env={"JQUANTS_REFRESH_TOKEN": SECRET_TOKEN})
        result = fetch_topix(provider)
        assert b"idToken" not in result.body and b"refreshToken" not in result.body


class TestAuthOutcomes:
    def test_auth_user_failure_is_reported_without_secrets(self):
        http_fn, _calls = jquants_http({"": topix_payload(sessions(3))},
                                       auth_user_status=403)
        provider = JQuantsTopixProvider(http_fn, env={
            "JQUANTS_MAIL": "u@example.com", "JQUANTS_PASSWORD": SECRET_PASSWORD})
        result = fetch_topix(provider)
        assert result.error_kind == "auth_error"
        assert "auth_user_http_403" in result.error_detail
        assert SECRET_PASSWORD not in result.error_detail

    def test_auth_refresh_failure(self):
        http_fn, _calls = jquants_http({"": topix_payload(sessions(3))},
                                       auth_refresh_status=401)
        provider = JQuantsTopixProvider(
            http_fn, env={"JQUANTS_REFRESH_TOKEN": SECRET_TOKEN})
        result = fetch_topix(provider)
        assert result.error_kind == "auth_error"
        assert "auth_refresh_http_401" in result.error_detail

    def test_auth_success_fixture_yields_records(self):
        days = sessions(5)
        http_fn, calls = jquants_http({"": topix_payload(days)})
        provider = JQuantsTopixProvider(http_fn, env={
            "JQUANTS_MAIL": "u@example.com", "JQUANTS_PASSWORD": SECRET_PASSWORD})
        result = fetch_topix(provider)
        assert result.ok and len(result.records) == 5
        assert any(c["headers"].get("Authorization") == f"Bearer {ID_TOKEN}"
                   for c in calls)


# ================================================================ schema / identity

class TestTopixSchemaAndIdentity:
    def test_valid_payload_passes(self):
        kind, issues = validate_topix_payload(topix_payload(sessions(2)))
        assert kind == "" and issues == ()

    @pytest.mark.parametrize("payload,expected", [
        ({"data": []}, "missing_topix_key"),
        ({"topix": "notalist"}, "topix_not_array"),
        ([], "payload_not_object"),
    ])
    def test_schema_errors(self, payload, expected):
        kind, issues = validate_topix_payload(payload)
        assert kind == "schema_error"
        assert any(expected in i for i in issues)

    @pytest.mark.parametrize("row", [
        {"Date": "2026-08-28", "Close": "2700", "Code": "1306"},           # ETF銘柄
        {"Date": "2026-08-28", "Close": "2700", "NetAssetValue": "2699"},  # ETF NAV
        {"Date": "2026-08-28", "Close": "2700", "ContractMonth": "2026-09"},  # 先物
        {"Date": "2026-08-28", "Close": "2700", "SettlementPrice": "2701"},
    ])
    def test_etf_and_futures_payloads_are_rejected(self, row):
        kind, issues = validate_topix_payload({"topix": [row]})
        assert kind == "identity_mismatch"
        assert any("non_index_fields" in i for i in issues)

    def test_provider_refuses_identity_mismatch_payload(self):
        bad = {"topix": [{"Date": "2026-08-28", "Close": "2700", "Code": "1306"}]}
        http_fn, _calls = jquants_http({"": bad})
        provider = JQuantsTopixProvider(http_fn, env={"JQUANTS_ID_TOKEN": ID_TOKEN})
        result = fetch_topix(provider)
        assert result.error_kind == "identity_mismatch"
        assert result.records == ()   # 1行も取り込まない

    def test_catalog_topix_identity_is_index_points(self):
        assert TOPIX_SPEC.unit == "index"
        assert TOPIX_SPEC.series.instrument_id == "index:topix"
        assert TOPIX_SPEC.preferred_source == "jquants"
        # ETF/先物symbolを持たない
        assert all("1306" not in sym and ".T" not in sym
                   for _pid, sym in TOPIX_SPEC.provider_symbols)


# ================================================================ ingestion / QA

def build_engine(tmp_path, *, topix_days, nikkei_days, env=None):
    """TOPIX（J-Quants stub）＋日経（Stooq stub）のengine。"""
    http_fn, _calls = jquants_http({"": topix_payload(topix_days)})
    providers = {
        "jquants": JQuantsTopixProvider(
            http_fn, env=env or {"JQUANTS_ID_TOKEN": ID_TOKEN}),
        "stooq": __import__(
            "src.intelligence.market.providers", fromlist=["StooqDailyHistoryProvider"]
        ).StooqDailyHistoryProvider(StubTransport({
            "s=^nkx": (200, nikkei_csv(nikkei_days))})),
    }
    from src.intelligence.core.paths import market_bank_root

    return MarketBackfillEngine(MarketBankStore(market_bank_root(tmp_path)), CATALOG,
                                providers, MARKET_OBSERVATION_V1)


class TestHistoricalIngestion:
    SERIES = (TOPIX_SERIES_ID, NIKKEI_SERIES_ID)

    def test_full_pipeline_qa_persistence_latest_and_nt_ratio(self, tmp_path):
        days = sessions(30)
        engine = build_engine(tmp_path, topix_days=days, nikkei_days=days)
        run = engine.run(start=days[0], end=days[-1], series_ids=self.SERIES)
        by_id = {r.series_id: r for r in run.results}
        assert by_id[TOPIX_SERIES_ID].status == "success"
        assert by_id[TOPIX_SERIES_ID].observations_added == 30  # ≥25DMA要件

        # --- Decimal / unit / trading_date / as_of
        rows = engine.store.index.query(series_id=TOPIX_SERIES_ID, kind="raw",
                                        limit=1000)
        assert len(rows) == 30
        latest = engine.store.index.latest_trading_session(TOPIX_SERIES_ID)
        obs = engine.store.normalized.get_observation(latest["observation_id"])
        assert obs.unit == "index"
        assert isinstance(obs.value, Decimal)
        assert obs.trading_date == days[-1].isoformat()
        assert obs.as_of.isoformat() == f"{days[-1].isoformat()}T06:30:00+00:00"
        assert obs.source_id == "jquants"

        # --- QA（provider経路provenanceでACCEPT）
        decisions = {a.decision.value for a in engine.store.qa.iter_assessments()
                     if a.record_id in {r["observation_id"] for r in rows}}
        assert decisions == {"accept"}

        # --- NT ratio（同一trading_dateの現物指数close同士のみ・provenance必須）
        nt = [o for o in engine.store.normalized.iter_observations()
              if o.series_id == "index:nikkei225_topix.nt_ratio.derived_metric"]
        assert len(nt) == 30
        for row in nt:
            assert len(row.inputs) == 2                      # Nikkei + TOPIX
            assert row.calculation_method == "nt_ratio:1.0.0"  # method:version
            assert row.unit == "x"
        sample = max(nt, key=lambda o: o.trading_date)
        nikkei_obs = engine.store.index.latest_trading_session(NIKKEI_SERIES_ID)
        assert sample.inputs == (nikkei_obs["observation_id"], obs.observation_id)
        expected = (Decimal(nikkei_obs["value"]) / obs.value).quantize(
            Decimal("0.000001"))
        assert sample.value == expected

        # --- 別プロセス相当の再構築（canonicalのみからlatest一致）
        engine.store.close()
        result = persistence_check(tmp_path, [TOPIX_SERIES_ID])
        assert result["canonical_observations"] > 0
        assert result["index_rebuilt_observations"] == result["canonical_observations"]
        assert result["latest"][TOPIX_SERIES_ID]["observation_id"] == obs.observation_id

    def test_nt_ratio_not_generated_for_missing_input_dates(self, tmp_path):
        nikkei_days = sessions(30)
        topix_days = nikkei_days[:-3]          # TOPIXだけ直近3営業日欠落
        engine = build_engine(tmp_path, topix_days=topix_days, nikkei_days=nikkei_days)
        engine.run(start=nikkei_days[0], end=nikkei_days[-1], series_ids=self.SERIES)
        nt_dates = {o.trading_date for o in engine.store.normalized.iter_observations()
                    if o.series_id == "index:nikkei225_topix.nt_ratio.derived_metric"}
        assert nt_dates == {d.isoformat() for d in topix_days}
        for missing in nikkei_days[-3:]:
            assert missing.isoformat() not in nt_dates  # 片側欠落日は生成しない


# ================================================================ freshness

def index_with(tmp_path, *, topix_days=(), nikkei_days=()):
    """観測をSQLite indexへ直接入れる軽量fixture（freshness判定の単体検証）。"""
    from src.intelligence.market.ingest import as_of_for
    from src.intelligence.market.model import Observation, ObservationKind

    index = SqliteMarketIndex(tmp_path / "market.sqlite3")
    observations = []
    for tag, series_id, days, spec in (("topix", TOPIX_SERIES_ID, topix_days, TOPIX_SPEC),
                                       ("nikkei", NIKKEI_SERIES_ID, nikkei_days,
                                        CATALOG.get(NIKKEI_SERIES_ID))):
        for i, day in enumerate(days):
            observations.append(Observation(
                observation_id=f"obs_{tag}_{day.isoformat()}",
                entity_id=spec.series.instrument_id, metric=spec.series.metric,
                value=Decimal(2700 + i), unit=spec.unit,
                as_of=as_of_for(spec, day.isoformat()), kind=ObservationKind.RAW,
                series_id=series_id, trading_date=day.isoformat(),
                source_id="test"))
    index.index_observations(observations)
    return index


NOW = datetime(2026, 8, 29, 21, 0, tzinfo=timezone.utc)  # 8/30 JST 6時


class TestFreshness:
    def test_no_data(self, tmp_path):
        index = index_with(tmp_path)
        result = evaluate_topix_freshness(index, now=NOW)
        assert result.verdict == NO_DATA
        assert result.reason_codes == ("no_topix_observations",)
        assert result.morning_usable is False

    def test_current_data_accepted_when_matching_reference_session(self, tmp_path):
        days = sessions(30)
        index = index_with(tmp_path, topix_days=days, nikkei_days=days)
        result = evaluate_topix_freshness(index, now=NOW)
        assert result.verdict == CURRENT_USABLE
        assert result.gap_sessions == 0
        assert result.latest_trading_date == days[-1].isoformat()
        assert result.history_rows == 30 and result.history_ok
        assert result.morning_usable is True

    def test_delayed_data_blocked_against_reference_session(self, tmp_path):
        nikkei_days = sessions(40)
        topix_days = nikkei_days[:-12]      # 12営業日遅延（Free plan相当の遅延）
        index = index_with(tmp_path, topix_days=topix_days, nikkei_days=nikkei_days)
        result = evaluate_topix_freshness(index, now=NOW)
        assert result.verdict == DELAYED_NOT_CURRENT
        assert result.gap_sessions == 12
        assert "behind_reference_tokyo_session" in result.reason_codes
        assert result.history_ok          # 履歴はあるが当日利用不可
        assert result.morning_usable is False

    def test_lag_days_computed_from_run_time(self, tmp_path):
        days = sessions(30)
        index = index_with(tmp_path, topix_days=days, nikkei_days=days)
        result = evaluate_topix_freshness(index, now=NOW)
        assert result.lag_days == (NOW.date() - days[-1]).days

    def test_without_reference_series_uses_lag_threshold_and_says_so(self, tmp_path):
        days = sessions(30)
        index = index_with(tmp_path, topix_days=days)   # 基準系列なし
        result = evaluate_topix_freshness(index, now=NOW)
        assert result.verdict == CURRENT_USABLE
        assert "reference_series_unavailable" in result.reason_codes
        assert "lag_threshold_basis_only" in result.reason_codes
        assert result.gap_sessions == -1

    def test_without_reference_series_stale_data_is_delayed(self, tmp_path):
        days = sessions(30, end=date(2026, 7, 31))      # 1ヶ月前まで
        index = index_with(tmp_path, topix_days=days)
        result = evaluate_topix_freshness(index, now=NOW)
        assert result.verdict == DELAYED_NOT_CURRENT
        assert "reference_series_unavailable" in result.reason_codes


# ================================================================ G10状態遷移

def freshness(verdict, *, rows=30, codes=()):
    return TopixFreshness(verdict=verdict, history_rows=rows, reason_codes=codes)


class TestG10StateTransition:
    def test_credential_missing_is_partially_resolved_not_blocked(self):
        state, codes = g10_state(freshness(NO_DATA, rows=0),
                                 credential_present=False)
        assert state == G10_PARTIAL
        assert "topix_credential_missing" in codes

    def test_credential_present_but_no_data_is_blocked(self):
        state, codes = g10_state(freshness(NO_DATA, rows=0), credential_present=True)
        assert state == G10_BLOCKED
        assert codes == ("topix_fetch_failed_with_credential",)

    def test_short_history_is_partially_resolved(self):
        state, codes = g10_state(freshness(CURRENT_USABLE, rows=10),
                                 credential_present=True)
        assert state == G10_PARTIAL
        assert "insufficient_history_for_25dma" in codes

    def test_delayed_data_is_historical_resolved_current_blocked(self):
        state, codes = g10_state(
            freshness(DELAYED_NOT_CURRENT, codes=("gap_sessions:12",)),
            credential_present=True)
        assert state == G10_HISTORICAL_ONLY
        assert "current_session_not_available" in codes
        assert "gap_sessions:12" in codes

    def test_current_usable_with_history_is_resolved(self):
        state, codes = g10_state(freshness(CURRENT_USABLE), credential_present=True)
        assert state == G10_RESOLVED
        assert {"live_authenticated_fetch", "history_ge_25dma",
                "current_session_available"} <= set(codes)

    def test_access_requirement_report_states_facts_and_forbids_proxy(self):
        # 監督者訂正: plan名を推測で断定しない（PLAN_CAPABILITY=UNVERIFIED）
        report = access_requirement_report(
            freshness(DELAYED_NOT_CURRENT, codes=("gap_sessions:12",)))
        assert "未確定" in str(report["required_access_level"])
        assert "1306" in report["no_proxy_fallback"]
        assert report["observed_verdict"] == DELAYED_NOT_CURRENT

    def test_resolved_report_does_not_demand_upgrade(self):
        report = access_requirement_report(freshness(CURRENT_USABLE))
        assert "要件充足" in str(report["required_access_level"])


# ================================================================ P2-G.1 レビュー反映

from src.intelligence.market.topix_freshness import (  # noqa: E402
    PLAN_CAPABILITY_UNVERIFIED,
)


class TestValidatedAuthMethod:
    """解決できた方式＝使える方式ではない。実API成功のみを検証済みとする。"""

    def test_not_validated_when_credentials_missing(self):
        http_fn, _calls = jquants_http({"": topix_payload(sessions(3))})
        provider = JQuantsTopixProvider(http_fn, env={})
        fetch_topix(provider)
        assert provider.last_auth_method == METHOD_MISSING
        assert provider.last_auth_method_validated == ""

    def test_not_validated_when_auth_fails(self):
        http_fn, _calls = jquants_http({"": topix_payload(sessions(3))},
                                       auth_refresh_status=401)
        provider = JQuantsTopixProvider(
            http_fn, env={"JQUANTS_REFRESH_TOKEN": SECRET_TOKEN})
        result = fetch_topix(provider)
        assert result.error_kind == "auth_error"
        assert provider.last_auth_method == METHOD_REFRESH_TOKEN
        assert provider.last_auth_method_validated == ""   # 断定しない

    def test_validated_only_after_successful_data_fetch(self):
        http_fn, _calls = jquants_http({"": topix_payload(sessions(3))})
        provider = JQuantsTopixProvider(
            http_fn, env={"JQUANTS_REFRESH_TOKEN": SECRET_TOKEN})
        assert fetch_topix(provider).ok
        assert provider.last_auth_method_validated == METHOD_REFRESH_TOKEN

    def test_credential_status_reports_unvalidated_by_default(self):
        status = credential_status(EnvCredentialResolver(
            {"JQUANTS_ID_TOKEN": ID_TOKEN}))
        assert status["present"] is True
        assert status["auth_method"] == METHOD_ID_TOKEN
        assert status["auth_method_validated"] == ""   # 実API成功まで空


class TestG10ResultStatesCandD:
    """監督者指定の結果状態 C（access不足）/ D（auth失敗）。"""

    def test_auth_failure_is_blocked_with_auth_failure_reason(self):
        state, codes = g10_state(freshness(NO_DATA, rows=0),
                                 credential_present=True,
                                 fetch_error_kind="auth_error")
        assert state == G10_BLOCKED
        assert "auth_failure" in codes

    @pytest.mark.parametrize("kind", ["no_data", "http_error", "identity_mismatch",
                                      "schema_error"])
    def test_dataset_unavailable_is_access_level_insufficient(self, kind):
        state, codes = g10_state(freshness(NO_DATA, rows=0),
                                 credential_present=True, fetch_error_kind=kind)
        assert state == G10_BLOCKED
        assert "access_level_insufficient" in codes
        assert f"error:{kind}" in codes

    def test_unknown_error_keeps_generic_reason(self):
        state, codes = g10_state(freshness(NO_DATA, rows=0),
                                 credential_present=True, fetch_error_kind="timeout")
        assert state == G10_BLOCKED
        assert "topix_fetch_failed_with_credential" in codes


class TestPlanCapabilityUnverified:
    """PLAN_CAPABILITY = UNVERIFIED（推測でtierを断定しない）。"""

    def test_report_marks_plan_capability_unverified(self):
        report = access_requirement_report(freshness(DELAYED_NOT_CURRENT))
        assert report["plan_capability"] == PLAN_CAPABILITY_UNVERIFIED
        assert report["plan_capability_evidence"]

    def test_report_does_not_assert_a_specific_plan_name(self):
        report = access_requirement_report(freshness(DELAYED_NOT_CURRENT))
        text = str(report["required_access_level"])
        assert "Light" not in text and "12週" not in text
        assert "未確定" in text

    def test_evidence_can_be_supplied_once_observed(self):
        report = access_requirement_report(
            freshness(DELAYED_NOT_CURRENT),
            plan_capability_evidence="live fetch: latest=2026-06-05 gap=12 sessions")
        assert "live fetch" in report["plan_capability_evidence"]

    def test_current_usable_report_states_requirement_met_by_measurement(self):
        report = access_requirement_report(freshness(CURRENT_USABLE))
        assert "実測" in str(report["required_access_level"])


# ================================================================ API Key方式（P2-G.1）

from src.intelligence.market.jquants_topix import (  # noqa: E402
    ENV_API_KEY,
    MECHANISM_AS_BEARER,
    MECHANISM_AS_REFRESH_TOKEN,
    METHOD_API_KEY,
)

API_KEY = "api-key-value-xyz"


def api_key_http(*, exchange_status=200, data_status=200, days=None, calls=None):
    """API Keyの搬送方式を切り替えられるstub（呼び出し回数も記録）。"""
    log = calls if calls is not None else []
    payload = topix_payload(days or sessions(3))

    def http_fn(url, method, headers, body):
        log.append({"url": url, "method": method, "headers": dict(headers)})
        if "/token/auth_refresh" in url:
            if exchange_status != 200:
                return exchange_status, b'{"message":"Forbidden"}'
            return 200, json.dumps({"idToken": ID_TOKEN}).encode()
        if data_status != 200:
            return data_status, b'{"message":"Forbidden"}'
        return 200, json.dumps(payload).encode()

    return http_fn, log


class TestApiKeyCredential:
    def test_resolver_accepts_api_key_env(self):
        resolution = EnvCredentialResolver({ENV_API_KEY: API_KEY}).resolve()
        assert resolution.method == METHOD_API_KEY
        assert resolution.source_names == (ENV_API_KEY,)
        assert resolution.present
        # 説明文へ値を出さない
        assert API_KEY not in resolution.detail

    def test_typed_credentials_take_precedence_over_untyped_api_key(self):
        resolution = EnvCredentialResolver({
            ENV_API_KEY: API_KEY, "JQUANTS_REFRESH_TOKEN": SECRET_TOKEN}).resolve()
        assert resolution.method == METHOD_REFRESH_TOKEN

    def test_api_key_exchanged_as_refresh_token_records_mechanism(self):
        http_fn, calls = api_key_http()
        provider = JQuantsTopixProvider(http_fn, env={ENV_API_KEY: API_KEY})
        result = fetch_topix(provider)
        assert result.ok
        assert provider.last_auth_method == METHOD_API_KEY
        assert provider.last_auth_method_validated == METHOD_API_KEY
        assert provider.last_mechanism_validated == MECHANISM_AS_REFRESH_TOKEN
        assert any(c["headers"].get("Authorization") == f"Bearer {ID_TOKEN}"
                   for c in calls)

    def test_api_key_falls_back_to_bearer_and_records_mechanism(self):
        http_fn, calls = api_key_http(exchange_status=403)
        provider = JQuantsTopixProvider(http_fn, env={ENV_API_KEY: API_KEY})
        result = fetch_topix(provider)
        assert result.ok
        assert provider.last_mechanism_validated == MECHANISM_AS_BEARER
        assert any(c["headers"].get("Authorization") == f"Bearer {API_KEY}"
                   for c in calls)

    def test_api_key_rejected_by_all_mechanisms_is_bounded_auth_error(self):
        http_fn, calls = api_key_http(exchange_status=403, data_status=403)
        provider = JQuantsTopixProvider(http_fn, env={ENV_API_KEY: API_KEY})
        result = fetch_topix(provider)
        assert result.error_kind == "auth_error"
        assert "api_key_mechanism_not_accepted" in result.error_detail
        assert MECHANISM_AS_REFRESH_TOKEN in result.error_detail
        assert MECHANISM_AS_BEARER in result.error_detail
        # 上限2回（交換1＋data 1）——総当たりしない
        assert len(calls) == 2
        assert provider.last_auth_method_validated == ""   # 断定しない
        assert provider.last_mechanism_validated == ""

    def test_api_key_value_never_appears_in_error_or_locator(self):
        http_fn, _calls = api_key_http(exchange_status=403, data_status=403)
        provider = JQuantsTopixProvider(http_fn, env={ENV_API_KEY: API_KEY})
        result = fetch_topix(provider)
        assert API_KEY not in result.error_detail
        assert API_KEY not in result.url
        assert API_KEY.encode() not in result.body

    def test_api_key_auth_failure_maps_to_g10_blocked(self):
        state, codes = g10_state(freshness(NO_DATA, rows=0),
                                 credential_present=True,
                                 fetch_error_kind="auth_error")
        assert state == G10_BLOCKED
        assert "auth_failure" in codes
