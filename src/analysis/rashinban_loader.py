"""Rashinban Learning Source（v2.6）— 岡三「羅針盤」を学習ソースとして読み込む。

ユーザーが data/rashinban/ 配下に .md / .txt を置くだけで、GitHub Actions実行時に
自動で読み込まれ、Strategist View・Future Intelligence・Investment Thesis・
News Ranking・Executive Summaryの分析へ「補助的に」接続される。
ファイルが1つも無い場合は空のRashinbanKnowledgeを返し、既存動作は一切変わらない。

最重要方針:
- 羅針盤の本文はレポートへ転載・長文引用しない。抽出する各パターンは
  1行80文字まで・カテゴリごと最大5件に制限し、HTMLにはファイル名・日付・
  抽出フレーム数・使用状況のみを表示する（本文・抜粋は表示しない）。
- 「引用元」ではなく「分析品質を上げるための判断フレーム」として扱う。
  v1.0の接続は、羅針盤が言及している既存macro_themeラベル（重点テーマ）に
  一致するニュース・テーマへ小さな補助シグナルを与えるのみで、
  既存スコアリング・判定ロジックの設計は変更しない。
- 抽出はすべてルールベース（キーワード一致）。AI APIは使わない。
- 対応形式は .md / .txt のみ（PDF/DOCXはmd/txtへ変換して置く運用。
  将来拡張はこのモジュールへの追加で対応できる構造にしている）。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .models import RashinbanKnowledge

logger = logging.getLogger("market_brief")

DEFAULT_DIR = "data/rashinban"
DEFAULT_MAX_FILES = 3
MAX_PATTERN_CHARS = 80
MAX_PATTERNS_PER_CATEGORY = 5
MAX_EXCERPT_CHARS = 120

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# 抽出カテゴリ（③）: 行にキーワードが含まれる場合、その行を短く切り詰めて
# 該当パターンへ分類する（人手による対応表・ルールベースのみ）。
_CATEGORY_KEYWORDS = {
    "market_view_patterns": [
        "日本株", "日経平均", "TOPIX", "米国株", "米株", "S&P", "NYダウ", "ナスダック",
        "金利", "為替", "ドル円", "日銀", "FRB", "FOMC",
    ],
    "theme_patterns": [
        "テーマ", "物色", "セクター", "業種", "波及", "連鎖", "恩恵", "きっかけ", "材料視",
    ],
    "stock_selection_patterns": [
        "銘柄", "注目株", "選定", "バリュエーション", "PER", "PBR", "割安", "割高",
        "レーティング", "格上げ", "格下げ", "目標株価",
    ],
    "risk_patterns": ["リスク", "懸念", "警戒", "下振れ", "悪材料", "不透明"],
    "time_horizon_patterns": ["短期", "中期", "長期", "目先", "年内", "来期", "半年", "数年"],
}


def _clean_line(line: str) -> str:
    """Markdown記号・箇条書き記号を落とし、比較・格納用に整える。"""
    line = re.sub(r"^[#>\-\*\s・●○◆■\d\.\)）]+", "", line.strip())
    return line.strip()


def _read_rashinban_files(base_dir: Path, max_files: int) -> List[Tuple[str, str]]:
    """data/rashinban/ 配下の .md / .txt を新しい順に最大max_files件読み込む。

    優先順位: latest.md（常に最新扱い）→ ファイル名の日付（YYYY-MM-DD）降順 →
    その他はファイル名降順。READMEは説明ファイルのため読み込まない。
    フォルダ自体が無い・空でも例外にせず空リストを返す。
    """
    if not base_dir.is_dir():
        return []
    candidates = [
        p
        for p in base_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".md", ".txt") and not p.name.lower().startswith("readme")
    ]

    def order(p: Path):
        if p.name.lower() == "latest.md":
            return (0, "")
        m = _DATE_RE.search(p.name)
        if m:
            return (1, "z" + "".join(chr(255 - ord(c)) for c in m.group(1)))  # 日付降順
        return (2, p.name)

    candidates.sort(key=order)
    results: List[Tuple[str, str]] = []
    for p in candidates[:max_files]:
        try:
            results.append((p.name, p.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("羅針盤ファイルの読み込みに失敗しました（スキップ）: %s (%s)", p.name, exc)
    return results


def build_rashinban_knowledge(
    files_texts: List[Tuple[str, str]],
    macro_theme_labels: Optional[List[str]] = None,
) -> RashinbanKnowledge:
    """読み込んだテキストから分析フレーム（型）をルールベースで抽出する。

    本文の長文転載を防ぐため、各パターンは80文字まで・カテゴリごと最大5件、
    raw_excerpt_summaryは120文字までに制限する。
    """
    knowledge = RashinbanKnowledge(source_files=[name for name, _ in files_texts])

    dates = []
    for name, _ in files_texts:
        m = _DATE_RE.search(name)
        if m:
            dates.append(m.group(1))
    if dates:
        knowledge.latest_date = max(dates)
    elif any(name.lower() == "latest.md" for name, _ in files_texts):
        knowledge.latest_date = "latest.md（常に最新扱い）"

    buckets = {field: [] for field in _CATEGORY_KEYWORDS}
    first_line = ""
    for _, text in files_texts:
        for raw_line in text.splitlines():
            line = _clean_line(raw_line)
            if len(line) < 6:
                continue
            if not first_line:
                first_line = line
            for field, keywords in _CATEGORY_KEYWORDS.items():
                if len(buckets[field]) >= MAX_PATTERNS_PER_CATEGORY:
                    continue
                if any(kw in line for kw in keywords):
                    snippet = line[:MAX_PATTERN_CHARS]
                    if snippet not in buckets[field]:
                        buckets[field].append(snippet)

    knowledge.market_view_patterns = buckets["market_view_patterns"]
    knowledge.theme_patterns = buckets["theme_patterns"]
    knowledge.stock_selection_patterns = buckets["stock_selection_patterns"]
    knowledge.risk_patterns = buckets["risk_patterns"]
    knowledge.time_horizon_patterns = buckets["time_horizon_patterns"]
    knowledge.raw_excerpt_summary = first_line[:MAX_EXCERPT_CHARS]

    # 重点テーマ: 羅針盤本文に「既存のmacro_themeラベル」が登場する場合のみ抽出
    # （新しいテーマの推定・生成はしない。既存configとの照合のみ）
    if macro_theme_labels:
        all_text = "\n".join(text for _, text in files_texts)
        knowledge.emphasized_theme_labels = [label for label in macro_theme_labels if label and label in all_text]

    return knowledge


def load_rashinban_learning(
    config: dict,
    macro_theme_labels: Optional[List[str]] = None,
    base_dir: Optional[Path] = None,
) -> RashinbanKnowledge:
    """config.yamlのrashinban設定（dir / max_files）に従って学習ソースを読み込む。

    ファイルが無い場合は空のRashinbanKnowledgeを返す（既存動作へ影響なし）。
    """
    cfg = config.get("rashinban", {}) or {}
    directory = base_dir if base_dir is not None else Path(cfg.get("dir", DEFAULT_DIR))
    max_files = int(cfg.get("max_files", DEFAULT_MAX_FILES))
    files_texts = _read_rashinban_files(directory, max_files)
    knowledge = build_rashinban_knowledge(files_texts, macro_theme_labels)
    if knowledge.source_files:
        logger.info(
            "Rashinban Learning Source: %d件読み込み（最新: %s／分析フレーム%d件／重点テーマ%d件）",
            len(knowledge.source_files),
            knowledge.latest_date or "日付不明",
            knowledge.frame_count(),
            len(knowledge.emphasized_theme_labels),
        )
    else:
        logger.info("Rashinban Learning Source: ファイル未配置のためスキップします（%s）。", directory)
    return knowledge
