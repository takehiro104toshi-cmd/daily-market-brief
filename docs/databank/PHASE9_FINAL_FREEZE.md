# PHASE 9 — WATCHLIST / THESIS INTELLIGENCE v1: COMPLETE / CLOSED / FROZEN

Phase 9 の最終凍結の記録（P9-FREEZE-RECORD）。本文書 ・registry ・guard だけの記録であり、runtime の意味は変えない。
この記録の commit は **新しい anchor ではない**。

| 項目 | 値 |
|---|---|
| 状態 | **COMPLETE / CLOSED / FROZEN** |
| 意味 ／ runtime の凍結 anchor | `4c1970174f678245b569fdbb812a8a6ced52410b`（registry の `P9_A5`） |
| 凍結の範囲 | P9-A0 〜 P9-A5 の実装 ／ runtime（登録済みの runtime 18 file ・Phase 9 の test ・Phase 9 の設計文書） |
| 実 data の検証 | P9-A5 real private validation: **PASS / CLOSED** |
| 最終監査 | P9-A6 final audit: **P9_FINAL_AUDIT_PASS** |
| 受理した観察 | P9-OBS-001 〜 P9-OBS-020 |
| Phase 8 | COMPLETE / CLOSED / FROZEN のまま（`0a32d86`。runtime 54 file は byte 一致） |

guard: `tests/intelligence/test_watchlist_thesis_boundary.py` の
`test_p9_freeze_the_18_registered_runtime_files_are_byte_identical_to_the_a5_freeze_anchor` が、登録済みの runtime 18 file が anchor と
byte 一致し、anchor の package の file の集合が登録と一致し、本文書が anchor の後に足され private な値を含まないことを pin する。

---

## 1. 意味（v1）

- private（caller が明示に渡す private root だけ。P8 の root と構造的に別）
- local（本人の環境だけ。scheduler ・自動化 ・web ・API は無い）
- deterministic（内容 address の id ・正準の JSONL ・file の順は authority ではない）
- human-governed（authority を作るのは `human:` の著者の検査済みの入力だけ ・自動の作成 ／ 遷移 ／ 昇格なし）
- immutable revision history（root ・内容 address の revision ・seq ・prev ・訂正は新しい revision）
- Watchlist authority（発行体だけ ・ACTIVE ⇄ PAUSED → REMOVED）
- Thesis authority（ACTIVE ⇄ CHALLENGED → INVALIDATED ・RETIRED ・無効の条件 ・支持 ／ 反証の根拠）
- P8 read-only handoff（完了した run の再構成 ・no-network ・no-credential ・no-write ・`run_id` ＋ `screen_result_id` の結び付き ・drift は
  `P8_RESULT_DRIFT`）
- safe projection（件数だけ）
- point-in-time reconstruction（時点 T ＝ `reviewed_at <= T` の最大の seq）
- stale-head fail-closed behavior（人が審査した先頭に結び付く ・古い先頭は `STALE_AUTHORITY_HEAD` ・同じ入力の再試行は `REUSED`）

## 2. 実 data の検証（集計だけ）

P9-A5: 完了した P8 の run の read-only の再構成（COMPLETE）・J-Quants の request 0 ・credential なし ・Watchlist の作成 1 件が
`APPENDED` ・同じ入力の再試行が `REUSED` ・安全な投影の ACTIVE ＝ 1 ・Thesis ＝ 0 ・store の再読み込み PASS ・時点の再構成 PASS ・P8 の
root の read-only の確認 PASS。実の発行体 ・code ・id ・瞬間 ・理由の文 ・authority の JSON ・private root の内容は本 repo に記録しない。
Thesis の実 data の作成は意図して行わない（Thesis は別の実 data の取り込みの経路を持たず、合成の test が網羅する）。

## 3. Phase 9 から明示に除外したもの

- ranking
- score
- recommendation
- target price
- expected return
- portfolio allocation
- position sizing
- trading action
- public output
- LLM authority
- P5 feedback

## 4. 延期（非 blocking）

- P6 Theme references
- P7 Narrative references
- A2 observation evidence references
- LLM text proposals
- machine-checkable invalidation conditions
- security-level watch
- tags / categories
- P8 result sealing
- whole-file hash chain
- thesis diffing
- repo CLI for candidate listing / decision generation
- real MANUAL / update / Thesis validation
- I1 multi-day identity continuity
- J-Quants terms review for LLM / public use

## 5. Phase 10 への境界

- Phase 10 は Phase 9 を **read-only** で消費する。
- Phase 10 は `AuthorityStores` を下流の interface として直接使わない（追記の API を持つため。P9-OBS-019）。**専用の read-only の
  Phase 9 の adapter** が要る。
- 個人の profile ・好み ・保有 ・建玉の文脈は Phase 10 が持つ。
- Phase 10 は P9 ・P8 の authority を変えない。

## 6. 観察の訂正（P9-OBS-018）

閉じた A1 の契約の文書（`PHASE9_A1_P8_HANDOFF_CONTRACT.md`）の登録の数の行（runtime 3 ・test 3 ・文書 1）は A1 の時点の値で、
凍結の時点では runtime 18 ・test 6 ・文書 5（本文書を含む）。閉じた A1 の文書は書き換えず、ここに訂正を記録する。

## 7. 変更の規則

凍結の Phase 9 の file の変更は、監督が承認した狭い再開（narrow reopening）だけ。
