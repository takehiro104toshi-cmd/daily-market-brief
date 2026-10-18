# PHASE 13 — A1: REVIEW STATE MEMORY PURE MODEL（純粋な model ・store ・adapter は無い）

Phase 13 の最初の runtime: Review State Memory の **純粋な決定論の model**（P12.5-A0 ・A2 ・design closeout の契約の実装の第一段）。
入力は P10 の governed な view と同じ形の **合成の入力**だけで、**凍結の package を import しない**（importer の許可は無い。P10 の governed な
adapter は P13-A2a の別の gate）。file ・環境 ・時計 ・socket ・process ・乱数 ・network に触れない。store ・永続化 ・manifest は無い（A3 以後）。
Obsidian ・投影は無い（A4）。B-track は HOLD ・P14 は未着手。

| 項目 | 値 |
|---|---|
| 状態 | **P13-A1 implemented（pure model）**。P13 全体は未完 |
| runtime（登録 ・認可: gate `P13-A1` ・anchor `4d464c30e4598d2ad5a0cee5a34ac366414fbde3` ＝ P13-A0 の commit） | `src/intelligence/market_memory/__init__.py` ・`src/intelligence/market_memory/canonical.py` ・`src/intelligence/market_memory/review_state_sample.py` ・`src/intelligence/market_memory/review_state_change.py`（stdlib だけ） |
| schema | `p13_review_state_sample:0.1.0` ・`p13_review_state_change:0.1.0` |
| id | 完全な sha256（64 hex）が識別。`p13smp_` ・`p13chg_` ＋ 先頭 24 hex は **略記**で、別の digest が同じ略記なら fail closed（`SHORT_ID_COLLISION`） |
| guard | `tests/intelligence/test_market_memory_boundary.py`（登録 ・認可 ・digest ・import ・語彙 ・private の形）・`test_market_memory_model.py`（合成の世界の正 ・負） |
| 凍結 | Phase 4 〜 12 の runtime ・P12.5 の設計の契約は不変 ・object 一致 |

## 1. model（A2 §7 の意味の型）

- **`SampleCutoff`**: 明示の aware な `at`（UTC に正準化）と明示の `as_of_date`（`date`。`at` から導かない ・`datetime` は拒む）。
- **`SourceViewIdentity`**: 標本を作った governed な view の schema ／ rules の version（文字をそのまま運ぶ）。
- **`ReviewStateEntry`**: 見直しの 1 行の構造の欄（`record_kind` ・`p9_root_id` ・`p9_revision_id` ・`issuer_id` ・`linked_watch_entry_id` ・
  `p9_status` ・`p9_provenance_kind` ・`review_due_on` ・`due_class` ・`attention` ・`excluded_by_profile` ・`surface_group`）。view の形の規則
  （watch は発行体 ・出所を持ち link は無い ／ thesis は link を持ち出所は無い ・表示の組と印 ・期日と区分の整合）を検査する。
- **`ReviewStateCounts`**: 見直しの view の件数 ＋ 凍結 P9 の安全な投影（`P9SafeCounts`）＋ 個人の安全な投影の 13 の整数。**実際の意味で検算**する:
  項目数 ・期日の区分ごとの数 ・印の数 ・除外の数 ・印の分割（FOCUS ＋ MUTE ＋ unmatched ＝ live の印）・P9 の root の数 ・状態 ／ 出所の分布 ・
  見直しの期日（`as_of_date` 以前）・profile 無しの窓は 0。矛盾は INTEGRITY_FAILURE。
- **`ReviewStateSample`**: `cutoff` ・`view_identity` ・`entries`（(`record_kind`, `p9_root_id`) で sort ・重複無し）・`counts` ・`rules_version` ・
  `provenance_class`（`P10_GOVERNED_VIEW_SAMPLE_NO_SOURCE_KNOWN_AT_NO_P10_REVISION_DIGEST`）・`authority_class`（DERIVED）。
  `sample_digest` ＝ `sha256("p13.review_state_sample.v1" + NUL + canonical_json(content))`。
- **`SampleEvidence`**: telemetry（`sampled_at` ・`build_ref`）。identity ・内容 ・PIT の判定に使わない。**known_at ではない**。
- **`SampleOutcome`**: SAMPLED ／ MISSING（source が無い: `P10_STORE_UNAVAILABLE` ・`P9_UNAVAILABLE`）／ INTEGRITY_FAILURE（壊れている ・矛盾 ・
  未知の code は fail closed）。失敗に部分の標本は無い。**空の標本**（有効で項目 0）は MISSING と区別する。
- **`StalenessLabel`**: 人が宣言した窓（日）による FRESH ／ STALE ／ UNDETERMINED の label。trigger ではない。
- **`PitState`**: KNOWN ／ UNKNOWN ／ UNCERTAIN ／ AMBIGUOUS の予約（将来の `MemoryItem` の族のため）。P9 ／ P10 の標本の経路は出さない。
- **`build_digest`**: 明示の順序つきの cutoff の集合 ・view の identity ・規則の version ・任意の入力の記述子からの build の identity。
  永続化 ・manifest は無い。決定論の identity は source の不変を証明しない。
- **`ReviewStateChange`**: 2 標本の **端点の差**（APPEARED ／ DISAPPEARED ／ CHANGED ・`changed_fields` は構造の欄だけ ・区間 (T1, T2] ・
  両端の完全な digest）。`interpretation` は固定の定数（transition の時刻 ・回数ではない）。同じ端点は記録を生まない ＝ **変化の不在の
  証明ではない**（`ENDPOINT_MATCH_IS_NOT_PROOF_OF_NO_CHANGE`）。view の identity ・規則の version が違う ・`at` が厳密に増えない標本は比べない。

## 2. 捏造しないもの

source の `known_at` ・`reviewed_at` ・P10 の revision の id ／ digest ・transition の瞬間 ・「変化なし」。schema にそれらの欄は無く
（`FORBIDDEN_FIELD_NAMES` が pin）、`changed_fields` に非構造の欄は入らない。

## 3. 境界

凍結の package を import しない（guard: 相対 import は package 内だけ ・stdlib の許可は `dataclasses` ・`datetime` ・`enum` ・`hashlib` ・
`json` ・`re` ・`typing` ・P12 と同じ名前 ・語彙の禁止 ・private の形の禁止 ・本番の閉包の外）。importer の許可は無い（P13-A2a）。
provider の本文 ・値 ・note ・著者 ・path ・資格情報は型として存在しない。

## 4. 試験（合成の世界）

正準 JSON ・独立の sha256 の再計算 ・round trip ・項目の順序に依らない identity ・telemetry の独立 ・naive な瞬間 ／ `datetime` の日の拒否 ・
strict な欄と private の形 ・件数の検算と改竄の INTEGRITY_FAILURE ・`as_of_date` の不一致 ・MISSING ／ INTEGRITY_FAILURE ／ 空の標本の区別 ・
鮮度の label ・予約語の不在 ・build の identity ・略記 id の衝突 ・変化の検出（APPEARED ／ DISAPPEARED ／ CHANGED ・欄の差）・往復した世界で
端点一致 → 記録無し ・identity ／ 規則 ／ 順序の不一致の拒否 ・非構造の欄 ・時刻の捏造の拒否。

## 5. 次（監督の個別の GO を要する）

P13-A2a governed な P10 の adapter と importer の登録 → A3 store ／ rebuild → A4 projection → A5 実機 → A6 freeze。
