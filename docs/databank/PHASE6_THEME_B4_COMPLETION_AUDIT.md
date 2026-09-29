# Phase 6 / P6-B4 完了監査 — taxonomy / entity / discovery / proposal bridge

本書は P6-B4（B4A〜B4E）の **読み取り専用の完了監査** である。新しい runtime 挙動は実装していない。
繰延項目の解消も行っていない。追加したのは本書と CHANGELOG 追記のみ。

監査対象 anchor:

| gate | commit |
|---|---|
| Foundation | `12847bf2783330cbd310d24c8310d3bf46469f6a` |
| B1 change detection | `e2d5168cb9e595478451b2534ae0080a31ac98d5` |
| B2 lifecycle | `ce2402a085523e526b6b8d2be1202e0e2cd74b8b` |
| B3 proposal / dedup | `4808f5e7c0d8cf22709f7597edc44fb4bc4bdb4c` |
| B4A architecture audit | `66a216ced49009a0131cfbb7109ad0fd7d298850` |
| B4B taxonomy / entity | `c776fffc3c5c6bae0bf49d5d55c579e90ab58187` |
| B4C deterministic discovery | `f26ed4ffc7764425271659f0b593983779402c4c` |
| B4D discovery E2E | `30b2ef047bf5e8e63afb67bda81df715498c38b4` |
| B4E evidence attachment bridge | `f9f7cc1afe3febcf6818593c0ed4e700fdef81d5` |

---

## 1. B4 の範囲

B4 は「versioned knowledge から、人間が受理した evidence の付与計画まで」を担う。Foundation を変えない範囲で、
候補の生成・提示・受理・計画までを閉じた。

```
versioned knowledge（taxonomy / entity catalog / discovery rules）
  → deterministic discovery（純関数。run report は derived）
    → B3 proposal authority（append-only の提案と決定）
      → human decision（ACCEPT / REJECT / DEFER / NOT_DUPLICATE）
        → EvidenceAttachmentPlan（derived。永続化しない）
          → 〔未実装〕Foundation execution gate
```

最後の矢印だけが Foundation authority を変えうる。B4 には存在しない。

## 2. authority map

| class | 成果物 | 種別 | 永続化 | 変更できるもの |
|---|---|---|---|---|
| **A. versioned knowledge** | `theme_taxonomy.<v>.yaml` / `entity_catalog.<v>.yaml` / `discovery_rules.<v>.yaml` | 語彙と rule。証拠ではない | repo（不変 snapshot） | 何も変えない。読むだけ |
| **B. derived discovery output** | `DiscoveryRunReport` | 派生。監査用 | なし | 何も変えない |
| **C. proposal authority** | `EvidenceCandidateProposal` / `ThemeCandidateProposal` / `DedupReviewProposal` / `ProposalDecision` | append-only の提案と人間の決定 | B3 の JSONL（B4 は自動追記しない） | proposal 履歴のみ |
| **D. derived bridge output** | `EvidenceAttachmentPlan` | 派生。計画 | なし | 何も変えない |
| **E. Foundation authority** | `ThemeRootRecord` / `ThemeObservation` / `ThemeGovernanceEvent` / `ThemeMetadataRecord` / `ThemeSeriesMapping` | Theme の権威 | Foundation store | B4 からは変更不可 |

### 証明（監査で実行した read-only の確認）

| 主張 | 根拠 |
|---|---|
| knowledge ≠ evidence authority | knowledge module は `EvidenceAttachment` を作らず、`ThemeStore` を import しない。B4B の loader は読み取りのみ |
| discovery hit ≠ Theme | `discover()` は `ThemeRootRecord` / `ThemeObservation` を構築せず、`new_root_id` を呼ばない（grep 0 件）。出力は proposal と derived report のみ |
| proposal ≠ Theme | proposal id は `thprop_` 接頭辞の content id、root id は `theme_<ULID>`。proposal は Foundation store に存在しない |
| ACCEPT ≠ Foundation mutation | end-to-end 実行で、discovery → 提案 → ACCEPT → plan の全段階を通しても Foundation authority 5 file の byte が完全一致することを確認した |
| AttachmentPlan ≠ EvidenceAttachment authority | plan は `EvidenceAttachmentPlan` 型で、対象 observation の attachment 数は変わらない。plan は永続化されない |
| Foundation を変えうるのは将来の実行 gate のみ | B4 のどの module も `themes.store` / `themes.operations` / `themes.revision` を import しない（boundary test で固定） |

## 3. B4A 決定の照合（D-B4-1〜10）

| id | 決定 | 実装箇所 | test 証跡 | 状態 |
|---|---|---|---|---|
| D-B4-1 | knowledge は YAML ＋ versioned code model。置き場所は `knowledge/theme_intelligence/`。ruleset も repo（内容方針 ＋ guard 付き） | `knowledge/theme_intelligence/*.yaml`、`knowledge_loader.py` / `taxonomy.py` / `entity_catalog.py` / `discovery_rules.py` | `test_theme_taxonomy.py`、`test_theme_entity.py`、`test_theme_discovery_rules.py`、boundary の内容方針 guard | IMPLEMENTED |
| D-B4-2 | entity identity は `<kind>:<slug>` 不変。type は 9 種。TECHNOLOGY / POLICY_PROGRAM は entity にしない | `entity_model.EntityType`（9 種を確認）、`FOUNDATION_KIND_BY_ENTITY_TYPE` | `test_theme_entity.py`（rename で id 不変、ticker は identity でない） | IMPLEMENTED |
| D-B4-3 | taxonomy は DAG multi-parent、related edge なし、伝播なし | `taxonomy_model.TaxonomyNode`（field に `related` が無いことを確認）、`nuclear` の親は `energy` と `power` | `test_theme_discovery_false_positive.py` の階層攻撃（親子の非伝播、多親でも hit は 1） | IMPLEMENTED |
| D-B4-4 | 入力 authority は §8 の許可表。NewsClassification は不採用 | `discovery_adapter`（`InputKind` は SOURCE_DOCUMENT / NEWS_ITEM / FACT / OBSERVATION の 4 種） | `test_theme_discovery.py` 15〜24、`UNSUPPORTED_INPUT` | IMPLEMENTED |
| D-B4-5 | matching は L1 ＋ L2（限定）。L3 は B7 | `MatchLevel`（L1 / L2 のみ）、`_scan_surfaces` は限定 text 面のみ | `test_theme_discovery_false_positive.py`（本文非走査、URL / author 非走査） | IMPLEMENTED |
| D-B4-6 | 自動 promotion なし。assembly は A ＋ binding ＋ 同一 rule 内集約のみ | `discovery._build_theme_candidate`（template ＋ binding ＋ 同 rule 内 evidence 集約） | `test_theme_discovery.py` 48、`test_theme_discovery_e2e.py` の firewall 群 | IMPLEMENTED |
| D-B4-7 | 等価提案は rule を跨いで収束。pin は複合文字列 ＋ run report。B3.1 の構造化 field は後日 | `evidence_reason()`（rule 非依存 canonical）、`_pins_reason()`（`pins taxonomy=… catalog=… ruleset=…`）、`DiscoveryRunReport` | `test_theme_discovery.py` 49〜51、`test_theme_discovery_e2e.py` 13 | IMPLEMENTED_WITH_LIMITATION（B3.1 構造化 field は未実装。繰延） |
| D-B4-8 | EvidenceCandidate bridge は別 gate B4E | `evidence_bridge.py` / `evidence_bridge_model.py` | `test_theme_evidence_bridge.py`（40 件） | IMPLEMENTED |
| D-B4-9 | PIT は version 単位 ＋ `published_at`。既定 latest なし | 3 loader すべてが `expected_version` 必須 ＋ `cutoff` 比較。「latest」解決の実装は存在しない | `test_theme_discovery_replay.py` 49〜54 | IMPLEMENTED |
| D-B4-10 | slug seed は採用、entity は参照分のみ、person 不採用、信号語は再 authoring | taxonomy 8 slug、entity 15 件（person 型なし）、rule 文面は本 gate での新規 authoring | boundary の内容方針 guard（保有銘柄名称 / ticker を raw text で検査） | IMPLEMENTED |

architecture 決定が黙って変更された箇所は無い。唯一の限定は D-B4-7 の B3.1 構造化 pin field で、当初から
「後日」と決定されていたものであり、代替（複合 pin ＋ run report）が実装済みである。

## 4. B4D 決定の照合

| id | 決定 | 本監査での状態 |
|---|---|---|
| D-B4D-1 | ORIGIN_KEY 次元の MIN_DISTINCT → 独立した discovery-rule gate へ繰延。closeout で追加しない | DEFERRED（未追加を確認） |
| D-B4D-2 | 位置単位の alias 一致 → 将来の B4C knowledge / runtime version へ繰延。現行の保守的な最長一致は凍結 | DEFERRED（`_longest_only` 不変を確認） |
| D-B4D-3 | adapter の入力単位診断の集約 → B6 monitoring へ繰延 | DEFERRED（run report は record 診断を集約しないまま） |
| D-B4D-4 | 空白入りの `data center` alias → 将来の taxonomy version へ繰延。0.2.0 を変更しない | DEFERRED（0.2.0 の digest 不変を確認） |
| D-B4D-5 | 逆向き consequence の裁定 → 人間 arbitration。自動勝者 / 順位 / score を作らない | POLICY_LOCKED（2 候補 ＋ 相互 dedup review のまま） |
| FC-1 | Foundation の機構語彙拡張 → 繰延。B4D が生成した ThemeCandidate の `OTHER` 使用は 0 | DEFERRED（driver / channel / domain / consequence すべて 0） |

## 5. B4E 決定の照合

| id | 決定 | 本監査での状態 |
|---|---|---|
| D-B4E-1 | HUMAN role authority の `note` は「提案 note が先、無ければ ACCEPT 決定の理由」。audit metadata のみ | LOCKED（実装と契約 doc が一致） |
| D-B4E-2 | 重複 attachment は `ATTACHMENT_ALREADY_PRESENT` の明示的な fail closed のまま。UI 側の解釈は後日。bridge の意味論は不変 | LOCKED |
| D-B4E-3 | plan journal → 繰延。新しい authority を作らない | DEFERRED（plan に content id なし、永続化なし） |
| D-B4E-4 | CONTRADICTS / INVALIDATES の bridge → B4 の外へ繰延 | DEFERRED（`FORBIDDEN_BRIDGE_ROLE` / `INVALIDATION_REF_FORBIDDEN` で fail closed） |

## 6. identity 監査

| 層 | identity | 監査結果 |
|---|---|---|
| taxonomy | slug は不変 token。rename は「新 slug ＋ 旧 slug の deprecation」 | 0.2.0 で `supply_chain` を新設し `supply_chain_theme` を deprecated ＋ superseded_by とした。旧 node は削除していない |
| entity | `<kind>:<slug>` は不変 | 社名変更（0.1.0 → 0.2.0）でも entity_id は不変。ticker は `identifiers` であり identity ではない（有効期間で切り替わっても id は同じ） |
| discovery rule | `rule_id` ＋ `rule_version` は provenance であり proposal の意味的 identity ではない | 同一 template・同一 evidence 集合なら、rule id / version が違っても proposal_id は同一 |
| proposal | B3 の content-addressed identity。provenance / created_at / locator / note は identity 外 | 凍結済み。B4 は変更していない |
| Theme | 不透明な `theme_<ULID>` root id ＋ content-addressed `ThemeObservation` | Foundation のまま。B4 は root を作らない |
| attachment | Foundation の `attachment_key` = `ref_id#consequence_ref` | B4E は同じ key 規約を使い、Foundation の identity を再定義していない |

確認した性質:

- entity の rename は entity id を書き換えない。
- ticker は identity ではない（同一 entity で EXM1 → EXM2）。
- taxonomy の rename は新 slug ＋ deprecation であり、旧 slug は後継へ暗黙解決されない。
- 等価な discovery rule の provenance は収束しうる（同一 proposal_id）。
- evidence 集合が異なれば別 proposal になりうる（semantic fingerprint が同じでも別 id）。
- proposal id が ThemeRoot id になることはない（接頭辞も生成経路も別）。
- 受理された proposal が Theme identity を書き換えることはない（plan は identity を持たない）。

## 7. 時間軸 / PIT 監査

| 軸 | 所有者 | 規律 |
|---|---|---|
| knowledge `published_at` | B4B / B4C snapshot | `published_at <= cutoff` でのみ使用可。等号は許可、超過は `FUTURE_KNOWLEDGE` / `FUTURE_VERSION` |
| discovery `cutoff` | 呼び出し側 | 明示必須。aware のみ |
| 入力 `published_at` / `known_at` / `retrieved_at` / `as_of` | 上流 model | cutoff 等号は許可、1 マイクロ秒の超過は除外（`AFTER_CUTOFF` / `KNOWN_AFTER_CUTOFF`） |
| proposal `created_at` | discovery の `run_created_at` | 明示必須。`run_created_at >= cutoff` |
| decision `recorded_at` | 人間 | 決定の chain 解決には使わない（`supersedes_decision_id` の graph のみ） |
| `evidence_time` | 入力由来 | 提案から plan まで書き換えない |
| plan `attached_at` | 呼び出し側の `created_at` | `>= proposal.created_at`、`>= decision.recorded_at`、`>= evidence_time`。等号は許可 |
| Foundation observation `recorded_at` | Foundation | B4 は書かない |

- 「latest」「current」を暗黙に解決する実装は B4 に存在しない（3 loader すべてが `expected_version` 必須）。
- 将来の knowledge / 入力は fail closed で除外される。
- 旧 version の replay は旧 slug の意味のまま再現し、新 slug を知らない。旧 ruleset を新 knowledge に当てると
  `TAXONOMY_PIN_MISMATCH`。
- 決定性は 10 seed の入力 shuffle・既存 proposal / decision の shuffle・knowledge の再読み込みで確認済み。

## 8. source origin / 独立性 監査

- discovery は `SourceOrigin` を保守的に導く（同一記事の NewsItem / SourceDocument / Fact は同じ origin group）。
- run report は origin group を数えるが、それを「独立 source 数」とは呼ばない。THEME_CANDIDATE には
  `EVIDENCE_REFS:n;ORIGIN_KEYS:m;NOT_AN_INDEPENDENCE_CLAIM` を診断として付す。
- B4 は Foundation の qualification を一切計算しない（`evaluate_qualification` を import しない）。
- B4E も独立性を主張しない。plan の plain 表現に `qualif` / `independent` / `diversity` の語は現れない。
- qualification は Foundation の責務のまま。
- ORIGIN_KEY 次元の MIN_DISTINCT が無いため、同一 origin の 2 表現だけで THEME_CANDIDATE が成立しうる。
  これは契約どおりの挙動であり、繰延として登録済み（D-B4D-1）。

## 9. false positive 安全性 監査（B4D 結果の再掲）

| 対象 | TP | TN | FP | FN |
|---|---|---|---|---|
| EvidenceCandidate | 18 | 17 | 0 | 0 |
| ThemeCandidate | 6 | 28 | 0 | 1 |

ThemeCandidate の唯一の FN は L2 のみの theme 的文面に対する意図的な fail closed であり、
診断 `THEME_CANDIDATE_REQUIRES_L1_HIT` を伴う。

**これらは合成 gate の結果であり、実運用の precision / recall の推定ではない。**

期待値が runtime 出力から生成されていないことの確認: golden case は `Case` dataclass の固定値として authoring されており、
test は期待と実測の一致を assert する。真値ラベル（`truth_*`）は契約期待（`expected_*`）と別に持ち、混同行列は
その対から数える。B4D 中の期待値修正は 2 件のみで、いずれも corpus 作成側の誤りであり runtime 由来ではない。

## 10. 人間 governance 監査

確認した連鎖:

1. rule は提案できる（discovery が proposal を生成する）。
2. proposal は存在できる（B3 の append-only authority）。
3. 人間が ACCEPT できる（`ProposalDecision`。`actor_class` は HUMAN 固定）。
4. bridge は計画できる（`EvidenceAttachmentPlan`）。
5. **Foundation は依然として変わらない**（authority 5 file の byte 一致を実測）。

禁止されている自動動作が実装されていないことを確認:

| 禁止 | 確認 |
|---|---|
| 自動 ThemeRoot 作成 | `new_root_id` / `ThemeRootRecord` の参照 0 件 |
| 自動 proposal ACCEPT | B4 module が `ProposalDecision` を構築する箇所 0 件 |
| 自動 merge | `plan_merge` / `execute_*` の参照 0 件 |
| 自動 evidence 付与 | `attach_evidence` / `revise_observation` の参照 0 件 |
| 自動 consequence 選択 | SUPPORTS は明示必須（`CONSEQUENCE_REF_REQUIRED`）。先頭採用なし |
| 自動 invalidation | `invalidation_ref` は常に禁止 |
| 自動勝者選択 | 矛盾 rule は 2 候補 ＋ 相互 dedup review |
| 自動順位付け | score / rank / confidence の語が B4 の実行コードに存在しない |
| production の解釈 authority への自動昇格 | production bundle の closure が `themes` / `theme_intelligence` を含まない |

## 11. dedup 監査

- 生成される class は `EXACT_SEMANTIC_MATCH` と `EXACT_IDENTITY_CORE_MATCH` の 2 つのみ。
  B3 の `DedupClass` 語彙には他 4 値が存在するが、`dedup.detect_exact_duplicates` はこの 2 つしか構築しない
  （`_BASIS_FOR_CLASS` の 2 entry のみ）。test で 2 class 限定を固定している。
- 類似度 score / embedding 距離 / ranking / nearest / top-N / 自動 merge はいずれも存在しない。
- `NOT_DUPLICATE` の抑制は履歴を保存する（review を再提示しないだけで、proposal 履歴は削除しない）。
- 逆向き consequence は人間 arbitration のまま。

## 12. knowledge version 監査

| file | version | published_at | content digest（先頭 12） |
|---|---|---|---|
| theme_taxonomy | 0.1.0 / 0.2.0 | 00:00Z / 01:00Z（2026-09-20） | 0.2.0 = `75c0ae8c0c2d` |
| entity_catalog | 0.1.0 / 0.2.0 | 00:00Z / 01:00Z（2026-09-20） | 0.2.0 = `63a23fcadc1f` |
| discovery_rules | 0.1.0 | 02:00Z（2026-09-20） | `95f56e5b7018` |

- `expected_version` は必須で、完全一致のみ受け付ける。
- `published_at <= cutoff` でのみ使用可。
- content digest は semantic payload の sha256 で、宣言値との不一致は `DIGEST_MISMATCH`。
- ruleset は taxonomy / catalog の version を正確に pin し、不一致は `TAXONOMY_PIN_MISMATCH` / `CATALOG_PIN_MISMATCH`。
- latest 解決・fallback は存在しない。
- 公開済み version の in-place 変更は無い（凍結後の diff 0 を確認）。
- 旧 version の replay が成立することを確認済み。
- **closeout では新 knowledge version を作成していない。**

## 13. 機密監査

- 公開している knowledge（taxonomy / entity catalog / discovery rules）の raw text に、保有銘柄一覧の名称・ticker は
  1 件も含まれない（既存 guard が raw text で検査し PASS）。
- 過去の signal 語リスト・named benefit chain・機密 source 文面・PDF 内容は含まれない。rule 文面はすべて本 phase での
  新規 authoring である。
- 成果物に credential 文字列は無い。`knowledge_loader` / `proposal_model` に現れる `api_key` 等は **禁止語検出器側の
  pattern** であり、値ではない。
- machine 固有 path は無い。検出器の regex 自身が pattern として持つのみ。
- `knowledge/theme_intelligence/` は GitHub Actions / scripts / docs/v2 / config.yaml のいずれからも参照されておらず、
  公開出力経路に入らない。production bundle の closure からも除外されている。

### 監査で見つかった 1 件の観察（NON_BLOCKING）

B4A architecture audit doc（凍結 anchor `66a216c`）の identifier 説明行に、ticker 表記の **書式例** として
公開 ticker が 2 件（東証コード形式 1 件、米国 ticker 1 件）書かれている。これらは偶然、config の保有銘柄一覧にも
存在する。性質は次のとおり。

- 目的は「ticker は identifier であって identity ではない」という表記例であり、銘柄選定・受益連鎖・推奨ではない。
- 実装 / knowledge / 公開出力には波及していない（上記のとおり knowledge の raw text には 1 件も無い）。
- 当該 doc は凍結 anchor であり、closeout は読み取り専用のため変更しない。

分類: NON_BLOCKING。将来 doc を改版する機会に、書式例を架空 ticker へ置き換えるかは監督者判断（本書 §17 に登録）。

## 14. import / 依存 監査

実測した依存方向（intra-package）:

```
knowledge_loader
  ├→ taxonomy_model → taxonomy
  ├→ entity_model   → entity_catalog
  └→ discovery_model → discovery_predicates / discovery_rules / discovery_adapter
                          └→ discovery ──→ proposal_model / proposal_resolution / dedup
proposal_model → proposal_resolution → dedup / proposal_store / proposal_bridge
evidence_bridge_model → evidence_bridge ──→ proposal_model / proposal_resolution
```

上流（package 外）への参照は Foundation の read-only 面（`themes.model` / `themes.fingerprint` /
`themes.qualification` / `themes.resolver`）、`core.ids` / `core.time` / `core.types`、および B4C adapter だけが使う
入力 model 4 種（`facts.model` / `market.model` / `sources.model` / `databank.news_model`）に限られる。

禁止されている逆方向の依存が存在しないことを確認:

| 禁止 | 確認 |
|---|---|
| Foundation → B4 | `src/intelligence/themes/` に `theme_intelligence` の参照 0 件 |
| B1 / B2 → B4 | `change.py` / `model.py` / `lifecycle*.py` に discovery / taxonomy / entity / bridge の参照 0 件 |
| B3 → B4 | `proposal_*.py` / `dedup.py` に B4 module の参照 0 件 |
| P4 / P5 → B4 | `predictions/` / `scripts/` / `.github/` / `config.yaml` に参照 0 件 |
| production / public bundle → B4 | bundle closure に `theme_intelligence` / `themes` を含まない |

循環依存: **なし**（module graph を走査して確認）。

## 15. 凍結面 監査

closeout 時点（`f9f7cc1`）での diff はすべて 0。

| 面 | 基準 | 結果 |
|---|---|---|
| Foundation | `12847bf` | diff 0 |
| B1 | `e2d5168` | diff 0 |
| B2 | `ce2402a` | diff 0 |
| B3 runtime | `4808f5e` | diff 0 |
| B4B runtime ＋ knowledge | `c776fff` | diff 0 |
| B4C runtime ＋ knowledge | `f26ed4f` | diff 0 |
| B4D tests ＋ docs | `30b2ef0` | diff 0 |
| B4E | `f9f7cc1` | diff 0（closeout は src を触らない） |
| P4 | `15739707` | diff 0 |
| P5 | `edbd0f2` | diff 0 |
| config / workflow / 公開出力 | — | 変更なし |

## 16. 永続化 監査

| 対象 | 永続化 | 備考 |
|---|---|---|
| versioned repo knowledge（YAML 5 file） | YES | 不変 snapshot。追記も上書きもしない |
| B3 `proposals.jsonl` | authority は B3 から存在 | **B4C の純粋な discovery は追記しない**（`proposal_store` を import しない） |
| B3 `proposal_decisions.jsonl` | authority は B3 から存在 | **B4 は decision を自動追記しない**（`ProposalDecision` を構築する箇所 0 件） |
| `DiscoveryRunReport` | NO | derived。戻り値のみ |
| `EvidenceAttachmentPlan` | NO | derived。content id も持たない |
| Foundation store | B4 からの書き込み NO | authority 5 file の byte 一致を実測 |

新しい SQLite / database / journal は追加していない（`theme_intelligence` 配下に `sqlite` の語 0 件）。

## 17. B4 繰延項目 登録簿（canonical）

| # | 項目 | 分類 | 行き先 |
|---|---|---|---|
| 1 | ORIGIN_KEY 次元の MIN_DISTINCT | NON_BLOCKING / FUTURE_GATE_REQUIRED | 独立した discovery-rule gate |
| 2 | 位置単位の alias 一致（最長一致による取りこぼしの解消） | NON_BLOCKING / FUTURE_GATE_REQUIRED | 将来の B4C version |
| 3 | adapter 入力単位診断の run report 集約 | NON_BLOCKING / FUTURE_GATE_REQUIRED | B6 monitoring |
| 4 | 空白入り `data center` alias の追加 | NON_BLOCKING / FUTURE_GATE_REQUIRED | 将来の taxonomy version |
| 5 | 逆向き consequence の裁定 | POLICY_LOCKED | 人間 arbitration（自動化しない） |
| 6 | FC-1 Foundation 機構語彙の拡張 | NON_BLOCKING | 必要が生じた時点で Foundation gate |
| 7 | plan journal（誰がいつ計画したか） | OPTIONAL | 新 authority を作る判断が要る |
| 8 | CONTRADICTS bridge | FUTURE_GATE_REQUIRED | B4 の外 |
| 9 | INVALIDATES bridge | FUTURE_GATE_REQUIRED | B4 の外 |
| 10 | `EvidenceAttachmentPlan` の Foundation 実行 | FUTURE_GATE_REQUIRED | 明示的な実行 gate（B4 の直接の後続） |
| 11 | 実データでの discovery coverage 測定 | FUTURE_GATE_REQUIRED | 運用 gate。合成 gate では測れない |
| 12 | Statement 入力の対応 | OPTIONAL | Foundation の `EvidenceKind` には存在するが adapter 未対応 |
| 13 | ContextItem / NewsClassification の対応 | POLICY_LOCKED | ContextItem は Foundation で付与禁止、NewsClassification は D-B4-4 で不採用 |
| 14 | 意味的 / LLM matching（L3） | FUTURE_GATE_REQUIRED | B7 |
| 15 | 運用 runner と store への追記 | FUTURE_GATE_REQUIRED | B6 |
| 16 | B3.1 の構造化 `knowledge_versions` field | OPTIONAL | D-B4-7 の当初からの後日項目。現行は複合 pin ＋ run report |
| 17 | B4A doc の ticker 書式例を架空 ticker へ置換 | NON_BLOCKING / OPTIONAL | doc 改版時。凍結 anchor のため closeout では触らない |

いずれも本 closeout では実装していない。

## 18. test / guard

| 範囲 | 件数 |
|---|---|
| B4B（taxonomy 24 ＋ entity 26 ＋ 境界 9） | 59 |
| B4C（discovery 43 ＋ rules 15 ＋ 境界 6） | 64 |
| B4D（E2E 66 ＋ false positive 59 ＋ replay 20） | 145 |
| B4E（evidence bridge） | 40 |
| theme 関連サブセット合計 | 701 |
| guard（機密 / 境界 / bundle） | 62 |
| 全体 | 2031 |

closeout で runtime を変更していないため、test の変更も無い。

## 19. B4 完了条件の照合

| 条件 | 結果 |
|---|---|
| B4A の architecture 決定が照合済み | ○（§3。黙った変更なし） |
| B4B knowledge が検証済み | ○（§12） |
| B4C deterministic discovery が検証済み | ○（§7、§8） |
| B4D 敵対 E2E が検証済み | ○（§9。Theme FP 0） |
| B4E 受理 evidence bridge が検証済み | ○（§2、§10） |
| 未解決 blocker なし | ○ |
| Foundation 不変 | ○（§15、実測 byte 一致） |
| 人間 governance 境界が保たれている | ○（§10） |
| 自動の Theme / evidence 変更なし | ○（§10） |
| PIT が決定論的 | ○（§7） |
| identity が安定 | ○（§6） |
| score / rank / prediction との結合なし | ○（実行コードに該当語なし） |
| 公開 / 顧客向け出力との結合なし | ○（§13、§14） |
| 繰延項目が明示登録済み | ○（§17） |
| 全 suite PASS | ○（2031） |
| guard PASS | ○（62） |
