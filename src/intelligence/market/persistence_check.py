"""永続化検証（Phase 2-D PART A gate / restart相当の別プロセス再オープン）。

書き込みに使ったプロセスの**メモリ状態を一切共有しない**別プロセスとして起動し:
1. data rootのcanonical JSONLを読み戻せること
2. SQLite indexを**空から全再構築**できること（canonical=正の実証）
3. 指定系列のlatest（trading_session基準）が親プロセスの結果と一致すること
を機械可読JSONで報告する。呼び出し側（pilot/テスト）が結果を突き合わせる。

ephemeral workspaceでの実行自体は「恒久保存」の証明にはならない——本チェックが
証明するのは「INTELLIGENCE_DATA_ROOTが指す媒体にあるcanonicalだけから、
別プロセスが同一の最新状態を復元できる」こと（媒体の恒久性はユーザーの
永続ディスク/バックアップ運用が担い、backup.pyのmanifest検証で照合する）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check(data_root: Path, series_ids: list) -> dict:
    from ..core.paths import market_bank_root
    from .store import MarketBankStore

    root = market_bank_root(data_root)
    store = MarketBankStore(root)
    # index破棄→canonicalのみから全再構築（正がJSONLであることの実証）
    indexed_obs, indexed_assessments = store.index.rebuild(
        store.normalized.iter_observations(), store.qa.iter_assessments())
    result = {
        "data_root": str(data_root),
        "canonical_observations": sum(1 for _ in store.normalized.iter_observations()),
        "canonical_assessments": sum(1 for _ in store.qa.iter_assessments()),
        "recovered_lines": store.normalized.recovered_lines,
        "index_rebuilt_observations": indexed_obs,
        "index_rebuilt_assessments": indexed_assessments,
        "latest": {},
    }
    for series_id in series_ids:
        row = store.index.latest_trading_session(series_id)
        result["latest"][series_id] = (
            None if row is None else {
                "observation_id": row["observation_id"],
                "trading_date": row["trading_date"],
                "value": row["value"],
                "source_id": row["source_id"],
            })
    store.close()
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="P2-D persistence validation (fresh process)")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--series", action="append", default=[])
    args = parser.parse_args(argv)
    print(json.dumps(check(Path(args.data_root), args.series), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
