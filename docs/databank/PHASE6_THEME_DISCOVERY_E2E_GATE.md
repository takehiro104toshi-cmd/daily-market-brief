# Phase 6 / P6-B4D — Theme discovery E2E ＋ false-positive gate

本書は B4C（deterministic theme discovery）に対する **検証 gate** の記録である。実装 gate ではない。
本 gate では runtime（`src/intelligence/theme_intelligence/discovery*.py`、taxonomy / entity catalog / discovery rules の
公開 snapshot）を一切変更していない。追加したのは test と本書のみ。

---

## 1. 目的と非目的

**目的**

- discovery が「似ている」だけの入力から候補を作らないこと（false positive の不在）を、敵対的な合成 corpus で固定する。
- 機構（driver → channel → domain → observable consequence）が template 由来であり、rule を跨いで合成されないことを固定する。
- point-in-time 境界と replay 決定性を固定する。

**非目的**

- 実運用の discovery 精度の測定。本書の数値は合成 corpus 上の契約適合の計数であり、
  **These figures are not estimates of real-world discovery precision/recall.**
- rule / taxonomy / entity catalog の拡充。coverage は本 gate の評価対象ではない。
- 閾値・スコア・類似度・LLM の導入。B4C 契約どおり存在しない。

---

## 2. 敵対 corpus（§2）

`tests/intelligence/test_theme_discovery_e2e.py` の `CORPUS` に 35 件の golden case を置いた。
入力はすべて合成（generic な語のみ）であり、実在記事・保有銘柄一覧・受益企業連鎖・過去 rule の原文は含まない。

case group と件数:

| group | N | 内容 |
|---|---|---|
| TP_CONTROL | 8 | 構造化 entity L1 / Fact type L1 / Observation series L1 / source kind L1 / 妥当な Theme trigger / 妥当な Evidence trigger / 同一 rule 複数 evidence / rule 跨ぎ収束 |
| L2_ATTACK | 6 | 別語内の alias、URL・author のみの alias、context 無し／別 context の context alias、L2 だけの theme 的文面、L1 の無い因果散文 |
| ENTITY_LIFECYCLE | 4 | 曖昧 entity、未知 entity、valid_from 前 entity、後継のある entity |
| TAXONOMY_HIERARCHY | 4 | 子 slug を親 rule で、親 slug を子 rule で、deprecated slug、後継 slug（対照） |
| NEGATIVE_PREDICATE | 2 | negative 一致による除外、positive ＋ negative の混在 |
| SOURCE_ORIGIN | 4 | 同一記事の 2 表現、同一記事の Fact ＋ News ＋ Document、単一 origin の Theme、同一入力の反復 |
| PIT_INPUT | 2 | cutoff 後の入力、USABLE でない Fact |
| MECHANISM_FIREWALL | 3 | 同一 rule 内に揃わない signal、部分証拠を持つ 3 rule、矛盾する 2 rule |
| MIN_DISTINCT | 2 | INPUT_ID 不足、TAXONOMY_TOKEN 充足 |
| **合計** | **35** | |

公開 ruleset（`discovery_rules.0.1.0.yaml`）に無い trigger 面（OFFICIAL_RELEASE source kind、context alias entity、
company entity、taxonomy 親子の単独 rule、firewall 用の 3 rule、矛盾 rule、TAXONOMY_TOKEN 次元の MIN_DISTINCT）は
tmp ruleset として test 内で authoring し、公開 loader（`load_discovery_rules_version`）の検証を通したうえで使用した。
公開 knowledge の 3 file は読み取り専用で使用している。

さらに `test_theme_discovery_false_positive.py`（59 件）と `test_theme_discovery_replay.py`（20 件）が
正規化層と PIT / 決定性を個別に stress する。

---

## 3. golden 期待値の作り方（§3 / §17）

各 case は次を **独立に authoring** した固定値として持つ。`discover()` の出力を snapshot したものではない。

- `record_ids` — 正規化後に残る入力 id
- `normalized` — 入力ごとの `(input_id, ENTITY|TAXONOMY, value, L1|L2)` の集合（L1 / L2 の区別を含む）
- `excluded` — `(input_id, reason)`
- `rule_hits` — `(rule_id, input_id)`
- `evidence_ids` / `theme_evidence` — 生成される EVIDENCE_CANDIDATE の ref_id と、THEME_CANDIDATE の evidence ref 集合
- `origin_groups` — `(origin_key, input ids)`
- `report_diagnostics` / `record_diagnostics` — run report 側・record 側に現れるべき診断
- `truth_evidence` / `truth_theme` — 「正しい discovery 契約なら出すべきか」の真値ラベル（契約の期待とは別に付ける）
- `fail_closed` — 契約が意図的に閉じる側に倒す case かどうか

test は `expected` と実測の一致を assert し、混同行列は `truth` と `expected` の対から数える。
したがって実装が期待と食い違えば test が落ち、期待を後から合わせ込むことはできない。

本 gate での期待値修正は 2 件のみで、いずれも **筆者の corpus 作成ミス**であり runtime 由来ではない。

1. `"Example Energy Systems expands"` に taxonomy alias `energy` が実在した（期待に追加）。
2. `"... banks of filters"` は `banks` が独立語として現れており正しい L2 hit だった（部分文字列 case を `Riverbanks` に差し替え）。

---

## 4. 混同行列（§4 / §19）

emission 単位（EvidenceCandidate / ThemeCandidate を別々に計数）。decision 履歴 case は emission 計数に含めず §15 で別に扱う。

| case group | N | E:TP | E:TN | E:FP | E:FN | T:TP | T:TN | T:FP | T:FN | 意図的 fail closed | 備考 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TP_CONTROL | 8 | 8 | 0 | 0 | 0 | 2 | 6 | 0 | 0 | 0 | 正例の取りこぼしが無いことの対照 |
| L2_ATTACK | 6 | 1 | 5 | 0 | 0 | 0 | 5 | 0 | 1 | 1 | FN は `fn_l2_only_theme_language` のみ |
| ENTITY_LIFECYCLE | 4 | 0 | 4 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 曖昧・未知・期間外・後継は hit しない |
| TAXONOMY_HIERARCHY | 4 | 1 | 3 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | TP 1 は後継 slug の対照 case |
| NEGATIVE_PREDICATE | 2 | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 除外は入力単位。部分点なし |
| SOURCE_ORIGIN | 4 | 4 | 0 | 0 | 0 | 1 | 3 | 0 | 0 | 0 | T:TP 1 は単一 origin の Theme（§8 参照） |
| PIT_INPUT | 2 | 0 | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | cutoff 超過・USABLE でない Fact |
| MECHANISM_FIREWALL | 3 | 1 | 2 | 0 | 0 | 2 | 1 | 0 | 0 | 0 | T:TP 2 は 3 rule 分離と矛盾 2 rule |
| MIN_DISTINCT | 2 | 1 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | |
| **合計** | **35** | **18** | **17** | **0** | **0** | **6** | **28** | **0** | **1** | **1** | |

- **ThemeCandidate の false positive は 0**（PASS 条件を満たす）。
- **EvidenceCandidate の false positive も 0**。
- ThemeCandidate の false negative は 1 件のみで、`fn_l2_only_theme_language`（L2 だけの theme 的文面）である。
  契約が意図的に閉じる側へ倒しており、診断 `THEME_CANDIDATE_REQUIRES_L1_HIT` が run report に現れることを assert している。

再掲: **These figures are not estimates of real-world discovery precision/recall.**

---

## 5. L1 の結果（§6 相当）

構造化面（NewsItem.entity_refs、Fact.subject / fact_type、Observation.entity_id / series_id、source kind）は
pinned catalog で正規化され、L1 として記録される。

- 構造化 ref は本文の文字列判断に影響されない（`test_22`）。
- 未知の構造化 ref・未知 ticker は推測されず `UNKNOWN_STRUCTURED_REF` / `UNKNOWN_IDENTIFIER` として記録される。
- ticker は有効期間で絞られる。期間外は `IDENTIFIER_OUT_OF_VALIDITY` で hit しない。

## 6. L2 の結果（§5）

限定 text 面（NewsItem headline / summary、SourceDocument title / summary）のみを走査する。本文全体の走査は無い。

| 攻撃 | 結果 |
|---|---|
| 別語内の部分文字列（turbojet / Japanese / Topixel / Riverbanks / Superpowered） | hit しない（境界一致のみ） |
| 句読点・括弧・スラッシュ隣接 | 正しく hit する（false negative を作らない） |
| NFKC（全角英数、半角カナ） | 正規化後に hit する |
| 大文字・小文字 | casefold 後に hit する |
| 連続空白・全角空白 | 空白正規化後に hit する |
| 重なる alias | 最長一致のみを採る（`bank of japan` を採り `japan` を捨てる） |
| 同一 alias の反復 | hit は 1 件。distinct 数も増えない |
| URL / author / locator のみの alias | hit しない |
| context alias（context 無し／別 entity の context） | hit しない |
| context alias（自分の context term あり） | hit する |
| 同一面の 2 entity | 両方 hit する |
| 同一 surface に 2 owner の context alias | AMBIGUOUS。勝者を選ばない |

## 7. taxonomy 階層攻撃（§6）

- 子 slug の hit は親 slug の predicate を満たさない（`grid` → `power` / `energy` / `ai` いずれも不成立）。
- 親 slug の hit は子 slug の predicate を満たさない。
- 多親 slug（`nuclear` は `energy` と `power` の子）でも hit は 1 件。distinct TAXONOMY_TOKEN も 1。
- deprecated slug（`supply_chain_theme`）は `DEPRECATED_TAXONOMY_TOKEN` として記録され、後継 `supply_chain` へは解決されない。

## 8. entity lifecycle 攻撃（§7）

- **rename**: 0.1.0 と 0.2.0 のいずれでも `company:example_motors` の id は不変。旧名称は両方で解決し、新名称は 0.2.0 のみで解決する。
- **ticker 変更**: 同一 entity id のまま EXM1 → EXM2。as_of により有効な方のみ hit。
- **supersession**: `SUPERSEDED_ENTITY:<old>-><new>` を記録し、後継へ自動で付け替えない。
- **inactive**: valid_from 前は `INACTIVE_ENTITY` で hit しない。
- **ambiguous**: 複数 owner が残れば hit を作らない。

## 9. source origin stress（§8）

- 1 記事から生じた NewsItem / SourceDocument / Fact は同一 origin group に集約される。
- run report は「独立 source 数」を持たない。THEME_CANDIDATE には
  `EVIDENCE_REFS:<n>;ORIGIN_KEYS:<m>;NOT_AN_INDEPENDENCE_CLAIM` を診断として付す。
- 単一 origin の 2 wrapper は `MIN_DISTINCT INPUT_ID 2` を満たすため契約上 THEME_CANDIDATE を生成する。
  これは契約どおりの挙動であり false positive として数えていない。ただし §17 の supervisor 決定事項に挙げる。
- series_id / source_id が欠ける Observation は `UNKNOWN` origin として保守的に扱う。

## 10. 機構 firewall（§9）

- 1 rule の predicate は同一入力に対して評価される。signal が別入力に分かれた場合、rule は成立しない。
- 部分的な根拠を持つ 3 rule（data_center / power / grid）は、それぞれ自分の template のまま 3 件の
  THEME_CANDIDATE になる。evidence ref は互いに素で、合成された機構は生じない。
- 矛盾する 2 rule（同一 identity core、逆向きの consequence）は 2 件の候補として残り、
  相互に `EXACT_IDENTITY_CORE_MATCH` の dedup review が付く。勝者選択・順位付けは行わない。
- L2 だけの一致では THEME_CANDIDATE を作らない（`THEME_CANDIDATE_REQUIRES_L1_HIT`）。

## 11. negative predicate（§10）

- negative は positive の前に評価され、一致した入力は rule 全体から除外される（部分点なし）。
- 同じ negative predicate を重複して書いても除外は 1 回。診断も 1 行。
- 除外された入力は MIN_DISTINCT の数にも入らない。

## 12. MIN_DISTINCT（§11）

| 次元 | 数え方 | 重複での増加 |
|---|---|---|
| INPUT_ID | 入力 id の異なり数 | しない |
| EVIDENCE_REF | (evidence kind, 入力 id) の異なり数 | しない |
| ENTITY_ID | matched 入力集合の entity id の異なり数 | しない |
| TAXONOMY_TOKEN | matched 入力集合の slug の異なり数 | しない |

未達時は `MIN_DISTINCT_NOT_MET:<dimension>:<count><<min>` を報告する。
入力単位の MIN_DISTINCT は ENTITY_ID / TAXONOMY_TOKEN のみを受け付け、他の次元は拒否する。

## 13. proposal id の収束と分岐（§12）

- 同じ意味（subject / mechanism / scope / invalidation / limitation）＋ 同じ evidence 集合であれば、
  rule id・rule version が違っても同一 `proposal_id` になる。rule 由来の値は `ProposalProvenance` と run report にのみ存在する。
- evidence 集合が違えば別 id になる（semantic fingerprint は一致しうるため dedup review の対象になる）。

## 14. decision 履歴（§13）

OPEN / OPEN_DEFERRED / ACCEPTED / REJECTED のいずれでも、同一 id の候補は再生成されず
`EXISTING_<STATUS>_PROPOSAL:<id>` として診断にのみ現れる。discovery は decision を作らず、変えない。
decision chain は `supersedes_decision_id` の graph で解決され、`recorded_at` や物理順では決まらない。

## 15. dedup（§14）

- 既存 THEME_CANDIDATE と semantic fingerprint が一致 → `EXACT_SEMANTIC_MATCH` の review。
- identity core のみ一致 → `EXACT_IDENTITY_CORE_MATCH` の review。
- 既存 Theme（read-only の resolution）に対しても同じ 2 分類で review を作る。counterpart は root id で参照する。
- いずれも一致しなければ review は作らない。
- `NOT_DUPLICATE` が記録された counterpart は再提示されない。

## 16. PIT と replay（§15 / §16）

- 入力 4 種（NewsItem published_at、SourceDocument published_at / retrieved_at、Observation as_of、Fact known_at）について、
  cutoff との **等号は許可**、**1 マイクロ秒の超過は除外**。
- knowledge 3 種（taxonomy / entity catalog / ruleset）についても、published_at == cutoff は使用可、
  cutoff より後なら `FUTURE_KNOWLEDGE`。loader 単体でも `FUTURE_VERSION` で fail closed。
- 旧 version に pin した replay（taxonomy 0.1.0 / catalog 0.1.0 / 旧 ruleset）は旧 slug `supply_chain_theme` のまま再現し、
  新 slug `supply_chain` を知らない。旧 ruleset を新 knowledge に当てると `TAXONOMY_PIN_MISMATCH`。
- 決定性: 入力順の 10 seed shuffle、既存 proposal と decision の shuffle、knowledge の再読み込みのいずれでも、
  `proposal_id` 列・`canonical_proposal_line` の byte 列・`run_report.to_plain()` が一致する。
- run report の順序はすべて canonical（診断は sorted かつ重複なし、origin group / rule hit / excluded / 抑制 id も sorted）。
- `run_created_at` は audit 側（`created_at` / `attached_at`）にのみ載り、identity payload を動かさない。

## 17. FC-1 — Foundation の OTHER category 使用（§18）

corpus 全体で生成された THEME_CANDIDATE は 9 件。component 別の `OTHER` 使用数は次のとおり。

| component | OTHER を要した候補数 |
|---|---|
| driver | 0 |
| channel | 0 |
| domain | 0 |
| consequence | 0 |

現行 template は Foundation の既定 category（DEMAND_SHIFT / VOLUME_DEMAND / REGION / MACRO_STATISTIC）で表現できており、
Foundation の語彙拡張要求は本 gate では発生していない。

## 18. 機密・境界（§20 / §21）

- 本 gate の成果物（test 3 file ＋ 本書）に、保有銘柄一覧の名称・ticker、機密由来の文章、実在の受益企業連鎖、
  machine 固有 path、credential 文字列が無いことを test で固定している。
- discovery は store / Foundation / proposal store / bridge を書かず、network・LLM・類似度・現在時刻・乱数を使わない
  （B4C boundary test で固定済み。本 gate でも run 中に tmp へ何も書かないことを確認している）。
- 本 gate は config.yaml / .github / scripts / docs/v2 / GitHub Pages を参照も変更もしていない。

## 19. 限界（§27）

1. corpus は合成であり、実データ分布を代表しない。本書の数値は実運用の精度推定ではない。
2. 公開 ruleset の rule は 7 本（うち 1 本は DEPRECATED）。coverage は評価していない。
3. 既存 Theme との dedup は read-only の duck-typed resolution で検証しており、Foundation store の実読み出しは行っていない
   （本 gate は Foundation に触れない方針のため）。
4. L2 は限定 text 面のみを対象とする。本文・PDF 本体・表の走査は契約に存在しない。
5. 日本語の形態素解析は行わない。非 ASCII token は正規化後の部分一致で判定する。

## 20. supervisor 決定事項（§29）

| id | 論点 | 本 gate での扱い |
|---|---|---|
| D-B4D-1 | MIN_DISTINCT に ORIGIN_KEY 次元が無く、同一 origin の 2 表現だけで THEME_CANDIDATE が成立しうる | 契約どおりとして扱い、診断 `ORIGIN_KEYS:1` を確認。次 version で ORIGIN_KEY 次元を足すか、THEME rule に必須化するかは supervisor 判断 |
| D-B4D-2 | 最長一致優先のため、同一面で短い alias が長い alias に包含されると短い側の entity が落ちる（`Japan and Bank of Japan` → country:jp が落ちる） | 保守側（false negative 方向）のため現状維持。位置単位の一致に変えるかは supervisor 判断 |
| D-B4D-3 | adapter の入力単位診断（AMBIGUOUS / INACTIVE / SUPERSEDED / DEPRECATED_TAXONOMY_TOKEN / UNKNOWN_*）が `DiscoveryRunReport` に集約されない | 現状は record 側にのみ存在。運用可観測性のため run report へ集約するかは supervisor 判断 |
| D-B4D-4 | taxonomy 0.2.0 に空白入りの `data center` が alias として無い（`data centre` / `datacenter` のみ） | 本 gate では変更しない。次 taxonomy version で追加するかは supervisor 判断 |
| D-B4D-5 | 同一 identity core で逆向きの consequence を持つ 2 rule は 2 候補 ＋ 相互 dedup review になる | 人間 arbitration 前提として現状維持で良いかを確認したい |

## 21. 本 gate の成果物

| path | 種別 |
|---|---|
| `tests/intelligence/test_theme_discovery_e2e.py` | 新規（golden corpus ＋ 混同行列 ＋ firewall / decision / dedup / hygiene） |
| `tests/intelligence/test_theme_discovery_false_positive.py` | 新規（L2 / taxonomy 階層 / entity lifecycle / negative / MIN_DISTINCT stress） |
| `tests/intelligence/test_theme_discovery_replay.py` | 新規（PIT 境界 / 旧 version replay / 決定性） |
| `docs/databank/PHASE6_THEME_DISCOVERY_E2E_GATE.md` | 新規（本書） |
| `CHANGELOG.md` | 追記のみ |

runtime file と knowledge snapshot は変更していない。
