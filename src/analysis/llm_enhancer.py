"""Claude APIによるAI考察の任意強化レイヤー（オプション機能）。

本モジュールを使わなくても Market Intelligence System v4 は完全に動作する。
各 analysis/ モジュールは、まずルールベース（決定論的な数値ロジック）で
考察文のたたき台を必ず生成する。その上で、環境変数 `ANTHROPIC_API_KEY` が
設定されており `anthropic` パッケージが利用可能な場合に限り、
Claude にそのたたき台を「与えられた事実の範囲内でのみ」自然な文章へ
磨き上げてもらう。

- APIキー未設定 / `anthropic` 未インストール / API呼び出し失敗（ネットワーク
  遮断・タイムアウト・レート制限など）の場合は、必ずルールベースのたたき台
  文言をそのまま返す（例外を上位に伝播させない）。
- Claudeへのプロンプトには「事実」として渡した数値以外を創作しないよう
  明示的に指示し、投資助言にならないよう断定表現を避けるよう指示する。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("market_brief")

DEFAULT_MODEL = "claude-sonnet-5"
_MODEL = os.environ.get("MARKET_BRIEF_LLM_MODEL", DEFAULT_MODEL)

try:
    import anthropic
except ImportError:  # anthropicパッケージ未インストールでも動作する
    anthropic = None

_SYSTEM_PROMPT = (
    "あなたは日本の証券会社に所属する市場ストラテジストです。"
    "与えられた「事実」に書かれた数値・事実の範囲内でのみ考察を述べてください。"
    "事実に含まれない数値・出来事を新たに作り出してはいけません。"
    "「必ず上昇する」「今すぐ買うべき」のような断定的な投資助言・勧誘表現は禁止です。"
    "「〜の可能性があります」「〜が意識されやすい状況です」など、"
    "仮説・考察であることが伝わる表現にしてください。"
    "出力は指定された文体・分量の指示に従い、余計な前置きや後書きは付けないでください。"
)


def is_available() -> bool:
    return anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))


def enhance(user_prompt: str, max_tokens: int = 500) -> Optional[str]:
    """成功時は生成テキストを返し、未設定/失敗時は必ずNoneを返す。"""
    if not is_available():
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=_MODEL,
            max_tokens=max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Claude APIによる考察強化に失敗しました。ルールベースの文言にフォールバックします: %s", exc)
        return None


def enhance_or_fallback(
    deterministic_text: str,
    facts: str,
    instruction: str,
    max_tokens: int = 500,
) -> str:
    """ルールベースのたたき台をClaudeで磨き上げる。失敗時はたたき台をそのまま返す。"""
    if not is_available():
        return deterministic_text

    user_prompt = (
        f"【事実】\n{facts}\n\n"
        f"【指示】\n{instruction}\n\n"
        f"【たたき台（この内容を、事実の範囲内で自然な文章に磨き上げてください）】\n{deterministic_text}"
    )
    result = enhance(user_prompt, max_tokens=max_tokens)
    if not result:
        return deterministic_text
    return result
