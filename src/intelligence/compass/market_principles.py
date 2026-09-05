"""Market principle registry（Phase 3.5 pre-flight A / Phase 3-C語彙安全）。

Compassの INTERPRETIVE / RISK claim（「米10年利回りの上昇は株式にとって逆風とみられる」等）
は **Fact ではなく Investment Interpretation** である。その根拠は「一般的な市場知識」を
暗黙のFactとして持ち込んだものではなく、`knowledge/compass_dna/market_rules.yaml`
（Compass DNA）に登録された**明示的な経験則**である。

本モジュールはその経験則を claim 側で参照可能な形に固定する:

- `rule_ref`（例 JP_US_001）… Compass DNA の rule_id
- `interpretation_type` … "market_principle"（経験則に基づく傾向の読み）
- `market_principle_version` … 参照した経験則カタログの版

FACT / INTERPRETATION の境界:
- FACTUAL claim は経験則を参照しない（参照していたら principle validator が拒否する）
- INTERPRETIVE / RISK claim が「追い風／逆風」を述べるときは、登録済みの principle を
  `rule_ref` で参照し、その principle が適用対象とする Context 型を引用していなければならない
- 因果（「〜を受けて」「〜により」）は principle でも表現できない（language validator）
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from ..context.builders import (
    EVENT_PROXIMITY,
    FX_DIRECTION,
    INDEX_DIRECTION,
    RATE_DIRECTION,
    TREND_VS_MA,
)
from ..internals.types import BREADTH_STATE, INDEX_LEADERSHIP

#: 参照する経験則カタログ（Compass DNA）の版。カタログの `version` と一致させる
MARKET_PRINCIPLE_VERSION = "compass_dna.market_rules:0.1.0"
MARKET_PRINCIPLE = "market_principle"
RULES_PATH = Path("knowledge/compass_dna/market_rules.yaml")


@dataclass(frozen=True, kw_only=True)
class MarketPrinciple:
    principle_id: str                     # Compass DNA rule_id
    name: str
    statement: str                        # 人間可読（生成物の根拠にはならない）
    applies_to: Tuple[str, ...]           # 適用対象のcontext_type
    interpretation_type: str = MARKET_PRINCIPLE


PRINCIPLES: Mapping[str, MarketPrinciple] = {
    p.principle_id: p for p in (
        MarketPrinciple(
            principle_id="JP_DIR_001", name="overnight_us_sets_bias",
            statement="前営業日の指数の方向は翌セッションのバイアスとして意識されやすい"
                      "（追い風／逆風の傾向であり因果ではない）",
            applies_to=(INDEX_DIRECTION,)),
        MarketPrinciple(
            principle_id="JP_US_001", name="rates_up_growth_down_banks_up",
            statement="米国・日本の10年利回りの上昇は株式（特にグロース）にとって逆風、"
                      "低下は追い風とみられる傾向",
            applies_to=(RATE_DIRECTION,)),
        MarketPrinciple(
            principle_id="JP_FX_001", name="usdjpy_rate_gap_vs_intervention",
            statement="円安は輸出企業にとって追い風、円高は逆風とみられる傾向",
            applies_to=(FX_DIRECTION,)),
        MarketPrinciple(
            principle_id="JP_INT_003", name="ma_deviation_overheat_and_dip_target",
            statement="移動平均からの乖離拡大は過熱／反動の目安として意識される",
            applies_to=(TREND_VS_MA,)),
        MarketPrinciple(
            principle_id="JP_DIR_004", name="pre_event_caution_post_event_relief",
            statement="大型イベント直前は様子見・利益確定が出やすい",
            applies_to=(EVENT_PROXIMITY,)),
        MarketPrinciple(
            principle_id="JP_INT_001", name="concentration_vs_breadth",
            statement="上昇の持続性は市場の広がり（breadth）に条件付けられる。"
                      "値上がり銘柄数の優勢は広がりの確認、劣勢は広がりの限定を示す",
            applies_to=(BREADTH_STATE, INDEX_LEADERSHIP)),
    )
}


def principle(rule_ref: str) -> Optional[MarketPrinciple]:
    return PRINCIPLES.get(rule_ref)


def is_registered(rule_ref: str) -> bool:
    return rule_ref in PRINCIPLES


def catalog_rule_ids(path: Path = RULES_PATH) -> Tuple[str, ...]:
    """Compass DNA カタログ（YAML）に存在する rule_id（テスト・監査用。読めなければ空）。"""
    try:
        import yaml  # 既存依存

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return tuple(str(r.get("rule_id", "")) for r in data.get("rules", [])
                     if r.get("rule_id"))
    except Exception:  # noqa: BLE001 監査用途のみ
        return ()


def registry_as_dict() -> Dict[str, Dict[str, object]]:
    return {pid: {"name": p.name, "statement": p.statement,
                  "applies_to": list(p.applies_to),
                  "interpretation_type": p.interpretation_type}
            for pid, p in PRINCIPLES.items()}
