# PHASE 8 — SCREENER INTELLIGENCE v1: COMPLETE / CLOSED / FROZEN

Phase 8 の最終凍結の記録（P8-FREEZE-RECORD）。本文書 ・registry ・guard だけの記録であり、runtime の意味は変えない。
この記録の commit は **新しい anchor ではない**。

| 項目 | 値 |
|---|---|
| 状態 | **COMPLETE / CLOSED / FROZEN** |
| 意味 ／ runtime の凍結 anchor | `0a32d86bd80d0f9a0b9f4cecbd7c961a93dfa15f`（registry の `P8_B5C`） |
| 凍結の範囲 | P8-A0 〜 P8-B5C（登録済みの runtime 54 file ・Phase 8 の test ・Phase 8 の設計文書） |
| 実 data の検証 | P8-B5D real multi-issuer validation: **PASS / CLOSED** |
| 最終監査 | P8-B5E final audit: **P8_FINAL_AUDIT_PASS** |
| 受理した観察 | P8-OBS-001 〜 P8-OBS-138 |
| full pytest（anchor の時点） | 6599 passed ／ 2 skipped |

guard: `tests/intelligence/test_screener_intelligence_boundary.py` の
`test_p8_freeze_the_54_registered_runtime_files_are_byte_identical_to_the_b5c_freeze_anchor` が、登録済みの runtime 54 file
（package の 51 ＋ package の外の runner 3）が anchor と byte 一致し、anchor の package の file の集合が登録と一致することを pin する。

---

## 1. 意味（v1）

- private（本人の private root だけ）
- local（本人の環境だけ。cron ・scheduler ・自動化は無い）
- deterministic（内容 address の id ・正準の JSON ・宣言の順は非意味）
- single authority day（identity の審査 ・取得 ・評価は 1 つの D0。日をまたぐ継続は fail closed）
- human-reviewed Universe（B5A。明示の code の有限の集合 ・版つき）
- human-reviewed Criteria Policy（B3。正確な選択 ・既定 ／ 最新 ／ fallback は無い）
- typed full result set（B5B。全 member に型つきの結果 ・実行の完全性 ・data の完全性 ・MATCH の部分集合は単独で出さない）
- safe projection only（件数 ・状態 ・規則の版だけ。発行体 ・code ・値 ・閾値 ・意図 ・著者 ・path は欄が無い）

## 2. 実 data の検証（集計だけ）

P8-B5D（新しい private root ・同じ D0）: 2 発行体 ・2 member ・B5C の 1 回の呼び出しで 3 request（master 1 ＋ fins 2）・
`COMPLETE` ・`EVALUATED` x2 ・data の完全性 `COMPLETE` x2 ・Screener の状態は型つき（MATCH は要求しない）・
0 request の再構成で安全な投影が同一。identity の bootstrap は別の前提の request（3）。
実の発行体 ・code ・id ・digest ・瞬間 ・閾値 ・財務の値は本 repo に記録しない。

## 3. Phase 8 から明示に除外したもの

- ranking
- universal score
- recommendation
- watchlist
- thesis
- Theme exposure
- public output
- LLM handling of J-Quants-derived data
- P5 feedback

P4 ・P6 ・P7 は read-only のまま、P5 は feedback から除外のまま。

## 4. 延期（非 blocking）

- I1 multi-day identity continuity
- Theme exposure
- extra metrics
- public output
- identity onboarding at scale
- policy-authoring CLI
- result diffing
- paste-safe report mode
- read-only result reconstruction adapter
- J-Quants terms review for future publication / LLM use

## 5. Phase 9 への引き渡し

- Phase 9 は Phase 8 を **read-only** で消費する。
- watchlist ／ thesis の状態は Phase 9 が持つ。
- Phase 9 は Phase 8 の authority（identity ・観測 ・保持 ・Universe ・方針 ・台帳）に書き戻さない。
- Phase 9 の実装の前に、**no-network ／ no-credential の結果の再構成の経路**（既存の run の台帳 ＋ authority の store → 凍結
  B4A ・B5B）を設計する。
- J-Quants の規約の確認は、公開 ・LLM による派生 data の扱いの前提条件。

## 6. 変更の規則

凍結の Phase 8 の file の変更は、監督が承認した狭い再開（narrow reopening）だけ。
