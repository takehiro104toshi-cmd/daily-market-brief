"""バックアップ基盤（Phase 2-D PART A / 手動・外部同期の土台）。

方針: 本フェーズでは**バックアップの土台のみ**（自動スケジューラ・世代管理は将来）。
data root配下のファイル台帳（inventory）＋sha256＋スキーマ情報を持つmanifestを
決定論的に生成し、別媒体へコピーした後の**検証**（verify）を可能にする。

- manifestはJSON 1ファイル（<data_root>/backup/manifest_<UTC時刻>.json）。
- SQLite indexは再構築可能な導出物だが、checksumはmanifestへ記録する
  （コピー先での破損検知用。indexが無くてもcanonical JSONLから再構築できる）。
- Secret・資格情報はdata root配下に存在しない設計（P1-C規律）だが、
  manifest自体もファイル名・ハッシュ・サイズのみでコンテンツを含まない。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .types import SCHEMA_VERSION

MANIFEST_VERSION = "1.0.0"

#: inventory対象から除く名前（一時ファイル・manifest自身の格納先）
_EXCLUDED_DIRS = {"backup"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_backup_manifest(root: Path, *, now: Optional[datetime] = None) -> Dict:
    """data root配下のfile inventory＋sha256を持つmanifest dictを生成する。"""
    root = Path(root)
    files: List[Dict] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in _EXCLUDED_DIRS:
            continue
        if path.name.startswith(".") and path.suffix == ".tmp":
            continue  # blob書き込み中の一時ファイル
        size = path.stat().st_size
        files.append({
            "path": rel.as_posix(),
            "size": size,
            "sha256": _sha256_file(path),
        })
        total += size
    return {
        "manifest_version": MANIFEST_VERSION,
        "schema_version": SCHEMA_VERSION,
        "created_at": (now or datetime.now(timezone.utc)).isoformat(),
        "root": root.as_posix(),
        "file_count": len(files),
        "total_bytes": total,
        "files": files,
    }


def write_backup_manifest(root: Path, *, now: Optional[datetime] = None) -> Path:
    """manifestを<root>/backup/へ書き出しパスを返す。"""
    manifest = build_backup_manifest(root, now=now)
    ts = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(root) / "backup"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"manifest_{ts}.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def verify_against_manifest(root: Path, manifest: Dict) -> Tuple[List[str], List[str], List[str]]:
    """コピー先root vs manifest → (missing, changed, extra) のrelパス一覧。

    missing/changedが空ならバックアップは検証OK（extraは情報提供——
    コピー後に新規追記されたJSONL等。破損とは区別する）。
    """
    root = Path(root)
    expected = {f["path"]: f for f in manifest.get("files", [])}
    actual = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in _EXCLUDED_DIRS:
            continue
        actual[rel.as_posix()] = path
    missing = [p for p in expected if p not in actual]
    changed = [
        p for p, meta in expected.items()
        if p in actual and (
            actual[p].stat().st_size != meta["size"] or _sha256_file(actual[p]) != meta["sha256"]
        )
    ]
    extra = [p for p in actual if p not in expected]
    return missing, changed, extra
