# PHASE 6 / P6-B6E-RERUN — THEME MONITORING E2E REVALIDATION（PIT remediation 後）

TEST / AUDIT / DOC ONLY。runtime は変更していない（R1 anchor `e67a546` 以降、`src/` ・`knowledge/` ・
`config.yaml` ・`.github/` ・`scripts/` の diff 0。monitoring 6 module は anchor と byte 一致）。

| 項目 | 判定 |
|---|---|
| BLOCKER-1（提案 authority の PIT 漏洩） | **CLOSED** |
| 6 family PIT | 全 green |
| zero-write / authority hash / 決定論 / fail closed | 全 PASS |
| blind spot（`OBSERVATION_NOT_SUPPLIED` ＋ `COMPLETE`） | 提案: **NON_BLOCKING_DEFERRED_WITH_CONTRACT**（§15） |
| real-data shadow | **NOT_RUN**（Theme authority がどの環境にも存在しない） |
| closeout readiness | deferred item 付きで closeout audit へ進める |

検証 file: `tests/intelligence/test_theme_monitoring_e2e_rerun.py`（48 件）。既存の
`test_theme_monitoring_e2e.py`（B6E）と `test_theme_monitoring_runner_pit.py`（B6D-R1）も無変更で再実行した。

finding の件数を重要度・evidence 強度・投資妥当性として解釈しない。以下の結果はすべて synthetic であり、
実世界の precision / recall / 因果の正しさ / 投資上の有用性を主張しない。

---

## 1. original B6E 証跡の整理

**BLOCKER-1 は実在した。** 同時に、B6E（`8655d8d`）の PIT test の一部には証拠上の問題があった。
「一部の test が誤構成だった」ことは「BLOCKER-1 が存在しなかった」ことを意味しない。

| 証拠 | 内容 | 評価 |
|---|---|---|
| B6E `test_d07`（strict xfail） | 未来の提案で過去 cutoff の digest が変わらないことを要求し、修正前の runner で失敗 | **正しく欠陥を検出** |
| B6E report §10 の再現手順 | 未来（day 10）の関係提案が day 5 の run で衝突 finding を生む | **正しい再現** |
| B6D-R1 A〜R matrix | 修正前の runner で 17 件 fail、修正後に全件 pass | **独立に実在を確認** |
| B6E `test_d08`（strict xfail） | 「未来」の提案が撤回 edge の無い A→C を指し、xfail の原因は day(5) 記録の既存提案による PIT 上正しい衝突 | **欠陥を検査していなかった**（R1 で訂正） |
| B6E `test_d09` | 比較した 2 cutoff の間に提案 record が無く、修正の前後どちらでも成立 | **判別力が無かった**（R1 で置換） |
| B6E `test_d04` | `theme_governance` と名付けた case が genesis observation の境界だった | **label の誤り**（R1 で訂正し、本物の governance 境界を追加） |

8655d8d は履歴に残っている（`test_03` が `git merge-base --is-ancestor` で固定）。revert / squash / 書き換えはしていない。

## 2. BLOCKER-1 の再検証（close 基準）

B6E の world 上で、B6D-R1 とは独立の fixture を使い、過去 cutoff day(10) の run の signature
（`run_id` ・`input_digests` ・status ・finding の canonical bytes ・report diagnostics ・runner diagnostics）が
未来の record の追加で変わらないことを確認した。

| close 基準 | test | 結果 |
|---|---|---|
| 未来の B3 提案が過去 run に影響しない | `test_10` | PASS |
| 未来の B3 決定が過去 run に影響しない | `test_11` | PASS |
| 未来の B5C 提案が過去 run に影響しない | `test_12` | PASS |
| 未来の B5C 決定が過去 run に影響しない | `test_13` | PASS |
| 未来の後継が過去の終端を変えない（B3 / B5C） | `test_14` / `test_15` | PASS |
| 未来の fork が過去の chain を unresolved にしない | `test_16`（B3）/ §4（B5C） | PASS |
| 過去の input digest / run_id / findings / diagnostics / status が不変 | `test_10`〜`test_16`（signature） | PASS |
| signature がこれら全部を含むこと自体 | `test_17` | PASS |
| xfail 0 / xpass 0 | full suite | PASS |

**BLOCKER-1 = CLOSED。**

## 3. 6 family PIT matrix

B6D-R1 の `test_six_family_pit_boundary` を無変更で再実行。record 時刻 t に対し cutoff = t − 1µs で不可視、
t と t + 1µs で可視。

| family | t − 1µs | t | t + 1µs |
|---|---|---|---|
| Theme observation / evidence | 不可視 | 可視 | 可視 |
| Theme governance（退役） | 不可視 | 可視 | 可視 |
| B3 theme proposal / decision | 不可視 | 可視 | 可視 |
| B5B relation assertion | 不可視 | 可視 | 可視 |
| B5B relation governance | 不可視 | 可視 | 可視 |
| B5C relation proposal / decision | 不可視 | 可視 | 可視 |

## 4. 解決前濾過の証明

1. **挙動**（`test_20`）: 未来（day 80 / 81）にだけ fork する B3 chain は、cutoff day(70) では
   `PROPOSAL_DECISION_CHAIN_UNRESOLVED` を出さず、day(90) では出す。
2. **情報論的な証明**（`test_21`）: 全 record を既存 resolver に渡した結果は `UNRESOLVED`、
   `active_decision = None`、`chain = ()` である。過去時点の終端を復元する情報が残っていないため、
   「解決してから cutoff で補正する」設計ではこの test を通せない。
3. **負の対照**（`test_22`）: runtime は変えず、test 内で濾過を外した runner に差し替えると、同じ入力で
   未来の fork が過去 cutoff に漏れる。test に判別力があることの証明。

## 5. PIT 保証の境界（新たに明文化）

- **妥当な journal**（正規の append 経路で書ける record だけから成る）では、未来の record は過去 run を変えない（§2）。
- **正規の append 経路では fork を書けない**（B3 / B5C とも append 時に拒否。`test_30`）。
- **経路外で書かれた不正 record** の扱いは store の frozen 意味論に従う:
  - B5C（および B5B・Foundation）は load 時に history 全体を拒否する。時刻が未来でも
    「読み飛ばして過去を健全に見せる」ことはせず、**全 cutoff で authority 失敗（PARTIAL）**になる（`test_31`）。
  - B3 は fork を load 時に診断付きで受け入れるため、PIT 濾過により過去 cutoff からは見えない（`test_16` / `test_20`）。
- どちらも黙った漏洩ではない。「store の検証が PIT 濾過より先」（B6D-R1 §9）の直接の帰結であり、仕様どおりである。

## 6. corruption / fail closed

B6E の matrix（Foundation / B3 / B5B / B5C / review × malformed / truncated / non-canonical / not-object / blank /
欠損 / 重複 / unsupported schema / unknown field）を無変更で再実行し全件 green。B6E-RERUN で次を追加した。

| 追加 case | 対象 | 結果 |
|---|---|---|
| unsupported schema | B3 / B5C 提案 | PARTIAL・修復なし（`test_40`） |
| unknown field | B3 / B5C 提案 | PARTIAL・修復なし |
| conflicting duplicate id | B3 / B5C 提案 | PARTIAL・修復なし |
| invalid history（dangling predecessor） | B3 / B5C 決定 | PARTIAL（`test_41`） |
| 未来日付の破損行 | B3 / B5C 決定 | PARTIAL（`test_42`。「未来だから無視」しない） |
| 不正な timestamp（解析不能 / naive） | B3 / B5C | PARTIAL（B6D-R1 matrix） |

silent COMPLETE は 1 件も観測されなかった。

## 7. zero-write / authority hash / finding・report 非永続

B6E の `test_e02`（data_root 全 file の sha256 inventory 比較: new 0 / deleted 0 / modified 0）・`test_e03`
（Foundation / B3 / B5B / B5C / review / knowledge の hash 不変）・`test_e04`（finding・run report 非永続）・
`test_b06`（破損状態でも byte 不変）、B6D-R1 の zero-write test をすべて再実行し green。
review state の自動追記は 0（review journal は run の前後で byte 一致）。

## 8. 決定論

同一 cutoff / authority bytes / knowledge version / ruleset / 観測入力で、`run_id`・`input_digests`・
finding と report の canonical bytes・diagnostics が一致（B6E `test_d01`）。独立 record の物理順 shuffle
11 seed で一致（`test_d02`）。別 path への複製と mtime 変更でも一致（B6D `test_17`）。
shadow harness を 2 回起動しても summary は完全一致（`test_90`）。

## 9. review state の分離

| 主張 | 検証 |
|---|---|
| Finding ≠ ReviewItemState | ACK / DISMISSED / DEFERRED のいずれを記録しても finding の canonical bytes は不変（`test_50`） |
| Acknowledgement ≠ Governance | review の前後で Foundation / B3 / B5B / B5C journal の hash 不変（`test_50`） |
| Dismissed ≠ 条件の解消 | DISMISSED 後も finding は出続ける（`test_50`） |
| Deferred ≠ 提案の DEFER | review の DEFERRED 後も B3 決定 journal は byte 不変、提案は OPEN のまま（`test_51`） |
| review journal ≠ Theme authority | review 追記の前後で Theme resolution が完全一致（`test_50`） |
| 消失しても書き換えない・再出現しても reopen しない | B6E `test_c06` |

## 10. RR-3 / authority safety

monitoring の runner / adapter / store は authority record を構築しない（`.build` 呼び出しは無い）。
`RelationGovernanceEventType` / `GovernanceEventType` / `ThemeRelationGovernanceEvent` / plan 型 / bridge /
authority 側 append / `attach_evidence` / `execute` は現れない（`test_60`）。monitoring の 6 module は
bridge・`themes.operations`・`themes.revision`・`themes.store` を import しない（`test_61`）。
自動 restore / retract / plan 実行 / 提案決定への経路は存在しない。B5 execution gate は作っていない。

## 11. 18 condition coverage と cross-layer coverage

- synthetic: positive 18/18、negative 18/18（B6E §A を無変更で再実行）。
- cross-layer: **17/18**（B6E §C）。

### condition #17（RELATION_GOVERNANCE_CHAIN_UNRESOLVED）の分類

**「現 store architecture 上の到達不能（防御的 condition）」**である。dead production code でも future condition でもない。

- store 経路: B5B `ThemeRelationStore` が per-edge の unresolved chain を生む history を load 時に拒否するため、
  runner は authority 全体の失敗（`AUTHORITY_STATE_UNUSABLE` ＋ PARTIAL）として表す（B6E `test_c04`）。
- in-memory 経路: `resolve_relation_graph` を store を介さずに呼ぶと `UnresolvedEdge` が生じ、adapter の
  `unresolved_relation_snapshot` → engine で #17 が発火する（`test_80`）。写像と評価器は生きている。
- 意図して作った到達不能ではなく、B5B の store 不変条件の帰結である。B5B の load 意味論が変わるか、
  store を介さない解決経路が加われば到達する。

## 12. blind spot の実験

day70 の cross-layer world（4 condition すべてが成立し得る状態）で、3 観測 channel を供給 / 欠落させた（`test_70`）。

| case | report.status | unevaluated | report.diagnostics | 黙った condition | runner diagnostics |
|---|---|---|---|---|---|
| all supplied | COMPLETE | 0 | 空 | なし | なし |
| all omitted | COMPLETE | 0 | **空** | #5 / #6 / #11 / #12 | 3 channel すべて |
| omit arrived_attachment_keys | COMPLETE | 0 | 空 | #6 | arrived_attachment_keys |
| omit semantic_revision_observation_ids | COMPLETE | 0 | 空 | #5 | semantic_revision_observation_ids |
| omit discovery_outcome_tokens | COMPLETE | 0 | 空 | #11 / #12 | discovery_outcome_tokens |

追加の観測:

- report 単体では、「channel を供給しなかった」と「供給したが空だった」を区別できない（`test_71`）。
- B6C engine は、必要な入力が無い condition を既に**未評価**として扱っている
  （freshness token 欠落 → `THEME_EVIDENCE_STALE`、created_at 欠落 → 提案滞留。`test_72`）。
- runner はこの 3 channel を authority から導く経路を持たず、既定は空の `MonitoringObservations()` である（`test_73`）。
  **つまり既定の run はすべて、この 4 condition について評価していないのに `COMPLETE` を返す。**

## 13. blind spot の意味論分析

1. **COMPLETE の意味**: B6B model は「`COMPLETE` は要求されたすべての条件を評価できたことを意味する」と定義し、
   「静かな無検出（finding 0 件の COMPLETE）を作らせない」と書く。現挙動はこの 4 condition について、
   実際には「供給された入力の範囲で評価が異常なく終わった」という意味で `COMPLETE` を返している。
2. **既存 contract の wording**: B6A §14.1（「静かな無検出は monitoring における最悪の失敗様式」）、
   B6A D-B6-9（「run 単位の技術情報は run report に留める」）、B6B model の `COMPLETE` 定義、
   B6C engine contract §13.1（必要な入力が無い condition は未評価にする）はいずれも前者の意味を支持する。
   後者を支持する記述は B6A〜B6C に無い。B6D contract §19 は limitation #1 として開示しているが、`COMPLETE` を再定義してはいない。
3. **未評価に入るべきか**: 意味論上は入るべきである。B6C の先例（入力欠落 → 未評価 ＋ 診断 code）と同じ構造だから。
4. **report 単体の consumer への false assurance**: 与える。`COMPLETE`・未評価 0・report diagnostics 空で、
   「評価したが該当なし」と区別できない（`test_70` / `test_71`）。
5. **主要 consumer surface**: `MonitoringRunReport` である。B6B の canonical・content-addressed・直列化可能な record
   （`canonical_monitoring_line` / `parse_monitoring_record`）であり、B6A D-B6-9 も run 単位の技術情報の置き場を
   run report としている。`MonitoringRunResult.diagnostics` は B6D の in-memory wrapper の field で、canonical な直列化を持たない。
6. **B7 が diagnostics を落とす危険**: ある。B7 が canonical record である report を読めば、欠落は見えない。
   現状で diagnostics を運ぶのは test helper の shadow summary だけである。
7. **残したまま closeout して壊れるもの**: authority（zero-write 証明済み）、PIT（§2〜§3）、
   出た finding の意味的正しさはいずれも壊れない。弱まるのは run status の **coverage の主張**
   （18 condition 中 4 condition）だけである。

## 14. blind spot の現時点の封じ込め

- runner の diagnostics が欠落 channel を決定的に列挙する。
- shadow harness の summary は `observation_channels_not_supplied` と `runner_diagnostics` を出す。
- report を読む consumer はまだ存在しない（Phase 6 は production 未接続、B7 未着手、real data なし）。

## 15. disposition の提案

**提案: C — NON_BLOCKING_DEFERRED_WITH_CONTRACT**

- **A を採らない理由**: 現挙動は B6A / B6B / B6C の wording と矛盾する。受け入れれば `COMPLETE` の意味を黙って変えることになる。
- **closeout を止めない理由**: authority・PIT・finding の正しさに影響しない。report の consumer がまだ存在しない。
  欠落は runner の surface で決定的に開示されている。どの修正案も既定 run の意味（例: 既定 run が常に PARTIAL になる）を
  変えるため、観測 channel の供給設計と一緒に決めるべき設計判断である。
- B6B の `COMPLETE` 定義を closeout の不変条件として扱うなら、同じ evidence は B（closeout 前の remediation）も支持する。どちらを採るかは監督者の判断である。

契約（deferred の条件）:

1. runner の直接の呼び出し元以外が `MonitoringRunReport` を読む前に（B7、永続化、公開出力、通知、
   coverage の証拠として解釈する real-data shadow のいずれか）、この gap を remediation する。
2. それまでの consumer は report と一緒に `MonitoringRunResult.diagnostics` を必ず読み、
   condition #5 / #6 / #11 / #12 について `COMPLETE` を「供給された入力に失敗が無かった」と読む。
3. B6 closeout 文書にこの契約をそのまま載せる。
4. remediation gate は `test_70` の matrix を保持し、`all omitted` が「`COMPLETE` ＋ 未評価 0」でなくなることを確認して反転させる。

remediation の候補（実装しない。選択は監督者）:

| 候補 | 変更面 | 帰結 |
|---|---|---|
| (a) runner が欠落 channel ごとに `AuthorityFailureSnapshot(blocked_condition_ids=…)` を渡す | runner のみ | 既存の B6C routing で未評価 ＋ PARTIAL。ただし channel の欠落が INTEGRITY finding（`AUTHORITY_STATE_UNUSABLE`）として出る |
| (b) 「未供給」を snapshot で表現し、engine が INTEGRITY finding なしで未評価にする | B6C engine ＋ B6D adapter / runner | freshness token 欠落と同じ扱い。既定 run は PARTIAL |
| (c) channel が実装されるまで 4 condition を無効化した ruleset version を出す | versioned ruleset | coverage の縮小を明示する。ruleset の変更になる |

## 16. real-data shadow

**NOT_RUN。** `data/` 配下に Theme authority journal（roots / observations / proposals / relation assertions /
relation proposals / review states）は 1 件も無い（`test_92`）。Phase 6 は production へ接続されていない。
Windows 側の操作も要求しない。shadow harness の read-only / `wrote_nothing` / `replay_identical` 契約は
B6E `test_f01`〜`test_f03` と `test_90` で再確認した。

## 17. security / confidentiality

tracked の production journal・PDF・sqlite・env は 0 件。monitoring 関連の tracked file（src / tests / docs）に
machine path は無く、credential 様の文字列は test の adversarial fixture（予約 domain `example.invalid` /
`example.test` 上の偽値、または denylist 走査の語）だけである（`test_91`）。shadow summary は counts・安定 id・
diagnostic code・version・hash のみ。

## 18. deferred register

| id | 内容 | owner | future gate | risk |
|---|---|---|---|---|
| B6-DEF-1 | blind spot: 観測 channel 欠落でも report は `COMPLETE`（#5 / #6 / #11 / #12） | 監督者（設計判断） | report の consumer が生まれる前（遅くとも B7 entry gate、または coverage の証拠として real-data shadow を解釈する前） | report 単体の consumer への false assurance。既定 run すべてが該当 |
| B6-DEF-2 | #17 は store 経路で到達不能（防御的 condition） | B6 closeout audit で記録 | なし（B5B の load 意味論が変わる時に再評価） | 低。fail closed で表れる |
| B6-DEF-3 | 経路外の不正 record は B5C / B5B / Foundation で全 cutoff fail closed、B3 は診断付きで load（PIT 保証の境界。§5） | B6 closeout audit で記録 | なし | 低。黙った漏洩ではない |
| B6-DEF-4 | review state は PIT ではない（運用状態） | 監督者 | 必要時 | 低 |
| B6-DEF-5 | real-data shadow 未実施 | 最初の Theme data_root を作る gate | その gate の直後 | coverage / noise が実測されていない |
| B6-DEF-6 | B6D limitation #2〜#6（attachment key の locator 化、`chain_kind` 固定、関係提案 chain 破損の integrity 表現、`NO_STATE_AT_CUTOFF` の category、governance events の供給） | B6 closeout audit | B6C / B6D を開く将来 gate | 低〜中（表示の粗さ） |
| B5 由来 | RR-1 / RR-2 / RR-3 ほか B5 closeout の deferred | 既存どおり | 既存どおり | 既存どおり |

## 19. 限界

1. すべて synthetic。実世界の precision / recall・因果の正しさ・投資上の有用性は主張しない。
2. B5C の DEFER 可視性は monitoring 出力から観測できない（OPEN と OPEN_DEFERRED はどちらも live。B6D-R1 報告のとおり）。
3. naive timestamp の経路は fault injection でしか到達しない（model が aware を強制するため）。
4. blind spot は未解決（§15）。

## 20. closeout readiness

BLOCKER-1 は CLOSED、6 family PIT は全 green、zero-write・決定論・fail closed・権限分離・RR-3・security は全 PASS。
blind spot は B6-DEF-1 として契約付きで deferred にする提案である。**deferred item 付きで B6 closeout audit へ進める。**
