"""themes — Phase 6 Theme 層（内部知識。production authority ではない）。

P6-A4a: 純 model 層のみ（record・語彙・canonical 直列化・content id・fingerprint・資格判定の純関数）。
store / JSONL IO / resolver / SQLite / discovery / lifecycle / graph / LLM は含まない（A4b 以降の gate）。

境界（`docs/databank/PHASE6_FOUNDATION_DECISIONS.md` §7、`tests/intelligence/test_theme_import_boundary.py`）:
- 許可 import: `core.ids`、`core.time`（stdlib 以外はこれだけ）。
- 禁止: compass / reports / predictions / internals / context / market store・providers / ingestion /
  normalization / databank runtime / network / legacy。凍結 P4 / P5 module は本 package を import しない。
- 本 package は `tests/intelligence/test_p43b2c_production_bundle.py` の EXCLUDED_PACKAGES に列挙されており、
  production runtime closure から機械的に排除される。

契約: PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md（A1）/ PHASE6_THEME_IDENTITY_EVIDENCE_CONTRACT.md（A2）/
PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md（A3）。
"""
