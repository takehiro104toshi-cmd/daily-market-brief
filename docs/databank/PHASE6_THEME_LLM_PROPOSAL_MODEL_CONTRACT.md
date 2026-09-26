# PHASE 6 / P6-B7B — LLM PROPOSAL MODEL / SCHEMA CONTRACT

PURE MODEL ONLY。provider・network・bridge・store・input manifest・PIT 解決・意味検証は実装していない。
module: `src/intelligence/theme_intelligence/llm_proposal_model.py`（flat `llm_*` module、D-B7-4）。
test: `tests/intelligence/test_theme_llm_proposal_model.py`。

前提（B7A で確定した決定 D-B7-1〜12）: 既存 B3 / B5C の proposal authority を再利用し、新しい authority・新しい proposal 型を
作らない。LLM の上限は L1。構造化 JSON を全体単位で拒否する。引用は opaque handle。LLM の provenance は HUMAN / RULE /
SOURCE_CLAIM を名乗れない。時刻は caller 注入。生成の監査 record と proposal authority は分離。実 provider なし。
Compass / DNA / formal review を入れない。B3 は変更しない。

---

## 1. authority の分類

| 型 | 分類 | 永続化（本 gate） | 意味 |
|---|---|---|---|
| `LlmGenerationRequest` | 非 authority（要求の記述） | なし | 呼び出し側が何を頼んだか |
| `LlmGenerationEnvelope` | 非 authority（生成物） | なし | LLM が返した構造化出力の全体 |
| `LlmCandidate` と payload | 非 authority（**下書き**） | なし | 既存 authority 型の材料。proposal でも decision でもない |
| `LlmAbstention` | 非 authority | なし | 有界な棄権理由 |
| `LlmGenerationRecord` | 監査 metadata（Theme authority ではない） | なし（journal store は後続 gate） | 生成 1 回の出来事の記録 |

凍結文言（test で固定）:

- `OUTPUT_IS_NOT_AUTHORITY` = "an llm generation is a draft for human review, never an authority record"
- `HANDLE_IS_NOT_AUTHORITY_ID` = "an opaque handle names an input of one request, never an authority record"

## 2. model の層（混ぜない）

```
A. LlmGenerationRequest   ── caller が決める（task / cutoff / generated_at / prompt contract / manifest digest / knowledge pins）
B. LlmGenerationEnvelope  ── LLM の出力全体（outcome = CANDIDATES | ABSTAIN）
   ├─ C. LlmCandidate × 1..16（kind 別 payload: EVIDENCE / THEME / RELATION）
   └─ D. LlmAbstention（ABSTAIN のときだけ）
E. LlmGenerationRecord    ── 監査（request ＋ provider / model / 生成設定の token ＋ outcome ＋ digest）
```

## 3. candidate kind

| kind | 対応する既存 authority 型 | 備考 |
|---|---|---|
| `EVIDENCE` | B3 EVIDENCE_CANDIDATE | 反証・無効化は第 4 の型ではなく、role（CONTRADICTS / INVALIDATES）で表す |
| `THEME` | B3 THEME_CANDIDATE | root id を作らない |
| `RELATION` | B5C RELATION_CANDIDATE | 主張・確認・decision を持たない |

B3 DEDUP_REVIEW は LLM の kind として存在しない。

task と許される kind / role（`check_task_compatibility`。構造的な整合で、実在・意味は見ない）:

| task | kind | EVIDENCE の role |
|---|---|---|
| `EVIDENCE_EXTRACTION` | EVIDENCE | SUPPORTS / CONTEXT |
| `CONTRADICTION_PROPOSAL` | EVIDENCE | CONTRADICTS / INVALIDATES |
| `THEME_PROPOSAL` | THEME | — |
| `RELATION_PROPOSAL` | RELATION | — |

どの task でも ABSTAIN は許される（`UNSUPPORTED_TASK` を含む）。

## 4. opaque handle

書式 `^(EV|TH|REL|ENT|MON|CQ|IC)_[0-9]{3,6}$`。handle は **1 つの要求の入力を指す名札**であり authority の id ではない。
実体への解決（handle → authority ref）は B7C の責務。model は書式と「欄ごとに許される種別」だけを検査する。

| 種別 | 指すもの | 使ってよい欄 |
|---|---|---|
| `EV` | evidence 入力 | `evidence_handles`、RELATION の `attribution_evidence_handle` |
| `TH` | Theme（root または THEME 提案） | EVIDENCE の `target_handle`、RELATION の `source_handle` / `target_handle` |
| `REL` | 既存 relation | RELATION の `previous_relation_handle` |
| `ENT` | entity | THEME の `subject_entity_handle`、component の `entity_handle` |
| `MON` | monitoring finding | `context_handles` だけ（**evidence ではない**） |
| `CQ` | 既存 Theme の期待 consequence | EVIDENCE（SUPPORTS / CONTRADICTS）の `component_handle` |
| `IC` | 既存 Theme の無効化条件 | EVIDENCE（INVALIDATES）の `component_handle` |

authority の id（`fact_…` / `thobs_…` / `thprop_…` など）・machine path・URL・journal key・全角数字は handle にならない。

## 5. envelope

| outcome | key の集合（ちょうどこれだけ） | 規則 |
|---|---|---|
| `CANDIDATES` | `output_schema_version` / `outcome` / `candidates` | 候補 1〜16 件。`abstention` key があれば `INVALID_COMBINATION` |
| `ABSTAIN` | `output_schema_version` / `outcome` / `abstention` | `candidates` key があれば（空 list でも）`INVALID_COMBINATION` |

空文字・空白だけの応答は棄権ではない（`EMPTY_OUTPUT`）。

## 6. 棄権語彙

`NO_SUPPORTED_PROPOSAL` / `INSUFFICIENT_EVIDENCE` / `AMBIGUOUS` / `UNSUPPORTED_TASK` / `CONFLICTING_EVIDENCE`（5 値）。
数値の確信度は持たない。任意で `limitations`（有界 category ＋ 有界の説明）を添えられる。

## 7. field 表

### 7.1 共通（`LlmCandidate`）

| field | 型 | 必須 | 規則 |
|---|---|---|---|
| `candidate_kind` | enum | ○ | EVIDENCE / THEME / RELATION |
| `evidence_handles` | list[EV] | ○ | EVIDENCE はちょうど 1、THEME / RELATION は 1〜16（**根拠の無い候補は作らない**）。重複不可 |
| `context_handles` | list[MON] | — | 0〜16。evidence ではない |
| `payload` | object | ○ | kind 別（下表）。kind と型が一致しなければ `INVALID_COMBINATION` / `UNKNOWN_FIELD` |
| `rationale` | text ≤240 | ○ | 説明文だけ。evidence・authority・lifecycle・governance・出典確認にならない |
| `limitations` | list[{category, statement ≤240}] | — | 0〜8。category は Foundation の `LimitationCategory` |

### 7.2 EVIDENCE payload

| field | 型 | 必須 | 規則 |
|---|---|---|---|
| `target_handle` | TH | ○ | 既存 Theme / THEME 提案 |
| `proposed_role` | enum | ○ | Foundation `EvidenceRole`（SUPPORTS / CONTEXT / CONTRADICTS / INVALIDATES） |
| `component_handle` | CQ / IC | — | SUPPORTS・CONTRADICTS は CQ、INVALIDATES は IC、CONTEXT は不可 |

evidence の時刻・origin・kind は持たない（B7D が manifest から複写する）。provenance の field は無い。

### 7.3 THEME payload

| field | 型 | 必須 | 規則 |
|---|---|---|---|
| `subject_statement` | text ≤240 | ○ | 主題 |
| `subject_entity_handle` | ENT | — | |
| `drivers` / `channels` / `domains` | list[{category, statement?, entity_handle?}] | ○ | 各 1〜8。category は Foundation `MECHANISM_CATEGORIES` の該当 type。OTHER は statement 必須 |
| `consequences` | list[{category, observable_target ≤200, expected_change, statement?}] | ○ | 1〜8。観測可能な帰結。価格目標・期間・正誤なし |
| `scope` | list[{dimension, value ≤200}] | ○ | 1〜8。PERIOD_FRAME ちょうど 1 |
| `invalidation_conditions` | list[{statement, observable_target?, expected_change?}] | ○ | 1〜8 |

certainty・主張 provenance・component key・condition key・evidence attachment・root id・inferred exposure link は持たない
（B7D が code で決める。certainty は固定、provenance は `LLM_PROPOSAL` 固定）。

### 7.4 RELATION payload

| field | 型 | 必須 | 規則 |
|---|---|---|---|
| `source_handle` / `target_handle` | TH | ○ | 異なること（`SELF_RELATION`） |
| `relation_type` | enum | ○ | B5 `RelationType`（CAUSES / AMPLIFIES / MITIGATES / DEPENDS_ON） |
| `previous_relation_handle` | REL | — | 在れば既存 relation の訂正候補 |
| `attribution_evidence_handle` | EV | — | 引用した evidence のどれか。「出典がそう書いている」と LLM が読んだという印であり、真実性でも SOURCE_ASSERTED でもない |

assertion class・確認 record・decision・客観的真実・推移的推論・重要度・中心性・因果確度は存在しない。
CAUSES の evidence 必須（B5）は、全 RELATION に evidence を要求する B7 の規則で満たされる。

### 7.5 request（`LlmGenerationRequest`）

| field | 規則 |
|---|---|
| `request_schema_version` | 一致必須 |
| `task` | `LlmTask` |
| `cutoff` / `generated_at` | aware datetime（caller 注入）。`generated_at >= cutoff` |
| `prompt_contract_version` | 有界 token（小文字・64 字以内）。credential に見える値は拒否 |
| `output_schema_version` | 一致必須 |
| `manifest_digest` | `thllmin_<24 hex>`（計算は B7C） |
| `knowledge_versions` | (name, version) の組、名前は一意、16 組以内 |

本文・excerpt・API key・provider secret の field は無い。

### 7.6 生成 record（`LlmGenerationRecord`）

| field | 規則 |
|---|---|
| `generation_id` | `thllmgen_` 内容 id（下記 identity） |
| `request` | 要求そのもの（`request_id` は導出値） |
| `provider_ref` / `model_ref` / `generation_config_ref` | 有界 token（`/`・path・credential に見える値は拒否）。**provenance だけ** |
| `outcome` | CANDIDATES / NO_PROPOSAL / REJECTED_GENERATION / RETRYABLE_FAILURE / INTEGRITY_FAILURE |
| `response_digest` | `thllmresp_` digest（raw response の本文は持たない） |
| `output_digest` | `thllmout_` digest（構造化出力の canonical 形） |
| `abstention_reason` / `candidate_count` | envelope から導く（`build` が設定。呼び出し側に書かせない） |
| `rejection_codes` | 大文字 code、一意、16 件以内 |

outcome と field の整合:

| outcome | response | output | 候補数 | 棄権理由 | 拒否 code |
|---|---|---|---|---|---|
| CANDIDATES | 有 | 有 | ≥1 | 無 | 無 |
| NO_PROPOSAL | 有 | 有 | 0 | 有 | 無 |
| REJECTED_GENERATION | 有 | 無 | 0 | 無 | ≥1 |
| RETRYABLE_FAILURE | 無 | 無 | 0 | 無 | ≥1 |
| INTEGRITY_FAILURE | 任意 | 無 | 0 | 無 | ≥1 |

raw response・prompt・推論過程（hidden reasoning）の field は無い。

## 8. identity

| 対象 | identity | 含めないもの |
|---|---|---|
| request（`request_id`、`thllmreq_`） | schema・task・cutoff・prompt contract・output schema・manifest digest・knowledge pins | `generated_at`・provider・model（誰がいつ答えたかは record） |
| 生成 record（`generation_id`、`thllmgen_`） | 出来事の全内容（request・provider / model / 設定 token・generated_at・outcome・digest・code） | — |
| 構造化出力（`output_digest`、`thllmout_`） | envelope の canonical 形 | provider・model・時刻 |
| raw response（`response_digest`、`thllmresp_`） | 応答文字列そのもの | — |
| **candidate** | **identity を持たない** | — |

- candidate の意味 identity は B7B では確定しない。handle は 1 要求の中でしか意味を持たず、handle → authority ref の解決
  （B7C）と template による identity 文の生成（B7D）の後でなければ安全に決められない。最終 identity は既存の
  B3 / B5C の内容 id である（provenance と created_at を含まない）。
- `LlmCandidate.structural_key()` は **同一生成内の重複判定用**の構造 key（説明文と限定条件を除く）であり、identity ではない。
- random UUID・現在時刻・provider・model 名・応答内の順序は、どの意味 identity にも入らない。

## 9. canonical 化

- canonical JSON は Foundation の `canonical_json`（key 整列・compact・`ensure_ascii=False`）。
- **順序を意味として持たない list**（canonical 形で整列する）: 候補、`evidence_handles`、`context_handles`、
  `limitations`、`drivers` / `channels` / `domains` / `consequences` / `scope` / `invalidation_conditions`。
  候補の順序は意味を持たないと宣言した（重要度・順位の含意を持たせないため）。
- **許す表現差**（明示・無害）: JSON の空白・改行・key 順、上記 list の順序、省略された任意 field と空値（`""` / `[]`）の同一視。
- **許さない**（生成全体を拒否）: code fence、前後の説明文、重複 key、NaN / Infinity、数値・真偽値、未知 field、
  重複 handle、重複 item、重複 candidate、切り詰め、前後空白・制御文字を含む文。
- **文の Unicode / case は B7B では正規化しない**（そのまま保持）。Foundation の正規化（NFKC・空白圧縮・casefold）は
  B7D が Foundation の型を組む時点で Foundation 自身の関数で行う（`normalized` を要求する field のため）。
  そのため B7B の重複判定は「大文字小文字だけ違う」候補を重複とみなさない（B7D の責務）。

## 10. 全体拒否

1 か所でも違反があれば `LlmModelError(code)` を出し、**生成全体**を拒否する。有効な候補だけを残す API は存在しない
（「3 件は有効、1 件は無効 → 3 件を採用」をしない。test 30 がどの位置に無効候補を置いても全体が失敗することを固定）。
Compass 生成器の「不正 claim を落として残りを使う」pattern は持ち込んでいない。

## 11. 構造検査の code（主なもの）

`INVALID_JSON` / `DUPLICATE_JSON_KEY` / `NOT_AN_OBJECT` / `EMPTY_OUTPUT` / `OVERSIZED_OUTPUT` / `UNKNOWN_FIELD` /
`MISSING_FIELD` / `UNSUPPORTED_SCHEMA_VERSION` / `INVALID_ENUM` / `INVALID_TYPE` / `INVALID_COMBINATION` / `INVALID_COUNT` /
`INVALID_HANDLE` / `HANDLE_KIND_NOT_ALLOWED` / `DUPLICATE_HANDLE` / `DUPLICATE_ITEM` / `DUPLICATE_CANDIDATE` /
`SELF_RELATION` / `INVALID_SCOPE` / `FIELD_TOO_LONG` / `INVALID_TEXT` / `PROHIBITED_CONTENT` / `INVALID_TOKEN` /
`INVALID_DIGEST` / `NAIVE_DATETIME` / `INVALID_DATETIME` / `GENERATED_BEFORE_CUTOFF` / `INVALID_RECORD_ID` /
`CANDIDATE_KIND_NOT_ALLOWED_FOR_TASK` / `ROLE_NOT_ALLOWED_FOR_TASK`。

## 12. 構造検査と意味検査の境界

| B7B が見る（構造） | B7B が見ない（B7C / B7D） |
|---|---|
| JSON が 1 つの object か、重複 key・数値・未知 field | handle が manifest に実在するか |
| outcome と key 集合の整合、件数・長さの上限 | handle が指す evidence / Theme / relation が PIT 可視か |
| enum（Foundation の role / mechanism category / scope 次元 / 期待変化、B5 の relation type） | evidence が主張を支えるか |
| handle の書式と欄ごとの種別 | taxonomy slug / entity が現行 knowledge に在るか |
| handle の一意性、根拠 handle の最小数、自己 relation | 出典帰属が evidence の origin と一致するか |
| PERIOD_FRAME ちょうど 1、OTHER の説明必須 | 既存 B3 / B5C 提案との重複 |
| 文が 1 行・有界・path / URL / 秘密 query を含まない | 文の正規化（Foundation 形）と identity 用 template 化 |
| task と kind / role の構造的整合 | authority ceiling の適用（provenance 固定・certainty 固定） |

## 13. security（構造的な排除）

- credential・API key・machine path・portfolio・Compass PDF / corpus 本文・hidden reasoning・raw article・system prompt は
  **schema に field が無い**。書けば `UNKNOWN_FIELD`（全 depth で strict）。
- 文 field は machine path（`C:\`・UNC・`/home/`・`/Users/`・`/root/`）・URL（`scheme://`）・秘密 query（`?api_key=` 等）を拒否。
- provider / model / 設定の token は `/`・空白・大文字を許さず、`sk-` や `secret` / `password` / `api_key` / `bearer` /
  `credential` を含む値を拒否（多層防御。一次防御は field の不在）。
- raw response は digest だけ。本文を record に入れる field は無い。
- 例外 message は code と短い説明だけ（本文・値を入れない）。

## 14. 純粋性と guard

- import は stdlib（`json` / `re` / `dataclasses` / `datetime` / `enum` / `typing`）と `..core.ids` / `..core.time` /
  `..themes.model`（語彙と canonical JSON）/ `.relation_model`（relation 語彙）だけ。
- 現在時刻・乱数・UUID・filesystem・環境変数・network・SDK・provider protocol を使わない（test 120〜123）。
- store / bridge / runner / resolution / operations を import しない。`append_*` / `execute_*` / decision / review の型を参照しない。
- `test_theme_intelligence_import_boundary.py` に登録（MODULES / LLM_MODULES / IDENTITY_MODULES / 閉包）。追加 guard:
  - 上流（Foundation / B1〜B6 と src 全体）が B7 を import しない
  - `llm_*.py` はすべて登録済みで、subpackage で guard を逃れない
  - B7 module は store・bridge・network・provider・公開 / 通知経路へ到達しない
- B6 の凍結 pin（`test_theme_monitoring_e2e.py` test_e01、`test_theme_monitoring_e2e_rerun.py` test_01、
  `test_theme_monitoring_coverage_rerun.py` test_01 / 02）は、**新規追加の `theme_intelligence/llm_*.py` だけ**を除外するよう
  更新した。既存 file の変更は従来どおり検出する（scratch clone で monitoring module を改変すると 5 件失敗することを確認）。

## 15. deferred（後続 gate）

| # | 内容 | gate |
|---|---|---|
| 1 | handle → authority ref の解決、PIT manifest、manifest digest の計算 | B7C |
| 2 | 意味検証（実在・支持・語彙の現行性・出典帰属の一致）、Foundation 正規化、identity 文の template 化、provenance / certainty の固定 | B7D |
| 3 | component key / condition key の決定論的導出（位置に依存しない方式） | B7D |
| 4 | 大文字小文字・Unicode 差だけの候補の重複判定 | B7D |
| 5 | 生成 journal store（`LlmGenerationRecord` の永続化）、retry 方針、provider protocol と fake / recorded provider | B7E |
| 6 | 既存提案との check-then-reuse、B3 exact dedup、submit | B7F |
| 7 | 注釈だけの役割（E: 正規化示唆、G: 説明、H: dedup 補助）の model | 必要になった gate（B7A §4） |
| 8 | B3 model への LLM provenance 不変条件（多層防御） | D-B7-12 により本 gate では行わない |
