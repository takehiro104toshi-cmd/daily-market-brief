# PHASE 7 / P7-A5 — NARRATIVE INTELLIGENCE COMPLETION AUDIT（ADVERSARIAL END-TO-END VALIDATION + CLOSEOUT）

Phase 7（Narrative Intelligence）の最終の敵対的 end-to-end 検証と closeout の記録。A5 は **test・guard・文書だけ**を足し、
Phase 7 の runtime（A1〜A4b）と Phase 6 を変えていない（新しい機能・型・claim・class・relation の意味・描画 mode・LLM・provider・
永続化・公開接続・個人化・順位付けは無い）。

test: `tests/intelligence/test_narrative_phase7_e2e.py`（matrix E01〜E44）・`tests/intelligence/test_narrative_intelligence_boundary.py`
（A5 節: Phase 7 の runtime 全体と A1〜A4b の契約が A4b の anchor と byte 一致）。

入る前の基準: 4889 passed / 2 skipped。

---

## 1. 総括の判定

**P7_NARRATIVE_INTELLIGENCE_COMPLETE / READY_FOR_SUPERVISOR_CLOSEOUT**（§28）。

明示の範囲と cutoff から、A2 の PIT 入力 → A3 の決定論の synthesis → A4a の提示 ／ 差分 → A4b の日本語の描画までを、本物の Phase 6
authority store（tmp の合成 world）で通して検証した。反証・無効化・不確実性・代替・SOURCE_ASSERTED は全層で保たれ、未来の記録は
どの層にも漏れず、提案 ／ 監視 ／ 生成物 ／ P5 は出力に影響せず、破損は fail closed、同じ入力は別 process でも byte 一致、全体の実行は
書き込み 0 byte。D-P7-A4B-1（検証済みの裏付け）の境界は敵対的に固定した。凍結した runtime に欠陥は見つからなかった（remediation 不要）。
実データでの E2E は実施できない（`REAL_DATA_E2E = NOT_RUN`。§21）。

## 2. 納品した範囲

| gate | 内容 | anchor | CHANGELOG |
|---|---|---|---|
| P7-A0 | architecture audit（文書） | `2fe7d0f` | v5.43 |
| P7-A1 | 意味論と純 model（`NarrativeSynthesis` ／ `NarrativeClaim` ／ ref） | `a02ad60` | v5.44 |
| P7-A2 | point-in-time 入力の組み立て（認可された一方向の読み取り adapter） | `2dfd85c` | v5.45 |
| P7-A3 | 決定論の synthesis engine（規則表 R01〜R14） | `9b33609` | v5.46 |
| P7-A4a | 提示 model ／ 差分 ／ 適格性（規則表 P01〜P14） | `50b24ef` | v5.47 |
| P7-A4b | 決定論の日本語の描画（template T01〜T18） | `b5f3a74` | v5.48 |
| P7-A5 | 敵対的 E2E 検証と closeout（test ／ guard ／ 文書だけ） | 本 commit | v5.49 |

## 3. architecture

```
caller（明示の型・root・cutoff・鮮度 policy・比較 cutoff）
  → A2 pit_assembler（Phase 6 の read-only API だけ）→ NarrativeInputSnapshot（DERIVED）
  → A3 synthesis_engine（規則表 R01〜R14）→ NarrativeSynthesis（A1。DERIVED）
  → A4a presentation_planner（規則表 P01〜P14）→ NarrativePresentation（DERIVED。表示の唯一の authority）
  → A4b text_renderer（narrative_renderer_ja 0.1.0。提示 ＋ 検証済みの裏付けの synthesis）→ RenderedNarrative（DERIVED）
previous synthesis ＋ current synthesis → A4a narrative_diff → NarrativeDiff → A4b render_diff → RenderedNarrativeDiff
```

package `src/intelligence/narrative_intelligence/`（11 module。すべて `phase7_runtime_registry.PHASE7_RUNTIME` に登録）。import の
内部の graph は E37 で完全一致を固定（§17）。

## 4. authority の流れ

| 状態 | authority の分類 | 永続？ | 可変？ | 解釈に影響してよいか | 表示に影響してよいか | そのまま公開してよいか |
|---|---|---|---|---|---|---|
| Phase 6 reviewed Theme | AUTHORITY（Phase 6 の reviewed L2 Theme。governance は Phase 6 だけ） | はい（append-only journal） | append-only（Phase 6 の governance の event だけ） | はい（A2 経由の唯一の入力） | A2〜A4a を通してだけ | いいえ |
| EvidenceAttachment | AUTHORITY（Phase 6 の observation の一部。role は Phase 6 が決める） | はい | 新しい observation の追加だけ | はい（role のまま） | A2〜A4a を通してだけ | いいえ |
| RelationAssertion | AUTHORITY（B5B の relation。assertion class 付き） | はい | append-only ＋ 撤回の event | はい（THEME_SET だけ・直接の辺だけ） | A2〜A4a を通してだけ | いいえ |
| NarrativeInputSnapshot | DERIVED ／ NON-AUTHORITY ／ NON-PERSISTENT（A2） | いいえ | 不変（改ざんは A3 が検出） | A3 の唯一の入力として | いいえ（直接は表示しない） | いいえ |
| NarrativeSynthesis | DERIVED ／ NON-AUTHORITY ／ NON-PERSISTENT（A1 の model、A3 が作る） | いいえ | 不変（改ざんは A4a ／ A4b が検出） | 派生の claim の集合（authority を変えない） | A4a の提示を通してだけ（A4b では検証済みの裏付けの材料） | いいえ |
| NarrativePresentation | DERIVED ／ NON-AUTHORITY ／ NON-PERSISTENT（A4a） | いいえ | 不変 | いいえ（新しい意味を持たない） | はい（何を・どの順で・適格・REQUIRED の唯一の authority） | いいえ |
| NarrativeDiff | DERIVED ／ NON-AUTHORITY ／ NON-PERSISTENT（A4a） | いいえ | 不変 | いいえ | はい（差分の表示の構造） | いいえ |
| RenderedNarrative | DERIVED ／ NON-AUTHORITY ／ NON-PERSISTENT（A4b） | いいえ | 不変 | いいえ（文言だけを変え、認識の意味を変えない） | 表示そのもの | いいえ（後の認可された adapter だけ） |
| RenderedNarrativeDiff | DERIVED ／ NON-AUTHORITY ／ NON-PERSISTENT（A4b） | いいえ | 不変 | いいえ | 表示そのもの | いいえ（後の認可された adapter だけ） |

Narrative の出力はすべて派生・非 authority・非永続。どの層も Phase 6 の authority を書かない（E10・E36）。

## 5. PIT の保証

- cutoff は caller が明示する（`now`・`latest`・None・naive は `INVALID_CUTOFF`。比較 cutoff は cutoff より厳密に前。E30）。
- 歴史の再現: cutoff T で 4 層を作り、後から governance（退役）・observation・evidence・relation の未来の記録を足して T で作り直すと、
  snapshot ／ synthesis ／ presentation ／ rendered の bytes が一致（E03。4 通りの要求）。Foundation の world（退役 → 取り消し → merge）
  でも途中までの world と全体の world が 5 つの checkpoint で全層一致し、退役 ／ merge の時点は `ROOT_NOT_ACCEPTED_AT_CUTOFF`（E03）。
- 未来の governance（E04）・observation と evidence（E05）・relation（E07）は T では見えず、後の cutoff でだけ見える。
- 現在と過去（E06b）: T1 と T2 の差は PIT で見える記録の差だけ（新しい SUPPORTS）。現在の状態で T1 を説明しない（手を加えていない
  world の T1 と一致）。

## 6. synthesis の保証

- 規則表 R01〜R14 だけ（A3 契約）。解釈を事実にしない（E13）。OBSERVED_FACT は FACT ／ OBSERVATION の記録で時刻が確立したものだけ、
  文書・報道・発言は世界の事実にならない、時刻の無い材料は投影されない（E12）。
- 機構の確度を強めない（HYPOTHESIZED は仮説のまま、EVIDENCE_SUPPORTED の Theme に仮説の不確実性を足さない。E14）。

## 7. 提示の保証

- 提示は表示の唯一の authority（何を・どの順で・適格・REQUIRED）。claim 1 つ ＝ item 1 つ。section の順は提示の順で重要度ではない。
- REQUIRED（反証・無効化・不確実性・代替）を落とした提示は描画されない（E18）。Theme は root id の順で、順位は無い（E02・E29）。

## 8. 描画の保証

- 描画は文言を変えるだけで認識の意味を変えない（`RENDERING_RULE`）。解釈は「整理されています」、出典の主張は「出典は…主張して
  います」、事実は「存在します」（E13）。FULL だけで、提示の item をすべて順に描く（E01・E02・E18）。
- 平文の文字の集合・長さの上限・禁止語（URL ／ journal ／ 秘密）で危険な値は描画の前に止まる（E31）。

## 9. D-P7-A4B-1 検証済みの裏付けの境界

監督が承認し凍結した契約: 提示は表示・順・適格・REQUIRED の **sole authority**。synthesis は **verified backing material** だけで、
凍結された A4a の計画で提示を **byte-for-byte** に作り直せる場合だけ使う。描画は提示の item から辿れる claim ／ ref だけを解決し、
synthesis を探して claim を足したり、省かれた claim を解釈し直したり、synthesis だけの材料から表示の内容を作ったりしない。

敵対的な固定（E19〜E21）:

| 項目 | 攻撃 | 結果 |
|---|---|---|
| A | 一致する提示 ＋ synthesis | 描画できる（同じ内容の synthesis なら同じ bytes） |
| B | X の提示 ＋ Y の synthesis（別 Theme・別 cutoff・別の範囲） | `PRESENTATION_INTEGRITY_FAILURE` |
| C | synthesis に提示に無い適格な claim を足す | A4a の作り直しと一致せず `PRESENTATION_INTEGRITY_FAILURE`（黙って読まない）。提示が許せば出る |
| D | synthesis だけの claim を選ぶ改ざんした提示 | `PRESENTATION_INTEGRITY_FAILURE` |
| E / F | 描画が synthesis を走査 ／ 探索する | 走査を禁じた記録用の索引で、解決された claim id ＝ 提示の item の claim id（順も同じ）。差分も同じ |
| G | 無関係な claim が bytes に影響する | 受けられる synthesis は提示の元と byte 一致するものだけ。描画の bytes は不変 |
| H | 提示から辿れない claim ／ ref が文に出る | 出ない（追加の key は受けた描画に現れない。テーマの label は提示の Theme だけ） |

mutation M15（提示を迂回）・M16（synthesis を探索）・M17（辿れない claim ／ ref を許す）をすべて検出（§25）。

## 10. 反証 ／ 無効化の保証

- 反証（NEWS_P の CONTRADICTS）は Phase 6 → A2（role・CONTESTED の flag）→ A3（EVIDENCE_ATTACHED の CONTRADICTS・CONTESTED の不確実性）→
  A4a（CONTRADICTION・REQUIRED）→ A4b（「一方、…矛盾する材料…」）の全層で反証のまま、既定の FULL に必ず出る（E08）。
- 無効化条件（inv1）と INVALIDATES の材料（INV_P）は別々に全層を通り（条件 P08 ／ 材料 P06 ／ 結び付き P09 の 3 つの別の claim）、どちらも
  Theme の governance を変えない（governance の journal は不変・全層で ACCEPTED・「テーマの状態を変えるものではありません」。E09・E10）。
- CONTEXT は全層で CONTEXT のまま（SUPPORTS ・証明・観測事実にならない。E11）。

## 11. relation ／ SOURCE_ASSERTED の保証

- 明示の B5B の relation は端点・向き・型・assertion class を A2 → A3 → A4a → A4b で保つ。逆向き・推移・撤回済み・範囲外の辺は無い（E15）。
- SOURCE_ASSERTED は描画で「出典は、…主張しています。これは出典による主張であり、この説明が主張する関係ではありません。」と限定される。
  snapshot ／ synthesis ／ 提示のどの層で限定を外しても fail closed、registry から限定の template を外すと `UNSUPPORTED_TEMPLATE`（限定の無い
  文言に落ちない。E16）。

## 12. 不確実性 ／ 代替の保証

- 不確実性の code はすべて REQUIRED で数値にならない（E14・E18・A4b の test）。
- 代替の説明は並列・順位なし・優先なし（「並列に記録されています（順不同）」。root id の順。入力の順を変えても同じ bytes。E17）。

## 13. 差分の保証

- 明示の T1 ／ T2 の synthesis から A4a の差分と A4b の描画: ADDED ／ REMOVED ／ UNCHANGED は claim id の集合の差と完全一致、描画の区分の文は
  それぞれの単独の描画と同じ文（E38）。
- 反証が後で外れる ／ SUPPORTS が後で増える world でも、改善・強化・弱化・強気・弱気・確信度の差の語や field は無い（E39）。

## 14. 決定論の再現

別 process・別 hash seed・`LC_ALL=C` で、同じ authority の状態・範囲・cutoff・規則 ／ template から snapshot ／ synthesis ／ presentation ／
rendered と差分 ／ 描画済みの差分の bytes が一致（E35）。時計 ／ 乱数 ／ 環境変数を止めても同じ（E30）。

## 15. 書き込みなし

完全な E2E（THEME_STATE ／ THEME_SET ／ 差分 ／ 失敗の経路を 2 周）の間、書き込みの mode の open・`os.replace` ／ `rename` ／ `remove` ／
`unlink` ／ `rmdir` ／ `mkdir` ／ `makedirs`・socket を失敗させても完走し、data_root の全 file の bytes と repo の状態が不変（E36）。
Phase 6 の authority journal・data_root・repo の runtime・Narrative の file ／ journal のどれも変わらない。出力の永続化は無い。

## 16. security

Phase 7 の runtime 全体を監査した: credential・machine path・環境変数・network・provider・生の LLM・隠れた推論・顧客 ／ portfolio の
data・生の Compass corpus・記事の本文の漏れは無い。現れるのは拒否のための語彙（A1 の禁止 field ／ ref 型、A4b の禁止語）と docstring
だけで、store の読み取りは A2 の `ThemeStore.open(read_only=True)` 1 か所だけ。人間の文・理由・抜粋・locator の canary は全層に現れない
（E31）。

**所見（Phase 6。Phase 7 には影響なし）P6-OBS-1**: Phase 6 の key の検査は `re.match` と `$` の組み合わせで、末尾の改行を 1 つ含む key を
受ける。Phase 7 の A1 は `fullmatch` なので、その key を持つ Theme は A2 で `REF_NOT_PROJECTABLE` として fail closed する（E31）。
Phase 6 の変更は本 gate の範囲外（非 blocking。§22）。

## 17. import の境界

内部の import graph（E37 で完全一致）:

```
synthesis_model        → core
input_model            → synthesis_model
pit_assembler          → input_model, synthesis_model, Phase 6（認可された read-only API だけ）
synthesis_engine       → input_model, synthesis_model
presentation_model     → synthesis_model
presentation_planner   → presentation_model, synthesis_model
narrative_diff         → presentation_model, presentation_planner, synthesis_model
rendered_model         → presentation_model, synthesis_model
render_templates_ja    → rendered_model
text_renderer          → narrative_diff, presentation_model, presentation_planner, render_templates_ja, rendered_model, synthesis_model
```

Phase 6 を import するのは `pit_assembler` だけ。描画の閉包は A2（`input_model` ／ `pit_assembler`）・A3 の engine・Phase 6・P5・legacy・
provider ／ network ／ 公開 ／ 通知 ／ 売買に届かない（静的と実行時の両方）。

## 18. 自己学習なし

出力は前の Narrative の結果・click・予測の的中・Theme の勝率・calibration・人の採用率に依らない（実行の順を変えても同じ bytes、module の
状態は不変、公開関数に履歴 ／ feedback の引数が無い、P5 ／ B6 ／ B7 を毒しても不変。E22〜E25・E34）。

## 19. 順位 ／ 推奨なし

どの層にも confidence・probability・score・rank・importance・centrality・PageRank・winner の field と数値は無い（E33）。買い・売り・保有
推奨・目標株価・期待リターン・ポジションの大きさ・受益者の順位・強気 ／ 弱気の結論は作れない（E32）。

## 20. 合成データでの検証の限界

検証はすべて tmp の合成 world（本物の Phase 6 store API で書いた authority）の上。意味論（PIT・役割・限定・隠さない規則・決定論・境界）は
検証したが、実際の市場データでの次の性質は検証していない:

- precision（出た説明がどれだけ正しいか）・recall（出るべき説明がどれだけ出たか）
- usefulness（読み手にとっての有用性）・実データでの日本語の文言の質
- coverage（実際の Theme ／ evidence ／ relation の分布での網羅）
- false-positive ／ false-negative の率

## 21. 実データの状態

`REAL_DATA_E2E = NOT_RUN`。repo と作業環境に実の Phase 6 Theme authority（`themes/theme_roots.jsonl` 等）は無い（`data/theme_learning` は
legacy の分析器の file で Phase 6 の authority ではない）。production の data root・Windows の研究 root・実の journal には触れていない。
実データでの Narrative の質は主張しない（§20）。

## 22. 延期の登録簿

| 項目 | 分類 | 備考 |
|---|---|---|
| real-world data validation | MANDATORY_BEFORE_PRODUCTION_INTEGRATION | 実データでの precision ／ recall ／ 有用性 ／ 文言の質（§20） |
| real Theme authority shadow | MANDATORY_BEFORE_PRODUCTION_INTEGRATION | 実の Phase 6 authority に対する shadow 実行（書き込みなし） |
| optional LLM surface wording | NON_BLOCKING_DEFERRED | 決定論の描画が基準。入れるなら別 gate（RENDERING_RULE を守る検証つき） |
| LLM alternative explanation proposal | NON_BLOCKING_DEFERRED | 提案は authority にならない（B7 と同じ扱い）。別 gate |
| persistence（if ever required） | NON_BLOCKING_DEFERRED | 現在は不要。必要なら明示の gate |
| P4/public integration | MANDATORY_BEFORE_PRODUCTION_INTEGRATION | 認可された adapter（形式ごとの escape・監督の文言の確認） |
| P8 handoff | NON_BLOCKING_DEFERRED | §27 |
| P10 personalization | NON_BLOCKING_DEFERRED | 読み手別の表現は Personal Intelligence の範囲 |
| localization/i18n | NON_BLOCKING_DEFERRED | 0.1.0 は日本語だけ |
| Theme display names | MANDATORY_BEFORE_PRODUCTION_INTEGRATION | A1 に名前が無い。人向けの公開には認可された名前の出所が要る |
| selected/compact rendering | NON_BLOCKING_DEFERRED | 入れるなら A4a の `validate_display_selection` を必ず通す |
| external citations/UI expansion | NON_BLOCKING_DEFERRED | 参照の印 → claim id → ref で辿れる |
| operational scheduling | MANDATORY_BEFORE_PRODUCTION_INTEGRATION | いつ・どの範囲で実行するかの運用の gate |
| real provider（if ever authorized） | MANDATORY_BEFORE_REAL_PROVIDER | credential の実行時注入・評価・監督の承認 |
| P6-OBS-1（Phase 6 の key の末尾改行） | NON_BLOCKING_DEFERRED | Phase 7 は fail closed。Phase 6 の保守の gate で扱う |
| SCENARIO_CONDITION の認識 class | CLOSED/OBSOLETE | A1 で不採用（A1 契約 §5） |
| 差分の MODIFIED 区分 | CLOSED/OBSOLETE | 決定論で支えられない（A4a 契約 §20） |
| P4 の NarrativePlan ／ NarrativeGenerator の再利用 | CLOSED/OBSOLETE | Phase 7 は別の名前で、P4 を import しない |

## 23. 凍結の anchor

| 対象 | anchor | A5 での状態 |
|---|---|---|
| Phase 6 | `5ef313a6a9477f05b4e46756fb8b79c0f0c3d685` | runtime 不変 |
| P7-A1 | `a02ad60878054b5846b11acac720fa2811f32505` | byte 一致 |
| P7-A2 | `2dfd85c757d96b3b546f6723f88d70b94a191f97` | byte 一致 |
| P7-A3 | `9b336091b2348cc2311872b76a7b4c1d82f92ccf` | byte 一致 |
| P7-A4a | `50b24ef6325da82999eae76c0b2982285a6ce3d5` | byte 一致 |
| P7-A4b | `b5f3a741fc10bb069112b385fe69cd7273fbb4b7` | byte 一致（A5 は Phase 7 の runtime 全体と A1〜A4b の契約をこの anchor と比べる） |

A5 は `src`・`knowledge`・`config.yaml`・`.github`・`docs/v2`・`docs/pages` を変えていない（boundary の A5 節）。

## 24. test の一覧

| file | 件数 | 対象 |
|---|---|---|
| `test_narrative_synthesis_model.py` | 514 | A1 |
| `test_narrative_pit_assembler.py` | 67 | A2 |
| `test_narrative_synthesis_engine.py` | 62 | A3 |
| `test_narrative_presentation_diff.py` | 62 | A4a |
| `test_narrative_renderer.py` | 88 | A4b |
| `test_narrative_intelligence_boundary.py` | 150 | Phase 7 の境界・凍結（A5 節を含む） |
| `test_narrative_phase7_e2e.py` | 59 | A5 の E2E ／ 敵対的 matrix E01〜E44（E04b・E06b を含む） |
| 合計 | 1002 | |

## 25. mutation の一覧

| gate | mutation | 結果 |
|---|---|---|
| P7-A2 | M1〜M15 | すべて検出 |
| P7-A3 | M1〜M15 | すべて検出 |
| P7-A4a | M1〜M15 | すべて検出 |
| P7-A4b | M1〜M15 | すべて検出 |
| P7-A5 | M01〜M25（下表） | すべて検出（26 件。M01b を含む。§下表） |

P7-A5 の mutation（scratch の clone。A1〜A4b の runtime を変異させ、A5 の E2E file の test が失敗することを確かめた。内部の検査も外した
上で検出したものを含む。基準の実行は全件 pass）:

| mutation | 内容 | 層 | 検出した E2E（失敗した件数） |
|---|---|---|---|
| M01 | 未来の Theme の漏れ（未来の時点の解決で資格を判定） | A2 | E01・E03 ほか（7） |
| M01b | governance event の cutoff の絞り込みを外す（多重防御。B2 は event を correction の chain の id 引きにしか使わないので振る舞いは同値） | A2 | E04b（構造の guard）（1） |
| M02 | 未来の evidence の漏れ（未来の時点の解決から投影） | A2 | E03・E05 ほか（11） |
| M03 | 未来の relation の漏れ | A2 | E03・E07（3） |
| M04 | 解釈 → 事実の文言 | A4b | E13・E14（2） |
| M05 | 機構の確度の強化 | A3 | E01・E02・E03・E14 ほか（28） |
| M06 | 反証の削除 | A3 | E01・E02・E08・E18（5） |
| M07 | 無効化の削除（内部の対応の検査も外す） | A4a | E01・E09・E10・E13 ほか（7） |
| M08 | CONTEXT → SUPPORTS | A2 | E01・E11・E40（3） |
| M09 | SOURCE_ASSERTED の限定の削除 | A4b | E16（1） |
| M10 | relation の反転 | A2 | E07・E15（2） |
| M11 | 推移の relation | A3 | E02・E15・E21・E32 ほか（8） |
| M12 | Theme の順位付け（model の順序の検査も外す） | A4a | E01・E02・E03 ほか（45） |
| M13 | 確信度の field（禁止 field の検査も外す） | A4b | E33・E39（2） |
| M14 | 推奨の文言 | A4b | E32（1） |
| M15 | 描画が提示を迂回（synthesis の計画を描く） | A4b | E18・E19・E20・E21（4） |
| M16 | 描画が synthesis を探索 | A4b | E01・E02・E03・E21 ほか（43） |
| M17 | 辿れない claim ／ ref を許す（byte 一致の検査も外す） | A4b | E18・E19・E20・E21（4） |
| M18 | 類似の差分の照合 | A4a | E38・E39（2） |
| M19 | ADDED SUPPORTS → 強まった | A4b | E38・E39（2） |
| M20 | REMOVED 反証 → 改善した | A4b | E39（1） |
| M21 | B7 の生成物を読む | A2 | E22〜E25 の B7（1） |
| M22 | P5 の evaluation ／ calibration を読む | A2 | E22〜E25 の P5・E37（2） |
| M23 | 暗黙の現在時刻 | A2 | E03 ほか（12） |
| M24 | Narrative の cache の書き込み | A4b | E36（1） |
| M25 | adapter 以外からの Phase 6 の import | A4b | E37（1。Phase 6 の import guard も） |

注: 最初に書いた M01（A2 の governance event の cutoff の絞り込みを外すだけ）は、B2 の `derive_lifecycle` が event を correction の chain の
id 引きにしか使わないため振る舞いが同値の mutant だった。M01 は未来の Theme 状態が実際に漏れる形に改め、絞り込みを外す形は M01b として
構造の guard（E04b）で検出する。凍結した runtime の欠陥ではない（絞り込みは多重防御として残っている）。

## 26. production 接続の前提

1. 実データでの validation と実の Theme authority への shadow 実行（§20〜§22）。
2. 人向けの Theme の表示名の認可された出所。
3. 認可された出力 adapter（Markdown ／ HTML 等の形式ごとの escape、`rendered_id` の作り直しでの検証、印 → claim の辿り）。
4. 実行の時機と範囲の運用の gate（scheduling）。
5. 監督による日本語の文言の確認（template の version を上げる手順は A4b 契約 §8）。
6. 永続化が必要なら明示の gate（現在は非永続）。

## 27. P8 への引き継ぎ

- P8 が使えるのは内部の `RenderedNarrative` ／ `RenderedNarrativeDiff` だけ。信用するときは元の提示と synthesis から描画を作り直して
  `rendered_id` の一致を確かめる（保存されない）。
- 表示の authority は A4a の提示で、描画は文言だけ。P8 は文を並べ替えたり、REQUIRED を落としたり、評価の語を足したりしない。
- 参照の印・`presentation_item_id`・claim id を落とさない（上流の ref まで辿れる）。
- LLM ／ provider ／ 公開 ／ 個人化 ／ 推奨は Phase 7 に無く、P8 が足すなら別の gate。

## 28. 最終の判定

**P7_NARRATIVE_INTELLIGENCE_COMPLETE / READY_FOR_SUPERVISOR_CLOSEOUT**

- 意味論・PIT・隠さない規則・限定・決定論・書き込みなし・境界・D-P7-A4B-1 は合成の world で敵対的に検証した（E01〜E44・mutation M01〜M25）。
- 凍結した Phase 7 の runtime に欠陥は無く、remediation は不要だった（A5 は runtime を変えていない）。
- 実データでの E2E は未実施（`REAL_DATA_E2E = NOT_RUN`）で、実データでの質は主張しない。production 接続の前提は §26。
- HARD STOP: Phase 8 は始めない。P4 ／ public ／ Pages への接続・LLM ／ provider・Narrative の永続化・凍結した runtime の変更は行わない。
