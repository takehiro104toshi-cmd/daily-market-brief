# PHASE 9 / P9-A3 — PRIVATE AUTHORITY STORES

Watchlist ／ Thesis の追記専用の private な authority の store ・正準の直列化 ・読み込みと追記の全検査 ・時点の状態 ・記録をまたぐ不変条件。
**Phase 9 の凍結ではない。** 人の判断の実行器 ・実 data の検証 ・LLM は無い。基準: P9-A2 `71009fa1f48ea4125bf10c486bbb89135870dd5c`。
P8 は凍結のまま（`0a32d86`）。実の発行体 ・id ・瞬間 ・閾値 ・財務の値は無い。

| file | 役割 |
|---|---|
| `serialization.py` | 正準の直列化 ／ 復元（欄の完全一致 ・既定値なし ・`revision_id` の一致） |
| `store_io.py` | 追記専用 JSONL の仕組み（唯一の書き込みの module）・検査済みの read-only の像の基底 |
| `watch_store.py` | Watchlist の store（`watchlist_authority.jsonl`） |
| `thesis_store.py` | Thesis の store（`thesis_authority.jsonl`） |
| `authority_stores.py` | 両方の store ＋ 唯一の追記の経路（記録をまたぐ不変条件の検査の後だけ書く） |

## 1. 場所

```
<caller が明示に渡す P9 の private root>/watchlist_thesis_intelligence/
    watchlist_authority.jsonl
    thesis_authority.jsonl
```

root は絶対の既存の directory（作らない）。`initialize` は `watchlist_thesis_intelligence/` と無い file だけを空で作る（既存の
file には触れない）。`open` は何も作らない（無ければ `STORE_MISSING`）。利用者の機械の path は無い。P8 の root とは構造的に別
（`require_separate_roots`。A4 の実行器が使う）。

## 2. 正準の encoding

1 行 ＝ `canonical_json(revision.as_dict())`（key の並び ・区切りの正準形 ・UTF-8 ・最後に改行）。`as_dict` は A2 の内容 address の
全欄 ＋ `revision_id`。瞬間は UTC の ISO の正準形（`+00:00`）だけ、日は `YYYY-MM-DD` だけ。復元は欄の集合の完全一致（未知 ・欠けた
欄は拒む）・enum ・id ・aware ・正準形を検査し、A2 の model を作り直して `revision_id` の一致を要求する。既定値の補完は無い。

## 3. 追記（唯一の経路 ＝ `AuthorityStores.append_watch` ／ `append_thesis`）

1. 両方の file が読み込み時と同じ（byte 長 ・sha256）。違えば `CONCURRENT_MODIFICATION`。
2. 同じ `revision_id` が既に在れば: 正準の行が同じなら **`REUSED`**（書かない）・違えば `REVISION_CONFLICT`。
3. 鎖の先頭: 新しい root は seq 1 の CREATE（既存の root への 2 つ目の作成 ・古い先頭に繋ぐ追記は **`CHAIN_HEAD_MISMATCH`**）・
   既存の root は先頭の seq ＋1 で `prev_revision_id` ＝ 先頭の revision。root の無い続きの revision は `ROOT_NOT_FOUND`。
4. 提案の世界（両方の store の全 revision ＋ 候補）で A2 の鎖の検査 ＋ **`check_world`**（全ての審査の瞬間の像）。違えば
   `APPEND_REJECTED`（`WORLD_INVALID:<A2 の code>`）。
5. 対象の store にだけ 1 行を `open("ab")` → write → flush → **fsync**。後に byte 長を確かめ、全体を再読み込みして再検査。他方の
   store は書かない（連鎖の書き込みは無い）。**`APPENDED`**。

個々の store に公開の追記の API は無い（記録をまたぐ不変条件の迂回を防ぐ）。削除 ・上書き ・修復 ・切り詰め ・圧縮 ・移行の API は無い。

## 4. 読み込みの検査（全て fail closed ・修復 ・skip しない）

`STORE_CORRUPTION`: encoding ・最後の改行の欠け（切断 `TRUNCATED_FINAL_LINE`）・空行 ・不正な JSON ・非正準の行 ・物理的な重複 ／ 同じ
`revision_id`（`DUPLICATE_REVISION`）・model の復元の失敗（`INVALID_RECORD:<code>`）・root ごとの鎖（`CHAIN_INVALID:<code>`。seq の
連番 ・先頭は seq 1 の CREATE ・prev ・不変の発行体 ／ 出所 ／ Watchlist の項目 ・reviewed_at の非減少 ・終端の後なし ・無効の条件の参照 ・
人の著者）。Watchlist の store は全ての審査の瞬間で「発行体ごとに REMOVED でない項目は高々 1 つ」も検査する。`AuthorityStores.open`
は両方を読んだ後に `check_world`（違えば `WORLD_INVALID:<code>`）。

## 5. 時点の状態 ・正確な選択（暗黙の最新 ／ 現在 ／ 今日は無い）

`roots()` ・`chain(root_id)` ・`revision(revision_id)` ・`revision_at_seq(root_id, seq)` ・`state_at(root_id, T)` ・`states_at(T)`。T は
明示の aware な瞬間（時計を読まない）。**時点 T の状態 ＝ `reviewed_at <= T` の最大の seq**（file の順は使わない）。

## 6. 同時の書き手

lock は持たない（本人の local な単一の書き手の前提。repository の P8 の store と同じ型）。追記の直前に両方の file の byte 長 ・sha256 を
読み込み時と比べ、違えば `CONCURRENT_MODIFICATION`（再読み込みして人が判断する）。1 行の追記の途中の失敗は最後の改行の欠けになり、
次の読み込みで `TRUNCATED_FINAL_LINE`（修復しない）。

## 7. A1 の発行体の存在（判断）

**A3 の store では検査しない。** 理由: store を P8 の root に結び付けない ・P8 を import しない（store は A2 の model ・標準 library
だけ）・凍結の A1 の identity の coverage は D0 の 1 日だけなので、P9 の後の `reviewed_at` で凍結の resolver を使うと
`OUTSIDE_COVERAGE` になる（I1 は延期のまま）。

**A4 の実行器が人の入力を作る前に行う:** `P8_PROPOSAL` の出所は、A1 の `reconstruct_bound` で再構成した P8 の全結果の EVALUATED の
発行体であることで足りる（P8 の評価の瞬間に凍結 A1 で解けた発行体）。`MANUAL` の出所は、凍結 A1 の identity の record（発行体の
登録の `known_at <= reviewed_at`）の存在を read-only で確かめる（coverage で解く resolver ではない）。その read-only の import の面は
A4 で監督の承認を得て pin する。

## 8. A4 に残すもの

人の判断の file（提案の digest への結び付き）→ A2 の revision の作成 → `AuthorityStores` への追記 ・A1 の発行体の存在（§7）・
`require_separate_roots`（P8 ／ P9 の root）・private な安全な投影 ・見直しの日の報告（`review_due_proposals` ・caller の日）。
