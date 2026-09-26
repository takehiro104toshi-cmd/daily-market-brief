# PHASE 6 FINAL COMPLETION AUDIT — THEME INTELLIGENCE

Phase 全体の完了監査。新しい能力なし・実 provider なし・実行なし。本監査の変更は文書・CHANGELOG・完了の凍結 test
（`tests/intelligence/test_theme_phase6_completion.py`）だけで、production runtime は変更していない。

出典の略記: A0.5 ＝ `PHASE6_FOUNDATION_DECISIONS.md`、A1 ＝ `…SEMANTICS_AUTHORITY_CONTRACT.md`、A2 ＝ `…IDENTITY_EVIDENCE_CONTRACT.md`、
A3 ＝ `…PERSISTENCE_REVISION_CONTRACT.md`、MAT ＝ `…FOUNDATION_INVARIANT_MATRIX.md`、B0 ＝ `…INTELLIGENCE_ARCHITECTURE_AUDIT.md`、
各 gate の contract / completion audit は `docs/databank/PHASE6_THEME_*.md`。

---

## 1. 結論

**Phase 6 Theme Intelligence は完了条件を満たす。** 判定: `P6_THEME_INTELLIGENCE_COMPLETE / READY_FOR_PHASE7_PLANNING`。

- 当初の範囲（Foundation ＋ B1〜B7。B0 の推奨順 F）はすべて実装・凍結済み。当初計画から形を変えた項目（B6 の派生 SQLite
  index、B3 / B5 の journal 名）は各 gate の architecture audit で監督判断として確定済みで、完了を妨げない（§2）。
- authority の境界は凍結されている。自動の処理（discovery・monitoring・LLM）が作れるのは L1 の候補・提案と派生物だけで、
  L2 の governance は人間、L3（production の解釈 authority）は Phase 6 では到達不能（§4・§7）。
- **Phase 5 closeout から B7 までの全期間、runtime の変更は Phase 6 の 3 名前空間への新規 file の追加だけ**（62 file。
  既存 file の変更 0）。後の gate が前の gate の runtime を変えたことは一度も無い（§19・`test_theme_phase6_completion.py`）。
- blocker なし（§22）。残る仕事は real provider の運用化・提案の実行・production 統合・実データの蓄積と評価・将来の意味拡張で、
  §21 の登録簿に分類した。

## 2. 当初の範囲

B0（`P6_B0_THEME_INTELLIGENCE_ARCHITECTURE_AUDIT_COMPLETE`、B0 §17〜§19 の推奨順 F）の計画と最終状態:

| # | capability | B0 の計画（要旨） | 最終状態 | 凍結 anchor |
|---|---|---|---|---|
| F | Theme Foundation | 持続する Theme の identity・履歴・PIT 解決（A0.5〜A3） | 実装・凍結（A4d.1 で blocker A4D-1〜3 を修正） | Foundation |
| B0 | architecture audit | B1〜B7 の順序と境界 | 完了（文書） | —（`686f4ea`） |
| B1 | Change Detection | 2 時点の解決の純粋な差分（知識軸 ／ evidence 時間軸） | 実装・凍結 | B1 |
| B2 | Lifecycle view | governance 層（authoritative な読み取り）＋ 派生の evidence 条件層 | 実装・凍結 | B2 |
| B3 | Proposal journal ＋ Dedup | 提案・人間の decision・exact dedup・plan を返す bridge | 実装・凍結 | B3 |
| B4 | Taxonomy ＋ Entity ＋ Discovery | versioned knowledge・決定論的 discovery（提案だけ）・attachment plan | 実装・凍結（B4A〜B4E） | B4 |
| B5 | Relation graph | 記述的な型付き有向グラフ・関係提案・人間の decision / 検証 | 実装・凍結（B5A〜B5D、R1） | B5 |
| B6 | Monitoring | 決定論的 condition の監視と人間の review 状態 | 実装・凍結（B6A〜B6E、D-R1、B6R1） | B6 |
| B7 | LLM 提案（任意・最後） | 提案だけの LLM 層（vendor 中立・鍵なし） | 実装・凍結（B7A〜B7G、closeout） | B7 |

当初計画との違い（いずれも各 gate の監督判断で確定済み。後付けの新要件ではない）:

- B6 の「派生 SQLite index」は作っていない（B6A / B6D で review 状態だけを journal にする Option A を採用。Phase 6 は SQLite を
  使わない）。MAT #76 / #85（派生 index の性質）は index を導入する場合の条件として §21 に残す。
- journal 名は B0 の案（`theme_proposals.jsonl` 等）から各 contract の名前（`theme_intelligence/proposals.jsonl` 等）に変わった
  （B5 completion audit §3.1 に意図的な差として記録）。
- B0 §3 の M12（Phase 7 への interface）は Phase 7 planning の範囲（§23 に暫定契約だけを置く）。
- 範囲外として当初から明示: 会社別 thesis・受益 ranking（Phase 9）、公開 / 顧客出力・Brief・Compass・P5 calibration・
  scheduling（B0 §10・§11.2・§15、A0.5 §9）。

## 3. architecture

### 3.1 目的

Theme Intelligence は時間を通じて持続する仮説 / intelligence の層である（A0.5 F-3: 複数の観測を時間を通じて結び、その支持・
反証・変化を点時刻で再構成できる、持続的で evidence に裏付けられた市場 / 投資の仮説・機構）。evidence を観測し、Theme の
identity と履歴を保ち、変化を検出し、lifecycle を表し、提案を支え、決定論的に候補を見つけ、Theme 間の記述的な関係を表し、
条件を監視し、上限つきの LLM 提案生成を許す。

**しないこと**: Production DNA（Compass DNA）への自動昇格、人間の governance 判断の自動化、trading の自動実行。

### 3.2 概念上の data flow（同期した 1 本の実行鎖ではない）

```
[authority]           上流の観測・evidence（B4 入力: NewsItem / SourceDocument / Fact / Observation）
                        ▼（人間の実行だけ: operations・attach_evidence・metadata）
                      Theme Foundation（roots・observations・governance・metadata・series mappings）
                        │ PIT resolver（cutoff）
[派生の解釈]            ├─▶ B1 Change Detection（2 時点の差分）
                        ├─▶ B2 Lifecycle view（governance 位置 ＋ evidence 条件）
                        ├─▶ B4 Discovery（versioned knowledge で候補）──┐
                        ├─▶ B5 Relation resolver / graph（記述的）       │
[提案 authority / L1]   │   B3 提案・decision journal ◀──────────────────┤（提案だけ。人間の decision）
                        │   B5C 関係提案・decision journal ◀─────────────┤
                        │   B5B relation assertion / governance（人間の実行だけ）
[運用の review]         ├─▶ B6 Monitoring（finding・run report は派生）→ review 状態（人間だけ・運用）
[提案生成]              └─▶ B7 LLM（PIT manifest → 生成 → 厳格 parse → 決定論検証 → check-then-reuse）──▶ B3 / B5C
```

各層は独立に呼ばれる（B1・B2・B4・B5・B6・B7 は caller が cutoff を与えて個別に実行する）。authority・派生の解釈・運用の
review・提案生成は別の面であり、下流が上流の authority を書き換える経路は無い（§16）。

## 4. authority model

| state | 分類 | 書き手 | 許される変更 |
|---|---|---|---|
| Foundation Theme（roots・observations・governance・metadata・series mappings の 5 journal） | AUTHORITATIVE（L1 候補 ／ L2 reviewed） | Foundation の operations・attach_evidence・metadata（人間の決定の実行） | 追記のみ・canonical・fsync・同 id 異 bytes は CONFLICT・single writer（A3 §7・§8） |
| EvidenceAttachment（observation 内） | AUTHORITATIVE | 同上（新しい observation revision として） | 追記のみ。訂正は新 record ／ event（A3 §15） |
| GovernanceEvent（11 種） | GOVERNANCE（人間だけ） | 人間の actor | 追記のみ。`EVENT_REVERSED` で訂正（A3 §10.1・§30） |
| B3 提案 journal | AUTHORITATIVE（L1 提案。Theme ではない） | `ProposalStore.append_proposal`（RULE・HUMAN・B7 経由の LLM_PROPOSAL） | 追記のみ・exact 同一は冪等・同 id 異 bytes は CONFLICT |
| B3 decision journal | GOVERNANCE（人間だけ） | `ProposalStore.append_decision`（HUMAN） | 追記のみ。`supersedes_decision_id` で訂正 |
| B4 knowledge（taxonomy・entity catalog・discovery rules） | VERSIONED KNOWLEDGE | 人間の knowledge 版の採用 | 新 version の追加だけ（`published_at ≤ cutoff`、latest 解決なし） |
| B4 discovery の派生物（`DiscoveryRunReport`・`EvidenceAttachmentPlan`・`ThemeCreationPlan`） | DERIVED / NON-AUTHORITY | 純関数 | 永続しない |
| B5C 関係提案 journal | AUTHORITATIVE（L1 提案） | `RelationProposalStore.append_proposal` | 追記のみ |
| B5C 関係 decision ／ SourceClaimVerification（ACCEPT decision に内包） | GOVERNANCE（人間だけ） | `append_decision`（HUMAN） | 追記のみ |
| B5B relation assertion ／ relation governance | AUTHORITATIVE（`HUMAN_ASSERTED` ／ `SOURCE_ASSERTED`）／ GOVERNANCE（RETRACTED・RESTORED） | 人間の実行だけ（実行 gate は未実装。RR-3） | 追記のみ |
| B6 `MonitoringFinding` ／ `MonitoringRunReport` | DERIVED / NON-AUTHORITY | 純関数 | 永続しない |
| B6 `ReviewItemState` | OPERATIONAL（人間だけ。governance ではない） | `MonitoringReviewStore.append_review_state`（HUMAN） | 追記のみ |
| B7 生成の成果物（request・envelope・manifest・生成入力・生成結果） | DERIVED / NON-AUTHORITY（LLM 出力は UNTRUSTED） | B7B〜B7E | 永続しない |
| B7 生成監査 journal | OPERATIONAL / AUDIT | `LlmGenerationJournal` だけ | 追記のみ |
| B7 検証済み plan ／ 提出結果 | DERIVED / NON-AUTHORITY | B7D ／ B7F | 永続しない（提出は B3 / B5C への L1 提案の追記だけ） |

凍結文言（抜粋）: 「automatic candidate ≠ reviewed Theme」「reviewed Theme ≠ Compass authority」（A1 §16）、
`FINDING_NON_MEANING`・`REVIEW_IS_NOT_GOVERNANCE`（B6）、`PROPOSER_IS_NOT_AUTHORITY`・`SOURCE_ASSERTED_NON_MEANING`（B5）、
`PROPOSAL_IS_NOT_DECISION`（B7F）。

## 5. 時間 model

| 時刻 | 意味 | 規則 |
|---|---|---|
| knowledge time（`published_at`） | versioned knowledge が使えるようになった時刻 | `published_at ≤ cutoff` だけ使える（`FUTURE_KNOWLEDGE`） |
| evidence time（`evidence_time` ＋ basis ／ quality） | evidence が指す現実の時刻 | `retrieved_at` ／ `created_at` を代用しない（A2 §7） |
| `attached_at` ／ observation `recorded_at` | system が知った時刻（知識軸） | `root.created_at ≤ attached_at ≤ observation.recorded_at`、`evidence_time > attached_at` は拒否 |
| governance ／ metadata ／ mapping の `recorded_at` | 人間の決定が記録された時刻 | aware UTC |
| caller の PIT cutoff | 「その時点で何が見えたか」 | 必ず caller が与える aware な時刻。暗黙の now ／ latest は無い |
| 運用の生成時刻（B7 `generated_at`・B6 run 時刻・B7F `submitted_at`） | 運用記録の時刻 | caller が与える。可視性の判定には使わない |

PIT の対応:

| 層 | PIT | 備考 |
|---|---|---|
| Foundation resolver | 対応（cutoff） | 純関数。cutoff 後の record は結果に影響しない（A3 §13・§32） |
| B1 | 対応（2 つの cutoff） | 逆順の cutoff は `CUTOFF_ORDER` |
| B2 | 対応（`resolution.cutoff` の snapshot） | policy は明示入力 |
| B3 | **現在の authority だけ**（cutoff 引数なし） | PIT で読むのは B6 runner の `_visible_at`（B6D-R1）。B7C は B3 状態を読まない |
| B4 | 対応（knowledge pin・cutoff） | knowledge は `published_at ≤ cutoff`（`FUTURE_KNOWLEDGE`）、入力は adapter が cutoff で濾過 |
| B5B | 対応（relation resolver） | B5C 提案は現在の authority（B6 runner が cutoff で濾過） |
| B6 | 対応（run cutoff） | review 状態は PIT ではない（運用。B6-DEF-4） |
| B7 | B7C〜B7E は対応（manifest・生成入力の replay） | **B7F の提出は現在の authority だけ**（backtest ではない） |

integrity-before-PIT: 壊れた authority は未来日付の行でも全体を止める（Foundation・B6-DEF-3・B7C）。

## 6. identity と履歴

| identity | 形 | 種類 |
|---|---|---|
| Theme root | `theme_<ULID>`（生成 id。内容から導出しない） | event / 生成 identity |
| observation | `thobs_`（IDENTITY / SEMANTIC 内容だけの content id） | 意味の content id |
| governance event ／ metadata ／ series mapping | `thgov_` ／ `thmeta_` ／ `thmap_`（記録の content id） | event の content id |
| B3 提案 ／ decision | `thprop_`（provenance・created_at・attached_at 除外）／ `thdec_`（recorded_at 除外） | 意味の content id ／ event の content id |
| relation assertion ／ relation governance | `threl_` ／ `thrgov_` | 記録の content id |
| B5C 関係提案 ／ decision | `threlprop_` ／ `threldec_` | 意味の content id ／ event の content id |
| monitoring finding | `thmfind_`（cutoff・version・run を除外） | 意味の content id |
| monitoring run ／ review 状態 | `thmrun_`（cutoff を含む）／ `thmrev_` | 運用の id |
| B7 plan ／ 上流提案 | `thllmplan_` ／ B3 / B5C の id（LLM の文・provider・model・時刻を除外） | 意味の content id |
| B7 attempt ／ 監査 record | `thllmatt_`（generated_at を含む）／ `thllmaud_` | 運用の event identity |

履歴: observation は更新しない（1 root 1 本の supersession chain。fork は `UNRESOLVED(FORK)`）。driver・channel・domain・
subject の差し替えは新 root（`IDENTITY_CORE_CHANGED`）。merge は新 root（`MERGE_RESULT`）で旧 root を残し、evidence の
割り当ては明示、split は 2 つ以上の結果 root、successor は `SUPERSEDED_BY_ROOT`。すべて人間だけ（A3 §17〜§19）。訂正は
新しい record / event で、旧 bytes は変えない（A3 §15）。上流の改訂は Theme の履歴を書き換えない（A3 §16）。

## 7. governance（Option B）

**Option B（A1 §16）**: system は canonical な INTERNAL CANDIDATE Theme（L1）を自動で作ってよいが、reviewed / accepted（L2）
は人間の承認を要する。L3（production の解釈 authority）は Phase 6 では到達不能。

人間だけが行う操作: L1 → L2 の受理（accept）・却下（reject）・保留（defer）・merge・split・retire・reopen・reviewed class の
変更（certainty change）・evidence role の訂正・metadata の訂正・事象の取消し（`EVENT_REVERSED`）・提案 decision
（B3: ACCEPT / REJECT / DEFER / NOT_DUPLICATE、B5C: ACCEPT / REJECT / DEFER）・SOURCE_ASSERTED の出典主張の確認
（SourceClaimVerification）・relation の宣言 / 撤回 / 復元・knowledge 版の採用・monitoring の review 状態。

LLM（B7）と決定論的 discovery（B4）・monitoring（B6）はこの境界を越えない: B4 は提案だけで RootRecord の自動作成は既定で
無効（B0 §6）、B6 の review は HUMAN 固定（RULE / LLM_PROPOSAL は `FORBIDDEN_REVIEW_AUTHORITY`）、B7 の上限は L1 提案
（B7 closeout）。

## 8. Foundation

- anchor `12847bf2783330cbd310d24c8310d3bf46469f6a`（`P6_THEME_FOUNDATION_COMPLETE / CLOSED / FROZEN`）。
- A4d E2E で見つかった blocker A4D-1（root 内の identity core 変更の受理）・A4D-2（`METADATA_CORRECTION_APPROVED` を含む store を
  再度開けない）・A4D-3（宣言済み結果 root の未来依存の診断）を A4d.1 で `store.py` / `resolver.py` だけの変更で修正
  （strict xfail 5 → PASS、remediation test 27）。
- 不変条件 matrix: PROVEN 81・STRUCTURAL 13・DEFERRED 3（#23・#76・#85）・BLOCKED 0。#51（L2 に LLM_PROPOSAL の role が
  無いこと）は後の受理検査に一部持ち越し（§21 P6-DEF-01）。
- **B1〜B7 は Foundation の意味を黙って変えていない**: `src/intelligence/themes` は Foundation anchor と byte 一致（完了 test）。
  Foundation を import してよいのは read-only surface だけ（import 境界 guard）。

## 9. B1 Change Detection

- anchor `e2d5168cb9e595478451b2534ae0080a31ac98d5`。
- 純粋な派生 `ThemeChangeSet`（`compare_resolutions` ／ `detect_changes`）。authority ではなく journal も content id も持たない。
- 知識軸（attached_at ／ recorded_at）と evidence 時間軸（`DATED_WITHIN_WINDOW` ／ `DATED_BEFORE_WINDOW` ／ `UNDATED`）を分ける。
- score・momentum・rank・weight・方向・昇格の語彙なし（`QUALIFICATION_CHANGED` は `NOT_A_PROMOTION`）。authority を変えない。

## 10. B2 Lifecycle

- anchor `ce2402a085523e526b6b8d2be1202e0e2cd74b8b`。
- `derive_lifecycle` → `ThemeLifecycleView` ＝ `GovernanceLifecycleView`（governance 位置の読み取り）＋ `EvidenceConditionView`
  （排他的でない条件 flag）。派生・永続しない。
- REOPENED → ACCEPTED。終端の訂正（ROLE_ / CERTAINTY_CHANGE_ / METADATA_CORRECTION_APPROVED）は状態を変えない
  （`CORRECTION_TERMINAL_IGNORED`、事象が無ければ `GOVERNANCE_EVENTS_REQUIRED` で推測しない）。
- evidence 条件は governance 状態を変えない（無効化 evidence で自動 RETIRED にしない）。隠れた authority の変更なし。
- 文書の不整合（非 blocking）: B2 contract §10 は上の解釈を「監督者の要確認事項」のまま残しているが、B3 contract の見出しは
  「監督者決定 B2-D1〜D3」を前提と記録している。本監査の指示（REOPENED → ACCEPTED と終端訂正の意味論を確認せよ）と実装は
  一致しており、凍結された意味論は実装どおりである。文書の文言合わせは §21 P6-DEF-31。

## 11. B3 Proposal / Dedup

- anchor `4808f5e7c0d8cf22709f7597edc44fb4bc4bdb4c`。
- 提案 ≠ Theme。decision は HUMAN だけ（actor_ref・reason 必須、訂正は `supersedes_decision_id`）。
- dedup は exact だけ（`EXACT_SEMANTIC_MATCH` ／ `EXACT_IDENTITY_CORE_MATCH`）。類似度・score・rank・nearest・embedding なし。
  DEDUP_REVIEW の ACCEPT は merge しない。
- bridge（`plan_theme_creation_from_accepted_proposal`）は plan を返すだけ（`execute_candidate`・`ThemeStore.append_*` を
  呼ばない）。
- B7 期の利用: B7F は B3 の `append_proposal` ／ `get_proposal` と凍結 constructor をそのまま使い（check-then-reuse は
  B5 completion audit §10.1 の運用契約どおり）、B3 の model・store・契約を変えていない（B3 runtime は anchor と byte 一致）。

## 12. B4 Discovery

- anchor `10b44839d0aa33f83b6517552ab8a6b7ed06a3fa`（B4A〜B4E。B4 completion audit §19 の 16 条件すべて ○）。
- versioned knowledge（taxonomy 0.1.0 / 0.2.0、entity catalog 0.1.0 / 0.2.0、discovery rules 0.1.0。`expected_version` 完全一致・
  latest なし・`published_at ≤ cutoff`）。
- 決定論的 discovery の出力は提案だけ（EVIDENCE_CANDIDATE・THEME_CANDIDATE・任意の DEDUP_REVIEW ＋ 派生 run report）。
  root を作らず、Foundation・ProposalStore に書かない。確度は `HYPOTHESIZED_MECHANISM` 固定。
- evidence attachment plan（B4E）は非 authority（SUPPORTS / CONTEXT だけ、role provenance は HUMAN、`execute_*` なし）。
- 偽陽性 gate（B4D、合成 35 件）: EvidenceCandidate FP 0、ThemeCandidate FP 0（FN 1 は意図した fail closed）。**合成の結果で
  あり実運用の precision / recall ではない**。
- Foundation を黙って変えない（discovery → 提案 → ACCEPT → plan の後も Foundation の 5 file は byte 一致）。
- B4 の繰越 17 項目は実装せず §21 に統合。

## 13. B5 Relation Graph

- anchor `8322cb1db6a991191500863afc05b66168e9a747`（`P6_B5_COMPLETION_AUDIT_PASS_WITH_NON_BLOCKING_DEFERRED_ITEMS`）。
- 記述的な graph（7 つの公開 method だけ。rank・score・確信度・中心性・PageRank・重要度・推奨なし。推移辺を導出しない）。
- SOURCE_ASSERTED ＝ 「出典がその関係を主張した」（`SOURCE_ASSERTED_NON_MEANING` ＝ 因果の真実を system が確認したことでは
  ない）。受理には人間の SourceClaimVerification（B5C-R1、10 条件）が要る（確認するのは出典の主張であって真実ではない）。
- 提案（B5C）と assertion（B5B）は分離。B5C の module は assertion を書く経路を持たない。
- RR-3（POLICY LOCKED）: 将来の `RelationAssertionPlan` → B5B 実行 gate は plan object を信頼せず、authoritative な提案 ＋
  人間の decision（＋ SourceClaimVerification）から再導出するか、同等の不変条件を完全に再検証しなければならない。
- 繰越（D3〜D5・RR-1 / RR-2・実行 gate 等）は §21 に統合。

## 14. B6 Monitoring

- anchor `7a8f8a473e6668a5cc782930dedf262818525b08`（B6A〜B6E、B6D-R1、B6 closeout、B6R1、B6R1-RERUN）。
- `MonitoringFinding`・`MonitoringRunReport` は派生・非 authority・永続しない。`ReviewItemState` は運用・追記のみ・HUMAN だけ
  （ACKNOWLEDGED / DISMISSED / DEFERRED。RESOLVED・CLOSED・AUTO_* なし）。
- 18 の condition rule（`monitoring_rules.0.1.0.yaml`。合成で正 18/18・負 18/18、層横断 17/18。#17 は現 store では到達不能な
  防御的 condition）。
- PIT remediation（BLOCKER-1: B3 / B5C の提案と decision を run cutoff で濾過していなかった）は B6D-R1 で修正し B6E-RERUN で
  CLOSED。coverage-completeness（B6-DEF-1: 観測 channel 未供給でも COMPLETE になった）は B6R1 で修正し B6R1-RERUN で CLOSED。
- authority を変えない（finding → governance・関係実行・evidence 付与・Theme 変更・trade・自動 review の近道は無い）。
- 実データ shadow は `REAL_DATA_SHADOW_NOT_RUN` ／ `NON_BLOCKING_DEFERRED_UNTIL_REAL_AUTHORITY_EXISTS`（harness は準備済み）。

## 15. B7 LLM Proposal

- anchor `785837fc387178d1f963f4b012a03fbe950acedf`（B7A〜B7G ＋ closeout。`P6_B7_COMPLETE`）。
- LLM の上限は L1 提案。厳格 schema（B7B）・PIT manifest（B7C）・決定論的な意味検証（B7D）・offline の Fake / Recorded 生成と
  生成監査 journal（B7E）・check-then-reuse の提案提出（B7F）・敵対的 E2E（B7G）。
- 実 provider なし・人間の decision なし・Foundation / B5B への実行なし。generation_ref と実在しない root はいずれも
  ACCEPTABLE_BOUNDARY（B7 closeout §12・§13）。

## 16. 層横断の不変条件

| 不変条件 | 根拠（test / guard） |
|---|---|
| 提案 ≠ authority の実行 | B3 bridge・B4E・B5C bridge は plan だけ。B7F は L1 提案だけ（B7G AV〜AZ） |
| LLM ≠ HUMAN | B7D provenance lock・B7F 再検証・B7G Y / Y2・mutant M4 |
| discovery ≠ Theme | B4 は提案だけ・root 自動作成なし（B4 completion audit §2） |
| monitoring ≠ governance | `REVIEW_IS_NOT_GOVERNANCE`・review は HUMAN・finding は非 authority（B6） |
| 関係提案 ≠ relation assertion | B5C module に assertion 書き込み経路なし・RR-3 |
| reviewed ／ APPROVED の知識 ≠ Production DNA | A1 §11・§16（Compass DNA 昇格は禁止）・§17 |
| Phase 6 は P5 calibration を自己学習に使わない | A0.5 F-10・B6 の非目標（P5 calibration feedback・DNA self-learning）・B7（journal は入力でない） |
| Phase 6 は P4 / P5 / 公開出力へ自動昇格しない | Phase 6 package を import する外部 module なし・production bundle から除外（§18） |

## 17. Production DNA の境界

- Phase 6 は `knowledge/compass_dna/*`（`market_rules.yaml`）・`src/intelligence/compass/market_principles.py`・P4 Morning Brief の意味・P5 の予測 / calibration
  の意味を変えない。`knowledge/compass_dna` は Phase 5 closeout 以降変更なし（最終変更は Phase 6 開始前。完了 test）。
- P5 calibration・B6 monitoring・B7 生成の成否・人間の提案受理率から Production DNA への feedback loop は無い: Phase 6 の
  package は compass・reports・predictions・evaluation・calibration を import しない（完了 test）、B7 生成監査 journal は生成入力
  にも evidence にもならない（B7G AP / AQ）、B6 に score・学習の経路は無い。

## 18. 公開 / legacy の境界

Phase 6 は内部に留まる: Phase 6 の package（`themes`・`theme_intelligence`）を import する module は Phase 6 の外に無い
（legacy `main.py`・`src/report`・P4 `/v2`・`scripts` を含む。完了 test）。`themes` は production bundle の除外 package、
`theme_intelligence` は production bundle の runtime closure に入らない（import 境界 guard）。GitHub Pages（`docs/pages`）・
workflow（`.github`）・scheduler・通知・portfolio / trading は Phase 6 の期間に変更されていない（完了 test）。

## 19. 検証の証拠

### 19.1 凍結の連鎖（`test_theme_phase6_completion.py`）

| anchor | 期間の runtime 差分（すべて新規追加） |
|---|---|
| Phase 5 closeout `edbd0f203fd2b96a5dbfff921ccf0ba584cbef88` | —（Phase 6 の起点） |
| Foundation `12847bf2783330cbd310d24c8310d3bf46469f6a` | `themes/` 8 module |
| B1 `e2d5168cb9e595478451b2534ae0080a31ac98d5` | `theme_intelligence/` 3 module |
| B2 `ce2402a085523e526b6b8d2be1202e0e2cd74b8b` | 2 module |
| B3 `4808f5e7c0d8cf22709f7597edc44fb4bc4bdb4c` | 5 module |
| B4 `10b44839d0aa33f83b6517552ab8a6b7ed06a3fa` | 12 module ＋ knowledge 5 file |
| B5 `8322cb1db6a991191500863afc05b66168e9a747` | 8 module |
| B6 `7a8f8a473e6668a5cc782930dedf262818525b08` | 6 module ＋ monitoring rules |
| B7 `785837fc387178d1f963f4b012a03fbe950acedf` | 12 module |

- anchor は一本の祖先鎖。各期間の差分は宣言した新規 file の追加だけ（計 62 file・変更 0・削除 0）。
- Phase 6 の 3 名前空間の外（src の他の package・`knowledge/compass_dna`・config・workflow・scripts・Pages・data・`main.py`・
  依存定義）は Phase 5 closeout 以降変わっていない。B7 anchor 以降も runtime の差分なし。
- 各 gate の remediation（B5-R1・B6D-R1・B6R1）はその gate の凍結の前に入っている（凍結後の runtime 変更は無い）。

### 19.2 後の gate が前の gate の test に加えた変更（test だけ・runtime に効かない）

| gate | 変更した既存 test | 内容 |
|---|---|---|
| B1 | `test_theme_import_boundary.py` | `theme_intelligence` だけが Foundation の read-only surface を import できる例外を登録 |
| B2〜B7 | `test_theme_intelligence_import_boundary.py` | 新 module の登録と各層の import / token 境界の追加（緩めない） |
| B6 | `test_theme_relation_rerun.py`・`test_theme_taxonomy_entity_boundary.py` | package の module 数の固定を B5 面だけに限定、knowledge の ruleset 名に monitoring rules を許可 |
| B7 | B6 の pin test 4 file | 新規追加の `llm_*.py` だけを B6 pin の対象外にする述語（`theme_freeze_pins.py`）の導入。B7 の anchor ごとの byte pin が改変を検出（B7G M14） |

### 19.3 test と全体結果

| 層 | test file（導入した gate） | 現在の件数（本監査の回帰） |
|---|---|---|
| Foundation | model・store・store_corruption・store_operations・resolver・resolver_facets・identity・evidence・governance_model・foundation_e2e / failures / remediation / replay・import_boundary | §19.4 |
| B1〜B7 | change／lifecycle／proposal・dedup／taxonomy・entity・discovery 群・evidence_bridge／relation 群／monitoring 群／llm 群 | §19.4 |

記録された closure 時の全体結果: Foundation（A4d.1）1590、B1 1640、B3 1723、B4 2031、B5 2500、B6（B6R1-RERUN）3227 passed /
2 skipped、B7 3926 passed / 2 skipped（B2 と B6 closeout の全体件数は記録なし）。mutation と敵対的検証: B6E / B6E-RERUN / B6R1-RERUN、
B5D / B5D-RERUN、B4D、B7D〜B7G（B7 closeout §17）。**リポジトリの健全性の最終値は §19.4 の最新の全体結果**。

### 19.4 最終回帰（本監査）

指示 §24 の順:

| # | 対象 | 結果 |
|---|---|---|
| 1 | Foundation | 260 passed |
| 2 | B1 | 43 passed |
| 3 | B2 | 40 passed |
| 4 | B3 | 41 passed |
| 5 | B4 | 308 passed |
| 6 | B5 | 467 passed |
| 7 | B6 | 727 passed, 2 skipped |
| 8 | B7 | 693 passed |
| 9 | 層横断 / guard / 凍結 pin（完了 test・B7 closeout・import 境界・B6 / B5 の pin・production bundle を含む） | 652 passed, 2 skipped |
| 10 | theme intelligence 一式 | 2617 passed, 2 skipped |
| 11 | **全体** | **3947 passed, 2 skipped**（監査前の 3926 passed / 2 skipped ＋ 本監査の 21。回帰なし） |

層の件数の和（1〜8 ＝ 2579）＋ import 境界 guard（17）＋ 完了 test（21）＝ 2617（10 と一致。重複して数えていない）。

## 20. 実データの状態

| 区分 | 状態 |
|---|---|
| Phase 6 の検証 | **すべて合成**（Foundation の fixture world、B4D の合成 corpus 35 件、B5D、B6E、B7G）。実世界の precision / recall は主張しない（B4 §9、B5 §7） |
| 前の phase から引き継いだ実データ / Windows 検証 | Phase 3.x の実データ検証（J-Quants の live 検証・Compass corpus の局所 PDF pilot・Phase 3.9.4 の Windows 検証など）と、A0.5 が触れる過去の `formal_review` の Windows 実データ検証は、それぞれの phase の対象を検証したもので、**Theme authority や Phase 6 の precision / recall の証拠ではない** |
| 実 Theme authority の shadow | 実 Theme authority が存在しないため B6・B7 とも NOT_RUN（harness は準備済み）。凍結契約と矛盾しないため **NON_BLOCKING** |

## 21. Phase 6 の deferred 登録簿（統合）

分類: NON_BLOCKING_DEFERRED ／ MANDATORY_BEFORE_REAL_PROVIDER ／ MANDATORY_BEFORE_AUTHORITY_EXECUTION ／
MANDATORY_BEFORE_PRODUCTION_INTEGRATION ／ CLOSED/OBSOLETE。同じ根の項目は 1 行にまとめ、出所に元の番号を残す。本監査では
いずれも実装しない。

| id | 内容 | 出所 | 分類 |
|---|---|---|---|
| P6-DEF-01 | 受理された Theme 候補の Foundation 実行 gate（plan を信頼せず再導出・再検証。L2 に LLM_PROPOSAL の role を残さない検査を含む） | B3 §1 / §12、MAT #51 | MANDATORY_BEFORE_AUTHORITY_EXECUTION |
| P6-DEF-02 | evidence attachment plan の Foundation 実行 gate | B4 #10、D-B4E-3 / 4 | MANDATORY_BEFORE_AUTHORITY_EXECUTION |
| P6-DEF-03 | CONTRADICTS / INVALIDATES の bridge と実行 | B4 #8・#9、B7-DEF-13 | MANDATORY_BEFORE_AUTHORITY_EXECUTION |
| P6-DEF-04 | relation assertion の実行 gate（RR-3 の再導出 ／ 完全再検証） | B5 実行 gate・RR-3、B7-DEF-17 | MANDATORY_BEFORE_AUTHORITY_EXECUTION |
| P6-DEF-05 | 実行時の対象（root・端点）の実在の再検証（B7F の root lookup は多層防御として任意） | B7-DEF-6・B7-DEF-16 | MANDATORY_BEFORE_AUTHORITY_EXECUTION |
| P6-DEF-06 | B5C store の古い docstring（RR-1。実行 gate の前の単独 patch） | B5 RR-1・§20、B7-DEF-20 | MANDATORY_BEFORE_AUTHORITY_EXECUTION |
| P6-DEF-07 | 実 provider の接続（SDK・network・runtime 注入の資格情報・timeout・rate・費用） | B0 §14、B7-DEF-1 | MANDATORY_BEFORE_REAL_PROVIDER |
| P6-DEF-08 | provider / model の運用方針（retry・backoff・model 変更・raw response の保持） | B7-DEF-15 | MANDATORY_BEFORE_REAL_PROVIDER |
| P6-DEF-09 | 試行ごとに一意な `generated_at` の caller 契約 | B7-DEF-4 | MANDATORY_BEFORE_REAL_PROVIDER |
| P6-DEF-10 | B7E → B7F の正常 orchestration の成文化 | B7-DEF-18 | MANDATORY_BEFORE_REAL_PROVIDER |
| P6-DEF-11 | LLM の知識は PIT ではない（B7 出力を評価・backtest・P5 に使わない方針の強制） | B7-DEF-19 | MANDATORY_BEFORE_REAL_PROVIDER |
| P6-DEF-12 | 実世界での LLM の品質・精度の評価 | B7-DEF-14 | MANDATORY_BEFORE_REAL_PROVIDER |
| P6-DEF-13 | 実 Theme authority と実データ shadow（B6 harness・B7 manifest shadow。いずれも提出・書き込みなし） | B6-DEF-5、B7-DEF-2 | MANDATORY_BEFORE_REAL_PROVIDER（production 統合の前にも必須） |
| P6-DEF-14 | 実データでの discovery / relation の品質測定（precision / recall） | B4 #11、B5 繰越 | MANDATORY_BEFORE_PRODUCTION_INTEGRATION |
| P6-DEF-15 | Phase 6 を読む正式な interface（Phase 7・Compass / Brief への接続は別 gate） | B0 M12・§15 | MANDATORY_BEFORE_PRODUCTION_INTEGRATION |
| P6-DEF-16 | 運用 runner / scheduling / store への自動追記 | B0 §11.2、B4 #15、B3 §14 | MANDATORY_BEFORE_PRODUCTION_INTEGRATION |
| P6-DEF-17 | single writer 契約（複数 writer・lock・B3 と B5C をまたぐ原子性なし） | A3 §28、B7F §10 / §12 | MANDATORY_BEFORE_PRODUCTION_INTEGRATION |
| P6-DEF-18 | 再利用（収束・共同発見）の診断・`append_or_reuse`・co-discovery journal | B5 D3〜D5、B7-DEF-3 | NON_BLOCKING_DEFERRED |
| P6-DEF-19 | 言い換え・準重複の意味照合（曖昧 dedup を authority にしない）・予約済み dedup class（SCOPE / SUBJECT / MECHANISM_VARIANT・PARENT_CHILD） | B3 §10、B7-DEF-11 | NON_BLOCKING_DEFERRED |
| P6-DEF-20 | Foundation の mechanism vocabulary の拡張（FC-1。実データで不足した場合） | B0 FC-1・R4、B4 #6 | NON_BLOCKING_DEFERRED |
| P6-DEF-21 | 文書 evidence の producer（Statement）と入力の拡張（excerpt・Fact.known_at の質） | A2 §22、B0 R6、B4 #12、B7-DEF-25 | NON_BLOCKING_DEFERRED |
| P6-DEF-22 | discovery / taxonomy の将来版（ORIGIN_KEY の MIN_DISTINCT・位置単位の alias・`data center` alias・adapter 診断の集約・構造化 knowledge_versions） | B4 #1〜#4・#16 | NON_BLOCKING_DEFERRED |
| P6-DEF-23 | 関係の語彙・世界時間・merge / split 時の辺の移行（B5-D2・D6・D7）、自動関係 discovery、意味的な出典検証器、`assertion_locus` の記法 | B5 繰越 | NON_BLOCKING_DEFERRED |
| P6-DEF-24 | 関係の出典帰属の制約・RULE と LLM の CONTEXT 候補の id の違い | B7-DEF-8・B7-DEF-9 | NON_BLOCKING_DEFERRED |
| P6-DEF-25 | B3 model への LLM provenance 不変条件（多層防御） | B7-DEF-12（D-B7-12） | NON_BLOCKING_DEFERRED |
| P6-DEF-26 | monitoring の制約（#17 は到達不能・review 状態は PIT でない・B6D の制約 #2〜#6・B6R1-RERUN の観察 1〜4） | B6-DEF-2・4・6、B6R1-RERUN-OBS | NON_BLOCKING_DEFERRED |
| P6-DEF-27 | integrity-before-PIT（壊れた authority はどの cutoff でも止める）を方針として維持 | B6-DEF-3、B7C | NON_BLOCKING_DEFERRED（方針） |
| P6-DEF-28 | 派生 index（SQLite 等）を導入する場合の性質（派生だけ・削除しても結果不変） | MAT #76・#85 | NON_BLOCKING_DEFERRED（導入時の条件） |
| P6-DEF-29 | 会社別 thesis・受益 ranking | MAT #23、B0 §10 | NON_BLOCKING_DEFERRED（Phase 9） |
| P6-DEF-30 | B7 の軽微な項目（journal 記録失敗時の方針・THEME manifest の vocabulary の束縛・consequence 別の支持・`subject_refs`・注釈役割・merge 元 / 先の scope・空の ruleset version・RR-2 の裸の ValueError・B1 の `ENTITY_LINK_CHANGED`・B2 の遷移 API・B4 の plan journal / 文書例） | B7-DEF-7・10・21〜24、B5 RR-2、B1 §12、B2 §9、B4 #7・#17 | NON_BLOCKING_DEFERRED |
| P6-DEF-31 | B2 contract §10 の文言を凍結済みの解釈（REOPENED → ACCEPTED ほか。B3 見出しの B2-D1〜D3）に合わせる・B5C の test 件数の記載差（59 と 75） | B2 §10、B3 見出し、B5 §19 | NON_BLOCKING_DEFERRED（文書の整合） |
| P6-DEF-32 | 閉じた項目: B6-DEF-1（CLOSED）・BLOCKER-1（CLOSED）・A4D-1〜3（修正済み）・FC-2〜5（不要）・RELATION_CANDIDATE（B5C で実装）・LLM_PROPOSAL 予約（B7 で使用）・L3 意味照合（B7）・entity catalog（B4）・B7-DEF-26 / 27・POLICY LOCKED 項目（B4 #5・#13） | 各 gate | CLOSED/OBSOLETE |

## 22. blocker の評価

**blocker なし。**

| 完了条件（指示 §21） | 結果 |
|---|---|
| 当初範囲の intelligence 能力がすべて実装されている | Foundation ＋ B1〜B7 を実装・凍結（§2） |
| authority の境界が凍結されている | §4・§7・§16、import 境界 guard、完了 test（§19.1） |
| blocker が残っていない | A4D-1〜3・BLOCKER-1・B6-DEF-1 はすべて閉じた。B7 は blocker なし |
| 残りの仕事の性質 | real provider の運用化（P6-DEF-07〜13）・提案の実行（01〜06）・production 統合（14〜17）・実データの蓄積 / 評価（13・14）・将来の意味拡張（18〜30）だけ |

remediation を要する runtime の欠陥は見つからなかった（Foundation・B4〜B7 の remediation 不要）。文書の不整合 2 件（§10・
P6-DEF-31）は意味論に影響しない。

## 23. Phase 7 への暫定 handoff

**暫定**（Phase 7 は開始しない）。Phase 7 Narrative は、将来に明示的に承認された interface を通してだけ Phase 6 を読む:

- 読み取りだけ: PIT resolver の結果と派生 view（B1 ChangeSet・B2 lifecycle view・B5 relation view・B6 finding）を caller の
  cutoff で読む。Theme 層は Phase 7 を import しない（B0 §15）。
- 禁止: Theme authority（Foundation・relation・提案・decision・review）への書き込み、人間の governance 判断、Theme 提案の
  黙った昇格（L1 を L2 / L3 として扱う）、生成監査 journal・monitoring finding を evidence として扱うこと、PIT / authority
  の境界の迂回、Production DNA への反映。
- 出力の文（narrative）は Phase 7 の責任で、Phase 6 の authority ではない。interface の名前・形は Phase 7 planning で決める
  （B0 §25 の未決事項）。

## 24. 判定

**P6_THEME_INTELLIGENCE_COMPLETE / READY_FOR_PHASE7_PLANNING**

Phase 7・B8 は開始しない。実 provider の接続・資格情報の要求・Foundation / B5B への提案の実行・RR-3 の実装・HUMAN decision の
作成・P4 / P5 の変更・scheduler / 通知 / 公開出力への接続は行わない。監督レビュー待ち。
