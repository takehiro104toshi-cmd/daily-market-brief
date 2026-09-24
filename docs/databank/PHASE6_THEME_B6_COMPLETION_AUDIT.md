# PHASE 6 / P6-B6 — THEME MONITORING COMPLETION AUDIT

AUDIT / DOC ONLY。runtime・test・knowledge・config・workflow・scripts は変更していない
（B6E-RERUN anchor `00bb5a2` 以降、`src/` ・`tests/` ・`knowledge/` ・`config.yaml` ・`.github/` ・`scripts/` の diff 0）。

**結論: B6 は完了条件を満たす。ただし B6-DEF-1（観測 channel の coverage 欠落）は B7 着手前の必須 remediation であり、
B6 closeout の次の gate は B7 ではなく P6-B6R1 である。**

finding の件数を重要度・evidence の強さ・投資妥当性として解釈しない。本 audit の検証はすべて synthetic であり、
実世界の precision / recall・因果の正しさ・投資上の有用性を主張しない。

---

## 1. phase lineage / anchors

| gate | anchor | 結果 |
|---|---|---|
| B6A monitoring architecture audit | `08c59febe4c13bf3ca78242cac5e65f8ddccda77` | D-B6-1〜14 を決定 |
| B6B model / vocabulary | `b12a4e3994920d18c8ab5526aaaddf15bcd94fbb` | record model・語彙・identity |
| B6C deterministic engine / ruleset | `d0aaee957723e445ed0dbef2af11c836d69f34c3` | 18 condition・versioned ruleset |
| B6D operational review store / runner | `8ef09ab1db447ad783defd0c6afecd3e943edcfe` | review journal・adapter・read-only runner |
| B6E adversarial E2E | `8655d8d03a02e953c67a4dd8dac1edf805307a80` | **BLOCKER-1 FOUND** |
| B6D-R1 PIT remediation | `e67a5462d41507ad6c70f8c539f91fd8d6ffc8f1` | BLOCKER-1 REMEDIATED |
| B6E-RERUN | `00bb5a22584958c0af1f6cd25882028e1ccf4c9c` | **BLOCKER-1 CLOSED** |
| 参照: B5 freeze | `8322cb1db6a991191500863afc05b66168e9a747` | 上流 relation authority |

履歴は一直線で、revert / squash / 書き換えは無い（B6E の証跡 commit は現 HEAD の祖先）。

## 2. authority map

| 対象 | 分類 | 書き手 | 永続化 |
|---|---|---|---|
| `MonitoringFinding` | DERIVED / NON-AUTHORITY | engine（純関数） | **しない** |
| `MonitoringRunReport` | DERIVED / NON-AUTHORITY | engine（純関数） | **現状しない**（B6D で Option A を採用） |
| `ReviewItemState` | OPERATIONAL / APPEND-ONLY / **HUMAN ONLY** | 人間（`append_review_state`） | `theme_intelligence/monitoring_review_states.jsonl` |
| monitoring ruleset | VERSIONED KNOWLEDGE | 人間（版管理された YAML） | `knowledge/theme_intelligence/monitoring_rules.0.1.0.yaml` |
| Theme / evidence / proposal / relation | 上流 authority（Foundation / B3 / B5B / B5C） | 各 authority の正規 API | 各 journal |

**B6 は authority を変更しない。** 新しい semantic / governance authority も作っていない。

## 3. 最終 pipeline

```
上流 authority（Foundation / B3 / B5B / B5C の journal）
   │  read-only open・store 検証（破損は fail closed）
   ▼
PIT 解決（Foundation / B5B は resolver の cutoff、B3 / B5C は runner が解決前に cutoff 濾過）
   ▼
上流の derived state（B2 lifecycle view / B3 status・chain / B5 edge・端点 / B5C status）
   ▼
monitoring_adapter（純写像。silent coercion 禁止）
   ▼
monitoring_engine（決定論・I/O なし・versioned ruleset）
   ▼
MonitoringFinding（非永続） ＋ MonitoringRunReport（非永続）
   ▼
review lookup（review journal を read-only で読み、resolve_review_state で解くだけ）
```

人間の行為:

```
MonitoringFinding ──(人が見る)──▶ ReviewItemState.build(actor_class=HUMAN)
                                   ──▶ MonitoringReviewStore.append_review_state()（唯一の書き込み経路）
```

**存在しない近道**（すべて test で不在を固定）:

| 近道 | 状態 |
|---|---|
| Finding → governance 変更 | 無い |
| Finding → relation の実行（plan → B5B append） | 無い |
| Finding → evidence の付与 | 無い |
| Finding → Theme の変更 | 無い |
| Finding → 取引行為 / 推奨 / signal | 無い |
| run → review state の自動追記 | 無い |

## 4. B6A decision audit（D-B6-1〜14）

| id | 決定 | 状態 | 根拠 / 記録先 |
|---|---|---|---|
| D-B6-1 | authority を持たない 3 層（knowledge / derived / operational）、層 4 は `MonitoringFinding` | IMPLEMENTED | §2、B6B contract |
| D-B6-2 | Option C（finding 非永続、review state のみ operational journal）。run report は任意で運用追記 | IMPLEMENTED（任意部分は「追記しない」を選択） | B6D contract §2（Option A 採用の理由） |
| D-B6-3 | finding_key = (condition_id, subject_kind, subject_ref, salient_state) の content id、run 時刻を含めない、状態変化で別 key | IMPLEMENTED（B6B で `schema_version` と `category` を identity に追加して精緻化） | B6B contract §5 identity contract（`(schema_version, condition_id, category, subject_kind, subject_ref, salient_state)`） |
| D-B6-4 | cutoff は明示かつ knowledge cutoff と同一、現在時刻を読まない、閾値は ruleset 定数 | IMPLEMENTED（一部 SUPERSEDED: stale の日数は B2 `LifecyclePolicy` が所有し、ruleset は提案滞留の閾値だけを持つ） | B6C contract §8 閾値の所有（「stale までの日数: B2 `LifecyclePolicy`。ruleset に置かない」）。runner は同じ cutoff で ruleset を読み込み PIT 解決する |
| D-B6-5 | versioned ruleset、宣言的述語のみ、任意 Python / regex / LLM 禁止 | IMPLEMENTED（より厳格: ruleset は有効化・閾値・表示 key のみで、述語すら持たない） | B6C `PROHIBITED_RULE_KEYS`（22 key） |
| D-B6-6 | severity / priority を導入しない | IMPLEMENTED | model / engine / runner に severity・priority・score・rank が無い |
| D-B6-7 | 矛盾 / 無効化は B2 の derived flag を参照するだけ | IMPLEMENTED | adapter の `ROLE_BY_FLAG`、自動 retire 等の経路なし |
| D-B6-8 | relation は B5 authority を読むのみ、graph 推論なし | IMPLEMENTED | adapter / engine に traversal・centrality・strength なし |
| D-B6-9 | integrity と review condition を category で分ける、run 単位の技術情報は run report に、読めなければ PARTIAL ＋ INTEGRITY | IMPLEMENTED（**例外 1 件を登録**: 観測 channel の欠落情報が run report に載らない → B6-DEF-1） | §17 |
| D-B6-10 | runner は read → PIT → rule → derived → 許可された review 追記まで | IMPLEMENTED（精緻化: review 追記を runner から分離し、人間専用の別 API にした） | B6D contract §6・§7（runner は `append_review_state` を参照しない） |
| D-B6-11 | real-data は shadow / no-write / no-notification から | 段階 1（synthetic）は IMPLEMENTED、実データ段階は **DEFERRED** | B6-DEF-5 |
| D-B6-12 | 実装順 B6B → C → D → E → closeout | IMPLEMENTED（BLOCKER-1 対応で B6D-R1 と B6E-RERUN を挿入） | §1 |
| D-B6-13 | internal のみ、通知 / 公開は scope 外 | IMPLEMENTED | 通知・公開・scheduler の module なし、production closure に不在 |
| D-B6-14 | 層 4 の名称は `MonitoringFinding` | IMPLEMENTED | model |

B6A §の語彙草案にあった run status `FAILED` は B6B で削除した（「report を出せない run は report を持たない」、
B6B contract §3 語彙に記録）。**記録の無い drift は 0 件。** 精緻化・一部 supersede・例外はすべて上表の記録先に残っている。

## 5. B6B model audit

| 項目 | 結果 |
|---|---|
| category | 7（EVIDENCE / SEMANTIC / LIFECYCLE / PROPOSAL / DISCOVERY / RELATION / INTEGRITY）。INTEGRITY だけが技術 category |
| subject kind | 8（bounded な列挙） |
| `SalientStateKind` | 14。kind ごとに key 集合が凍結、値は bounded な token のみ（数値・時刻を入れられない） |
| finding identity | `(schema_version, condition_id, category, subject_kind, subject_ref, salient_state)` |
| identity から除外 | cutoff・ruleset version・knowledge version・condition version・message key・trigger / supporting refs・diagnostics。経過日数・件数・時刻は salient state に入れられない |
| run identity | `(schema_version, cutoff, ruleset_version, knowledge_versions, input_digests)`。recorded_at と結果は除外 |
| run status | COMPLETE / PARTIAL のみ。`COMPLETE ⟺ unevaluated_conditions == ()` を model が強制 |
| review disposition | ACKNOWLEDGED / DISMISSED / DEFERRED のみ（RESOLVED / CLOSED / AUTO は無い） |
| review actor | HUMAN のみ（RULE / LLM_PROPOSAL は `FORBIDDEN_REVIEW_AUTHORITY`） |
| review chain | predecessor graph だけで解く（RESOLVED / NONE / UNRESOLVED / INVALID）。latest-wins なし |
| episode | identity に episode は無く、再出現で自動 reopen しない |
| 直列化 | canonical JSON 1 行、content id |
| 禁止語彙 | severity / score / rank / probability / prediction は model に存在しない |

**`COMPLETE` の意味論は B6B の定義（「要求されたすべての条件を評価できた」）を authoritative contract として保持する。**
B6-DEF-1 は、この定義を変えて受け入れることなく、定義どおりに是正する対象である。

## 6. B6C engine audit

| 項目 | 結果 |
|---|---|
| condition | 厳密に 18（`CONDITION_REGISTRY` と `REQUIRED_CONDITION_IDS` が一致） |
| ruleset | `monitoring_rules.0.1.0.yaml`（digest・envelope・published_at・expected version を検証）。latest 解決なし |
| DSL | なし。rule が持てるのは condition_id / version / enabled / 分類の再宣言 / message_key / threshold_days だけ |
| regex / fuzzy / LLM 評価器 | なし（`PROHIBITED_RULE_KEYS` 22 key で schema 拒否） |
| engine の I/O | なし（import は `core.time`・model・rules・標準 library のみ） |
| 現在時刻 | 読まない |
| 決定論 | 同一入力で同一出力。finding は `finding_id` 順（順序に優先度の意味なし） |
| 評価不能 | 未評価 ＋ INTEGRITY finding ＋ PARTIAL（freshness token 欠落・created_at 欠落も未評価） |
| authority 変更 | なし |
| ranking / 予測 / 取引の意味論 | なし |
| synthetic coverage | positive 18/18、negative 18/18 |

## 7. B6D operational audit

| 項目 | 結果 |
|---|---|
| 永続化するもの | review state だけ |
| finding / run report の永続化 | 0 / 0 |
| runner | 構造として read-only（shadow flag を持たない） |
| data_root | 明示必須（空・空白・`~` 始まりは拒否） |
| review journal | canonical 行の追記専用、`open('ab')` → flush → `os.fsync` |
| 冪等 / 衝突 | 同 id 同 bytes は ALREADY_PRESENT、同 id 異 bytes は CONFLICT |
| 破損 | 12 種の corruption code と 5 種の history code で fail closed |
| 自動修復 | なし |
| adapter | field ごとの写像表（B6D contract §8）。None・UNRESOLVED・破損・未知 root を偽にしない |
| review と finding | 別物（ACK しても finding は出続ける） |
| 自動 reopen | なし |
| scheduler / notifier | なし |

## 8. PIT blocker の履歴

| gate | 状態 | 内容 |
|---|---|---|
| B6E | **FOUND** | B3 / B5C の提案・決定が run cutoff で濾過されず、未来の record が過去の finding / digest / run_id に影響 |
| B6D-R1 | **REMEDIATED** | runner が canonical record を解決前に cutoff 濾過（`monitoring_runner.py` のみ変更） |
| B6E-RERUN | **CLOSED** | close 基準をすべて満たす |

確認済みの項目（B6D-R1 A〜R matrix と B6E-RERUN §2 / §4）:
B3 提案の cutoff / B3 決定の cutoff / B5C 提案の cutoff / B5C 決定の cutoff / 解決前の濾過 /
未来の後継の隔離 / 妥当な journal での未来の fork の隔離 / 未来の record が過去の digest・run_id・finding・
diagnostics・status を変えないこと。

**B6E 証跡の訂正（監査履歴として保持）**: B6E の `test_d08` は欠陥を検査していなかった（xfail の原因は
PIT 上正しい衝突）、`test_d09` は判別力が無かった、`test_d04` は label を誤っていた。いずれも B6D-R1 で訂正した。
BLOCKER-1 の実在は `test_d07`、B6E report §10 の再現手順、B6D-R1 A〜R matrix によって独立に確認されている。

## 9. 6 family PIT matrix（最終）

| family | t − 1µs | t | t + 1µs |
|---|---|---|---|
| Theme observation / evidence | 不可視 | 可視 | 可視 |
| Theme governance | 不可視 | 可視 | 可視 |
| B3 proposal / decision | 不可視 | 可視 | 可視 |
| B5B relation assertion | 不可視 | 可視 | 可視 |
| B5B relation governance | 不可視 | 可視 | 可視 |
| B5C relation proposal / decision | 不可視 | 可視 | 可視 |

**PIT 保証の境界**: 不正・破損した authority は PIT 濾過より先に検証され、全 cutoff で fail closed し得る
（例: 経路外で書かれた B5C の fork は過去の cutoff でも authority 失敗になる）。これは store の完全性検証であり、
historical leakage ではない。正規の append 経路で書ける record に限れば、未来の record は過去 run を変えない。

## 10. fail-closed audit

| 仕込み | silent ignore | 修復 | COMPLETE ＋ 0 |
|---|---|---|---|
| malformed JSON | なし | なし | なし |
| truncated line | なし | なし | なし |
| blank line | なし | なし | なし |
| non-object | なし | なし | なし |
| non-canonical | なし | なし | なし |
| unsupported schema | なし | なし | なし |
| unknown field | なし | なし | なし |
| conflicting duplicate | なし | なし | なし |
| invalid history（dangling / fork / 順序） | なし | なし | なし |
| invalid timestamp（解析不能 / naive） | なし | なし | なし |

対象: Foundation / B3 / B5B / B5C / review journal（B6E §B、B6D-R1、B6E-RERUN §5）。未来日付の破損行も読み飛ばさない。

## 11. 決定論

同じ意味的入力 → 同じ run_id / input digest / finding / report / diagnostics。物理順の shuffle（11 seed）で不変。
現在時刻・mtime・path・inode に依存しない（別 path への複製と mtime 変更で一致）。random な UUID は使わない（すべて content id）。

## 12. zero-write

`run_monitoring()` の前後で data_root の全 file inventory が一致（new 0 / deleted 0 / modified 0）。
Foundation / B3 / B5B / B5C / review / knowledge の hash は不変。finding 永続化 0、run report 永続化 0、review の自動追記 0。

## 13. review と governance の分離

| review の語 | 意味しないもの |
|---|---|
| ACKNOWLEDGED | Theme governance の ACCEPT ではない |
| DISMISSED | evidence の無効化でも条件の解消でもない（finding は出続ける） |
| DEFERRED | B3 / B5C の DEFER 決定ではない（提案 journal は byte 不変） |
| `ReviewItemState` | semantic authority ではない |

review history は人間の運用履歴だけである（B6E-RERUN §9 で全 disposition について検証）。

## 14. RR-3

B5 の RR-3 POLICY LOCK を継承する。B6 には `RelationAssertionPlan` / `EvidenceAttachmentPlan` の実行、
authority への append、governance の変更、提案の自動受理のいずれも存在しない。将来の execution gate は B6 の責務ではない。

## 15. condition coverage

- synthetic: positive 18/18、negative 18/18。
- cross-layer（実 authority fixture 経由）: 17/18。
- **#17 `RELATION_GOVERNANCE_CHAIN_UNRESOLVED` の分類（固定）**: 現 store architecture 上は到達不能な防御的 condition。
  B5B store が per-edge の unresolved chain を load 時に拒否するため、store 経路では authority 全体の失敗として表れる。
  in-memory 解決では到達可能で、写像と評価器は生きている。削除も変更もしない。

## 16. real-data shadow

**REAL_DATA_SHADOW_NOT_RUN。** 理由: 実 Theme authority が存在しない（どの環境にも Theme journal が無い）。
**disposition: NON_BLOCKING_DEFERRED_UNTIL_REAL_AUTHORITY_EXISTS**（監督判定）。

将来の手順: 最初の実 authority dataset が生まれる → read-only shadow（harness の 1 command）→ `wrote_nothing` →
`replay_identical` → 記述的な noise review。operational / public な consumer の前に実施する。precision / recall は主張しない。

## 17. B6-DEF-1（canonical 登録）

| 項目 | 内容 |
|---|---|
| **ID** | B6-DEF-1 |
| **Title** | Observation channel completeness blind spot |
| **Status** | **NON_BLOCKING_FOR_B6_CLOSEOUT / MANDATORY_PRE_B7_REMEDIATION** |
| **Risk** | MonitoringRunReport may claim COMPLETE while conditions #5/#6/#11/#12 were not evaluated because observation channels were not supplied. |
| **Authority impact** | NONE |
| **PIT impact** | NONE |
| **Finding correctness impact** | No evidence of incorrect emitted findings. |
| **Coverage/status correctness impact** | YES |
| **Deadline** | BEFORE P7 ENTRY（監督指示の原文どおり）。Status が MANDATORY_PRE_B7_REMEDIATION のため、実効の期限は B7 entry の前である |
| **Owner** | P6-B6R1 remediation gate |

監督 disposition の意味:

- B6 closeout は妨げない。B7 entry は妨げる。B7 の実装を始める前に必ず remediation する。
- `COMPLETE` の意味論を変更して受け入れることは禁止。現状を「仕様どおり」と再定義することも禁止。
- B6B の `COMPLETE` 定義を authoritative contract として保持する。

**将来 gate（仮称）: P6-B6R1 MONITORING COVERAGE-COMPLETENESS REMEDIATION**

最低限の目的:

1. 「channel 未供給」と「channel は供給されたが空」を、canonical な `MonitoringRunReport` 上で区別する。
2. 必要な入力が未供給なら、該当 condition を unevaluated として扱い、`COMPLETE` を返さない。

具体的な実装方法は本 closeout では決めない（候補の比較は `PHASE6_THEME_MONITORING_E2E_RERUN.md` §15）。
B6E-RERUN の `test_70` / `test_71` は現挙動の記録であり、P6-B6R1 がこれを反転させて是正を確認する。

## 18. deferred register

| id | 内容 | blocking | owner | deadline | risk | future gate |
|---|---|---|---|---|---|---|
| **B6-DEF-1** | 観測 channel の coverage 欠落（§17） | B6 closeout: No / **B7: Yes** | P6-B6R1 | BEFORE P7 ENTRY（実効: B7 entry 前） | report 単体の consumer への false assurance（既定 run すべてが該当） | P6-B6R1 |
| B6-DEF-2 | #17 は store 経路で到達不能な防御的 condition（§15） | No | B6 closeout で記録済み | なし | 低（fail closed で表れる） | B5B の load 意味論を変える gate があれば再評価 |
| B6-DEF-3 | PIT 保証の境界: 不正な authority は PIT 濾過前に検証され全 cutoff で fail closed し得る（§9） | No | B6 closeout で記録済み | なし | 低（黙った漏洩ではない） | なし |
| B6-DEF-4 | review state は PIT authority ではない（運用状態） | No | 監督者 | なし | 低 | 過去時点の review 状態が必要になった時 |
| B6-DEF-5 | real-data shadow 未実施（§16） | No | 最初の実 authority を作る gate | operational / public consumer の前 | coverage と noise が実測されていない | 実 authority 生成後の shadow gate |
| B6-DEF-6 | B6D limitation #2〜#6（attachment key の locator 化、`chain_kind` 固定、関係提案 chain 破損の integrity 表現、`NO_STATE_AT_CUTOFF` の category、governance events の供給） | No | B6B / B6C / B6D を開く将来 gate | なし | 低〜中（表示の粗さ） | 未定 |

**B5 から継承した deferred**（RR-1 / RR-2 / RR-3 ほか）は `PHASE6_THEME_B5_COMPLETION_AUDIT.md` §14 と
その register を参照する。本 audit では再定義しない。

## 19. security / confidentiality

tracked の production journal 0、confidential PDF 0、sqlite / env 0、credential 0、machine 固有 path 0、
記事本文 0、個人の portfolio データ 0。monitoring の出力は本文・長い引用を保持しない
（finding は bounded な token、shadow summary は counts・id・code・version・hash のみ）。
docs に現れる `?api_key=` は guard が拒否する対象の説明であり、credential ではない。

## 20. import / layering

- 依存方向: Foundation / B1〜B5 → （read-only）→ B6。B6 は下流の読み取り専用層。
- Foundation / B1〜B5 は B6 を import しない（`theme_intelligence` の外に monitoring を参照する module は無い。import boundary guard が固定）。
- legacy report / notifier / publication は B6 を import も使用もしない。`.github/` ・`config.yaml` ・`scripts/` は `theme_intelligence` を参照しない。
- production bundle closure に `theme_intelligence` は含まれない。public / customer surface は無い。

## 21. 限界

1. 検証はすべて synthetic。実世界の precision / recall・因果の正しさ・投資上の有用性は主張しない。
2. real-data shadow 未実施（B6-DEF-5）。
3. B6-DEF-1 が未是正（B7 前に必須）。
4. B5C の DEFER 可視性は monitoring の出力から観測できない（OPEN と OPEN_DEFERRED はどちらも live）。
5. naive timestamp の経路は fault injection でしか到達しない。

## 22. closeout readiness と次の gate

B6A〜B6E-RERUN の性質（authority 非保持・PIT・決定論・zero-write・fail closed・review 分離・RR-3・security）は
すべて保持されている。BLOCKER-1 は CLOSED。B6-DEF-1 は監督判定どおり B7 前の必須 remediation として登録した。

**B6 は supervisor freeze に進める。B6 closeout 後の次の gate は P6-B6R1 であり、B7 ではない。**
