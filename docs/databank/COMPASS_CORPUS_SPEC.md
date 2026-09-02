# COMPASS_CORPUS_SPEC — Compass Corpus Foundation（Phase 3.7）

「グローバル投資の羅針盤」PDF を継続的に蓄積し、後続 Phase（3.8 Analyzer / 3.9 Compass DNA v2）が
自動研究できる **正式な Compass Corpus** の foundation。実装は `src/intelligence/corpus/`
（1機能=1ファイル）、設定は `config.yaml: compass_corpus`、テストは
`tests/intelligence/test_compass_corpus.py`（42 件）。

## 1. 目的と境界

- Corpus は **historical analytical corpus**（その時点で人間の分析者が何を観測し、何を重視し、
  どう解釈し、どう見通したか）。training truth / market truth / Fact Store ではない。
- Market Fact の truth source は J-Quants / approved market sources。羅針盤の記載値で Fact Store を
  上書きしない（`alignment.py` は比較結果を保持するだけ）。
- offline-first。本文を外部 LLM へ自動送信しない。新 API key を要求しない。
- Corpus から production Compass rule を自動変更しない（append-only の version / supersession のみ）。
- 原本は CONFIDENTIAL_SOURCE。Git 非管理の local research area（config `source_dir`）に置き、
  コードは機密パスを直接参照しない（confidential guard）。Corpus store は
  `INTELLIGENCE_DATA_ROOT` 配下（`compass_corpus` / pilot は `compass_corpus_pilot`）。

## 2. 既存 historical Compass の棚卸し（`inventory.py`・捏造しない）

| 種別 | 件数 | 内容 |
|---|---|---|
| PDF_SOURCE（原本、hash で unique 化） | **10** | 2026-06-18, 06-19, 06-22, 06-23, 06-24, 06-25, 06-26, 06-29, 06-30, 07-01（55 ページ） |
| 重複コピー | 0（走査 dir 内） | 同一 hash が別 dir にも存在するが同一 document として扱う |
| DERIVED_HISTORICAL_ARTIFACT | 9 | `docs/compass_dna/*.md`（7）、`analysis_rules/market_rules.yaml`、`knowledge/compass_dna/market_rules.yaml` |
| DERIVED_TEXT_ARTIFACT | 0 | legacy の `.md/.txt` は存在しない |

derived artifact は **PDF corpus source として数えない**。8月分（Phase 0.5 想定）は存在しない。

## 3. Source model（`source.py`・immutable）

`SourceDocument`: document_id / sha256 / original_filename / source_type / received_at / document_date /
date_sequence / page_count / byte_size / media_type / storage_locator / family / family_confidence /
publication_date / schema_version。原本は `sources/<document_id>.pdf` へ一度だけコピー（hash 検証後に
read-only）。`verify_original()` で再検証できる。pipeline は原本を書き換えない。

## 4. Identity（`identity.py`）と重複（`pipeline.py`）

- `document_id = "cmp_" + sha256[:20]`。filename に依存しない。
- 同一 hash の再投入は **DUPLICATE**（documents には追加せず `duplicates.jsonl` ledger に記録）。
- 同一 document_date の別 PDF は別 identity・`date_sequence` 2, 3, …。
- document_date（紙面）≠ received_at（受領時刻）を常に分離。

## 5. Validation / quarantine（`validation.py` / `family.py` / `status.py`・fail-closed）

| 検証 | 失敗時 |
|---|---|
| `%PDF-` magic / 読める | FAILED（NOT_PDF_BYTES / PDF_UNREADABLE） |
| page count 3..12 | QUARANTINED |
| document family（page-1 の安定 marker 8 種、必須 3 種。HIGH = 必須全部＋5 個以上） | QUARANTINED（MEDIUM / LOW） |
| document_date（page-1「YYYY年M月D日」。脚注日・PDF metadata との矛盾は記録） | QUARANTINED（欠落時） |

status: RECEIVED → VALIDATED → EXTRACTION_READY → EXTRACTED → ANALYZED / PARTIAL、
または QUARANTINED / FAILED。DUPLICATE は投入イベント。すべて `status_events.jsonl` に残す。

## 6. Corpus store（`store.py`）

canonical JSONL（append-only、10 ファイル: documents / status_events / duplicates / temporal / extractions /
artifacts / analyses / quality / coverage_labels / alignments）＋ SQLite index（`rebuild_index()` で
canonical だけから再構築）。各ファイルは key で idempotent。metadata と analysis artifact は別ファイル。

## 7. Extraction（`extraction.py` / `page_sections.py` / `header_values.py`）

- text layer（pypdf）優先。**OCR は default で行わない**（`ocr_attempted=False`、artifact の `ocr_derived=False`）。
- artifact: artifact_id / document_id / extractor_version / page / block_index / line_start–line_end /
  kind（BANNER / HEADING / BULLET / TABLE_ROW / FOOTNOTE / TEXT）/ quality（OK / LOW_TEXT / EMPTY）。
- section: p1_japan_outlook / global_strategy（us_equity_outlook | fx_outlook）/ investment_idea /
  featured_stocks / jp_weekly_review / us_weekly_review / publications。
- header 表（固定 10 列: 日経平均・25日MA・TOPIX・プライム売買代金・NYダウ・S&P500・ナスダック・
  日10年・米10年・ドル円）と P2 指数表（ラッセル2000 / SOX / VIX / MOVE / TOPIXバリュー / グロース）を
  EXTRACTED_VALUE として保持（Closed も記録）。

## 8. Structured Compass record（`structured_record.py`）

15 category（market_values / selected_topics / main_theme / market_state_mentions / sector_mentions /
rate_mentions / fx_mentions / index_mentions / breadth_mentions / event_mentions / interpretations /
outlook_statements / why_statements / risk_statements / watch_items）。
observation level を必ず分離: SOURCE_STATEMENT / EXTRACTED_VALUE / ANALYST_INTERPRETATION / OUTLOOK
（確信度ラダー 0–5、FACT_ANALYSIS_FORECAST_SPEC §3）/ RISK / SYSTEM_DERIVED_LABEL。
語尾規約は rule-based・決定的（完全な semantic analyzer ではない＝foundation）。
system label（coverage）は record の外（`coverage_labels.jsonl`）に置き、羅針盤原文として扱わない。

## 9. Provenance（`store.provenance_chain()`）

observation → record_id → artifact（page / line_start–line_end / extractor_version）→ 原本
（storage_locator + sha256）。将来の Compass DNA rule は observation_id / artifact_id を supporting example
として保持できる。

## 10. Temporal semantics（`temporal.py`）

document_date / publication_date（PDF CreationDate、判明時のみ）/ received_at / referenced_market_session /
future_event_mentions を分離。referenced session は営業日カレンダーがある場合のみ「発行日の直前営業日」
（basis CALENDAR）。無ければ **UNKNOWN**（basis NO_CALENDAR。`candidate_previous_weekday` はヒント欄で
session ではない）。

## 11. Market data alignment（`alignment.py`）

header 5 系列（日経平均・TOPIX・日10年・米10年・ドル円）を Market Data Bank の series_id
（context/builders と同一）と突き合わせ MATCH / NEAR_MATCH（許容 0.05%）/ CONFLICT / NOT_AVAILABLE /
NOT_COMPARABLE を保存。lookup は callable 注入。**Fact Store には書かない**。

## 12. Quality（`quality.py`）

VALID / PARTIAL（LOW_TEXT ページ・header 一部欠落・P2 指数表不足）/ LIMITED_USE（EMPTY ページ・header 欠落）/
QUARANTINED（family 不確実）。pattern evidence へ無条件投入できるのは VALID のみ
（`eligible_for_pattern_evidence`）。milestone / coverage は VALID + PARTIAL を usable として数える。

## 13. Coverage model（`coverage.py`・thresholds version 1.0.0）

11 dimension: equity_direction / volatility_state / nikkei_vs_topix / yen_direction / japan_rate_direction /
us_rate_direction / turnover_state / breadth_state / growth_value_state / sector_leadership / major_event_state。
label source の優先順位: **CONTEXT**（Phase 3-B / 3.5、J-Quants 由来）＞ **EXTRACTED_VALUE**（紙面の数値表を
閾値で判定。equity ±0.5% / relative ±0.3pt / yen ±0.3円 / rate ±0.02pt / turnover ±1.0兆円 / VIX 15–25 /
growth-value ±0.3pt）＞ **TEXT_KEYWORD**（major_event_state のみ）＞ UNKNOWN。
breadth_state / sector_leadership は CONTEXT が無ければ UNKNOWN（本文から bull/bear を決めない）。
report: dimension × label の counts、well_represented（>= 3 本）/ underrepresented / missing、
underrepresented_regimes、dimensions_fully_unknown。

## 14. Milestones（`milestones.py`）

CORPUS_10 structure validation / CORPUS_30 basic pattern validation / CORPUS_50 production evaluation minimum /
CORPUS_100 Compass DNA v2 review target / CORPUS_200 regime-aware review target。現在値と next milestone・
必要本数を machine-readable に出す。

## 15. Version / re-analysis（`versioning.py` / `pipeline.reanalyze_document()`）

schema / extractor / analysis / coverage thresholds / family markers の 5 version。再解析は保存済み artifact
から新 analysis_version の record を **追記**し `supersedes` で旧 record を指す（旧 record・原本は不変）。
`current_analysis()` は version 最大 → created_at 最新。

## 16. CorpusSnapshot（`snapshot.py`）

Phase 3.8 への read model: versions / counts（documents, usable, eligible, partial, limited_use, quarantined,
failed, duplicates_seen）/ date_range / documents（status, quality, locator, sha256, current_analysis_id,
analysis_versions, supersession_chain, artifact_count, observation_counts, coverage labels + sources,
alignment summary）/ coverage report / milestones / store_counts。`snapshot.json` として書き出す。

## 17. Mobile Intake boundary（`intake.py`）と inbox contract（`inbox.py`）

- `IntakeRequest(path, original_filename, source_type ∈ LOCAL_FILE / HISTORICAL_IMPORT / INBOX / MOBILE_UPLOAD,
  received_at, channel)` → `CompassIntakeService.submit()` → ACCEPTED / DUPLICATE / QUARANTINED / FAILED /
  REJECTED。Google Drive / iCloud / Dropbox 等の adapter は request を作るだけ。core は cloud SDK に依存しない
  （Phase 3.7 では接続を実装しない）。
- inbox: `incoming/` → stable-file detection（size 不変 ×2 sample かつ mtime が `inbox_stable_seconds` 以上前）
  → `.processing/<name>.lock` 排他 → intake → `inbox_ledger.jsonl`。copy 途中は SKIPPED_UNSTABLE。
  原本を移動・削除しない。同一 hash は SKIPPED_PROCESSED。watcher daemon は作らない。

## 18. Corpus pilot（実データ・isolated root `data root/compass_corpus_pilot`）

`python -m src.intelligence.corpus.pilot`（offline、4.9 s）。marker `::P37_*::`。

| 項目 | 実測 |
|---|---|
| ingest | 10 / 10 ANALYZED、quality VALID 10、family HIGH 10、header COMPLETE 10、3.45 s |
| artifacts / observations | 883 artifacts、1,173 observations（v1.0.0）。ページ品質 OK 55/55 |
| p2 mode | fx_outlook 4（06-18, 06-23, 06-25, 06-30）/ us_equity_outlook 6 |
| 月曜号 | 06-22, 06-29 は 7 ページ（jp / us weekly review 検出） |
| provenance | selected_topics observation → BULLET artifact（page 1, line 50）→ 原本 sha256 一致・read-only |
| temporal | publication_date = document_date 10/10（PDF metadata 07:27–07:32 JST）、矛盾 0、referenced session UNKNOWN（NO_CALENDAR、推測なし） |
| alignment | NOT_COMPARABLE 50/50（この環境に Market Bank / calendar が無い。MATCH / NEAR / CONFLICT はテストで検証） |
| dedup lab（別 root） | 同一ファイル再投入 DUPLICATE / 改名コピー DUPLICATE / 同日別 PDF（再保存）→ 新 id・date_sequence 2 / 非羅針盤 PDF → QUARANTINED（FAMILY_CONFIDENCE_LOW 等）/ 非 PDF bytes → FAILED |
| reanalysis | v1.0.1 で 10 本追記 → analyses 20、旧 record 保持、chain [new, old] |
| SQLite rebuild | index を canonical から再構築 → 全 table 件数一致（documents 10 / status_events 60 / artifacts 883 / analyses 20 / observations 2,337 / coverage_labels 220 / alignments 100） |
| idempotency | 原本 10 本再投入 → DUPLICATE 10、canonical は duplicates ledger 以外不変 |
| inbox | copying.pdf（半分）→ UNSTABLE / SKIPPED、stable.pdf → SUCCESS、再実行 SKIPPED_PROCESSED、原本移動なし |
| security | 原本 hash 不変 10/10、package に network import 0・secret access 0、外部 LLM 0、production corpus root 不変、marker に本文なし |

### 18.1 Coverage report（v1.0.0、10 本）

| dimension | 分布 | source |
|---|---|---|
| equity_direction | UP 5 / DOWN 3 / FLAT 2 | EXTRACTED_VALUE |
| volatility_state | NORMAL 10 | EXTRACTED_VALUE（VIX 16.4–19.5） |
| nikkei_vs_topix | NIKKEI_OUTPERFORM 4 / IN_LINE 3 / TOPIX_OUTPERFORM 3 | EXTRACTED_VALUE |
| yen_direction | FLAT 8 / YEN_WEAKER 2 | EXTRACTED_VALUE |
| japan_rate_direction | UP 4 / FLAT 4 / DOWN 2 | EXTRACTED_VALUE |
| us_rate_direction | UP 3 / DOWN 3 / FLAT 3 / UNKNOWN 1（米国休場明け） | EXTRACTED_VALUE |
| turnover_state | EXPANDING 4 / CONTRACTING 4 / STABLE 2 | EXTRACTED_VALUE |
| breadth_state | UNKNOWN 10 | CONTEXT 待ち |
| growth_value_state | GROWTH_LEAD 5 / MIXED 3 / VALUE_LEAD 2 | EXTRACTED_VALUE |
| sector_leadership | UNKNOWN 10 | CONTEXT 待ち |
| major_event_state | CENTRAL_BANK 8 / EARNINGS 2 | TEXT_KEYWORD（最弱） |

- milestone: **CORPUS_10 到達**（usable 10）。next CORPUS_30、あと 20 本。
- underrepresented: equity_direction=FLAT, yen_direction=YEN_WEAKER, japan_rate_direction=DOWN,
  turnover_state=STABLE, growth_value_state=VALUE_LEAD, major_event_state=EARNINGS。
- missing: volatility LOW / HIGH、yen STRONGER、breadth 全 label、sector 全 label、event MACRO_DATA /
  GEOPOLITICS / NONE_DETECTED。→ 2 週間・単一局面（FOMC 直後〜月末）のみ。coverage > raw count。

## 19. 既知の制約（Phase 3.8 以降）

- 本環境には Market Bank / 営業日カレンダーが無く referenced session は UNKNOWN。Actions 環境で
  J-Quants calendar と Context を供給すれば alignment と CONTEXT label が有効になる（コード変更不要）。
- 本文分類は rule-based foundation。level_counts は 1 文を category ごとに数える（重複あり）。
- 8月号以降の原本は private 経路で `source_dir` へ置けば同じ pipeline で追加できる。
