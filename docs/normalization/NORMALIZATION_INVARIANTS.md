# NORMALIZATION_INVARIANTS — 正規化層の不変条件（Phase 1-D）

各不変条件は対応するテストで機械検証される（tests/intelligence/）。

| # | 不変条件 | 検証テスト |
|---|---|---|
| N1 | 同一RawItem＋同一normalizer version → 同一のdocuments/observations（ID含む完全一致） | test_deterministic_same_input_same_output_including_ids / test_deterministic_observation_ids |
| N2 | 処理時刻はNormalizationEventのみが持つ（record contentのsemantic equalityへ不干渉） | 同上（now違いで再実行しても文書一致） |
| N3 | LLM・乱数・外部検索への依存ゼロ | ベンダー中立importスキャン（test_import_boundary が normalization/ を自動走査） |
| N4 | SourceDocument→RawItem→FetchAttempt→SourceEndpoint→Sourceの1本chainで逆引き可能 | test_documents_created_with_full_provenance_chain |
| N5 | original locatorを失わない（canonicalは別フィールドの補助） | test_entry1_full_normalization / test_tank_article_maps_to_source_document |
| N6 | source提供日時とinferred日時を混同しない。naiveのtz勝手確定禁止・retrieved_at黙示代入禁止・unknown許容 | test_normalization_dates.py 全件 |
| N7 | 推定日付は published_inferred=True＋inferred_from で機械可読 | test_entry2_partial_with_url_inferred_date / test_tank_date_inferred_flag_carried_machine_readable |
| N8 | タイトル・本文の正規化は意味を書き換えない（NFC/entity/空白のみ。翻訳・要約禁止） | test_normalization_text.py |
| N9 | 欠損・異常はstructured issue（silent correction禁止）。RawItemは消えない | test_missing_title_entry_rejected_with_issue / test_anomalous_source_date_is_flagged_not_adopted ほか |
| N10 | 改定は新レコード＋revision_of（旧Documentを削除しない）。曖昧ならrelationを付けない | test_revision_detected_for_same_guid_changed_content / test_no_revision_for_identical_content_or_ambiguity |
| N11 | v2再処理は新ID・旧output非破壊（append-onlyストア） | test_reprocessing_v2_creates_new_ids_preserves_v1 / test_v1_v2_coexist_without_overwrite |
| N12 | 金融数値はDecimal（floatを経由しない）。derivedはinputs＋calculation_method必須 | test_json_numbers_become_decimal_never_float / test_derived_observation_requires_provenance |
| N13 | 単位（pct/bps/ratio）のunit無視同一視を拒否。変換は明示Decimal演算のみ | test_unit_conversions_are_exact_decimal |
| N14 | 数値抽出は明示schemaのみ（意味推測禁止）。entity参照はsource明示識別子のみ | mapping spec設計＋test_observation_normalizer.py |
| N15 | 自由文Fact生成をしない（SourceDocumentまで）。tankのINTERPRETED系を取り込まない | test_tank_interpreted_fields_are_not_imported（＋normalization/にFactStatement生成コードが存在しない） |
| N16 | 永続はappend-only・冪等・crash-safe・再オープン可能 | test_normalized_store.py 全件 |
| N17 | Secretは永続経路（serialization/JSONL/log/error）へ流れない。runtime注入はephemeralのみ | test_ingestion_auth.py |

## Evidence創出の現状（P1-D終端）

- SourceDocumentはEvidence sourceとして利用可能（EvidenceLink.evidence_idへ
  source_document_idを入れる基盤はP1-Aで整備済み。JsonlEvidenceStore.add_documents）。
- FactStatement等のclaim生成はP1-E Evidence QAの対象（本層では作らない）。
