# PHASE 11 / P11-A1 — GOVERNED READ ADAPTER + UI MODEL

Phase 11（PWA ／ 利用者との対話の面）の最初の実装 gate。凍結の Phase 10 を **governed な read の API だけ**で読む Phase 11 の唯一の
read の adapter と、不変の UI model ・決定論の JSON だけを足す。**Phase 11 の凍結ではない。** HTTP server ・browser の UI ・manifest ・
service worker ・browser の保存 ・PWA の install ・書き込み ・実行器の呼び出しは無い（後の gate）。

- 基準: `P11_BASE` ＝ Phase 10 の凍結の記録の commit `d01f6bc01fba783e77cc3a623745b8b033883e1a`。
- 監督者の固定（P11-A0）: v1 は read-only ・profile の文は出さない ・除外の id ／ 理由は出さない ・push 通知は Phase 11 v1 に無い ・
  private な PWA は loopback の local の Python app ・既存の GitHub Pages は不変で別 ・private な P10 の data は機械を出ない ・LLM なし ・
  保有なし。
- 凍結の anchor は不変: P10 `1a7b9a2`（runtime 17 file）・P9 `4c19701`（18）・P8 `0a32d86`（54）・P7。

## 1. package ・登録

- `src/intelligence/personal_ui/`: `__init__.py` ・`p10_read_adapter.py` ・`ui_model.py`（`PHASE11_A1_RUNTIME`）。production runtime
  closure の外 ・公開の Pages の workflow ／ script ／ 公開の report の code から参照されない（guard）。
- 凍結の P7 ／ P8 ／ P9 ／ P10 の test の guard 5 file に Phase 11 の runtime ・test ・文書 ・`p10_read_adapter` の importer の許可を足した
  （test だけの狭い再開）。行は `PHASE11_TEST_REGISTRATION` に完全に列挙し、Phase 11 の guard が `P11_BASE` との差分の完全一致を pin する。
  P10 の登録の pin は P10 の終わり（`P11_BASE`）まで。P10 の凍結の guard の「src は不変」は Phase 10 の package に限った（Phase 10 の
  runtime が不変という不変条件は同じ。他の phase の追加を塞がない）。

## 2. read の境界（`p10_read_adapter`。完全一致 ・`SANCTIONED_P11_P10_IMPORTS`）

| module | 名前 |
|---|---|
| `personal_intelligence.review_view` | `read_personal_review` ・`ReviewViewError` |
| `personal_intelligence.personal_projection` | `personal_safe_projection` |
| `personal_intelligence.p9_view` | `read_p9_safe_view` ・`P9ViewError` |

import しない: `ProfileStore` ・`AttentionStore` ・`PersonalAuthorityStores` ・`store_io` ・`serialization` ・`admin_init` ・`executor` ・
`decisions` ・`local_cli` ・`read_p9_private_snapshot` ・P9 の store ・P8 ・J-Quants ・公開の report ・通知 ・network ・LLM。
stdlib は `dataclasses` ・`datetime` ・`json` ・`re` ・`typing` だけ（`os` ・`pathlib` ・`socket` ・`http` ・`subprocess` も無い）。

推移的な load（P10-OBS-044 ・P11-OBS-008）: 凍結 P10 の `review_view` ／ `p9_view` が凍結 P9 を import し、凍結 P9 の `p8_handoff` が
P8 ／ J-Quants の module の **code** を load する。request は無い（test が socket ・HTTP ・J-Quants の client ／ transport の構築を罠にして
0 を証明）。P11 は新しい直接の import を足さない。

## 3. UI model（`ui_model`。不変 ・派生 ・非 authority）

`UiModel`: `schema_version`（`p11_ui_model:0.1.0`）・`view_class` ・`at`（UTC の ISO に正準化）・`as_of_date` ・`active_profile_present` ・
`review_lookahead_days` ・`personal_counts`（凍結 P10 の安全な投影の 13 の件数）・`p9_counts`（凍結 P9 の安全な view の件数を平らに）・
`unmatched_live_mark_count` ・`entries` ・`source_schema_versions`。

`UiReviewEntry`: `ordinal` ・`source_kind`（WATCH ／ THESIS）・`p9_status` ・`p9_provenance_kind` ・`review_due_on`（ISO の日か null）・
`due_class` ・`attention`（FOCUS ／ NORMAL ／ MUTE）・`excluded_by_profile` ・`surface_group` ・`linked_watch_ordinal`（Thesis が link する
Watchlist の行の同じ応答の中の位置か null）。

意図して捨てた欄（governed な view にはあるが P11 には無い）: `p9_root_id` ・`p9_revision_id` ・`issuer_id` ・`linked_watch_entry_id`。
governed な view に無く P11 も足さない: profile の文 3 つ ・除外の id ・除外の理由 ・著者 ・瞬間 ・revision の鎖。

表示の鍵の決定: **`ordinal`（応答の中の位置）だけ**。決定論（同じ入力 → 同じ位置）で、authority の id を復元できず、応答をまたいで
同じ record を結び付ける仮名にもならない（hash の仮名は決定論なら結び付き ・乱数なら非決定論になる）。新しい authority の id は作らない。

語彙は凍結 P10 の列挙の値の複製で、一致は test が pin。点数 ・順位 ・優先度 ・推奨 ・確信 ・利回り ・価格 ・売買 ・配分 ・適合性 ・保有の
欄は無い。順は governed な view のまま（P11 で並べ替えない）。MUTE ・除外 ・終端 ・期日の無い行も governed な view のまま含む。

## 4. 決定論 ・JSON

同じ P9 ／ P10 の store の byte ・同じ瞬間（時間帯が違っても UTC で同じ）・同じ日 ・同じ schema → `ui_model_json_bytes` は同じ byte。
JSON は UTF-8 ・key の文字の順 ・区切りの空白なし ・NaN ／ Infinity は拒む ・schema の版を含む。表示の直列化であり authority の形では
ない（保存しない）。新しい依存は無い（stdlib の `json`）。

## 5. 誤りの model（`UiReadError`）

`INPUT_INVALID:<INSTANT_NOT_AWARE ／ INVALID_DATE ／ ROOT_REQUIRED:P10 ／ ROOT_REQUIRED:P9>` ・`P10_UNAVAILABLE:<store の code>` ・
`P10_INVALID:<A2 の code>` ・`P9_UNAVAILABLE:<code>` ・`P9_INVALID:<code>` ・`P10_READ_FAILED` ・`P9_READ_FAILED` ・`MODEL_INVALID:<欄>`。
detail は大文字の code の文字（`[A-Z0-9_:]`）だけを通し、他は捨てる（path ・id ・文 ・生の例外 ・credential は入らない）。修復しない。

## 6. 時点 ・時計 ・network

`at`（aware）・`as_of_date` は必須 ・既定なし ・時計から導かない ・そのまま governed な view へ渡す。network ・HTTP の library ・J-Quants ・
環境変数の読みは無い（`JQUANTS_API_KEY` を読まない ・出さない）。

## 7. 証拠

`tests/intelligence/test_personal_ui_adapter.py`: model の形 ・捨てた欄の不在 ・順の保持 ・MUTE ／ 除外の可視 ・link の ordinal ・
決定論（繰り返し ・時間帯）・正準の JSON ・sentinel の私的（id ・発行体 ・文 ・理由 ・著者 ・path ・credential）・誤りの写像 ・
zero network ・credential の非読 ・語彙の一致 ・保有の語彙なし ・読み込みで何も書かない。
`tests/intelligence/test_personal_ui_boundary.py`: registry の完全一致 ・`P11_BASE` 以後の面 ・凍結の test の差分の pin ・P7 〜 P10 の
runtime の object 一致 ・import の面の完全一致 ・禁止の import ・production の外 ・Pages ／ 公開の code の外 ・語彙。

## 8. 観察

P11-OBS-001 〜 015（P11-A0）を引き継ぐ。P11-OBS-016 〜（gate の報告に記録）。
