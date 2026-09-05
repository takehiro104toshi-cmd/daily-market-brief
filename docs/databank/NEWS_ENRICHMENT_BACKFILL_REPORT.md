# NEWS_ENRICHMENT_BACKFILL_REPORT — 実コーパスenrichment実行報告（Phase 2-E / 2026-08-30）

対象: News Bank歴史コーパス **3,001 NewsItem**（P2-C移行済み・2026-06-22〜07-22）。
実行: ローカル（LLM未使用——optional層のskip動作も本番系で確認）。
corpus fingerprint: `ac5bde41a3cc7cd0…`（全stage一致——入力不変の機械証明）。

## 1. 段階実行（small sample → 500 → full）

| stage | seen | classified | unclassified | failed | 分類追加 | events | review | 時間 |
|---|---|---|---|---|---|---|---|---|
| sample-50 | 50 | 29 | 21 | 0 | 56 | 56 | 2 | 0.4s |
| stage-500 | 500 | 302 | 198 | 0 | 515 | 515 | 10 | 2.2s |
| **full** | **3,001** | **1,785** | **1,216** | **0** | **3,021** | 3,021 | 51 | **13.6s** |

会計: seen = classified + unclassified + failed（全stage一致）。
累計 **3,592分類・3,592 events・review queue 63件**・peak 47MB。

## 2. 冪等・検証

- 冪等再実行: 追加0・events 0・review 0 ✅（run跨ぎのcreated_at差はID同一性に
  含めない設計をこの実行で校正——初回実行で発見した実バグの修正）
- validation（10種・full corpus・evidence実テキスト照合/文書linkage込み）:
  **0 issues** ✅
- SQLite index全再構築 → canonical（bank＋enrichment store）から同一クエリ結果 ✅

## 3. provenance内訳

ENTITY_DATABASE 2,192 / RULE_BASED 1,400 / SOURCE_EXPLICIT 0（本コーパスは
source提供カテゴリを持たない——正直な0。機構はテストで検証済み）/ LLM 0（未使用）/
USER 0。全レコードにclassifier/version/taxonomy_version/evidence付き。

## 4. ReviewQueue 63件（黙って捨てなかった候補）

- **ambiguous_alias 58**: Apple 18・Alphabet 13・Amazon 11・Meta 7・Fed 7ほか
  ——文脈条件を満たさず**linkしなかった**曖昧alias（FALSE ENTITY LINK防止の実働記録）
- **unknown_ticker 5**: NASDAQ:SNDK / NASDAQ:VIVS / NASDAQ:SPCX等——明示ticker記法
  だがカタログ外（カタログ拡張候補として保存）

## 5. クエリsmoke（実corpus・監督者例）

| クエリ | 結果 |
|---|---|
| AIテーマ（corpus 30日窓 6/22-7/22） | 86件 |
| NVIDIA関連（company:nvidia） | 32件 |
| semiconductorsテーマ | 23件 |
| defenseテーマ | 71件 |
| company:nvidia × theme:ai | 5件 |
| country:US × GEOPOLITICS | 27件 |
| ticker NVDA | 32件 |
| Japan × MONETARY_POLICY | 0件（正直な結果: corpus窓に明示的な日銀決定見出しが無い。MONETARY_POLICY全体で4件・BOJ mention 11件） |

## 6. 時系列foundation（件数取得まで——傾向の主張はしない）

- aiテーマ週次件数: W26=1 / W28=33 / W29=52
- event type分布: EARNINGS 121・PRICE_MOVE 69・REGULATION 66・MA 54・GEOPOLITICS 41…
- 企業mention上位: NVIDIA 32・Alphabet 25・Tesla 19・Boeing 13・Intel/OpenAI/MSFT/TSMC 12

## 7. run manifest

enrichment_runs.jsonlへ全stage記録（run_id / corpus_fingerprint / entity catalog・
theme taxonomy・event taxonomy各version / classifier versions 4種 / 会計 / limit）。
LLM欄は空（未使用の正直な申告）。
