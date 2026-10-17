# PHASE 9 / P9-A4 — HUMAN DECISION EXECUTOR / PRIVATE PROJECTION

人の判断 ／ 著述の入力 → 決定論の検査 → A2 の revision の作成 → A3 `AuthorityStores` への追記、と private な安全な投影 ・見直しの日の
報告 ・local の入口。**Phase 9 の凍結ではない。** 実 data の検証 ・LLM ・公開の出力 ・scheduler は無い。基準: P9-A3
`b5e03dec4aa51ac94324b6b300ab4d24f09d89ee`。P8 は凍結のまま（`0a32d86`）。実の発行体 ・id ・run ・閾値 ・財務の値は無い。

| file | 役割 |
|---|---|
| `decision_model.py` | 人の入力の model ・判断の file の正準の復元（欄の完全一致 ・既定値なし） |
| `p8_identity.py` | `MANUAL` の発行体の凍結 A1 の record の read-only の確認（新しい P8 の import の面） |
| `executor.py` | 人の入力 → 検査 → revision の作成 → `AuthorityStores` への追記（`dry-run` は書かない） |
| `projection.py` | 安全な投影（件数だけ）・見直しの日の報告（private ・P9 の id と日だけ） |
| `local_cli.py` | 本人の local な入口（`apply` ・`summary` ・`review-due`） |

## 1. 人の authority の流れ

人の入力（`author_ref` は `human:` ・`reviewed_at` ・`review_due_on` ・理由 ／ 内容 ・出所の結び付き ・訂正の参照 ・更新の
`expected_head_revision_id` を全て明示）→ 決定論の検査 → A2 の revision の作成（seq ・prev ・root ・revision の id は実行器が導く ・
caller は選べない）→ A3 `AuthorityStores.append_watch` ／ `append_thesis`（最終の検査 ＝ 鎖の先頭 ・`check_world`）。自動の作成 ・
遷移 ・提案の受理 ・機械 ／ LLM の著者は無い。runtime で authority の revision を作るのは実行器だけ（直列化は保存した行の復元だけ）。

入力の種類: `WATCH_CREATE_FROM_PROPOSAL` ・`WATCH_CREATE_MANUAL` ・`WATCH_REVISE` ・`WATCH_TRANSITION` ・`WATCH_CORRECTION` ・
`THESIS_CREATE` ・`THESIS_REVISE` ・`THESIS_TRANSITION`（内容は先頭のまま ・状態だけ ・無効の条件は key で指す）・`THESIS_CORRECTION`。

## 2. P8 の提案への結び付き（`WATCH_CREATE_FROM_PROPOSAL`）

1. 明示の P8 root（P9 の root と構造的に別。`ROOTS_NOT_SEPARATE`）・run ・期待の `screen_result_id`。無ければ `P8_ROOT_REQUIRED`。
2. A1 `reconstruct_bound`（network ・transport ・credential ・P8 への書き込みなし）。違えば `P8_RESULT_DRIFT` ・`P8_LEDGER_INVALID` 等。
3. 発行体が再構成の結果の member にある（無ければ `PROPOSAL_ISSUER_ABSENT`）・member が EVALUATED（違えば
   `PROPOSAL_MEMBER_NOT_EVALUATED`。凍結 B5B は EVALUATED の member にだけ発行体を付けるので、取得の失敗等は
   `PROPOSAL_ISSUER_ABSENT` になる）。
4. 同じ引き渡しから A2 の提案を決定論で再生成し、入力の `proposal_digest` と完全一致（違えば `PROPOSAL_DIGEST_MISMATCH`）。
5. 出所 ＝ その提案の `P8_PROPOSAL`（`require_proposal_binding`）。MATCH は特別ではない（NO_MATCH ・NOT_EVALUABLE ・HOLD ・
   AUTHORITY_FAILURE も EVALUATED なら同じ）。指標の値は取り込まない。

Thesis の新しい `P8_SCREEN_RESULT` の根拠も同じ再構成で確かめる（発行体が EVALUATED ・Screener の状態が一致。違えば
`P8_EVIDENCE_MISMATCH`）。既に先頭にある根拠は再検査しない。

## 3. `MANUAL` の出所の意味（正直な主張）

`p8_identity.confirm_reviewed_issuer_record`: 明示の P8 root の凍結 A1 の identity の authority を read-only で開き（`initialize` ／
`append` なし ・無ければ `IDENTITY_AUTHORITY_UNAVAILABLE` ・作らない）、`issuer_id` が **人が審査した発行体の登録の record**
（`IssuerRegistration` ・出所 `HUMAN_REVIEWED`）に対応し、その record が `known_at <= reviewed_at` であることだけを確かめる
（`ISSUER_AUTHORITY_UNKNOWN` ・`ISSUER_NOT_HUMAN_REVIEWED` ・`ISSUER_NOT_KNOWN_BY_REVIEWED_AT`）。意味の定数:
`HUMAN_REVIEWED_A1_ISSUER_REGISTRATION_RECORD_KNOWN_BY_REVIEWED_AT_NOT_A_LISTING_OR_COVERAGE_CLAIM`。凍結 A1 の coverage は
authority の日だけで、I1 は延期のままなので、`reviewed_at` の時点の上場 ・coverage ・identity の解決は主張しない。A1R の訂正の履歴も
評価しない（record の存在だけ）。

新しい P8 の import の面（`identity_model.SourceClass` ・`identity_store.IdentityStore` ／ `IdentityStoreError`）は、凍結 P8 の
`test_bo` の P9 の importer の一覧（完全な path → import の面）に test だけの狭い再開で足し、`PHASE9_TEST_REGISTRATION` で行を pin した。

## 4. 先頭の古さ ・revision の作成 ・冪等

更新は人が審査した `expected_head_revision_id` の revision から作る（seq ＝ 期待の先頭の seq ＋1 ・prev ＝ 期待の先頭 ・不変の
発行体 ／ 出所 ／ Watchlist の項目は先頭から）。期待の先頭が鎖に無ければ `EXPECTED_HEAD_UNKNOWN`。

- 作った revision が既に store にあれば（同じ入力の再試行）→ A3 が **`REUSED`**（書かない）。
- 無く、現在の鎖の先頭が期待の先頭と違えば **`STALE_AUTHORITY_HEAD`**（新しい先頭に読み替えない）。
- 遷移の妥当性（`ILLEGAL_TRANSITION`）・A2 の後続の規則（`INVALID_DECISION:<code>`）を追記の前に検査する。
- Thesis の作成: Watchlist の項目が在り（`WATCH_ENTRY_NOT_FOUND`）、`reviewed_at` の時点で REMOVED でなく
  （`WATCH_ENTRY_NOT_LIVE_AT_REVIEW`）、発行体が同じ（`ISSUER_MISMATCH`）。Watchlist を自動で変えない。

## 5. 追記の流れ

実行器の検査 → `AuthorityStores.append_*`（両方の file の不変 ・同じ revision は `REUSED` ・鎖の先頭 ・`check_world` ・対象の store に
だけ fsync で 1 行）。`dry-run` は書かずに同じ世界の検査をして `VALID` ／ `WOULD_REUSE` ／ `WOULD_BE_REJECTED:<code>`。

## 6. 安全な投影 ・見直しの日

- 安全な投影（`safe_projection(stores, at=, as_of_date=)`）: 明示の瞬間 `at` の各 root の状態の件数だけ（Watchlist: 数 ・状態 ・
  出所の種類 ・見直しの日が来た数 ・宣言した Thesis の link の数。Thesis: 数 ・状態 ・見直しの日が来た数 ・無効の根拠 ・支持 ／ 反証の
  根拠の種類）。発行体 ・名前 ・code ・理由 ・主張 ・根拠の文 ・run ・`screen_result_id` ・提案の digest ・著者 ・正確な `reviewed_at` ・
  財務の値 ・閾値 ・P9 の id は欄が無い。
- 見直しの日の報告（`review_due_report`）: 明示の `as_of_date` 以前が見直しの日の root（L0 ・P9 の id と日だけ ・既定の投影とは別の
  private な view）。時計を読まない ・追記しない ・状態を変えない ・OVERDUE を保存しない。

## 7. local の入口

`python -m src.intelligence.watchlist_thesis_intelligence.local_cli apply --p9-root R --decision FILE [--p8-root P] [--dry-run]` ・
`summary` ・`review-due`（`--at` ・`--as-of-date` を明示）。出力は local の受領（状態 ・P9 の id ・seq）・安全な投影 ・見直しの日の報告
だけ。web ・API ・PWA ・Morning Brief ・scheduler ・自動化は無い。production runtime closure の外。

## 8. A5 に残すもの

本人の環境での実の private な検証（完了した実の P8 の run の read-only の消費 ・新しい P9 の root ・人の判断の file ・J-Quants の
request なし）と、Phase 9 の最終監査 ・凍結の記録。
