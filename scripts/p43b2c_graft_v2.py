#!/usr/bin/env python3
"""GitHub Actions 用（P4-3b2c）: 検証済み `/v2` を Pages staging tree へ接ぎ木する。

**これが Pages staging tree へ書き込む唯一の経路である。** 呼ばれるのは
「凍結 P4-3b2a が組み立てを OK で終え、かつ typed gate が PASS を返した後」だけで、
それまで legacy tree には一切触れない。

規律:

- **承認済みの 5 file を、凍結 b2a が報告した論理名で 1 つずつ copy する。**
  wildcard も再帰探索も `glob` も使わない。ディレクトリを見て名前を推測しない。
- 日付入りの 2 file 名は b2a の検証済み metadata（`::P43B2A_PUBLISHED::` の `names`）
  から来る。ここで日付を組み立て直さない。
- symlink / 6 file 目 / 欠落 / 予期しないサブディレクトリ / dot 残骸 / 宛先の既存を拒否する。
- copy 後に**実測で**照合する（source と byte 同一・ちょうど 5 file）。

**やらないこと**: 公開契約の検証（凍結 b2a の責務）/ 鮮度判定（typed gate の責務）/
legacy root・history への関与 / ネットワーク / リポジトリへの書き込み /
`src.intelligence` の import。

標準ライブラリのみを使う。絶対 path を出力しない。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

GRAFT_VERSION = "0.1.0"

V2_DIRNAME = "v2"
INDEX_NAME = "index.html"
LATEST_MARKDOWN = "latest_morning_brief.md"
LATEST_JSON = "latest_morning_brief.json"
APPROVED_COUNT = 5

_DATED_MARKDOWN = re.compile(r"\A(\d{4}-\d{2}-\d{2})_morning_brief\.md\Z")
_DATED_JSON = re.compile(r"\A(\d{4}-\d{2}-\d{2})_morning_brief\.json\Z")


class GraftRejected(RuntimeError):
    """接ぎ木の前提が崩れている（fail closed。legacy tree は触らない）。"""


def approved_names(names: Sequence[str]) -> List[str]:
    """b2a が報告した名前が承認済みの 5 つちょうどであることを確かめる。"""
    if not isinstance(names, (list, tuple)):
        raise GraftRejected("published names are unusable")
    cleaned = sorted(str(name) for name in names)
    if len(cleaned) != APPROVED_COUNT:
        raise GraftRejected(
            f"expected exactly {APPROVED_COUNT} published names, found {len(cleaned)}: "
            f"{cleaned}")
    for name in cleaned:
        if "/" in name or name.startswith(".") or name in ("", ".", ".."):
            raise GraftRejected(f"published name is not a plain file name: {name!r}")
    dated_markdown = [n for n in cleaned if _DATED_MARKDOWN.match(n)]
    dated_json = [n for n in cleaned if _DATED_JSON.match(n)]
    if len(dated_markdown) != 1 or len(dated_json) != 1:
        raise GraftRejected(f"published names must hold exactly one dated pair: {cleaned}")
    session = _DATED_MARKDOWN.match(dated_markdown[0]).group(1)
    if _DATED_JSON.match(dated_json[0]).group(1) != session:
        raise GraftRejected("dated published names disagree on the session date")
    missing = [n for n in (INDEX_NAME, LATEST_MARKDOWN, LATEST_JSON) if n not in cleaned]
    if missing:
        raise GraftRejected(f"published names are missing fixed members: {missing}")
    return cleaned


def _require_clean_source(staging_v2: Path, names: Sequence[str]) -> None:
    if staging_v2.is_symlink() or not staging_v2.is_dir():
        raise GraftRejected("staged v2 source is missing or is not a directory")
    entries = sorted(p.name for p in staging_v2.iterdir())
    if entries != sorted(names):
        raise GraftRejected(
            f"staged v2 source is not the approved set: found {entries}, "
            f"expected {sorted(names)}")
    for name in entries:
        source = staging_v2 / name
        if source.is_symlink():
            raise GraftRejected(f"staged v2 member is a symlink: {name}")
        if source.is_dir():
            raise GraftRejected(f"staged v2 member is a directory: {name}")
        if not source.is_file():
            raise GraftRejected(f"staged v2 member is not a regular file: {name}")


def graft(*, staging_v2: Path, pages_site: Path,
          names: Sequence[str]) -> Dict[str, object]:
    """検証済み 5 file を `pages-site/v2` へ名前指定で copy する。"""
    staging_v2 = Path(staging_v2)
    pages_site = Path(pages_site)
    approved = approved_names(names)
    _require_clean_source(staging_v2, approved)

    if pages_site.is_symlink() or not pages_site.is_dir():
        raise GraftRejected("pages site root is missing or is not a directory")
    destination = pages_site / V2_DIRNAME
    if destination.exists() or destination.is_symlink():
        raise GraftRejected(f"{V2_DIRNAME} already exists in the pages site")

    destination.mkdir()
    digests: Dict[str, str] = {}
    try:
        for name in approved:                       # 承認済みの論理名を 1 つずつ
            shutil.copyfile(staging_v2 / name, destination / name)
        grafted = sorted(p.name for p in destination.iterdir())
        if grafted != approved:
            raise GraftRejected(f"grafted v2 tree is not the approved set: {grafted}")
        for name in approved:
            source_bytes = (staging_v2 / name).read_bytes()
            placed_bytes = (destination / name).read_bytes()
            if source_bytes != placed_bytes:
                raise GraftRejected(f"grafted file differs from its validated source: {name}")
            digests[name] = hashlib.sha256(placed_bytes).hexdigest()
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)   # 半端な v2 を残さない
        raise

    session = _DATED_MARKDOWN.match(
        next(n for n in approved if _DATED_MARKDOWN.match(n))).group(1)
    return {"graft_version": GRAFT_VERSION, "names": approved, "count": len(approved),
            "session_date": session, "sha256": digests}


# ---------------------------------------------------------------- CLI

def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P43B2C_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _published_names(gate_path: str) -> List[str]:
    try:
        payload = json.loads(Path(gate_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GraftRejected("gate verdict is missing or unreadable") from None
    if not isinstance(payload, dict):
        raise GraftRejected("gate verdict is unusable")
    if payload.get("result") != "PASS":
        raise GraftRejected(f"gate result is not PASS: {payload.get('result')!r}")
    names = payload.get("published_names")
    if not isinstance(names, list):
        raise GraftRejected("gate verdict carries no published names")
    return [str(name) for name in names]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P4-3b2c: 検証済み /v2 を Pages staging tree へ接ぎ木する")
    parser.add_argument("--staging-v2", required=True, help="凍結 b2a が組んだ v2（隔離先）")
    parser.add_argument("--pages-site", required=True, help="legacy Pages staging root")
    parser.add_argument("--gate", required=True, help="typed gate の判定 JSON（PASS 必須）")
    parser.add_argument("--output", default="", help="接ぎ木記録の書き出し先 JSON")
    args = parser.parse_args(argv)

    try:
        record = graft(staging_v2=Path(args.staging_v2), pages_site=Path(args.pages_site),
                       names=_published_names(args.gate))
    except GraftRejected as exc:
        _emit("GRAFT_REJECTED", {"reason": str(exc)})
        return 1
    _emit("GRAFT", record)
    if args.output:
        Path(args.output).write_text(json.dumps(record, ensure_ascii=False, sort_keys=True),
                                     encoding="utf-8")
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
