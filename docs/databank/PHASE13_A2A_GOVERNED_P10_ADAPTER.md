# PHASE 13 — A2a: GOVERNED P10 SAFE VIEW ADAPTER（read-only ・P10 の 5 つの名前だけ）

Review State Memory の標本を、凍結の P10 の **governed な safe view だけ**から作る read-only の adapter（P13-A2a）。
P13-A1 の純粋な model（`ccfc8e57885fabc5936a39034a9e816c66b2fbbc` ＝ registry の `P13_A1`）は変えない。store ・永続化 ・投影 ・
`SampleEvidence` の作成は無い（P13-A3 以後）。B-track は HOLD ・P14 は未着手。

| 項目 | 値 |
|---|---|
| runtime（登録 ・認可: gate `P13-A2a` ・anchor `P13_A1`） | `src/intelligence/market_memory/governed_review_source.py` |
| API | `sample_review_state(p10_root, p9_root, *, cutoff: SampleCutoff, rules_version: str) -> SampleOutcome` |
| import の面 | `read_personal_review` ・`read_p9_safe_view` ・`personal_safe_projection` ・`ReviewViewError` ・`P9ViewError`（P11 と同じ 5 つ ・完全一致） |
| importer の登録 | `SANCTIONED_P13_P10_IMPORTERS`（adapter の 1 file だけ）。凍結の P10 の importer の guard に 5 行を足し、`PHASE13_TEST_REGISTRATION` が完全一致で pin |
| A1 の不変 | A1 の runtime 4 file の blob は `P13_A1` の commit と一致（HEAD ・index ・作業木を guard が確かめる） |
| `__init__.py` | adapter を出さない（A1 の model は P10 を import しないまま） |

## 1. 手順（明示の cutoff ・3 回の読み）

1. `read_p9_safe_view(p9_root, at, as_of_date)` — P9 の失敗は P9 の category で分類する（見直しの view の経路は P9 の category を落とすため先に読む）。
2. `read_personal_review(p10_root, p9_root, at, as_of_date)`。
3. `read_p9_safe_view` をもう一度読み、1 と全ての欄 ・view の class ・schema ・rules の version が一致することを確かめる。
4. 形（dataclass の欄の集合）・schema ／ rules の version ・3 つの view の class ・`as_of_date` を、検証済みの固定の literal と比べる。
   期待の値は **返った object から導かない**（literal は P10 の凍結の定数と一致することを test が確かめる）。未知の版 ・class は fail closed。
5. `personal_safe_projection(review)`。
6. 承認した欄だけを P13 の model に写す（見直しの項目の 12 欄 ・P9 の安全な投影の 11 の件数 ・個人の投影の 13 の整数 ・見直しの件数）。
7. P13-A1 の `build_sample` で標本を作る（件数の検算 ・矛盾は A1 の INTEGRITY_FAILURE）。

`at` と `as_of_date` は呼び出し側が渡した `SampleCutoff` のまま 3 回とも同じ。時計 ・既定 ・「最新」は無い。source の `known_at` ・
`reviewed_at` ・transition の瞬間 ・P10 の revision の digest は **捏造しない**（view に無く、model にも欄が無い）。

## 2. 失敗の分類（adapter が行う ・固定の code だけ）

P10 の `P10_STORE_UNAVAILABLE` ・`P9_UNAVAILABLE` は不在だけでなく破損も含む（P12.5 の調査 ・P13-A2a の調査で確認）。従って adapter は
P13-A1 の `outcome_for_source_failure` に P10 ／ P9 の生の code を **渡さず**、`SampleOutcome` を自分で作る。

| 状況 | 結果 | code |
|---|---|---|
| P9 ／ P10 の store の最初の不在（category `STORE_MISSING` ・不在の code だけ） | MISSING | `P9_STORE_MISSING` ／ `P10_STORE_MISSING` |
| 破損（category `STORE_CORRUPTION`） | INTEGRITY_FAILURE | `P9_STORE_CORRUPTION` ／ `P10_STORE_CORRUPTION` |
| 世界の不正 | INTEGRITY_FAILURE | `P9_WORLD_INVALID` ／ `P10_WORLD_INVALID` |
| 並行の変更 ・2 回の P9 の読みの不一致 ・最初の成功の後の読みの失敗（見直しの経路の P9 の失敗を含む） | INTEGRITY_FAILURE | `SOURCE_CHANGED_DURING_READ` |
| governed な reader が root ・入力を拒む（相対 ・`..` ・symlink など） | INTEGRITY_FAILURE | `SOURCE_INPUT_REJECTED` |
| 未知の code ・形の違う detail | INTEGRITY_FAILURE | `SOURCE_READ_UNCLASSIFIED` |
| 未知の版 ／ class ・形 ・`as_of_date` の不一致 ・写せない内容 | INTEGRITY_FAILURE | `VIEW_SCHEMA_UNSUPPORTED` ／ `VIEW_CLASS_UNSUPPORTED` ／ `VIEW_SHAPE_UNSUPPORTED` ／ `VIEW_AS_OF_MISMATCH` ／ `VIEW_CONTENT_INVALID` |
| 呼び出し側の型の誤り（空 ・NUL を含む ・型の違う root、`SampleCutoff` でない cutoff、不正な `rules_version`） | 例外 `ReviewStateError` | `ADAPTER_INPUT_INVALID`（detail は欄の名前だけ ・source は読まない） |

有効な空の標本（store は在り項目が 0）は SAMPLED であり、MISSING ではない。失敗に部分の標本は無い。結果に例外の detail ・root ・
著者 ・note は入らない。広い例外の捕捉は無く、P10 の error 以外の例外は隠さず上へ出る。

## 3. 限界（明示）

2 回の P9 の読みが一致しても、P9 と P10 の store をまたぐ **不可分な snapshot の証明ではない**。読みの間に書き換えて戻す往復（ABA）は
除外できない（test が限界を固定する: 一時の revision を見直しの view が見て、2 回の P9 の読みは一致し、標本は SAMPLED になる）。
P10 の store も 1 回しか読まないので、その間の P10 の往復も検出できない。完全な整合性の検証（root の manifest など）は監督の将来の決定。

## 4. 境界

- import は上の 5 つの名前と P13 の `.canonical` ・`.review_state_sample` だけ。P10 ／ P9 の store の class ・private な snapshot ・executor は無い。
- 凍結の guard の変更は P10 の importer の guard の 5 行だけ（`SANCTIONED_P13_P10_IMPORTERS` の完全一致の分岐）。他の textual な import の
  禁止（P8 ・P9 ・P11 ・P12 の package 名）は不変。P13 の guard は adapter にだけ `personal_intelligence` の名前を許す。
- file ・環境 ・時計 ・socket ・process ・network ・資格情報は使わない（P12 と同じ名前 ・語彙の guard）。本番の閉包の外。

## 5. 試験（合成の一時 root だけ）

凍結の test の builder（P9 の世界 ・P10 の初期化 ・P10 の executor の決定）で一時 root を作る。本物の private な root には触れない。
空 ・有効な標本 ・決定の前後の端点の差 ・決定論 ・読みの前後の P9 ／ P10 の tree の byte と mtime の不変 ・不在 → MISSING ・破損 → INTEGRITY_FAILURE ・
並行の変更 ・2 回の P9 の読みの不一致 ・最初の成功の後の失敗 ・ABA の限界 ・未知の版 ／ class ／ 形 ・`as_of_date` の不一致 ・入力の誤り ・
root の拒否 ・部分の標本が無い ・detail ／ root の不漏えい ・telemetry の独立 ・面の検査 ・network ／ 資格情報 ／ process の罠。

## 6. 次（監督の個別の GO を要する）

P13-A3 store ／ rebuild（`SampleEvidence` ・永続化）→ A4 projection → A5 実機 → A6 freeze。
