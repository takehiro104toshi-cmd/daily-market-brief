# PHASE 9 / P9-A1 — P8 → P9 HANDOFF CONTRACT / REGISTRATION / READ-ONLY RECONSTRUCTION ADAPTER

Phase 9（Watchlist / Thesis Intelligence）の最初の実装 gate。凍結の Phase 8（`docs/databank/PHASE8_FINAL_FREEZE.md`。意味 ／
runtime の凍結 anchor `0a32d86bd80d0f9a0b9f4cecbd7c961a93dfa15f`）の完了した screen の run を、P9 が **read-only** で消費するための
契約と、その再構成の adapter だけを足す。**Phase 9 の凍結ではない。** Watchlist ／ Thesis の authority ・store ・提案 ・状態の遷移は
後の gate。

- 基準: P8 の凍結の記録の commit `471e98de5f90dcbbf4ecae9970745eb896e2b3c5`（registry の `P9_BASE`）。
- 受理した観察: P9-OBS-001 〜 P9-OBS-011（P9-A0）。
- 本 gate は合成の P8 の run の test だけ。実 J-Quants ・private の実 data の root ・実の Universe ／ 方針は無い。

---

## 1. namespace

`src/intelligence/watchlist_thesis_intelligence/`（Phase 9 の package）。理由:

- 既存の `*_intelligence` package（`theme_intelligence` ・`narrative_intelligence` ・`screener_intelligence`）と同じ命名で、Phase の
  package であることが名前で分かる。P8 の private root の `screener_intelligence/` と同じく、P9 の private root の dir 名
  （`watchlist_thesis_intelligence/`）と一致する。
- 既存の公開の watchlist（`config.yaml` の `watchlist:` ・`src/analysis/models.py` の `WatchlistEntry` ・`src/report` ・Morning Brief ・
  PWA）とは別物。本 package はそれらを import ・移行 ・供給しない（guard）。
- 本 package は production runtime closure に含まれない（guard）。

| file | 役割 |
|---|---|
| `__init__.py` | package の docstring だけ（import なし） |
| `p8_handoff.py` | 完了した P8 の run の read-only の再構成 ・drift の検査 |
| `private_root.py` | P9 の private root の規約（定義だけ ・A1 では使わない） |

## 2. 意味の分離

**P8 `ScreenResultSet` ≠ P9 Watchlist の項目 ≠ P9 Thesis ≠ 推奨 ≠ 売買の指示。**

- P8 の結果は「明示の方針 P に、評価の瞬間 T で、発行体 X が当てはまった ／ 当てはまらなかった ／ 評価できなかった」という型つきの
  事実。意見 ・順位 ・推奨ではない。
- A1 には Watchlist の昇格 ・提案 ・順位 ・点数 ・推奨 ・Thesis の authority は無い。

## 3. 引き渡しの契約

1. P9 は **完了した** P8 の run を **read-only** で消費する。
2. P9 は P8 の store（authority ・台帳）に **書かない**（作成 ・追記 ・修復 ・削除 ・初期化なし）。
3. 完了した run を読むのに **J-Quants の request は要らない**（transport ・client を作らない ・network なし）。
4. 完了した run を再構成するのに **`JQUANTS_API_KEY` は要らない**（credential を読まない）。
5. **COMPLETE の run だけ**を消費する。閉じていない呼び出し（`P8_RUN_OPEN_INVOCATION`）・未判定 ・未試行の発行体 ・PARTIAL
   （`P8_RUN_NOT_COMPLETE`）は fail closed。
6. P9 は **`run_id` と消費した `screen_result_id` の両方**に結び付く。新しい再構成が違えば **`P8_RESULT_DRIFT`**。
7. 手順: **1 つの P8 の private root ・D0 に 1 つの run**（`ONE_P8_RUN_PER_PRIVATE_ROOT_PER_D0`）。凍結の台帳は
   `screen_result_id` を封じないので、同じ root ・同じ D0 の後の run が前の run の評価の瞬間までの保持を足すと、前の run の再構成が
   変わり得る（P9-OBS-002）。drift の検査がそれを fail closed にする。P8 を再開して結果の id を封じることはしない（延期）。
8. 評価の意味（凍結 B2 ／ B4A ／ B5B）を複製しない。

## 4. adapter（`p8_handoff.reconstruct_completed_run(p8_root, run_id)`）

| 段 | 内容 | 失敗 |
|---|---|---|
| 入力 | 明示の P8 root（絶対 ・既存の directory。作らない）・明示の `run_id`（`p8run_<24 hex>`） | `P8_ROOT_REQUIRED` ・`P8_ROOT_NOT_ABSOLUTE` ・`P8_ROOT_MISSING` ・`RUN_ID_INVALID` |
| 台帳 | 凍結 `ledger_path` ＋ `load_ledger`（read-only。digest ・鎖 ・遷移の検査） | `P8_LEDGER_INVALID`（凍結の code を detail に） |
| spec | 台帳の spec → 凍結 `ScreenRunSpec`。`as_dict()` の完全一致 ・`run_id` の一致（規則の版の束ねを含む） | `P8_SPEC_MISMATCH` |
| 完了 | 閉じていない呼び出しなし ・master の判定あり ・全発行体を試行済み | `P8_RUN_OPEN_INVOCATION` ・`P8_RUN_NOT_COMPLETE` |
| store | 必要な 9 つの凍結の store を `open(read_only=True)` で確かめる（無い store は作らない） | `P8_STORE_MISSING` ・`P8_STORE_UNAVAILABLE` |
| authority | Universe の record（id ・版 ・member）・方針の record（id ・版）が spec と一致 | `P8_UNIVERSE_MISMATCH` ・`P8_POLICY_MISMATCH` |
| 再構成 | 凍結 `assemble`（凍結 B4A ／ B5B）。実行の完全性が COMPLETE | `P8_RECONSTRUCTION_FAILED` ・`P8_RUN_NOT_COMPLETE` |
| 出力 | `P8RunHandoff`: 凍結 `ScreenResultSet` ＋ 不変の `HandoffMetadata`（`run_id` ・`screen_result_id` ・Universe ／ 方針の id と版 ・mode ・日 ・評価の瞬間 ・件数 ・完全性 ・台帳の event 数 ・先頭の digest） | — |

使わないもの: 凍結 B5C の `execute_screen` ／ `continue` ／ `_store_integrity`（store を作る）／ `LedgerWriter` ／ `_create_ledger`・
`LocalHttpsTransport` ・`JQuantsLiveClient` ・HTTP の client ・store の `initialize` ／ `append`・環境変数 ・時計 ・LLM。

drift: `require_binding(handoff, run_id=, screen_result_id=)`（純）・`reconstruct_bound(p8_root, run_id=, screen_result_id=)`（新しい
再構成 ＋ 一致の要求）。違えば `P8_RESULT_DRIFT`。

## 5. Phase 9 の private root の規約（定義だけ）

`<caller が明示に渡す P9 の private root>/watchlist_thesis_intelligence/`（`private_root.phase9_authority_dir`）。既定の path ・利用者の
機械の path は無い。P8 の root と P9 の root は構造的に分ける（同じ ・入れ子は `ROOTS_NOT_SEPARATE`。`require_separate_roots`）。
A1 では何も作らない ・使わない。

## 6. 登録 ・凍結の P7 ／ P8 の test の狭い再開（test だけ）

- `tests/intelligence/phase9_runtime_registry.py`: P9 の runtime 3 ・test 3 ・文書 1 の完全な一覧。
- 凍結の P7 ／ P8 の test の guard に入れた登録の差分は registry の `PHASE9_TEST_REGISTRATION` に行で完全に列挙し、P9 の guard が
  anchor との差分の完全一致を pin する（P8 が P7 に入れた登録と同じ型）。P8 の runtime の source は `0a32d86` と byte 一致。
- P8 の `test_bo_no_other_package_imports_phase8` の外の importer の許可は `p8_handoff.py` の 1 file だけで、import の面は
  `SANCTIONED_P9_A1_IMPORTS`（module → 名前の完全一致）で pin する。

## 7. 合成の証拠（`tests/intelligence/test_watchlist_thesis_handoff.py`）

完了した run の決定論の再構成（2 回 ・同じ `screen_result_id`）・P8 root の file ／ byte の不変 ・無い store を作らずに fail closed ・
credential の環境変数なし ・transport ／ client ／ HTTPS ／ socket ／ 実行 ／ store の作成の罠は呼ばれない ・閉じていない呼び出し ・
PARTIAL（予算の延期 ・master の失敗）・違う ／ 不正な run_id ・spec の不一致（版 ・瞬間 ・規則の束ね ・余分 ／ 欠けた欄）・台帳の破損 ・
root の検査 ・drift（純の helper ・同じ root の同じ日の後の run）・private root の規約。

## 8. 境界（`tests/intelligence/test_watchlist_thesis_boundary.py`）

registry の完全一致 ・import の面の完全一致 ・P5 ／ `src.analysis` ／ `src.report` ／ 通知 ／ 公開 ／ PWA ／ LLM ／ HTTP ／ P8 の書き込み ・
実行の経路を import しない ・transport を作らない ・store の `open` は `read_only=True` だけ ・順位 ／ 点数 ／ 推奨の語なし ・production
runtime closure の外 ・他の package から import されない ・P8 runtime の byte 一致 ・凍結の P7 ／ P8 の test の差分は登録だけ。
