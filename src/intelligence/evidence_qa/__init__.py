"""Evidence QA / Trust Gate（Phase 1-E）。

「存在する情報」を「分析に利用してよいEvidence」へ昇格させる品質判定層。
Compass Generator / News Bank / Prediction / Theme Engineが利用する**前に**通す関門。

CORE PRINCIPLE（設計原則）:
    存在する情報 ≠ 信頼できるEvidence
    HTTP 200    ≠ 正しい情報
    Tier 1      ≠ 常に正しい
    複数source一致 ≠ 必ず真（転載10件 ≠ 独立10source）
    AI生成      ≠ Fact

方針:
- 13次元を**独立に**評価する（単一の総合scoreへ潰さない——後から
  「Freshnessの問題かSourceの問題か」が分からなくなるため）。
- 判定はpolicy（名前＋version付き）に基づく決定論。再評価はappend-only
  （旧assessmentを上書きしない）。
- Black Box判定禁止: 全判定がreason code＋人間可読レポートで説明可能。
- 自由文からのFact大量生成はしない（Trust Gateの検証はsynthetic fixtureで行う）。
"""
