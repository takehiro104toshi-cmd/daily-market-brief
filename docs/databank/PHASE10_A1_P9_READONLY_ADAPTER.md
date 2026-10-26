# PHASE 10 / P10-A1 — REGISTRATION + READ-ONLY P9 ADAPTER

Phase 10（Personal Intelligence）の最初の実装 gate。Phase 10 の登録と、凍結の Phase 9 を read-only で読む専用の adapter だけを足す。
**Phase 10 の凍結ではない。** 個人の profile ・FOCUS ／ MUTE（P10-A2 の意味）・個人の store ・実行器 ・個人の見直しの列 ・保有
（Phase 10.1）・通知 ・LLM（v1 では除外）・PWA ・自動化は無い。

- 基準: `P10_BASE` ＝ P9 の凍結の記録の commit `3bfc76c6b2f76f613bb50710e6e7eb976a642326`。
- Phase 9 は凍結のまま（anchor `4c1970174f678245b569fdbb812a8a6ced52410b` ・runtime 18 file は byte 一致）。P8 ・P7 も不変。
- 受理した観察: P10-OBS-001 〜 P10-OBS-010（P10-A0）。

## 1. package ・private root

- package: `src/intelligence/personal_intelligence/`（`__init__.py` ・`p9_view.py`）。production runtime closure の外。
- private root の規約: `<caller が明示に渡す P10 の root>/personal_intelligence/`（A1 では使わない ・作らない）。P8 ・P9 の root と
  構造的に別。

## 2. 登録（test だけの狭い再開）

- `tests/intelligence/phase10_runtime_registry.py`: runtime 2 ・test 3 ・文書 1 の完全な一覧 ・`P10_BASE` ・Phase 9 の importer の
  一覧 `SANCTIONED_P10_P9_IMPORTERS`（完全な path → import の面）。
- 凍結の P7 ／ P8 ／ P9 の test の guard 4 file に、Phase 10 の runtime ・test ・文書 ・`p9_view` の importer の許可を足した。行は
  `PHASE10_TEST_REGISTRATION` に完全に列挙し、Phase 10 の guard が `P10_BASE` との差分の完全一致を pin する。
- P9 の登録の pin は P9 の終わり（`P10_BASE`）まで（P9 の guard の比較の「現在」を `P10_BASE` の内容にした）。以後の差は Phase 10 の
  guard が pin する（P8 → P9 と同じ合成）。P8 ／ P9 の registry は不変。
- 一般の許可（「`personal_intelligence` の下は何でも可」）は無い。

## 3. adapter（`p9_view.py`。P9-OBS-019 ・P10-OBS-002 ・P10-OBS-003）

凍結 P9 の import の面（完全一致）: `watch_store.WatchlistStore` ・`thesis_store.ThesisStore`（`open` だけ）・`cross_rules.check_world` ・
`projection.safe_projection` ・`store_io.AuthorityStoreError` ・`revision_model.SemanticModelError`。`AuthorityStores` ・`initialize` ・
`_append_line` ・実行器 ・local の入口 ・P8 ・J-Quants ・network ・credential は無い。

- 両方の store を `open(p9_root)` だけで開く（作らない ・無ければ `P9_STORE_UNAVAILABLE`。破損も同じ ・修復しない）。
- 凍結の `check_world` を両方の全ての鎖で呼ぶ（違えば `P9_WORLD_INVALID`）。不変条件は複製しない。
- store の object は関数の中の read-only の像（`_ReadOnlyWorld`。公開しない）だけで、返り値は Phase 10 が持つ不変の型（凍結の
  dataclass ・tuple ・文字列 ・数 ・日）だけ。
- 明示の aware な `at` ・日 `as_of_date` だけ（時計 ・最新 ・現在なし）。凍結 P9 の時点の意味（`reviewed_at <= T` の最大の seq）。

### 3.1 `read_p9_safe_view(p9_root, *, at, as_of_date) -> P9SafeView`（既定）

凍結 P9 の安全な投影（件数だけ）を不変の型に写す: `as_of_date` ・Watchlist の数 ・状態 ・出所の種類 ・見直しの日が来た数 ・宣言した
Thesis の link の数 ・Thesis の数 ・状態 ・見直しの日が来た数 ・無効の根拠 ・支持 ／ 反証の根拠の種類（件数は `(key, count)` の tuple）。
発行体 ・P9 の id ・文 ・run ／ 結果の id ・著者 ・瞬間は無い。

### 3.2 `read_p9_private_snapshot(p9_root, *, at) -> P9PrivateSnapshot`（private ・local だけ）

時点 T の各 root の最小の状態（root の id の文字の順 ・非意味）:
- `P9WatchState`: `watch_entry_id` ・先頭の `revision_id` ・`issuer_id` ・`status` ・`review_due_on` ・`provenance_kind`。
- `P9ThesisState`: `thesis_id` ・先頭の `revision_id` ・`watch_entry_id` ・`status` ・`review_due_on`。

理由 ・主張 ・根拠 ・run ／ 結果 ／ 提案の id ・著者 ・瞬間は入れない（P10-A2 の見直しの列 ・FOCUS ／ MUTE ・除外に要る最小）。凍結 P9 の
revision の object は返さない。

## 4. 合成の証拠

`tests/intelligence/test_personal_intelligence_p9_view.py`: 安全な view ・private な snapshot ・時点（前 ・ちょうど ・後）・明示の瞬間 ／
日 ・無い root ／ file を作らずに fail closed ・Watchlist ／ Thesis の store の破損 ・記録をまたぐ世界の違反 ・store の object ／ 追記 ／
作成の面が出ない ・不変 ・決定論。読み込みの間は credential なし ・socket ／ HTTP ・P9 の store の作成 ／ 追記 ・`AuthorityStores` を罠にし、
P9 の root の byte の不変を確かめる。

`tests/intelligence/test_personal_intelligence_boundary.py`: registry の完全一致 ・`P10_BASE` 以後の面 ・凍結の test の差分の pin ・
P9 ／ P8 ／ P7 runtime の byte 一致 ・import の面の完全一致 ・書き込み ／ 時計 ／ 環境変数なし ・production の外 ・語彙。
