# COMPASS_CORPUS_RESEARCH_SPEC — Automatic Compass Corpus Analyzer（Phase 3.8）

Compass document が Corpus に追加されるたびに、source → structured analysis → market-state alignment →
editorial / analytical pattern extraction → cross-document comparison → pattern evidence → coverage →
benchmark を **自動・再現可能・versioned** に実行する研究層。実装は `src/intelligence/corpus_research/`
（1機能=1ファイル）、設定は `config.yaml: compass_research`、テストは
`tests/intelligence/test_corpus_research.py`（29 件）。production Compass rule を学習・変更しない。

## 1. 研究課題と境界

研究対象は「どんな市場状態で、どの Evidence を選び、何を Main Theme とし、どう解釈し、WHY をどう組み立て、
どの Outlook へつなげ、どの Risk を提示したか」という **分析構造**。

| Compass | ≠ | 
|---|---|
| source statement | Market Fact |
| printed number | Fact Store truth |
| interpretation | deterministic market principle |
| forecast | realized outcome |

客観 market state は J-Quants / Market Bank / Fact / Context / Internals を優先（3.6 J-Quants First）。
本文から客観市場状態を捏造しない。外部 LLM / embedding は使わない（OPTIONAL_FUTURE_ENHANCEMENT: 文分類の
精度向上には LLM が寄与し得るが、機密 PDF の外部送信は本 Phase では行わない）。

## 2. Architecture

```
CorpusSnapshot（3.7）→ statements → salience / links / why / outlook / risk → regime alignment
  → AnalyticalStructure → comparator（similarity）→ patterns（assignments）→ lifecycle（status）
  → registry / DNA comparison / conflicts → benchmark → review queue → CompassCorpusResearchSnapshot
```

| module | 役割 |
|---|---|
| `categories.py` | editorial selection の controlled vocabulary（JAPAN_EQUITY … TECHNICAL / OTHER / UNKNOWN）。無理に分類しない |
| `statements.py` | 3.7 observation → 順序付き文 index。research artifact には observation_id と text_hash のみ |
| `salience.py` | 見出し / 配置 / 初出 / 反復（上限）/ 専用段落 / outlook・why 連結の重み付き score（語数不使用、v1.0.0） |
| `links.py` | EVIDENCE→INTERPRETATION→OUTLOOK / EVIDENCE→OUTLOOK / EVIDENCE→RISK / EVENT→WATCH。同一段落内のみ。basis = 接続語 or 順序 |
| `why_model.py` | EXPLICIT_WHY / IMPLICIT_ASSOCIATION / NO_WHY / UNKNOWN。co-occurrence を因果にしない |
| `outlook_model.py` | direction（UP/DOWN/RANGE/MIXED/UNCERTAIN/NOT_STATED）/ horizon（INTRADAY…LONG/NOT_STATED）/ ladder / target / conditional / caveat |
| `risk_model.py` | EXPLICIT_RISK / COUNTERARGUMENT / INVALIDATION_CONDITION / UNCERTAINTY / WATCH_ITEM / NOT_RISK |
| `regime.py` | `MarketConnector`（calendar / Context / Market Bank へ読み取り専用）。CONTEXT ＞ EXTRACTED_VALUE ＞ UNKNOWN。known_at ≤ 発行 cutoff（07:30 JST） |
| `structure.py` | AnalyticalStructure（§3） |
| `comparator.py` | 重み付き Jaccard（regime .25 / evidence .25 / theme .15 / why .10 / outlook .15 / risk .10）。shared / different features を返す |
| `patterns.py` | pattern identity = canonical component hash。粒度: FULL / EVIDENCE_OUTLOOK / STATE_OUTLOOK / THEME_OUTLOOK / EVIDENCE_WHY / EVIDENCE_RISK |
| `lifecycle.py` | OBSERVED → NEW_PATTERN_CANDIDATE → REVIEW_CANDIDATE → STRONG_PATTERN_CANDIDATE（上限）。APPROVED は返せない |
| `store.py` | canonical JSONL 9 ファイル、`digest()`（timestamps 除外）、version_key ごとの state |
| `dna_comparison.py` | `market_rules.yaml`（読み取りのみ）との比較・conflict 記録 |
| `benchmark.py` / `review_queue.py` / `acquisition.py` / `research_snapshot.py` | §7–§10 |
| `engine.py` | incremental / full rebuild / equivalence |
| `intake_hook.py` / `batch_import.py` | 3.75 boundary（失敗隔離・bounded retry）/ private batch 追加 |

## 3. AnalyticalStructure（analysis unit）

document_id / document_date / corpus_analysis_version / analyzer versions / quality / eligible /
market_state（regime labels + sources）/ regime（referenced session, known_at cutoff, look_ahead_rejected,
comparable_values）/ selected_evidence（salience 順）/ main_theme（P1 【】見出し → 3 本目ボレット → top salience）/
supporting_themes / interpretations / why_links + why_summary / outlook + outlook_summary / risk + risk_summary /
watch_items / coverage_labels / market_alignment / salience_profile / links / field_support / pattern_assignments。
支持のない field は空のまま（`field_support` が false）。本文は含まない。

## 4. Pattern model

pattern ≒ MARKET STATE + SELECTED EVIDENCE + WHY + OUTLOOK or RISK。component が無い partial type を許す。
record: pattern_id / pattern_version / pattern_type / components / supporting_document_ids / support_count /
eligible_support / regime_count / regime_coverage / date_range / span_days / valid_ratio / status /
thresholds_version / evidence_references（observation_id → 3.7 provenance chain で原本まで辿れる）/
quality / first_seen / last_seen / limitations。record は append-only（支持が増えると新 record、旧 record 保持）。

### 4.1 Lifecycle thresholds（v1.0.0、`config.yaml`）

| status | 条件 |
|---|---|
| OBSERVED | 1 observation |
| NEW_PATTERN_CANDIDATE | support ≥ 2 |
| REVIEW_CANDIDATE | eligible support ≥ 3 かつ regime ≥ 2 かつ期間 ≥ 30 日 |
| STRONG_PATTERN_CANDIDATE | eligible support ≥ 5 かつ regime ≥ 3 かつ期間 ≥ 90 日かつ全 VALID |
| APPROVED / REJECTED / SUPERSEDED | **Phase 3.8 では付与しない**（3.9 の監督者 process） |

support count だけでは昇格しない（regime diversity・期間・quality）。

### 4.2 Anti-overfitting

現 Corpus は 10 本・2026-06-18〜07-01（13 日・単一局面）。全結論に limitation を付ける:
CORPUS_SIZE（eligible < 30）/ SHORT_SPAN（< 30 日）/ SINGLE_REGIME / NOT_PREDICTIVE。
普遍的な市場ルールも予測妥当性も主張しない。単一の 2 週間局面だけで昇格しない（REVIEW 以上に到達不可）。

## 5. Pattern Registry と Compass DNA

`pattern_registry.json`（`is_production_rule_source: false`）は研究 evidence。`market_principles.py` /
`market_rules.yaml` / production Compass rule とは分離し、自動同期しない。
DNA comparison: rule の conditions / implication key を category へ写像し、pattern の evidence・target・
direction と突き合わせて EXPLAINED_BY_EXISTING_RULE / PARTIALLY_EXPLAINED / NEW_PATTERN_CANDIDATE /
CONFLICTS_WITH_EXISTING_RULE / NOT_COMPARABLE。conflict は rule_id・supporting documents・regimes・evidence を
記録し、どちらが正しいか決めない。

## 6. Incremental / rebuild / versions

- incremental: 未解析 document の structure だけ作り、その document を含む similarity pair、割り当てられた
  pattern の record、DNA 比較、review queue、benchmark、snapshot を更新。決定的・idempotent（再実行で追記 0）。
- full rebuild: fresh root へ全 document を再構築。`equivalence()` で derived digest（timestamps 除外）が一致。
  pattern record は corpus 規模に依存しない（corpus-level limitation は表示時に付ける）ため incremental ≈ rebuild。
- versions: structure / salience / link / why / outlook / risk / similarity / pattern / thresholds / benchmark の
  10 version。version_key ごとに state を持ち、旧結果を保持、混在しない。

## 7. Benchmark（予測精度ではない）

| metric | ground truth |
|---|---|
| category_extraction_agreement | P2 mode（紙面構造: fx_outlook / us_equity_outlook）と抽出 outlook の target |
| headline_theme_agreement | main theme が top-3 salience に含まれる |
| outlook / why / risk / watch / alignment / context coverage | 各 field を抽出できた document の比率 |
| pattern_assignment_stability | 保存 assignment と再計算の一致 |
| rebuild_equivalence / incremental_equivalence | digest 一致（pilot で計測） |

labelled ground truth の無い precision / recall は出さない。「Compass の分析論理を再構成できるか」と
「将来市場を予測できるか」は別問題（後者は Prediction Journal）。

## 8. Supervisor Review Queue / acquisition / snapshot

review queue（auto approval なし）: NEW_PATTERN / PATTERN_CONFLICT / LOW_CONFIDENCE_EXTRACTION /
UNUSUAL_REGIME / NEW_THEME_CATEGORY / DNA_CONFLICT。各 item に理由と evidence 参照。
acquisition: coverage report の missing（HIGH）/ underrepresented（MEDIUM）/ Context 供給が必要（DATA_SUPPLY）。
`research_snapshot.json`: corpus_count / eligible / date_range / milestone / coverage / analyzer_versions /
patterns_by_status / top candidates / new candidates / conflicts / similar documents / benchmark / review_queue /
acquisition / market_connector / limitations / boundaries。

## 9. Intake integration と失敗隔離

`mobile_intake.processor` は `post_ingest(document_id)` callable を受け取るだけ（adapter は research を知らない）。
`intake_hook.ResearchTrigger` が bounded retry（既定 2 回）で incremental を呼び、失敗しても
CORPUS_SUCCESS + RESEARCH_ANALYSIS_FAILED を記録するだけで Corpus ingestion は巻き戻さない。
`batch_import.py`: dedup / bounded batch / progress / failure isolation / Git 非追跡 / 最後に incremental 1 回。

## 10. 実 10 document pilot（isolated root `compass_research_pilot`、offline 4 s）

| 項目 | 実測 |
|---|---|
| structures | 10/10（eligible 10）。links 9–28 / doc、why EXPLICIT 3–8 / doc |
| market connector | calendar / Context / Market Bank いずれも本環境に無し → referenced session UNKNOWN、comparable 0/10、CONTEXT label 0（EXTRACTED_VALUE 79 / TEXT_KEYWORD 10 / UNKNOWN 41 dims）。Actions 環境で store を供給すれば同じコードで CONTEXT が優先される（テストで検証） |
| similarities | 45 pair（top 例: 0.577、shared: equity UP / SECTOR / THEME / why EXPLICIT / horizon 1D / target JAPAN_EQUITY） |
| patterns | 53（FULL 10 / EVIDENCE_OUTLOOK 10 / STATE_OUTLOOK 10 / THEME_OUTLOOK 8 / EVIDENCE_WHY 7 / EVIDENCE_RISK 8）。OBSERVED 49 / NEW_PATTERN_CANDIDATE 4 / REVIEW 0 / STRONG 0 / APPROVED 0 |
| top candidate | EVIDENCE_WHY（SECTOR + THEME → EXPLICIT_WHY）support 3・regime 3（06-19〜06-26）— limitation: CORPUS_SIZE / SHORT_SPAN / NOT_PREDICTIVE |
| DNA comparison | PARTIALLY_EXPLAINED 49 / EXPLAINED 3 / NEW 1 / conflicts 0（rules 13 読み込み、変更なし） |
| benchmark | category agreement 1.000、headline theme 0.800、outlook direction 1.000、why explicit 1.000、risk 1.000、watch 1.000、alignment 0.000、context 0.000、assignment stability 1.000 |
| review queue | 17 open（NEW_PATTERN 4 / PATTERN_CONFLICT 1 / UNUSUAL_REGIME 10 / NEW_THEME_CATEGORY 2） |
| idempotency | 2 回目の run: 追記 0、digest 同一 |
| N+1 fixture（別 root、再保存 PDF、実 Corpus に数えない） | 新 document 1、incremental structures 1、affected patterns のみ更新、fixture root 11 / 実 10 不変 |
| rebuild equivalence | incremental digest == full rebuild digest |
| version bump（pattern 1.0.1） | 旧 53 record 保持、新 version 53 record、state key 2 本、混在なし |
| failure isolation | CORPUS_SUCCESS + RESEARCH_ANALYSIS_FAILED、attempts 2、Corpus document 保持 |
| security | tracked PDF 0、原本 hash 不変、repository 不変、production research root 不変、network / LLM import 0、research artifact に本文・full path なし |

## 11. Historical expansion と acquisition

`python -m src.intelligence.corpus_research.batch_import --source <private dir> --max 20`。
coverage-guided acquisition（研究資料の取得推奨・投資助言ではない）: 円高局面 / 高・低ボラ局面 /
米金利低下・日本金利低下局面 / バリュー優位 / 決算集中期 / 指標発表週 / 地政学局面。breadth・sector は
Context 供給（J-Quants）が必要。
