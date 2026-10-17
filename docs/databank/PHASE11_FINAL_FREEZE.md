# PHASE 11 — PERSONAL UI (PRIVATE LOCAL PWA) v1: COMPLETE / CLOSED / FROZEN

Phase 11 の最終凍結の記録（P11-A6 final audit / freeze）。本文書 ・registry ・guard ・CHANGELOG だけの記録であり、runtime の意味は
変えない。この記録の commit は **新しい anchor ではない**。

| 項目 | 値 |
|---|---|
| 状態 | **COMPLETE / CLOSED / FROZEN** |
| 意味 ／ runtime の凍結 anchor | `43c0b856d41efed397de213a1a06178c5e97ab10`（registry の `P11_A5`。P11-A5 の Windows の移植性の follow-up の commit） |
| 凍結の範囲 | P11-A0 〜 P11-A5 の実装 ／ runtime（登録済みの runtime 12 file ＝ .py 4 ＋ static な asset 8 ・Phase 11 の test ・設計文書） |
| 実機の検証 | P11-A5 real Windows local validation（Edge ・DevTools protocol の自動検証）: **A5_PASS**（手動の y/n の証拠には依らない） |
| 最終監査 | P11-A6 final audit: **P11_FINAL_AUDIT_PASS** |
| 受理した観察 | P11-OBS-001 〜 P11-OBS-075 |
| Phase 10 | COMPLETE / CLOSED / FROZEN のまま（`1a7b9a2…`。runtime 17 file は object 一致） |
| Phase 9 ／ Phase 8 | COMPLETE / CLOSED / FROZEN のまま（`4c19701…` 18 file ・`0a32d86…` 54 file は object 一致） |
| 公開の面 | GitHub Pages ・公開の report ・Cloudflare ・notifier は `P11_BASE`（`d01f6bc…`）以後も不変 |

guard: `tests/intelligence/test_personal_ui_boundary.py` の
`test_p11_freeze_the_12_registered_runtime_files_are_object_identical_to_the_anchor` と
`test_p11_freeze_the_record_holds_no_private_validation_values`（§7）。

---

## 1. anchor と記録の関係

- `P11_A5`（`43c0b85…`）で Phase 11 v1 の runtime は完了した。A1 の runtime 3 file は `P11_A1`（`da80675…`）以後 object 一致のまま。
  A2 〜 A4 の runtime と static な asset は A5 の Windows の移植性の 2 commit（`a10686d…` ・`43c0b85…`。server の閉じ方だけ）を経て
  `43c0b85…` で確定した。
- 本記録の commit は文書 ・registry の定数 ・guard ・CHANGELOG だけを足す。runtime 12 file の git の blob は anchor と同じ（guard が pin）。
- P11-A5 の helper（repo 外。`transfer/p11-a5-helper-v2` の transfer 専用 branch）は runtime の凍結の一部ではない。

## 2. 凍結した範囲（v1）

- 凍結の Phase 10 の governed な read の面（`read_personal_review` ・`personal_safe_projection` ・`read_p9_safe_view`）だけを import する
  read-only の adapter と UI model（id ・note ・除外の理由 ・著者 ・revision は無い。件数 ・code ・日付だけ）
- loopback（127.0.0.1）だけの local server（Host ・Origin ・Sec-Fetch-Site の完全一致 ・CORS 無し ・cookie 無し ・log 無し ・
  決定論の header ・資格情報があれば起動を拒む ・static の allowlist ・応答を書いた後の有界な読み捨て）
- static な PWA の shell（vanilla HTML ／ CSS ／ JS ・CSP は `'self'` だけ ・shell だけの service worker ・`/api/` は cache しない ・
  browser は何も保存しない ・時点は人が明示に入れる ・失敗の全てで private な model を DOM と memory から消す）
- A4 の硬化（応答の表示 schema の検査 ・10 秒の中止 ・Windows の移植性）

## 3. 不変量（最終監査で再確認）

loopback だけ ／ Host ・Origin ・Fetch Metadata の厳密な規則 ／ CORS 無し ／ browser の永続化に private な data 無し（localStorage ・
sessionStorage ・IndexedDB 空 ・app origin の cookie 無し ・server は Set-Cookie を出さない）／ Cache Storage は shell の経路だけ ・`/api`
は無い ／ offline で shell は出て private な data は出ない ／ server が無い時は古い行が消える ／ 再起動の後の明示の読み込みは同じ
ENTRY_COUNT ／ DOM に private な token 無し ／ page の通信は loopback だけ ／ 外への通信ゼロ ／ P9 ・P10 の root は read-only ／
検証の間 repo は不変 ／ 再起動を跨いで応答は同一 ／ 明示の時点 ・時計の暗黙の権威は無い ／ P10 の store を直接 import しない ／
書き込み無し。

## 4. P11-A5 の証拠（Windows の実機）

preflight ・read ・server ・browser（`BROWSER_PATH=cdp:edge`）・storage ・offline ・restart ・verify の全てが PASS。browser の不変量は
DevTools protocol で自動に検証した（手動の y/n の答えは証拠として使わない）。browser の vendor 自身の cookie（app origin ではない）は
明示に範囲外とし、件数と属性（値は無し）だけを private な log に残す。

## 5. 観察 ・残る負債（凍結を妨げない）

- P11-OBS-070: 凍結の P7 〜 P9 の test の `subprocess.run(text=True)` は locale の復号に依存する。Windows では helper の環境
  （`PYTHONUTF8=1`）で補正。test の byte は不変（別の gate で test だけの移植性の修正を検討）。
- P11-OBS-071: Windows の Winsock は未読の受信 data が残る close を RST にする。server は body を宣言して読み切っていない接続だけ
  有界に読み捨ててから閉じる（`43c0b85…`）。
- P11-OBS-072: browser の vendor の cookie は fresh な profile にも入る。P11 の不変量は app origin の cookie が無いこと。
- P11-OBS-073: Phase 11 v1 は read-only。P11.1 で書き込みを足す時は別の write の脅威の審査（CSRF ・同意 ・冪等性）が要る。
- P11-OBS-074: 完全に侵害された OS ／ browser の profile は P11 の守る範囲の外（受け入れた境界）。
- P11-OBS-075: PWA の install prompt と見た目の品質は機械で検証していない（不変量ではない）。
- 以前からの観察（P11-OBS-001 〜 069）はそのまま引き継ぐ。P11-OBS-002 は凍結を妨げないので再開しない。

## 6. 次

Phase 12 は未着手。Phase 11 の runtime の変更は、新しい gate と anchor の再設定が無い限り行わない。

## 7. guard

- `P11_A5` が正確 ・HEAD の祖先 ・`P11_A1` 〜 `P11_A3` ・`P11_BASE` の子孫。
- 登録済みの runtime はちょうど 12 file（.py 4 ＋ static 8）・全て anchor に在る ・anchor の package の file の集合 ＝ 登録。
- 12 file の git の blob の id が anchor ・index ・worktree で全て同じ（locale ・checkout の改行に依らない）。
- anchor 以後に Phase 11 の package は変わっていない。本文書は anchor の後に足された。
- 本文書に private な値の形（id の接頭辞 ・発行体 ・5 桁の code ・著者 ・瞬間 ・Windows の path ・validation の profile の文）は無い。
