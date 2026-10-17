# PHASE 10 — PERSONAL INTELLIGENCE v1: COMPLETE / CLOSED / FROZEN

Phase 10 の最終凍結の記録（P10-FREEZE-RECORD）。本文書 ・registry ・guard ・CHANGELOG だけの記録であり、runtime の意味は変えない。
この記録の commit は **新しい anchor ではない**。

| 項目 | 値 |
|---|---|
| 状態 | **COMPLETE / CLOSED / FROZEN** |
| 意味 ／ runtime の凍結 anchor | `1a7b9a26c8ee6a2b86a30e88c224a737565ce979`（registry の `P10_A4`。P10-A4 の commit） |
| A5 の検証を走らせた tree | `e46bbae85167ab3dbcb70285f214a066ec01781e`（registry の `P10_VALIDATED_TREE`） |
| 凍結の範囲 | P10-A0 〜 P10-A5 の実装 ／ runtime（登録済みの runtime 17 file ・Phase 10 の test ・Phase 10 の設計文書） |
| 実 data の検証 | P10-A5 real private validation（Windows）: **A5_PASS** |
| 最終監査 | P10-A6 final audit: **P10_FINAL_AUDIT_PASS** |
| 受理した観察 | P10-OBS-001 〜 P10-OBS-054 |
| Phase 9 | COMPLETE / CLOSED / FROZEN のまま（`4c1970174f678245b569fdbb812a8a6ced52410b`。runtime 18 file は object 一致） |
| Phase 8 | COMPLETE / CLOSED / FROZEN のまま（`0a32d86`。runtime 54 file は object 一致） |

guard: `tests/intelligence/test_personal_intelligence_boundary.py` の
`test_p10_freeze_the_17_registered_runtime_files_are_object_identical_to_the_anchor_and_the_validated_tree` と
`test_p10_freeze_the_record_holds_no_private_validation_values`（§8）。

---

## 1. 2 つの commit の関係（anchor と validated tree）

- `P10_A4`（P10-A4 の commit）で Phase 10 の runtime の実装は完了した。これが意味 ／ runtime の凍結 anchor。
- `P10_VALIDATED_TREE` は Windows の P10-A5 の preflight の test だけの修正（Phase 10 の境界の test の git の出力の復号を locale に
  依らない UTF-8 にし、byte の一致の guard を git の object の id の比較にした）と CHANGELOG の 2 file だけが anchor と違う。
- Phase 10 の runtime 17 file は、`P10_A4` と `P10_VALIDATED_TREE` で git の blob の id が全て同じ（guard が pin する）。
- したがって `P10_VALIDATED_TREE` で走らせた A5 の実 data の検証は、`P10_A4` の runtime をそのまま検証している。
  `P10_VALIDATED_TREE` は新しい意味 ／ runtime の anchor ではない。

## 2. 凍結した範囲（v1）

- 凍結の Phase 9 を read-only で読む専用の adapter（Phase 10 の唯一の Phase 9 の importer。store の object は出さない）
- Personal Profile の authority（人が持つ質的な文脈 ・ACTIVE ／ RETIRED ・見直しの窓の日数 ・発行体の除外）
- Attention の authority（FOCUS ／ MUTE ／ CLEARED ＝ 表示の意図だけ。対象は Phase 9 の root 1 つ）
- 不変の revision の履歴（内容 address の id ・seq ・直前の revision ・人の著者 ・明示の瞬間）
- 時点の再構成（`reviewed_at <= T` の最大の seq。最新 ／ 現在 ／ 時計なし）
- private な追記専用の store（正準の直列化 ・破損は fail closed ・楽観的な並行性）
- 人の決定の実行器（7 つの型つきの決定。authority を作るのは実行器だけ）
- Phase 9 の対象 ／ revision の検査（その時点に見える対象のその revision と一致）
- 古い先頭の fail closed（`STALE_AUTHORITY_HEAD`。新しい先頭に黙って載せない）
- 正確な再試行 ／ 冪等（`REUSED`）
- dry-run（全ての検査 ・何も書かない）
- 決定論の個人の見直しの view（期日が主 ・同じ日の中だけ FOCUS → NORMAL → MUTE ・除外 ／ MUTE を消さない）
- 件数だけの安全な投影
- private ／ local の CLI（明示の root ・瞬間 ・日。既定の出力は受領 ／ 件数だけ）

## 3. 明示に除外（v1 に無い）

保有 ・証券会社 ／ 口座の data ・税の文脈 ・配分 ・建玉の大きさ ・rebalance ・順位 ・投資の点数 ・危険 ／ 適合性の点数 ・推奨 ・目標の価格 ・
期待の利回り ・売買の指示 ・売買の実行 ・LLM の authority ・LLM の提案 ・P5 の feedback ・J-Quants の直接の取り込み ・公開の出力 ・
PWA の UI ・自動化。

## 4. P10-A5 実 data の検証の証拠（集計だけ）

| 項目 | 結果 |
|---|---|
| Windows の preflight ／ 焦点の Windows の test | PASS |
| credential | 無し（環境変数は未設定） |
| network ／ J-Quants の request | 0 |
| Phase 9 の private root | 全段で read-only（manifest の byte ・sha256 ・mtime が不変） |
| Profile | dry-run VALID ・APPENDED ・正確な再試行 REUSED ・ACTIVE の数 ＝ 1 |
| Attention | dry-run VALID ・FOCUS APPENDED ・再試行 REUSED ・FOCUS → MUTE APPENDED ・MUTE → CLEARED APPENDED ・CLEARED の終端の拒否 PASS ・付け直しは新しい root PASS |
| 拒否 | 古い先頭 PASS ・Phase 9 の revision の不一致 PASS ・対象の不在 ／ 種類の不一致 PASS ・UTF-8 にできない文 PASS ・2 つ目の ACTIVE な Profile PASS ・部分の配置 PASS ・拒否は何も書かない PASS |
| 見直しの view | 決定論 PASS ・ACTIVE な profile が見える ・印の時点が反映 ・ACTIVE な profile 無し → 窓 0 日 PASS |
| 安全な投影 | 件数だけ ・内部で一貫 ・既定の出力に private な値なし PASS |
| 再び開く ／ 時点 ／ 再び開いた後の再試行 | PASS |
| authority の file | profile 1 行 ・attention 4 行 ・LF だけ PASS |
| 最終 | **A5_PASS** |

id ・発行体 ・code ・著者 ・瞬間 ・profile の文 ・private な file の内容 ／ hash は記録しない（§8 の guard が pin）。

## 5. 観察の分類

受理: P10-OBS-001 〜 P10-OBS-054。うち、閉じた後も残る非 blocking の項目:

- **P10-OBS-023**: `__init__.py` の docstring は A1 の時のまま（profile ・FOCUS ／ MUTE が「無い」と書いてある）。直すと凍結の
  runtime の blob が変わるので直さない。本文書がその訂正。
- **P10-OBS-027**: 低い層の初期化は無い authority の file を 1 つだけ作れる。普通の runtime は管理の初期化の `PARTIAL_LAYOUT` の
  拒否で守られ、実行器は初期化しない。
- **P10-OBS-028**: 並行性は楽観的 ・lock なし（本人の local な単一の書き手の v1）。
- **P10-OBS-030**: A2 の純な model は対の無い surrogate を後の境界の前では受ける。実行器と直列化が安全に拒む。下流に guard のない
  直接の構築の経路を足さない。
- **P10-OBS-036**: 終端の Phase 9 の record は見直しの view の NO_DUE_DATE の尾に残る。
- **P10-OBS-044**: P8 ／ J-Quants の module は凍結 Phase 9 の import を通して推移的に load される（request は無い。A5 が network 0 ・
  request 0 を証明）。
- **P10-OBS-046 ／ 050**: Windows の焦点の検証は clean。古い凍結の P7 ／ P8 ／ P9 の test の補助は `PYTHONUTF8=1` なしでは locale に
  敏感。test の移植の負債であり runtime の意味ではない。
- **P10-OBS-048**: validation だけの authority が private な P10 の A5 の root に残る。実の個人の authority として再利用しない。
- **P10-OBS-051**: 実際に使った helper の版は private な証拠のまま。helper は repo に入れない。
- **P10-OBS-052**: repo に A5 の runbook は無い。集計の証拠は本文書に記録する。
- **P10-OBS-053**: 実の Attention の検証は Watchlist の対象 1 つ。Thesis の対象の Attention は合成の test で覆う。
- **P10-OBS-054**: 実の検証の profile に除外は無かった。除外の組は合成の test で覆う。

## 6. 延期（非 blocking）

- Phase 10.1: 保有 ・口座 ／ 証券会社の文脈 ・税の文脈 ・観測した保有と承認した保有の意味 ・時価 ／ 損益 ／ 配分の問い。
- その他: 通知の好み ／ 配送 ・終端の record の filter ・A2 の surrogate の直接の硬化 ・lock の並行性 ・LLM の提案の利用 ・公開の表示。

## 7. 以後の境界

| Phase | 内容 |
|---|---|
| Phase 10.1 | Holdings Intelligence（延期 ・任意の将来の phase） |
| Phase 11 | PWA ／ 利用者との対話の面 |
| Phase 12 | 自動化 |
| Phase 12.5 | Market Memory ／ Obsidian の設計 |
| Phase 13 | Market Brain ／ Market Memory |
| Phase 14 | 継続学習の統合 |

Phase 11 は Phase 10.1 の前に始めてよい。どの phase も自分の gate なしに Phase 10 の private な authority を消費しない。

## 8. guard

- `P10_A4` ・`P10_VALIDATED_TREE` が正確 ・両方が HEAD の祖先 ・`P10_A4` が `P10_VALIDATED_TREE` の祖先。
- 登録済みの runtime はちょうど 17 file ・全て anchor に在る ・anchor の package の file の集合 ＝ 登録。
- 17 file の git の blob の id が anchor ・validated tree ・index ・worktree（git の object の意味で hash）で全て同じ（locale ・
  checkout の改行に依らない）。
- anchor 以後に Phase 10 の src の runtime は変わっていない ・validated tree は test と CHANGELOG だけが違う。
- 本文書は anchor ・validated tree の後に足された。
- 本文書に private な値の形（id の接頭辞 ・発行体 ・5 桁の code ・著者 ・瞬間 ・Windows の path ・validation の profile の文）は無い。
