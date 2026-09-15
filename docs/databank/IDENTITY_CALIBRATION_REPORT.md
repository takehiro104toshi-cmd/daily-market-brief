# IDENTITY_CALIBRATION_REPORT — identity判定の校正報告（Phase 2-B / 2026-08-30）

## 1. CALIBRATION DATASET（計69ペア＋実runtime 60記事）

### labeled fixture（29ペア・`tests/intelligence/identity_calibration_pairs.py`）

| label | 件数 | 内容 |
|---|---|---|
| DIFFERENT_ARTICLE | 14 | **実tankハザード**（ECBカレンダー2027/2028 sim0.957・Bloomberg日次連載0.947・FedReg通番0.917・BBC Iran連日同型見出し）＋実同一event別publisher5ペア（関税・Houthis・活動家・山火事）＋合成（決算定型ja/en・日経平均日次・GDP速報） |
| SAME_ARTICLE | 6 | tracking URL違い / 同一GUID / **実データBBCガスパイプライン（ハイフン編集・sim1.000）** / 軽微編集en / 句読点ゆれja / 同一内容URL違い |
| REVISION | 3 | 同一URL速報→詳報 / 同一GUID更新 / ja数値確定更新 |
| SYNDICATED_COPY | 3 | Reuters→Yahoo型en / ja転載 / wire→紙面 |
| UNCERTAIN | 3 | 実SCMP HKEX（sim0.958・改稿か別記事か人間でも判別困難）/ paraphrase en / ja |

### title-onlyハザードコーパス（40ペア・実tankタイトル）

全3,056記事の同一publisher内ペア類似度スキャン上位（0.60〜0.91）。改題と別記事が
混在するためground-truthラベルは付けず、**「内容証拠なしではmerge禁止」の安全条件
検証**に使用（FERC通番・PJM Supplemental・Z.ai/Zhipu改称・typo修正等の実在ペア）。

### 実データruntime検証（60記事）

tank実記事60件（ja10・federalregister12・bloomberg8・eia6・一般24）を
normalize→ingest。

## 2. 結果（PRECISION FIRST）

| 指標 | 結果 |
|---|---|
| **false merge（DIFFERENT 14ペア）** | **0** ✅（目標達成） |
| UNCERTAIN 3ペアのmerge | 0（安全側） |
| **recall（正例12ペア）** | **12/12 = 1.00**（SAME→EXACT/AUTO_MERGE・REVISION→REVISION・SYNDICATED→SYNDICATED全て正解） |
| ハザード40ペアのmerge | 0 ✅ |
| 実tank 60記事 | 60 DISTINCT・誤merge 0・validation issue 0（dedup済コーパスへの正しい挙動） |

precision（fixture上）= 1.00、recall（fixture上）= 1.00。
注: fixtureは代表ケースであり実運用recallはこれを下回りうる（PRECISION FIRSTにより
recall不足は許容——CANDIDATE経由で人間/後段が拾える）。

## 3. 校正で確定したthreshold・規則

DEDUP_STRATEGY §3参照。校正過程での主要な設計修正:

1. **title-only fingerprint一致のexact扱いを廃止**（校正中に発見: summary空同士の
   fingerprint＝見出しhashで、定型見出しがEXACT_MATCH化する欠陥→summary必須条件を追加）。
2. **数字トークンガード新設**（実データ分析: 高類似別記事の上位が全て数字違い）。
3. auto_merge_title 0.90→**0.85**（min合成での軽微編集の実測0.89に合わせ、
   false merge 0を維持したまま正例を回収）。

## 4. FALSE MERGE AUDIT（Black Box merge禁止）

`identity_report.render_merge_audit()` が全mergeについて
「判定種別・対象article・confidence・matched/failed signals・algorithm version」を
人間可読で出力する（テストで出力内容を検証）。CANDIDATEは「不足signal」付きで
別掲され、merge済みとの区別が常に明示される。

## 5. 再校正の手順

threshold変更時: (1) IdentityThresholdsを変更 (2) calibration testを実行
（false merge 0が破れたら棄却） (3) `algorithm_version`を上げ、
本報告書へ追記。fixtureへのペア追加は随時（append-only）。
