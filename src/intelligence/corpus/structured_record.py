"""Structured Compass record（Phase 3.7 §10–§11）。

1 document から後続 3.8 が研究できる schema。今回は **foundation**（rule-based・決定的）であり
完全な semantic analyzer ではない。observation level を必ず分離する:

    SOURCE_STATEMENT        紙面の文（事実・記述）
    EXTRACTED_VALUE         表から抽出した数値
    ANALYST_INTERPRETATION  分析者の因果・解釈（〜とみられる / 背景に〜）
    OUTLOOK                 見通し（〜を想定 / 〜となろう。確信度ラダー 0–5）
    RISK                    リスク・反対材料（もっとも / 他方 / 警戒）
    SYSTEM_DERIVED_LABEL    システムが付けた label（羅針盤原文ではない）

語尾規約は docs/compass_dna/FACT_ANALYSIS_FORECAST_SPEC.md（Phase 0）に基づく。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .config import CorpusConfig
from .extraction import KIND_BULLET, KIND_HEADING, KIND_TABLE_ROW, KIND_TEXT, ExtractionArtifact
from .header_values import HeaderValue
from .page_sections import GLOBAL_STRATEGY, INVESTMENT_IDEA, P1_JP_OUTLOOK
from .versioning import analysis_record_id

SOURCE_STATEMENT = "SOURCE_STATEMENT"
EXTRACTED_VALUE = "EXTRACTED_VALUE"
ANALYST_INTERPRETATION = "ANALYST_INTERPRETATION"
OUTLOOK = "OUTLOOK"
RISK = "RISK"
SYSTEM_DERIVED_LABEL = "SYSTEM_DERIVED_LABEL"
LEVELS = (SOURCE_STATEMENT, EXTRACTED_VALUE, ANALYST_INTERPRETATION, OUTLOOK, RISK,
          SYSTEM_DERIVED_LABEL)

CATEGORIES: Tuple[str, ...] = (
    "market_values", "selected_topics", "main_theme", "market_state_mentions",
    "sector_mentions", "rate_mentions", "fx_mentions", "index_mentions", "breadth_mentions",
    "event_mentions", "interpretations", "outlook_statements", "why_statements",
    "risk_statements", "watch_items",
)

ANALYZER_NAME = "rule_based_foundation"

# ---- 語尾・語彙（FACT_ANALYSIS_FORECAST_SPEC §1 / §3）
_OUTLOOK_END = re.compile(r"(想定|見込|となろう|しよう|であろう|だろう|とみる|期待|注目|焦点|可能性|ありそう|余地|予想|見通し|たい|そうだ)[^。]{0,12}$")
_LADDER: Tuple[Tuple[int, re.Pattern], ...] = (
    (5, re.compile(r"投資妙味|押し目買い|追随|拾う")),
    (4, re.compile(r"想定|見込|となろう|しよう|であろう|だろう|とみる")),
    (3, re.compile(r"期待")),
    (2, re.compile(r"注目|焦点")),
    (1, re.compile(r"可能性|ありそう|余地")),
    (0, re.compile(r"となれば|次第")),
)
_RISK = re.compile(r"リスク|警戒|懸念|逆風|下振れ|不透明|悪化|重し|もっとも|他方|一方で|ネガティブ|下押し")
_INTERP = re.compile(r"とみられ|と考え|意識され|背景に|ため|受け|好感|嫌気|材料視|につなが|影響|反映")
_WHY = re.compile(r"背景|ため|受け|好感|嫌気|材料|要因|きっかけ")
_WATCH = re.compile(r"注目|焦点|見極め|警戒|動向")

_MENTIONS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("market_state_mentions", re.compile(r"底堅|反落|続伸|続落|急落|急騰|利食い|上昇|下落|調整|高値|安値|過熱|乖離|反発|軟調|堅調|もみ合い")),
    ("sector_mentions", re.compile(r"銀行|半導体|電力|商社|自動車|不動産|証券|保険|建設|機械|電機|素材|エネルギー|小売|通信|医薬|海運|鉄鋼|化学|金融|ハイテク|ディフェンシブ|バリュー|グロース|防衛|光関連|データセンター")),
    ("rate_mentions", re.compile(r"金利|利回り|国債|日銀|FRB|FOMC|利上げ|利下げ|金融政策|イールド")),
    ("fx_mentions", re.compile(r"ドル円|円高|円安|為替|ドル高|ドル安|レンジ")),
    ("index_mentions", re.compile(r"日経平均|TOPIX|NYダウ|S&P500|ナスダック|SOX|先物|25日|ラッセル|VIX")),
    ("breadth_mentions", re.compile(r"占有率|裾野|物色の広がり|寄与度|騰落|値上がり|値下がり|上位\d+位|主役交代|顔ぶれ")),
    ("event_mentions", re.compile(r"決算|FOMC|日銀|CPI|雇用統計|選挙|会合|発表|イベント|GDP|PMI|関税|総裁")),
)
_EVENT_STATE_PRIORITY: Tuple[Tuple[str, re.Pattern], ...] = (
    ("CENTRAL_BANK", re.compile(r"FOMC|日銀|金融政策決定会合|ECB|利上げ|利下げ")),
    ("EARNINGS", re.compile(r"決算")),
    ("MACRO_DATA", re.compile(r"CPI|雇用統計|GDP|PMI|物価")),
    ("GEOPOLITICS", re.compile(r"関税|地政学|中東|ウクライナ|停戦")),
)

_SENTENCE_SPLIT = re.compile(r"(?<=。)")


@dataclass(frozen=True)
class Observation:
    observation_id: str
    level: str
    category: str
    text: str
    page: int
    artifact_id: str
    key: str = ""
    value: str = ""
    confidence_ladder: Optional[int] = None
    note: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"observation_id": self.observation_id, "level": self.level,
                "category": self.category, "text": self.text, "page": self.page,
                "artifact_id": self.artifact_id, "key": self.key, "value": self.value,
                "confidence_ladder": self.confidence_ladder, "note": self.note}


@dataclass(frozen=True)
class CompassStructuredRecord:
    record_id: str
    document_id: str
    document_date: str
    analysis_version: str
    analyzer_name: str
    created_at: str
    p2_mode: str
    sections: Tuple[str, ...]
    observations: Mapping[str, Tuple[Observation, ...]]   # category → observations
    supersedes: str = ""

    def category(self, name: str) -> Tuple[Observation, ...]:
        return tuple(self.observations.get(name, ()))

    def counts(self) -> Dict[str, int]:
        return {c: len(self.observations.get(c, ())) for c in CATEGORIES}

    def level_counts(self) -> Dict[str, int]:
        out = {lvl: 0 for lvl in LEVELS}
        for obs in self.all_observations():
            out[obs.level] = out.get(obs.level, 0) + 1
        return out

    def all_observations(self) -> List[Observation]:
        seen = set()
        out: List[Observation] = []
        for c in CATEGORIES:
            for obs in self.observations.get(c, ()):
                if obs.observation_id not in seen:
                    seen.add(obs.observation_id)
                    out.append(obs)
        return out

    def as_dict(self) -> Dict[str, object]:
        return {"record_id": self.record_id, "document_id": self.document_id,
                "document_date": self.document_date, "analysis_version": self.analysis_version,
                "analyzer_name": self.analyzer_name, "created_at": self.created_at,
                "p2_mode": self.p2_mode, "sections": list(self.sections),
                "supersedes": self.supersedes,
                "counts": self.counts(), "level_counts": self.level_counts(),
                "observations": {c: [o.as_dict() for o in self.observations.get(c, ())]
                                 for c in CATEGORIES}}


def record_from_dict(d: Mapping[str, object]) -> CompassStructuredRecord:
    obs_raw = d.get("observations") or {}
    observations: Dict[str, Tuple[Observation, ...]] = {}
    for cat, items in dict(obs_raw).items():
        observations[cat] = tuple(Observation(
            observation_id=str(o.get("observation_id", "")), level=str(o.get("level", "")),
            category=str(o.get("category", cat)), text=str(o.get("text", "")),
            page=int(o.get("page", 0) or 0), artifact_id=str(o.get("artifact_id", "")),
            key=str(o.get("key", "")), value=str(o.get("value", "")),
            confidence_ladder=o.get("confidence_ladder"), note=str(o.get("note", "")))
            for o in items)
    return CompassStructuredRecord(
        record_id=str(d.get("record_id", "")), document_id=str(d.get("document_id", "")),
        document_date=str(d.get("document_date", "")),
        analysis_version=str(d.get("analysis_version", "")),
        analyzer_name=str(d.get("analyzer_name", "")), created_at=str(d.get("created_at", "")),
        p2_mode=str(d.get("p2_mode", "")), sections=tuple(d.get("sections") or ()),
        observations=observations, supersedes=str(d.get("supersedes", "")))


def confidence_ladder(sentence: str) -> Optional[int]:
    for level, pattern in _LADDER:
        if pattern.search(sentence):
            return level
    return None


def classify_statement(sentence: str) -> Tuple[str, Optional[int]]:
    """文 → (level, ladder)。OUTLOOK 語尾 → OUTLOOK。反対材料語 → RISK。解釈語 → INTERPRETATION。"""
    s = sentence.strip().rstrip("。").strip()
    if _OUTLOOK_END.search(s):
        ladder = confidence_ladder(s)
        # 反対材料語（もっとも / 他方 / 警戒 …）を含み確信度が弱い（<= 1）文は RISK 側（tail scenario）
        if _RISK.search(s) and (ladder is None or ladder <= 1):
            return RISK, ladder
        return OUTLOOK, ladder
    if _RISK.search(s):
        return RISK, None
    if _INTERP.search(s):
        return ANALYST_INTERPRETATION, None
    return SOURCE_STATEMENT, None


def split_sentences(text: str, min_chars: int = 8) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if len(s.strip()) >= min_chars]


def _obs_id(record_id: str, category: str, page: int, artifact_id: str, index: int) -> str:
    seed = f"{record_id}|{category}|{page}|{artifact_id}|{index}"
    return "cso_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def analyze_document(*, document_id: str, document_date: str,
                     artifacts: Sequence[ExtractionArtifact],
                     header_values: Sequence[HeaderValue],
                     secondary_values: Sequence[HeaderValue],
                     sections: Sequence[str], p2_mode: str, config: CorpusConfig,
                     created_at: datetime, analysis_version: Optional[str] = None,
                     supersedes: str = "") -> CompassStructuredRecord:
    version = analysis_version or config.analysis_version
    record_id = analysis_record_id(document_id, version)
    cap = config.max_observations_per_category
    max_chars = config.max_statement_chars
    buckets: Dict[str, List[Observation]] = {c: [] for c in CATEGORIES}

    def add(category: str, obs: Observation) -> None:
        if len(buckets[category]) < cap:
            buckets[category].append(obs)

    # ---- EXTRACTED_VALUE（表）
    table_rows = {(a.page, a.line_start): a for a in artifacts if a.kind == KIND_TABLE_ROW}
    for idx, hv in enumerate(list(header_values) + list(secondary_values)):
        art = table_rows.get((hv.page, hv.line_level))
        aid = art.artifact_id if art else ""
        note = "closed" if hv.closed else f"change={hv.change} ({hv.change_kind})"
        add("market_values", Observation(
            observation_id=_obs_id(record_id, "market_values", hv.page, aid or hv.key, idx),
            level=EXTRACTED_VALUE, category="market_values", text="", page=hv.page,
            artifact_id=aid, key=hv.key, value="" if hv.level is None else str(hv.level),
            note=note))

    # ---- P1 ボレット / 見出し（SOURCE_STATEMENT）
    section_of_page = {i + 1: s for i, s in enumerate(sections)}
    theme_done = False
    for art in artifacts:
        sec = section_of_page.get(art.page, "")
        if sec == P1_JP_OUTLOOK and art.kind == KIND_BULLET:
            add("selected_topics", Observation(
                observation_id=_obs_id(record_id, "selected_topics", art.page, art.artifact_id, 0),
                level=SOURCE_STATEMENT, category="selected_topics",
                text=art.text[:max_chars], page=art.page, artifact_id=art.artifact_id))
        if sec == P1_JP_OUTLOOK and art.kind == KIND_HEADING and art.text.startswith("【") and not theme_done:
            add("main_theme", Observation(
                observation_id=_obs_id(record_id, "main_theme", art.page, art.artifact_id, 0),
                level=SOURCE_STATEMENT, category="main_theme",
                text=art.text[:max_chars], page=art.page, artifact_id=art.artifact_id))
            theme_done = True
    if not theme_done and buckets["selected_topics"]:
        last = buckets["selected_topics"][-1]
        add("main_theme", Observation(
            observation_id=_obs_id(record_id, "main_theme", last.page, last.artifact_id, 1),
            level=SOURCE_STATEMENT, category="main_theme", text=last.text, page=last.page,
            artifact_id=last.artifact_id, note="fallback=third_bullet"))

    # ---- 本文の文単位分類（P1 / P2 / アイデア面）
    for art in artifacts:
        sec = section_of_page.get(art.page, "")
        if sec not in (P1_JP_OUTLOOK, GLOBAL_STRATEGY, INVESTMENT_IDEA):
            continue
        if art.kind not in (KIND_TEXT, KIND_BULLET):
            continue
        for s_idx, sentence in enumerate(split_sentences(art.text)):
            level, ladder = classify_statement(sentence)
            text = sentence[:max_chars]
            base_kwargs = dict(page=art.page, artifact_id=art.artifact_id, text=text)
            if level == OUTLOOK:
                add("outlook_statements", Observation(
                    observation_id=_obs_id(record_id, "outlook_statements", art.page, art.artifact_id, s_idx),
                    level=OUTLOOK, category="outlook_statements", confidence_ladder=ladder, **base_kwargs))
            elif level == RISK:
                add("risk_statements", Observation(
                    observation_id=_obs_id(record_id, "risk_statements", art.page, art.artifact_id, s_idx),
                    level=RISK, category="risk_statements", **base_kwargs))
            elif level == ANALYST_INTERPRETATION:
                add("interpretations", Observation(
                    observation_id=_obs_id(record_id, "interpretations", art.page, art.artifact_id, s_idx),
                    level=ANALYST_INTERPRETATION, category="interpretations", **base_kwargs))
            if _WHY.search(sentence):
                add("why_statements", Observation(
                    observation_id=_obs_id(record_id, "why_statements", art.page, art.artifact_id, s_idx),
                    level=level if level != SOURCE_STATEMENT else ANALYST_INTERPRETATION,
                    category="why_statements", **base_kwargs))
            if _WATCH.search(sentence) and level in (OUTLOOK, RISK):
                add("watch_items", Observation(
                    observation_id=_obs_id(record_id, "watch_items", art.page, art.artifact_id, s_idx),
                    level=level, category="watch_items", confidence_ladder=ladder, **base_kwargs))
            for category, pattern in _MENTIONS:
                if pattern.search(sentence):
                    add(category, Observation(
                        observation_id=_obs_id(record_id, category, art.page, art.artifact_id, s_idx),
                        level=level, category=category, confidence_ladder=ladder, **base_kwargs))

    return CompassStructuredRecord(
        record_id=record_id, document_id=document_id, document_date=document_date,
        analysis_version=version, analyzer_name=ANALYZER_NAME, created_at=created_at.isoformat(),
        p2_mode=p2_mode, sections=tuple(sections),
        observations={c: tuple(v) for c, v in buckets.items()}, supersedes=supersedes)


def event_state_from_text(text: str) -> str:
    """SYSTEM_DERIVED_LABEL 用: 本文 keyword からイベント状態を決める（優先順位固定）。"""
    for label, pattern in _EVENT_STATE_PRIORITY:
        if pattern.search(text or ""):
            return label
    return "NONE_DETECTED"
