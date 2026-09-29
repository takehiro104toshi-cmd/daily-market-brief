"""theme_intelligence — Phase 6 P6-B Theme Intelligence layer（内部知識。authority ではない）。

Theme Foundation（`src/intelligence/themes/`、凍結）の **上** に置く派生層。P6-B1 は change detection のみ:
2 つの点時刻再構成（`ThemeResolution`）を比較して「Theme について何が変わったか」を決定論的に表現する。

境界（`tests/intelligence/test_theme_intelligence_import_boundary.py`）:
- 許可 import: `themes.model` / `themes.qualification` / `themes.resolver` の pure / read-only surface のみ。
- 禁止: `themes.store` への直接依存、compass / reports / predictions / internals / context / market / ingestion /
  normalization / databank / legacy / network / 公開・顧客出力。Foundation は本 package を import しない。
- 本 package は production runtime closure に含まれない。

契約: `docs/databank/PHASE6_THEME_CHANGE_DETECTION_CONTRACT.md`（P6-B1）。
"""
