# PHASE 6 THEME SEMANTICS + AUTHORITY CONTRACT（P6-A1・Family A の凍結）

## 1. 目的

本書は Phase 6（Theme）の **P6-A1 gate** の成果物であり、Family A（D1 Theme の形式意味論、D2 Theme vs
Narrative、D3 Theme vs Context、D4 Theme vs Compass、D16 人間 review / governance 境界）を凍結する。
storage schema・identity hash・field 名・enum 名・閾値は凍結しない（Family B / C / D の後続 gate）。
実装（ThemeRecord / ThemeStore / discovery / lifecycle / graph / LLM）は含まない。本書は設計事項であり、
変更は監督者の決定による。作成日 2026-09-19。

## 2. 凍結済みの上流決定（再開しない）

- P6-A0（`P6_A0_THEME_FOUNDATION_AUDIT_COMPLETE`）と P6-A0.5（`P6_A0_5_FOUNDATION_PORT_POLICY_FROZEN`、
  anchor `61b5229c68fa82c8506250f37e4e0437f5e378b8`、`PHASE6_FOUNDATION_DECISIONS.md` F-1〜F-10、D0 解決）。
- Phase 6 は現 branch（curated bundle）で続け、歴史 runtime source を土台に必要としない。歴史資産は個別認可まで参照のみ。
- Theme は新しい内部 intelligence 層。P4 / P5 を変更せず、その authority にならない。土台（identity → evidence →
  支持 / 反証 → 不変履歴 → 点時刻再構成 → change 表現）が discovery / lifecycle / graph に先行する。
- Compass `EvidencePackage` は再利用しない。Theme 履歴の黙った書換え禁止。Theme authority の永続化は P5 journal
  規律以上。legacy theme_learning は precedent ではない。P5 較正は Theme を変更しない。Theme identity ≠ taxonomy slug。
  PRIMARY / OBSERVATIONAL evidence と DERIVED / INTERPRETIVE context を区別する。

## 3. Theme の形式意味論（D1）

### 3.1 定義

**Theme とは、内部知識として保持される、構造化された持続的な市場 / 投資の仮説であって、次を満たすものである。**

1. **主題と機構**: 何についての仮説か（phenomenon / subject）と、driver がどの transmission channel を通じて
   どの affected domain に及ぶかを、構造化された形（controlled vocabulary または evidence 参照付きの短い structured
   statement）で述べる。裸の label（"AI"）は機構ではない。
2. **機構の確からしさの明示**: 機構は §12 の確度 class（観測された連関 / 仮説 / evidence に支持された機構 /
   source の明示的因果主張）のいずれかを必ず宣言し、不確実性を表現できる。
3. **scope の明示**: 対象領域（地域・産業・資産 class・期間の枠）を宣言する（粒度は D14）。
4. **時間を跨ぐ持続性**: 1 つの観測 / event / session を超えて意味を保つことが期待される仮説である（§13）。
5. **evidence 参照の能力**: PRIMARY / OBSERVATIONAL evidence（Fact、market Observation、SourceDocument / NewsItem、
   provenance 十分な factual Statement）への参照を、役割（支持 / 反証 / 文脈 等）と evidence 自身の時点、付与時点、
   provenance 付きで蓄積できる。
6. **反証可能性**: 反証 evidence・limitations・無効化概念を保持できる（§14）。
7. **不変履歴**: 生成・evidence 追加・訂正・状態観測が点時刻で再構成できる履歴を持つ（Family C）。
8. **authority の位置**: Theme は内部 Theme 知識であり、production interpretive authority（Compass DNA / MorningBrief /
   MarketSignal）ではない（§15）。

### 3.2 各語の意味

- **persistent（持続的）**: 「多くの記事に出る」ではなく、仮説の内容が複数の観測 / event / session にわたって
  意味を保つと**期待され**、かつ履歴として保持されること。数値閾値は定めない（§13）。
- **evidence-backed（evidence に裏付けられた）**: Theme の主張が、id と時点と provenance を持つ primary evidence
  への参照によって支持 / 反証されること。Compass 出力・MorningBrief・prediction / evaluation / calibration・LLM 出力・
  keyword 一致は evidence ではない。
- **hypothesis / mechanism（仮説 / 機構）**: 「X が Y を通じて Z に影響する」という、反証可能で、観測可能な帰結を
  持つ構造。因果の断定ではなく、確度 class 付きの主張。
- **links multiple observations through time（複数の観測を時間を通じて結ぶ）**: 相異なる時点の evidence 参照が
  同一の機構に関連付けられ、それらの関係（支持 / 反証）が保持されること。同一時点・同一 source の多数の言及は
  「複数の観測」ではない。

### 3.3 資格判定（後続 validator の判定基準。validator は未実装）

| 判定 | 条件 |
|---|---|
| **QUALIFIES_SEMANTICALLY** | Q1 主題 ＋ 機構が構造化されて述べられている（label のみは不可）／Q2 機構確度 class が宣言されている／Q3 scope が宣言されている／Q4 複数の観測 / event / session を跨ぐ仮説である／Q5 **相異なる evidence 時点**かつ**相異なる source / 観測**に由来する primary evidence 参照が複数ある（「複数」は定義から導かれる意味論的最小であり、調整閾値ではない）／Q6 無効化概念（何が観測されれば弱まる / 崩れるか）を述べられる／Q7 予測・推奨・Compass rule・keyword・単一 event のいずれでもない／Q8 すべての evidence 参照が provenance を持つ |
| **THEME_CANDIDATE_POSSIBLE**（validator 語彙では INSUFFICIENT_EVIDENCE） | Q1〜Q3・Q6〜Q8 を満たすが、Q5 が未達（evidence が無い、単一時点のみ、単一 source のみ）。候補として保持し、evidence の蓄積を待つ |
| **DOES_NOT_QUALIFY** | Q1（機構なし）、Q4（本質的に単一 event / 単一 session の状態）、Q7（予測 / 推奨 / rule / keyword）のいずれかに違反、または evidence 参照が原理的に不可能（LLM 命名のみ、taxonomy slug のみ） |

## 4. Theme は keyword の袋ではない（§2 凍結）

次だけでは Theme は成立しない: 同じ keyword の反復、同じ topic を扱う多数の記事、sector の人気、ticker の上昇、
taxonomy label の一致、LLM が概念を命名したこと、Compass が言及したこと、MorningBrief が言及したこと、
prediction の成績が良いこと。反復・件数は後日の **discovery の手掛かり**にはなりうるが、Theme の意味論的証明ではない。

## 5. 非目標

Theme は次を含まない / 行わない: 散文 narrative の生成（Phase 7）、方向予測・target return・horizon・正誤 /
hit-miss・較正 feedback（P5）、売買推奨・position sizing・price target（§11）、Compass DNA の変更・第二 DNA 化（§9）、
taxonomy slug との同一視、entity 推定の断定（Family B / D）、lifecycle 状態名の定義（P6-C）、graph edge type（P6-D）、
自動 discovery / LLM 生成（P6-B 以降）、顧客 / 公開出力。

## 6. 意味論の構成要素（§3 分類。field 名は未凍結）

| 要素 | 分類 | 備考 |
|---|---|---|
| A 主題 / 現象 | REQUIRED_FOR_THEME_SEMANTICS | 何についての仮説か |
| B 機構（driver → channel → affected domain → 観測可能な帰結）＋ 確度 class | REQUIRED_FOR_THEME_SEMANTICS | 監督者 bias どおり機構が核。確度 class は必須（§12） |
| C scope | REQUIRED_FOR_THEME_SEMANTICS | 地域 / 産業 / 資産 class / 期間枠。粒度は D14 |
| D 時間的持続性（期待） | REQUIRED_FOR_THEME_SEMANTICS | 意味論的要件。lifecycle 状態ではない（§13） |
| E 支持 evidence 参照 | REQUIRED capability。QUALIFIES には内容必須、候補には任意 | 役割・時点・provenance 付き |
| F 反証 evidence 参照 | REQUIRED capability。内容は任意（0 件は正当なデータ） | 0 件を確証と解釈しない |
| G 影響を受ける domain / entity | domain は B の一部として REQUIRED。entity 連結は LATER_PHASE_CONCERN（Family B / D） | 推定 entity は provenance 付き inferred relationship（§11） |
| H limitations / 不確実性 / 無効化概念 | REQUIRED capability。候補では任意、reviewed では governance 上必須（§14） | |
| I 状態 / lifecycle | LATER_PHASE_CONCERN（P6-C） | 状態名を今は作らない |
| J narrative / 散文 | MUST_NOT_BE_PART_OF_THEME_AUTHORITY | label・短い説明は OPTIONAL_SEMANTIC_METADATA（§8） |
| 表示用 label / 短い description | OPTIONAL_SEMANTIC_METADATA | authority にならない。LLM 提案なら provenance 必須 |
| taxonomy 分類 | OPTIONAL_SEMANTIC_METADATA（採否は P6-B） | identity ではない |

## 7. Theme vs Topic（§5）

- **Topic** は「何について語られているか」の label（"AI"、"copper"、"Banks"）。主語はあるが機構・scope・
  反証可能性が無い。News Bank の `ThemeReference.theme_label` / `ClassificationDimension.THEME`、Evidence の
  `Statement.themes`、legacy `config.yaml themes` は**すべて topic / 分類 tag**であり、本書の Theme ではない
  （名前は変更しないが、Phase 6 の Theme と読み替えない）。
- topic が Theme **候補**になりうる条件: 誰か（人間・rule・LLM 提案）が **機構**（driver → channel → domain）と
  scope と無効化概念を構造化して述べ、primary evidence 参照が付き始めたとき。それまでは topic のまま。
- 例（意味論の粒度説明のみ。事実の主張ではない）: topic "AI" ↔ 候補「AI infrastructure の拡張が data-center の
  電力需要を増やし、発電・送電・冷却・capex に圧力をかける」。topic "copper" ↔ 候補「電化と grid / data-center
  投資が銅需要を増やす一方、鉱山供給の反応は遅い」。

## 8. Theme vs Event（§6）

- Event は点的（政策発表、決算、金利決定、供給障害、買収、規制）。Theme は複数の event / 観測を跨いで持続する。
- **1 つの event は Theme を生成しない。** event は Theme 候補を**trigger** し、あるいは既存 Theme を**支持 / 反証**
  する evidence になる。例外的な event が機構を露わにすることはあるが、持続性（Q4）と複数観測（Q5）の要件は
  免除されない。event 単独は最大でも THEME_CANDIDATE_POSSIBLE。

## 9. Theme vs Context（D3）

- `ContextItem` は session 固有・決定論 rule 導出・Fact から構築・P4 意味論に結合・設計上非因果（`Relationship`
  に因果値なし）。Theme は多 session・機構志向・履歴保持・evidence 蓄積。
- **凍結**: ContextItem は Theme ではない。ContextItem は将来、明示的に **DERIVED / INTERPRETIVE CONTEXT** としてのみ
  消費されうる（primary evidence ではない。primary と同等に数えない）。その認可は Family B。
- **Theme は Context 無しで完全に存在できる（YES）。** 土台は Context を要求しない。
- Context → Theme の自動昇格は存在しない（Context が何 session 続いても Theme を作らない）。
  Theme → Context / P4 の依存は Phase 6 に存在しない。
- 1 session の状態（例: 円安の 1 session 観測）は Context に属する。持続が期待される機構を述べ、後に十分な evidence を
  得たときに限り Theme 候補になる。

## 10. Theme vs Narrative（D2）

- **Theme（authority）**: 構造化された意味論（主題・機構・確度 class・scope）、evidence 関係（役割・時点・provenance）、
  limitations・無効化概念、点時刻履歴。
- **Narrative（Phase 7）**: 散文、順序付け、説明、読者別の framing、圧縮、storytelling。
- 自然言語の label や短い description は metadata として存在してよいが、**Theme の意味論的 authority にならない**。
  Theme は生成 prose に依らず、構造化意味論と evidence だけから再構成・理解できなければならない。
- Theme 層に prose 生成器を置かない。Compass の language 規律（因果語・助言語・数値目標の禁止）を Theme が
  再実装する状況を作らない。Phase 7 は本書で実装しない。

## 11. Theme vs Compass（D4。Phase 6 で恒久）

| 項目 | 凍結 |
|---|---|
| Compass | 当日 session の解釈、production interpretive authority、P4 凍結経路、MorningBrief の源 |
| Theme | 持続的な内部仮説 / 機構層 |
| Theme は CompassOutlook を evidence authority として消費しない | ○ |
| Theme は MorningBrief を evidence authority として消費しない | ○ |
| Compass は Phase 6 で Theme を消費しない | ○ |
| Theme は Compass DNA（`market_rules.yaml` / `market_principles.py`）を変更しない・第二 DNA にならない | ○ |
| Theme は MarketSignal と P5 identity に影響しない | ○ |
| 両者は下位 evidence（Fact / Observation / Document）を独立に共有してよい | ○ |
| Compass の `rule_ref` / `Implication` / `counter_context_ids` は Theme の根拠ではない（参照 provenance にはなりうる） | ○ |

将来の Theme → Compass / Brief 統合は Phase 6 完了後の**別の明示 gate**を要する。

## 12. 機構の意味論（§4）

### 12.1 確度 class（名称は暫定）

| class | 意味 | 成立に必要なもの |
|---|---|---|
| OBSERVED_ASSOCIATION | 観測の共起・相関が記録されているだけ | 複数観測の記録。**因果を主張しない** |
| HYPOTHESIZED_MECHANISM | driver → channel → domain が述べられているが、帰結の evidence は未確認 | 構造化された機構の記述（人間または provenance 付き提案） |
| EVIDENCE_SUPPORTED_MECHANISM | 機構が予期する観測可能な帰結について、相異なる時点・source の primary evidence が支持し、反証が検討されている | 支持 evidence の参照（帰結に対応するもの）＋ 反証の有無の明示 |
| EXPLICIT_SOURCE_CAUSAL_CLAIM | ある source が因果を明示的に主張している（attribution） | source への参照。**これ自体は class を上げない**（誰が言ったかの記録） |

### 12.2 規則

- **co-occurrence ≠ causality。** OBSERVED_ASSOCIATION は反復・件数・期間の長さによって自動で上位 class にならない。
- HYPOTHESIZED → EVIDENCE_SUPPORTED への変更は、(a) 機構が予期する帰結に対応する evidence、(b) 相異なる時点、
  (c) 反証の検討、を伴う**明示の判断**であり、reviewed Theme では人間 decision（§16）。候補上の class は宣言者
  （人間 / rule / LLM 提案）の provenance 付き宣言であり、system が件数で引き上げない。
- 反証 evidence は class を引き下げる根拠になりうるが、引き下げも自動ではなく履歴に残る判断である。
- 機構は概念的に **driver・transmission channel・affected domain・expected observable consequences** を持つ
  （schema は Family B）。expected observable consequences が無い機構は反証不能であり Q6 を満たさない。
- 不確実性は prose ではなく class ＋ limitations ＋ 反証参照で表す。

## 13. 持続性の意味論（§12）

- 数値（日数・記事数・evidence 数・score）を定めない。
- **意味論的持続性**: 仮説の内容が、1 つの観測 / event / session を超えて意味を保つと期待されること。
  「今日の地合い」「今週の決算反応」は Context / event であり、それらを説明する**機構**が Theme である。
- **lifecycle 状態**（強まる / 弱まる / 崩れる 等）は P6-C の別概念。本書は状態名を作らない。
- 持続性の期待は宣言（Q4）であり、実際に持続したかは履歴と evidence（Family C の再構成）が示す。

## 14. 支持 / 反証 / limitations の意味論（§13）

- Theme は**反証可能・挑戦可能**でなければならない。model は支持 evidence・反証 evidence・limitations /
  不確実性・無効化概念を保持できる（役割 enum は P6-A2）。
- 反証が既に存在することは要求しない。**反証 0 件は正当なデータ**である。ただし**反証の不在を確証と解釈しない**。
- limitations: **能力は必須**（保持できること）。**非空の内容**は候補生成時には必須でなく、reviewed / accepted
  Theme の governance 要件（§16）とする。
- 無効化概念（何が観測されれば Theme が弱まる / 崩れるか）は Q6 として意味論の要件。

## 15. authority 階層（§14。名称は暫定）

| level | 内容 | Phase 6 での到達 |
|---|---|---|
| L0 OBSERVATION / SOURCE EVIDENCE | Fact / Observation / SourceDocument / NewsItem / factual Statement（QA 済み） | Theme の入力 |
| L1 DERIVED THEME CANDIDATE | rule / cluster / LLM 提案 / 人間下書きによる候補。provenance 必須 | 到達可（自動生成可、§16 B） |
| L2 REVIEWED / ACCEPTED INTERNAL THEME | 人間 decision により受理された内部 Theme。limitations 非空 | 到達可（人間のみ） |
| L3 PRODUCTION INTERPRETIVE AUTHORITY | Compass DNA / MorningBrief / MarketSignal に相当する production authority | **到達不可**（Phase 6 の Theme は reviewed でも内部知識のまま） |

昇格規則（L1 → L2 の判断基準の詳細、L2 → L3）は定義しない。自動昇格は存在しない。却下 / 引退した候補も履歴から消えない。

## 16. 人間 governance（D16）

**採用: Option B。** system は canonical な **INTERNAL CANDIDATE** Theme（L1）を自動で作成してよいが、
reviewed / accepted（L2）は人間の承認を要する。明示: `automatic candidate ≠ reviewed Theme`、
`reviewed Theme ≠ Compass authority`。

| 自動 system がしてよいこと | 自動 system がしてはならないこと（人間 decision 必須） |
|---|---|
| evidence の検出と候補への付与提案 | production authority の生成（Phase 6 では誰にも不可） |
| 候補 Theme の提案・作成（L1、provenance 付き） | 相異なる Theme identity の黙った merge |
| 候補間の関係・重複候補の提示 | Theme identity の黙った split |
| 反証候補の提示 | Compass DNA への昇格 |
| label / description の提案 | 曖昧な dedup を事実として確定 |
| 機構 class の変更提案（evidence 参照付き） | 推定因果の確立因果への変換、reviewed Theme の class 変更 |
| | L1 → L2 の受理、L2 の引退 / 再開、reviewed Theme の evidence 役割の訂正 |

人間 decision は理由と対象 record を伴い履歴に残る（形式は Family C）。historical formal-review subsystem は
再利用しない（原則のみ継承: auto approval なし、reason 必須、撤回は履歴、助言語なし）。

## 17. LLM authority 境界（§16）

LLM は将来、label 提案・機構の要約・候補関係の提案・反証候補の提示・dedup review の補助をしてよい。
LLM 出力**単独**では、evidence の成立、因果の確立、identity merge の確定、reviewed 状態の付与、production
authority の付与のいずれもできない。LLM 由来の意味論的提案はすべて「提案」であることを示す provenance を持つ。
LLM 提案が canonical 意味論に入るのは、evidence 参照と人間 decision（L2）または rule 検証（L1 候補）を経たときのみ。
A1 では LLM を実装しない。

## 18. 粒度の予告（D14 は後続。暫定境界のみ）

本定義は macro 構造機構、産業機構、技術 / infrastructure 機構、commodity 需給機構のいずれの規模でも成立する
（機構・scope・持続性・evidence の要件は同じ）。**企業固有の投資 thesis は既定の Theme 定義の外**に置く
（Phase 9 Thesis Tracker の領域）。階層（親子）は定義しない。

## 19. 資格判定表（§18。意味論の分類のみ。機構が事実であるとは主張しない）

| # | 例 | 判定 | 理由 |
|---|---|---|---|
| 1 | "AI" | NOT_THEME | topic label。機構・scope・反証可能性なし |
| 2 | "Copper" | NOT_THEME | 資産 / commodity の名前。機構なし |
| 3 | "Banks" | NOT_THEME | sector label |
| 4 | AI capex に関する 1 本の記事 | NOT_THEME（evidence 候補） | 単一 source・単一時点の evidence。Theme 候補の trigger / 支持にはなりうる |
| 5 | 1 回の利上げ | NOT_THEME（event） | 点的 event。Theme を支持 / 反証する evidence にはなりうる |
| 6 | AI keyword の反復言及 | NOT_THEME | 件数は機構でも evidence でもない（§4）。discovery の手掛かりに留まる |
| 7 | data-center 電力需要の持続的機構 ＋ 複数の独立 evidence | QUALIFIES_SEMANTICALLY | 主題・機構・scope・持続性・相異なる時点 / source の evidence・無効化概念を備えうる |
| 8 | 銅の需給機構 ＋ 支持 evidence ＋ 反証 evidence | QUALIFIES_SEMANTICALLY | 7 と同じ。反証を保持していることは要件充足の例示 |
| 9 | "TOPIX will rise tomorrow" | NOT_THEME | 短期方向予測（P5 の領域）。機構でも持続でもない |
| 10 | "Company X is a buy" | NOT_THEME | 投資推奨（§11 禁止）。企業固有 thesis は Phase 9 |
| 11 | 円安を示す 1 つの ContextItem | NOT_THEME | session 固有の derived context（D3）。primary evidence でもない |
| 12 | 円安が輸入 input cost に及ぶという多 session 仮説 ＋ evidence | QUALIFIES_SEMANTICALLY（evidence が相異なる時点 / source を満たす場合）／さもなくば THEME_CANDIDATE_POSSIBLE | 機構（driver 為替 → channel 輸入価格 → domain input cost）と持続性がある |
| 13 | LLM が命名した Theme label（evidence なし） | NOT_THEME | 提案でしかない（§17）。evidence 参照が不可能な限り DOES_NOT_QUALIFY |
| 14 | evidence の付かない taxonomy slug | NOT_THEME | 分類語彙（§7）。identity にも Theme にもならない |

## 20. 意味論的不変条件（後続 test 用の番号付き）

1. Theme ≠ keyword / topic（label のみでは資格を満たさない）。
2. Theme ≠ 単一 event（event は trigger / evidence にとどまる）。
3. Theme ≠ ContextItem（Context は session 固有の derived 解釈）。
4. Theme ≠ Narrative（prose は authority ではない）。
5. Theme ≠ Prediction（方向・target・horizon・正誤を持たない）。
6. Theme ≠ Recommendation（BUY / SELL / weight / price target / sizing を持たない）。
7. Theme ≠ Compass rule（DNA を変更せず第二 DNA にならない）。
8. Theme は evidence 参照の能力を必須とする（参照は id・時点・provenance を持つ）。
9. Theme は反証 evidence の能力を必須とする（0 件は正当）。
10. Theme は点時刻で再構成可能な不変履歴を持つ。
11. 連関 ≠ 因果（OBSERVED_ASSOCIATION は件数 / 反復で上位 class にならない）。
12. 自動候補 ≠ reviewed Theme。
13. reviewed Theme ≠ production interpretive authority（Phase 6 では L3 到達不可）。
14. LLM 出力単独では evidence・因果・merge・reviewed・authority を確立できない。
15. 反証の不在 ≠ 確証。
16. taxonomy slug ≠ Theme identity（分類は任意 metadata）。
17. Theme は Context 無しで存在できる。
18. Theme は Phase 6 で P4 / P5 を変更せず、P4 / P5 から import されない。
19. 機構確度 class の宣言は必須であり、不確実性は prose でなく class ＋ limitations ＋ 反証で表す。
20. すべての evidence 参照は PRIMARY / OBSERVATIONAL と DERIVED / INTERPRETIVE を区別する class を持つ。
21. Compass 出力・MorningBrief・prediction / evaluation / calibration は Theme evidence ではない。
22. 同一時点・同一 source の多数の言及は「複数の観測」ではない。
23. 企業固有 thesis は既定の Theme 定義の外（Phase 9）。
24. 人間 decision（受理・merge・split・引退・class 変更）は理由と対象を伴い履歴に残り、自動では起きない。
25. 却下 / 引退した候補も履歴から削除されない。

## 21. 既存語彙との関係（衝突監査）

現 branch の `databank.news_model.ThemeReference` / `ClassificationDimension.THEME` / `NewsQuery.theme`、
`evidence.model.Statement.themes`、legacy `config.yaml` の themes / durable_themes / macro_themes /
theme_relations / causal_rules、`data/theme_learning`、tank 由来の INTERPRETED `themes` は、いずれも
**topic / 分類 tag または legacy 挙動**であり、本書の Theme ではない。名前は変更せず、意味も読み替えない。
`evidence_qa` の docstring にある「Theme Engine が利用する前に通す関門」は本書と整合する（Theme は QA 済み
evidence を消費する側）。`src/intelligence/__init__.py` / `MORNING_DELIVERY_SPEC.md` §14 / production bundle guard の
`themes` 排除と矛盾しない。

## 22. 未解決（Family B / C / D）

- **B（P6-A2）**: D5 evidence kind / class の語彙、D6 identity model（root / lineage、内容住所、fork / merge）、
  D9 役割 enum と missing evidence の表現、D15 entity 連結の境界（directly evidenced vs inferred）、D19 市場確認
  series の対応表、D17 の evidence 側二重時点。機構の schema（driver / channel / domain / consequences の表現）。
- **C（P6-A3）**: D7 revision / event model、D8 append-only authority と derived index、D17 の再構成規則、
  人間 decision record の形式。
- **D（P6-B 以降）**: D10 graph、D11 lifecycle 状態、D12 discovery、D13 dedup、D14 粒度 / 階層、D18 Morning Brief
  消費、D21 legacy 節の扱い、D22 Phase 7 出力契約、taxonomy 採否、L1 → L2 の判断基準の詳細。

## 23. 次 gate

**P6-A2 Theme Identity ＋ Evidence Contract**（Family B）。本書は P6-A2 の入力である。

P6-A2 の結果: Family B（D5 / D6 / D9 / D15 / D19 / D17 evidence 側）は
`PHASE6_THEME_IDENTITY_EVIDENCE_CONTRACT.md` で凍結（`P6_A2_THEME_IDENTITY_EVIDENCE_CONTRACT_FROZEN`）。
本書 §22 の B 行は解決済み。本書の意味論は変更されていない。次 gate は P6-A3（Family C）。

P6-A3 の結果: Family C（D7 / D8 / D17）は `PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md` で凍結
（`P6_A3_THEME_PERSISTENCE_REVISION_CONTRACT_FROZEN`）。本書 §22 の C 行は解決済み。次 gate は P6-A4a（実装）。
