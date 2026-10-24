"""Phase 12 — automation（運用の層）。P12-A1: 純粋な domain ／ state の層だけ。

- scheduler ・subprocess ・server の起動 ・socket ・network ・資格情報 ・file の書き込みは無い（後の gate）。
- schedule の authority は **運用の authority** であり市場の authority ではない。run の ledger は **実行の証拠** だけ。
  派生の snapshot は昇格しない。status の projection は authority ではない。
- 時計の分離: `selection_clock_at`（slot の選択に影響してよい唯一の壁時計の観測）は caller が渡す。`scheduled_for` だけが
  `at` ・`as_of_date` ・`session_date` ・時点 ・市場の意味を決める。`started_at` ・`completed_at` ・`recorded_at` は telemetry。
記録: `docs/databank/PHASE12_A1_SCHEDULE_RUN_STATE_MODEL.md`。
"""
