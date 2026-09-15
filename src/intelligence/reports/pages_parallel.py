"""Morning Delivery `/v2` 並走公開の検証と組み立て（Phase 4 P4-3b2a v0.1.0）。

P4-3a が出した**凍結済みの公開安全 artifact 4 点**を受け取り、公開契約を検証してから
`/v2` 配信ディレクトリを組み立てる**publication boundary 層**である。

    抽出済み artifact ディレクトリ（4 file）
      → validate_publication_artifacts()   公開契約の検証（fail closed）
      → assemble_v2_publication()          隔離 staging → 検証 → v2 へ差し替え
      → v2/ （index.html ＋ 承認済み 4 file ＝ ちょうど 5 file）

規律:
- **入力先も出力先も明示指定必須。** 既定 path へ fallback しない。リポジトリの
  `output/v2` を暗黙の既定にしない。
- **公開語彙を再実装しない。** `delivery` / `market_signal` / `delivery_emit` の
  凍結済み公開シンボルを import して使う（5 ラベルも公開 key 集合も書き写さない）。
- **legacy root を持たない・作らない・触らない。** 書き込むのは明示された v2 宛先と、
  その差し替えに使う同階層の一時ディレクトリだけ。`index.html`（root）・`history/**`・
  `legacy.html` には一切関与しない。
- **wildcard copy をしない。** 承認済みの論理名を 1 つずつ copy する。
- **第二の内容ポリシーを作らない。** 公開 JSON へは凍結済みの
  `FORBIDDEN_PUBLIC_SUBSTRINGS` をそのまま適用する。Markdown は P4-1 が凍結した
  顧客安全バイト列であり、その同一性は digest 照合で担保する（別基準で再検閲しない）。
- **canonical store を作らない。** JSONL も SQLite も DB も cache も履歴 index も作らない。
  入力は派生 publication input であって正本ではない。
- **ネットワークを使わない。** GitHub API も artifact download も行わない
  （run 選択と download は P4-3b2b、本番 Pages 統合は P4-3b2c の別 gate）。
- **時計を読まない。** JST 当日は呼び出し側が明示的に渡す（純関数として検証可能にする）。
- Decision / formal review / corpus / replay / shadow review / evaluation と
  legacy（notifiers / main / 旧 report・analysis・collectors 系）/ 外部記事基盤 /
  Phase 5 / 生成モデルは import しない。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .delivery import (
    FORBIDDEN_PUBLIC_SUBSTRINGS,
    PUBLIC_KEYS,
    PUBLIC_SIGNAL_KEYS,
    PUBLIC_UNAVAILABLE_REASONS,
    canonical_delivery,
)
from .delivery_emit import (
    DELIVERY_DIRNAME,
    LATEST_JSON,
    LATEST_MARKDOWN,
    dated_json_name,
    dated_markdown_name,
)
from .market_signal import SIGNAL_LEVEL_JA

PAGES_PARALLEL_VERSION = "0.1.0"

#: 公開ディレクトリ名（`delivery_emit` の宣言を再定義しない）
V2_DIRNAME = DELIVERY_DIRNAME
#: 並走 route の固定リンクページ（静的テンプレートを copy するだけ・生成しない）
INDEX_NAME = "index.html"

_DATED_MARKDOWN = re.compile(r"\A(\d{4}-\d{2}-\d{2})_morning_brief\.md\Z")
_DATED_JSON = re.compile(r"\A(\d{4}-\d{2}-\d{2})_morning_brief\.json\Z")
_ISO_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_SHA256_HEX = re.compile(r"\A[0-9a-f]{64}\Z")

#: 入力ディレクトリに現れてはならない種別（承認済み 4 file 以外は無視せず**拒否**する）
_REJECTED_SUFFIXES = (".html", ".htm", ".sqlite3", ".sqlite", ".db", ".jsonl", ".part")
_REJECTED_STEMS = ("index",)


class PublicationRejected(ValueError):
    """公開契約を満たさない入力（fail closed）。

    欠けた値を代替で埋めない。部分的に公開しない。
    """


def _reject(reason: str) -> "PublicationRejected":
    return PublicationRejected(reason)


def _valid_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        return False
    year, month, day = (int(part) for part in value.split("-"))
    try:
        date(year, month, day)          # 暦として成立するか。**現在時刻は読まない**
    except ValueError:
        return False
    return True


@dataclass(frozen=True, kw_only=True)
class ValidatedPublication:
    """検証を通過した公開入力の要約（公開して安全な値だけを持つ）。"""

    session_date: str
    reference_session: str
    dated_markdown: str
    dated_json: str
    markdown_sha256: str
    markdown_bytes: int
    json_sha256: str
    json_bytes: int
    signal_available: bool
    artifact_names: Tuple[str, ...]
    published_names: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        return {
            "session_date": self.session_date,
            "reference_session": self.reference_session,
            "dated_markdown": self.dated_markdown,
            "dated_json": self.dated_json,
            "markdown_sha256": self.markdown_sha256,
            "markdown_bytes": self.markdown_bytes,
            "json_sha256": self.json_sha256,
            "json_bytes": self.json_bytes,
            "signal_available": self.signal_available,
            "artifact_names": list(self.artifact_names),
            "published_names": list(self.published_names),
        }


def _entry_names(artifact_dir: Path) -> List[str]:
    """入力ディレクトリの**全 entry**（ディレクトリ・隠しも数える）。"""
    return sorted(entry.name for entry in artifact_dir.iterdir())


def _check_entry_shape(artifact_dir: Path) -> None:
    entries = sorted(artifact_dir.iterdir(), key=lambda p: p.name)
    if len(entries) != 4:
        raise _reject(f"artifact directory must hold exactly 4 entries, found {len(entries)}: "
                      f"{[e.name for e in entries]}")
    for entry in entries:
        if entry.is_dir():
            raise _reject(f"subdirectory is not publishable: {entry.name}")
        if not entry.is_file():
            raise _reject(f"non-regular entry is not publishable: {entry.name}")
        if entry.name.startswith("."):
            raise _reject(f"hidden entry is not publishable: {entry.name}")
        lowered = entry.name.lower()
        for suffix in _REJECTED_SUFFIXES:
            if lowered.endswith(suffix):
                raise _reject(f"unapproved artifact kind ({suffix}): {entry.name}")
        for stem in _REJECTED_STEMS:
            if lowered.startswith(stem):
                raise _reject(f"unapproved artifact name: {entry.name}")


def _sole_match(names: Sequence[str], pattern: "re.Pattern[str]", label: str) -> Tuple[str, str]:
    matched = [(name, pattern.match(name).group(1)) for name in names  # type: ignore[union-attr]
               if pattern.match(name)]
    if len(matched) != 1:
        raise _reject(f"expected exactly one {label}, found {len(matched)}: "
                      f"{[name for name, _ in matched]}")
    return matched[0]


def _read_nonempty(path: Path, label: str) -> bytes:
    if not path.is_file():
        raise _reject(f"missing approved artifact: {label}")
    data = path.read_bytes()
    if not data:
        raise _reject(f"empty approved artifact: {label}")
    return data


def _check_public_payload(payload: object, *, raw_json: str, session_date: str,
                          markdown: bytes) -> Tuple[str, bool]:
    if not isinstance(payload, dict):
        raise _reject("public JSON must be a JSON object")
    if tuple(sorted(payload)) != tuple(sorted(PUBLIC_KEYS)):
        raise _reject(f"public key set drifted from the frozen contract: {sorted(payload)}")
    signal = payload.get("signal")
    if not isinstance(signal, dict):
        raise _reject("public signal must be a JSON object")
    if tuple(sorted(signal)) != tuple(sorted(PUBLIC_SIGNAL_KEYS)):
        raise _reject(f"public signal key set drifted from the frozen contract: {sorted(signal)}")

    if payload.get("session_date") != session_date:
        raise _reject(f"public session_date {payload.get('session_date')!r} does not match the "
                      f"dated filename session {session_date!r}")
    reference = payload.get("reference_session")
    if not _valid_iso_date(reference):
        raise _reject(f"reference_session is not a valid date: {reference!r}")
    # 朝の snapshot は「その朝までに揃った session」を参照するため、参照日は当日以前になる。
    if str(reference) > session_date:
        raise _reject(f"reference_session {reference!r} is later than session_date {session_date!r}")

    digest = payload.get("markdown_sha256")
    if not isinstance(digest, str) or not _SHA256_HEX.match(digest):
        raise _reject(f"markdown_sha256 is not a sha256 hex digest: {digest!r}")
    if digest != hashlib.sha256(markdown).hexdigest():
        raise _reject("markdown_sha256 does not match the published Markdown bytes")
    declared = payload.get("markdown_bytes")
    if not isinstance(declared, int) or isinstance(declared, bool):
        raise _reject(f"markdown_bytes is not an integer: {declared!r}")
    if declared != len(markdown):
        raise _reject(f"markdown_bytes {declared} does not match the published Markdown "
                      f"length {len(markdown)}")

    available = signal.get("available")
    if not isinstance(available, bool):
        raise _reject(f"signal.available is not a boolean: {available!r}")
    label = signal.get("label")
    reason = signal.get("unavailable_reason")
    if available:
        if label not in set(SIGNAL_LEVEL_JA.values()):
            raise _reject(f"signal label is not an approved Market Signal label: {label!r}")
        if reason != "":
            raise _reject(f"available signal must not carry an unavailable reason: {reason!r}")
    else:
        if label != "":
            raise _reject(f"unavailable signal must not carry a label: {label!r}")
        if reason not in PUBLIC_UNAVAILABLE_REASONS:
            raise _reject(f"unavailable reason is not publishable: {reason!r}")

    # 凍結済みの最終防壁をそのまま適用する（第二の内容ポリシーを作らない）。
    canonical = canonical_delivery(payload)
    for forbidden in FORBIDDEN_PUBLIC_SUBSTRINGS:
        if forbidden in canonical or forbidden in raw_json:
            raise _reject(f"internal vocabulary reached the public artifact: {forbidden}")
    return str(payload["session_date"]), available


def validate_publication_artifacts(artifact_dir: Path, *, jst_today: str) -> ValidatedPublication:
    """抽出済み artifact ディレクトリが公開契約を満たすか検証する（純関数・時計を読まない）。

    `jst_today` は呼び出し側が明示的に渡す JST 当日（`YYYY-MM-DD`）。**未来日の
    session だけを拒否する**。連休・祝日・producer の実行間隔により古い session が
    正しいことは通常であるため、古さそのものでは拒否しない
    （公開物は file 名と `session_date` / `reference_session` で自己記述する）。
    """
    if not _valid_iso_date(jst_today):
        raise _reject(f"jst_today must be an explicit YYYY-MM-DD date: {jst_today!r}")
    artifact_dir = Path(artifact_dir)
    if not artifact_dir.is_dir():
        raise _reject(f"artifact directory does not exist: {artifact_dir.name}")

    _check_entry_shape(artifact_dir)
    names = _entry_names(artifact_dir)

    dated_markdown, markdown_session = _sole_match(names, _DATED_MARKDOWN, "dated Markdown")
    dated_json, json_session = _sole_match(names, _DATED_JSON, "dated JSON")
    if markdown_session != json_session:
        raise _reject(f"dated artifacts disagree on session date: "
                      f"{markdown_session} vs {json_session}")
    session_date = markdown_session
    if not _valid_iso_date(session_date):
        raise _reject(f"dated filename session is not a valid date: {session_date!r}")
    if session_date > jst_today:
        raise _reject(f"session_date {session_date} is later than the supplied JST today "
                      f"{jst_today}")
    if set(names) != {dated_markdown, dated_json, LATEST_MARKDOWN, LATEST_JSON}:
        raise _reject(f"artifact set is not the approved four: {names}")

    latest_markdown = _read_nonempty(artifact_dir / LATEST_MARKDOWN, LATEST_MARKDOWN)
    latest_json_bytes = _read_nonempty(artifact_dir / LATEST_JSON, LATEST_JSON)
    dated_markdown_bytes = _read_nonempty(artifact_dir / dated_markdown, dated_markdown)
    dated_json_bytes = _read_nonempty(artifact_dir / dated_json, dated_json)

    if dated_markdown_bytes != latest_markdown:
        raise _reject("dated Markdown and latest Markdown are not byte-identical")
    if dated_json_bytes != latest_json_bytes:
        raise _reject("dated JSON and latest JSON are not byte-identical")

    try:
        raw_json = latest_json_bytes.decode("utf-8", errors="strict")
        payload = json.loads(raw_json)
    except (UnicodeDecodeError, ValueError) as exc:
        raise _reject(f"public JSON does not parse: {exc.__class__.__name__}") from None

    _, available = _check_public_payload(payload, raw_json=raw_json,
                                         session_date=session_date, markdown=latest_markdown)

    approved = (dated_markdown, dated_json, LATEST_MARKDOWN, LATEST_JSON)
    return ValidatedPublication(
        session_date=session_date,
        reference_session=str(payload["reference_session"]),
        dated_markdown=dated_markdown,
        dated_json=dated_json,
        markdown_sha256=hashlib.sha256(latest_markdown).hexdigest(),
        markdown_bytes=len(latest_markdown),
        json_sha256=hashlib.sha256(latest_json_bytes).hexdigest(),
        json_bytes=len(latest_json_bytes),
        signal_available=available,
        artifact_names=approved,
        published_names=tuple(sorted(approved + (INDEX_NAME,))),
    )


def published_names(session_date: str) -> Tuple[str, ...]:
    """`/v2` に置いてよい file 名（この 5 つ以外を置かない）。"""
    return tuple(sorted((dated_markdown_name(session_date), dated_json_name(session_date),
                         LATEST_MARKDOWN, LATEST_JSON, INDEX_NAME)))


def _verify_staged_tree(staging: Path, validated: ValidatedPublication,
                        artifact_dir: Path, index_template: Path) -> None:
    """差し替える**前**に、組み上がった tree が期待どおりかを実測する。"""
    entries = sorted(staging.iterdir(), key=lambda p: p.name)
    if any(entry.is_dir() for entry in entries):
        raise _reject("staged v2 tree must not contain a subdirectory")
    staged = tuple(entry.name for entry in entries)
    if staged != validated.published_names:
        raise _reject(f"staged v2 tree is not the approved five: {list(staged)}")
    for name in validated.artifact_names:
        if (staging / name).read_bytes() != (artifact_dir / name).read_bytes():
            raise _reject(f"staged artifact differs from its source: {name}")
    if (staging / INDEX_NAME).read_bytes() != index_template.read_bytes():
        raise _reject("staged index page differs from the static template")


def _swap_into_place(staging: Path, destination: Path) -> None:
    """staging を `destination` へ差し替える。

    **原子性の現実的な境界**: 宛先が無ければ rename 1 回で入れ替わる。既存の
    `v2` がある場合は「退避 → 差し替え」の rename 2 回になり、POSIX は複数 rename に
    またがる原子性を提供しないため **一括の原子性は保証しない**。差し替えに失敗した
    場合は退避した直前の good state を戻してから例外を伝播させる。
    """
    if not destination.exists():
        os.replace(staging, destination)
        return
    holder = Path(tempfile.mkdtemp(dir=destination.parent, prefix=f".{destination.name}.old-"))
    retired = holder / destination.name
    os.replace(destination, retired)
    try:
        os.replace(staging, destination)
    except BaseException:
        os.replace(retired, destination)          # 直前の good state を戻す
        raise
    finally:
        shutil.rmtree(holder, ignore_errors=True)


def assemble_v2_publication(*, artifact_dir: Path, v2_destination: Path, jst_today: str,
                            index_template: Path) -> ValidatedPublication:
    """検証を通過した場合にだけ `/v2` を組み立てる。**legacy root には触れない。**

    宛先の basename は `v2` でなければならない（root や history を宛先にできない）。
    親ディレクトリは呼び出し側が用意しておく（この層は Pages root を作らない）。
    """
    destination = Path(v2_destination)
    if destination.name != V2_DIRNAME:
        raise _reject(f"v2 destination basename must be {V2_DIRNAME!r}: {destination.name!r}")
    parent = destination.parent
    if not parent.is_dir():
        raise _reject(f"v2 destination parent does not exist: {parent.name}")
    template = Path(index_template)
    if not template.is_file():
        raise _reject(f"static index template does not exist: {template.name}")

    validated = validate_publication_artifacts(artifact_dir, jst_today=jst_today)

    staging = Path(tempfile.mkdtemp(dir=parent, prefix=f".{destination.name}.tmp-"))
    try:
        for name in validated.artifact_names:          # 承認済みの論理名を 1 つずつ
            shutil.copyfile(Path(artifact_dir) / name, staging / name)
        shutil.copyfile(template, staging / INDEX_NAME)
        _verify_staged_tree(staging, validated, Path(artifact_dir), template)
        _swap_into_place(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)     # 半端な staging を残さない
        raise
    return validated


# ---------------------------------------------------------------- CLI（b2b/b2c 用の薄い入口）

def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P43B2A_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4 P4-3b2a: Morning Delivery /v2 並走公開の検証と組み立て")
    parser.add_argument("--artifact-dir", required=True,
                        help="抽出済み Morning Delivery artifact ディレクトリ（4 file）")
    parser.add_argument("--v2-destination", required=True,
                        help="組み立て先（basename は v2）")
    parser.add_argument("--jst-today", required=True,
                        help="JST 当日 YYYY-MM-DD（未来 session の拒否に使う）")
    parser.add_argument("--index-template", required=True,
                        help="固定リンクページの静的テンプレート")
    parser.add_argument("--validate-only", action="store_true",
                        help="検証だけ行い、組み立てはしない")
    args = parser.parse_args(argv)

    _emit("HEAD", {
        "module": "src.intelligence.reports.pages_parallel",
        "version": PAGES_PARALLEL_VERSION,
        "v2_dirname": V2_DIRNAME,
        "validate_only": bool(args.validate_only),
        "uses_network": False,
        "writes_canonical_store": False,
        "touches_pages_root": False,
    })
    try:
        if args.validate_only:
            validated = validate_publication_artifacts(Path(args.artifact_dir),
                                                       jst_today=args.jst_today)
        else:
            validated = assemble_v2_publication(
                artifact_dir=Path(args.artifact_dir),
                v2_destination=Path(args.v2_destination),
                jst_today=args.jst_today,
                index_template=Path(args.index_template))
    except PublicationRejected as exc:
        _emit("REJECTED", {"reason": str(exc)})
        _emit("END", {"result": "REJECTED"})
        return 1

    _emit("INPUT", {"jst_today": args.jst_today,
                    "session_date": validated.session_date,
                    "reference_session": validated.reference_session,
                    "artifact_names": list(validated.artifact_names)})
    _emit("PUBLISHED", {"count": 0 if args.validate_only else len(validated.published_names),
                        "names": [] if args.validate_only else list(validated.published_names),
                        "markdown_bytes": validated.markdown_bytes,
                        "markdown_sha256": validated.markdown_sha256,
                        "json_bytes": validated.json_bytes,
                        "json_sha256": validated.json_sha256,
                        "signal_available": validated.signal_available})
    _emit("END", {"result": "OK", "session_date": validated.session_date})
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
