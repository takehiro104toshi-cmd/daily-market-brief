# PHASE 10 / P10-A4 — HUMAN DECISION EXECUTOR + P9 VALIDATION + PERSONALIZED REVIEW VIEW

人の決定の実行器 ・Attention の P9 の参照の read-only の検査 ・古い先頭 ／ 再試行の意味 ・決定論の個人の見直しの view ・件数だけの安全な
投影 ・private ／ local の狭い CLI を足す gate。**Phase 10 の凍結ではない。** 保有 ・口座 ／ 税 ・通知 ・LLM ・公開の出力 ・PWA ・自動化 ・
推奨 ・点数 ・portfolio の最適化 ・売買の操作は無い。

- 受理した観察: P10-OBS-001 〜 P10-OBS-032。監督者の固定: 実行器は初期化しない（P10-OBS-027）・人の入力の境界で UTF-8 を検査
  （P10-OBS-030 ・A2 は不変）・Attention の見た revision は時点の snapshot の対象の revision と等しいこと。
- runtime（新規だけ ・A1 〜 A3 の runtime は不変）: `decisions.py` ・`executor.py` ・`review_view.py` ・`personal_projection.py` ・
  `admin_init.py` ・`local_cli.py`（`PHASE10_A4_RUNTIME` ・`SANCTIONED_P10_A4_MODULES`）。凍結の P7 ／ P8 ／ P9 の guard は再開していない。

## 1. 人の決定（`decisions`）

7 つの型だけ: `ProfileCreate` ・`ProfileRevise` ・`ProfileCorrection` ・`ProfileRetire` ・`AttentionCreate` ・`AttentionRevise` ・
`AttentionTransition`（Attention の訂正は無い）。authority を担う値だけを持ち、作成は root ／ revision の id を受けない。更新は
`expected_head_revision_id` を持つ。`author_ref`（`human:`）・`reviewed_at`（aware）は明示。`decision_from_mapping` は local の JSON の
object を欄の完全一致で型にする（`NORMAL` ・未知の操作 ・未知 ／ 欠けた欄は拒む）。

## 2. 実行器（`apply_decision` ・`dry_run_decision`）

1. 入力: 型 ・列挙 ・aware な瞬間 ・**全ての人の文（id ・著者 ・除外の各項目を含む）が UTF-8 にできること**（`INPUT_REJECTED:UNENCODABLE_TEXT`。
   revision を作る前 ・文は返さない ・生の `UnicodeEncodeError` は出ない）。
2. P10 の store を開く（`PersonalAuthorityStores.open` だけ。初期化 ・作成 ・部分の配置の補修はしない → `STORE_UNAVAILABLE`）。
3. 候補を導く: 作成は A2 の root の id ・seq 1。更新は人が見た先頭（`expected_head_revision_id`）から seq ＋1 ・prev。
4. 候補が同じ行で既に在れば `REUSED`（dry-run は `WOULD_REUSE`）。正確な再試行は古い先頭でも `REUSED`。
5. 人が見た先頭が今の先頭でなければ `STALE_AUTHORITY_HEAD`（新しい先頭の上に黙って載せない）。root が無い ／ 見た revision が鎖に
   無ければ `INPUT_REJECTED:AUTHORITY_ROOT_NOT_FOUND` ／ `EXPECTED_HEAD_NOT_IN_CHAIN`。
6. Attention だけ: §3 の P9 の検査。
7. A2 の型の構築（`INPUT_REJECTED:<A2 の code>`）・A3 と同じ鎖 ／ 世界の検査（`AUTHORITY_WORLD_INVALID:<A2 の code>` ＝ 2 つの ACTIVE な
   profile ・同じ対象の 2 つの生きた印 ・終端 ・不正な遷移 ・訂正の対象なし ・reviewed_at の逆行）。
8. apply: 唯一の追記の経路で 1 行（A3 の `CHAIN_HEAD_MISMATCH` → `STALE_AUTHORITY_HEAD` ・`CONCURRENT_MODIFICATION` はそのまま）。
   dry-run は同じ全ての検査をして何も書かない ・作らない（`VALID` ／ `WOULD_REUSE` ／ `WOULD_BE_REJECTED` と拒否の code だけ）。

Profile: 作成（ACTIVE）・改訂 ／ 訂正（全ての内容を明示 ・ACTIVE のまま）・退役（`retirement_reason` ・内容は変えない ・TRANSITION）。
置き換えの profile は自動で作らない。Attention: 作成（FOCUS ／ MUTE）・改訂（同じ状態で見た revision を新しくする）・遷移
（FOCUS ⇄ MUTE ・→ CLEARED。CLEARED は終端 ・付け直しは新しい作成 ＝ 新しい root）。

## 3. P9 の参照の検査（A1 の `read_p9_private_snapshot` だけ）

Attention の CREATE ／ REVISE ／ TRANSITION（CLEARED を含む）ごとに `read_p9_private_snapshot(p9_root, at=reviewed_at)`:
- 対象の root がその時点に見える（無い ／ まだ無い → `P9_TARGET_ABSENT`）。
- 種類が一致（Watchlist の項目 ／ Thesis が逆 → `P9_TARGET_KIND_MISMATCH`）。
- `observed_p9_revision_id` ＝ その時点のその対象の revision（古い非先頭 ・他の対象の revision → `P9_REVISION_STALE_OR_MISMATCH`）。

これで対象の存在 ・種類 ・revision の所属 ・時点の可視を一度に示す。P9 の root が読めない ／ 世界が違えば `P9_UNAVAILABLE`。P9 は
書かない（test が byte と mtime の不変を確かめる）。P9 の store ・`AuthorityStores` ・実行器 ・P8 ・J-Quants は import しない。
Profile の `excluded_issuer_ids` は P9 の存在を要しない（構文だけ ・A2）。

## 4. 個人の見直しの view（`read_personal_review(p10_root, p9_root, *, at, as_of_date)`）

private ・local ・派生 ・非 authority ・書かない ・時計なし。P10 は store を開くだけ（＋ A2 の世界の検査）、P9 は A1 の snapshot だけ。
各 P9 の record（全て ・終端の record も含む）の `ReviewEntry`: 種類 ・P9 の root ／ revision の id ・発行体（Thesis は同じ snapshot の
link した Watchlist の項目の発行体）・link ・P9 の状態 ・出所の種類 ・`review_due_on` ・期日の区分 ・印 ・除外 ・表示の組。

- 期日の区分（`as_of_date` と ACTIVE な profile の `review_lookahead_days`）: `OVERDUE`（前）・`DUE`（当日）・`UPCOMING`（窓の内）・
  `LATER` ・`NO_DUE_DATE`。ACTIVE な profile が無ければ窓 0 日 ・除外なし。
- 印: `FOCUS` ／ `MUTE`（生きた印）・`NORMAL`（印なし ・CLEARED）。
- 組: `EXCLUDED_BY_PROFILE`（ACTIVE な profile が発行体を除外）＞ `MUTED` ＞ `REVIEW`。除外も MUTE も消さない（全ての record を含む）。
  除外 ＋ FOCUS は矛盾ではなく、FOCUS の印を残したまま除外の組に置く。

### 4.1 順（見直しの作業の順だけ ・投資の順位ではない）

1. `review_due_on` の昇順（日の無い record は日のある record の後）。
2. 同じ日の中だけ: FOCUS → NORMAL → MUTE（FOCUS は早い期日を越えない）。
3. P9 の root の id。

点数 ・順位 ・優先度 ・推奨 ・売買の緊急度 ・期待の利回り ・目標の価格 ・配分 ・大きさの欄は無い。

## 5. 安全な投影（`personal_safe_projection`）

件数だけ: ACTIVE な profile ・生きた FOCUS ／ MUTE の印 ・CLEARED の印 ・record ・`OVERDUE` ／ `DUE` ／ `UPCOMING` ／ `LATER` ／
`NO_DUE_DATE` ・FOCUS ／ MUTE の record ・除外の record。文 ・除外 ・理由 ・発行体 ・P9 ／ P10 の id ・著者 ・瞬間 ・日は無い。保存しない。

## 6. 管理の初期化（`init_personal_root`）と CLI

`init_personal_root`（実行器とは別の明示の管理の操作 ・A3 の primitive より厳しい）: 両方の file が無い → `INITIALIZED` ／ 両方が在り正しい
→ `ALREADY_INITIALIZED`（変えない）／ 片方だけ → `PARTIAL_LAYOUT`（作らない）／ 拒む root ・無い root ・破損 → `INIT_REFUSED:<code>`。

`python -m src.intelligence.personal_intelligence.local_cli`（private ・local だけ ・対話の UI なし）: `init` ・`apply` ・`dry-run` ・
`review` ・`summary`。root ・瞬間 ・日は全て明示（既定 ・推測 ・環境変数 ・時計なし）。決定は local の絶対 path の通常の file（`..` ・
symlink ・64 KiB 超は拒む）の UTF-8 の JSON。標準出力は 1 行の JSON で、既定は受領 ／ 件数だけ（id ・発行体 ・文 ・著者なし）。
`--private` を明示した時だけ受領の id ／ 見直しの private な行を出す。拒否は `REFUSED` と終了 code 2。

## 7. 私的 ・境界

profile の文 ・除外は C2 の個人の財務の文脈: log ・普通の例外 ・安全な投影 ・既定の CLI の出力に出さない。P9 の private な値は C1。
外部の処理 ・LLM ・network ・credential は無い（`JQUANTS_API_KEY` なしで動く）。新しい authority の revision を作るのは実行器だけ、
追記の経路を呼ぶのも実行器だけ、初期化を呼ぶのは管理の初期化だけ、`p9_view` を使うのは実行器と見直しの view だけ（境界の test）。

## 8. A5（実データの検証）の前提

- 監督者が許した実の P9 の private root（A5 の P9 の検証の root ・読むだけ）と、それとは別の明示の P10 の private root。
- `init` → `apply`（profile ・Attention。見た revision は `review --private` で時点の P9 の先頭を確かめる）→ `review` ／ `summary` の時点の
  検査 ・P9 の root の byte の不変 ・`JQUANTS_API_KEY` なし ・network なし。実の id ・発行体 ・値は repo ・文書 ・CHANGELOG に入れない。

## 9. 観察

P10-OBS-033 〜 P10-OBS-043（gate の報告に記録）。
