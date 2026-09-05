"""決定論テキストマッチ基盤（Phase 2-E L1/L2共通・意味推論なし）。

規則（TICKER SAFETY / alias安全の実装基盤）:
- ASCII語:
  - **全大文字略語**（AI・EV・US・NATO等）… 大文字表記そのままの単語境界マッチのみ
    （小文字"ai"や語中の"AI"にはマッチしない——一般語への誤爆防止）
  - **"="プレフィクス付き語**（"=Fed"等）… 表記そのまま（case-sensitive）の
    単語境界マッチ（"fed the dog"の動詞fedへ誤爆しない。カタログ側で明示指定）
  - それ以外 … case-insensitiveの単語境界マッチ（"Semiconductor"/"semiconductor"）
- 非ASCII含む語（日本語等）… 部分文字列マッチ（分かち書きが無いため。
  日本語aliasはカタログ側で固有性の高い表記のみ登録する）
- 単語境界は英数字の連続で判定（"U.S."等のピリオド付きも安全に扱う）
"""
from __future__ import annotations

import re
from typing import Dict, Optional

_CACHE: Dict[str, re.Pattern] = {}


def _is_ascii(term: str) -> bool:
    return all(ord(c) < 128 for c in term)


def _pattern_for(term: str) -> re.Pattern:
    cached = _CACHE.get(term)
    if cached is not None:
        return cached
    case_sensitive = term.startswith("=")
    body_term = term[1:] if case_sensitive else term
    escaped = re.escape(body_term)
    # 単語境界: 前後が英数字でないこと（\bはピリオド・$等で崩れるため明示lookaround）
    body = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    if case_sensitive or (body_term.isupper() and len(body_term) >= 2):
        pattern = re.compile(body)  # 明示指定または全大文字略語: case-sensitive
    else:
        pattern = re.compile(body, re.IGNORECASE)
    _CACHE[term] = pattern
    return pattern


def find_term(text: str, term: str) -> Optional[str]:
    """textにtermが規則どおり出現すれば**実際にマッチした表記**を返す（evidence用）。"""
    if not text or not term:
        return None
    if _is_ascii(term):
        m = _pattern_for(term).search(text)
        return m.group(0) if m else None
    idx = text.find(term)
    return term if idx >= 0 else None


def find_any(text: str, terms) -> Optional[str]:
    """terms中の最初にヒットした語の実マッチ表記（無ければNone）。"""
    for term in terms:
        hit = find_term(text, term)
        if hit is not None:
            return hit
    return None
