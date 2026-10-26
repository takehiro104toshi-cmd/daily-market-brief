# PHASE 12.5 — MARKET MEMORY ／ OBSIDIAN ARCHITECTURE DESIGN: DESIGN COMPLETE / CLOSED / FROZEN（設計だけ ・runtime は無い）

Phase 12.5（Market Memory ／ Obsidian の設計）の最終の closeout の記録（P12.5-A5）。閉じて凍結するのは **architecture の設計の契約**だけ
（P12.5-A0 ・A2 と A4 の整合の是正）。**P13 の runtime（Market Memory の実装）は存在しない ・P14（継続学習）は未着手 ・P12 B-track
（取得の自動化）は HOLD のまま**であり、本記録はそれらの実装 ・importer の登録 ・private root ・vault ・資格情報のいずれも承認しない。
本記録 ・registry ・guard ・CHANGELOG だけの記録であり、runtime ・設計の意味は変えない。**この記録の commit は新しい設計の anchor ではない。**

| 項目 | 値 |
|---|---|
| 状態 | **DESIGN COMPLETE / CLOSED / FROZEN**（Phase 12.5 の architecture の設計だけ） |
| 設計の anchor | `2d18133fdde8306c7b260b3e94669eefd448b188`（registry の `P12_5_DESIGN_ANCHOR`。A4 の是正の commit。A0 ・A2 の契約の blob はこの commit で確定） |
| 凍結の範囲 | `PHASE12_5_A0_MARKET_MEMORY_ARCHITECTURE.md`（architecture の契約）・`PHASE12_5_A2_SOURCE_CAPABILITY_CONTRACT.md`（source の能力の契約 ・P13 Review State Memory MVP） |
| P13 runtime | **存在しない**（`src/` に Market Memory の package は無い。guard が不在を pin する） |
| P14 ・B-track | P14 未着手 ・B-track HOLD（本記録の範囲の外 ・完了とも言わない） |
| Phase 12 A-track v1 | COMPLETE / CLOSED / FROZEN のまま（`e390cddff9101541d16ba308a15d9ad1df3ca7b7` ・validated `3056e25586767fd7b5d8095f016a4d254de5c360`。runtime 43 file は object 一致） |
| Phase 8 ／ 9 ／ 10 ／ 11 | COMPLETE / CLOSED / FROZEN のまま（`0a32d86…` 54 file ・`4c19701…` 18 file ・`1a7b9a2…` 17 file ・`43c0b85…` 12 file は object 一致） |
| 公開の面 ・config ・workflow ・Secrets ・private root ・pin ・scheduled task | 不変（P12.5 の全 gate で触れていない） |

guard: `tests/intelligence/test_automation_boundary.py` の `test_p12_5_closeout_the_design_contracts_are_frozen_at_the_anchor_and_the_record_is_design_only` と
`test_p12_5_closeout_guard_rejects_mutated_records_and_foreign_anchors`（§8）。

---

## 1. anchor と本記録の関係

- `P12_5_DESIGN_ANCHOR`（`2d18133fdde8306c7b260b3e94669eefd448b188`）は P12.5-A4（A0 の整合の是正）の commit。A0 と A2 の文書の git の blob は
  この commit のものが凍結の対象であり、guard が HEAD の blob と anchor の blob の一致を pin する。
- 本記録の commit は文書 ・registry の定数 ・guard ・CHANGELOG だけを足す。A0 ・A2 の blob ・`src/` ・凍結の phase の runtime は anchor と同じ。
  **本記録の commit は新しい設計の anchor ではない**（記録は anchor の後に在り、anchor には本記録は存在しない。guard が pin する）。
- A0 ・A2 の変更は、以後は監督が承認した狭い再開（新しい gate と anchor の再設定）だけ。

## 2. P12.5 の gate の履歴（設計だけ）

| gate | 内容 | commit |
|---|---|---|
| P12.5-A0 | architecture の契約（hybrid ・DERIVED ・PIT ・export だけ ・分離） | `f205c0c…`（v6.23） |
| P12.5-A1 | source capability investigation（報告だけ ・commit 無し） | — |
| P12.5-A2 | source capability contract ・P13 Review State Memory MVP ・P13-A2a の登録の提案（実装しない） | `9cd14fb…`（v6.24） |
| P12.5-A3 | design closeout investigation（報告だけ ・A0 ／ A2 の不整合 5 件を特定） | — |
| P12.5-A4 | A0 の整合の是正（§2.2 ・§4 ・§5.3 ・§5.4 ・§5.5 ・§6.3 ・§11。A2 は不変） | `2d18133…`（v6.25。設計の anchor） |
| P12.5-A5 | 本記録 | 本 commit（anchor ではない） |

## 3. A0 ／ A2 の契約と A4 の是正の要約

- **A0**: Market Memory は凍結の P8 〜 P12 の上に乗る **決定論 ・DERIVED ・read-only ・networkless** の記憶の層。hybrid（統治された read-only の
  source adapter ＋ 構造化の memory store ＋ private な Markdown ／ Obsidian の投影 ＋ 生成 note と人の note の分離 ＋ 人の note の自動取り込み無し）。
  3 つの時刻の軸（event time ・known_at ・telemetry）・明示の aware な cutoff ・歴史の保存 ・supersedes の lineage ・状態の区別（CURRENT ／
  SUPERSEDED ／ MISSING ／ STALE ／ UNKNOWN ／ UNCERTAIN ／ AMBIGUOUS ／ INTEGRITY_FAILURE）・staged → verified → published の crash-safe な export ・
  path ／ symlink ／ junction ／ Markdown ／ 外部 link ／ 埋め込まれた秘密 ／ export 先の check ・既知の sync 先の拒否（検出は不完全で保証ではない）・
  B-track ・network ・新しい取得無しで動く ・LLM ／ embedding ／ 自己学習 ／ 自律の決定は v1 に無い。
- **A2**: 凍結の read の面の目録（file ・symbol ・行）・「呼べる」と「消費を承認されている」の区別（凍結の boundary test が import の面を文字列 ・
  完全一致で固定する）・AVAILABLE ／ LIMITED ／ GATED ／ UNAVAILABLE の定義と能力の行列 ・**P13 の MVP ＝ Review State Memory**（入力は P10 の
  governed な `read_personal_review` ・`read_p9_safe_view` ・`personal_safe_projection` だけ）・標本は「cutoff で有効だった状態」、変化は「cutoff で
  区切った区間の観測」、同じ端点は変化の不在を証明しない、`sampled_at` は telemetry、known_at を作らない ・`ReviewStateSample` ／ `ReviewStateChange`
  の提案 ・P8 の `KnowledgeTime` の状態と resolver の status の 2 層 ・P13-A2a の登録の提案（実装しない）・MVP の外（GATED）。
- **A4 の是正**（A3 が特定した 5 件 ＋ 1 件の明確化）: §5.5 の P8 の語彙の 2 層化 ・§4 ／ §5.3 の 2 つの DERIVED の族 ・§5.4 の build identity の
  一般化（順序つきの cutoff の集合 ・root の manifest は任意 ・決定論の identity は source の不変を証明しない）・§11 の古い記述の訂正
  （governed な view は id 粒度）・§2.2 の P8 の消費は全て GATED ・§6.3 の file 名は例示。監督が 6 件を承認し、A0 と A2 は意味として整合した。

## 4. 承認した設計の不変量（P13 の guard が継承する）

1. **hybrid の構造化 DERIVED の memory ＋ Markdown の投影**: store は構造化 ・追記専用 ・content-addressed、vault は投影であって store ではない。
2. **統治された read-only の source の境界**: 凍結の phase の authority ・ledger に書かない ・承認済みの governed な面だけ ・新しい private の
   読み取り面を発明しない ・P8 の消費は全て GATED ・importer は凍結の test の狭い再開で正確に登録する。
3. **明示の PIT と真実の provenance**: 明示の aware な cutoff と `as_of_date` だけ ・「最新」「今」は無い ・provenance は source が与える以上を主張しない。
4. **2 つの record の族**: `MemoryItem`（source の正準 digest と本物の known_at を要する）と `ReviewStateSample` ／ `ReviewStateChange`（P10 の
   governed な標本。provenance の限界を記録する）。型で区別し、一方の規則を他方に合わせて弱めない。
5. **捏造しない**: 無い source の known_at ・revision の digest ・transition の瞬間を作らない。標本の間の変化は区間の観測、同じ端点は変化の不在を
   証明しない、`sampled_at` は telemetry。
6. **決定論の identity と replay**: identity は telemetry と無関係 ・build identity は順序つきの cutoff の集合 ・入力の記述子 ・schema version ・規則の
   version から ・同じ入力は byte 一致 ・決定論の identity だけでは private な source の不変を証明しない。
7. **安全な staged の Obsidian export**: staged → verified → published ・検証に通る代替が揃う前に既存の生成 note を消さない ・`generated/` だけを書き
   `notes/` は読まない ・path ／ symlink ／ junction ／ traversal ／ 外部 link ／ HTML ／ embed ／ 埋め込まれた秘密 ／ export 先 ／ sync 先の check。
8. **v1 に無いもの**: authority への書き込み ・取得 ・network ・資格情報 ・LLM ／ embedding ／ 自己学習 ・自律の決定 ・順位 ／ score ／ 推奨 ／
   配分 ／ 取引の意味（NON-GOAL）。
9. **B-track が無い状態は支持する条件**: 自動の取得 ・network ・新しい取得が無くても Market Memory は動き、鮮度は表明するもので仮定しない。

## 5. 将来の実装の gate の公式の順序（各 gate は監督の個別の GO を要する ・本記録は承認しない）

1. **P13-A0** runtime surface registration — 新しい `src/` の package の面を凍結の P7 〜 P12 の boundary test に **test だけ**の登録で足す
   （P12-A1 の `PHASE12_TEST_REGISTRATION` の様式。凍結の test は `src/` の面の完全一致を要するので、純粋な model でもこの gate 無しには始められない）。
2. **P13-A1** pure memory model — 合成の入力 ・stdlib だけ ・凍結の package を import しない ・標本 ／ 変化の schema と id の接頭辞をここで確定。
3. **P13-A2a** governed P10 adapter — A2 §10 の import の集合（P11 と同一）の正確な登録 ＋ adapter ＋ negative test。
4. **P13-A3** store ／ rebuild — 追記専用 ・checkpoint ・idempotent な rebuild ・状態の区別。
5. **P13-A4** Obsidian projection — template ・sanitization ・export の id ／ file 名の規則 ・目印 ・sync 先の拒否 ・staged publication。
6. **P13-A5** Windows private validation — repo の外の helper ・read-only の source ・使い捨ての vault ・前後の manifest（P12-A6 の様式）。
7. **P13-A6** final freeze — 記録 ・registry ・guard。
G2（P12 ledger）・G3（P8 取得の metadata）・G4（P8 観測）・G5（P9 の構造の revision timeline）は上の列の外の別の gate。

## 6. 先送りの決定（監督。本記録は決めない）

- P9 ／ P10 の root の file の byte の manifest と source の整合性の検証（P13 で計算するか ・build identity に入れるか）。
- `ReviewStateSample` ／ `ReviewStateChange` の schema ・id の接頭辞 ・永続化（P13-A1）。
- export の識別子 ・file 名の規則（P13-A4）。
- STALE の方針（窓）と明示の cutoff の列の与え方（人が宣言する一覧か ・P12 の `scheduled_for` なら G2）。
- P12 ledger（G2）・P8 の取得 ／ 観測（G3 ・G4）・P9 の revision の鎖（G5）の gate の順序と可否。
- B-track の統治と資格情報の custody（B0 の設計が先。P8 の運用の契約は scheduled ／ background の取得を禁じたまま）。

## 7. 凍結の保護（本記録で再確認）

- `src/` は P12 A-track v1 の anchor（`e390cdd…`）以後不変。Phase 4 〜 11 の runtime は anchor と object 一致。P8 〜 P11 の registry ・凍結の
  importer の一覧は不変。公開の面 ・config ・workflow ・Secrets ・private root ・runtime pin ・scheduled task に触れていない。
- 歴史の PDF ・証拠 ・journal は削除 ・修復 ・書き換えをしていない。
- 本記録の変更: 本文書 ・`PHASE12_5_DOCS` ／ `PHASE12_DOCS` への登録 ・`P12_5_DESIGN_ANCHOR` の定数 ・guard ・CHANGELOG だけ。

## 8. guard（文書と blob の境界だけ）

- A0 ・A2 の blob（`git ls-tree`）が HEAD と `P12_5_DESIGN_ANCHOR` で一致 ・本記録は anchor に存在しない ・本記録は `PHASE12_5_DOCS` と
  `PHASE12_DOCS` に在る ・`src/` は `P12_A6` 以後不変 ・P8 〜 P11 の registry は不変 ・P13 の package は存在しない ・本記録に必須の主張が在り
  完了の誤った主張 ・署名の実装の主張 ・private の形が無い。
- negative control: 必須の句を 1 つ消した text ・private の形を 1 つ足した text ・完了の誤った主張を足した text を guard の検査に通すと
  **失敗する**こと、A0 の無い commit（`P12_BASE`）を anchor として比較すると blob の一致が **成り立たない**ことを test が示す。

## 9. closeout の基準（満たした）

監督が A0 ・A2 ・A4 を承認した ・A0 と A2 が整合した ・guard と全 suite が緑 ・`src/` の差分が無い ・private の形が文書に無い ・P13 の runtime が
無い。これで **Phase 12.5 の設計は閉じる**。**P13 ・P14 ・B-track は閉じない ・完了ではない ・本記録は実装を承認しない。**
