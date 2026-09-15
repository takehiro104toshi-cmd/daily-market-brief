# NEWS_ENRICHMENT_QUALITY — enrichment品質報告（Phase 2-E / full 3,001件）

METRIC LANGUAGE（P2-B以来の規律）: **fixture precision/recall**（ラベル付き30件への
測定）と**実corpusのcoverage**（何%に分類が付いたか）を区別する。実corpusの
precision/recallは人手レビュー無しに主張しない。

## 1. FIXTURE CALIBRATION（30件・ja/en・曖昧語negative含む）

対象領域: AI / semiconductor / rates / central bank / earnings / geopolitics /
defense / power / generic ambiguous（Apple果実・CAT scan・fed動詞・power単独・
Arm wrestling等のnegative 6件を含む）。

| 次元 | fixture precision | fixture recall | false positive |
|---|---|---|---|
| entity | **1.000** | 1.000 | **0** |
| theme | **1.000** | 1.000 | **0** |
| event type | **1.000** | 1.000 | **0** |
| time horizon | **1.000** | 1.000 | **0** |

（初回測定でevent fp2・fn3を検出→規則を校正して到達。fixtureへの過適合を防ぐため
negativeケースを固定——**production precision/recallの主張ではない**）

## 2. 実corpus COVERAGE（3,001件）

| 次元 | タグ付き件数 | coverage | 上位 |
|---|---|---|---|
| country（subject） | 1,088 | 36.3% | US 444・CN 191・IR 165・GB 140・IN 83・JP 69 |
| theme | 716 | 23.9% | energy 91・ai 86・defense 71・geopolitics 65・india 64・trade_policy 64・power 56 |
| event type | 467 | 15.6% | EARNINGS 121・PRICE_MOVE 69・REGULATION 66・MA 54 |
| company | 176 | 5.9% | NVIDIA 32・Alphabet 25・Tesla 19・Boeing 13 |
| ticker | 165 | 5.5% | NVDA 32・GOOGL 25・TSLA 19 |
| commodity | 108 | 3.6% | crude_oil 63・natural_gas 24 |
| central bank | 57 | 1.9% | Fed 30・BOJ 11・BOE 10・ECB 6 |
| time horizon | 34 | 1.1% | YEARS 30（高確信規則のみの正直な値） |

- **未分類 1,216件（40.5%）** … 一般ニュース（スポーツ・天気・社会面等）が
  金融taxonomyの守備範囲外——precision優先の設計上、正直なギャップとして報告。
- multi-label分布: 1テーマ587・2テーマ107・3テーマ18・4テーマ4。

## 3. publisher / language差

- publisher別分類率: SCMP 95.3%・Bloomberg 79.3%・Guardian 78.1%・Japan Times 69.3%・
  CNBC 68.5%・Al Jazeera 59.1%・CNA 56.7%・Yahoo Finance 46.8%
  （Yahoo FinanceはETF定型記事等の金融周辺コンテンツが多く、意図的にタグを絞る
  規則の帰結）。
- **ja 15件は分類0%** … 全て金融庁の行政公表物（ソルベンシー規制・有価証券報告書・
  ガイドライン等）で現taxonomyの守備範囲外。日本語規則自体は機能している
  （fixture・「日銀、利上げを見送り 円安進行」等で検証済み）。**JP官庁公表物向けの
  taxonomy拡張はP2-F候補**として記録。

## 4. LEGACY AGREEMENT（参考統計・not ground truth）

tank legacyテーマ（en slug→新slug対応28種でmap可能な788件）と新deterministic
テーマのany-overlap一致: **379件（48.1%）**。
解釈上の注意: legacyはLLM由来の多テーマ付与（寛容）・新系は多信号precision優先
（保守的）のため、不一致=どちらかの誤りではない。**自動昇格はしない**
（LegacyAnnotationは隔離を維持——P2-C決定の継続）。

## 5. ReviewQueue

63件（ambiguous_alias 58・unknown_ticker 5）。人間レビューのワークフローはP2-F
（本phaseは置き場と冪等蓄積まで）。

## 6. 既知の限界（正直な申告）

- カタログ企業36社の範囲でのcompany coverage（5.9%は「カタログ内企業の記事」の率）
- theme weak signal単独の意図的miss（"Power outage"等）——precision優先の設計コスト
- source-explicitカテゴリ0（本コーパスの取得時にRSSカテゴリを保存していない——
  今後の日次運用フィードでL0層が実働する）
