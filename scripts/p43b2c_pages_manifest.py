#!/usr/bin/env python3
"""GitHub Actions 用（P4-3b2c）: Pages staging tree の manifest 作成・比較・構造検査。

**CI 配管専用**であり、配信物の内容には一切関与しない。責務は次の 3 つだけ:

  1. build   — tree を `(相対 POSIX path, sha256, byte 数)` の決定論的 manifest にする
  2. verify  — legacy 部分が `/v2` 追加の前後で **byte 単位に同一**であることを実測する
  3. hygiene — 公開 tree の**構造・path・secret 衛生**だけを検査する

**やらないこと**: `/v2` の公開内容の検証（凍結 P4-3b2a の責務）/ Pages への deploy /
リポジトリへの書き込み / ネットワーク / `src.intelligence` の import / 時計依存の判断。

`hygiene` は **b2c 固有の構造検査に限る**。凍結 b2a の内部語彙契約
（`FORBIDDEN_PUBLIC_SUBSTRINGS`）は legacy レポート本文へ**適用しない**
——legacy の散文には同じ語が日常的に現れるため誤検知になる。`/v2` の内容安全性の
権威は凍結 b2a のままである。

標準ライブラリのみを使う。絶対 path を出力しない（root は basename だけを報告する）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

MANIFEST_VERSION = "0.1.0"

#: 並走 route のディレクトリ名（比較から除外してよい唯一の top level entry）
V2_DIRNAME = "v2"
#: legacy root の必須 file
INDEX_NAME = "index.html"

#: 内容走査の上限（生成 HTML が大きいため 1 file あたりで打ち切る）
MAX_SCAN_BYTES = 8 * 1024 * 1024
#: 内容走査の対象（画像等のバイナリは対象外）
SCANNED_SUFFIXES = (".html", ".htm", ".md", ".json", ".txt", ".xml", ".csv")

#: 公開 tree に現れてはならない種別（派生データ・資格情報・書庫）
FORBIDDEN_SUFFIXES = (".pdf", ".sqlite", ".sqlite3", ".db", ".jsonl", ".parquet",
                      ".zip", ".tar", ".gz", ".env", ".pem", ".key", ".part", ".log")
#: 公開 tree に現れてはならない path 断片（内部 store / 機密 source の混入検知）
FORBIDDEN_PATH_SEGMENTS = ("compass", "corpus", "evidence", "governance", "decision",
                           "candidate", "market_bank", "knowledge", "intelligence_data")

#: runner / 開発機の絶対 path（公開物へ出てはならない）
_RUNNER_PATH = re.compile(r"/home/runner/|/Users/[A-Za-z0-9_.-]+/|C:\\\\Users\\\\")
#: 明確に秘密の形をしたリテラル（alternation を組み立てて自己一致を避ける）
_SECRET_SHAPES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("github_pat", re.compile(r"\bghp" + r"_[A-Za-z0-9]{20,}\b")),
    ("github_fine_grained_pat", re.compile(r"\bgithub" + r"_pat_[A-Za-z0-9_]{20,}\b")),
    ("anthropic_api_key", re.compile(r"sk-" + r"ant-[A-Za-z0-9_\-]{16,}")),
    ("aws_access_key_id", re.compile(r"\bAKIA" + r"[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_header", re.compile(r"\bAuthorization:\s*Bearer\s+[A-Za-z0-9._\-]{16,}")),
)


class ManifestRejected(RuntimeError):
    """tree が公開 staging として受け入れられない（fail closed）。"""


# ---------------------------------------------------------------- tree walk

def _require_directory(root: Path) -> Path:
    if root.is_symlink():
        raise ManifestRejected(f"root is a symlink: {root.name}")
    if not root.is_dir():
        raise ManifestRejected(f"root is not a directory: {root.name}")
    return root


def iter_files(root: Path) -> Iterator[Tuple[str, Path]]:
    """root 配下の全 file を `(相対 POSIX path, path)` で返す。

    symlink は file / ディレクトリを問わず**拒否**する（follow もしない）。
    解決後の path が root の外を指すものも拒否する（path escape 防御）。
    """
    root = _require_directory(Path(root))
    anchor = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        for name in sorted(dirnames):
            if (here / name).is_symlink():
                raise ManifestRejected(
                    f"symlinked directory is not publishable: "
                    f"{(here / name).relative_to(root).as_posix()}")
        dirnames[:] = sorted(dirnames)
        for name in sorted(filenames):
            path = here / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ManifestRejected(f"symlinked file is not publishable: {relative}")
            resolved = path.resolve()
            if resolved != anchor and anchor not in resolved.parents:
                raise ManifestRejected(f"path escapes the publication root: {relative}")
            yield relative, path


def build_manifest(root: Path, *,
                   exclude_top_level: Sequence[str] = ()) -> List[Dict[str, object]]:
    """決定論的 manifest（相対 path 昇順）を作る。"""
    excluded = set(exclude_top_level)
    entries: List[Dict[str, object]] = []
    for relative, path in iter_files(root):
        if relative.split("/", 1)[0] in excluded:
            continue
        blob = path.read_bytes()
        entries.append({"path": relative,
                        "sha256": hashlib.sha256(blob).hexdigest(),
                        "bytes": len(blob)})
    entries.sort(key=lambda entry: str(entry["path"]))
    return entries


def manifest_digest(entries: Sequence[Dict[str, object]]) -> str:
    """manifest 全体の指紋（1 byte でも違えば変わる）。"""
    canonical = "\n".join(f"{e['path']}\t{e['sha256']}\t{e['bytes']}" for e in entries)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- comparison

def compare_manifests(before: Sequence[Dict[str, object]],
                      after: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """2 つの manifest の差分を返す（`equal` が True なら完全一致）。"""
    left = {str(e["path"]): e for e in before}
    right = {str(e["path"]): e for e in after}
    only_before = sorted(set(left) - set(right))
    only_after = sorted(set(right) - set(left))
    changed = sorted(p for p in set(left) & set(right)
                     if left[p]["sha256"] != right[p]["sha256"]
                     or left[p]["bytes"] != right[p]["bytes"])
    return {"equal": not (only_before or only_after or changed),
            "only_in_before": only_before, "only_in_after": only_after,
            "changed": changed,
            "before_count": len(left), "after_count": len(right)}


def dot_entries(entries: Sequence[Dict[str, object]]) -> List[str]:
    """path 成分に dot 始まりを含む entry（staging 残骸の検出）。"""
    found = []
    for entry in entries:
        relative = str(entry["path"])
        if any(part.startswith(".") for part in relative.split("/")):
            found.append(relative)
    return sorted(found)


def require_legacy_invariants(entries: Sequence[Dict[str, object]]) -> None:
    """legacy 側に独立して要求する不変条件（件数は固定しない）。

    実 tree の形（root の `index.html` と、`history/**` があるならその中身）に
    従うだけで、**歴史的な file 数を固定しない**（毎日増えるため）。
    """
    paths = [str(e["path"]) for e in entries]
    if INDEX_NAME not in paths:
        raise ManifestRejected(f"legacy root {INDEX_NAME} is missing")
    leaked = [p for p in paths if p == V2_DIRNAME or p.startswith(V2_DIRNAME + "/")]
    if leaked:
        raise ManifestRejected(f"legacy manifest must not contain {V2_DIRNAME}/: {leaked[:3]}")
    residue = dot_entries(entries)
    if residue:
        raise ManifestRejected(f"unexpected dot entry in the publication tree: {residue[:3]}")


def verify_v2_shape(root: Path, expected_names: Sequence[str]) -> List[str]:
    """`<root>/v2` が承認済みの 5 file **ちょうど**であることを実測する。"""
    v2 = Path(root) / V2_DIRNAME
    if v2.is_symlink() or not v2.is_dir():
        raise ManifestRejected(f"{V2_DIRNAME} is missing or is not a directory")
    entries = sorted(p.name for p in v2.iterdir())
    if any((v2 / name).is_dir() for name in entries):
        raise ManifestRejected(f"{V2_DIRNAME} must not contain a subdirectory: {entries}")
    if any((v2 / name).is_symlink() for name in entries):
        raise ManifestRejected(f"{V2_DIRNAME} must not contain a symlink: {entries}")
    expected = sorted(expected_names)
    if entries != expected:
        raise ManifestRejected(
            f"{V2_DIRNAME} is not the approved set: found {entries}, expected {expected}")
    return entries


# ---------------------------------------------------------------- hygiene

def hygiene_findings(root: Path) -> List[str]:
    """公開 tree の構造・path・secret 衛生だけを検査する（内容評価はしない）。"""
    findings: List[str] = []
    for relative, path in iter_files(root):
        lowered = relative.lower()
        for suffix in FORBIDDEN_SUFFIXES:
            if lowered.endswith(suffix):
                findings.append(f"forbidden file type {suffix}: {relative}")
        for segment in FORBIDDEN_PATH_SEGMENTS:
            if segment in lowered.split("/"):
                findings.append(f"forbidden path segment {segment!r}: {relative}")
        if not lowered.endswith(SCANNED_SUFFIXES):
            continue
        blob = path.read_bytes()[:MAX_SCAN_BYTES]
        text = blob.decode("utf-8", "ignore")
        if _RUNNER_PATH.search(text):
            findings.append(f"machine-specific absolute path: {relative}")
        for label, pattern in _SECRET_SHAPES:
            if pattern.search(text):
                findings.append(f"secret-shaped literal ({label}): {relative}")
    return sorted(set(findings))


# ---------------------------------------------------------------- CLI

def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P43B2C_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _write_manifest(path: Path, root: Path, entries: List[Dict[str, object]]) -> Dict[str, object]:
    document = {"version": MANIFEST_VERSION, "root_name": Path(root).name,
                "count": len(entries), "digest": manifest_digest(entries),
                "entries": entries}
    path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return document


def _load_manifest(path: Path) -> List[Dict[str, object]]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ManifestRejected("stored manifest carries no usable entries")
    return entries


def _grafted_names(path: Optional[str]) -> List[str]:
    if not path:
        raise ManifestRejected("--grafted is required when /v2 is expected")
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    names = document.get("names")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ManifestRejected("grafted record carries no usable names")
    return names


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P4-3b2c: Pages staging tree の manifest / 構造検査")
    sub = parser.add_subparsers(dest="command")

    build = sub.add_parser("build", help="manifest を作る")
    build.add_argument("--root", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--exclude-top-level", action="append", default=[])

    verify = sub.add_parser("verify", help="legacy 不変と /v2 形状を実測する")
    verify.add_argument("--root", required=True)
    verify.add_argument("--before", required=True)
    verify.add_argument("--expect-v2", choices=("present", "absent"), required=True)
    verify.add_argument("--grafted", default="")

    hygiene = sub.add_parser("hygiene", help="構造・path・secret 衛生を検査する")
    hygiene.add_argument("--root", required=True)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage()
        return 2

    try:
        if args.command == "build":
            entries = build_manifest(Path(args.root),
                                     exclude_top_level=args.exclude_top_level)
            document = _write_manifest(Path(args.output), Path(args.root), entries)
            _emit("MANIFEST", {"stage": "before", "root_name": document["root_name"],
                               "count": document["count"], "digest": document["digest"],
                               "excluded_top_level": sorted(args.exclude_top_level)})
            return 0

        if args.command == "verify":
            before = _load_manifest(Path(args.before))
            after = build_manifest(Path(args.root), exclude_top_level=[V2_DIRNAME])
            difference = compare_manifests(before, after)
            require_legacy_invariants(after)
            v2_present = (Path(args.root) / V2_DIRNAME).exists()
            names: List[str] = []
            if args.expect_v2 == "present":
                names = verify_v2_shape(Path(args.root), _grafted_names(args.grafted))
            elif v2_present:
                raise ManifestRejected(f"{V2_DIRNAME} exists although /v2 was not published")
            _emit("MANIFEST_VERIFY", {
                "legacy_unchanged": difference["equal"],
                "before_digest": manifest_digest(before),
                "after_digest": manifest_digest(after),
                "legacy_count": difference["after_count"],
                "only_in_before": difference["only_in_before"][:5],
                "only_in_after": difference["only_in_after"][:5],
                "changed": difference["changed"][:5],
                "v2_expected": args.expect_v2, "v2_present": v2_present,
                "v2_names": names})
            if not difference["equal"]:
                _emit("LEGACY_FAILURE", {"reason": "legacy tree changed while adding /v2"})
                return 1
            return 0

        if args.command == "hygiene":
            findings = hygiene_findings(Path(args.root))
            _emit("HYGIENE", {"root_name": Path(args.root).name,
                              "finding_count": len(findings), "findings": findings[:10],
                              "result": "PASSED" if not findings else "FAILED"})
            return 1 if findings else 0
    except ManifestRejected as exc:
        _emit("LEGACY_FAILURE", {"reason": str(exc)})
        return 1
    return 2


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
