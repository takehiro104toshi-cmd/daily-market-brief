# EVIDENCE_INVARIANTS — 不変条件と強制箇所（schema 0.2.0）

Phase 1-A 成果物（2026-08-29）。各不変条件は「どこで強制されるか」を明記する。
（構築時=dataclass `__post_init__` / 導出=evidence/invariants.py / 保存時=jsonl_store）

| # | 不変条件 | 強制箇所 | テスト |
|---|---|---|---|
| 1 | 全datetimeはtimezone-aware（naive拒否） | 構築時（core/time.ensure_aware） | test_evidence_domain::TestTimeModel |
| 2 | 金融値はDecimalのみ（float拒否・欠測はNone） | 構築時（Observation / ForecastMetadata.target_low/high） | TestObservationModel / TestForecastModel |
| 3 | FactStatementはSUPPORTSリンク無し→UNSUPPORTED（AI生成文を自動でFACT扱いしない） | 導出（unsupported_facts / derive_verification） | TestFactModel |
| 4 | AnalysisStatementは inputs≥1・rule_id・agent 必須 | 構築時 | TestAnalysisModel |
| 5 | ForecastStatementはForecastMetadata必須／非FORECASTはmetadataを持てない（型で不可能） | 構築時＋型設計 | TestForecastModel |
| 6 | ForecastMetadataは supporting_evidence≥1・invalidation_conditions≥1・predictor・confidence∈[0,5] | 構築時 | TestForecastModel |
| 7 | derived Observationは calculation_method＋inputs≥1（派生provenance） | 構築時 | TestObservationModel |
| 8 | raw Observationは source_id 必須 | 構築時 | 同上 |
| 9 | SourceDocumentは content_hash・retrieved_at・source_tierスナップショット必須 | 構築時 | TestTimeModel他 |
| 10 | EvidenceLinkの自己参照禁止（claim_id≠evidence_id） | 構築時 | TestEvidenceLink |
| 11 | 重複ID: 同一内容→冪等スキップ／異内容→ValueError（Evidence不変・改定はrevision_of） | 保存時（jsonl_store._append） | test_evidence_store |
| 12 | 改定は上書きせず新レコード（revision_of）。latest_revisionsは導出であり削除しない | 型＋導出 | TestConflictAndRevision |
| 13 | 矛盾Evidenceは両方保持し CONFLICTING を導出（自動削除しない） | 導出 | 同上 |
| 14 | RETRACTED / STALE は明示設定のみ（導出で上書きしない。valid_until経過はis_staleで判定材料提供） | 導出 | （invariants実装） |
| 15 | vNext→Legacy import禁止／vNext全域でLLMベンダーSDK import禁止 | AST検査テスト | test_import_boundary |
| 16 | Serializationはfloatを一切通さない（encode時TypeError） | encode | test_evidence_serialization |

## 検証状態の導出セマンティクス（derive_verification）

```
明示RETRACTED/STALE            → そのまま維持（導出で上書きしない）
SUPPORTS ∧ CONTRADICTS         → CONFLICTING
CONTRADICTSのみ                → CONFLICTING（裏付けなき反証も両論保持）
SUPPORTSのみ                   → VERIFIED
リンクなし ∧ FACT               → UNSUPPORTED
リンクなし ∧ ANALYSIS/FORECAST  → UNVERIFIED
```

## 生成層（Phase 3以降）へ委ねた規約（保存層では強制しない）

- counter_points必須化（Compass DNA: 反対材料なき予測の生成禁止）
- 伝聞FACT（attribution=REPORTED）の語尾減衰表示
- CONFLICTINGの編集上の解決ポリシー

## Open Questions（P1-B以降で解決）

1. 「CONTRADICTSのみ」にREFUTED状態を新設するか（現状CONFLICTINGに包含）。
2. SourceDocumentへのdate_inferred/raw_published_at追加（tank date_quality移植時）。
3. VerificationStateの言明保存値と導出値の同期タイミング（保存時に導出値を書き戻すか、
   常に導出で読むか——参照実装は「導出で読む」）。
