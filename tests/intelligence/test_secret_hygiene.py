"""リポジトリ全体のsecret混入ガード（PROJECT-WIDE RETROACTIVE AUDIT）。

原則: credentialは**runtime injectionのみ**。追跡対象ファイルへ実値を置かない。
既存の `test_knowledge_assets.py` は knowledge/ 配下のYAMLのみを対象にしていた
ため、docs/・src/・tests/・workflowを含む**追跡ファイル全体**へ範囲を広げる。

検出対象は「形が明確に秘密である」リテラルに限定する（誤検知で開発を止めない）。
env変数名・定数名・`${{ secrets.X }}` 参照は秘密ではないので対象外。
"""
from __future__ import annotations

import re
import subprocess

#: 明確に秘密の形をしたリテラル（プロバイダ発行のキー形式）
SECRET_PATTERNS = {
    "anthropic_api_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    "openai_api_key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "github_pat": re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    "github_fine_grained_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key_id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
}

#: credentialをURLクエリへ載せた形（永続化locatorへ秘密が残る事故の形）
CREDENTIAL_IN_QUERY = re.compile(
    r"[?&](refreshtoken|api_?key|apikey|token|password|subscription-key|appid)="
    r"[A-Za-z0-9_\-]{12,}", re.IGNORECASE)

#: バイナリ・生成物は対象外
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip",
                 ".woff", ".woff2", ".sqlite3", ".db")


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    for name in out.stdout.decode("utf-8").split("\0"):
        if name and not name.lower().endswith(SKIP_SUFFIXES):
            yield name


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except (OSError, IsADirectoryError):  # pragma: no cover
        return b""


#: 全追跡ファイルの走査は1回だけ行い、両検査で共有する（テスト時間の抑制）
_SELF = "tests/intelligence/test_secret_hygiene.py"


#: 追跡ファイルは output/history/ 等の生成HTMLを含み総量が大きいため、
#: まず全パターンを1本のalternationで粗くふるい、当たったファイルだけ
#: 個別パターンで特定する（検出力は同じで走査コストだけ下げる）。
#: 追跡ファイルは output/history/ 等の生成HTMLを含み総量が大きい。
#: utf-8デコードを避けてbytesのまま粗くふるい、当たったファイルだけ
#: デコードして個別パターンで特定する（検出力は同じで走査コストを下げる）。
_ANY_SECRET_B = re.compile(
    "|".join(f"(?:{p.pattern})" for p in SECRET_PATTERNS.values()).encode())
_CREDENTIAL_IN_QUERY_B = re.compile(CREDENTIAL_IN_QUERY.pattern.encode(), re.IGNORECASE)


def _scan_tracked_files():
    """追跡ファイルを1回だけ走査して (秘密形リテラル, credential付きURL) を返す。"""
    secret_hits, url_hits = [], []
    for path in _tracked_text_files():
        blob = _read_bytes(path)
        if _ANY_SECRET_B.search(blob):
            text = blob.decode("utf-8", "ignore")
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    # 値そのものは**絶対に出力しない**（検知のためにも出さない）
                    secret_hits.append(f"{path}: {label}")
        if path != _SELF and _CREDENTIAL_IN_QUERY_B.search(blob):
            url_hits.append(path)
    return secret_hits, url_hits


_SCAN_CACHE = None


def _scan():
    global _SCAN_CACHE
    if _SCAN_CACHE is None:
        _SCAN_CACHE = _scan_tracked_files()
    return _SCAN_CACHE


def test_no_secret_shaped_literals_in_tracked_files():
    """追跡ファイルにプロバイダ発行キー形式のリテラルが存在しない。"""
    secret_hits, _ = _scan()
    assert secret_hits == [], f"秘密の形をしたリテラルを検出: {secret_hits}"


def test_no_credential_bearing_urls_in_tracked_files():
    """credentialをクエリに載せたURLが追跡ファイルへ残っていない。

    URLはRawItem.locator / FetchAttempt.url として**永続化される**ため、
    ここに秘密が載る設計・記録は事故に直結する。
    """
    _, url_hits = _scan()
    assert url_hits == [], f"credentialを含むURLらしき記述を検出: {url_hits}"


def test_jquants_v2_sends_api_key_only_as_header():
    """V2 providerがAPI KeyをURLではなくヘッダでのみ送る（永続化locatorに残さない）。"""
    from datetime import date
    from pathlib import Path

    from src.intelligence.market.jquants_v2 import (
        AUTH_HEADER,
        ENV_API_KEY,
        JQuantsV2TopixProvider,
    )
    from src.intelligence.market.series_catalog import load_catalog

    secret = "SYNTHETIC-KEY-FOR-TEST-ONLY"
    seen = []

    def http(url, method, headers, body):
        seen.append((url, dict(headers)))
        return 200, b'{"data": [{"Date": "2026-09-01", "O": "1", "H": "2", "L": "0", "C": "1"}]}'

    catalog = load_catalog(Path("knowledge/market_series/core_series.yaml"))
    spec = catalog.get("index:topix.close.closing.tokyo")
    provider = JQuantsV2TopixProvider(http, env={ENV_API_KEY: secret})
    result = provider.fetch_daily_history(spec, start=date(2026, 8, 1),
                                          end=date(2026, 9, 1))

    assert result.error_kind == ""
    assert seen, "リクエストが発行されていない"
    for url, headers in seen:
        assert secret not in url            # URLへ載せない（＝永続化されない）
        assert headers.get(AUTH_HEADER) == secret
    assert secret not in result.url
    assert secret not in result.body.decode("utf-8")
    assert secret not in result.error_detail
