"""personal_intelligence — Phase 10 Personal Intelligence（private ・local。P10-A1 は登録と Phase 9 の read-only の adapter だけ）。

P10-A1 は凍結の Phase 9（`docs/databank/PHASE9_FINAL_FREEZE.md`。anchor `4c19701`）を **read-only** で読む専用の adapter
（`p9_view`）だけを持つ。個人の profile ・FOCUS ／ MUTE ・個人の store ・実行器 ・個人の見直しの列 ・保有 ・通知 ・LLM ・PWA ・自動化は
無い（後の gate ・延期）。推奨 ・売買 ・順位 ・点数 ・建玉 ・配分は作らない。

本 package は production runtime closure に含まれない。境界: `tests/intelligence/test_personal_intelligence_boundary.py`。
契約: `docs/databank/PHASE10_A1_P9_READONLY_ADAPTER.md`。
"""
