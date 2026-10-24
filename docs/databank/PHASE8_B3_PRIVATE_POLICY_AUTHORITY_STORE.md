# PHASE 8 / P8-B3 — PRIVATE CRITERIA POLICY AUTHORITY STORE（人が審査した方針の private authority）

監督の決定 P8-OBS-63（RESOLVED: PRIVATE AUTHORITY STORE）に基づき、凍結 B1 の `CriteriaPolicy` を包む最小の追記専用 authority record と、
caller が渡す **private の data_root** の下の JSONL store を足す gate。答える問いは「どの正確な screening の方針を ・誰が ・いつ（明示の瞬間）・
どの版 ・どの authority mode で審査したか」だけ。最良の方針 ・最良の閾値 ・魅力 ・買い ・閾値の最適化 ・backtest ・P5 からの学習は答えない。
store は人の決定を記録する。投資の方針を作らない。

- 基準: P8-B2 `8129e953cc1c8886c782857ff9e8010b639893f9`（凍結。runtime 45）。full pytest の基準 6399 passed ／ 2 skipped。
- 本書 ・CHANGELOG ・test ・source は実の閾値 ・実の方針 ・実の著者を載せない。例と test の値は明らかに合成の値（投資の方針ではない）。
- 評価（B2）・Theme（B6）・UniverseSpec ・security への投影（B7）・配線 ・実 request ・LLM は無い。

---

## 0. 凍結の入力と変更なしの層

| 層 | 使う入口 | 変更 |
|---|---|---|
| 凍結 B1 | `CriteriaPolicy` ・`Criterion`（`from_dict` ・`as_dict`）・`ScreenerAuthorityMode` ・`CriteriaComposition` ・`POLICY_SCHEMA_VERSION` ・`ScreenerModelError` | なし（byte 一致） |
| 凍結 B2 | 消費の境界の参照だけ（B3 は評価器を import しない） | なし |
| core | `identity_model.canonical_json` ・`core.time.from_iso` | なし |

## 1. authority record（`screener_policy_authority_model.py`）

| 名前 | 内容 |
|---|---|
| `PolicyAuthorityRecord(policy, authority_class, schema_version, rules_version)` | 凍結 `CriteriaPolicy` を包む frozen dataclass。`record_id` ＝ `policy.policy_id`（第二の identity は作らない）。`policy_key` ・`version` は方針の値の便宜の property |
| `as_dict()` | `{"record_kind": "SCREENER_POLICY_AUTHORITY", "schema_version", "rules_version", "authority_class", "policy": policy.as_dict()}`。方針の dict は B1 の `as_dict`（鍵 ・版 ・著者 ・審査の瞬間（UTC ISO）・意図 ・構成 ・authority mode ・criterion_ids ・criteria の内容 ・policy_id ・schema ・rules） |
| `canonical_line()` | `canonical_json(as_dict()) + "\n"`（sort_keys ・区切りなし ・ensure_ascii=False） |
| `from_dict(data)` → `policy_from_dict(data["policy"])` | 欄の集合は完全一致（欠け ・未知は拒む）。criteria は凍結 `Criterion.from_dict`（criterion_id を検証）、方針は凍結 `CriteriaPolicy(...)` の constructor ・validator を通し、`policy_id` を再計算して保存値と一致、`criterion_ids` の順序も一致を要求。B1 の拒否は `POLICY_INVALID`（内側の code を detail に） |
| `PolicyMetadata` | 人が選ぶための metadata（policy_id ・policy_key ・version ・author_ref ・reviewed_at ・authority_mode ・composition ・criterion_count）。閾値 ・基準の内容は含まない |
| 定数 | `HUMAN_REVIEWED_SCREENING_POLICY` ・`NOT_IMPLIED_BY_AUTHORITY` ・`VERSION_RULE` ・`POLICY_AUTHORITY_SCHEMA_VERSION` ・`POLICY_AUTHORITY_RULES_VERSION`（`p8_screener_policy_authority:0.1.0`） |

B1 が既に持つ欄（policy_key ・version ・author_ref ・reviewed_at ・authority_mode ・composition ・criterion_ids ・policy_id）は複製しない。
record が足すのは record_kind ・schema ・rules ・authority の分類だけ。保存された authority だけで正確な `CriteriaPolicy` を復元 ・検証できる
（可変の外部の設定に依らない）。

### authority の分類

`HUMAN_REVIEWED_SCREENING_POLICY` は「人がこの screening の方針を明示に審査した」だけを意味する。`NOT_IMPLIED_BY_AUTHORITY` が code で
固定する: 本番の投資の推奨 ・検証済みの alpha ・証明された予測の規則 ・Production Compass DNA ・Theme の authority ・watchlist の authority ・
thesis の authority では **ない**。

## 2. store（`screener_policy_authority_store.py`）

path: `<data_root>/screener_intelligence/screener_policy_authority.jsonl`。`data_root` は caller が明示に渡す（空 ・None は
`DATA_ROOT_REQUIRED`）。既定の path ・config.yaml の path ・cwd 相対の暗黙の保存 ・repo の下の journal は無い。

| API | 意味 |
|---|---|
| `initialize(data_root)` ／ `open(data_root, read_only=False)` | 開くたびに全行を凍結 B1 で復元して検査する（fail closed。修復しない） |
| `append(record) -> AppendResult(policy_id, status)` | `APPENDED` ／ `REUSED`（byte 一致）。write → flush → fsync。外部の変更は byte 長で検知（`CONCURRENT_MODIFICATION`） |
| `get_by_policy_id(policy_id)` | 正確な policy_id |
| `get_by_key_version(policy_key, version)` | 正確な (鍵, 版)。版は明示の int（省略 ・推定なし） |
| `list_metadata()` | `PolicyMetadata` の tuple。並びは (policy_key, version, policy_id) の辞書順で、「現在」「推奨」の意味は無い |
| `validate(data_root) -> IntegrityReport(status, record_count, failure_code, line_number)` | OK ／ STORE_MISSING ／ STORE_CORRUPTION。修復しない |
| `records()` ・`canonical_lines()` ・`reload()` ・`verify_unchanged()` | 既存の P8 store と同じ |

**無いもの**: `get_latest_policy` ・current ・active ・default ・最高の版の自動選択 ・reviewed_at による自動選択 ・閾値の検索 ・順位 ・推奨の検索 ・
曖昧な検索 ・delete ・update-in-place ・自動修復 ・truncation ・compaction ・migration ・時計 ・暗黙の reviewed_at。

### append ・REUSED ・衝突

| 条件 | 結果 |
|---|---|
| 同じ policy_id ・byte 一致 | `REUSED`（書かない） |
| 同じ policy_id ・内容が違う | `POLICY_CONTENT_CONFLICT`（fail closed） |
| 同じ (policy_key, version) ・違う policy_id | `POLICY_VERSION_CONFLICT`（fail closed。閾値 ・著者 ・審査の瞬間 ・意図のどれが違っても） |
| read_only ・型違い ・外部の変更 | `READ_ONLY` ・`INVALID_TYPE` ・`CONCURRENT_MODIFICATION` |

### 版の規則（`VERSION_RULE = EXPLICIT_HUMAN_LABEL_UNIQUE_PER_KEY_NO_SEQUENCE_NO_CURRENT`）

| 場合 | v1 の扱い |
|---|---|
| A. 同じ方針の replay | `REUSED` |
| B. 同じ鍵 ・同じ版 ・意味の違う内容 | `POLICY_VERSION_CONFLICT` |
| C. 同じ鍵 ・高い版 | 別に審査された `CriteriaPolicy` として append できる |
| D. 高い版の後の低い版（歴史の backfill） | **許す**。条件: その版が未占有 ・record が単独で妥当 ・reviewed_at が明示。append の順 ＝ 方針の年代の主張はしない（journal の位置は意味を持たない） |
| E. 版の欠番（v1 → v3） | **許す**。版は人の明示の label で、推定された連番の保証ではない |

「現在の方針」の指し手は無い。消費者は正確な `policy_id` か正確な `(policy_key, version)` を要求する。

### journal の fail closed（`CORRUPTION_REASONS`）

STORE_MISSING ・INVALID_ENCODING ・TRUNCATED_FINAL_LINE ・BLANK_LINE ・INVALID_RECORD ・NON_CANONICAL_LINE ・POLICY_INVALID（B1 が復元を拒む）・
POLICY_ID_MISMATCH ・CRITERION_IDS_MISMATCH ・PHYSICAL_DUPLICATE（同じ policy_id の 2 行目。byte 一致でも拒む: append は REUSED で書かないので
正常な journal には現れない）・KEY_VERSION_DUPLICATE。`line_number` を持つ。legacy ・不正な行を黙って受けない。

## 3. 合成の例（投資の方針ではない）

```
{"authority_class":"HUMAN_REVIEWED_SCREENING_POLICY",
 "policy":{"author_ref":"human:synthetic-reviewer","authority_mode":"STRICT_PIT","composition":"ALL_OF",
           "criteria":[{...凍結 B1 の Criterion.as_dict（合成の値）...}],"criterion_ids":["p8crt_…"],
           "intent":"synthetic example","policy_key":"synthetic-example","reviewed_at":"2026-01-01T00:00:00+00:00",
           "rules_version":"p8_screener_semantics:0.1.0","schema_version":"p8_screener_policy:0.1.0","version":1},
 "record_kind":"SCREENER_POLICY_AUTHORITY","rules_version":"p8_screener_policy_authority:0.1.0",
 "schema_version":"p8_screener_policy_authority:0.1.0"}
```

## 4. private ／ public の境界

- journal は private の data_root だけ（repo の下 ・Git 追跡 ・config.yaml ・knowledge/ ・docs/ ・source の定数 ・公開の出力には方針の値を置かない）。
- test は明らかに合成の閾値だけ（test が docs ・CHANGELOG に閾値の値 ・policy_id が無いことを guard）。
- Morning Brief ・Pages ・safe summary への統合は無い。

## 5. 境界（guard）

- 新規 runtime は model ・store の 2 module（P8_B2 anchor と byte 一致の凍結 runtime 45 ・Phase 8 の test ・先行の文書）。registry: `P8_B2` ・
  `PHASE8_B3_RUNTIME`。store は `IO_MODULES`（`__init__`: ab ・mkdir、`append`: ab ・write ・fsync だけ）。
- import は sanctioned の名前だけ。`screener_evaluator` ・A3 ・A3-RA ・保持 ・観測 ・identity の store ・J-Quants ・P5〜P7 ・Theme は無い。
- `screener_criteria` の消費は B2 ・B3 だけ（凍結 B1 の test の消費の行は B3 guard が pin）。

## 6. 観察（監督への報告。変更はしない）

- P8-OBS-72: (policy_key, version) は人の名前空間として足りる（鍵は `^[a-z0-9][a-z0-9_-]{0,63}$`、版は ≥ 1 の int）。ただし鍵は
  author_ref を含まないので、別の著者が同じ鍵 ・同じ版で違う方針を書くと `POLICY_VERSION_CONFLICT` になる（意図どおり fail closed。著者ごとの
  名前空間が要るなら後の governance の決定）。
- P8-OBS-73: author_ref は B1 の文字列（形の検査だけ）。「誰が審査する資格を持つか」の authority（審査者の登録 ・署名）は B3 に無い。B3 は
  「人が審査したと記録された」までを保証する。
- P8-OBS-74: reviewed_at の順序と版の順序は独立（test が v2 の審査が v3 より後の場合を pin）。消費者は版 ・審査の瞬間のどちらでも「新しい」を推定しない。
- P8-OBS-75: byte 一致の重複の行は journal では `PHYSICAL_DUPLICATE` として拒む（append は REUSED で書かないため、重複の行は外部の変更の証拠）。
  許容する案は採らなかった。
- P8-OBS-76: `list_metadata` の並びは (鍵, 版, policy_id) の辞書順。並びの最後が「現在」と読まれる危険は文書 ・docstring ・test で明示した。
  並びを policy_id だけにする案（人の選択が難しくなる）は採らなかった。

## 7. 次の gate（開始しない）

P8-B4 以降。本 gate は評価 ・配線 ・Theme ・UniverseSpec ・security への投影 ・公開の出力を含まない。
