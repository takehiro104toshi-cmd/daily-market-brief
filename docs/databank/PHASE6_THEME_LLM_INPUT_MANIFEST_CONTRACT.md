# PHASE 6 / P6-B7C — LLM INPUT MANIFEST / POINT-IN-TIME GROUNDING CONTRACT

DETERMINISTIC INPUT LAYER ONLY。LLM・provider・prompt・意味検証・bridge・store・generation journal は無い。

| module | 役割 |
|---|---|
| `src/intelligence/theme_intelligence/llm_manifest_model.py` | 純 model（投影・handle・内部対応表・digest。I/O なし） |
| `src/intelligence/theme_intelligence/llm_manifest_builder.py` | read-only builder（既存の PIT 入口だけで上流を読む） |
| `tests/intelligence/test_theme_llm_input_manifest.py` | test matrix A〜Z ＋ 重複・prompt 境界・B7B 接続・凍結 |
| `tests/intelligence/theme_freeze_pins.py` | B6 凍結 pin の共通規則（新規 `llm_*.py` の追加だけを対象外にする） |

問い: **「caller が決めた cutoff 時点で、LLM に何を見せてよかったか」**。

---

## 1. authority の分類

| 対象 | 分類 |
|---|---|
| `LlmInputManifest` | **DERIVED・非 authority・非永続**（B7C では保存しない） |
| visible payload | LLM に見せてよい data。authority の id を含まない |
| 内部対応表（`resolution`） | handle → authority / source ref。B7D の grounding 検証用。visible に入らない |
| `LlmManifestScope` | caller の明示入力 |

manifest の構築は上流を変えない（data root の全 file の hash が前後で一致することを test で固定）。
凍結文言: `MANIFEST_IS_NOT_AUTHORITY` / `MANIFEST_IS_NOT_A_PROMPT`。

## 2. 入力 family（含めるもの・除外するもの）

| family | 扱い | 具体的な role | 読み方 |
|---|---|---|---|
| evidence（Fact / NewsItem / SourceDocument / Observation） | **含める**（全 task 必須） | 候補の根拠。LLM が引用できるのは manifest の EV だけ | caller が渡した上流 record を B4 `adapt_inputs` で正規化 |
| Theme（root の cutoff 時点の状態） | **含める**（EVIDENCE / CONTRADICTION / RELATION） | evidence の付与先・反証先・関係の端点 | Foundation `resolve_at_data_root` |
| relation（B5B） | **含める**（RELATION だけ・導出） | 既存関係の記述（重複提案・訂正の文脈） | B5B `resolve_relations_at_data_root` |
| entity（pinned catalog） | **含める**（THEME だけ・導出） | THEME 候補の主題 / component の entity handle | evidence の entity hit を catalog で引く |
| B6 MonitoringFinding | **任意**（CONTRADICTION だけ） | 反証・無効化の文脈（「どこを見るべきか」） | caller が選んだ finding |
| taxonomy | 語彙として使う（slug を evidence に付す） | 分類の token | B4 adapter が pinned snapshot で解決 |
| **B3 提案状態** | **除外** | 生成に必要な role が無い。重複確認は B7F の check-then-reuse | 読まない |
| **B5C 関係提案状態** | **除外** | 同上 | 読まない |
| discovery 出力 | **除外** | 非 authority の文脈であり、根拠は evidence そのもので足りる | 読まない |
| Compass PDF / corpus / formal review / APPROVED-but-NOT_PROMOTED / REJECTED / KEEP_REVIEWING / Production DNA | **除外**（D-B7-11） | — | import もしない |
| portfolio / credential / machine path / API key / hidden reasoning / 受理率 / finding 件数 / review disposition / P5 較正 / 売買推奨 | **除外** | — | 投影の field に存在しない |

## 3. task → family matrix

| task | caller 必須 | caller 任意 | 導出 | Theme component の handle |
|---|---|---|---|---|
| `EVIDENCE_EXTRACTION` | EVIDENCE, THEME | — | — | CQ |
| `CONTRADICTION_PROPOSAL` | EVIDENCE, THEME | MONITORING | — | CQ, IC |
| `THEME_PROPOSAL` | EVIDENCE | — | ENTITY | — |
| `RELATION_PROPOSAL` | EVIDENCE, THEME | — | RELATION | — |

表に無い family を caller が渡すと `FAMILY_NOT_ALLOWED_FOR_TASK`（黙って捨てない）。

## 4. PIT の規則

`canonical load / validation → cutoff visibility → upstream resolver → B7 projection`。

| family | PIT |
|---|---|
| Theme | Foundation resolver が store 全体を検証してから cutoff で解決（未来の observation / evidence / governance は見えない） |
| relation | B5B resolver が store を検証してから cutoff で解決（未来の assertion / 撤回は見えない） |
| evidence | B4 adapter が `published_at` / `retrieved_at` / `known_at` / `as_of` > cutoff を除外 |
| finding | `finding.cutoff == manifest cutoff` のものだけ |
| knowledge | taxonomy / catalog の `published_at <= cutoff`（`FUTURE_KNOWLEDGE`） |

B3 / B5C は読まないため、B6D-R1 の「検証 → 時刻で濾過 → resolver」規則を適用する場面が B7C には無い（B7F が読むときに適用する）。
`generated_at` は可視性の判定に使わない。現在時刻・mtime・「latest」は使わない。

## 5. integrity-before-PIT

- 破損した authority は、壊れた行が未来の時刻を名乗っていても読み飛ばさない。Foundation / B5B の store は load 時に
  検証するため、未来日付の破損行でも `STORE_CORRUPTION` になり、builder は `THEME_NOT_RESOLVED` /
  `RELATION_NOT_RESOLVED` で止まる（修復しない。file は変えない）。
- evidence の adapter 除外のうち、PIT（`AFTER_CUTOFF` / `KNOWN_AFTER_CUTOFF`）だけが「見えないだけ」で痕跡を残さない。
  それ以外（非対応の型・USABLE でない Fact・naive 時刻・日付不正）は `EVIDENCE_INPUT_REJECTED` で止まる。
- relation を読まない task（EVIDENCE / CONTRADICTION / THEME）は relation store の状態に影響されない。

## 6. scope の意味

- `None` ＝ 渡していない、空 tuple ＝ 空で渡した。両者を区別し、manifest の `scope_presence` と digest に束縛する。
- 必須 family の省略は `SCOPE_OMITTED`。空での供給は許す（LLM は棄権するしかない manifest になる）。
- 「全 Theme」「全 evidence」の暗黙の既定は無い。scope を黙って広げない。
- scope の Theme が cutoff で解決できない（NO_STATE・破損・未解決）なら `THEME_NOT_RESOLVED`（黙って落とさない）。
- root id でない値は `INVALID_SCOPE_ENTRY`、同じ root を 2 回渡すと `DUPLICATE_SCOPE_ENTRY`。

## 7. 投影 field（すべて理由付き）

**evidence（EV）**

| field | 理由 |
|---|---|
| `evidence_kind` | Fact / News / 文書 / 観測の区別（根拠の性質） |
| `evidence_date` | 時間的な前後関係の判断に要る最小の粒度（日付）。時刻・known_at は内部表だけ |
| `source_kind` | origin の種別（出所の性質）。origin key・publisher・URL は出さない |
| `fact_type` / `observation_series` | 構造化された分類 token |
| `taxonomy_slugs` | pinned taxonomy の語彙（B4 が解決済み） |
| `entity_handles` | THEME task のときだけ。entity id は出さない |
| `text_surfaces` | B4 の限定面（NewsItem の見出し・要約、SourceDocument の題名・要約）だけ |

**Theme（TH）**: `subject_statement`、`drivers` / `channels` / `domains`（category と文）、`consequences`（CQ・category・
observable target・期待変化・文）、`invalidation_conditions`（IC・文・observable target・期待変化）、`scope`。
certainty・governance 状態・attachment・limitations・provenance・recorded_at・root id は出さない。

**relation（REL）**: `source_handle` / `target_handle` / `relation_type` / `assertion_class`。帰属・chain・端点の lifecycle は出さない。

**entity（ENT）**: `entity_type` / `canonical_name`（pinned catalog）。

**finding（MON）**: `condition_id` / `subject_handle`（TH）/ 許可された salient fact（`role` / `absence_kind` /
`evidence_condition`）。finding id・category・ruleset・件数・review 状態・trigger / supporting ref は出さない。

visible payload に数値は 1 つも無い（test で再帰的に確認）。

## 8. text の方針

- 本文は出さない。B4 の既存の限定面をそのまま使い、新しい要約を作らない（B7C は LLM を使えない）。
- 文は書き換えない（切り詰め・改行除去・path 除去をしない）。次の場合は fail closed:
  - `MAX_SURFACE_LEN`（600）を超える → `SURFACE_TOO_LONG`
  - 制御文字（改行を含む）→ `INVALID_INPUT_TEXT`
  - machine path・URL（`scheme://`）・秘密 query → `PROHIBITED_CONTENT_IN_INPUT`

## 9. handle の algorithm

| handle | 並び順の key |
|---|---|
| `EV_nnn` | evidence の ref id（Foundation ref） |
| `TH_nnn` | Theme root id |
| `CQ_nnn` / `IC_nnn` | TH の順 → component key / condition key |
| `REL_nnn` | edge key |
| `ENT_nnn` | entity id |
| `MON_nnn` | finding id |

番号は 1 から 3 桁（上限 999。超えたら `MANIFEST_TOO_LARGE`）。authority ref の辞書順で振るため、入力の物理順・mapping 順・
data root の path・mtime・乱数・時計に依らない。純 model も自分で並べ替える（builder の並べ替えに頼らない）。

**安定性の契約: canonical に等価な manifest の間で安定。** handle は authority の identity ではない（見える item の集合が
変われば番号はずれる）。cutoff 後の record は見えないので、未来の追加で過去の handle は変わらない。

## 10. 逆引き表の方針

- `HandleRef(handle, family, ref, detail)` の表は visible に入らない。handle が在るだけで authority ref を渡すことはしない。
- detail: EV は evidence の時刻・basis・quality・日付・known_at・source origin（B3 EVIDENCE_CANDIDATE を組む材料）、
  TH は cutoff 時点の observation id、CQ / IC は component key / condition key、REL は edge key（ref は terminal assertion id）。
- B7D は grounding 検証にこの表を使う。`manifest.resolve(handle)` は表に無い handle を `UNKNOWN_HANDLE` で拒否する。

## 11. manifest の identity

| digest | 束縛するもの | 束縛しないもの |
|---|---|---|
| `manifest_digest`（`thllmin_`） | schema version・task・cutoff・knowledge pin・scope presence・全投影（handle 付き）・**内部対応表** | path・mtime・UUID・時計・provider / model・生成 response |
| `visible_digest`（`thllmvis_`） | LLM に見える部分だけ | 内部対応表 |

内部の authority ref を `manifest_digest` に含める理由: 見た目が同じでも別の record を指す manifest を区別するため
（replay で handle が別の record に解決されることを防ぐ）。digest は hash なので ref 自体は漏れない。
`manifest_digest` はそのまま B7B の `LlmGenerationRequest.manifest_digest` に入る（test で接続を確認）。

## 12. knowledge pin（実際に使ったものだけ）

| pin | 条件 |
|---|---|
| `taxonomy` / `entity_catalog` | 常に（evidence は全 task 必須で、B4 adapter が両方を使う） |
| `mechanism_vocabulary` | Theme を 1 つ以上投影したとき |
| `theme_relation_vocabulary` | RELATION task（relation を解決したとき） |
| `monitoring_rules` | finding を 1 つ以上投影したとき（finding の ruleset version。混在は `MIXED_MONITORING_RULESETS`） |

「latest」解決は無い。pin の形は B7B の request の `knowledge_versions` と互換。

## 13. 重複の方針

| 状況 | 扱い |
|---|---|
| 同じ record（同じ id・同じ内容）を 2 回渡す | 同一性が証明されるので 1 item に畳む |
| 同じ id で内容が違う | `CONFLICTING_EVIDENCE_INPUT` |
| 別 record が handle 以外で同じ投影になる | **畳まずに fail closed**（`DUPLICATE_PROJECTION`。LLM が見分けられない引用を作らない） |
| 例: merge 元と merge 先を同時に scope に入れる | 同じ意味を持つため `DUPLICATE_PROJECTION`。caller がどちらかを選ぶ |

判定は handle をすべて（入れ子の CQ / IC を含む）取り除いた投影で行う。

## 14. MonitoringFinding の境界

- DERIVED・非 authority のまま。CONTRADICTION task の任意文脈として、caller が選んだものだけを入れる（自動起動しない）。
- 許可 condition: `THEME_CONTRADICTION_EVIDENCE_PRESENT` / `THEME_INVALIDATION_EVIDENCE_PRESENT` /
  `THEME_WITHOUT_COUNTED_EVIDENCE` / `GOVERNANCE_EVIDENCE_DIVERGENCE`。INTEGRITY は `FINDING_NOT_ALLOWED`。
- subject は scope の Theme root であること（`FINDING_OUT_OF_SCOPE`）。cutoff は一致（`FINDING_CUTOFF_MISMATCH`）。
- 件数を重要度にしない。ACK / DISMISS / DEFER を渡さない（review 状態を読まない）。
- 型の参照: package 内で `monitoring_model` を参照してよい module に `llm_manifest_model` を名指しで加えた（B6B の
  test_87）。参照は finding の型検査だけで、B7 module の import 閉包は `monitoring_model` 止まり
  （engine / rules / store / runner には到達しない）。

## 15. B3 提案状態の判断

**除外。** 生成に必要な role が無い（Theme は root の解決済み状態で足り、重複確認は B7F の check-then-reuse の責務）。
提案と decision の履歴を prompt 内の意味的な真実にしないためでもある。B3 / B5C の journal が壊れていても、未来の提案・
決定が足されても、manifest は変わらない（test で固定）。

## 16. relation の意味

- B5B の PIT 解決の結果から、cutoff 時点で **ACTIVE** かつ **両端が scope の Theme** の関係だけ。撤回済み・片端だけ・
  scope 外の関係は見せない。scope に触れる未解決の辺があれば `RELATION_NOT_RESOLVED`。
- `assertion_class` をそのまま写す。**SOURCE_ASSERTED は「出典がそう主張した」であり客観的真実ではない**。
  verified / true / confirmed のような変換をしない。
- centrality / PageRank / 重要度 / 推移的推論 / 因果 score を足さない。
- 端点の lifecycle は投影しないため、endpoint lookup は scope の Theme の作成時刻だけで組む（B5B では退役・後継は
  辺の可視性を変えず、diagnostic にだけ影響する）。relation store の欠落は空の graph ではなく fail closed。

## 17. security / data minimization

- 除外は string の denylist ではなく **投影の field 自体が無い**ことで行う（test で field 集合を固定）。
- 入力文の path / URL / 秘密 query / 制御文字は fail closed。authority id の形（Theme root / news / doc / fact / obs /
  `th*_` content id）が visible に現れないことを test で確認。
- builder は compass / corpus / formal review / decision / DNA / predictions / reports / notifiers を import しない。
- B7 module は書き込み API・store class・network・provider・環境変数・時計・乱数を使わない（guard）。

## 18. 決定論と replay

- 同じ semantic な PIT 状態 → 同じ canonical visible bytes・handle・内部表・digest（入力順 5 通り、別 path ＋ mtime 変更、
  別 process で確認）。
- visible JSON は canonical（key 整列・compact）で、読み直して再 dump しても同じ bytes。

## 19. failure mode

| code | 意味 |
|---|---|
| `MISSING_CUTOFF` / `NAIVE_CUTOFF` | cutoff が無い / naive |
| `SCOPE_OMITTED` | 必須 family の省略 |
| `FAMILY_NOT_ALLOWED_FOR_TASK` | task が取らない family を渡した |
| `INVALID_SCOPE` / `INVALID_SCOPE_ENTRY` / `DUPLICATE_SCOPE_ENTRY` | scope の型・値・重複 |
| `MISSING_KNOWLEDGE` / `FUTURE_KNOWLEDGE` | pinned knowledge が無い / cutoff 後の公開 |
| `THEME_AUTHORITY_UNAVAILABLE` / `THEME_NOT_RESOLVED` | Theme store が開けない / cutoff で解決できない（NO_STATE・破損・未解決） |
| `RELATION_AUTHORITY_UNAVAILABLE` / `RELATION_NOT_RESOLVED` | relation store が開けない / 破損・scope に触れる未解決 |
| `EVIDENCE_INPUT_REJECTED` / `CONFLICTING_EVIDENCE_INPUT` | PIT 以外の理由で evidence を正規化できない / 同じ id の別内容 |
| `SURFACE_TOO_LONG` / `INVALID_INPUT_TEXT` / `PROHIBITED_CONTENT_IN_INPUT` | 入力文の長さ・制御文字・path / URL / 秘密 |
| `FINDING_CUTOFF_MISMATCH` / `FINDING_NOT_ALLOWED` / `FINDING_OUT_OF_SCOPE` / `MIXED_MONITORING_RULESETS` | finding の契約外 |
| `UNKNOWN_ENTITY` | evidence の entity が pinned catalog に無い |
| `DUPLICATE_PROJECTION` / `DUPLICATE_INPUT` | 見分けられない投影 / 同じ ref の重複 |
| `MANIFEST_TOO_LARGE` | 件数の上限（切り詰めない） |
| `UNKNOWN_HANDLE` | 逆引きに無い handle |

## 20. deferred

| # | 内容 | gate |
|---|---|---|
| 1 | handle を使った候補の grounding 検証（実在・種別・PIT・出典帰属の一致・Foundation 正規化・template identity） | B7D |
| 2 | B3 / B5C の読み取り（check-then-reuse・exact dedup）と PIT 濾過（B6D-R1 規則） | B7F |
| 3 | prompt の組み立て（manifest を provider 形式へ）と provider protocol / fake provider / generation journal | B7E |
| 4 | Theme の governance 状態を投影するか（merge 元と先の衝突を caller の scope 選択以外で解く方法） | 監督判断（現状は fail closed） |
| 5 | 同じ端点・type・class で帰属だけが違う関係の区別（帰属を投影しないため `DUPLICATE_PROJECTION` になる） | 監督判断 |
| 6 | 本文の excerpt（限定面より広い文）を使う必要が生じた場合の上限と権利確認 | 必要になった gate |

### 凍結 pin の監査（§29）

B7B で B6 の凍結 pin に入れた例外（新規 `llm_*` を差分から除外）は、`tests/intelligence/theme_freeze_pins.py` の
`is_new_llm_module` に一本化し、次に絞った: status が追加（`A` / `??`）で、path が
`src/intelligence/theme_intelligence/llm_<name>.py`（package 直下）に完全一致するものだけ。
既存 file の変更（`M` / `D` / rename）・subdirectory・別 package・`llm_` 以外の名前は対象外にならない（test で 10 例を固定）。
凍結済みの B7B module（`llm_proposal_model.py`）は B7B anchor `e2aa991` と byte 一致であることを別に固定した。
