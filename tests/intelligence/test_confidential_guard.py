"""CONFIDENTIAL_SOURCE / SENSITIVE_IDENTIFIER の誤コミット防止Guard（Stage 1.6）。

docs/security/DATA_CLASSIFICATION_POLICY.md の機械的執行。
Legacy CIはpytestを実行しないため、このGuardは開発ブランチとローカル実行で機能する
（CI組込みはStage 2の承認事項）。現在のツリーは是正済みのため**strict**（例外なし）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def test_no_pdf_is_git_tracked() -> None:
    """羅針盤等のPDF（CONFIDENTIAL_SOURCE想定拡張子）はpublicリポジトリでtracking禁止。"""
    tracked_pdfs = [f for f in _tracked_files() if f.lower().endswith(".pdf")]
    assert tracked_pdfs == [], (
        "publicリポジトリにPDFがtrackingされています（DATA_CLASSIFICATION_POLICY違反）:\n"
        + "\n".join(tracked_pdfs)
    )


def test_confidential_research_dir_tracks_only_readme() -> None:
    bad = [
        f for f in _tracked_files()
        if f.startswith("research/source_docs/") and Path(f).name != "README.md"
    ]
    assert bad == [], "research/source_docs/ はREADME以外tracking禁止:\n" + "\n".join(bad)


def test_confidential_paths_are_gitignored() -> None:
    """保護対象パスに置かれたファイルがgitに無視されることを実地検証する。"""
    probes = [
        "research/source_docs/compass/2099-01-01.pdf",
        "date/rashinban/2099_0101_1.pdf",
        "cloudflare/.wrangler/cache/anything.json",
        "data/vnext/anything.jsonl",
    ]
    for probe in probes:
        rc = subprocess.run(
            ["git", "check-ignore", "-q", probe], cwd=REPO_ROOT
        ).returncode
        assert rc == 0, f"{probe} が.gitignoreで保護されていません"


def test_sensitive_identifier_files_not_tracked() -> None:
    tracked = set(_tracked_files())
    for path in (
        "cloudflare/private-insight-wrangler.toml",
        "cloudflare/.wrangler/cache/wrangler-account.json",
    ):
        assert path not in tracked, f"SENSITIVE_IDENTIFIERファイルがtracking中: {path}"


def test_vnext_code_never_references_confidential_paths() -> None:
    """vNextコードがCONFIDENTIAL_SOURCEのパスを読み書きしないこと
    （本文をpublic出力・LLM送信経路へ流し込まない構造的担保の一部）。"""
    forbidden = ("date/rashinban", "research/source_docs")
    violations = []
    for py in (REPO_ROOT / "src" / "intelligence").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                violations.append(f"{py.relative_to(REPO_ROOT)}: '{token}'")
    assert violations == [], (
        "vNextコードは機密研究パスへ直接アクセスしない（承認済みresearch層を将来設ける）:\n"
        + "\n".join(violations)
    )
