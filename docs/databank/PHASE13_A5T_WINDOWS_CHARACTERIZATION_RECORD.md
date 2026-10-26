# PHASE 13 — A5-T: WINDOWS CHARACTERIZATION RECORD（文書だけ ・本記録は実行を承認しない）

監督が受理した P13-A5 の Windows の特性の記録（A5-T の T-02 ・T-03）の結果を、守られた文書だけの記録として残す。本記録は
**受理した特性の記録の結果**だけを書き、P13-A5 の受理 ・A5-W の結果 ・A6 の判断ではない。本記録は実行を承認しない。
runtime ・凍結の契約 ・計画の記録 ・roadmap ・試験の helper ・故障の行列 ・既存の fixture ・runner ・設定 ・workflow は変えない。

| 項目 | 値 |
|---|---|
| gate | `P13-A5-T`（特性の記録 ・文書 ・registry ・guard だけ） |
| 基準の HEAD | `f503e9280f60cce1dc7cc28cc6c39575e1721a1e`（A5-0R の計画の記録の commit） |
| 計画 | `docs/databank/PHASE13_A5_WINDOWS_VALIDATION_PLAN.md`（本記録は変えない） |
| 監督の決定 | Windows の特性の記録は PASS / CLOSED ・G7 の独立の監査は PASS / CLOSED ・是正は R1（注記だけ）を受理 ・本記録の実装は 4 つの file に限って承認 |
| 状態 | P13-A5 は受理していない。Market Memory v1 は凍結していない。A5-W ・A6 は HOLD |

## 1. 範囲と主張しないこと

- 本記録は T-02 ・T-03 の受理した結果 ・証拠の identity ・限界 ・R1 の注記 ・残る義務だけを書く。
- 試験は注入した例外だけ。実際の process の終了 ・電源断 ・OS の crash は試していない。
- process の中の audit hook は OS の水準の閉じ込めではない。
- 観測は 1 つの host（native の Windows 11 Home ・管理者ではない ・Python 3.12.10）だけ。host の path ・時刻は記さない。
- 使い捨ての fixture は repo の外に在る（r01 〜 r07）。どれも保持し、変えない。残りの片付け ・lock の削除はしていない。
- Windows の期待の分類の表は無い（報告は `WINDOWS_EXPECTED_CLASSES=UNVERIFIED`）。Windows の期待の固定は T-05 の別の承認。
- 受理した POSIX の基準（42 の点 ・252 の場合）は変えない。POSIX の基準は静的な導出であり Linux では再検証していない。

## 2. 証拠の identity

| 証拠 | identity |
|---|---|
| T-02 の recorder | `p13a5-t2b-recorder:3` |
| T-02 の証拠の stdout | sha256 `bbc6880fd9524a3f39aee0a1de4f0bde3019785f198141f6dd11212cd4cf3d97` ・終了の code 0 |
| T-02 の Windows の全ての呼び出しの列（1,905 の呼び出し） | `b5b0b12ceae016569a5f284ee2174174053fb83f151b738275e834843b49d398` |
| POSIX の基準の列（42 の点 ・静的な導出） | `a93a996c57823182fe8d03f1759517bd95b383479e704f8bbba01af695bdc2cd` |
| T-03 の runner（R8-L.2） | `p13a5-t2c-runner:6` ・sha256 `9bd75714621bcd0b39f2effe80abd6e942bf394fa34ee73eb2a482410af186e2` ・127,278 byte |
| F1 ALL の選択（246 の場合） | `d0fb5f5010aa5a211ec2dc53c48ede70977d749ba6e2a4f451897e2ab814b57e` |
| F1 ALL の証拠の stdout | sha256 `85dab58a6004b9196ad831998abf6c7a1ed77dd52347c81678507463a6819e76` ・1,793,722 byte ・終了の code 0 |
| 無故障の基準の manifest | `cf2af47b70ba0a50b693d8be1c463305291dab9ae5f3ca02e823311af0dd029f`（37 の file ・29 の directory） |
| 残った vault の writer lock（4 の場合 ・同じ byte） | 92 byte ・sha256 `9e8d408dff076061d716e824912a932bc1186fa99cdf0e4d1d9028a261b51379` |
| 残った private の writer lock（1 の場合） | 98 byte ・sha256 `593e9e53b1f3ef0817d48d7d249c8bb91334f41494acdcea7c1bcbfd0fe7d04c` |

残った lock は決定的な `lock_record`（時刻 ・process の id を含まない）。証拠の file は repo の外に保持し、repo には写さない。

## 3. T-02 の結果（CLOSED）

- Windows の native の mutation の点は 41（K1 と K2 で同じ列 ・全ての呼び出しの列も同じ ・出力の木は K0 ・K1 ・K2 で同じ ・残りは 0）。
- 操作の内訳: create 11 ・write 11 ・fsync 11 ・mkdir 2 ・rename 3 ・replace 1 ・unlink 2。
- POSIX の基準は 42 の点。差はちょうど 1 つで、POSIX の予約の `mkdir`（`V:generated/<L>` ・POSIX の点 31）が Windows の道には無い。
  差の分類は `MATCHES_RESERVATION_HYPOTHESIS`（POSIX の予約の差）。
- この差のため Windows の点 31 以降は POSIX の点 32 以降に当たる（Windows の点 38 は POSIX の点 39）。

## 4. T-03 の結果（CLOSED）

- 選んだ場合 246 ・試みた場合 246 ・VALID 246（全ての場合で `CLASS_EVIDENCE=VALID`）。
- 分類の総数: A=142 ・H=9 ・M=95 ・F=0。

| 群 | 故障 | 2 つ目の故障 | 場合 | A | H | M | F |
|---|---|---|---|---|---|---|---|
| B1 | 前 | 無し | 41 | 26 | 2 | 13 | 0 |
| A1 | 後 | 無し | 41 | 26 | 2 | 13 | 0 |
| T1 | 切れ | 無し | 41 | 26 | 2 | 13 | 0 |
| B2 | 前 | 在る | 41 | 20 | 0 | 21 | 0 |
| A2 | 後 | 在る | 41 | 24 | 3 | 14 | 0 |
| T2 | 切れ | 在る | 41 | 20 | 0 | 21 | 0 |
| 計 | — | — | 246 | 142 | 9 | 95 | 0 |

- 1 つ目の故障は 246 の場合の全てで観測した（注入の観測 ・対象の一致）。
- 2 つ目の故障は 72 の場合で観測した（構成した 84 の場合のうち ・lock の接頭辞の照合は全てで一致）。
- 12 の場合は確かめた設計どおりの lock の在る拒否で 2 つ目の故障に届かない: B2-W02 ・B2-W05 ・B2-W40 ・B2-W41 ・A2-W01 ・
  A2-W02 ・A2-W04 ・A2-W05 ・T2-W02 ・T2-W05 ・T2-W40 ・T2-W41。
- E3 の免除は 12（`E3_DESIGNED_LOCK_PRESENT` ・各々の場合で高々 1 つ）。native の判定の総数は E1 45,836 ・E2 2,535 ・E3 12 ・
  INJECTED 318（1 つ目の 246 と 2 つ目の 72）。
- 必須の manifest は 996 が捕捉され安全（unsafe は 0）。G7 の独立の監査は disk との照合（群の木 12 ／ 12 ・回復の後の木 246 ／ 246 ・
  quarantine の file 101 ／ 101）が保存した証拠と一致すると確かめた。
- 見積もりの割り当ては 70,582,272 byte ・実行の時間は 314,483 ms。予期しない block ・未審査の event は無く、保護した mutation は 0。
- 残りは 18 の場合に在る。13 は保全による `.p13-interrupted`（H の 9 の場合と M の 4 の場合 B2-W26 ・B2-W29 ・T2-W26 ・T2-W29）。
  5 は class A の場合に残った writer lock（§5 の R1）。
- 報告だけの field: `SECOND_FAULT_HANDLED` は回復の試みの有無にすぎない。`INVARIANT_AUTO_SINGLE_STEP` が False の場合は 39 の
  AUTO の場合（`FAILED>PUBLISHED`）。どちらも分類 ・合否に使わない。

## 5. R1 の解釈（必須 ・注記だけ）

| 場合 | 凍結の規則の分類 | 2 つ目の故障 | 残った lock |
|---|---|---|---|
| B2-W38 | A | 回復の 8 番目の mutation ・vault の lock の unlink | vault の writer lock を保持 |
| A2-W38 | A | 回復の 8 番目の mutation ・vault の lock の unlink | vault の writer lock を保持 |
| T2-W38 | A | 回復の 8 番目の mutation ・vault の lock の unlink | vault の writer lock を保持 |
| A2-W40 | A | 回復の 7 番目の mutation ・vault の lock の unlink | vault の writer lock を保持 |
| A2-W41 | A | 回復の 8 番目の mutation ・private の lock の unlink | private の writer lock を保持 |

監督の必須の注記（原文）:

> B2-W38, A2-W38, T2-W38, A2-W40 and A2-W41 remain class A under frozen rules, but retain a writer lock.
> Data convergence does not imply operational readiness for the next publication.
> An authorized human procedure is required to resolve the lock safely.
> CLASS_EVIDENCE=VALID certifies evidence validity, not next-publication readiness.
> SECOND_FAULT_HANDLED and INVARIANT_AUTO_SINGLE_STEP are reporting-only.
> POSIX priors are historical comparisons, not verified native Windows outcomes.

- 5 つの場合は凍結の規則の下で class A のままだが、writer lock を保持する。
- data の収束は次の公開の運用の準備を意味しない。
- lock を安全に解くには、承認された人の手順が要る。
- `CLASS_EVIDENCE=VALID` は証拠の妥当性を証し、次の公開の準備を証さない。
- `SECOND_FAULT_HANDLED` と `INVARIANT_AUTO_SINGLE_STEP` は報告だけ。
- POSIX の先行値は歴史の比較であり、Windows で検証した native の結果ではない。
- 機構（source の分析）: 解放の `_unlink_if_owned` の失敗は `UNLINK_FAILED` から `LOCK_RELEASE_FAILED` になり、`_run` は結果に
  `lock_release` を付けて返すが `converge` はそれを見ない。次の公開は `*_LOCK_PRESENT` で拒否される見込みであり、これは source の
  分析と類似の観測した拒否からの推論で、5 つの場合で次の公開は試していない。
- 凍結の分類は黙って変えない。lock は消さない。

## 6. Windows と POSIX の分類の差（9）

Windows と POSIX の分類の差は 9。POSIX の先行値は歴史の比較であり、差は Windows の失敗ではない。

| 場合 | POSIX の先行値 → Windows | 2 つ目の故障の比較 | 説明 |
|---|---|---|---|
| B1-W31 | H→A | 比較できる | 予約の無い状態（POSIX の予約の `mkdir` が無い） |
| T1-W31 | H→A | 比較できる | 予約の無い状態（POSIX の予約の `mkdir` が無い） |
| B2-W31 | M→A | 比較できない | 点のずれの後の 2 つ目の故障の位置 |
| A2-W31 | M→A | 比較できない | 点のずれの後の 2 つ目の故障の位置 |
| T2-W31 | M→A | 比較できない | 点のずれの後の 2 つ目の故障の位置 |
| B2-W32 | A→M | 比較できない | 点のずれの後の 2 つ目の故障の位置 |
| T2-W32 | A→M | 比較できない | 点のずれの後の 2 つ目の故障の位置 |
| A2-W35 | A→M | 比較できない | 点のずれの後の 2 つ目の故障の位置 |
| A2-W29 | H→A | 位置は比較できる | source の推論だけ: POSIX の予約の `mkdir` が 2 つ目の故障の位置 8 の操作をずらす |

A2-W29 の原因は source の推論だけで、Windows でも POSIX でも直接には確かめていない。

## 7. 状態（本記録の時点）

| 項目 | 状態 | 根拠 |
|---|---|---|
| T-01 | OPEN / NOT EVIDENCED | 既存の P13 の suite を Windows で変えずに走らせた証拠は無い（r01 〜 r03 の狭い pytest の実行は T-01 ではない ・試験の id は記録に無い） |
| T-02 | CLOSED | §3 |
| T-03 | CLOSED | §4 |
| T-04 | PARTIAL | 点の対応と 9 の差の説明は在るが、A2-W29 は source の推論だけ ・2 つ目の故障を比べられない場合が残る |
| T-05 | OPEN | Windows の期待の表 ・platform ごとの数の assertion は無い（試験の変更は別の承認） |
| T-06 | OPEN | Windows の複製での独立の負の control は実行していない |
| A5-W | NOT FORMALLY EXECUTED | W-01 〜 W-20 は正式には実行していない（W-13 は特性の記録で実質的に覆われ、W-04 は観測しただけ ・どちらも A5-W の結果ではない） |
| A6 | HOLD | A5-W の core の BLOCKING の項目が残る |

P13-A5 は受理していない。Market Memory v1 は凍結していない。本記録は実行を承認しない（A5-W ・A6 ・T-05 ・T-06 ・pytest ・
helper の実行の権限は無い）。

## 8. 延期した設計の問い（提案だけ ・実装は承認しない）

- `LOCK_RELEASE_FAILED` の扱いと通知（`converge` が `lock_release` を見ない）。
- data の完全性と次の公開の準備を別々の指標として報告すること。
- 複数の試みの AUTO の報告の意味（`INVARIANT_AUTO_SINGLE_STEP`）。
- 本番の振る舞いを変えるべきか（監督の決定 ・別の gate）。
- 残った lock を解く人の手順（計画の §6 ・設計だけ ・実行できる道具は無い）。

## 9. 禁止と承認の範囲

- 本記録は文書 ・registry ・guard だけ。product の機能 ・runtime の振る舞いは変わらない。
- 禁止: lock の削除 ・残りの片付け ・r01 〜 r07 の変更 ・新しい fixture ・新しい故障の注入 ・凍結の分類の黙った変更 ・
  期待の数を失敗に合わせて書き換えること ・実の root ／ vault への access ・本番の公開。
- pytest ・commit ・push ・A5-W ・A6 ・T-05 ・T-06 は監督の別の明示の承認が要る。
