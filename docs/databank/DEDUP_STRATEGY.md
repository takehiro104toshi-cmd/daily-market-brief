# DEDUP_STRATEGY — 重複判定戦略（Phase 2-B）

## 1. signal一覧（独立に計算・単独ではsemantic mergeしない）

| # | signal | 実装 | 用途 |
|---|---|---|---|
| 1 | exact canonical URL | P1-C normalize_url（tracking除去のみ） | STAGE 1 |
| 2 | exact source GUID | source-local限定 | STAGE 1（cross-source禁止） |
| 3 | exact normalized fingerprint | P1-D content_fingerprint（title+summary） | STAGE 1（summary必須条件付き） |
| 4 | exact content hash | 生entry XMLのsha256 | STAGE 1 |
| 5 | normalized title similarity | **min(文字3-gram Jaccard, SequenceMatcher比)** | STAGE 2/3 |
| 6 | summary similarity | 同上（内容証拠） | STAGE 2 |
| 7 | published proximity | 時間差（不明時は近接を仮定しない） | STAGE 2/3 |
| 8 | numeric token set | タイトル数字集合の一致（NFKC後） | STAGE 2ガード |
| 9 | publisher / duplicate_group | 補助（confidence文脈） | 記録 |
| 10 | 明示syndicationメタデータ | ソース提供時のみ（推測しない） | 将来 |

## 2. 手法選定（LLM embedding不使用——P2-B指示）

- **文字n-gram Jaccard（n=3）を主軸**: word tokenizer非依存で日本語・英語の両方で
  機能（「日銀、政策金利を維持」の句読点ゆれは1.0、別記事は低値——テスト検証）。
- SequenceMatcher（stdlib difflib）を第2軸とし、**min()合成**で保守側に倒す
  （片方だけ高い場合に引きずられない）。
- TF-IDF cosineは不採用（コーパス依存のIDFが決定論・再現性を弱めるため。
  必要になればP2-E再検討）。外部依存の追加ゼロ。

## 3. threshold（校正値。推測固定ではない）

labeled fixture（実tankハザード含む29ペア）＋実tank title-onlyハザード40ペアで校正:

| パラメータ | 値 | 根拠 |
|---|---|---|
| auto_merge_title | 0.85 | 軽微編集（冠詞挿入等）がmin合成で0.89前後になる実測。0.90では正例を落とし、0.85でもfixture上のfalse merge 0を維持 |
| auto_merge_summary | 0.80 | 内容証拠の必須水準（同一summaryの転載編集を捕捉） |
| auto_merge_max_hours | 48h | 実ハザード（BBC Iran連日報道）が24h差のため、summary差と併用で安全を確認 |
| candidate_title | 0.70 | CANDIDATE観察の下限（merge権限なし） |
| 数字トークンガード | 集合不一致で禁止 | 実tank上位ハザードが全て数字違い（2027/2028・日付・通番） |

## 4. 校正結果（IDENTITY_CALIBRATION_REPORT.md詳細）

- DIFFERENT_ARTICLE 14ペア: **false merge 0**
- UNCERTAIN 3ペア: merge 0（安全側）
- 正例12ペア（SAME 6/REVISION 3/SYNDICATED 3）: **recall 12/12**
- title-onlyハザード40ペア（実tank）: merge 0（内容証拠なしmerge禁止の実証）
- 実tank 60記事runtime: 60 DISTINCT・誤merge 0

## 5. Phase 2後半へ残す課題

cross-publisher書き換え転載（同一内容・別文言）はexact/near-dup signalでは検出不能
（P2-A実測: tank内cross-domain衝突0）。NewsEvent clustering（P2-E以降）の責務。
