"""personal_ui — Phase 11 PWA ／ 利用者との対話の面（private ・local ・read-only。P11-A1 は governed な read の adapter と UI model だけ）。

P11-A1 は凍結の Phase 10（anchor `1a7b9a2`。`docs/databank/PHASE10_FINAL_FREEZE.md`）を **governed な read の API だけ**
（`review_view.read_personal_review` ・`personal_projection.personal_safe_projection` ・`p9_view.read_p9_safe_view`）で読み、
不変の UI model と決定論の JSON に写す（`p10_read_adapter` ・`ui_model`）。store ・実行器 ・直列化 ・管理の初期化 ・private な
P9 の snapshot ・P9 の store ・P8 ・J-Quants ・公開の出力 ・通知は import しない。HTTP server ・browser の UI ・manifest ・service
worker ・browser の保存 ・書き込みは無い（後の gate）。profile の文 ・除外の id ／ 理由 ・id は出さない。推奨 ・順位 ・点数 ・保有 ・
LLM は作らない。

本 package は production runtime closure に含まれず、公開の Pages には入らない。境界: `tests/intelligence/test_personal_ui_boundary.py`。
契約: `docs/databank/PHASE11_A1_GOVERNED_READ_ADAPTER.md`。
"""
