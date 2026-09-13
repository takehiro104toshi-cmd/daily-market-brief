"""Investment Intelligence OS vNext — 新アーキテクチャの中核パッケージ。

このパッケージはLegacy Daily Market Brief（src/analysis, src/report,
src/collectors, main.py）とは独立した新開発本線（vNext）である。
設計根拠: docs/rebuild/TARGET_ARCHITECTURE.md / STAGE1_VNEXT_FOUNDATION.md。

Import境界（tests/intelligence/test_import_boundary.py で機械検査）:
    - vNext（本パッケージ）から Legacy モジュール
      （src.analysis / src.report / src.collectors / src.data / src.date /
      notifiers / main）への import は禁止。
    - Legacy から vNext への import も原則行わない（Stage 3以降、承認済みの
      adapter モジュール経由でのみ接続する）。
    - 旧 AnalysisBundle のような巨大万能オブジェクトは作らない。
      モデルはドメイン単位（core/types.py 参照）に分離する。

データフロー（TARGET_ARCHITECTURE.md §2）:
    sources → evidence → (market / news / entities) → themes / predictions /
    thesis / screening → reports → 配信・personalization
"""
