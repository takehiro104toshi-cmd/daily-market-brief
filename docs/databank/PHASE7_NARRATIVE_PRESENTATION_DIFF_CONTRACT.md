# PHASE 7 / P7-A4a — NARRATIVE PRESENTATION MODEL / DIFF / ELIGIBILITY CONTRACT（DETERMINISTIC STRUCTURE ONLY / NO NATURAL-LANGUAGE RENDERER）

A4a は A1 の `NarrativeSynthesis` から**提示の構造**（`NarrativePresentation`）を作り、明示的に与えた 2 つの synthesis から
**構造の差分**（`NarrativeDiff`）を作る純関数だけを持つ。人が読む文章・要約・LLM・provider・永続化・公開出力は無い。
module: `src/intelligence/narrative_intelligence/presentation_model.py`（model・規則表）・`presentation_planner.py`（再検証・
提示の計画・見せ方の選び方の検査）・`narrative_diff.py`（差分）。
test: `tests/intelligence/test_narrative_presentation_diff.py`（matrix A〜BH）・`tests/intelligence/test_narrative_intelligence_boundary.py`
（BI〜BM: A1 / A2 / A3 / Phase 6 の byte 凍結・runtime の import closure・module 状態なし・未登録 runtime の検出）・
`tests/intelligence/phase7_runtime_registry.py`（A4a の 3 module を登録）。

anchor: P7-A3 freeze `9b336091b2348cc2311872b76a7b4c1d82f92ccf`、P7-A2 freeze `2dfd85c757d96b3b546f6723f88d70b94a191f97`、
P7-A1 freeze `a02ad60878054b5846b11acac720fa2811f32505`、Phase 6 freeze `5ef313a6a9477f05b4e46756fb8b79c0f0c3d685`。
入る前の基準: 4667 passed / 2 skipped。

**本 gate の設計判断（監督の確認を求める）**

| id | 事項 | 選択 |
|---|---|---|
| D-P7-A4A-1 | section の分類 | A1 の claim kind 6 つ（STATE / MECHANISM / EVIDENCE / CHANGE / RELATION / INVALIDATION）＋ 隠さないために分ける 3 つ（CONTRADICTION・UNCERTAINTY・ALTERNATIVES）＝ 9 つ。どれも少なくとも 1 つの規則が使う（§8） |
| D-P7-A4A-2 | 見せ方の義務 | 2 値だけ: REQUIRED（反証・無効化の 3 形・すべての不確実性・代替）と ELIGIBLE（その他）。SOURCE_ASSERTED の relation は ELIGIBLE だが、item の `assertion_class` が必須で外せない（§7・§14） |
| D-P7-A4A-3 | 不適格（出さない）の class | 0.1.0 には無い。A1 が未審査・提案・LLM 出力・本文・path を model の段階で拒否するため、有効な synthesis の claim はすべて表示してよい（§6） |
| D-P7-A4A-4 | item のまとめ方 | claim 1 つ ＝ item 1 つ（まとめない）。文としてまとめるのは A4b の書き方で、ここでは構造を固定するだけ（§15） |
| D-P7-A4A-5 | CONTEXT | EVIDENCE の section に role CONTEXT のまま ELIGIBLE（A3 の D-P7-A3-1 を継ぐ。支持にしない）（§6） |
| D-P7-A4A-6 | 受ける synthesis の version | A1 の schema（`narrative_synthesis:0.1.0` ／ `narrative_claim:0.1.0`）と A3 の規則表 pin `narrative_synthesis_rules` 0.1.0 が必須。A3 を import しない（名前と version は複製し、一致は test で固定）（§4） |
| D-P7-A4A-7 | subject の外の claim | 規則表 0.1.0 は subject の外の claim を作らない。A1 としては有効でも subject の外に触れる claim を持つ synthesis は `SYNTHESIS_INTEGRITY_FAILURE`（THEME_STATE は構造上つねに 1 Theme が中心）（§10） |
| D-P7-A4A-8 | 差分の比較条件 | 同じ kind・同じ `narrative_key`（型と subject の組）・同じ knowledge pin（reader と A3 の規則表）・previous の cutoff < current の cutoff（厳密）（§19） |
| D-P7-A4A-9 | 差分の item | 提示の item をそのまま埋め込む。差分の identity は差分の規則表と提示の規則表の両方の version を束ねる（§16・§20） |
| D-P7-A4A-10 | 隠さない規則の強制 | `validate_display_selection`: A4b が見せる claim の選び方は、見せる Theme に触れる REQUIRED の item をすべて含まなければ拒否（§7・§26） |
| D-P7-A4A-11 | 提示の field | cutoff・knowledge pin・input digest は持たない（元の synthesis id が束ねる。A4b は synthesis を併せて読む）（§5） |

A1 ／ A2 ／ A3 の変更は不要だった（`P7_A1_REMEDIATION_REQUIRED` ／ `P7_A2_REMEDIATION_REQUIRED` ／ `P7_A3_REMEDIATION_REQUIRED` の
条件に当たらない）。

---

## 1. 目的

提示と差分が答える問い・答えない問い（凍結文言。`PRESENTATION_ANSWERS` ／ `PRESENTATION_DOES_NOT_ANSWER` ／ `DIFF_ANSWERS` ／
`DIFF_DOES_NOT_ANSWER`）:

```
which structured claims of one synthesis may be displayed, in which closed section and presentational order, and which must stay visible
how to word it, which claim or theme matters most, how the evidence balances, how confident to be, or which explanation wins
which structured claims were added, removed or unchanged between two explicitly supplied syntheses
why the market changed, whether a theme improved, whether confidence increased, or whether an investment became more attractive
```

```
NarrativeSynthesis（A1・凍結）→ 再検証 → 規則表（P01〜P14）→ section（提示の順）→ NarrativePresentation
previous NarrativeSynthesis ＋ current NarrativeSynthesis（どちらも明示）→ 再検証 → 比較条件 → claim id の集合の差 → NarrativeDiff
```

## 2. A4 の分割

監督判断で A4 は 2 つに分かれる。A4a（本 gate）: 提示の model・適格・分類・決定論の順序・構造の差分。A4b（後続）: 人が読む
決定論の文章化。見せてよい構造を、書き方を決める前に凍結するのが目的。本 gate は A4b・自然文・要約を実装しない。

## 3. authority の分類

`AUTHORITY_CLASS = ("DERIVED", "NON_AUTHORITY", "NON_PERSISTENT")`。凍結文言 `PRESENTATION_IS_NOT_AUTHORITY`:

```
a narrative presentation or diff is a derived, non-authoritative, non-persistent arrangement of existing synthesis claims; never a new claim, a knowledge authority, a ranking, a recommendation or a trading signal
```

A4a は Theme・observation・attachment・governance・relation・提案・Production DNA・A1 の synthesis を書かず変えない（test AY / BH:
入力の bytes と data_root と repo が不変）。

## 4. 純関数の境界

- 入力: A1 の `NarrativeSynthesis`（提示）、明示的な previous と current（差分）。出力: 派生の構造だけ。
- store・A2 の adapter（`pit_assembler`）・A2 の入力 model・A3 の engine・Phase 6・filesystem・時計・乱数・network・provider を
  使わない（import の許可一覧と runtime の `sys.modules` で固定。BB〜BE・boundary の BB / BC / BD / BE）。
- 実行時の証明: `open` ／ `os.open` ／ `os.replace` ／ `os.rename` ／ `os.remove` ／ `os.mkdir` ／ `os.makedirs` ／ `socket` を失敗させても
  同じ出力（AY / BF）、`time` ／ `random` ／ `secrets` ／ `uuid` ／ `os.urandom` を失敗させても同じ出力（AE / BG）、別 process・別
  hash seed で byte 一致（C・AM）、別の path に作った同じ world・mtime の変更で同じ bytes（AD）。

**入力の再検証**（`revalidate_synthesis`。型付きの synthesis を盲信しない）:

1. `NarrativeSynthesis` でなければ `INVALID_SYNTHESIS`（dict・JSON 文字列・None も）。
2. kind が THEME_STATE / THEME_SET でなければ `UNSUPPORTED_PRESENTATION_KIND`。
3. 直列化の schema（synthesis と claim）が既知でなければ `UNSUPPORTED_SYNTHESIS_VERSION`。
4. synthesis・claim・ref の型と属性の集合が dataclass の field と完全一致（後から足された `score` ／ `confidence`・subclass を拒否）。
5. A1 の厳格な復元（`NarrativeSynthesis.from_json(to_canonical_json())`）で作り直し、内容と canonical bytes が一致すること。
   synthesis id・claim id・認識 class・claim kind・predicate・不確実性 code・ref（role ／ assertion class を含む）・knowledge pin・
   cutoff・input digest・subject の改ざんはここで検出される。
6. A3 の規則表 pin（`narrative_synthesis_rules`）が既知の version（0.1.0）でなければ `UNSUPPORTED_SYNTHESIS_VERSION`（pin が無い
   synthesis も）。
7. 規則表 0.1.0 が作らない形（subject の外に触れる claim）は `SYNTHESIS_INTEGRITY_FAILURE`。

以後は作り直した synthesis だけを使う。改ざんの test: synthesis id・cutoff・input digest・claim の欠落（AT）、claim id・ref の
付け足し（AU）、role・class・kind・code・predicate・pin・足された属性・subject・assertion class・subclass（AV）、version（AW）。

## 5. 提示の model

`presentation_model.py`（不変・`frozen`・`kw_only`）:

- `PresentationItem`: `claim_id`・`theme_root_ids`（claim の root の集合）・`epistemic_class`・`claim_kind`・`predicate`・
  `uncertainty_code`（IS_UNCERTAIN だけ）・`evidence_role`（EVIDENCE_ATTACHED だけ）・`assertion_class`（relation だけ）。`rule_id`・
  `section`・`visibility` は規則表から constructor が決める（外から与えられない）。属性の組は A1 の `PREDICATE_SIGNATURES` と
  root の数（事実 0・relation 2・代替 2 以上・他 1）で検査する。
- `PresentationSection`: section と item（1 つ以上・その section の item だけ・canonical な順）。空の section は作らない。
  section が無いことは「その種の claim が synthesis に無い」だけで、「反証が存在しない」等の主張ではない（A4b は無いことを文に
  しない）。
- `NarrativePresentation`: `kind`・`subject_root_ids`・`source_synthesis_id`・`sections`・`presentation_id`（派生）。
- `NarrativeDiffItem`（区分 ＋ 提示の item）・`NarrativeDiff`（`kind`・`subject_root_ids`・`previous_synthesis_id`・
  `current_synthesis_id`・`items`・`diff_id`）。

P4 の凍結名（`NarrativePlan`・`NarrativeGenerator` 等）は使わない（boundary の AP）。直列化に A1 の禁止 field（`score`・`rank`・
`confidence`・`summary`・`text`・`path` 等）が現れれば constructor が拒否する。`from_dict` ／ `from_json` ／ 保存の API は持たない
（AX）。

## 6. 適格

適格（ELIGIBLE）は「後で人に見せる Narrative に出してよい」だけを意味する。重要・正しい・確信度が高い・推奨を意味しない。
score・順位・重要度の重みは無い（P / Q / R）。

規則表 `PRESENTATION_RULES`（静的・`narrative_presentation_rules` 0.1.0。A1 の claim の形すべてに 1 つずつ。全域で重複なし。test S）:

| rule | claim の形 | section | 義務 |
|---|---|---|---|
| P01 | THEME_REVIEWED_STATE | STATE | ELIGIBLE |
| P02 | RECORDS_MECHANISM_COMPONENT | MECHANISM | ELIGIBLE |
| P03 | EVIDENCE_ATTACHED（SUPPORTS） | EVIDENCE | ELIGIBLE |
| P04 | EVIDENCE_ATTACHED（CONTEXT） | EVIDENCE | ELIGIBLE（role CONTEXT のまま。支持にしない） |
| P05 | EVIDENCE_ATTACHED（CONTRADICTS） | CONTRADICTION | REQUIRED |
| P06 | EVIDENCE_ATTACHED（INVALIDATES） | INVALIDATION | REQUIRED |
| P07 | EVIDENCE_ITEM_OBSERVED | EVIDENCE | ELIGIBLE（記録の観測だけ。内容なし） |
| P08 | RECORDS_INVALIDATION_CONDITION | INVALIDATION | REQUIRED |
| P09 | INVALIDATING_EVIDENCE_ATTACHED | INVALIDATION | REQUIRED |
| P10 | IS_UNCERTAIN（5 つの code すべて） | UNCERTAINTY | REQUIRED |
| P11 | CHANGED_BETWEEN_CUTOFFS | CHANGE | ELIGIBLE |
| P12 | HUMAN_ASSERTED_RELATION | RELATION | ELIGIBLE（assertion class を運ぶ） |
| P13 | SOURCE_ASSERTED_RELATION | RELATION | ELIGIBLE（assertion class SOURCE_ASSERTED が必須） |
| P14 | ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE | ALTERNATIVES | REQUIRED |

不適格（出さない）の class は 0.1.0 には無い（D-P7-A4A-3）。A1 が未審査の Theme・提案・LLM 出力・本文・path・予測を model の段階で
拒否するので、有効な synthesis の claim はすべて表示してよい。将来 A1 ／ A3 が表示してはならない材料を持つなら、提示の規則表の
version を上げて決める。独立に書き下した期待で「すべての claim が表どおりの section と義務に 1 回だけ置かれる」ことを 6 通りの
synthesis で確かめる（G）。

## 7. 隠さない義務

REQUIRED の item は「その Theme の item を 1 つでも見せるなら隠してはならない」。対象: CONTRADICTS の attachment（J）・INVALIDATES の
attachment ／ 無効化条件 ／ 無効化の evidence（K）・すべての不確実性 code（L）・代替の説明（Y）。SOURCE_ASSERTED の限定は item の
`assertion_class` として必須で、relation の item から外せない（M）。

既定の提示（`plan_presentation`）はすべての claim を含む。A4b が一部だけを見せる場合は `validate_display_selection(presentation,
claim_ids)` を通す: 選んだ item が触れる Theme の集合を求め、その Theme に触れる REQUIRED の item が 1 つでも欠ければ
`PRESENTATION_CONFLICT`（`REQUIRED_ITEM_DROPPED`）。未知の claim id も拒否。これで「SUPPORTS だけを見せて反証・無効化を黙って
落とす」選び方は作れない（O・K・N・Y）。観測の記録（Theme に触れない事実）だけの選び方は何も強制しない。

## 8. 分類

閉じた `SectionKind`（9 つ。D-P7-A4A-1）: STATE・MECHANISM・EVIDENCE・CONTRADICTION・INVALIDATION・UNCERTAINTY・CHANGE・RELATION・
ALTERNATIVES。A1 の claim kind 6 つに、§7 の隠さない義務と「反対の claim を別に見せる」ために CONTRADICTION（EVIDENCE から role で
分ける）・UNCERTAINTY（認識 class で分ける）・ALTERNATIVES（認識 class で MECHANISM から分ける）を足した最小の集合。
RECOMMENDATION・BUY・SELL・WINNER・TOP_THEME・BENEFICIARY_RANKING・SUMMARY・OUTLOOK・PREDICTION・SIGNAL は存在しない（S）。

## 9. 順序

- section の順（`SECTION_ORDER`）は上の宣言の順で、**読みやすさのための提示の順であり、重要度の順位ではない**（T / U）。
  凍結文言 `SECTION_ORDER_MEANING`: `presentational reading order only; not importance, priority or ranking`。
- section 内は canonical な identity の順: Theme の root id の組 → claim id（`item_order_key`）。score・重要度・evidence の件数で
  並べない（V / W）。
- 順序は constructor が**検査**する（並べ替えて黙って直さない）。重要度の順などで並べた入力は `PRESENTATION_CONFLICT`（T / V / W /
  AL）。
- 差分の順: 区分（ADDED → REMOVED → UNCHANGED。提示の順で重要度ではない）→ section の順 → Theme の root id の組 → claim id
  （`diff_item_order_key`）。

## 10. THEME_STATE

明示の Theme 1 つが中心。item の root はその Theme だけ（観測の記録は root を持たない）。synthesis に無い関係する Theme を足さず、
A3 が作らない relation の材料を作らない。A1 としては有効でも subject の外の Theme に触れる claim（relation 等）を持つ THEME_STATE の
synthesis は `SYNTHESIS_INTEGRITY_FAILURE`（A）。subject と合わない item を持つ提示は model が拒否する。

## 11. THEME_SET

Theme を順位付けしない。Theme ごとのまとまりは canonical な root id の順（ULID の文字列順。評価ではない）。主役・二番手・上位・
最強の Theme は無い（Q / W）。Theme の入力の順を逆にしても同じ bytes（W）。Theme ごとの item の数が違っても並びは root id の順の
まま（W）。受益者の順位の field・値は無い（X）。

## 12. 代替の説明

代替は並列・順位なし・排他的でない（上流が排他を明示しない限り）。代替の item は 2 つ以上の Theme の root を canonical な集合として
持ち、ALTERNATIVE_HYPOTHESIS のまま REQUIRED（Y）。好ましい説明を選ぶ field・引数は無い（`preferred` は TypeError。AA）。ref の
並びを逆にしても同じ item（Z）。代替に含まれるどの Theme を見せても、代替を隠す選び方は拒否される（Y）。

## 13. 不確実性

A3 の不確実性 code（NO_SUPPORTING_EVIDENCE・SINGLE_SOURCE_EVIDENCE・STALE_EVIDENCE・CONTESTED_EVIDENCE・MECHANISM_HYPOTHESIZED）を
そのまま運ぶ。複数の理由を数値の確信度にまとめない。evidence の件数から確信度を推測しない（SUPPORTS が 1 つ減っても他の item は
同じ。R）。すべての code は REQUIRED（L）。

## 14. SOURCE_ASSERTED

relation の item は `assertion_class` を必ず持ち、predicate と一致しなければならない（SOURCE_ASSERTED_RELATION ⇔ SOURCE_ASSERTED）。
A4b は A1 の凍結文言 `SOURCE_ASSERTED_MEANING`（"a source asserted this relation; the narrative does not assert it"）を表現できる。
assertion class を落とす・HUMAN_ASSERTED に書き換える item は `PRESENTATION_CONFLICT`（M）。

## 15. 追跡

item はちょうど 1 つの claim id に結び付く（孤立した item は無い。D-P7-A4A-4）。item の構造上の属性は claim のものと一致する（E）。
claim を落とさない・足さない・2 回置かない（F / G）。偽の claim id を足した提示は id が変わり、synthesis から作り直した提示と一致
しない（F）。値は id と閉じた語彙と version の token だけで、新しい意味を持たない（H）。

## 16. 提示の identity と規則表

`presentation_id = content_id("narprs", canonical_json(payload))`。payload は schema（`narrative_presentation:0.1.0`）・規則表
（`narrative_presentation_rules` 0.1.0）・元の synthesis id・kind・subject・section と item の全体。時計・乱数・path・mtime は
入らない（AB / AD / AE）。規則表の version は A4a の identity にだけ束ね、A1 ／ A2 ／ A3 に保存しない（AC）。同じ synthesis と同じ
規則 → 同じ bytes と id（C）。規則の意味を変えたら version を上げる。

## 17. 差分の目的

差分は「明示的に与えた 2 つの synthesis の間で、構造化された Narrative の中身の何が変わったか」だけに答える（§1 の凍結文言）。
市場の変化の理由・Theme の改善・確信度の上昇・投資の魅力には答えない（AP / AQ）。

## 18. 差分の呼び出しの契約

`diff_syntheses(*, previous, current)`: 両方とも keyword だけで既定値なし。前回の実行・昨日・最新の保存物を探さない（store を
読まない）。引数の欠落・位置引数は TypeError、synthesis でない値は `INVALID_SYNTHESIS`（AS）。

## 19. 比較できる条件

A1 の synthesis が持つ情報だけを使う（足りない来歴を作らない。D-P7-A4A-8）:

- 同じ kind（違えば `INCOMPATIBLE_DIFF_INPUTS` ／ `KIND_MISMATCH`。AR）
- 同じ `narrative_key`（A1 の型と subject の組。違えば `SCOPE_MISMATCH`。AS）
- 同じ knowledge pin（reader の version と A3 の規則表の version。違えば `KNOWLEDGE_PINS_MISMATCH`。A3 の引き継ぎ §26-4）
- previous の cutoff < current の cutoff（厳密。同じ synthesis どうし・逆順は `CUTOFF_ORDER`）

A1 は cutoff 以外の時間の来歴（記録の時刻・data_root の世代）を持たないので、それ以上の時系列の検査はしない。

## 20. 差分の区分

`DiffCategory` は ADDED（current だけ）・REMOVED（previous だけ）・UNCHANGED（両方）の 3 つだけ（AF〜AI）。MODIFIED は決定論で
支えられない（A1 の claim id は ref の全体から決まり、「同じ claim の変更」を決める鍵が無い）ので存在しない（AK）。差分の item は
その claim の提示の item を埋め込む（ADDED ／ UNCHANGED は current から、REMOVED は previous から）。差分の identity:
`diff_id = content_id("nardif", canonical_json(payload))`。payload は schema（`narrative_diff:0.1.0`）・差分の規則表
（`narrative_diff_rules` 0.1.0）・提示の規則表・kind・subject・previous id・current id・item の全体（AM）。

## 21. claim identity の照合

既定かつ唯一の照合は claim id の完全一致。似た claim（例: 機構 component の key だけが違う）・言い換え・意味の近さ・embedding で
合わせない。A1 の identity が収束させたものだけが同じ claim（AJ）。

## 22. 方向の評価をしない

ADDED の SUPPORTS を IMPROVED にしない（AN）、REMOVED の反証を STRENGTHENED にしない（AO）。BULLISH・BEARISH・BETTER・WORSE・
POSITIVE・NEGATIVE・UP・DOWN・UPGRADE・DOWNGRADE・MORE_CONFIDENT 等の語彙・field は無い（AP）。不確実性 claim の増減は code を持つ
item の ADDED ／ REMOVED として出るだけで、確信度の変化に換算しない（AQ）。

## 23. 失敗

`FAILURE_CODES`（`NarrativePresentationError`）:

| code | 条件 |
|---|---|
| INVALID_SYNTHESIS | 入力が `NarrativeSynthesis` でない |
| UNSUPPORTED_SYNTHESIS_VERSION | synthesis ／ claim の schema、または A3 の規則表 pin が未知・欠落 |
| SYNTHESIS_INTEGRITY_FAILURE | 型・属性・A1 の厳格な復元・id・canonical bytes の不一致、subject の外の claim |
| UNSUPPORTED_PRESENTATION_KIND | kind が THEME_STATE ／ THEME_SET でない |
| PRESENTATION_CONFLICT | 規則表に無い形・section ／ 順序 ／ 重複 ／ root の不整合・claim の対応の欠落・禁止 field・隠さない義務に反する選び方 |
| INCOMPATIBLE_DIFF_INPUTS | kind ／ narrative_key ／ knowledge pin の不一致、cutoff の順が previous < current でない |

detail は上流の code・型名・field 名だけで、本文・path・秘密値を含まない。

## 24. security ／ import 境界

- import の許可一覧（boundary）: `presentation_model` は `re`・`dataclasses`・`enum`・`typing`・`..core.ids`・`.synthesis_model`、
  `presentation_planner` は `dataclasses`・`typing`・`.presentation_model`・`.synthesis_model`、`narrative_diff` は `typing`・
  `.presentation_model`・`.presentation_planner`・`.synthesis_model`。A2（`input_model`・`pit_assembler`）・A3（`synthesis_engine`）・
  Phase 6・P4・P5・legacy・provider・network・公開 ／ 通知 ／ 売買の経路は import しない（runtime の `sys.modules` でも確認）。
- Phase 6 を import してよい Phase 7 の module は P7-A2 の adapter だけのまま（A2→P6 の例外を広げない。BM）。登録は A4a の 3 module の
  完全な path だけ。未登録の runtime は引き続き検出される（BM）。
- module 直下に可変な入れ物・global・履歴 ／ cache ／ 前回の実行の名前を持たない（boundary の module 状態の test）。
- A1（`a02ad60`）・A2（`2dfd85c`）・A3（`9b33609`）の runtime と契約は byte 一致（BI / BJ / BK）。Phase 6 の runtime は `5ef313a` から
  不変（BL）。
- 秘密値・path・生の LLM 応答・本文・人間の文を持たない。出力の文字列はすべて id・enum・version の token（H）。
- scratch の clone で mutation M1〜M15 をすべて検出（結果は CHANGELOG v5.47）。

## 25. 延期する事項（P7-A4A-DEF）

- 人が読む文章化（A4b）・claim をまとめた文の単位（同じ attachment を語る R04 と R10 の併記など）。
- 不適格（出さない）の class（将来の A1 ／ A3 の材料に応じて規則表の version を上げて決める）。
- 保存・履歴の差分・暗黙の前回（別の gate）。
- A3 の規則表の version が違う synthesis どうしの比較（現在は `KNOWLEDGE_PINS_MISMATCH`）。
- 公開 ／ P4 ／ P8 への接続・LLM。

## 26. A4b への引き継ぎ

A4b（決定論の文章化）は A4a の出力だけを使う:

1. 入力は `(synthesis, presentation)`。A4b は `plan_presentation(synthesis)` を作り直し、`presentation_id` の一致を確かめる
   （提示は保存されない）。ref の中身（component key・relation type・change kind 等）は synthesis の claim から読む。
2. section と item の順をそのまま使う（重要度の順ではない。並べ替えない）。
3. 一部だけを見せるなら、見せる claim id の集合を `validate_display_selection` に通す（REQUIRED を落とさない）。
4. 文は item の (class, kind, predicate, code, role, assertion class) ごとの閉じた template から作り、claim の意味を超えない。
   SOURCE_ASSERTED は `SOURCE_ASSERTED_MEANING` を表現する。section が無いことを文にしない。
5. 差分は `NarrativeDiff` の区分をそのまま使い、方向の評価の語を足さない。
6. LLM は別の gate まで使わない。
