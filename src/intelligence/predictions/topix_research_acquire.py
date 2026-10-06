"""TOPIX ONE-TIME RESEARCH ACQUISITION driver（Phase 5 Entry Contract A0.7）。

目的は 1 つだけ——`NEUTRAL_RANGE` の band を決めるために必要な
**TOPIX 日次 close の実データ**を、production から完全隔離された
research dataset として 1 回だけ取得することである。

    JQuantsV2TopixProvider  (/v2/indices/bars/daily/topix)
    JQuantsV2Client         (/v2/markets/calendar)
      → MarketBackfillEngine（既存の ingest / QA / derived をそのまま使う）
      → **明示指定された research root だけ**へ保存
      → 取得後 validation（13 項目）→ acquisition metadata

規律:

- **production Market Bank の永続化設計ではない。** producer / publication /
  `/v2` / Pages / governance / Compass DNA のいずれにも触れない。
- **第二の J-Quants client を作らない。HTTP を再実装しない。**
  既存の `JQuantsV2TopixProvider` / `JQuantsV2Client` / `MarketBankStore` /
  `ingest` / `derive_per_series` / `tokyo_calendar` を再利用する。
- **到達してよい endpoint は 2 つだけ**（`ALLOWED_ENDPOINTS`）。他の market
  series / provider（yfinance / stooq / treasury_gov / mof_japan）は
  **1 つも登録しない**ため、構造的に到達できない。`pilot_runner` も呼ばない。
- **暗黙の production fallback を持たない。** research root / start / end は
  すべて明示引数で必須。`data_root()` を読まない。
- **credential は `JQUANTS_API_KEY` の runtime injection のみ。** 未設定なら
  ネットワークを 1 回も叩かず、ディレクトリも作らずに停止する。
- **provider の 20 page 安全上限を変更しない。** 上限へ到達したら期間を勝手に
  短縮も分割もせず `RESEARCH_WINDOW_EXCEEDS_EXISTING_PAGINATION_CONTRACT` で停止する。
- **祝日判定に weekday 演算を使わない。** 営業日は J-Quants 取引カレンダーの
  実測検証済み区分だけで決める。検証できなければ fail closed。
- **非空 research root へは黙って追記しない**（初版は fail closed）。

このモジュールは threshold を決めない。分布も測定しない。取得と検証だけを行う。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..core import serialization
from ..evidence_qa.policy import HISTORICAL_V1
from ..market.backfill import MarketBackfillEngine
from ..market.derived import derived_series_id_for
from ..market.jquants_light_datasets import get_dataset
from ..market.jquants_light_store import JQuantsLightStore
from ..market.jquants_records import PARSERS, RecordProvenance
from ..market.jquants_v2 import TOPIX_PATH, JQuantsV2TopixProvider
from ..market.jquants_v2_client import JQuantsV2Client
from ..market.model import latest_revisions
from ..market.series_catalog import load_catalog
from ..market.store import MarketBankStore
from ..market.tokyo_calendar import DEFAULT_TRADING_DIVISIONS, trading_days, validate_divisions

#: acquisition metadata の schema 版（挙動を変えたら上げる）
RESEARCH_SCHEMA_VERSION = "topix_research_acquisition:0.1.0"

#: 研究対象は TOPIX 現物終値の 1 系列だけ（ETF・先物・近似指数を代用しない）
TOPIX_SERIES_ID = "index:topix.close.closing.tokyo"
CALENDAR_DATASET = "markets_calendar"
CALENDAR_PATH = "/markets/calendar"

#: **到達を許す endpoint はこの 2 つだけ**（allowlist。これ以外は登録も参照もしない）
ALLOWED_ENDPOINTS: Tuple[str, ...] = (TOPIX_PATH, CALENDAR_PATH)

#: 既存 provider の安全上限（**変更しない**）。到達したら fail closed。
PROVIDER_PAGE_CAP = 20

#: derived と同一の丸め規約（cross-check を同条件で行うため）
_Q = Decimal("0.000001")

#: research root として拒否する path 断片（連続する segment 列として照合）
FORBIDDEN_PATH_PARTS: Tuple[Tuple[str, ...], ...] = (
    ("data", "vnext"), ("output",), ("docs",), ("knowledge",), (".git",),
)

RESULT_OK = "ACQUISITION_OK"
RESULT_INVALID_ARGS = "INVALID_ARGUMENTS"
RESULT_INVALID_ROOT = "INVALID_RESEARCH_ROOT"
RESULT_NON_EMPTY_ROOT = "NON_EMPTY_RESEARCH_ROOT"
RESULT_NO_CREDENTIALS = "NO_CREDENTIALS"
RESULT_FETCH_FAILED = "ACQUISITION_FETCH_FAILED"
RESULT_PAGINATION = "RESEARCH_WINDOW_EXCEEDS_EXISTING_PAGINATION_CONTRACT"
RESULT_VALIDATION_FAILED = "ACQUISITION_VALIDATION_FAILED"

MARKER = "::P5_TOPIX_RESEARCH::"


class ResearchAcquisitionError(RuntimeError):
    """fail closed の停止理由（`code` は機械可読・`detail` に秘密を載せない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def repository_root() -> Path:
    """このモジュールから見たリポジトリ root（src/intelligence/predictions/x.py）。"""
    return Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------- argument contract

def parse_iso_date(token: str, *, field: str) -> date:
    try:
        return date.fromisoformat(token)
    except ValueError:
        raise ResearchAcquisitionError(
            RESULT_INVALID_ARGS, f"{field} is not an ISO date (YYYY-MM-DD)") from None


def validate_window(start: date, end: date, *, today: date) -> None:
    """start < end、かつ end は未来でないこと。**期間を勝手に作らない**。"""
    if not start < end:
        raise ResearchAcquisitionError(RESULT_INVALID_ARGS, "start-date must be < end-date")
    if end > today:
        raise ResearchAcquisitionError(RESULT_INVALID_ARGS, "end-date is in the future")


def _contains_parts(path: Path, needle: Sequence[str]) -> bool:
    parts = tuple(path.parts)
    n = len(needle)
    return any(parts[i:i + n] == tuple(needle) for i in range(len(parts) - n + 1))


def validate_research_root(raw: str, *, repo_root: Optional[Path] = None) -> Path:
    """research root を **ネットワークの前に** 検証する（fail closed）。

    - 絶対 path 必須
    - repository root 配下を拒否（data/vnext・output・docs・knowledge・.git を含む）
    - production canonical root の名前断片を拒否
    - 既存なら空ディレクトリのみ許可（非空は `NON_EMPTY_RESEARCH_ROOT`）
    """
    if not raw:
        raise ResearchAcquisitionError(RESULT_INVALID_ROOT, "--research-root is required")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise ResearchAcquisitionError(RESULT_INVALID_ROOT, "--research-root must be absolute")
    resolved = candidate.resolve()
    repo = (repo_root or repository_root()).resolve()
    if resolved == repo or repo in resolved.parents:
        raise ResearchAcquisitionError(
            RESULT_INVALID_ROOT, "--research-root must be outside the repository")
    for needle in FORBIDDEN_PATH_PARTS:
        if _contains_parts(resolved, needle):
            raise ResearchAcquisitionError(
                RESULT_INVALID_ROOT, f"forbidden path segment: {'/'.join(needle)}")
    if resolved.exists():
        if not resolved.is_dir():
            raise ResearchAcquisitionError(RESULT_INVALID_ROOT, "--research-root is not a directory")
        if any(resolved.iterdir()):
            raise ResearchAcquisitionError(
                RESULT_NON_EMPTY_ROOT,
                "research root is not empty (this driver never appends to an existing dataset)")
    return resolved


# ---------------------------------------------------------------- acquisition

@dataclass(frozen=True, kw_only=True)
class AcquisitionOutcome:
    """1 回の取得結果（metadata へそのまま落とす。秘密を持たない）。"""

    result: str
    research_root: str
    requested_start: str
    requested_end: str
    topix_observations: int
    topix_earliest: str
    topix_latest: str
    topix_pages: int
    api_version: str
    calendar_rows: int
    calendar_pages: int
    derived_return_1d: int
    checks: Mapping[str, object]

    def as_dict(self) -> Dict[str, object]:
        return {
            "schema_version": RESEARCH_SCHEMA_VERSION,
            "result": self.result,
            "research_root": self.research_root,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "topix_observations": self.topix_observations,
            "topix_earliest": self.topix_earliest,
            "topix_latest": self.topix_latest,
            "topix_pages": self.topix_pages,
            "api_version": self.api_version,
            "calendar_rows": self.calendar_rows,
            "calendar_pages": self.calendar_pages,
            "derived_return_1d": self.derived_return_1d,
            "checks": dict(self.checks),
        }


def _store_calendar_raw(store: JQuantsLightStore, result, attempt_id: str) -> str:
    """生応答を blob ＋ RawItem として保存し raw_item_id を返す（URL に秘密は無い）。"""
    from ..sources.model import RawItem

    body = result.raw_body
    if not body:
        return ""
    content_hash, locator, _created = store.raw.store_body(body)
    raw_item_id = RawItem.make_id("jquants", result.url, content_hash)
    if store.raw.get_raw_item(raw_item_id) is None:
        store.raw.add_raw_item(RawItem(
            raw_item_id=raw_item_id, source_id="jquants", locator=result.url,
            retrieved_at=datetime.now(timezone.utc), media_type="application/json",
            content_hash=content_hash, size_bytes=len(body), storage_ref=locator,
            endpoint_id=f"jquants:{result.dataset}", fetch_attempt_id=attempt_id))
    return raw_item_id


def acquire(
    *,
    research_root: Path,
    start: date,
    end: date,
    catalog_path: Path,
    provider: Optional[JQuantsV2TopixProvider] = None,
    client: Optional[JQuantsV2Client] = None,
) -> Tuple[AcquisitionOutcome, MarketBankStore, JQuantsLightStore]:
    """TOPIX ＋ 取引カレンダーを 1 回だけ取得して research root へ保存する。

    呼び出し側は credential 検査を済ませていること（未設定なら本関数へ来ない）。
    """
    serialization.register_domain_types()
    catalog = load_catalog(catalog_path)
    spec = catalog.get(TOPIX_SERIES_ID)
    if spec is None:
        raise ResearchAcquisitionError(RESULT_INVALID_ARGS, "TOPIX series not in catalog")

    topix_provider = provider or JQuantsV2TopixProvider()
    bank = MarketBankStore(research_root / "databank" / "market")
    light = JQuantsLightStore(research_root / "jquants_light")
    try:
        return _acquire_inner(
            research_root=research_root, start=start, end=end, catalog=catalog,
            spec=spec, topix_provider=topix_provider, client=client,
            bank=bank, light=light)
    except Exception:
        # 失敗しても sqlite handle を開いたままにしない（Windows の lock を残さない）
        for store in (bank, light):
            try:
                store.close()
            except Exception:  # noqa: BLE001 close の失敗で原因例外を隠さない
                pass
        raise


def _acquire_inner(
    *,
    research_root: Path,
    start: date,
    end: date,
    catalog,
    spec,
    topix_provider: JQuantsV2TopixProvider,
    client: Optional[JQuantsV2Client],
    bank: MarketBankStore,
    light: JQuantsLightStore,
) -> Tuple[AcquisitionOutcome, MarketBankStore, JQuantsLightStore]:
    """`acquire()` の本体（store の後片付けは呼び出し側が持つ）。"""
    # ---- TOPIX: **jquants provider だけ**を登録する（他 provider へ到達できない）
    engine = MarketBackfillEngine(
        bank, catalog, {"jquants": topix_provider}, HISTORICAL_V1, sleeper=None)
    run = engine.run(start=start, end=end, series_ids=(TOPIX_SERIES_ID,))

    pages = int(getattr(topix_provider, "pages_fetched", 0) or 0)
    if pages >= PROVIDER_PAGE_CAP:
        raise ResearchAcquisitionError(
            RESULT_PAGINATION,
            f"provider reached the frozen {PROVIDER_PAGE_CAP}-page cap; "
            "truncation cannot be ruled out (window is not shortened or split here)")
    if run.series_success != 1:
        failures = ";".join(f"{r.status}:{r.error_kind}" for r in run.results)
        raise ResearchAcquisitionError(RESULT_FETCH_FAILED, failures[:160])

    # ---- 取引カレンダー（営業日判定の唯一の権威。weekday 演算は使わない）
    cal_spec = get_dataset(CALENDAR_DATASET)
    cal_client = client or JQuantsV2Client()
    cal_result = cal_client.fetch(
        CALENDAR_DATASET, cal_spec.path,
        {"from": start.isoformat(), "to": end.isoformat()},
        required_fields=cal_spec.required_fields)
    if int(getattr(cal_result, "pages", 0) or 0) >= PROVIDER_PAGE_CAP:
        raise ResearchAcquisitionError(
            RESULT_PAGINATION, "calendar fetch reached the frozen page cap")
    if not cal_result.ok:
        raise ResearchAcquisitionError(
            RESULT_FETCH_FAILED, f"calendar:{cal_result.error_kind}")
    attempt_id = "p5res_0001"
    raw_item_id = _store_calendar_raw(light, cal_result, attempt_id)
    provenance = RecordProvenance(
        endpoint=cal_spec.path, retrieved_at=cal_result.retrieved_at,
        raw_item_id=raw_item_id or "", fetch_attempt_id=attempt_id)
    parse = PARSERS[CALENDAR_DATASET]
    records = [r for r in (parse(row, provenance) for row in cal_result.rows) if r is not None]
    light.append(CALENDAR_DATASET, records)

    checks = validate_acquisition(
        bank=bank, light=light, spec=spec, start=start, end=end,
        research_root=research_root)
    raw = latest_revisions(tuple(
        o for o in bank.observations_for_series(TOPIX_SERIES_ID) if o.kind.value == "raw"))
    dates = sorted(o.trading_date for o in raw if o.trading_date)
    derived_id = derived_series_id_for(spec, "return_1d")
    derived_count = len(bank.observations_for_series(derived_id))
    failed = sorted(k for k, v in checks.items() if v is not True)
    outcome = AcquisitionOutcome(
        result=RESULT_OK if not failed else RESULT_VALIDATION_FAILED,
        research_root=research_root.name,
        requested_start=start.isoformat(), requested_end=end.isoformat(),
        topix_observations=len(raw),
        topix_earliest=dates[0] if dates else "",
        topix_latest=dates[-1] if dates else "",
        topix_pages=pages, api_version=topix_provider.api_version,
        calendar_rows=len(records), calendar_pages=int(getattr(cal_result, "pages", 0) or 0),
        derived_return_1d=derived_count, checks=checks)
    return outcome, bank, light


# ---------------------------------------------------------------- post-acquisition validation

def validate_acquisition(
    *,
    bank: MarketBankStore,
    light: JQuantsLightStore,
    spec,
    start: date,
    end: date,
    research_root: Path,
) -> Dict[str, object]:
    """成功扱いする前の 13 検証。値が `True` 以外なら ACQUISITION_VALIDATION_FAILED。"""
    checks: Dict[str, object] = {}
    raw = latest_revisions(tuple(
        o for o in bank.observations_for_series(TOPIX_SERIES_ID) if o.kind.value == "raw"))
    ordered = sorted((o for o in raw if o.trading_date), key=lambda o: o.trading_date)

    # 1. 観測が 1 件以上
    checks["topix_observations_present"] = len(ordered) > 0
    # 2. 合成 fixture（source_id='test'）の混入ゼロ
    checks["no_synthetic_source"] = all(o.source_id != "test" for o in ordered)
    # 3. provider / api version が J-Quants v2
    checks["provider_is_jquants_v2"] = bool(ordered) and all(
        o.source_id == "jquants" for o in ordered)
    # 4. trading_date の重複ゼロ
    days = [o.trading_date for o in ordered]
    checks["no_duplicate_trading_date"] = len(days) == len(set(days))
    # 5. close の欠測ゼロ
    checks["no_missing_close"] = all(o.value is not None for o in ordered)
    # 6. close <= 0 ゼロ
    checks["no_nonpositive_close"] = all(
        o.value is not None and o.value > 0 for o in ordered)

    # 7. カレンダー区分の実測検証（推測で HolDiv の意味を決めない）
    cal_rows = [dict(r) for r in light.calendar_range(start.isoformat(), end.isoformat())]
    validation = validate_divisions(cal_rows, days)
    checks["calendar_validated"] = bool(validation.validated)
    # 8. gap 検査（営業日と観測日が過不足なく一致する）
    sessions = [d for d in trading_days(cal_rows, trading_divisions=DEFAULT_TRADING_DIVISIONS)
                if start.isoformat() <= d <= end.isoformat()]
    covered = [d for d in days if start.isoformat() <= d <= end.isoformat()]
    checks["no_session_gap"] = bool(sessions) and sorted(sessions) == sorted(covered)
    # 9. weekday fallback は構造的に使わない（この module は weekday 演算を持たない）
    checks["no_weekday_fallback"] = True

    # 10. raw close からの独立再計算 == 既存 derived return_1d
    derived_id = derived_series_id_for(spec, "return_1d")
    stored = {o.trading_date: o.value
              for o in bank.observations_for_series(derived_id) if o.value is not None}
    recomputed: Dict[str, Decimal] = {}
    usable = [o for o in ordered if o.value is not None]
    for i in range(1, len(usable)):
        prev, cur = usable[i - 1], usable[i]
        if prev.value == 0:
            continue
        recomputed[cur.trading_date] = (
            (cur.value - prev.value) / prev.value * Decimal(100)
        ).quantize(_Q, rounding=ROUND_HALF_EVEN)
    checks["derived_return_matches_recomputation"] = (
        bool(recomputed) and stored == recomputed)

    # 11. secret leakage ゼロ（research root 配下の全 text へ key literal が出ない）
    checks["no_secret_leakage"] = _no_secret_in_tree(research_root)
    # 12 / 13. repository / production data root へ書いていない（path 不変条件の再確認）
    repo = repository_root().resolve()
    root = research_root.resolve()
    checks["no_repository_write"] = not (root == repo or repo in root.parents)
    checks["no_production_data_root_write"] = not _contains_parts(root, ("data", "vnext"))
    return checks


def _no_secret_in_tree(root: Path) -> bool:
    """成果物に credential が混入していないこと（値は決して出力しない）。"""
    secret = os.environ.get("JQUANTS_API_KEY", "").strip()
    needles = [b"x-api-key", b"api_key="]
    if secret:
        needles.append(secret.encode("utf-8"))
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            return False
        if any(n and n in blob for n in needles):
            return False
    return True


# ---------------------------------------------------------------- CLI

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5 ONE-TIME TOPIX research acquisition (isolated; not production)")
    parser.add_argument("--research-root", required=True,
                        help="絶対 path。リポジトリ外・空ディレクトリのみ")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD（含む）")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD（含む）")
    parser.add_argument("--catalog", default="knowledge/market_series/core_series.yaml")
    args = parser.parse_args(argv)

    bank = light = None
    try:
        root = validate_research_root(args.research_root)
        start = parse_iso_date(args.start_date, field="--start-date")
        end = parse_iso_date(args.end_date, field="--end-date")
        validate_window(start, end, today=datetime.now(timezone.utc).date())

        # credential 未設定なら **ネットワーク 0 回・ディレクトリも作らず** 停止
        if not JQuantsV2Client().credential_present():
            raise ResearchAcquisitionError(
                RESULT_NO_CREDENTIALS, "JQUANTS_API_KEY is not set (runtime injection only)")

        outcome, bank, light = acquire(
            research_root=root, start=start, end=end, catalog_path=Path(args.catalog))
        payload = outcome.as_dict()
        (root / "acquisition.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(MARKER + json.dumps(payload, ensure_ascii=False))
        return 0 if outcome.result == RESULT_OK else 1
    except ResearchAcquisitionError as exc:
        print(MARKER + json.dumps(
            {"schema_version": RESEARCH_SCHEMA_VERSION, "result": exc.code,
             "detail": exc.detail}, ensure_ascii=False))
        return 1
    finally:
        for store in (bank, light):
            if store is not None:
                store.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
