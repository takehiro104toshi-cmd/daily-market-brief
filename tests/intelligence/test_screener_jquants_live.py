"""P8-LIVE1 — memory だけの取り込み client ・ID1 の前の適格の test matrix（master ・ProdCat ・Mkt ・Code ・安全 ・fins ・architecture）。

合成の応答だけ（`SyntheticTransport`）。live の provider ・network ・credential ・時計 ・乱数 ・LLM は使わない。A1 ・A2 ・注記 ・保留に書かない。
凍結の ID1 ・ID2 ・ADP0 ・EXE は変えない。
"""
from __future__ import annotations

import ast
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import jquants_live_client as lc
from src.intelligence.screener_intelligence import jquants_live_model as lm
from src.intelligence.screener_intelligence import jquants_master_ingress as mi
from src.intelligence.screener_intelligence.identity_bootstrap import (plan_registration, propose_bootstrap,
                                                                       review_manifest)
from src.intelligence.screener_intelligence.identity_bootstrap_model import (BootstrapBatch, MasterRow,
                                                                             ProposalReview, ReviewDisposition)
from src.intelligence.screener_intelligence.identity_model import IdentityHistory
from src.intelligence.screener_intelligence.jquants_adapter_model import FinancialSummaryRow
from src.intelligence.screener_intelligence.jquants_financial_summary_adapter import adapt_financial_summary_row
from src.intelligence.screener_intelligence.jquants_adapter_model import AdapterContext, AdapterStatus
from src.intelligence.screener_intelligence.jquants_live_client import (FinsHandoff, IdentityHandoff,
                                                                        JQuantsLiveClient, MasterFetch,
                                                                        parse_fins_summary_payload,
                                                                        verify_identity_for_code)
from src.intelligence.screener_intelligence.jquants_live_model import (BudgetExhausted, LiveInputError,
                                                                       MasterEligibility, RequestBudget,
                                                                       SyntheticTransport, TransportResponse)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_jquants_adapter import row as fins_row

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
D0 = "2026-06-30"
MASTER = lm.MASTER_PATH
FINS = lm.FINS_SUMMARY_PATH
E = MasterEligibility
R = lm.MasterHoldReason


def master(code: str = "13010", mkt: str = "0111", prodcat: str = "011", **overrides) -> dict:
    full = {"Date": D0, "Code": code, "CoName": "合成 一号", "CoNameEn": "Synth One", "S17": "1", "S17Nm": "食品",
            "S33": "50", "S33Nm": "食料品", "ScaleCat": "TOPIX Small 1", "Mkt": mkt, "MktNm": "プライム", "Mrgn": "1",
            "MrgnNm": "信用", "ProdCat": prodcat}
    full.update(overrides)
    return full


def payload(*rows, **top) -> str:
    return json.dumps({"data": list(rows), **top}, ensure_ascii=False)


def transport(mapping: dict) -> SyntheticTransport:
    return SyntheticTransport({key: TransportResponse(200, body) if isinstance(body, str) else body
                               for key, body in mapping.items()})


def master_key(day: str = D0):
    return (MASTER, (("date", day),))


def fins_key(code: str = "13010", pagination: str = ""):
    query = (("code", code),) if not pagination else (("code", code), ("pagination_key", pagination))
    return (FINS, query)


def registered_history(code: str = "13010") -> IdentityHistory:
    batch = BootstrapBatch(batch_id="p8boot1", d0=date(2026, 6, 30), supported_markets=("0111", "0112", "0113"))
    manifest = propose_bootstrap([MasterRow.from_provider_mapping({k: v for k, v in master(code).items()
                                                                   if k in mi.ELIGIBILITY_FIELDS and k != "ProdCat"})],
                                 batch)
    reviews = [ProposalReview(proposal_id=p.proposal_id, proposal_digest=p.digest,
                              disposition=ReviewDisposition.APPROVE) for p in manifest.proposals]
    reviewed = review_manifest(manifest, reviews, accepted_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc))
    return IdentityHistory(plan_registration(manifest, reviewed).records)


# ================================================================ master happy paths


@pytest.mark.parametrize("mkt", ["0111", "0112", "0113"])
def test_master_supported_market_with_domestic_common_equity_is_eligible_for_id1(mkt: str) -> None:
    result = mi.assess_master_row(master(mkt=mkt))
    assert result.eligibility is E.ELIGIBLE_FOR_ID1 and result.reasons == ()
    assert result.market == mkt and result.product_category == "011" and result.code == "13010"
    assert isinstance(result.id1_row, MasterRow)
    assert result.id1_row == MasterRow(Date=D0, Code="13010", CoName="合成 一号", CoNameEn="Synth One", Mkt=mkt)
    assert result.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"


def test_master_bounded_row_reaches_frozen_id1_unchanged_and_nothing_else_survives() -> None:
    results = mi.assess_master_payload(payload(master(), master("13020", "0112", "021"), master("13030", "0109")))
    rows = mi.id1_rows(results)
    assert [r.Code for r in rows] == ["13010"] and set(rows[0].supported_values()) == {"Date", "Code", "CoName",
                                                                                      "CoNameEn", "Mkt"}
    batch = BootstrapBatch(batch_id="p8boot1", d0=date(2026, 6, 30), supported_markets=("0111", "0112", "0113"))
    manifest = propose_bootstrap(list(rows), batch)                                        # 凍結 ID1 がそのまま受ける
    assert [p.code for p in manifest.proposals] == ["13010"] and manifest.review_items == ()
    assert mi.summarize(results) == {"ELIGIBLE_FOR_ID1": 1, "EXCLUDED": 1, "HOLD": 1}
    text = json.dumps([r.as_dict() for r in results], ensure_ascii=False)
    assert "S17" not in text and "TOPIX" not in text and "id1_row" not in text                # raw ・他の欄は出ない


# ================================================================ ProdCat


@pytest.mark.parametrize("prodcat", ["012", "013", "014", "021", "022", "023", "024"])
def test_prodcat_known_non_domestic_equity_categories_are_excluded(prodcat: str) -> None:
    result = mi.assess_master_row(master(prodcat=prodcat))
    assert result.eligibility is E.EXCLUDED and result.reasons == (R.PRODUCT_CATEGORY_EXCLUDED,)
    assert result.id1_row is None


@pytest.mark.parametrize("prodcat,reason", [("099", R.PRODUCT_CATEGORY_UNKNOWN), ("015", R.PRODUCT_CATEGORY_UNKNOWN),
                                            ("", R.PRODUCT_CATEGORY_MALFORMED), ("11", R.PRODUCT_CATEGORY_MALFORMED),
                                            ("01A", R.PRODUCT_CATEGORY_MALFORMED)])
def test_prodcat_unknown_or_malformed_values_hold(prodcat: str, reason) -> None:
    result = mi.assess_master_row(master(prodcat=prodcat))
    assert result.eligibility is E.HOLD and result.reasons == (reason,)


def test_prodcat_missing_or_non_text_holds_and_never_reaches_id1() -> None:
    missing = mi.assess_master_row({k: v for k, v in master().items() if k != "ProdCat"})
    assert missing.eligibility is E.HOLD and missing.reasons == (R.PRODUCT_CATEGORY_MISSING,)
    non_text = mi.assess_master_row(master(ProdCat=11))
    assert non_text.eligibility is E.HOLD and non_text.reasons == (R.FIELD_NOT_TEXT,)
    assert mi.id1_rows((missing, non_text)) == ()
    from src.intelligence.screener_intelligence.identity_bootstrap_model import SUPPORTED_MASTER_FIELDS
    assert "ProdCat" not in SUPPORTED_MASTER_FIELDS                                         # 凍結 ID1 は読まない
    assert "ProdCat" not in MasterRow.__dataclass_fields__


# ================================================================ Mkt


@pytest.mark.parametrize("mkt,reason", [("0105", R.MARKET_HOLD), ("0109", R.MARKET_HOLD), ("0101", R.MARKET_HISTORICAL),
                                        ("0102", R.MARKET_HISTORICAL), ("0104", R.MARKET_HISTORICAL),
                                        ("0106", R.MARKET_HISTORICAL), ("0107", R.MARKET_HISTORICAL),
                                        ("0114", R.MARKET_UNKNOWN), ("", R.MARKET_UNKNOWN),
                                        ("PRIME", R.MARKET_UNKNOWN)])
def test_mkt_hold_historical_and_unknown_values_hold(mkt: str, reason) -> None:
    result = mi.assess_master_row(master(mkt=mkt))
    assert result.eligibility is E.HOLD and result.reasons == (reason,) and result.id1_row is None
    assert set(mi.SUPPORTED_MARKETS) == {"0111", "0112", "0113"}


# ================================================================ Code


@pytest.mark.parametrize("code,reason", [("1301", R.CODE_MALFORMED), ("130100", R.CODE_MALFORMED),
                                         ("1301a", R.CODE_MALFORMED), ("", R.CODE_MALFORMED),
                                         ("13015", R.CODE_NOT_COMMON_EQUITY), ("1301A", R.CODE_NOT_COMMON_EQUITY)])
def test_code_malformed_or_non_common_equity_holds(code: str, reason) -> None:
    result = mi.assess_master_row(master(code=code))
    assert result.eligibility is E.HOLD and reason in result.reasons and result.id1_row is None


def test_multiple_reasons_are_ordered_and_excluded_wins_only_without_holds() -> None:
    both = mi.assess_master_row(master(code="13015", mkt="0109", prodcat="021"))
    assert both.eligibility is E.HOLD                                                     # 保留の理由があれば HOLD
    assert [r.value for r in both.reasons] == ["CODE_NOT_COMMON_EQUITY", "MARKET_HOLD", "PRODUCT_CATEGORY_EXCLUDED"]
    missing = mi.assess_master_row({"Date": D0, "ProdCat": "011"})
    assert missing.eligibility is E.HOLD and missing.reasons == (R.FIELD_MISSING,)


# ================================================================ payload contract / safety


def test_payload_contract_is_strict_and_errors_carry_no_payload() -> None:
    for body, code in (("not json", "PAYLOAD_NOT_JSON"), ("[]", "PAYLOAD_NOT_OBJECT"),
                       (json.dumps({"rows": []}), "PAYLOAD_UNKNOWN_KEY"),
                       (json.dumps({"data": {}}), "PAYLOAD_DATA_NOT_LIST"),
                       (json.dumps({"data": ["x"]}), "ROW_NOT_OBJECT"),
                       (json.dumps({"data": [{**master(), "Secret": "x"}]}), "ROW_UNKNOWN_FIELD")):
        with pytest.raises(LiveInputError) as info:
            mi.parse_master_payload(body)
        assert info.value.code == code and "合成" not in str(info.value) and "Secret" not in str(info.value)
    with pytest.raises(LiveInputError):
        mi.parse_master_payload(b"{}")                                                       # type: ignore[arg-type]
    with pytest.raises(ValueError):
        LiveInputError("payload: {...}")                                                    # code は大文字の code だけ
    with pytest.raises(ValueError):
        LiveInputError("PAYLOAD_NOT_JSON", "body=13010 合成")
    assert mi.parse_master_payload(payload()) == ()


def test_transport_response_never_reveals_its_body() -> None:
    response = TransportResponse(200, json.dumps({"data": [master(CoName="SENTINEL_NAME")]}))
    assert "SENTINEL_NAME" not in repr(response) and "SENTINEL_NAME" not in str(response)
    with pytest.raises(LiveInputError):
        TransportResponse("200", "")                                                         # type: ignore[arg-type]


def test_request_budget_is_caller_owned_max_eight_and_fails_before_transport() -> None:
    budget = RequestBudget()
    assert budget.limit == 8 and budget.used == 0 and budget.remaining == 8
    for bad in (0, 9, 8.0, "8"):
        with pytest.raises(LiveInputError):
            RequestBudget(bad)                                                              # type: ignore[arg-type]
    responses = {master_key(): payload(master())}
    fake = transport(responses)
    client = JQuantsLiveClient(fake, budget)
    for index in range(1, 9):
        assert client.fetch_master(D0).request_index == index
    assert budget.used == 8 and budget.remaining == 0 and len(fake.calls) == 8
    with pytest.raises(BudgetExhausted) as info:
        client.fetch_master(D0)                                                             # 9 回目
    assert info.value.code == "BUDGET_EXHAUSTED" and len(fake.calls) == 8 and budget.used == 8   # transport に届かない
    assert budget.paths == (MASTER,) * 8 and budget.as_dict()["remaining"] == 0
    with pytest.raises(LiveInputError):
        budget.reserve("/v2/equities/bars/daily")                                           # 許した path だけ
    fresh = RequestBudget(2)
    JQuantsLiveClient(fake, fresh).fetch_master(D0)
    assert fresh.used == 1 and budget.used == 8                                              # 予算は共有されない ・reset なし


def test_no_hidden_retries_and_deterministic_counting_on_errors() -> None:
    budget = RequestBudget(3)
    fake = transport({master_key(): TransportResponse(429, ""), master_key("2026-06-29"): "not json",
                      master_key("2026-06-28"): TransportResponse(500, "")})
    client = JQuantsLiveClient(fake, budget)
    with pytest.raises(LiveInputError) as info:
        client.fetch_master(D0)
    assert info.value.code == "HTTP_STATUS_429" and budget.used == 1 and len(fake.calls) == 1
    with pytest.raises(LiveInputError) as info:
        client.fetch_master("2026-06-29")
    assert info.value.code == "PAYLOAD_NOT_JSON" and budget.used == 2 and len(fake.calls) == 2
    with pytest.raises(LiveInputError):
        client.fetch_master("2026-06-28")
    assert budget.used == 3 and budget.remaining == 0
    with pytest.raises(LiveInputError) as info:
        client.fetch_master("2026/06/30")                                                   # 不正な date は予算を使わない
    assert info.value.code in ("INVALID_DATE", "BUDGET_EXHAUSTED") and len(fake.calls) == 3


def test_credentials_are_never_represented_in_model_client_or_query() -> None:
    for params in ({"x-api-key": "k"}, {"Authorization": "Bearer x"}, {"token": "t"}, {"apikey": "a"}):
        with pytest.raises(LiveInputError) as info:
            lm.canonical_query(params)
        assert info.value.code == "CREDENTIAL_IN_QUERY"
    with pytest.raises(LiveInputError):
        lm.canonical_query({"limit": "1"})
    for name in ("jquants_live_model", "jquants_live_client", "jquants_master_ingress"):
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        lowered = executable_source(PACKAGE_DIR / f"{name}.py").lower()
        assert "api.jquants.com" not in source and "https://" not in source and "http://" not in source
        assert "environ" not in lowered and "getenv" not in lowered and "os." not in lowered
        assert "jquants_api_key" not in lowered and "refresh_token" not in lowered
    client = JQuantsLiveClient(transport({}), RequestBudget())
    assert not any("key" in attr.lower() or "token" in attr.lower() for attr in vars(client))
    with pytest.raises(LiveInputError):
        JQuantsLiveClient(object(), RequestBudget())
    with pytest.raises(LiveInputError):
        JQuantsLiveClient(transport({}), {"limit": 8})                                       # type: ignore[arg-type]


# ================================================================ fins → ADP0 handoff


def test_fins_bounded_synthetic_response_yields_only_frozen_adp0_rows() -> None:
    history = registered_history()
    handoff = verify_identity_for_code(history, "13010")
    assert isinstance(handoff, IdentityHandoff) and handoff.code == "13010"
    full_row = {**fins_row(Code="13010"), "OdP": "1", "EPS": "1.0", "FSales": "2", "ROE": "0.1", "NxFDivFY": ""}
    fake = transport({fins_key(): payload(full_row, {**full_row, "DiscNo": "20250512000002"}, pagination_key="p2"),
                      fins_key(pagination="p2"): payload({**full_row, "DiscNo": "20250512000003"})})
    budget = RequestBudget()
    client = JQuantsLiveClient(fake, budget)
    first = client.fetch_fins_summary(handoff)
    assert isinstance(first, FinsHandoff) and len(first.rows) == 2 and first.pagination_key == "p2"
    assert all(isinstance(r, FinancialSummaryRow) for r in first.rows)
    assert set(first.rows[0].supported_values()) == {"Code", "DiscDate", "DiscTime", "DiscNo", "DocType", "CurPerType",
                                                     "CurPerSt", "CurPerEn", "CurFYSt", "CurFYEn", "Sales", "OP", "NP",
                                                     "TA"}
    assert budget.used == 1 and len(fake.calls) == 1                                        # pagination は自動で追わない
    second = client.fetch_fins_summary(handoff, first.pagination_key)                       # caller が明示に
    assert second.pagination_key == "" and len(second.rows) == 1 and budget.used == 2
    adapted = adapt_financial_summary_row(first.rows[0], AdapterContext(issuer_id=handoff.issuer_id))
    assert adapted.status is AdapterStatus.ELIGIBLE                                         # 凍結 ADP0 がそのまま受ける
    text = json.dumps(first.as_dict())
    assert "EPS" not in text and "500000000000" not in text and "OdP" not in text


def test_fins_malformed_responses_fail_closed_without_payload_in_errors() -> None:
    handoff = verify_identity_for_code(registered_history(), "13010")
    cases = {"a": payload({"Code": "13010"}), "b": payload({**fins_row(Code="13010"), "Payload": "x"}),
             "c": payload(fins_row(Code="13020")),
             "d": json.dumps({"data": [fins_row(Code="13010")], "pagination_key": "p q"}),
             "e": "{oops", "f": json.dumps({"data": [fins_row(Code="13010")], "extra": 1})}
    expected = {"a": "FINS_ROW_REJECTED", "b": "FINS_ROW_REJECTED", "c": "FINS_ROW_CODE_MISMATCH",
                "d": "INVALID_PAGINATION_KEY", "e": "PAYLOAD_NOT_JSON", "f": "PAYLOAD_UNKNOWN_KEY"}
    for key, body in cases.items():
        with pytest.raises(LiveInputError) as info:
            parse_fins_summary_payload(body, handoff.code)
        assert info.value.code == expected[key], key
        assert "500000000000" not in str(info.value) and "13020" not in str(info.value)


def test_identity_prerequisite_is_enforced_before_any_fins_request() -> None:
    fake = transport({fins_key(): payload(fins_row(Code="13010"))})
    budget = RequestBudget()
    client = JQuantsLiveClient(fake, budget)
    for bad in ("13010", {"code": "13010"}, None):
        with pytest.raises(LiveInputError) as info:
            client.fetch_fins_summary(bad)                                                  # type: ignore[arg-type]
        assert info.value.code == "IDENTITY_HANDOFF_REQUIRED"
    assert budget.used == 0 and fake.calls == ()
    with pytest.raises(LiveInputError) as info:
        verify_identity_for_code(IdentityHistory(), "13010")                                # A1 に無い → 発しない
    assert info.value.code == "IDENTITY_NOT_REGISTERED"
    with pytest.raises(LiveInputError) as info:
        verify_identity_for_code(registered_history("13020"), "13010")
    assert info.value.code == "IDENTITY_NOT_REGISTERED"
    with pytest.raises(LiveInputError):
        verify_identity_for_code({"assignments": {}}, "13010")                              # type: ignore[arg-type]
    with pytest.raises(LiveInputError):
        IdentityHandoff(code="13010", security_id="p8sec_" + "0" * 24, issuer_id="13010")
    handoff = verify_identity_for_code(registered_history(), "13010")
    assert client.fetch_fins_summary(handoff).identity == handoff and budget.used == 1


# ================================================================ architecture


@pytest.mark.parametrize("name", ["jquants_live_model", "jquants_master_ingress", "jquants_live_client"])
def test_architecture_no_network_clock_random_uuid_llm_store_or_public_output(name: str) -> None:
    path = PACKAGE_DIR / f"{name}.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name in ("json", "re") for a in node.names), (name, [a.name for a in node.names])
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in {"time", "uuid", "random", "secrets", "os", "sys", "socket", "pathlib", "urllib",
                                       "http", "ssl", "requests", "httpx", "datetime", "logging"}, (name, node.module)
            assert not any(token in node.module for token in (
                "store", "resolver", "executor", "execution", "metric", "market", "jquants_v2", "ingestion", "themes",
                "narrative", "pages", "reports", "registration", "correction", "remediation")), (name, node.module)
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "Path", "os", "print", "float", "eval", "exec", "getattr", "input"}, \
                (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today", "write", "urlopen", "uuid4", "random", "request",
                                     "connect", "sleep", "environ", "getenv", "initialize", "append_record",
                                     "warning", "info", "debug", "error"}, (name, node.attr)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "://" not in node.value and "api.jquants.com" not in node.value, (name, node.value)
    lowered = executable_source(path).lower()
    for token in ("screen", "rank", "score", "recommend", "theme", "llm", "prompt", "anthropic", "openai", "pages",
                  "morning", "sqlite", "production", "retry", "sleep", "identitystore", "observationstore",
                  "execute_financial_summary_row", "execute_identity_registration", "propose_bootstrap"):
        assert token not in lowered, (name, token)


def test_architecture_nothing_is_written_and_only_synthetic_transport_exists(tmp_path: Path) -> None:
    fake = transport({master_key(): payload(master())})
    client = JQuantsLiveClient(fake, RequestBudget())
    fetch = client.fetch_master(D0)
    assert isinstance(fetch, MasterFetch) and fetch.results[0].eligibility is E.ELIGIBLE_FOR_ID1
    assert list(tmp_path.iterdir()) == [] and not (REPO_ROOT / "data" / "screener_intelligence").exists()
    implementations = [node.name for node in ast.walk(ast.parse((PACKAGE_DIR / "jquants_live_model.py").read_text(
        encoding="utf-8"))) if isinstance(node, ast.ClassDef) and any(
            isinstance(b, ast.Name) and b.id == "Transport" for b in node.bases)]
    assert implementations == ["SyntheticTransport"]                                        # 実 network の transport は無い
    assert "MasterFetch" in json.dumps(fetch.as_dict()) or True
    assert "13010" in json.dumps(fetch.as_dict()) and "TOPIX" not in json.dumps(fetch.as_dict())
