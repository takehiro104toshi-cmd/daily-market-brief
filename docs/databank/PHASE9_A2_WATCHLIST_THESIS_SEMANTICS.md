# PHASE 9 / P9-A2 — WATCHLIST / THESIS SEMANTIC MODEL

Watchlist ／ Thesis の意味の model ・L0 の提案 ・不変の revision ・状態機械 ・記録をまたぐ不変条件 ・禁止の意味（純 ・保存なし）。
**Phase 9 の凍結ではない。** store ・追記の実行器 ・LLM は無い。基準: P9-A1 `ee8492532f50b1bfa9d41395dbc43667a0ae8399`（引き渡しの契約
`PHASE9_A1_P8_HANDOFF_CONTRACT.md` が authority）。P8 は凍結のまま（`0a32d86`）。実の発行体 ・run ・id ・閾値 ・財務の値は無い。

| file | 役割 |
|---|---|
| `revision_model.py` | 共通の revision の意味（root ・内容 address の revision ・seq ・prev ・reviewed_at ・人の著者 ・時点の状態） |
| `watch_model.py` | Watchlist の項目の revision ・状態機械 ・出所 |
| `thesis_model.py` | Thesis の revision ・無効の条件 ・根拠 ／ 反証 ・状態機械 |
| `proposal_model.py` | L0 の提案（Watchlist の候補 ・見直しの日）。非 authority ・保存しない |
| `cross_rules.py` | 記録をまたぐ不変条件（時点ごとの像） |

## 1. 意味

- **Watchlist の項目**: 人が「この発行体を追う」と決めた記録（理由 ・次の見直しの日）。主語は凍結 A1 の IssuerId だけ（security の
  watch は v1 に無い）。
- **Thesis**: 人が書いた「なぜ追うか」の説明（主張 ・仕組み ・きっかけ ・危険 ・前提 ・無効の条件 ・支持の根拠 ・反証）。
- P8 の `ScreenResultSet` ≠ Watchlist の項目 ≠ Thesis ≠ 推奨 ≠ 売買の指示。

## 2. authority

| level | 作る者 | authority | 保存 |
|---|---|---|---|
| L0 提案（`PROMOTION_CANDIDATE` ・`REVIEW_DUE`） | 決定論の code | 無い | しない（入力から再導出 ・digest） |
| Watchlist の revision | 人（`author_ref` は `human:` ・`reviewed_at` は caller が渡す aware） | 有る | A3 |
| Thesis の revision | 人 | 有る | A3 |

自動の昇格 ・自動の遷移 ・code ／ LLM が作る authority は無い（runtime の code は authority の revision を作らない。guard）。時計を
読まない: `reviewed_at` ・`review_due_on` ・horizon ・状態は全て caller が渡す。OVERDUE は caller が渡す日からの派生（保存しない）。

## 3. id（内容 address ・sha256 の先頭 24 hex ＝ 96 bit）

| id | 接頭辞 | 導く欄 |
|---|---|---|
| Watchlist の項目（root ・安定） | `p9wat` | 発行体 ・著者 ・作成の `reviewed_at` ・出所 |
| Watchlist の revision | `p9wrv` | revision の全欄 |
| Thesis（root ・安定） | `p9ths` | 発行体 ・Watchlist の項目 ・著者 ・作成の `reviewed_at` |
| Thesis の revision | `p9trv` | revision の全欄 |
| 無効の条件 | `p9inv` | thesis ・人が付けた key（文を直しても変わらない） |
| 提案の digest | `p9prp` | 提案の全欄 |

名前 ・code ・点数 ・順位 ・推奨 ・閾値 ・個人の data は id に入らない。

## 4. 状態機械（全て人の `TRANSITION`）

- Watchlist: `ACTIVE` ・`PAUSED` ・`REMOVED`（終端）。(作成) → ACTIVE ／ ACTIVE ⇄ PAUSED ／ ACTIVE ・PAUSED → REMOVED。
  REMOVED には `removal_reason` が要る。ACTIVE は `review_due_on` が要る（PAUSED は任意 ・REMOVED は無い）。削除の後の再追加は
  別の root（復活しない）。`PROPOSED` ・`OVERDUE` は保存しない。
- Thesis: `ACTIVE` ・`CHALLENGED` ・`INVALIDATED`（終端）・`RETIRED`（終端）。(作成) → ACTIVE ／ ACTIVE → ACTIVE（`REVISE` の内容の
  revision）／ ACTIVE ⇄ CHALLENGED ／ ACTIVE ・CHALLENGED → INVALIDATED ・RETIRED。遷移には人の `status_reason` が要る。
  INVALIDATED は `CONDITIONS`（直前の revision の既知の条件の id を 1 つ以上）か `OTHER`（条件の id なし ・人の理由）。
- 終端からの遷移 ・訂正は無い。

## 5. revision

不変の revision の鎖: root ・内容 address の `revision_id` ・`seq`（1 から連番）・`prev_revision_id` ・`reviewed_at`（非減少）・
`author_ref`。変更の種類: `CREATE`（seq 1）・`REVISE`（状態は同じ）・`TRANSITION`（状態機械）・`CORRECTION`（状態は同じ ・同じ鎖の
既存の revision を `corrects_revision_id` と理由で正す。過去は書き換えない）。発行体 ・出所 ・（Thesis の）Watchlist の項目は
root を通して不変。**時点 T の状態 ＝ 検査済みの鎖の `reviewed_at <= T` の最大の seq**（file の順は authority ではない）。

## 6. 出所 ・根拠

- Watchlist の出所: `P8_PROPOSAL`（run ・`screen_result_id` ・方針の id と版 ・Universe の id と版 ・authority の日 ・提案の digest）か
  `MANUAL`。P8 の提案は EVALUATED の発行体ごとに 1 つ（MATCH は特別ではない ・状態で選ばない ・run 全体の件数を持つ）。人の作成は
  提案の digest に正確に結び付く（`require_proposal_binding`）。
- Thesis の根拠（v1）: `P8_SCREEN_RESULT`（run ・結果 ・発行体 ・Screener の状態。指標の値は無い）と `HUMAN_NOTE`。支持と反証は別の
  欄で、同じ根拠は両方に置けない。P8 の根拠の発行体は Thesis の発行体と同じ。
- 確信（`confidence_note`）は文だけ。数 ・割合 ・比だけの文は拒む（数の確信は点数の代わり）。

## 7. 記録をまたぐ不変条件（`cross_rules.check_world`。全 revision の審査の瞬間ごとの像）

1. 発行体ごとに REMOVED でない Watchlist の項目は高々 1 つ。
2. 生きている Thesis（ACTIVE ・CHALLENGED）は、その時点に存在し REMOVED でない同じ発行体の項目を指す（→ 生きている Thesis が
   ある間は項目を REMOVED にできない ・項目なしに Thesis は作れない）。
3. 全ての Thesis の発行体は、指す項目の発行体と同じ。
4. Watchlist の `thesis_ids` は人が宣言した索引だけ（authority ではない）: 宣言した各 id はその時点に存在し、その Thesis が項目を
   指す。link の authority は Thesis の `watch_entry_id`。記録を自動で書き換える関数は無い。

## 8. 除外する意味

順位 ・点数 ・優先度 ・推奨 ・売買 ・目標株価 ・期待収益 ・比率 ・配分 ・建玉 ・確信の数 ・格付け ・個人の好み ・保有 ・portfolio ・売買の指示は
欄 ・enum ・識別子に無い（構造の guard）。人の自由文の普通の語は検閲しない。

凍結の値の複製: IssuerId の構文（`p8iss_<24 hex>`）と P8 の Screener の状態は test が凍結 A1 ／ B1 と一致を pin する（P8 の
package を新しく import しない ・P8 の data は A1 の `p8_handoff` だけを通る）。

## 9. A3 に残すもの（store が要る検査）

- 正準の行の直列化 ／ 復元（`from_dict`）・追記専用の store（Watchlist ・Thesis は別）・破損 ・切断 ・同時の変更は fail closed。
- 追記のたびに既存の全 revision ＋ 候補で `check_world`（store 全体の発行体の一意 ・link ・時点ごとの像）。
- root ・revision の id の store 全体の一意 ・鎖の先頭の一致（同時の追記の検出）。
- 発行体が凍結 A1 の identity に存在すること（P8 の root の read-only の消費 ・時点つき）。
- P8 の提案の digest と、A1 の再構成（`reconstruct_bound`）から導いた提案の一致（実行器は A4）。
