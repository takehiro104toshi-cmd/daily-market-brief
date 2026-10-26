"""watchlist_thesis_intelligence — Phase 9 Watchlist / Thesis Intelligence（private ・local。P9-A1 は引き渡しだけ）。

P9-A1 は凍結の Phase 8（`docs/databank/PHASE8_FINAL_FREEZE.md`。anchor `0a32d86`）の完了した screen の run を **read-only** で
再構成する引き渡し（`p8_handoff`）と、Phase 9 の private root の規約（`private_root`）だけを持つ。Watchlist ／ Thesis の authority ・
store ・提案 ・順位 ・点数 ・推奨 ・LLM ・公開の出力は無い。

既存の公開の watchlist（`config.yaml` の `watchlist:` ・`src/analysis` ・`src/report` ・Morning Brief）とは別物で、それらを import ・
移行 ・供給しない。本 package は production runtime closure に含まれない。

境界: `tests/intelligence/test_watchlist_thesis_boundary.py`。契約: `docs/databank/PHASE9_A1_P8_HANDOFF_CONTRACT.md`。
"""
