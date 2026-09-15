"""Morning Delivery artifact emitter（Phase 4 P4-3a v0.1.0）。

`MorningDelivery` を `output/v2/` 配下の並走 artifact として書き出す**唯一の層**。
束ね方（packaging）は `delivery.py` の純関数が持ち、ここは書き出しだけを担う。

    output/v2/latest_morning_brief.md      … 凍結 Markdown の逐語バイト
    output/v2/latest_morning_brief.json    … 顧客向け公開 JSON
    output/v2/YYYY-MM-DD_morning_brief.md
    output/v2/YYYY-MM-DD_morning_brief.json

規律（`docs/databank/MORNING_DELIVERY_SPEC.md`）:
- **`output/v2/` の承認済み 4 file 以外へ書かない。** legacy 成果物
  （`output/latest_market_brief.*` / `output/history/**`）には触れない。
- **Markdown はバイト単位で verbatim。** 見出しも footer も id も足さない。
- **canonical store を作らない。** JSONL append-only も SQLite も index も作らない
  （これは派生 artifact であって intelligence の正本ではない）。
- **atomic 置換**。同一ディレクトリの temp file へ書いて `os.replace` で差し替える。
  途中失敗で既存の正常な artifact を壊れた内容で上書きしない。
- **冪等**。同じ `MorningDelivery` を 2 回出せば同じバイト列。時刻・乱数・host 依存なし。
- Decision / formal_review / corpus / replay / shadow_review / evaluation と
  legacy（notifiers / main / 旧 report・analysis・collectors 系）/
  外部記事基盤 / Phase 5 / 生成モデルは import しない。**通知もしない**
  （配信経路への接続は P4-3b の bridge gate）。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from .delivery import MorningDelivery, delivery_public_json

#: 並走出力の root（MIGRATION_PLAN Stage 4 の `output/v2/`）
DELIVERY_DIRNAME = "v2"
DEFAULT_OUTPUT_DIR = Path("output") / DELIVERY_DIRNAME

LATEST_MARKDOWN = "latest_morning_brief.md"
LATEST_JSON = "latest_morning_brief.json"


def dated_markdown_name(session_date: str) -> str:
    return f"{session_date}_morning_brief.md"


def dated_json_name(session_date: str) -> str:
    return f"{session_date}_morning_brief.json"


def artifact_names(session_date: str) -> Tuple[str, ...]:
    """P4-3a が書く承認済みファイル名（この 4 つ以外は書かない）。"""
    return (dated_markdown_name(session_date), dated_json_name(session_date),
            LATEST_MARKDOWN, LATEST_JSON)


def delivery_artifacts(delivery: MorningDelivery) -> Dict[str, str]:
    """ファイル名 → 書き出す本文。**先に全バイトを用意する**（部分適用を避けるため）。"""
    markdown = delivery.markdown
    public_json = delivery_public_json(delivery)
    return {
        dated_markdown_name(delivery.session_date): markdown,
        LATEST_MARKDOWN: markdown,
        dated_json_name(delivery.session_date): public_json,
        LATEST_JSON: public_json,
    }


def _atomic_write(target: Path, text: str) -> None:
    """同一ディレクトリの temp file → `os.replace` で 1 file を原子的に差し替える。

    `os.replace` は同一ファイルシステム上で atomic なので、途中失敗しても
    既存の正常な artifact が壊れた内容で残ることはない。
    """
    encoded = text.encode("utf-8")
    handle, temp_name = tempfile.mkstemp(dir=str(target.parent),
                                         prefix=f".{target.name}.", suffix=".part")
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)      # 失敗時に temp を残さない
        raise


def emit_morning_delivery(delivery: MorningDelivery, *,
                          output_dir: Path = DEFAULT_OUTPUT_DIR) -> List[Path]:
    """配信 artifact を `output/v2/` へ書き出し、書いた path を順に返す。

    **原子性の現実的な境界**: 各ファイルの差し替えは `os.replace` により個別に
    atomic である。一方、4 file 全体をまたぐトランザクションは POSIX の
    ファイルシステム API が提供しないため、**4 file 一括の原子性は保証しない**。
    緩和策として、置換を始める前に全バイトを用意し（`delivery_artifacts`）、
    シリアライズ段階の失敗が 1 file も差し替えないようにしている。
    置換の途中で失敗した場合は例外が伝播し、既に差し替えた file はそのまま残る
    （どの file も「古い正しい内容」か「新しい正しい内容」のいずれかであり、
    壊れた内容にはならない）。
    """
    artifacts = delivery_artifacts(delivery)          # 先に全バイトを確定させる
    approved = set(artifact_names(delivery.session_date))
    unexpected = sorted(set(artifacts) - approved)
    if unexpected:
        raise ValueError(f"unapproved delivery artifact names: {unexpected}")

    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for name in sorted(artifacts):
        target = output_dir / name
        _atomic_write(target, artifacts[name])
        written.append(target)
    return written
