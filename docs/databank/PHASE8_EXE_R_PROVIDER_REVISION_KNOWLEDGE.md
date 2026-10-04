# PHASE 8 / P8-EXE-R — PROVIDER REVISION ACQUISITION-TIME KNOWLEDGE（provider 側の変更の知識は取得の時刻）

P8-A2C-R1 の設計で見つかった凍結 runtime の依存（`P8_A2C_R1_FROZEN_DEPENDENCY_FOUND`。監督が受理）を閉じる gate。
凍結 EXE の executor の **provider 側の変更（同じ自然 key ・違う digest）の扱いだけ**を再開した。coverage ・`holdings_as_of` ・
subject-scoped coverage ・retrospective resolver ・epoch ・A3 の adapter ・実 request ・private の pilot の store の変更は**無い**。

- 基準: P8-OBS60-I1 `9d833b2fe4f359cad00f1bbdfb0943487c8ea10f`（凍結。runtime 35）。full pytest の基準 6041 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の値 ・会社名を載せない。例はすべて合成。

---

## 0. 結論

1. **見つかった問題**: 凍結 ADP0 の provider の record の参照 `jq.fins_summary:<Code>.<DiscNo>.<DocType>:<digest24>` は内容の digest
   を含む。provider 側が同じ自然 key（Code ・DiscDate ・DiscTime ・DiscNo ・DocType）の行の内容だけを修正すると（公式の修正履歴にある
   「データ全般を修正」）、参照が変わり、凍結 EXE はそれを**新しい revision として元の開示日時（DiscDate ・DiscTime）の知識で** append して
   いた。凍結 A2 は末尾と同じ知識を認めるので append は通り、`_chain_head` は cutoff で知られた最後の record を選ぶため、**元の開示の
   直後のあらゆる STRICT な cutoff で、後から取得した修正値が過去の PIT の答えを書き換えていた**（遡及の修正の禁止に反する）。
2. **自然 key と digest の区別**: 自然 key は凍結 ADP0 のまま（再定義しない）。
   - **provider の訂正** ＝ 新しい DiscNo（別の自然 key）: 従来どおり、その訂正自身の DiscDate ・DiscTime を知識にする新しい revision。
   - **provider 側の変更** ＝ 同じ自然 key ・違う digest: 本 gate の対象。
3. **世界の知識と system の知識**: `DiscDate` ・`DiscTime` は provider が報告する世界 ／ 公開の開示の知識。`AdapterContext.acquired_at`
   は「この system がこの bounded な provider の表現を取得した時刻」。初見の行（何年も後に取得した過去の行を含む）は世界の開示の知識を
   保つ。同じ自然 key の変更は、それより早い変更の時刻が何も立証されていないので、**保守的な system の知識の境界として `acquired_at`**
   を知識にする。`acquired_at` を provider の実際の修正の時刻だと主張しない。
4. **fail closed**: 変更を検知して `acquired_at` が無ければ、開示日時に落とさず `REJECTED / PRECHECK_FAILED` ・failure code
   `PROVIDER_REVISION_ACQUISITION_TIME_REQUIRED`（0 書き込み）。naive な `acquired_at` は凍結 ADP0 の `AdapterContext` が拒む。
5. **同じ digest の再取得**: `REUSED` のまま（新しい revision ・supersedes ・知識 ・id の変更なし）。`acquired_at` が後でも revision には
   ならない。変更の revision 自身の再取得も `REUSED`（参照の一致 ＝ 内容 ・開示日時の一致。知識の比較は外した。知識は EXE-R で取得の
   時刻になり得るため）。
6. **追記専用**: 元の観測 ・その知識 ・鎖の過去の member は不変。変更は `supersedes = 鎖の末尾` の新しい不変の revision。2 度目の変更は
   さらに後の取得の時刻で鎖に続く。末尾より前の取得の時刻は凍結 A2 が `NON_MONOTONIC_KNOWLEDGE` で拒む。
7. **STRICT PIT の受け入れ条件（test で固定）**: 元の開示の後 ・取得の前の cutoff → 元の record（元の値）。取得の後の cutoff → 変更の
   revision。取得の直前 → 元のまま。
8. **会計基準の不連続（OBS-57）・ADP0 の保留**: 変わらない（IFRS の行は `SEMANTIC_CHAIN_CONFLICT`、Foreign は `ACCOUNTING_STANDARD_UNKNOWN`）。
9. **R1 との関係**: これで P8-A2C-R1 の凍結の依存は閉じた。epoch の membership ・`holdings_as_of` ・subject-scoped coverage は
   未実装（別 gate ・監督の決定）。本 gate は retrospective な coverage を実装しない。
10. **既存の実 pilot**: 21 の観測は書き換えない ・移行しない。remediation は将来に同じ自然 key の変更に出会ったときに前向きに働く。

---

## 1. 変更

| 対象 | 変更 |
|---|---|
| `jquants_financial_summary_executor.py` | `_plan_field` に `acquired_at` を渡し、同じ自然 key ・違う digest の鎖の member があれば知識を `KnowledgeTime.exact(acquired_at)` にする（無ければ `_Abort`）。helper `_natural_key_ref`。同じ参照の replay の比較から知識を外す。import に `KnowledgeTime`。module docstring の注記 |
| ADP0 `AdapterContext` | 変更なし（`acquired_at: Optional[datetime]` ・aware 必須は既存） |
| A1 ・A1R ・A2 ・A2R ・A3 ・ADP0 ・ST1 ・ID1 ・ID2 ・LIVE1 ・LIVE2 ・PILOT2A ・ACQ0 ・I1 | 変更なし（OBS60-I1 の anchor と byte 一致。guard `test_exe_r_*`。executor の差は AST で `_plan_field` ・`_natural_key_ref` ・`_execute_eligible` ・import の 1 行に限る） |

---

## 2. 判定の表

| 状況 | 知識 | 結果 |
|---|---|---|
| 初見の自然 key | DiscDate ・DiscTime（DiscTime 空 → DATE） | `APPENDED`（`acquired_at` は使わない） |
| 同じ自然 key ・同じ digest | 変わらない | `REUSED`（`acquired_at` の有無 ・前後に依らない） |
| 同じ自然 key ・違う digest ・`acquired_at` あり | `acquired_at`（TIMESTAMP） | `APPENDED`（新しい revision。`supersedes` ＝ 鎖の末尾） |
| 同じ自然 key ・違う digest ・`acquired_at` なし | — | `REJECTED / PRECHECK_FAILED / PROVIDER_REVISION_ACQUISITION_TIME_REQUIRED`（0 書き込み） |
| 新しい DiscNo の訂正 | 訂正の DiscDate ・DiscTime | `APPENDED`（従来どおり。`acquired_at` 不要） |
| 鎖の末尾より前の `acquired_at` | — | `REJECTED / OBSERVATION_CONFLICT / NON_MONOTONIC_KNOWLEDGE` |
| 会計基準 ・区分の不連続 | — | `HELD / SEMANTIC_CHAIN_CONFLICT`（変わらない） |

---

## 3. 次の gate

P8-A2C（subject-scoped `ObservationCoverage` ・`holdings_as_of` ・retrospective resolver。監督の決定の後）→ P8-OBS60-F1 → P8-A3-RA →
P8-PILOT2B。
