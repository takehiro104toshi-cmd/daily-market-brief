"""P1-C Live Validation（最小限の実接続確認）。

目的: adapter / fetcher の接続確認のみ。**bulk ingestionはしない**
（1ソース=1リクエスト・対象は監督者指定の少数セットのみ）。

実行環境: 本開発コンテナはegress遮断のため、GitHub Actions runner
（.github/workflows/p1c-live-validation.yml）で実行する。プロキシ制約の迂回はしない。

出力: 各ソースの検証結果を `::LIVE_VALIDATION_RESULT::{json}` 行としてstdoutへ出す
（ログから機械抽出してSourceHealthObservation追記・カタログ更新に使う）。
Secret・body本文はログへ出さない（entry件数・形式・状態のみ）。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..sources.health_check import (
    FetchResult as HealthFetchResult,
    classify_format,
    evaluate,
    extract_latest_item_at,
)
from ..sources.model import SourceEndpoint
from .feed_parser import decode_body, parse_feed
from .fetcher import Fetcher
from .raw_store import JsonlRawRepository
from .transport import UrllibTransport

#: 監督者指定のFirst Live Validation Set（CORE中心＋各format最低1つ）。
#: RSS2=bls_latest等 / Atom=uk_gov / RDF=mof_whatsnew,dmb_boj_whatsnew /
#: JSON=edinet_disclosures（キー無し=401でAUTH_REQUIRED挙動の実証。Secretは使わない）
DEFAULT_SET = (
    "fed_press",        # CORE / Fed
    "boj_whatsnew",     # CORE / BOJ (EN)
    "dmb_boj_whatsnew", # BOJ (JP, RDF) — DEGRADED原因の切り分け
    "mof_whatsnew",     # CORE / MOF (RDF)
    "dmb_ecb_press",    # CORE / ECB
    "bls_latest",       # CORE / BLS (RSS2)
    "us_treasury",      # CORE候補 / endpoint実体・format確定
    "jp_stat_release",  # CORE候補 / endpoint実体・format確定
    "uk_gov",           # Atom代表
    "nhk_business",     # 既知HEALTHYの較正用（RSS2/JP）
    "edinet_disclosures",  # JSON API / 認証なし挙動の実証（キーは送らない）
)

MARKER = "::LIVE_VALIDATION_RESULT::"


def load_catalog(path: Path) -> dict:
    import yaml  # runner側でのみ必要（オフラインテストはこの関数を使わない）

    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_source(feed: dict, fetcher: Fetcher) -> dict:
    """1ソースを1リクエストで検証し、記録用dictを返す。"""
    endpoint = SourceEndpoint(source_id=feed["id"], url=feed["endpoint"]["url"])
    outcome = fetcher.fetch(endpoint)
    attempt = outcome.attempt
    response = outcome.response

    body = response.body if response is not None else b""
    sample = decode_body(body[:16384], attempt.content_type).text[:8192] if body else ""
    state, note = evaluate(
        HealthFetchResult(
            status=attempt.status_code,
            final_url=attempt.final_url,
            permanent_redirect=attempt.permanent_redirect,
            content_type=attempt.content_type,
            body_sample=sample,
            error=attempt.error_detail,
        ),
        now=attempt.requested_at,
        canonical_url=endpoint.url,
    )
    parse_result = parse_feed(body, content_type=attempt.content_type, source_url=endpoint.url) if body else None
    latest = extract_latest_item_at(sample)
    return {
        "source_id": feed["id"],
        "checked_at": attempt.requested_at.isoformat(),
        "state": state.value,
        "note": note,
        "http_status": attempt.status_code,
        "final_url": attempt.final_url,
        "permanent_redirect": attempt.permanent_redirect,
        "content_type": attempt.content_type,
        "detected_format": classify_format(sample).value if sample else "unknown",
        "parsed_format": parse_result.format.value if parse_result else "",
        "entries_extracted": len(parse_result.entries) if parse_result else 0,
        "parse_error": parse_result.error if parse_result else "",
        "etag_present": bool(attempt.etag),
        "last_modified_present": bool(attempt.last_modified),
        "latest_item_at": latest.isoformat() if latest else "",
        "content_hash": attempt.content_hash,
        "body_size": attempt.body_size,
        "elapsed_ms": attempt.elapsed_ms,
        "error_kind": attempt.error_kind,
        "retries": attempt.retries,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="P1-C minimal live validation")
    parser.add_argument("--ids", default=",".join(DEFAULT_SET),
                        help="comma-separated source ids (default: supervisor-approved set)")
    parser.add_argument("--catalog", default="knowledge/source_reliability/source_feeds.yaml")
    args = parser.parse_args(argv)

    catalog = load_catalog(Path(args.catalog))
    by_id = {f["id"]: f for f in catalog["feeds"]}
    ids = [s.strip() for s in args.ids.split(",") if s.strip()]

    with tempfile.TemporaryDirectory() as tmp:
        repo = JsonlRawRepository(Path(tmp))
        fetcher = Fetcher(UrllibTransport(), repo)
        print(f"P1-C live validation: {len(ids)} sources, 1 request each "
              f"(no bulk ingestion), at {datetime.now(timezone.utc).isoformat()}")
        for source_id in ids:
            feed = by_id.get(source_id)
            if feed is None:
                print(MARKER + json.dumps({"source_id": source_id, "state": "error",
                                           "note": "not in catalog"}, ensure_ascii=False))
                continue
            try:
                record = validate_source(feed, fetcher)
            except Exception as exc:  # noqa: BLE001 1ソースの失敗で全体を止めない
                record = {"source_id": source_id, "state": "error",
                          "note": f"{type(exc).__name__}: {str(exc)[:160]}"}
            print(MARKER + json.dumps(record, ensure_ascii=False))
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
