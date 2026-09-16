"""データ永続化の設置場所解決（Phase 2-D PART A / PERSISTENCE DECISION）。

開発コンテナはephemeral（コンテナ回収でworkspaceは消える）。従って
「コード＝Gitリポジトリ / データ＝ローカル永続領域」を分離し、canonicalデータの
設置場所を**設定可能**にする（GitリポジトリをData Bankとして使わない——
data/vnext/は.gitignore済みであり、履歴への大量データコミットは禁止）。

解決順序（絶対パスのハードコード禁止）:
1. 環境変数 `INTELLIGENCE_DATA_ROOT`（最優先。ユーザーの永続ディスク・
   バックアップ先NAS等、実行環境ごとの差し替え点）
2. config.yaml の `vnext.data_root`（リポジトリ設定。CLAUDE.mdルール8）
3. 既定値 `data/vnext`（カレントディレクトリ相対——従来ストアのdocstringと同一）

方針: 本モジュールは**パス解決のみ**を行う（I/Oはstore側）。ディレクトリ作成は
呼び出し側のstoreが行う（既存storeはroot.mkdir済み）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

#: 環境変数名（実行環境ごとの永続領域差し替え点）
DATA_ROOT_ENV = "INTELLIGENCE_DATA_ROOT"

#: 既定root（相対パス。CWD=リポジトリrootでの従来挙動と一致）
DEFAULT_DATA_ROOT = Path("data") / "vnext"

#: config.yamlのキー（vnext: { data_root: ... }）
CONFIG_SECTION = "vnext"
CONFIG_KEY = "data_root"


def _from_config(config_path: Path) -> Optional[Path]:
    """config.yamlのvnext.data_rootを読む（無ければNone。失敗しても既定へ委ねる）。"""
    if not config_path.is_file():
        return None
    try:
        import yaml  # 既存依存（requirements.txt PyYAML）

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        value = (config.get(CONFIG_SECTION) or {}).get(CONFIG_KEY)
        return Path(str(value)) if value else None
    except Exception:  # noqa: BLE001 設定破損でデータ層を止めない（既定へフォールバック）
        return None


def data_root(*, env: Optional[dict] = None, config_path: Path = Path("config.yaml")) -> Path:
    """canonicalデータのroot。env注入可（テストでos.environへ触らない）。"""
    environ = os.environ if env is None else env
    override = environ.get(DATA_ROOT_ENV, "").strip()
    if override:
        return Path(override)
    from_config = _from_config(config_path)
    if from_config is not None:
        return from_config
    return DEFAULT_DATA_ROOT


def market_bank_root(base: Optional[Path] = None) -> Path:
    """Market Data Bankのroot（<data_root>/databank/market）。

    配下レイアウト（storeが作成する）:
        raw/            … provider応答の生CSV blob（BlobStore）
        normalized/     … observations.jsonl 等（canonical・append-only）
        evidence_qa/    … assessments.jsonl
        index/          … market.sqlite3（再構築可能index。canonicalではない）
        backfill_runs.jsonl … 取得run manifest（append-only監査履歴）
    """
    root = base if base is not None else data_root()
    return root / "databank" / "market"
