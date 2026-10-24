# PHASE 7 / P7-A0 — NARRATIVE INTELLIGENCE ARCHITECTURE ＋ EXISTING-SYSTEM AUDIT

READ-ONLY の architecture 監査。Phase 7 の runtime・model・永続化・LLM 接続は作っていない。Phase 6（凍結 anchor `5ef313a`）・
P4・P5・公開出力は変更していない。本書の変更は文書と CHANGELOG だけ。

基準: Phase 6 final freeze `5ef313a`、Phase 5 semantic freeze `edbd0f2`。branch は `claude/investment-intelligence-phase6`。

---

## 1. 結論

**Phase 7 Narrative Intelligence は、既存の凍結された層を変えずに実装できる。blocker は無い。** 判定:
`P7_A0_ARCHITECTURE_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_DECISIONS`。

推奨の骨子（すべて監督判断待ち。§28）:

1. **authority**: Narrative は**派生 artifact**（新しい authority を作らない）。永続化は初期 gate では行わず、将来の consumer
   統合 gate で任意の**運用 emission journal**（監査用・入力にしない）を足せる形にする（§5 の案 C。初期は A と同じ振る舞い）。
2. **定義**: 明示された subject・scope・時間窓・cutoff について、上流の intelligence を決定論的に合成し、すべての文を上流の
   record に束縛した構造（§6）。予測・推奨・要約・書き直しではない。
3. **型**: 初期は `THEME_STATE`（1 つの reviewed Theme）と `THEME_SET`（明示された reviewed Theme の集合と、その間の明示的な
   relation）の 2 つ。`EVIDENCE_LINKED` は次の候補、MARKET_STATE は P4 統合の方針の後、SCENARIO は範囲外（§7）。
4. **事実と解釈**: すべての文に閉じた認識 class（観測・記録された解釈・派生・未審査の文脈・不確実性・仮説）を持たせ、描画で
   class を格上げしない（§9）。
5. **LLM**: 初期の Phase 7 は LLM を使わない。構造も描画も決定論的に作る。LLM は後の任意 gate で「検証済み構造の言い回しの
   提案」か「未審査の代替説明の提案」に限る（§16）。
6. **選定**: 明示の caller 要求だけで Narrative を作る。決定論的な「適格性一覧」（順位なし）を補助として出せる（§18）。
7. **入力**: Phase 6 の PIT 入口（resolver・change・lifecycle・relation resolver）を主入力にし、P4 の観測層（Fact・Context・
   Internals・EvidencePackage）は文脈に限る。P5 の成果物は使わない（§4）。

## 2. 既存システムの棚卸し

調査範囲: repository 全体（`main.py`・`src/`・`tests/`・`docs/`・`knowledge/`・`scripts/`）と、参照のために履歴 branch
（`claude/investment-intelligence-phase0-rvdplu`、Phase 0〜4 の凍結履歴。本 branch の祖先ではない）を `git show` で読んだ。

**branch の事実**: 本 branch が追跡する `src/intelligence/` の package は 19 個（compass・context・core・databank・enrichment・
evidence・evidence_qa・facts・ingestion・internals・market・normalization・predictions・reports・review・sources・themes・
theme_intelligence ＋ `__init__`）。`corpus`・`corpus_research`・`decision`・`formal_review`・`thesis`・`screening`・
`personalization`・`replay` 等の source は**この branch に無い**（履歴 branch だけ）。P4 の仕様書（`PHASE4_ENTRY_CONTRACT.md`・
`FACT_LAYER_SPEC.md`・`CONTEXT_ENGINE_SPEC.md`・`COMPASS_GENERATOR_SPEC.md`・`MARKET_SIGNAL_SPEC.md`）も履歴 branch だけにあり、
本 branch では `PHASE5_ENTRY_CONTRACT.md` と Phase 6 文書が P4 の authority 境界を引き継いでいる。

| 構成要素 | 場所 | 分類 | 理由 |
|---|---|---|---|
| legacy の market narrative（見出し・結論・因果連鎖・要因・見通し・リスク・示唆） | `src/analysis/market_narrative.py` | REFERENCE_ONLY（節の構成）／ CONFLICTING（code） | 固定文をデータに関係なく出す。同日の値動きから証拠なしに原因を帰属 |
| legacy の strategic narrative | `src/analysis/strategic_narrative.py` | REFERENCE_ONLY（方向整合の考え）／ CONFLICTING（code） | 利回り 1 本の上昇から中銀の期待後退を断定する等、証拠なき因果 |
| legacy の LLM 文章化 | `src/analysis/llm_enhancer.py` と呼び出し元（scenario・ai_summary・themes_forecast 等） | CONFLICTING | vendor SDK を直接呼び、LLM の文が検証も印も無く規則文を置き換える |
| legacy の scenario・確率・regime score・news ranking・銘柄選定 | `src/analysis/scenario*.py`・`market_regime.py`・`news_ranking.py`・`top_picks.py` 等 | CONFLICTING | 重み付き和の擬似確率・score を authority として提示、推奨相当 |
| legacy の theme 学習（勝率の feedback） | `src/analysis/theme_learning`・`future_intelligence.py` | CONFLICTING | 可変 JSON を 1 日に何度も書き換え、勝率で確信度を補正する自己強化（PIT でない） |
| legacy の条件付き if-then・根拠つき確信度・鮮度 / 異常の表示・出典一覧・「なぜ今日か」 | `future_probability.py`・`future_intelligence._confidence_score`・`data_freshness.py`・`utils.SourceRegistry`・`why_today.py` | REFERENCE_ONLY | 考え方は有用（データ欠落で条件が偽になる・確信度 ＝ 証拠の充足で確率ではない） |
| legacy の描画（Markdown・HTML・mobile・PDF） | `src/report/*` | LEGACY | 公開 Pages と通知に直結。Phase 7 は接続しない |
| legacy の営業 / 顧客向け module | `sales_*`・`call_priority` 等 | UNRELATED / LEGACY | 対象が違う |
| P4 Compass の NarrativePlan・生成器・検証器・quality gate | `src/intelligence/compass/*` | REFERENCE_ONLY | 決定論の既定・LLM 出力は信頼しない・閉じた語彙・grounding / 言語規則の検証の規律は手本。ただし P4 の翌日見通しの生成器であり Phase 7 の narrative ではない |
| P4 MorningBrief・MarketSignal・delivery | `src/intelligence/reports/*` | REFERENCE_ONLY（規律）／入力は §4 | `text` と `display_text` の分離・閉じた表・理由 code・時計は端で 1 回・単一の writer は手本。凍結された公開契約なので Phase 7 から書かない |
| evidence の基本型（事実 / 分析 / 予測文、支持 / 反証 link、反論、無効化条件） | `src/intelligence/evidence/model.py`・`invariants.py` | REUSE（候補） | 文ごとの証拠参照・反論・無効化の既存の型。採用は A1 で決める |
| vendor 中立の LLM 境界 | `src/intelligence/core/contracts.py`（`LLMProvider`） | REUSE（将来の任意 gate） | 利用不可なら規則のフォールバック、証拠参照つきの文章化だけ。実装は存在しない |
| Phase 6 B7 の provider 境界 | `theme_intelligence/llm_provider.py` | REFERENCE_ONLY | Fake / Recorded だけ。Phase 7 は Phase 6 の module を再利用して書き換えない |
| 顧客 / 公開の語彙の閉包 guard・機密 guard | `tests/intelligence/test_customer_display_vocabulary.py`・`test_confidential_guard.py` | REUSE（guard の型） | Narrative の出力と fixture にそのまま適用できる |
| Phase 6 の Theme model に narrative 欄が無いことの test | `test_theme_model.py`・`test_theme_foundation_e2e.py` | REFERENCE_ONLY（境界） | Theme は構造のまま、文は Phase 7（A1 §10） |
| 履歴 branch の corpus_research（why / risk / outlook の型、明示の接続語だけで結ぶ構造） | 履歴 branch | REFERENCE_ONLY | 最良の「なぜ」「リスク」の語彙だが機密の Compass 本文の分析。本 branch に無く、入力にしない |
| 履歴 branch の shadow_review の説明 template（未知 rule は例外） | 履歴 branch | REFERENCE_ONLY | 決定論の説明の手本 |
| 履歴 branch の thesis / screening / personalization | 履歴 branch | UNRELATED（P8 / P9 / P10） | docstring だけの骨組み |
| 語の偶然の一致（summary・cause・mechanism・context の変数名など、約 90 行） | 各所 | UNRELATED | 意味上の narrative ではない |

**名前の衝突（CONFLICTING・要判断）**: P4 は既に「NARRATIVE」を段階名に使っている（`NarrativePlan`・`NarrativeGenerator`・
`DeterministicNarrativeGenerator`・`LLMNarrativeGenerator`。P4 の段階 `FACT → CONTEXT → NARRATIVE → OUTLOOK → COMPASS`）。
Phase 7 の型名はこれと衝突させない（§21）。

**legacy から学ぶこと（概念だけ）**: 結論 → 何が動いたか → なぜ（要因と連鎖）→ 押し下げと支え → 条件つきの注目点 → リスク
→ 示唆 → 出典の骨組み。要因を対象の実際の方向と照らす。禁止する因果の言い回しの一覧。事実と分析の凡例。取得できないものは
「取得不可」と書く。確信度は証拠の充足であって確率ではない。**避けること**: データと無関係な固定文、証拠 id の無い原因の帰属、
擬似確率・星・「最重要」の固定、LLM による置き換え、銘柄推奨と構えのラベル、勝率の feedback、部分文字列一致の theme、深い
場所での時計の読み取り、全体 config、例外の握りつぶし（fail open）、生成中の副作用。

**結合の危険（legacy）**: 暗黙の現在時刻（`main` と collector 群）、全体 `config.yaml` の theme / 因果 key、import 時の SDK と
network、`output/` と `data/` への書き込みと CI の commit / Pages 公開 / 通知、可変 JSON 状態。Phase 7 はこれらを import せず、
legacy も Phase 7 を import しない（vNext の import 境界 `src/intelligence/__init__.py` と既存の guard）。

## 3. 目的と非目標

**目的**: 構造として次に答える — 何が起きているか ／ なぜか ／ どの持続的な Theme がそれを説明するか ／ 何が変わったか ／
どの関係が効くか ／ どの証拠が説明を支え、どれが反するか ／ 何が起きれば説明が無効になる・変わるか ／ 何が不確かか。
時間を意識した、説明可能な合成の層。

**非目標**: ニュース要約、記事の書き直し、LLM の論評、市場予測、売買推奨、Theme の再分類、P4 Morning Brief の置き換え、
受益銘柄の順位付け（Phase 6 の禁止と Phase 9 の範囲。§19）、読者別の framing（将来の personalization との境界は §28）。

## 4. 上流の入力の地図

### 4.1 概念上の連鎖の実現性

`Fact → Context → Theme Evidence → Persistent Theme → Theme Change → Theme Relations → Narrative` は**修正つきで実現できる**:

- Theme の evidence は B4 の入力型（NewsItem・SourceDocument・Fact・Observation）の ref を attachment として持つ。**P4 の
  Context は Theme evidence の供給源ではない**（B4 の繰越 #13: ContextItem / NewsClassification は POLICY_LOCKED）。したがって
  連鎖は `Fact / 観測 → Theme evidence（attachment）→ Theme → Change → Relations → Narrative` が主系列で、Context は
  Narrative の文脈（CONTEXT_ONLY）として横から入る。
- Narrative は上流を読むだけで、上流の authority を変えない（書き込み API を import しない。§21）。

### 4.2 P4

| artifact | 分類 | 理由 |
|---|---|---|
| Fact（`facts/`） | SAFE_READ_ONLY_INPUT（観測） | OBSERVATION。cutoff で濾過できる（`known_at`）。market 事実の `known_at` はセッション close（市場時刻の PIT。後日の値の改訂に対して bitemporal ではない） |
| Context（`context/`） | CONTEXT_ONLY | OBSERVATION だが Theme evidence ではなく、`Relationship` は因果を持たない。Narrative の文脈として観測 class で表示するだけ |
| Internals（`internals/`） | CONTEXT_ONLY | 同上。週次を日次として書かない |
| EvidencePackage | CONTEXT_ONLY（MARKET_STATE 型の将来の入力候補） | cutoff と先読み除外を持つ最良の P4 入口。ただし翌日見通しのための束 |
| CompassDraft（生の draft） | NOT_ALLOWED | 却下された claim と投影前の材料を含む。予測の authority として読まない（P5 §3） |
| MorningBrief・MarketSignal | CONTEXT_ONLY（原文のまま・言い換えず・予測に格上げしない） | 凍結された公開契約の出力。Narrative の根拠ではなく「その朝 P4 が何を出したか」の記録 |
| Production Compass DNA（`market_rules.yaml`・registry 6 rule） | CONTEXT_ONLY（`rule_ref` の引用だけ） | P4 の唯一の解釈 authority（AUTHORITATIVE_RULE）。Narrative は引用だけで、DNA の声で語らず、拡張も書き込みもしない。`valid_from` が無いので過去時点は version / git で pin する |
| Formal Decision layer | GOVERNANCE_ONLY（本 branch に source なし） | GOVERNANCE_RECORD。知識ではない |
| APPROVED-but-NOT_PROMOTED | NOT_ALLOWED（既定の拒否） | VALIDATED_REVIEW_KNOWLEDGE であって rule ではない。表示には完全な provenance の組と監督の設計承認が要る |
| REJECTED・KEEP_REVIEWING・未審査の推奨 | NOT_ALLOWED | 知識ではない ／ 未決 |
| 生の corpus・corpus research・replay | NOT_ALLOWED | RESEARCH_EVIDENCE（未審査・機密）／ PROCESS_ARTIFACT |

### 4.3 P5

**P5 の成果物は Narrative の入力として正当化できない。**（`PHASE5_ENTRY_CONTRACT.md` §3・§18、`PHASE5_COMPLETION_AUDIT.md`、
Phase 6 F-10・不変条件 #21）

- CalibrationReport: as-of の時刻が無く、訂正で過去の値が変わる。内部 analytics であり authority ではない。
- EvaluationRecord: 検証可能な知識時刻が無い（`created_at` は監査用で未検証）。実際の値動きが要るなら market の Observation を読む。
- PredictionRecord: P4 MarketSignal の写し。LIVE・`recorded_at ≤ cutoff` の条件なら PIT の形を持つが、MarketSignal と重複し、
  journal も空。
- 危険: 後知恵の漏洩、P5 → Narrative → Brief → P5 の循環（自己学習）、較正の authority 化、予測と事実の混同。
- 安全な利用は data ではなく**設計の再利用**だけ（追記専用 journal・fail closed の supersession）。

### 4.4 Phase 6

| interface | 分類 | 理由 |
|---|---|---|
| Theme root ／ observation（`resolve_at_data_root` → `ThemeResolution`） | SAFE_NARRATIVE_INPUT（L2 の reviewed Theme）／ CONTEXT_ONLY（L1 の候補） | Foundation の authority。L1 は自動の候補で reviewed ではない（A1 §16）ので、解釈の根拠にするのは L2 だけ |
| EvidenceAttachment（`ThemeResolution.evidence` の可視 attachment） | SAFE_NARRATIVE_INPUT | role（SUPPORTS / CONTRADICTS / INVALIDATES / CONTEXT）と role provenance を保ったまま使う。`evidence_time ≤ T` かつ `attached_at ≤ T` のものだけ |
| GovernanceLifecycleView | SAFE_NARRATIVE_INPUT | governance の位置の読み取り（REOPENED → ACCEPTED は凍結の解釈）。Narrative は governance を決めない |
| EvidenceConditionView | SAFE_NARRATIVE_INPUT（派生の条件として） | STALE・反証 / 無効化の evidence の存在などの記述的な flag。governance の判断として書かない |
| ThemeChangeSet（`detect_changes`） | SAFE_NARRATIVE_INPUT | 2 つの cutoff の純粋な差分。知識軸と evidence 時間軸を区別したまま使う |
| B3 の提案状態（open / deferred） | CONTEXT_ONLY（未審査） | L1 提案。B3 は cutoff を持たないので、PIT で読むには作成時刻 / 記録時刻で濾過する（B6D-R1 と同じ規則） |
| B3 / B5C の decision | GOVERNANCE_ONLY | 人間の決定の事実。Narrative は決定を作らない・言い換えない |
| B4 の discovery の成果物（run report・hit） | NOT_ALLOWED（直接）／ B3 提案として CONTEXT_ONLY | run report は永続しない派生物。再実行は候補の生成であって Narrative の仕事ではない |
| B4 の versioned knowledge（taxonomy・entity catalog） | SAFE_NARRATIVE_INPUT（語彙・label） | pin された版の語彙で表示する（最新版に差し替えない） |
| B5B の relation（`resolve_relations_at_data_root` ＋ graph view） | SAFE_NARRATIVE_INPUT | 明示的な relation authority（HUMAN_ASSERTED / SOURCE_ASSERTED、撤回 / 復元の governance）。使い方の規則は §13 |
| B5C の関係提案 | CONTEXT_ONLY（未審査） | L1 提案 |
| B6 の MonitoringFinding ／ RunReport | CONTEXT_ONLY ／ 選定の契機 | 派生・非 authority（§14） |
| B6 の ReviewItemState | NOT_ALLOWED | 運用の人間の確認記録で、市場の事実でも governance でもない。PIT でもない |
| B7 の LLM 提案（B3 / B5C に提出されたもの） | CONTEXT_ONLY（未審査・LLM 由来と表示） | 他の L1 提案と同じ扱い |
| B7 の生成成果物・生成監査 journal・検証済み plan | NOT_ALLOWED | 監査 data と非永続の派生物。evidence でも入力でもない（B7 closeout §10） |

## 5. authority の推奨

| 観点 | A: 純派生 | B: 追記専用の Narrative authority | C: 派生 ＋ 任意の運用 journal | D: 人間が審査する Narrative（L2 narrative） |
|---|---|---|---|---|
| 監査性 | 入力 digest と version を結果に持てば再計算で監査できる。何を誰に出したかは残らない | 完全 | 派生の監査 ＋ 出したことの記録 | 完全 ＋ 人間の判断の記録 |
| replay | 上流が追記専用なので同じ cutoff で byte 一致に再現 | 記録を読むだけ | A と同じ（journal は入力にしない） | 記録を読むだけ |
| PIT 再構成 | 上流の PIT に従う（自然） | 記録の時刻と上流の時刻の二重管理 | A と同じ | B と同じ |
| 改訂 / 履歴 | cutoff ごとの instance の差分として派生（§11） | supersession chain を保つ必要 | A と同じ ＋ 出した履歴 | B ＋ 審査の履歴 |
| 人間の governance | 不要（authority ではない） | Narrative の governance を新設する必要（第 2 の解釈 authority） | 不要 | 新しい L2 の審査の仕組みが要る |
| 複雑さ | 最小 | 大（store・破損・訂正・governance） | 小（journal は後で・監査だけ） | 最大 |
| 将来の P8 利用 | 同じ cutoff で再計算して読む | 記録を読む | 再計算 ＋ 出した記録の参照 | 審査済みだけを読む |
| 将来の P4 / 公開統合 | 何を出したかの証跡が無い | 証跡あり | 統合 gate で journal を有効にして証跡を持つ | 証跡あり・承認済みだけ |
| 危険 | 公開時の証跡不足（統合までは問題にならない） | Narrative が「もう 1 つの解釈 authority」になる。Theme / DNA と競合 | journal が入力に逆流する危険（B7E と同じ guard で防ぐ） | 人手の負荷と、Theme の governance との二重化 |

**推奨: C（派生 artifact ＋ 任意の運用 journal）。初期の Phase 7 gate では journal を作らず、A と同じ純派生として実装する。**
journal は P8 / 公開への統合 gate で監督判断により有効化する（出したことの監査記録であって Narrative の authority ではない。
生成入力・evidence・選定に使わない）。B と D は、Narrative を Theme と Production DNA に並ぶ第 2 の解釈 authority にするため
推奨しない。

## 6. Narrative の定義

**Narrative ＝ 明示された型・subject・scope・時間窓 `[T1, T2]`・cutoff `T2`・knowledge の pin について、上流の intelligence を
決定論的に合成した、引用つきの構造。** 何が観測され、記録された解釈は何で、何が変わり、どの明示的な関係がつながり、何が
支え・反し・無効化しうるか、何が不確かかを述べる。**上流の authority を作らず、変えない。**

- Narrative は Theme ではない（Theme は持続する仮説の authority。Narrative はその時点の読み方）。
- Narrative は予測でも推奨でもない（方向・確率・目標・構えの欄を持たない）。
- Narrative は要約でも書き直しでもない（上流の文を言い換えて新しい主張を作らない）。

## 7. 型の分類

| 候補 | 評価 | 推奨 |
|---|---|---|
| `THEME_STATE`（1 つの reviewed Theme の時間窓での状態と変化） | 上流がすべて揃う（resolver・change・lifecycle・evidence・relation） | **採用（初期）** |
| `THEME_SET`（明示された reviewed Theme の集合と、その間の明示的な relation） | relation authority と resolver で成立。推移辺を作らない | **採用（初期）** |
| `EVIDENCE_LINKED`（観測された 1 件の evidence が、どの reviewed Theme に attachment されているか） | 「なぜ起きているか・どの Theme が説明するか」に最も近い。ただし scope の Theme を走査する規則が要る | 次の候補（初期の後） |
| MARKET_STATE | P4 の Context / Internals / EvidencePackage を主入力にする必要があり、P4 との境界と Theme ↔ 市場の対応（series mapping）の方針が先 | 延期（P4 統合の方針の後） |
| RISK_NARRATIVE | 独立の型ではなく各型の節（反証・無効化・不確実性） | 型にしない |
| SCENARIO_NARRATIVE | 将来の分岐の予測になる。Phase 7 は予測しない | 範囲外 |
| CROSS_THEME_SYNTHESIS | `THEME_SET` と同じ（明示 relation に限る） | `THEME_SET` に統合 |

型は閉じた enum にし、自由な category を作らない。

## 8. 意味の構造（最小）

実装しない。A1 で model 化する候補:

| 部分 | 内容 | 主な出所 |
|---|---|---|
| header | 型・subject（Theme root id の組）・scope・時間窓・cutoff・knowledge の pin・入力 digest・engine version | caller の spec ＋ 入力の組み立て |
| WHAT | cutoff 時点で見えている観測（evidence ref・時刻・種類） | EvidenceAttachment |
| WHY | reviewed Theme に記録された機構（driver → channel → domain → consequence）と、その確度 class・provenance | Theme observation |
| EVIDENCE | role ごとの ref（支持・反証・無効化・文脈）と role provenance | EvidenceAttachment |
| CHANGE | 窓の中の変化（`ThemeChangeSet` の項目、lifecycle の位置の変化） | B1・B2 |
| RELATIONS | 明示的な relation（型・assertion class・状態） | B5B |
| UNCERTAINTY | 閉じた種類の列挙（例: 証拠が古い・数えられる証拠が無い・機構が仮説のまま・反証がある・未審査の提案がある・必要な入力が無い） | B2 flag・Theme の確度・PIT の欠落 |
| INVALIDATION | Theme に記録された無効化条件と、無効化 evidence の有無（「無効になった」とは書かない） | Theme observation・B2 |
| ALTERNATIVES | 同じ evidence を持つ他の reviewed Theme（並べるだけ・順位なし）と、未審査の文脈（分けて表示） | resolver・B3 / B5C（未審査） |

各部分は**文（statement）の列**で、文は `{認識 class, template key, 引数, 引用 ref の組}` を持ち、自由文を持たない。描画は別
（§17）。

## 9. 事実と解釈の境界

閉じた認識 class（提案）:

| class | 意味 | 例 |
|---|---|---|
| OBSERVED | 上流に記録された観測そのもの | 「〜が報じられた（ref）」 |
| RECORDED_INTERPRETATION | reviewed Theme に記録された解釈（機構・consequence・無効化条件） | 「Theme は〜という機構を記録している（確度: 仮説）」 |
| DERIVED | 決定論の code が authority から計算したこと | 「窓の中で支持 evidence が 2 件加わった」「証拠が 90 日以上古い」 |
| UNREVIEWED_CONTEXT | 未審査の提案・monitoring の finding | 「審査待ちの提案がある（ref）」 |
| UNCERTAINTY | 欠落・曖昧・未知 | 「機構は検証されていない」「入力が供給されていない」 |
| HYPOTHESIS | 支持の無い代替の説明（未審査の提案か、確度が仮説の機構だけから） | 「代替の説明として〜が提案されている（未審査）」 |

規則:

1. 文の class は合成時に決まり、描画で変えない（格上げ禁止: 解釈 → 事実、仮説 → 解釈、未審査 → 解釈）。
2. 文は 1 つ以上の ref を持つ（UNCERTAINTY は欠落の理由 code を持つ）。ref は cutoff 時点で解決できなければならない。
3. 描画は class ごとの閉じた template だけを使う（観測は報告の形、解釈は「記録している」の形、仮説は「提案されている」の形）。
4. 因果の動詞は RECORDED_INTERPRETATION の機構にだけ使い、OBSERVED / DERIVED には使わない（P4 の言語規則と同じ考え）。
5. SOURCE_ASSERTED の relation は「出典がそう主張している」とだけ書き、客観的な事実として書かない。
6. 確度 class（HYPOTHESIZED_MECHANISM 等）と role provenance（HUMAN / RULE / LLM_PROPOSAL）を常に表示する。

## 10. PIT と時間 model

Narrative は cutoff を caller が与え（aware な時刻・暗黙の now / latest なし）、同じ cutoff・同じ入力・同じ version なら byte 一致に
再現されること。

| 上流 | PIT | Narrative での扱い |
|---|---|---|
| Foundation resolver・B1・B2・B4 knowledge・B5B | 再構成できる | 主入力 |
| B6 の run（finding） | cutoff で再構成できる | 文脈 / 契機 |
| B6 の review 状態 | できない（運用） | 使わない |
| B3 / B5C の提案・decision | 現在の authority だけ（cutoff 引数なし） | 作成 / 記録時刻で濾過すれば PIT で読める（B6D-R1 と同じ）。濾過しない読みは禁止 |
| P4 の Fact / Context / Internals | 市場時刻の PIT（bitemporal ではない） | 文脈に限り、この性質を明示する |
| P4 の CompassDraft | `generated_at` が現在時刻の既定 | 使わない |
| Production DNA | `valid_from` なし | version / git の pin で引用だけ |
| P5 | 再構成できない ／ 後知恵 | 使わない |
| B7 の生成監査 journal | 運用の記録 | 使わない |

integrity-before-PIT を引き継ぐ: 壊れた authority は未来日付の行でも Narrative 全体を止める（黙って空にしない）。

## 11. identity と改訂の model

**推奨: hybrid の content identity（保存しない）。**

- **narrative key**: `{型, subject, scope, 窓の規則}` の content id。同じ問いを表す（保存しない・root を作らない）。
- **instance id**: `{narrative key, cutoff, 窓, 入力 digest, knowledge pin, engine version}` の content id。ある時点の答え。
- **改訂**: 同じ key の後の cutoff の instance。系譜は cutoff の順で派生し、保存しない。2 つの instance の差（NarrativeChange。B1 と
  同じ考えの純粋な差分）で「Narrative の何が変わったか」を出す。

上流の変化の扱い（§5 の C と整合: Narrative は変更されない。新しい cutoff の新しい instance になる）:

| 変化 | 結果 |
|---|---|
| 新しい evidence・Theme の改訂・lifecycle の変化・relation の変化・反証・無効化 evidence | 同じ key の新しい instance（CHANGE 節と NarrativeChange に現れる） |
| Theme の RETIRED ／ MERGE ／ SPLIT | 同じ key の新しい instance が governance の位置と lineage を示す。Narrative の「退役」record は作らない |
| knowledge version の変化 | pin が変わるので別の instance（旧 pin の instance は旧 pin のまま再現できる） |
| engine version の変化 | 別の instance（比較は同じ engine version の間だけ） |

将来 journal（§22）を有効にした場合も、journal の record は「この instance をこの時刻に出した」という event であり、Narrative の
改訂や authority ではない。

## 12. 反証と代替の説明

1 つの物語を押し付けない:

- 支持と反証が両方あるときは両方を並べ、どちらかに決めない（`UNRESOLVED` の不確実性を立てる）。
- 無効化条件と無効化 evidence の有無を分けて示す（無効化 evidence があっても「無効になった」とは言わない。退役は人間の governance）。
- 代替の説明は、同じ evidence を持つ他の reviewed Theme を並べる（順位なし）か、未審査の提案として分けて示す。
- 機構が不明・確度が仮説のときは `UNKNOWN_MECHANISM` ／ `HYPOTHESIZED` を不確実性として示す。

**確信度の score・順位は持たない**（既定）。件数は記述として示してよいが、強さ・均衡・勝敗の尺度にしない（legacy の擬似確率・
勝率 feedback の反省）。

## 13. relation の使い方

Narrative が使ってよいのは、cutoff で解決した B5B の明示的な relation authority だけ:

- 直接の辺だけを使う。**推移辺を事実として導かない**（2 段以上の経路を「つながっている」と主張しない）。
- centrality・PageRank・次数による重要度を使わない（B5 の graph は 7 つの記述的な method だけ）。
- 共同の発見・同じ evidence の共有・同じ提案への登場を関係として扱わない（関係は B5B の assertion だけ）。
- SOURCE_ASSERTED は「出典が主張した」であって客観的な真実ではない（`SOURCE_ASSERTED_NON_MEANING`）。
- 撤回された relation は撤回の事実として示し、現役の関係として使わない。
- B5C の関係提案は未審査の文脈（§15）。

## 14. monitoring の使い方

- `MonitoringFinding` ／ `MonitoringRunReport` は派生・非 authority。Narrative では**選定の契機**（§18）と**未審査の文脈**
  （「監視の条件が観測された」: condition id と ref を示す）に限る。市場の事実・解釈の根拠にしない。
- `ReviewItemState`（ACKNOWLEDGED / DISMISSED / DEFERRED）は人間が見たことの運用記録で、市場の真実でも governance でもない。
  Narrative に入れない（「却下された」を「誤りだった」と読まない）。

## 15. 提案と未審査の知識の方針

| 対象 | 方針 |
|---|---|
| B3 の open ／ deferred 提案 | 解釈・事実の根拠にしない。使う場合は PIT で濾過し、未審査の文脈として別の節に置く |
| B4 の discovery hit | 直接は使わない（B3 提案として記録されたものだけが上の扱い） |
| B5C の関係提案 | B3 と同じ |
| B7 の LLM 提案（B3 / B5C に提出済み） | B3 と同じ ＋ LLM 由来と表示 |
| B7 の生成出力・監査 journal・plan | 使わない |

**推奨（厳格）**: 初期の実装では未審査の知識を Narrative に**入れない**。「審査待ちがある」という件数と ref の文脈節は、A1 で
監督が承認した場合に限り足す。

## 16. LLM の役割

**初期の Phase 7 は LLM を必要としない。** 構造の合成は上流の構造化された intelligence から決定論的にでき、描画も閉じた
template でできる（P4 の決定論の既定と同じ）。

将来の任意 gate として考えられる役割（同じ原則: LLM は提案し、決定論の code が検証し、authority の境界は外に残る）:

1. **言い回しの提案**: 検証済みの構造の文を自然な文に言い換える提案。決定論の検証器が文の網羅・ref・class の言い回し・禁止語を
   確かめ、落ちれば template の文に戻す。
2. **代替の説明の提案**: HYPOTHESIS class の未審査の提案としてだけ（B7 の B3 提出と同じ経路・上限 L1）。

LLM を使う gate は、Phase 6 の MANDATORY_BEFORE_REAL_PROVIDER の項目（P6-DEF-07〜13）を前提にする。境界は vNext の
`core.contracts.LLMProvider` か Phase 6 B7 の provider protocol の型に従い、legacy の LLM 経路は使わない。

## 17. 決定論の core

LLM を後で使う場合も、次は決定論のまま残す:

- PIT の入力の組み立て（caller の cutoff・上流の PIT 入口だけ・未来の record は存在しない扱い）
- authority の濾過（§4 の分類・allowed-source の方針 §23）と L2 / L1 の区別
- evidence role・role provenance・確度 class の保持
- Theme と relation の適格性（§13・§18）
- identity（key・instance id）と改訂の系譜（cutoff の順）
- 引用 ref の束縛と解決可能性の検査
- 文の認識 class と、その class の template の選択
- schema の検証と禁止語（因果・助言・予測・数値目標）の検査
- 描画（閉じた template。未写像の値は fail closed）

## 18. 選定の方針

**初期の方針: 明示の caller 要求だけ。** caller が `{型, subject, scope, 窓, cutoff}` を与える（B6 の monitoring scope と同じく
authority の全体を暗黙に列挙しない）。

補助として、決定論の**適格性一覧**を出せる（Narrative を作るのではなく候補を示すだけ）:

- 対象: caller が与えた scope の reviewed Theme
- 理由 code（複数可）: 窓の中の変化がある（`ThemeChangeSet` が空でない）・lifecycle の位置が変わった・反証 ／ 無効化の evidence が
  ある・relation が変わった・monitoring の finding がある・新しい evidence が attachment された
- 並びは Theme root id の順だけ。**順位・重要度 score・LLM の選択は無い**

## 19. P8 Screener への暫定 handoff

**暫定**（P8 は開始しない）:

- P8 が読めるのは、将来に承認される interface を通した Narrative の構造化された欄（Theme ref・文の class・不確実性の種類・変化の
  種類・relation の ref）だけ。cutoff を明示して読む。
- Narrative は銘柄の順位・売買の signal・portfolio の推奨・隠れた score にならない。Narrative は方向・強さ・score の欄を持たない
  ので、P8 がそれを数値化して順位に使うことを契約で禁じる。
- 受益の 1 次 / 2 次 / 3 次（履歴 branch の旧 roadmap の P7-1）は、Phase 6 の受益順位の禁止と矛盾する。Phase 7 では扱わず、
  P8 / P9 の契約で改めて決める（§28）。

## 20. 将来の production ／ P4 の境界

Phase 7 の初期実装は内部だけ。将来に統合するには次が要る（いずれも Phase 7 の初期範囲の外）:

- 承認された adapter（Phase 7 → 公開の片方向。P4 の凍結された公開契約を変えない形で）
- 引用と evidence の保証（すべての文の ref が解決でき、公開してよい出典だけ）
- authority の濾過（L2 だけ・未審査は出さない）と PIT ／ 現在の区別の明示
- 描画の規則（閉じた語彙・公開の禁止語の guard・`text` と `display_text` の分離）
- security ／ 機密（§23）と、出したことの監査 journal（§22）
- production bundle の閉包から外す guard の更新（Phase 7 の package を除外 package と閉包の guard に登録）

## 21. package と import の設計

**推奨: `src/intelligence/narrative_intelligence/`**（Phase 6 と同じく flat な module ＋ guard 登録）。

- 読んでよいもの: Phase 6 の read-only surface（`themes` の resolver / model、`theme_intelligence` の change・lifecycle・
  relation_resolution・relation_graph・knowledge loader・proposal_resolution（読みだけ）・monitoring_model（読みだけ））、
  `core`（時刻の検査・id）、承認された場合だけ P4 の `facts` / `context` の read-only 入口。
- 禁止: すべての store の書き込み API、`reports`・`compass` の生成器・`predictions`・legacy（`src/analysis`・`src/report`・
  `main`）・LLM SDK・network・時計・乱数。
- 上流（Phase 6・P4・P5・legacy）は Phase 7 を import しない（guard で検査）。Phase 6 との循環は生じない（Phase 7 → Phase 6 の
  片方向）。
- 型名は P4 の `NarrativePlan` ／ `NarrativeGenerator` と衝突させない（例: `ThemeNarrative…` の接頭辞）。名前は監督判断。

## 22. 永続化

**初期: 永続化しない。** 再現性と監査性は次で得る:

- 上流はすべて追記専用で PIT の入口を持つ → 同じ cutoff の再計算は byte 一致になる。
- Narrative の結果は入力 digest・knowledge の pin・engine version・instance id を持つ → どの入力から作ったかを検査できる。
- replay の test（別 process・入力順の違い・未来の record の追加で結果が変わらない）で保証する。

将来の任意の運用 journal（統合 gate で監督判断）を足すなら:

| 項目 | 内容 |
|---|---|
| 永続するもの | emission record（instance id・narrative key・cutoff・入力 digest・engine version・出した先の種類・出した時刻）。本文と LLM の生の出力は入れない |
| 分類 | OPERATIONAL / AUDIT（Narrative の authority ではない） |
| 追記 | 追記専用・canonical JSONL・同 id 同 bytes は冪等・同 id 異 bytes は CONFLICT・single writer |
| PIT | 記録は運用時刻を持つが、Narrative の再現には使わない |
| identity | event identity（instance id ＋ 出した時刻 ＋ 出した先） |
| 破損 | fail closed・修復しない・読み飛ばさない |
| replay | journal は入力・evidence・選定に使わない（B7E と同じ guard） |

## 23. security ／ 機密

**allowed-source の方針（提案）**:

| 出典 | 可否 |
|---|---|
| Foundation の reviewed Theme（L2）・EvidenceAttachment・governance の位置・B1 / B2 の派生・B5B の relation・B4 の pin された語彙 | 可 |
| P4 の Fact / Context / Internals（文脈として） | 可（観測 class で） |
| Production DNA の `rule_ref` | 引用だけ可（本文・出典頁の表示は不可） |
| 未審査の提案・monitoring の finding | 既定は不可（承認時に未審査の文脈として） |
| Compass の corpus・PDF の本文・ファイル名・path | 不可 |
| formal review の記録の内容 | 不可 |
| portfolio ／ 個人の行動記録 | 不可 |
| 資格情報・machine path | 不可 |
| LLM の生の応答・隠れた推論・生成監査 journal | 不可 |
| P5 の成果物 | 不可 |

漏洩の経路と対策: 未審査の提案の文（B3 の reason 等）は template でない場合があるので、文を写さず ref と class だけを示す。
evidence の excerpt・要約は既存の権利規則に従い、Narrative 側で本文を増やさない。既存の機密 guard（`test_confidential_guard.py`）と
公開語彙の guard の型を Narrative の出力に適用する。

## 24. 実データの準備

合成の test で品質を主張しない。実データで Narrative を評価する前に要るもの:

- 実 Theme authority（P6-DEF-13）: 少なくとも数個の L2 Theme、それぞれ 2 つ以上の独立した origin からの数えられる evidence
- relation の網羅: scope の Theme の間に 1 つ以上の明示的な relation（HUMAN_ASSERTED と SOURCE_ASSERTED の両方の例）
- 変化の履歴: 2 つ以上の cutoff にまたがる改訂・evidence の追加、反証 ／ 無効化 evidence の実例
- knowledge の pin と、入力の種類の多様さ（news・document・fact・observation）
- 評価の基準: 引用がすべて cutoff で解決できる・事実 ／ 解釈の class の正しさ（人間の review）・PIT の replay が byte 一致・未来の
  record が見えない・反証と不確実性の網羅・人間による有用性の定性評価。**precision / recall は主張しない**

## 25. Phase 6 の deferred の影響

| P6-DEF | 内容 | Phase 7 への影響 |
|---|---|---|
| 13 | 実 Theme authority ／ 実データ shadow | 実データの評価を止めるが、計画と合成での実装は止めない |
| 15 | Phase 6 を読む正式な interface | Phase 7 の入力の組み立て（A2）がその consumer 側を定義する。blocker ではない |
| 01〜06 | 提案の実行 gate | 止めない。Narrative は既存の L2 authority を読むだけ（自動の経路で L2 にならないことはむしろ前提） |
| 07〜12 | 実 provider | 止めない（初期は LLM なし）。LLM の任意 gate の前提 |
| 17 | single writer | 止めない（Narrative は書かない。journal を足すときに再考） |
| 26・27 | monitoring の制約・integrity-before-PIT | 制約として引き継ぐ（review 状態を使わない・壊れた authority で止める） |
| 18・19 | 収束・準重複の意味照合 | Narrative で意味の dedup をしない |
| 29 | 会社別 thesis ／ 受益順位 | Phase 7 の範囲外（§19） |
| 31 | B2 の文書の文言（REOPENED → ACCEPTED ほか） | 止めない。ただし Narrative が lifecycle を語る前（A1）に文書を合わせることを推奨 |

**Phase 7 の計画・初期実装を止める Phase 6 の deferred は無い。**

## 26. Phase 7 の gate 案

最小の一貫した順序（例示の A0〜A7 から統合・縮小した）:

| gate | 内容 | runtime |
|---|---|---|
| P7-A0 | 本監査 | なし |
| P7-A1 | 意味と authority の契約 ＋ 純 model（定義・型・文の認識 class・allowed-source・identity・改訂の考え方。I/O なし） | 純 model |
| P7-A2 | PIT の入力の組み立て（Phase 6 の PIT 入口だけを読む read-only builder・allowed-source の濾過・入力 digest） | read-only |
| P7-A3 | 決定論の合成 engine と検証器（節・文・引用の束縛・反証 ／ 代替 ／ 不確実性・禁止語） | 純関数 |
| P7-A4 | 決定論の描画（閉じた template）・NarrativeChange（2 つの instance の差）・適格性一覧 | 純関数 |
| P7-A5 | 敵対的 E2E（PIT 漏洩・authority の越境・未審査の格上げ・relation の誤用・機密）＋ closeout | test と文書 |

初期の範囲外（それぞれ別の gate・監督判断）: LLM の任意 gate（§16）、運用 journal（§22）、P4 ／ 公開の adapter（§20）、P8 への
interface（§19）、`EVIDENCE_LINKED` と MARKET_STATE の型。

## 27. blocker

**なし。** 記録する衝突 ／ 不整合（blocker ではない・監督判断で解く）:

1. 名前の衝突: P4 の `NarrativePlan` ／ `NarrativeGenerator`（§2・§21）。
2. 旧 roadmap の P7-1 の「受益 1 次 / 2 次 / 3 次」と Phase 6 の受益順位の禁止（§19）。
3. Phase 6 A1 §10 が「読者別の framing」を Phase 7 に置き、将来の personalization（P10）と重なる（§3）。
4. P4 の仕様書と P4 の governance / research の source が本 branch に無い（境界は P5 の契約と Phase 6 文書が引き継ぐ。§2）。
5. `src/intelligence/__init__.py` の docstring が本 branch に無い文書を指している（文書の不整合）。
6. legacy の LLM 経路と vNext の LLM 境界の併存（Phase 7 は vNext 側だけに従う）。

## 28. 監督判断が必要な事項

| # | 決定 | 推奨 |
|---|---|---|
| D-P7-1 | Narrative の authority | C（派生 ＋ 任意の運用 journal）。初期は journal なし（§5） |
| D-P7-2 | package 名と型名の接頭辞 | `src/intelligence/narrative_intelligence/`、P4 と衝突しない型名（§21） |
| D-P7-3 | 初期の型 | `THEME_STATE`・`THEME_SET`（§7） |
| D-P7-4 | 解釈の根拠にする Theme の範囲 | L2（reviewed）だけ。L1 は文脈（§4.4） |
| D-P7-5 | 文の認識 class の語彙 | §9 の 6 class |
| D-P7-6 | LLM | 初期は使わない（§16） |
| D-P7-7 | 選定 | 明示の caller 要求 ＋ 順位なしの適格性一覧（§18） |
| D-P7-8 | P4 の入力 | Fact・Context・Internals は文脈、DNA は `rule_ref` の引用だけ、CompassDraft ／ governance ／ research は不可（§4.2） |
| D-P7-9 | P5 の入力 | 使わない（§4.3） |
| D-P7-10 | 未審査の知識 | 初期は入れない（§15） |
| D-P7-11 | monitoring | finding は契機と文脈だけ、review 状態は不可（§14） |
| D-P7-12 | identity | hybrid の content identity・保存しない・系譜は派生（§11） |
| D-P7-13 | 永続化 | 初期はなし。journal は統合 gate（§22） |
| D-P7-14 | 受益順位と読者別 framing | Phase 7 の範囲外（P8 / P9 / P10 で決める）（§19・§27） |
| D-P7-15 | P6-DEF-31（B2 文書の文言）を A1 の前に閉じるか | 閉じることを推奨（止めはしない） |
| D-P7-16 | 描画の言語 | 日本語の閉じた template を既定（P4 の表示規則に合わせる） |
| D-P7-17 | gate の順序 | §26 の A1〜A5 |

**判定: P7_A0_ARCHITECTURE_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_DECISIONS**

A1 は開始しない。Narrative の model・永続化・LLM 接続・Phase 6 ／ P4 ／ P5 ／ 公開出力の変更は行わない。監督レビュー待ち。
