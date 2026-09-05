"""P2-A Real End-to-End Pilot実行スクリプト（GitHub Actions用）。

監督者指定: 少数sourceのみ（bulk禁止）・途中をmockしない・failure pathも確認。
出力は `::E2E_RESULT::{json}` 行＋trace report（logから機械抽出して文書化する）。
Secret不使用・body本文はログへ出さない（trace内のtitle 1件のみ＝公開見出し）。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..evidence_qa.policy import GENERIC_V1
from ..ingestion.transport import UrllibTransport
from .e2e import Pipeline
from .trace import build_trace, render_trace

#: 成功系: 異なるtier/publisher/言語/形式を含む5ソース（監督者優先: BOJ/ECB/Fed＋BLS＋一般1）
SUCCESS_SET = ("boj_whatsnew", "fed_press", "dmb_ecb_press", "nhk_business", "theverge")
#: 失敗系: 404が確定しているソース（P1-C実測）＋UA条件403（bls_latest）
FAILURE_SET = ("dmb_boj_whatsnew", "bls_latest")

MARKER = "::E2E_RESULT::"
TRACE_BEGIN = "::E2E_TRACE_BEGIN::"
TRACE_END = "::E2E_TRACE_END::"


def main(argv=None) -> int:
    import yaml

    parser = argparse.ArgumentParser(description="P2-A real end-to-end pilot")
    parser.add_argument("--catalog", default="knowledge/source_reliability/source_feeds.yaml")
    args = parser.parse_args(argv)

    catalog = yaml.safe_load(Path(args.catalog).read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in catalog["feeds"]}

    with tempfile.TemporaryDirectory() as tmp:
        pipeline = Pipeline(Path(tmp), UrllibTransport(), GENERIC_V1)
        print(f"P2-A E2E pilot: {len(SUCCESS_SET)}+{len(FAILURE_SET)} sources, "
              f"1 request each, at {datetime.now(timezone.utc).isoformat()}")
        first_accept = None
        for source_id in SUCCESS_SET + FAILURE_SET:
            feed = by_id[source_id]
            result = pipeline.run_source(feed)
            attempt = result.fetch_outcome.attempt
            record = {
                "source_id": source_id,
                "stage_reached": result.stage_reached,
                "http_status": attempt.status_code,
                "error_kind": attempt.error_kind,
                "raw_item_id": (result.fetch_outcome.raw_item.raw_item_id
                                if result.fetch_outcome.raw_item else ""),
                "body_size": attempt.body_size,
                "parse_format": (result.normalization.documents[0].media_type
                                 if result.normalization and result.normalization.documents
                                 else ""),
                "documents": (len(result.normalization.documents)
                              if result.normalization else 0),
                "normalization_status": (result.normalization.status.value
                                         if result.normalization else ""),
                "normalization_issues": (len(result.normalization.issues)
                                         if result.normalization else 0),
                "assessments": len(result.assessments),
                "decisions": result.decisions,
            }
            print(MARKER + json.dumps(record, ensure_ascii=False))
            if first_accept is None:
                for a in result.assessments:
                    if a.decision.value in ("accept", "accept_with_warnings"):
                        first_accept = a
                        break
        if first_accept is not None:
            trace = build_trace(first_accept, normalized_store=pipeline.normalized,
                                raw_repository=pipeline.raw, catalog_by_id=by_id)
            print(TRACE_BEGIN)
            print(render_trace(trace))
            print(TRACE_END)
        else:
            print("no accepted assessment produced (trace unavailable)")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
