"""P2-G.2 J-Quants V1→V2 migration のオフラインテスト。

監督者指定の最低テスト項目:
V2 endpoint construction / V2 auth header / API key never leaked /
V2 response parse / TOPIX identity guard / historical ingestion /
freshness / G10 reassessment / legacy V1 endpoint not used /
credential missing graceful stop。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.intelligence.evidence_qa.policy import MARKET_OBSERVATION_V1
from src.intelligence.market.backfill import MarketBackfillEngine
from src.intelligence.market.jquants_v2 import (
    ACCEPTED_ENV_VARS,
    API_VERSION,
    AUTH_HEADER,
    CAUSE_API_VERSION_MISMATCH,
    CAUSE_CREDENTIAL_REJECTED,
    CAUSE_PLAN_NOT_ENTITLED,
    ENV_API_KEY,
    JQUANTS_V2_BASE,
    METHOD_API_KEY_HEADER,
    METHOD_MISSING,
    TOPIX_PATH,
    JQuantsV2CredentialResolver,
    JQuantsV2TopixProvider,
    classify_v2_failure,
    credential_status_v2,
    scrub_response_text,
    validate_topix_v2_payload,
)
from src.intelligence.market.persistence_check import check as persistence_check
from src.intelligence.market.series_catalog import load_catalog
from src.intelligence.market.store import MarketBankStore
from src.intelligence.market.topix_freshness import (
    CAUSE_LEGACY_V1_ENDPOINT,
    G10_BLOCKED,
    G10_PARTIAL,
    NO_DATA,
    PLAN_CAPABILITY_EVIDENCE_TOPIX_TIER,
    PLAN_CAPABILITY_UNVERIFIED,
    PLAN_CAPABILITY_VERIFIED,
    TOPIX_SERIES_ID,
    TopixFreshness,
    access_requirement_report,
    g10_state,
)

from .market_fixtures import StubTransport

CATALOG = load_catalog(Path("knowledge/market_series/core_series.yaml"))
TOPIX_SPEC = CATALOG.get(TOPIX_SERIES_ID)
NIKKEI_SERIES_ID = "index:nikkei225.close.closing.tokyo"

API_KEY = "TEST-ONLY-SYNTHETIC-JQUANTS-V2-KEY"


# ---------------------------------------------------------------- fixtures

def sessions(count: int, *, end: date = date(2026, 8, 28)):
    days = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def v2_payload(days, *, base=Decimal("2700"), date_fmt="iso", pagination_key=""):
    """V2応答（{"data": [...]}・四本値はV2短縮名 O/H/L/C）。"""
    rows = []
    for i, day in enumerate(days):
        stamp = day.isoformat() if date_fmt == "iso" else day.strftime("%Y%m%d")
        rows.append({"Date": stamp, "O": str(base + i), "H": str(base + i + 5),
                     "L": str(base + i - 5), "C": str(base + i)})
    payload = {"data": rows}
    if pagination_key:
        payload["pagination_key"] = pagination_key
    return payload


def nikkei_csv(days, *, base=39000):
    lines = ["Date,Open,High,Low,Close,Volume"]
    for i, day in enumerate(days):
        close = base + i * 10
        lines.append(f"{day.isoformat()},{close},{close + 50},{close - 50},{close},1000")
    return ("\n".join(lines) + "\n").encode()


def v2_http(payload_by_page, *, status=200, error_body=b'{"message":"Forbidden"}',
            calls=None):
    log = calls if calls is not None else []

    def http_fn(url, method, headers, body):
        log.append({"url": url, "method": method, "headers": dict(headers)})
        if status != 200:
            return status, error_body
        for key, page in payload_by_page.items():
            if (key == "" and "pagination_key" not in url) or (
                    key and f"pagination_key={key}" in url):
                return 200, json.dumps(page).encode()
        raise AssertionError(f"unexpected url {url}")

    return http_fn, log


def provider(payload_by_page=None, *, env=None, **kwargs):
    http_fn, log = v2_http(payload_by_page or {"": v2_payload(sessions(3))}, **kwargs)
    p = JQuantsV2TopixProvider(
        http_fn, env={ENV_API_KEY: API_KEY} if env is None else env)
    return p, log


def fetch(p, *, start=date(2026, 7, 1), end=date(2026, 8, 28)):
    return p.fetch_daily_history(TOPIX_SPEC, start=start, end=end)


# ============================================== STEP 1-2: credential / auth

class TestV2Credential:
    def test_only_api_key_env_accepted_v1_names_rejected(self):
        """V1のenv名をV2の既定にしない（旧仕様を推測でV2へ持ち込まない）。"""
        v1_env = {"JQUANTS_MAIL": "a@example.com", "JQUANTS_PASSWORD": "p",
                  "JQUANTS_REFRESH_TOKEN": "r", "JQUANTS_ID_TOKEN": "i"}
        resolution = JQuantsV2CredentialResolver(v1_env).resolve()
        assert resolution.method == METHOD_MISSING
        assert resolution.present is False
        assert ACCEPTED_ENV_VARS == (ENV_API_KEY,)

    def test_api_key_resolves_to_header_method(self):
        status = credential_status_v2(JQuantsV2CredentialResolver({ENV_API_KEY: API_KEY}))
        assert status["present"] is True
        assert status["auth_method"] == METHOD_API_KEY_HEADER
        assert status["api_version"] == API_VERSION == "v2"
        assert status["auth_header"] == AUTH_HEADER == "x-api-key"
        assert status["source_env_names"] == [ENV_API_KEY]
        # 解決できた方式＝検証済みではない（実API成功のみが検証）
        assert status["auth_method_validated"] == ""
        assert API_KEY not in json.dumps(status)

    def test_missing_credential_makes_no_network_call(self):
        p, log = provider(env={})
        result = fetch(p)
        assert result.error_kind == "no_credentials"
        assert log == []                       # 大量retryどころか1回も叩かない
        assert result.records == ()

    def test_series_without_jquants_symbol_reports_gap_without_crash(self):
        """symbol未定義の系列でもproviderは例外を投げずGAPとして返す。"""
        spec = CATALOG.get("index:growth250.close.closing.tokyo")
        assert spec.symbol_for("jquants") is None
        p, log = provider()
        result = p.fetch_daily_history(spec, start=date(2026, 7, 1),
                                       end=date(2026, 8, 28))
        assert result.error_kind == "no_symbol"
        assert result.url == ""
        assert log == []

    def test_api_key_sent_as_header_never_in_url(self):
        p, log = provider()
        result = fetch(p)
        assert result.error_kind == ""
        assert log[0]["headers"][AUTH_HEADER] == API_KEY
        assert "Authorization" not in log[0]["headers"]  # V1のBearer方式は使わない
        assert API_KEY not in log[0]["url"]
        assert API_KEY not in result.url        # 永続化locatorへ載せない
        assert p.last_auth_method_validated == METHOD_API_KEY_HEADER


class TestV2Endpoint:
    def test_uses_v2_topix_path_not_legacy_v1(self):
        p, log = provider()
        result = fetch(p, start=date(2026, 7, 1), end=date(2026, 8, 28))
        assert JQUANTS_V2_BASE == "https://api.jquants.com/v2"
        assert TOPIX_PATH == "/indices/bars/daily/topix"
        assert log[0]["url"].startswith(JQUANTS_V2_BASE + TOPIX_PATH)
        assert "/v1/" not in log[0]["url"]
        assert "/indices/topix?" not in log[0]["url"]   # V1の旧パス形状ではない
        assert "from=2026-07-01" in log[0]["url"] and "to=2026-08-28" in log[0]["url"]
        assert "/v2/" in result.url                     # provenance locatorに版数が残る
        assert p.api_version == "v2"

    def test_catalog_declares_v2_endpoint_and_identity_unchanged(self):
        info = CATALOG.providers["jquants"]
        assert info.api_version == "v2"
        assert info.endpoint_template == JQUANTS_V2_BASE + TOPIX_PATH
        assert "/v1/" not in info.endpoint_template
        # identityは維持（ETF/先物symbolはカタログに存在しない）
        assert TOPIX_SPEC.series_id == "index:topix.close.closing.tokyo"
        assert TOPIX_SPEC.preferred_source == "jquants"
        assert TOPIX_SPEC.symbol_for("jquants") == "topix"
        assert "1306" not in json.dumps(dict(TOPIX_SPEC.provider_symbols))

    def test_pagination_follows_v2_key(self):
        days = sessions(4)
        pages = {"": v2_payload(days[:2], pagination_key="P2"),
                 "P2": v2_payload(days[2:], base=Decimal("2800"))}
        p, log = provider(pages)
        result = fetch(p)
        assert len(log) == 2
        assert "pagination_key=P2" in log[1]["url"]
        assert len(result.records) == 4
        assert p.pages_fetched == 2
        assert any("paginated_response" in i for i in result.parse_issues)


# ============================================== secret safety

class TestSecretSafety:
    def test_error_response_echoing_key_fragment_is_redacted(self):
        """API Gatewayが値の断片/ダイジェストを返しても診断へ出さない。"""
        echo = json.dumps({"message": "Invalid key=value pair in Authorization "
                                      f"header: '{API_KEY[:16]}'"}).encode()
        p, _log = provider(status=403, error_body=echo)
        result = fetch(p)
        assert result.error_kind == "auth_error"
        assert API_KEY[:16] not in result.error_detail
        assert "redacted" in result.error_detail

    def test_sha256_digest_echo_is_stripped(self):
        text = ("Invalid key=value pair (missing equal-sign) in Authorization header "
                "(hashed with SHA-256 and encoded with Base64): 'AAAABBBBCCCC'")
        out = scrub_response_text(text, ())
        assert "AAAABBBBCCCC" not in out
        assert "digest-echo-removed" in out

    def test_secret_absent_from_persisted_provenance(self, tmp_path):
        from src.intelligence.core.paths import market_bank_root

        store = MarketBankStore(market_bank_root(tmp_path))
        p, _log = provider({"": v2_payload(sessions(3))})
        result = fetch(p)
        store.record_provider_fetch(result, "att_v2_1")
        blob = json.dumps([a.__dict__ for a in store.raw.iter_attempts()],
                          default=str)
        assert API_KEY not in blob
        assert API_KEY not in result.body.decode()
        store.close()


# ============================================== STEP 4: schema / identity

class TestV2Schema:
    def test_v2_envelope_and_short_field_names(self):
        kind, issues = validate_topix_v2_payload(v2_payload(sessions(2)))
        assert kind == "" and issues == ()

    def test_v1_envelope_is_not_accepted_as_v2(self):
        """V1形状（{"topix": [...]}）をV2として黙って受理しない。"""
        kind, issues = validate_topix_v2_payload(
            {"topix": [{"Date": "2026-08-28", "Close": "2700"}]})
        assert kind == "schema_error"
        assert issues and issues[0].startswith("missing_data_key")

    def test_etf_nav_row_rejected(self):
        payload = {"data": [{"Date": "2026-08-28", "C": "2700",
                             "NetAssetValue": "2701", "FundCode": "1306"}]}
        assert validate_topix_v2_payload(payload)[0] == "identity_mismatch"

    def test_futures_row_rejected(self):
        payload = {"data": [{"Date": "2026-08-28", "C": "2700",
                             "ContractMonth": "2026-09", "SettlementPrice": "2705"}]}
        assert validate_topix_v2_payload(payload)[0] == "identity_mismatch"

    def test_non_topix_index_code_rejected(self):
        payload = {"data": [{"Date": "2026-08-28", "C": "2700", "Code": "0028"}]}
        assert validate_topix_v2_payload(payload)[0] == "identity_mismatch"

    def test_topix_index_code_accepted(self):
        payload = {"data": [{"Date": "2026-08-28", "C": "2700", "Code": "0000"}]}
        assert validate_topix_v2_payload(payload)[0] == ""

    def test_topix_index_code_zero_padding_variants_accepted(self):
        """"0000" と 0 の表記差でTOPIXを取りこぼさない（誤検知の抑制）。"""
        for code in ("0000", 0, "0", " 0000 "):
            payload = {"data": [{"Date": "2026-08-28", "C": "2700", "Code": code}]}
            assert validate_topix_v2_payload(payload)[0] == "", code

    def test_securities_code_rejected_even_zero_padded(self):
        payload = {"data": [{"Date": "2026-08-28", "C": "2700", "Code": "1306"}]}
        assert validate_topix_v2_payload(payload)[0] == "identity_mismatch"

    def test_identity_mismatch_ingests_zero_rows(self):
        payload = {"data": [{"Date": "2026-08-28", "C": "2700", "FundCode": "1306"}]}
        p, _log = provider({"": payload})
        result = fetch(p)
        assert result.error_kind == "identity_mismatch"
        assert result.records == ()

    def test_both_date_formats_accepted(self):
        p, _log = provider({"": v2_payload(sessions(3), date_fmt="compact")})
        result = fetch(p)
        assert [r.trading_date for r in result.records] == [
            d.isoformat() for d in sessions(3)]

    def test_values_stay_string_tokens(self):
        p, _log = provider({"": v2_payload(sessions(2))})
        result = fetch(p)
        assert all(isinstance(r.close, str) for r in result.records)
        assert result.media_type == "application/json"
        assert p.observed_row_fields == ("C", "Date", "H", "L", "O")
        assert p.observed_top_keys == ("data",)


# ============================================== failure classification

class TestFailureClassification:
    def test_endpoint_not_exist_message_is_version_mismatch_not_credential(self):
        """V1 EOL後の403を「credential不正」と断定しない（監督者訂正）。"""
        message = ("The requested endpoint does not exist. Please check the URL, "
                   "HTTP method, and API version")
        assert classify_v2_failure(403, message) == CAUSE_API_VERSION_MISMATCH

    def test_plan_message_classified_as_entitlement(self):
        assert classify_v2_failure(
            403, "This API is not available on your subscription plan.") == (
            CAUSE_PLAN_NOT_ENTITLED)

    def test_bare_forbidden_is_credential_rejected(self):
        assert classify_v2_failure(403, "Forbidden") == CAUSE_CREDENTIAL_REJECTED

    def test_provider_records_cause_on_failure(self):
        body = json.dumps({"message": "The requested endpoint does not exist. "
                                      "Please check the URL, HTTP method, and API "
                                      "version"}).encode()
        p, _log = provider(status=403, error_body=body)
        result = fetch(p)
        assert result.error_kind == "auth_error"
        assert p.last_failure_cause == CAUSE_API_VERSION_MISMATCH
        assert "cause=api_version_mismatch" in result.error_detail


# ============================================== STEP 6-9: pipeline

def build_engine(tmp_path, *, topix_days, nikkei_days):
    from src.intelligence.core.paths import market_bank_root
    from src.intelligence.market.providers import StooqDailyHistoryProvider

    http_fn, _log = v2_http({"": v2_payload(topix_days)})
    providers = {
        "jquants": JQuantsV2TopixProvider(http_fn, env={ENV_API_KEY: API_KEY}),
        "stooq": StooqDailyHistoryProvider(
            StubTransport({"s=^nkx": (200, nikkei_csv(nikkei_days))})),
    }
    return MarketBackfillEngine(MarketBankStore(market_bank_root(tmp_path)), CATALOG,
                                providers, MARKET_OBSERVATION_V1)


class TestV2Pipeline:
    SERIES = (TOPIX_SERIES_ID, NIKKEI_SERIES_ID)

    def test_v2_history_flows_through_qa_canonical_and_nt_ratio(self, tmp_path):
        days = sessions(30)
        engine = build_engine(tmp_path, topix_days=days, nikkei_days=days)
        run = engine.run(start=days[0], end=days[-1], series_ids=self.SERIES)
        topix = {r.series_id: r for r in run.results}[TOPIX_SERIES_ID]
        assert topix.status == "success"
        assert topix.observations_added == 30            # ≥25DMA

        rows = engine.store.index.query(series_id=TOPIX_SERIES_ID, kind="raw",
                                        limit=1000)
        latest = engine.store.index.latest_trading_session(TOPIX_SERIES_ID)
        obs = engine.store.normalized.get_observation(latest["observation_id"])
        assert obs.unit == "index"
        assert isinstance(obs.value, Decimal)
        assert obs.trading_date == days[-1].isoformat()
        assert obs.as_of.isoformat() == f"{days[-1].isoformat()}T06:30:00+00:00"
        assert obs.source_id == "jquants"

        # provenance: RawItem locatorにV2版数が残る
        raw_items = [i for i in engine.store.raw.iter_raw_items()
                     if i.source_id == "jquants"]
        assert raw_items and all("/v2/" in i.locator for i in raw_items)
        assert all(API_KEY not in i.locator for i in raw_items)

        decisions = {a.decision.value for a in engine.store.qa.iter_assessments()
                     if a.record_id in {r["observation_id"] for r in rows}}
        assert decisions == {"accept"}

        nt = [o for o in engine.store.normalized.iter_observations()
              if o.series_id == "index:nikkei225_topix.nt_ratio.derived_metric"]
        assert len(nt) == 30
        sample = max(nt, key=lambda o: o.trading_date)
        nikkei_obs = engine.store.index.latest_trading_session(NIKKEI_SERIES_ID)
        assert sample.inputs == (nikkei_obs["observation_id"], obs.observation_id)
        assert len(sample.inputs) == 2

        engine.store.close()
        result = persistence_check(tmp_path, [TOPIX_SERIES_ID])
        assert result["index_rebuilt_observations"] == result["canonical_observations"]

    def test_freshness_current_when_matching_reference_session(self, tmp_path):
        from src.intelligence.market.topix_freshness import (
            CURRENT_USABLE, evaluate_topix_freshness)

        days = sessions(30)
        engine = build_engine(tmp_path, topix_days=days, nikkei_days=days)
        engine.run(start=days[0], end=days[-1], series_ids=self.SERIES)
        freshness = evaluate_topix_freshness(
            engine.store.index,
            now=datetime(2026, 8, 28, 23, 0, tzinfo=timezone.utc))
        assert freshness.verdict == CURRENT_USABLE
        assert freshness.history_ok
        state, reasons = g10_state(freshness, credential_present=True)
        assert state == "RESOLVED"
        assert "current_session_available" in reasons
        engine.store.close()


# ============================================== STEP 10: G10 reassessment

class TestG10Reassessment:
    NO_DATA_FRESHNESS = TopixFreshness(verdict=NO_DATA,
                                       reason_codes=("no_topix_observations",))

    def test_version_mismatch_is_not_reported_as_auth_failure(self):
        state, reasons = g10_state(
            self.NO_DATA_FRESHNESS, credential_present=True,
            fetch_error_kind="auth_error",
            failure_cause=CAUSE_API_VERSION_MISMATCH)
        assert state == G10_BLOCKED
        assert CAUSE_API_VERSION_MISMATCH in reasons
        assert "auth_failure" not in reasons

    def test_legacy_v1_endpoint_cause_supported(self):
        state, reasons = g10_state(
            self.NO_DATA_FRESHNESS, credential_present=True,
            fetch_error_kind="auth_error", failure_cause=CAUSE_LEGACY_V1_ENDPOINT)
        assert state == G10_BLOCKED
        assert CAUSE_LEGACY_V1_ENDPOINT in reasons

    def test_plan_not_entitled_maps_to_access_level(self):
        state, reasons = g10_state(
            self.NO_DATA_FRESHNESS, credential_present=True,
            fetch_error_kind="auth_error", failure_cause=CAUSE_PLAN_NOT_ENTITLED)
        assert state == G10_BLOCKED
        assert "access_level_insufficient" in reasons

    def test_credential_missing_still_partial(self):
        state, reasons = g10_state(self.NO_DATA_FRESHNESS, credential_present=False)
        assert state == G10_PARTIAL
        assert "topix_credential_missing" in reasons

    def test_plan_capability_entitlement_verified_window_still_unverified(self):
        report = access_requirement_report(
            self.NO_DATA_FRESHNESS,
            plan_capability_evidence=PLAN_CAPABILITY_EVIDENCE_TOPIX_TIER)
        assert report["plan_capability"] == PLAN_CAPABILITY_VERIFIED
        assert "Light" in str(report["plan_capability_evidence"])
        assert "UNVERIFIED" in str(report["plan_capability_scope"])
        assert report["topix_update_time_local"] == "16:30"
        assert "ETF" in str(report["no_proxy_fallback"])

    def test_plan_capability_unverified_without_evidence(self):
        report = access_requirement_report(self.NO_DATA_FRESHNESS)
        assert report["plan_capability"] == PLAN_CAPABILITY_UNVERIFIED
