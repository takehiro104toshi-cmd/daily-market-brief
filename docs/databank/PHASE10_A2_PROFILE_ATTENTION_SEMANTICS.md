# PHASE 10 / P10-A2 — PERSONAL PROFILE + ATTENTION SEMANTICS

人が持つ質的な Personal Profile と Attention（FOCUS ／ MUTE ＝ 表示の意図だけ）の **純な意味の model** だけを足す gate。
**Phase 10 の凍結ではない。** file の入出力 ・store ・追記 ・実行器 ・CLI ・個人の見直しの列 ・保有 ・通知 ・LLM ・PWA ・自動化 ・
P8 ／ P9 への書き込みは無い。Phase 9 は import しない（A1 の `p9_view` が唯一の Phase 9 の importer のまま）。

- 受理した観察: P10-OBS-001 〜 P10-OBS-016。
- runtime（`src/intelligence/personal_intelligence/`）: `revision_model.py` ・`profile_model.py` ・`attention_model.py` ・
  `cross_rules.py`。`tests/intelligence/phase10_runtime_registry.py` の `PHASE10_A2_RUNTIME` に完全に登録。凍結の P7 ／ P8 ／ P9 の
  guard は registry の名前で Phase 10 を参照するので、A2 では凍結の test を再開していない（`PHASE10_TEST_REGISTRATION` は不変）。
- import の面（完全一致 ・`SANCTIONED_P10_A2_MODULES`）: package の中と `..core.ids.content_id` ・`..core.time.to_utc_iso` だけ。

## 1. 共通の revision（`revision_model`）

- root の安定 id ・内容 address の revision id（`content_id` ＝ sha256 の先頭 24 hex。正準の JSON ＝ key の文字の順 ・区切りの空白なし）。
- `seq` は 1 から ＋1 ずつ ・`prev_revision_id` は直前の revision ・`reviewed_at` は caller が渡す aware な瞬間（UTC で正準化 ・非減少）・
  `author_ref` は `human:` 接頭辞（凍結 P9 と同じ規則 ・test が一致を pin）。上書き ・時計 ・乱数は無い。
- 種類: `CREATE` ・`REVISE` ・`CORRECTION` ・`TRANSITION`。種類は内容の差を意味しない（同じ内容の REVISE も有効）。差が要る消費者は
  欄を明示に比べる（Profile は `content()`）。
- 種類の監査: Profile は 4 種すべて。Attention は `CREATE` ・`REVISE` ・`TRANSITION` だけ（§3）。
- 時点: `state_at(chain, T)` ＝ 検査済みの鎖の `reviewed_at <= T` の最大の `seq`（入力 ／ 物理の順に依らない）。`states_at` ・
  `revision_at_seq` ・`ordered_chain`。最新 ・現在 ・now は無い。
- Phase 9 の参照の構文は構造だけの複製（`p8iss_` ・`p9wat_` ・`p9wrv_` ・`p9ths_` ・`p9trv_`）。凍結 P9 の定数との一致は test が pin。

## 2. Personal Profile（`profile_model.PersonalProfileRevision`）

- root `p10prf_` ＝ 作成の著者 ・reviewed_at から導く。revision `p10prv_`。
- 状態: `ACTIVE` ・`RETIRED`（終端）。CREATE → ACTIVE ／ ACTIVE → ACTIVE（REVISE ・CORRECTION）／ ACTIVE → RETIRED（TRANSITION ・
  `retirement_reason` 必須 ・内容は変えない）。RETIRED → ACTIVE は無い。退役の後の新しい profile は新しい root。
- CORRECTION は内容のどの欄も正してよい（`corrects_revision_id` は同じ鎖の既存の revision ・`correction_reason` 必須）。過去の
  revision は残り、訂正の reviewed_at より前の時点の状態は記録のまま。REVISE との違いは意図（考えの変化か、記録の誤りか）だけ。
- 内容の欄（`PROFILE_CONTENT_FIELDS` ・完全）:

| 欄 | 型 | 規則 |
|---|---|---|
| `horizon_note` | 文 | 質的 ・任意（空可） |
| `liquidity_note` | 文 | 質的 ・任意 |
| `risk_context_note` | 文 | 質的 ・任意（危険の点数 ・区分ではない） |
| `review_lookahead_days` | 整数 | `REVIEW_LOOKAHEAD_MIN_DAYS`（0）〜 `REVIEW_LOOKAHEAD_MAX_DAYS`（90）。表示 ／ 見直しの窓だけ。bool ・小数 ・文字は拒む |
| `excluded_issuer_ids` | 発行体の id の tuple | 構文だけ（P9 に在るとは主張しない）・文字の順 ・重複は拒否（`canonical_excluded_issuer_ids` が明示に正準化）・最大 200 |
| `exclusion_reason_note` | 文 | 除外があれば必須 ・無ければ空 |

### 2.1 文の数字の扱い（決定）

文の数字 ・語は検閲しない。「long term, roughly 10 years」「I want to review this every 30 days」「I do not want concentrated
positions」は有効。境界は構造で守る:
- 型の欄は上の表だけ（`kw_only` の凍結の dataclass。未知の欄 ＝ `risk_score` ・`allocation` 等は `TypeError`）。
- 数の authority は `seq` と `review_lookahead_days` だけ。
- 文は Phase 10 の code が解釈 ・比較 ・並べ替え ・計算に使わない（不透明の文）。検査は文字列 ・長さ（2000）・制御文字 ・credential
  らしい文だけ。

### 2.2 型の schema で持てない概念

`risk_score` ・`suitability_score` ・`risk_category` ・`expected_return` ・`target_return` ・`target_price` ・`allocation` ・`weight` ・
`position_size` ・`buy` ・`sell` ・`rebalance` ・`recommendation` ・`rating` ・`conviction` ・`holdings` ・portfolio の最適化。欄の名前に
これらの語は無く（test が pin）、`authority_class` は固定。

## 3. Attention（`attention_model.AttentionRevision`）

- 意味: 「この調べの記録をもっと出す（FOCUS）／ あまり出さない（MUTE）」だけ。投資の意味 ・順位 ・優先度 ・緊急度 ・重み ・確信 ・
  推奨は無い。FOCUS と MUTE は表示の意図の列挙で、数 ・順序の値を持たない。自由文の欄も無い（数の欄は `seq` だけ）。
- 対象（決定）: P9 の root の id ちょうど 1 つ。`target_kind` ＝ `P9_WATCH_ENTRY`（`p9wat_`）か `P9_THESIS`（`p9ths_`）。発行体だけの
  印は無い。印は後の P9 の revision を越えて生きる（P9 の revision が増えても黙って無効にならない）。
- `observed_p9_revision_id`: 人が印を作る ／ 改める時に見た P9 の revision（`p9wrv_` ／ `p9trv_` ・種類と一致）。出所 ・文脈だけ。
- root `p10att_` ＝ 対象の種類 ・対象の root ・作成の著者 ・reviewed_at（状態に依らない）。revision `p10arv_`。
- 状態: `FOCUS` ・`MUTE` ・`CLEARED`（終端 ＝ この記録をもう個人化しない）。印が無いこと ＝ 既定（NORMAL は保存しない）。
  CREATE → FOCUS ／ MUTE ・FOCUS ⇄ MUTE ・FOCUS ／ MUTE → CLEARED（TRANSITION）・同じ状態で見た revision を改める（REVISE）。
  CLEARED の後の付け直しは新しい root。対象は鎖の中で変わらない。
- CORRECTION は受けない（`CHANGE_KIND_NOT_SUPPORTED`）: 直す内容が状態と見た revision だけで、TRANSITION ・REVISE と同じ変化に
  2 つの書き方を作らない。対象の誤りは CLEARED ＋ 正しい対象の新しい root。

## 4. 記録をまたぐ規則（`cross_rules.check_personal_world`）

全 revision の審査の瞬間ごとに、時点の像で:
1. ACTIVE な Personal Profile は高々 1 つ（`MULTIPLE_ACTIVE_PROFILES`）。
2. 生きている Attention（FOCUS ・MUTE）は P9 の対象の root ごとに高々 1 つ（`DUPLICATE_LIVE_ATTENTION`）。同じ瞬間の CLEARED と
   付け直しは有効。

意図して検査しないこと:
- 除外 ＋ FOCUS ・除外 ＋ MUTE は有効。除外は個人の制約 ／ 文脈、FOCUS ／ MUTE は表示の意図で、矛盾する authority ではない。A4 の
  個人の見直しの view は「profile で除外」の組に置き、FOCUS ／ MUTE の印を metadata として残してよい（表示の方針は A4）。印を消す ・
  拒む ・変えることはしない。Attention は発行体を持たないので、A2 では組み合わせ自体を作れない。
- 好みの推測（除外から印 ・印から profile）はしない。記録を書き換える ・状態を自動で変える関数は無い。
- 参照の実在。A2 は構文だけ。

## 5. A4 に残す検査（A2 では行わない）

A1 の `read_p9_private_snapshot` を使い、実行器が書く前に:
- `target_root_id` が時点 T の P9 に在り、種類が一致する。
- `observed_p9_revision_id` がその root の鎖の revision で、T に見える（`reviewed_at <= T`）。
- 除外の発行体と P9 の発行体の照合は表示の組だけ（authority の拒否ではない）。
- store の追記の時の `check_personal_world`（A3 ／ A4。store は A2 に無い）。

## 6. 証拠

`tests/intelligence/test_personal_intelligence_semantics.py`: P9 の構文 ・著者の規則の凍結 P9 との一致 ・時点（前 ・ちょうど ・同じ瞬間 ・
後）・Profile の作成 ／ 改訂 ／ 訂正 ／ 退役 ・終端 ・種類の規則 ・連続 ・非減少 ・人の著者 ・窓の範囲 ・除外の正準化 ／ 重複 ・文の数字 ・
型の schema の除外 ・決定論の id ・Attention の FOCUS ⇄ MUTE ／ CLEARED ・対象の構文 ・同じ対象の重複 ・付け直し ・除外との組 ・推測なし ・
file の入出力なし。`tests/intelligence/test_personal_intelligence_boundary.py`: registry ・import の面 ・語彙 ・入出力 ／ store ／ 時計 ／
Phase 9 の面なし。

## 7. 観察

P10-OBS-017 〜 P10-OBS-024（gate の報告に記録）。
