# PHASE 8 / P8-ST1 — SEMANTIC METADATA + HELD OBSERVATION STORES（運用 store）

P8-A3R の設計（§9 ・§10）のうち、実データの adapter ・executor の**前に要る 2 つの追記専用の運用 store** だけを実装した gate。
監督の決定 D1〜D8（P8-A3R ＝ PASS ／ CLOSED ／ FROZEN `f1c4a4e`）に従う。合成 data だけ。J-Quants の API ・adapter ・executor ・identity
の登録 ・実データの pilot は無い。

- 基準: P8-A3R `f1c4a4e86c51b1668b9be41d6ceff06440e29608`（凍結。runtime 16 module）。full pytest の基準 5546 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・財務の実の値を載せない。

---

## 0. 結論

1. 追加した runtime は 3 module: `semantic_metadata_store`（A2R の注記の運用 store）、`held_observation_model`（保留の観測の record）、
   `held_observation_store`（保留の観測の運用 store）。A1 ・A2 ・A1R ・A2R ・A3A ・A3B の 16 module は byte 一致。
2. authority の class: 注記 ＝ **`SEMANTIC_METADATA_RECORD`**（provider の写しの運用上の metadata。D2）、保留 ＝ **`OPERATIONAL_HOLD_RECORD`**
   （運用 record。D3）。どちらも市場の観測 ・投資の authority ・Production DNA ・Theme の証拠 ・推奨 ・watchlist ではない。severity ・
   score ・順位 ・自動の昇格 ・再試行 ・削除は無い。
3. 注記の store は凍結した A2R の `ObservationSemantics` ・`SemanticMappingProvenance` をそのまま 1 つの journal に置く。同じ
   `observation_id` に内容の違う注記 ／ provenance → `SEMANTICS_CONFLICT` ／ `PROVENANCE_CONFLICT` で拒む（最新 ・先勝ち ・出所で選ばない）。
4. `HeldObservation` は raw の応答 ・credential ・自由文の理由を持てない（欄は参照 ・digest ・閉じた enum ・規則の版だけ。参照の欄は
   文字の集合と長さで本文 ・JSON ・path ・URL を通さない。`raw` ・`payload` ・`response_body` ・`api_response` の欄は無く、渡せば
   `TypeError`）。監督の決定 D6（raw は memory だけ）を record の型で強制する。
5. 時刻は caller が明示に渡す aware な datetime だけ（`observed_at`。省けば None）。時計を読まない。
6. 2 つの store は A2 の観測 ・A1 の identity ・指標 ・公開の出力に触れない（import の境界 ・runtime の閉包 ・file の不在で証明）。
7. P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION** のまま（runtime で解かない。§9）。
8. 判定: **P8_ST1_OPERATIONAL_STORES_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§12）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `f1c4a4e86c51b1668b9be41d6ceff06440e29608`（期待どおり。working tree は clean） |
| 凍結の anchor | A1 `4162e9c` ／ A2 `b686b00` ／ A2R `4d3540c` ／ A3A `84c2d52` ／ A3B `d8845f2` ／ A3R `f1c4a4e`（`src` と A3R の設計の記録）と byte 一致 |
| full pytest の基準 | 5546 passed ／ 2 skipped |

---

## 2. authority の分類

| record | class | 何であるか | 何でないか |
|---|---|---|---|
| `ObservationSemantics` ・`SemanticMappingProvenance`（A2R。store に入る） | `SEMANTIC_METADATA_RECORD` | provider の写しの運用上の metadata。A3 は注記が KNOWN の観測だけを使う | 観測の authority（A2）・投資の authority ・DNA ・Theme ・推奨 |
| `HeldObservation` | `OPERATIONAL_HOLD_RECORD` | 候補が A2 に安全に入れなかった**事実**と閉じた理由 | authority ・severity ・順位 ・score ・投資の解釈 ・再試行の queue |

---

## 3. 注記の store（`semantic_metadata_store`）

| 項目 | 契約 |
|---|---|
| 場所 | `<data_root>/screener_intelligence/semantic_metadata.jsonl`（1 file。A1 ・A2 ・A1R の store と同じ dir、別の file） |
| record | 凍結した A2R の 2 つの record（`record_kind` で区別）。競合する model は作らない |
| identity | A2R の内容 address（`p8sem_` ・`p8map_`）。時計 ・乱数 ・path に依らない |
| append | 正準の行だけ ・write → flush → fsync ・同じ record（byte 一致）は `ALREADY_PRESENT`（冪等）・read-only なら拒否 |
| 受け付けない物 | A2 の観測 ・dict ・文字列 ・bytes ・None → `INVALID_TYPE`（raw を渡す入口が無い） |
| 不変条件（journal） | 1 `observation_id` に注記 1 つ（内容が違う → `SEMANTICS_CONFLICT`）・provenance 1 つ（違う → `PROVENANCE_CONFLICT`）・注記の `mapping_provenance_id` は journal にある同じ観測の provenance（`PROVENANCE_MISSING` ／ `PROVENANCE_MISMATCH`）。provenance を先に append する |
| 衝突の解決 | しない。最新 ・先勝ち ・確度 ・出所の見え方で選ばない。訂正は明示の record（後の gate） |
| 更新 ・削除 | API を持たない |
| 破損 | `STORE_MISSING` ・`INVALID_ENCODING` ・`TRUNCATED_FINAL_LINE` ・`BLANK_LINE` ・`INVALID_RECORD` ・`NON_CANONICAL_LINE` ・`PHYSICAL_DUPLICATE` ・`INVALID_JOURNAL`（disk 上の衝突を含む）で fail closed。読み飛ばさない ・修復しない |
| 外部の変更 | byte 長で検知（`CONCURRENT_MODIFICATION`。single writer） |
| 版 | `STORE_RULES_VERSION = p8_semantic_metadata_store:0.1.0`。record の schema は A2R の `p8_observation_semantics:0.1.0` |
| PIT | 注記は provider の行と写しの規則の版から導ける派生 record で、世界の知識を足さない。解決 ・指標は caller が固定した版の注記を使う。版の更新は本 store の外の明示の訂正 |
| 読み | `semantics_for(observation_id)` ・`provenance_for(observation_id)` ・`records()` ・`canonical_lines()` ・`counts()`・`open_semantic_metadata_journal(data_root)`（read-only） |

## 4. 保留の観測の record（`HeldObservation`）

| 欄 | 型 ・制約 | identity |
|---|---|---|
| `provider` | A1 の `SourceClass`（JQUANTS 等） | 入る |
| `schema_family` | A2R の `SchemaFamily`（`JQUANTS_V2_FINS_SUMMARY`） | 入る |
| `provider_record_ref` | A2 の `source_record_ref` と同じ形（英数と `._:#-`、160 文字まで、credential の印なし）。本文 ・JSON ・空白 ・path ・URL は通らない | 入る |
| `provider_record_digest` | sha256 の 64 hex（小文字） | 入る |
| `reasons` | `HeldReason` の tuple。重複を除き語彙の順（正準）。空は拒否 | 入る |
| `mapping_rule_version` ・`rules_version` | `name:semver` | 入る |
| `issuer_id` ・`security_id` | 省略可。あれば A1 の id の形 | 入る |
| `attempted_field` ・`attempted_statement_basis` | 省略可。A2 の `FundamentalField` ・`StatementBasis` | 入る |
| `observed_at` | 省略可。caller が渡す **aware** な datetime（naive は `NAIVE_DATETIME`）。UTC の ISO で直列化（同じ瞬間なら同じ id） | 入る |
| `audit_note` | 160 文字まで ・1 行 ・credential の印なし。既定は空 | **入らない**（同じ id で違う note は store が `HELD_CONTENT_CONFLICT`） |

- id ＝ `p8hld_` ＋ identity の payload の内容 address。`record_kind = HELD_OBSERVATION`、`schema_version = p8_held_observation:0.1.0`。
- 無い欄: `raw` ・`payload` ・`response_body` ・`api_response` ・`body` ・severity ・priority ・rank ・score。kw_only の frozen dataclass なので
  未知の kw は `TypeError`。
- `from_dict` は未知の欄 ・schema ・kind ・id の改竄 ・理由の順の非正準 ・語彙の外を拒む。

### 4.1 理由の語彙（閉じた 17 値）

| 群 | 値 | 根拠 |
|---|---|---|
| 指示の最低 12 | `IDENTITY_UNRESOLVED` ・`ACCOUNTING_STANDARD_UNKNOWN` ・`ACCOUNTING_STANDARD_UNSUPPORTED` ・`STATEMENT_BASIS_UNKNOWN` ・`DOCTYPE_UNRECOGNIZED` ・`CURRENCY_UNSUPPORTED` ・`CURRENCY_UNKNOWN` ・`PERIOD_UNSUPPORTED` ・`KNOWLEDGE_TIME_INSUFFICIENT` ・`SEMANTIC_CHAIN_CONFLICT` ・`PROVIDER_REVISION_CONFLICT` ・`MAPPING_UNSUPPORTED` | 監督の指示 §6 |
| A3R の設計が要る 5 | `DOCTYPE_OUT_OF_SCOPE`（REIT ・予想の修正の行。§7）・`VALUE_UNPARSEABLE`（数でない token。§7）・`KNOWLEDGE_TIME_INVALID`（DiscDate が不正。§6）・`SEMANTICS_CONFLICT`（注記 store の衝突。§9）・`TERMS_BOUNDARY`（規約の境界で止めた物。§12） | A3R §6 ・§7 ・§9 ・§10 ・§12 |

severity ・priority ・rank ・score ・retry を含む値は無い（test で禁止）。

## 5. 保留の store（`held_observation_store`）

| 項目 | 契約 |
|---|---|
| 場所 | `<data_root>/screener_intelligence/held_observations.jsonl` |
| append | `HeldObservation` だけ（A2 の観測 ・注記 ・dict ・bytes → `INVALID_TYPE`）。正準の行 ・fsync ・同じ record は `ALREADY_PRESENT`・同じ id で内容が違う（`audit_note`）→ `HELD_CONTENT_CONFLICT` |
| 再試行 ・昇格 ・削除 ・更新 | 無い（method の名前にも無いことを test）。保留の解除は後の gate の明示の run と参照 record。同じ候補を別の run で保留すれば `observed_at` の違う別の record |
| 破損 | `STORE_MISSING` ・`INVALID_ENCODING` ・`TRUNCATED_FINAL_LINE` ・`BLANK_LINE` ・`INVALID_RECORD` ・`NON_CANONICAL_LINE` ・`PHYSICAL_DUPLICATE` で fail closed |
| 外部の変更 | byte 長で検知 |
| 読み | `records()` ・`get(record_id)` ・`canonical_lines()` ・`counts()`（理由ごとの件数。順位ではない） |
| 版 | `STORE_RULES_VERSION = p8_held_observation_store:0.1.0` |

---

## 6. raw の data の禁止（監督の決定 D6）

- 2 つの store は record の型でしか受け付けない。A2R の record と `HeldObservation` は値の欄（金額 ・行の本文）を持たない。
- `HeldObservation` の参照の欄は正規表現で本文 ・JSON ・空白 ・path ・URL を拒み、digest は 64 hex だけ。`raw` ・`payload` ・`response_body` ・
  `api_response` ・`body` ・`row` を kw で渡せば `TypeError`、`from_dict` に足せば `UNKNOWN_FIELD`。
- test は dict ・JSON 文字列 ・bytes ・URL ・path を実際に渡して拒否を確かめる。
- module の source に `raw_` ・`payload` ・`response_body` ・`api_response` の語が無い（docstring を除く実行部で検査）。

## 7. 保存の root の方針

- `data_root` は明示の引数（空 ・None は `DATA_ROOT_REQUIRED`）。既定の root ・`INTELLIGENCE_DATA_ROOT` ・`config.yaml` ・絶対の path を
  store は読まない（A1 ・A2 と同じ）。
- 将来の実データは repo の外の private な data root に置く（`data/vnext` は .gitignore 済み。repo の `data/` には作らない。test は
  `tmp_path` だけ）。

## 8. 時刻の方針

- record の identity ・metadata に時計を使わない（`now` ・`utcnow` ・`today` ・`time` は AST で禁止）。
- `observed_at` は caller が渡す aware な datetime だけ。省略可。naive は拒否。
- 注記は不変の `observation_id` に結び付く（A2 の観測の知識の時刻を持たない ・変えない）。

## 9. P8-OBS-58 ・59（利用規約）

| id | 状態 | 帰結 |
|---|---|---|
| P8-OBS-58（継続反復の第三者への提供は私的利用でない） | **BLOCKED_PENDING_TERMS_CONFIRMATION** | ST1 の合成の実装は可 ・private の pilot の設計は可 ・PILOT2 の実行は監督の確認が要る ・公開への統合は別の認可まで禁止 |
| P8-OBS-59（解約 ・downgrade 時の削除） | **BLOCKED_PENDING_TERMS_CONFIRMATION** | 削除の手順は後の gate。ST1 の store は private の root にだけ置く前提 |

runtime で法的 ・規約の判断はしない（`TERMS_BOUNDARY` は「止めた事実」の理由 code であって判断ではない）。

## 10. authority の分離（guard）

- import の境界: 注記の store は `.observation_semantics_model` だけ、保留の model は `.identity_model` ・`.observation_model` ・
  `.observation_semantics_model` だけ、保留の store は `.held_observation_model` だけを使う（指名の名前の完全一致）。A2 ・A1 ・A1R の
  store ・resolver ・履歴 ・A2R の写し ・gate ・指標を import しない。先行の層は ST1 を知らない。
- runtime: 2 つの store を使っても `identity_records.jsonl` ・`observation_records.jsonl` が作られず、A2 の観測を append すれば
  `INVALID_TYPE`。`ObservationStore` ・`IdentityStore` の名前が source に無い。
- 書き込みの面: `__init__`（`ab` ・`mkdir`）と `append`（`ab` ・`write` ・`fsync`）だけ（既存の store の guard を拡張）。
- Pages ・reports ・themes ・narrative ・compass ・market ・jquants の module を import しない（AST）。

---

## 11. 変更したファイル ・test

- `src/intelligence/screener_intelligence/semantic_metadata_store.py`【新規】
- `src/intelligence/screener_intelligence/held_observation_model.py`【新規】
- `src/intelligence/screener_intelligence/held_observation_store.py`【新規】
- `tests/intelligence/test_screener_operational_stores.py`【新規】: matrix A（注記の store: 追記 ・再生 ・同じ内容の再利用 ・基準 ／
  区分 ／ provenance の衝突 ・provenance の先行 ・不正な record ・破損 7 種 ・disk 上の衝突 ・決定論 ・正準 ・float なし）、B（保留の
  model: 全理由 ・複数理由の順 ・identity の参照 ・aware の時刻 ・naive の拒否 ・raw の dict ／ bytes ／ JSON ／ URL ／ path の拒否 ・
  credential の印 ・監査の注記の境界 ・往復 ・改竄）、C（保留の store: 再生 ・同じ id の衝突 ・型 ・破損 6 種 ・決定論 ・再試行 ／ 昇格 ／
  削除の不在）、D（authority の分離 ・root の注入 ・provider の値を持たない）。
- `docs/databank/PHASE8_ST1_OPERATIONAL_STORES.md`【新規】（本書）
- `tests/intelligence/phase8_runtime_registry.py`（3 module ・test ・本書の登録、`PHASE8_ST1_RUNTIME`、anchor `P8_A3R`）
- `tests/intelligence/test_screener_intelligence_boundary.py`（ST1 の import の境界 ・閉包 ・指名の import ・語彙 ・書き込みの面、A3R の
  凍結の guard、先行の guard の除外）
- `CHANGELOG.md`（v5.65）
- 凍結の 16 module ・config ・workflow ・Pages ・main.py ・Phase 4〜7 ・先行の文書は無変更

## 12. adapter ／ executor の前に残る事 ・判定

| 事項 | 状態 |
|---|---|
| P8-ADP0: provider の record の identity ・取り込みの event ・知識の時刻 ・4 欄 ・期間 ・通貨（JP_GAAP だけ。D4）の純関数 | 次の gate |
| P8-EXE: executor（全再導出。D5）。ELIGIBLE → 注記 store → A2 `append`；HOLD → 保留 store | ADP0 の後 |
| P8-ID1: bootstrap の候補 ・審査 manifest（D1） | ADP0 と並行可 |
| 注記の訂正 ・保留の解除の参照 record | 後の gate（ST1 は衝突を拒むだけ） |
| P8-OBS-58 ・59 | 監督の確認（PILOT2 の実行の前提） |

**判定: P8_ST1_OPERATIONAL_STORES_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**

adapter ・executor ・identity の登録 ・実データの pilot ・追加の指標 ・screen ・ranking ・推奨 ・Theme ・公開への統合 ・Phase 9 は行っていない。
