"""英語ニュース自動翻訳（v2.8・④）— 英語見出しを自然な日本語へ翻訳する。

安全なオプション機能として実装する。ANTHROPIC_API_KEY が設定され `anthropic`
パッケージが使える場合のみ、英語と判定した見出しを日本語へ翻訳して
Headline.title_ja に格納する。未設定・失敗時は何もしない（原文のまま）ため、
既存動作を一切壊さない。表示側は title_ja があれば「日本語 → 原文を見る」の
順で見せる（html_builder側で実装）。

金融用語を優先し、Ticker（NVDA等）や略語（EPS→EPS（一株利益）等）は
補足しつつ維持するようプロンプトで指示する。翻訳結果は同一プロセス内で
キャッシュし、同じ見出しへの二重リクエストを避ける。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import llm_enhancer

logger = logging.getLogger("market_brief")

# 英語判定: ASCII英字が一定割合以上を占め、日本語（かな・カナ・漢字）をほぼ含まない
_JP_RE = re.compile(r"[ぁ-んァ-ン぀-ヿ一-龯]")
_ASCII_ALPHA_RE = re.compile(r"[A-Za-z]")
MAX_TRANSLATE = 40  # 1回の実行で翻訳する最大件数（コスト・時間の上限）

# v3.0（①）: 翻訳キャッシュの永続化。原文タイトルをキーに日本語訳を保存し、
# 翌日以降も再利用してAPIコストを抑える。GitHub Actionsがコミットして蓄積する。
DEFAULT_CACHE_DIR = "data/translation_cache"
CACHE_FILENAME = "translation_cache.json"

_TRANSLATE_INSTRUCTION = (
    "次の英語の金融ニュース見出しを、自然な日本語に翻訳してください。"
    "金融用語を正確に訳し、企業名やTicker（例: NVDA）はそのまま残してください。"
    "EPS・CPI・FOMC・guidance・yield・rate cut等の専門用語は「EPS（一株利益）」"
    "のように必要に応じて日本語補足を付けてください。"
    "原文の意味を変えず、煽り表現は使わず、100文字以内を目安にしてください。"
    "訳文のみを1行で出力し、前置き・引用符・原文は含めないでください。"
)

_cache: Dict[str, str] = {}


def _cache_path(cache_dir) -> Path:
    return Path(cache_dir) / CACHE_FILENAME


def load_cache(cache_dir) -> Dict[str, str]:
    """永続キャッシュを読み込む（壊れていても空dictを返しレポート生成は継続）。"""
    path = _cache_path(cache_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning("翻訳キャッシュの読み込みに失敗しました（空として扱います）: %s", exc)
        return {}


def save_cache(cache_dir, cache: Dict[str, str]) -> None:
    """永続キャッシュを保存する（失敗してもレポート生成は継続）。"""
    try:
        path = _cache_path(cache_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 翻訳失敗（空文字）はキャッシュへ残さない（次回リトライできるように）
        clean = {k: v for k, v in cache.items() if v}
        path.write_text(json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        logger.warning("翻訳キャッシュの保存に失敗しました（無視して継続します）: %s", exc)


def is_english(text: str) -> bool:
    """見出しが英語主体かどうかを判定する（日本語を含めば英語扱いしない）。"""
    if not text or _JP_RE.search(text):
        return False
    alpha = len(_ASCII_ALPHA_RE.findall(text))
    return alpha >= 6 and alpha >= len(text) * 0.4


def translate_text(text: str) -> str:
    """1件を翻訳する。翻訳不可（キー未設定・失敗）なら空文字を返す。"""
    if text in _cache:
        return _cache[text]
    result = llm_enhancer.enhance(
        f"【指示】\n{_TRANSLATE_INSTRUCTION}\n\n【英語見出し】\n{text}",
        max_tokens=200,
    )
    translated = (result or "").strip()
    _cache[text] = translated
    return translated


def translate_headlines(headlines: List, enabled: bool = True, cache_dir: Optional[str] = None) -> int:
    """英語見出しを翻訳して Headline.title_ja に格納する。翻訳した件数を返す。

    v3.0（①）: 永続キャッシュ（cache_dir配下のtranslation_cache.json）を先に読み、
    キャッシュにあれば API を呼ばずに再利用する。キャッシュヒットのみの場合でも
    title_ja は埋まる（API不要）。ANTHROPIC_API_KEY 未設定でも、過去に翻訳して
    キャッシュ済みの見出しは日本語で表示できる。新規翻訳はキーがある時のみ行い、
    実行後にキャッシュを保存する。キャッシュ破損時も原文のまま継続する。
    """
    if not enabled:
        return 0

    persistent = load_cache(cache_dir) if cache_dir is not None else {}
    _cache.update(persistent)  # 永続キャッシュをプロセス内キャッシュへ取り込む
    api_available = llm_enhancer.is_available()

    filled_count = 0   # title_jaを埋めた件数（キャッシュ再利用含む）
    api_calls = 0      # 実際にAPIを呼んだ新規翻訳件数
    cache_dirty = False
    for h in headlines:
        if getattr(h, "title_ja", ""):
            continue
        if not is_english(h.title):
            continue
        # 1) キャッシュ再利用（API不要・キー未設定でも使える）
        cached = _cache.get(h.title)
        if cached:
            h.title_ja = cached
            filled_count += 1
            continue
        # 2) 新規翻訳（APIキーがあり、上限内のときのみ）
        if not api_available or api_calls >= MAX_TRANSLATE:
            continue
        ja = translate_text(h.title)
        api_calls += 1
        if ja and ja != h.title:
            h.title_ja = ja
            _cache[h.title] = ja
            filled_count += 1
            cache_dirty = True

    if cache_dir is not None and cache_dirty:
        save_cache(cache_dir, _cache)
    if filled_count:
        logger.info(
            "英語ニュース自動翻訳: %d件を日本語表示（うち新規翻訳%d件・キャッシュ再利用%d件）。",
            filled_count, api_calls, filled_count - api_calls,
        )
    return filled_count
