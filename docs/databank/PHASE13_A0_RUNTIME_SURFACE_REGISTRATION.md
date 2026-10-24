# PHASE 13 — A0: RUNTIME SURFACE REGISTRATION（登録だけ ・runtime は無い ・実装ではない）

Phase 13（Market Memory ／ Review State Memory）の最初の gate。**P13 の `src/` の file は 1 つも足さない**（package も `__init__` も無い）。
足すのは、凍結の Phase 7 〜 12 の boundary test が `src/` の面の完全一致を要するために必要な **test だけの登録の仕組み**と、本記録 ・CHANGELOG
だけ。P13-A1（純粋な memory の model）・P13-A2a（P10 の governed な面の importer の許可）・以後の gate は、それぞれ監督の個別の GO を要する。
本記録は実装ではない ・実装を承認しない。

| 項目 | 値 |
|---|---|
| 状態 | **REGISTRATION ONLY（P13-A0 runtime surface registration）**。`PHASE13_RUNTIME` は **空** ・P13 の package は存在しない |
| P13_BASE | `aded7ee8621e9abac18d313009444675ab771ae6`（P12.5 の設計の closeout の記録の commit。登録はここから足す ・固定 ・A0 の commit ではない） |
| 登録 | `tests/intelligence/phase13_runtime_registry.py`（`PHASE13_RUNTIME = ()` ・`PHASE13_RUNTIME_AUTHORIZATION = ()` ・`PHASE13_TESTS` ・`PHASE13_DOCS` ・`PHASE13_TEST_REGISTRATION` ・`is_phase13_addition` ・`only_phase13_registration`） |
| guard | `tests/intelligence/test_market_memory_boundary.py`（registry の digest ・src の面 ・凍結の test の狭い再開の完全一致 ・blob ・package の不在 ・negative control） |
| importer | **importer の許可は無い**。P13 が凍結の package を import する許可は別の gate（P13-A2a）。textual な import の禁止（P8 〜 P12 の package 名）は全て不変 |
| 凍結 | Phase 4 〜 11 ・Phase 12 A-track v1（`e390cdd…` ・`3056e25…`）・P12.5 の設計の契約（`P12_5_DESIGN_ANCHOR`）は不変 ・object 一致。B-track は HOLD ・P14 は未着手 |

## 1. なぜ登録が要るか（P12.5-A3 ・P13-A0 の調査）

凍結の P7 〜 P12 の boundary test は、各 phase の base 以後の `src/` の変更の集合が「登録済みの runtime の追加の集合」と **完全に一致**することを
要する（例: P12 の guard の `_changes(P12_BASE, "src") == {A: PHASE12_RUNTIME}`、P8 の guard の `SURFACE` の差の集合、P7 の
`PHASE7_EXCLUDED_PATHSPECS` を使う Phase 6 の試験）。従って P13 の `src/` の file は、純粋な model であっても、これらの集合に `PHASE13_RUNTIME`
を足す登録無しには 1 つも置けない。P12-A1 は同じ理由で `PHASE12_TEST_REGISTRATION`（7 file の行の完全一致）を導入した。P13-A0 はその様式を
そのまま踏む。

## 2. 登録の仕組み

- `P13_BASE` は固定（上の表）。`PHASE13_RUNTIME` は空の tuple。`is_phase13_addition(status, path)` は登録済みの path の追加（`A` ／ `??`）だけを
  認め、修正（M）・未登録の path ・近い名前 ・package の外は認めない（**修正は決して認めない**）。
- `PHASE13_TEST_REGISTRATION` は凍結の 7 file（P7 の registry ・P7 ／ P8 ／ P9 ／ P10 ／ P11 ／ P12 の boundary test）に入れた行を取り除いた行 ・
  加えた行として完全に列挙し、`only_phase13_registration` が `P13_BASE` との差分の完全一致を確かめる。加えた行は: `PHASE13_RUNTIME` ／
  `PHASE13_TESTS` ／ `PHASE13_DOCS` を src ／ tests ／ docs の面の集合に足す行、`is_phase13_addition` を pending の filter に足す行、
  P12 の登録の検査を `P13_BASE` の snapshot に pin し直す行（P12 が P11 に行ったのと同じ）、P12 の凍結と P12.5 の closeout の「src は不変」を
  「登録した P13 の追加だけ」に狭める行。**importer の test（`*_no_other_code_imports_it`）には触れない**（guard が pin する）。
- **registry の drift の防止**: `test_market_memory_boundary.py` が `PHASE13_RUNTIME` ・`PHASE13_RUNTIME_AUTHORIZATION` ・`PHASE13_TESTS` ・
  `PHASE13_DOCS` ・package ・base の正準 digest を定数として持つ。runtime を足すには registry と guard の定数と gate の文書の 3 つを同時に、
  監督の gate で変える。tuple に path を足すだけでは落ちる。
- **認可の束縛**: 将来の runtime の path は `PHASE13_RUNTIME_AUTHORIZATION` にちょうど 1 つ（gate の id ・その gate の anchor の commit ・path ・
  契約文書）として現れ、anchor は HEAD の祖先、path は anchor に存在せず、文書に path が書かれていなければならない。A0 では空集合。

## 3. 歴史の保存

- P12 A-track v1 の凍結（`P12_VALIDATED_TREE` 以後の `src` 不変）と P12.5 の設計の closeout（`P12_A6` 以後の `src` 不変 ・P13 の package の不在）は、
  「登録した P13 の追加だけ」を許す形に狭めた。**P12.5 の設計の closeout の anchor（`P12_5_DESIGN_ANCHOR`）・`P13_BASE` に P13 の runtime が
  無かった**という歴史の事実は、その snapshot の `ls-tree` で引き続き pin する（将来 P13 の file が認められても成り立つ）。
- P8 〜 P12 の runtime の blob は anchor と object 一致。P12.5 の契約（A0 ・A2）の blob は設計の anchor と一致。

## 4. negative control（guard が示す）

未登録の path（`__init__` を含む）・修正 ・近い名前（`market_memory2` ・`market_memory_model.py`）・凍結の runtime の path は `is_phase13_addition`
で落ちる。登録の行の改変 ・欠落 ・未登録の追加は `only_phase13_registration` で落ちる。runtime を 1 つ足した registry の digest は定数と一致しない。
禁止の token（凍結の package 名）を含む code は走査で落ちる（A0 では走査の対象は空）。P13 の package は今 ・`P13_BASE` ・設計の anchor の
いずれにも無い。

## 5. 次（監督の個別の GO を要する）

P13-A1 純粋な Review State Memory の model（合成の入力 ・stdlib だけ ・凍結の package を import しない ・`PHASE13_RUNTIME_AUTHORIZATION` に登録）
→ P13-A2a governed な P10 の adapter と importer の登録 → A3 → A4 → A5 → A6。B-track は HOLD ・P14 は未着手。
