# PHASE 8 / P8-PILOT2A — LOCAL REAL-DATA PILOT RUNNER（2 段の local runner。合成の検証だけ）

将来の PILOT2 を本人の Windows 機でだけ実行するための **2 段の runner** を作った gate。本 gate では実の J-Quants request ・cloud の credential
の使用 ・実の identity の登録 ・実の payload ・PILOT2 の実行は無い（合成 transport の test だけ）。

- 基準: P8-LIVE2 `476182af12bb583102e1f616316889bcfb8c58b9`（凍結。package 30 module ＋ LIVE2 transport）。full pytest の基準 5910 passed ／ 2 skipped。
- 規約 ・利用の authority は凍結の LIVE0 ・LIVE2。本書は placeholder だけで実の credential ・code ・値を含まない。

---

## 0. 結論

1. 追加した runtime は 1 module: **`src/intelligence/jquants_pilot2_local.py`**（`prepare` ・`execute` ・CLI `main`）。**package の外**。
   `scripts/` ではなく `src/intelligence/` に置いた理由: 凍結 LIVE2 の test が `scripts/` から transport を参照することを禁じており（本番 ・自動化への
   配線の防止）、runner は transport を使うため `scripts/` と両立しない。package の 30 module ・LIVE2 transport は byte 一致。
2. **2 段の人の gate**: 段 1 `prepare` は master を 1 回取得し、LIVE1 の適格 → 要求 code の選択 → 凍結 ID1 の提案 → **審査 packet** ＋
   **判断 template** を private の data root に書いて止まる（fins ・ID2 ・A1 ・A2 ・指標に触れない。自動の承認なし）。段 2 `execute` は
   人の判断（APPROVE ／ REJECT ／ DEFER ＋ aware な `accepted_at`）を読み、凍結 ID1 を再導出して digest を照合 → 凍結 ID2 → A1 の確認 →
   承認済みで登録できた発行体だけ fins → 凍結 ADP0 ・EXE → 凍結 A3 の 4 指標の status → **安全な要約**。
3. **request の予算**は 2 段を通して最大 8。`budget_state.json` に回数と path だけを保存し、段 2 は reset せず残りだけ使う（9 回目は transport に
   届かない。失敗した request も数える）。段 2 は master を再取得しない（packet の ID1 の 5 欄の行から再導出）。
4. **private の data root** は絶対 path で、repo ・`.git` ・GitHub の workspace の中を拒み、Actions の環境では動かない。作る file は packet ・
   判断 ・予算の状態 ・4 journal ・安全な要約だけ。raw の応答 ・provider の fixture は無い。
5. **安全な要約**（`safe_summary.json` ・stdout）は件数 ・outcome ・理由の code ・digest ・予算 ・store の整合 ・状態だけ。会社名 ・code ・財務の値 ・
   raw ・journal の内容 ・credential ・URL は入らない（test）。これだけを Claude ／ ChatGPT に貼る。
6. **発見 P8-OBS-60（監督の決定が要る）**: 凍結 A2 の resolver は財務の観測の解決に **`FUNDAMENTAL_DISCLOSURE` の coverage 宣言**
   （`ObservationCoverage`。data の日を覆い `complete_through ≥ cutoff`）を要求するが、凍結 EXE ・本 runner は coverage を書かない
   （書けば「全発行体について完全」という dataset 全体の宣言になり、1〜3 発行体の pilot では真でない。A2 の coverage は主語の範囲を持たない）。
   加えて PIT: identity は審査の `accepted_at` に知られ、bootstrap の identity coverage は D0 の 1 日なので、D0 の後の審査では主語が解けない。
   → **現状の凍結の意味では、PILOT2 の A3 指標は typed の `INSUFFICIENT_DATA`（`OUTSIDE_COVERAGE` ／ `SUBJECT_NOT_RESOLVED`）になる**。
   runner はそれを正直に報告する（値を作らない）。監督の指示どおり指標の可用性は PILOT_PASS の条件でない。test は coverage record を
   test だけが足すと 4 指標が `VALUE` になることで runner の A3 の配線を証明する（§5 ・§10）。
7. 判定: **P8_PILOT2A_LOCAL_RUNNER_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§14）。

---

## 1. 前提（本人の環境）

- Windows 機 ・Python 3.11 以上 ・repo の clone（本 branch）・`pip install -r requirements.txt`。
- 本人の J-Quants Light account の API key を **環境変数 `JQUANTS_API_KEY`** に置く（shell の session だけ。file ・repo ・chat に書かない）。
- repo の**外**に private の data root（例 `C:\Users\<you>\p8_private\pilot`）。本人だけが読める場所。
- D0（snapshot の日 `YYYY-MM-DD`）と 1〜3 の対象 code（5 桁 ・末尾 `0`）を本人が決める。自動の発見 ・選定は無い。
- 監督の PILOT2 の実行の承認。

## 2. 段 1 `prepare`

```
python -m src.intelligence.jquants_pilot2_local prepare --d0 <YYYY-MM-DD> --codes <CODE1> [<CODE2> <CODE3>] --data-root <PRIVATE_ROOT>
```

| 手順 | 内容 |
|---|---|
| 検査 | data root（§7）・D0 ・code（1〜3 ・重複なし ・`[0-9]{4}0`）・transport |
| pilot_id | `p8pilot2_<D0 の数字>_<sha256(D0, codes) の先頭 8>`（決定論） |
| 予算 | `budget_state.json` から復元（無ければ 8 ／ 0）。master の取得の後（失敗しても）保存 |
| 取得 | `fetch_master(D0)`（request 1。凍結 LIVE1 ・LIVE2）→ 行ごとの適格（raw は捨てる） |
| 選択 | 要求 code だけ。snapshot に無い code は `NOT_RETURNED` |
| ID1 | ELIGIBLE の行だけで `propose_bootstrap(rows, BootstrapBatch("p8boot1", D0, ("0111","0112","0113")))` |
| 出力 | `review_packet.json` ・`decision_template.json` ・`budget_state.json`（data root の `pilot2/`）。stdout は安全な要約（code ・名前なし） |
| 触れない | fins ・ID2 ・A1 ・A2 ・注記 ・保留 ・指標。既に packet があれば `PACKET_ALREADY_EXISTS`（上書きしない） |

## 3. 審査 packet（`review_packet.json`。private root の中だけ。commit しない）

| 欄 | 内容 |
|---|---|
| `schema` ・`pilot_id` ・`d0` ・`batch_id` ・`supported_markets` ・`manifest_digest` ・`rules_version` | 識別 ・digest |
| `targets[]` | `code` ・`eligibility`（ELIGIBLE_FOR_ID1 ／ HOLD ／ EXCLUDED ／ NOT_RETURNED）・`reasons`（LIVE1 の code）・`market` ・`product_category` ・`name_ja` ・`name_en` ・`checklist`（5 項目の真偽）・（提案があれば）`proposal_id` ・`proposal_digest` ・`issuer_anchor` ・`security_anchor` ・`issuer_id` ・`security_id` |
| `id1_rows[]` | 凍結 ID1 の 5 欄（`Date` ・`Code` ・`CoName` ・`CoNameEn` ・`Mkt`）。段 2 の決定論の再導出に要る唯一の入力 |
| `review_items[]` | ID1 の保留 ・人の審査の項目（あれば） |

含まない: API key ・raw の行 ・他の provider の欄（S17 ・S33 ・ScaleCat ・MktNm ・Mrgn …）・応答の本文。J-Quants 由来の名前を含むので
**private root の外に出さない ・commit しない**。処分は LIVE0 §7.3（解約時に data root ごと廃棄）。

## 4. 人の判断（`decision.json`）

template（`decision_template.json`）を `decision.json` に写し、次だけを編集する:

```
{
  "schema": "p8_pilot2_human_decision:0.1.0",
  "pilot_id": "<template のまま>",
  "manifest_digest": "<template のまま>",
  "accepted_at": "2026-07-01T18:05:00+09:00",          # 審査を確定した時刻。timezone つき。必須
  "decisions": [
    {"code": "<CODE>", "proposal_id": "<そのまま>", "proposal_digest": "<そのまま>", "disposition": "APPROVE"}
  ]
}
```

| 規則 | 内容 |
|---|---|
| disposition | `APPROVE` ／ `REJECT` ／ `DEFER` だけ。空 ・`yes` ・他 → `DECISION_DISPOSITION_MISSING`。既定の承認 ・一括の承認は無い |
| `accepted_at` | ISO 8601 ・timezone つき（`+09:00` ／ `Z`）。無い → `ACCEPTED_AT_MISSING`、naive → `ACCEPTED_AT_NAIVE`、形が違う → `ACCEPTED_AT_INVALID`。runner は時刻を作らない |
| 結びつき | `pilot_id` ・`manifest_digest` ・各 `proposal_id` ・`proposal_digest` が packet と一致。違えば `DECISION_PILOT_MISMATCH` ／ `DECISION_MANIFEST_STALE` ／ `DECISION_PROPOSAL_UNKNOWN` ／ `DECISION_PROPOSAL_STALE`（network ・書き込みの前） |
| 審査の前に見る事 | LIVE0 §7.2 の checklist（packet の `checklist` と `name_ja` ・`market` ・`product_category`。JPX の上場廃止一覧を人が確認） |

## 5. 段 2 `execute`

```
python -m src.intelligence.jquants_pilot2_local execute --data-root <PRIVATE_ROOT> [--decision <PATH>]
```

| 手順 | 内容 |
|---|---|
| 読み直し | packet ・判断。`id1_rows` から `MasterRow` を作り凍結 ID1 を再導出 → `manifest_digest` 一致（違えば `PACKET_MANIFEST_STALE`） |
| 審査の結びつけ | 凍結 `review_manifest`（提案の digest に結ぶ。`accepted_at` は人の値） |
| store | 4 store を無ければ作る（既にあれば触れない） |
| ID2 | 凍結 `execute_identity_registration` → `APPENDED` ／ `REUSED` ／ `NO_AUTHORIZED_ITEMS` ／ `REJECTED` ／ `PARTIAL_FAILURE` |
| A1 の確認 | 承認済みで束が APPENDED ／ REUSED の code だけ `verify_identity_for_code`（凍結 LIVE1）。失敗 → その code の fins を発しない |
| fins | 予算が残る code だけ `fetch_fins_summary(handoff)`（1 page。pagination は追わず件数だけ記録）。失敗 ・予算の枯渇は typed に記録 |
| ADP0 ・EXE | 行ごとに凍結 `execute_financial_summary_row(row, AdapterContext(issuer_id), root)`。outcome ・理由 ・保留の理由を数える |
| A3 | 発行体ごとに凍結 `revenue_growth` ・`operating_margin` ・`net_margin` ・`roa_point_in_time` の **status と理由の code だけ**（値は出さない ・保存しない）。対象 ＝ A2 の最新の年度、比較 ＝ その前年度（無ければ `INSUFFICIENT_DATA / NO_PRIOR_FISCAL_YEAR`）、cutoff ＝ max(観測の `certain_by`, Issuer の登録の `known_at`) ＋ 1 秒（時計なし）。**現状は coverage 宣言が無いので `INSUFFICIENT_DATA`（§0 の 6）** |
| 出力 | `safe_summary.json` ＋ stdout（同じ内容） |

## 6. 予算（2 段で 8）

`budget_state.json = {schema, pilot_id, limit: 8, used, remaining, paths}`。段 1 ・段 2 とも開始時に復元（`reserve` を path ごとに再生）、request の
たびに保存。段 2 は master を再取得しない。再実行で fins を再取得するので予算は進む（枯渇すれば `BUDGET_EXHAUSTED` で skip し
`PILOT_PARTIAL`）。9 回目は凍結 LIVE1 の `RequestBudget` が transport の前に拒む。隠れた retry ・pagination の自動追随は無い。

## 7. private の data root

| 拒否 | code |
|---|---|
| 無い ・空 ・相対 | `DATA_ROOT_REQUIRED` ／ `DATA_ROOT_NOT_ABSOLUTE` |
| repo の中（Pages ・docs ・data を含む） | `DATA_ROOT_INSIDE_REPO` |
| `.git` を含む | `DATA_ROOT_INSIDE_GIT` |
| `GITHUB_WORKSPACE` の中 | `DATA_ROOT_INSIDE_WORKSPACE` |
| `GITHUB_ACTIONS` が設定された環境 | `GITHUB_ACTIONS_NOT_ALLOWED` |

中に作る物: `pilot2/review_packet.json` ・`pilot2/decision_template.json` ・`pilot2/decision.json`（人が作る）・`pilot2/budget_state.json` ・
`pilot2/safe_summary.json` ・`screener_intelligence/{identity_records, observation_records, semantic_metadata, held_observations}.jsonl`。

## 8. 再実行 ・失敗

- ID2 ・EXE の途中の失敗（`PARTIAL_FAILURE`）: rollback ・削除なし。再実行は凍結の再利用で収束（test: identity 2 record → 8、注記 4 → 8 ＋ 観測 8）。
- fins の失敗: その code は `fins.failed` に code で記録。他の code は続く。
- store の破損: 段 2 の最初に 4 store を見る。`CORRUPT_<code>` があれば ID2 ・fins に進まず `PILOT_FAIL`（書かない ・呼ばない ・修復 ・削除しない。
  人が LIVE0 の手順で判断）。`MISSING` は作ってよい。
- runner の拒否は `{"state": "FAILED", "code": …, "detail": …}`（code と field 名だけ）。

## 9. 処分（LIVE0 §7.3）

解約 ・退会 ・downgrade の請求対象期間の終了で、private の data root（packet ・判断 ・予算 ・4 journal ・要約）を丸ごと削除し、日時と件数だけを
private の運用記録に残す。runner は削除の機能を持たない。

## 10. 安全な要約（`safe_summary.json`）

含む: `schema` ・`stage` ・`state`（`HUMAN_REVIEW_REQUIRED` ／ `PILOT_PASS` ／ `PILOT_PARTIAL` ／ `PILOT_FAIL`）・`pilot_id` ・`d0` ・`target_count` ・
`eligibility_counts` ・`decision_counts` ・`id2`（outcome ・理由 ・束の状態の件数 ・failure_code）・`digests`（manifest ・reviewed ・plan）・
`identity_verification`（ok ・failed ・理由）・`fins`（success ・failed ・skipped_budget ・理由 ・行数 ・pagination の有無）・`exe_outcomes` ・
`exe_reasons` ・`held_reasons` ・`metrics[]`（指標ごとの status と理由の code）・`request`（limit ・used ・remaining ・paths）・`store_integrity`。
含まない: 会社名 ・code ・財務の値 ・raw ・応答の抜粋 ・API key ・journal の内容 ・query つき URL（test が sentinel で確認）。

`PILOT_PASS` の条件: 承認 ≥ 1 ・ID2 が APPENDED ／ REUSED ・A1 の確認の失敗 0 ・fins 成功 ≥ 1 かつ失敗 0 かつ予算での skip 0 ・
EXE の APPENDED ／ REUSED ≥ 1 かつ REJECTED ／ PARTIAL 0 ・store 整合 ・request ≤ 8。指標の可用性は条件でない（typed の unavailable で可。
P8-OBS-60 のため現状は常に `INSUFFICIENT_DATA`）。`PILOT_FAIL`: 承認 0 ・ID2 REJECTED ／ PARTIAL ・登録 0 ・store 破損。他は `PILOT_PARTIAL`。

## 11. 将来の Windows の手順（placeholder だけ）

```
cd <repo>
set JQUANTS_API_KEY=<your key>                       # PowerShell: $env:JQUANTS_API_KEY="<your key>"
python -m src.intelligence.jquants_pilot2_local prepare --d0 <YYYY-MM-DD> --codes <CODE1> <CODE2> --data-root <PRIVATE_ROOT>
    → <PRIVATE_ROOT>\pilot2\review_packet.json を読む（LIVE0 §7.2 の checklist）
    → decision_template.json を decision.json に写し、disposition と accepted_at を書く
python -m src.intelligence.jquants_pilot2_local execute --data-root <PRIVATE_ROOT>
    → <PRIVATE_ROOT>\pilot2\safe_summary.json の内容だけを監督に貼る
```

## 12. 変更の範囲

| 対象 | 状態 |
|---|---|
| `src/intelligence/jquants_pilot2_local.py` | **新規**（package の外） |
| `tests/intelligence/test_screener_pilot2_local_runner.py` | **新規**（合成 transport の E2E ・人の判断 ・予算 ・再実行 ・要約の漏洩 ・architecture） |
| registry ・boundary | PILOT2A の登録（`PHASE8_PILOT2A_RUNTIME`）・`test_bo` の外の importer 2 つ目 ・LIVE2 anchor の guard |
| package 30 module ・LIVE2 transport ・Phase 8 の test 13 file ・先行の記録 23 | **byte 一致** |

## 13. 監督への提案（PILOT2 の前の決定）

P8-OBS-60: 実データから A3 指標を得るには、(a) 主語の範囲つきの coverage（凍結 A2 の model の変更 → 別 gate ・承認）、または (b) EXE の
後に **発行体ごとの取得の完全性**を別の record で宣言する設計、または (c) PILOT2 では指標を求めない（identity ・A2 ・注記 ・保留の経路の
実証だけ）のいずれかの決定が要る。本 runner は (c) の下でそのまま使える。

## 14. 判定

**P8_PILOT2A_LOCAL_RUNNER_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**
