"""Phase 3-C Evidence-Grounded Compass Generator.

**LLM MAY WRITE. LLM MAY NOT INVENT.**

Fact Layer（3-A）＋ Compass Context Engine（3-B）で確認された情報**だけ**を根拠に、
Morning Compassとして使える grounded narrative を生成する層。

pipeline（責務分離）:
  Morning Context Snapshot → Evidence Package → Narrative Plan
  → generator（deterministic / fake / LLM）→ Generated Claims
  → Grounding / Citation / Numeric / Direction / Temporal / Missingness /
    Language validation → Quality Gate → Compass Output（persist）
"""
