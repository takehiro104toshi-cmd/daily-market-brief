# PHASE 10 / P10-A3 — PRIVATE PROFILE / ATTENTION AUTHORITY STORES

Personal Profile と Attention の **private ・local ・追記専用の authority の store** だけを足す gate。A2 の純な意味をそのまま使い、
store は新しい意味を作らない。**Phase 10 の凍結ではない。** 実行器 ・P9 の参照の実在の検査 ・個人の見直しの列 ・安全 ／ private な
個人の投影 ・CLI ・実データの検証 ・保有 ・通知 ・LLM ・PWA ・自動化は無い。P8 ／ P9 は読まない ・書かない ・import しない。

- 受理した観察: P10-OBS-001 〜 P10-OBS-024。監督者の固定: `review_lookahead_days` の 0..90 は v1 の schema の範囲（config ではない）。
- runtime（新規だけ ・既存の P10 の runtime は不変）: `serialization.py` ・`store_io.py` ・`profile_store.py` ・`attention_store.py` ・
  `authority_stores.py`。`PHASE10_A3_RUNTIME` ・`SANCTIONED_P10_A3_MODULES`（import の module の完全一致）に登録。凍結の P7 ／ P8 ／
  P9 の guard は再開していない。

## 1. 配置 ・初期化 ・開く

`<caller が明示に渡す P10 の root>/personal_intelligence/`:
- `profile_authority.jsonl`
- `attention_authority.jsonl`

| 操作 | 意味 |
|---|---|
| `PersonalAuthorityStores.initialize(p10_root)` | 明示の初期化。root は既存の directory であること（無ければ `STORE_MISSING:P10_ROOT_MISSING` ・作らない）。無い `personal_intelligence/` と無い file だけを作る（file は排他の作成 `xb` ・既存の file は byte も mtime も触れない）→ 開く。繰り返しは既存を変えない。 |
| `PersonalAuthorityStores.open(p10_root)` ・`ProfileStore.open` ・`AttentionStore.open` | 既存を読むだけ。何も作らない。root ・directory ・file が無ければ `STORE_MISSING`、壊れていれば `STORE_CORRUPTION`（修復しない）。 |

root の安全（`ROOT_REJECTED`）: 文字列 ／ Path 以外 ・空 ・NUL ・相対 ・`..` の部品（正規化で救わない）・symlink の root ／ authority の
directory ／ file。root の中の他の子（P8 ／ P9 らしい directory を含む）は探さない ・推測しない ・読まない ・触れない。

## 2. 正準の直列化（`serialization`）

- 1 行 ＝ `canonical_json(revision.as_dict())`（A2 の正準の JSON ＝ key の文字の順 ・区切りの空白なし ・非 ASCII はそのまま）＋ LF。UTF-8。
  列挙は `.value` ・tuple は list ・瞬間は UTC の ISO（`+00:00`）・`revision_id` を含む。
- 欄の集合（完全一致）: `PROFILE_RECORD_FIELDS`（20 欄）・`ATTENTION_RECORD_FIELDS`（14 欄）＝ A2 の dataclass の欄 ＋ `revision_id`。
- 読み: 未知 ／ 欠けた欄は拒む（既定値で補わない）・文字列の欄は文字列 ・列挙は値 ・瞬間は UTC の正準の ISO だけ ・A2 の型を全ての欄で
  明示に構築（A2 の全検査）・再計算した `revision_id` が記録と一致。
- UTF-8 にできない文字（対の無い surrogate）は `UNENCODABLE_TEXT` で拒む（P10-OBS-030）。

## 3. 読み込みの検査と破損（fail closed ・修復なし）

file ごとの順: UTF-8（`INVALID_ENCODING`）・最後の LF（`MISSING_FINAL_NEWLINE`）・空行（`BLANK_LINE`）・JSON（`MALFORMED_JSON`）・正準の
行（`NON_CANONICAL_LINE` ＝ CRLF ・空白 ・key の順 ・重複 key）・記録（`INVALID_RECORD:<A2 の code>` ・`REVISION_ID_MISMATCH` を含む）・物理的な
重複（`DUPLICATE_REVISION`）・鎖と世界（`INVALID_AUTHORITY:<A2 の code>`。prev ・seq ・reviewed_at ・状態機械 ・終端 ・同じ root の 2 つの
作成 ・`MULTIPLE_ACTIVE_PROFILES` ・`DUPLICATE_LIVE_ATTENTION`）。各 store は A2 の `check_personal_world` を自分の file で、coordinator は
両方で走らせる。物理の順は時点の状態を決めない。部分の読み込み ・skip は無い。

## 4. store の API（read-only ・正確な選択 ・時点だけ）

`ProfileStore` ・`AttentionStore`（基底 `store_io.AuthorityFile`）: `roots()` ・`chain(root_id)` ・`revision(revision_id)` ・
`revision_at_seq(root_id, seq)` ・`state_at(root_id, T)` ・`states_at(T)` ・`all_revisions()` ・`line_for` ・`line_of` ・
`verify_unchanged()` ・`revalidate()` ・`same_directory`。T は明示の aware な瞬間（A2）。最新 ／ 現在 ／ now ・追記 ・初期化の API は無い。

## 5. 唯一の追記の経路（`PersonalAuthorityStores`）

公開の追記は `append_profile_revision(PersonalProfileRevision)` ・`append_attention_revision(AttentionRevision)` だけ（汎用の追記は無い）。
物理的な追記は `store_io` の私的な `_append_line`（binary の `ab` ・LF ・flush ・fsync ・前後の長さ ・全体の再読み込み）だけで、import するのは
coordinator だけ（境界の test が pin）。上書き ・切り詰め ・削除 ・修復の API は無い。

追記の前に:
1. 両方の store の byte（長さ ・sha256）が読み込み時と同じことを確かめ、同じ byte を全て検査し直す。
2. 同じ `revision_id` が在れば: 正準の行が同じなら `REUSED`（書かない）・違えば `REVISION_CONFLICT`。
3. 鎖の先頭: 新しい root は seq 1 の CREATE（でなければ `ROOT_NOT_FOUND`）・既存の root は先頭の seq ＋1 かつ `prev_revision_id` が
   先頭（違えば `CHAIN_HEAD_MISMATCH` ・新しい先頭の上に黙って載せない）。
4. 提案の世界（両方の全 revision ＋ 候補）で A2 の `check_personal_world`（違えば `WORLD_INVALID:<code>`）。除外 ＋ FOCUS ／ MUTE は有効。
5. 他方の file の byte を直前に確かめ、対象の file にだけ 1 行（連鎖の書き込みなし）。

人向けの「古い先頭」の意味 ・P9 の参照の実在の検査は A4。

## 6. 並行性

本人の local な単一の書き手の楽観的な並行性（lock なし）。読み込みで両方の file の byte 長 ・sha256 を記録し、追記の前（全体の再検査）と
書く直前に確かめる。どちらの file の変更 ・消失も `CONCURRENT_MODIFICATION`。書いた後の長さが合わなければ
`STORE_CHANGED_DURING_APPEND`。同時の書き手の間の完全な排他は保証しない（検出して fail closed）。

## 7. 私的

store の内容は private ・local だけ。log ・print は無い。例外の文は安全な code ・file の種類（`profile` ／ `attention`）・行の番号だけで、
path ・id ・文 ・著者 ・記録の内容は入れない（test が pin）。安全な投影は作らない。credential らしい文は A2 が拒む。

## 8. 証拠

`tests/intelligence/test_personal_intelligence_stores.py`: 初期化 ・繰り返し ・無い root ・拒む root ・symlink ・開くは作らない ・他の
root ／ らしい子に触れない ・正準の往復と欄の集合 ・破損の全種（file は不変）・Profile の作成 ／ 改訂 ／ 訂正 ／ 退役 ・`REUSED` ・終端 ・
2 つの ACTIVE ・`CHAIN_HEAD_MISMATCH` ・`REVISION_CONFLICT` ・Attention の FOCUS ／ MUTE ／ CLEARED ／ 付け直し ・重複の生きた印 ・時点 ・
除外との組 ・両方の file の並行の変更 ・決定論の byte ・例外の私的。`tests/intelligence/test_personal_intelligence_boundary.py`: 書き込み
の面は store_io だけ ・私的な書き手の importer は coordinator だけ ・store に追記 ／ 初期化なし ・import の面。

## 9. 観察

P10-OBS-025 〜 P10-OBS-032（gate の報告に記録）。
