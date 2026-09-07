# Compass First Formal DNA Review 仕様（Phase 3.9.5）

**NOT_AUTOMATIC_APPROVAL / NOT_DNA_PROMOTION / EVIDENCE_PACKET_BOUND / HUMAN_ONE_AT_A_TIME**

Phase 3.9.2 は「engine が何を推奨するか」、Phase 3.9.3 は「今日人間が何を見るべきか」、Phase 3.9.4 は
「推奨がどれだけ持続したか」を答える。Phase 3.9.5 は、それらを **人間が実際に見る証拠 packet** にまとめ、
freshness / 整合性 guard を通したうえで、人間の formal Decision を Phase 3.9.1 に書く層である。

```
APPROVE_RECOMMENDED ≠ APPROVED      REJECT_RECOMMENDED ≠ REJECTED      APPROVED ≠ PROMOTED_TO_DNA
```

自動承認・自動却下・新しい recommendation state・DNA 書き込みはない。実装は `src/intelligence/formal_review/`
（1 機能 = 1 ファイル）、設定は `config.yaml: compass_formal_review`（1.0.0 / digest `cca7b43627b9a355`）。

## 1. review unit と population

- 原子的 formal review unit = **単一 pattern_id**（Phase 3.9.1 Decision が pattern 単位）。group 単位の Decision は作らない。
- primary candidate = 現在の recommendation が APPROVE_RECOMMENDED / REJECT_RECOMMENDED で、Decision head が
  NONE / KEEP_REVIEWING / REOPENED_FOR_REVIEW。head が APPROVED / REJECTED / SUPERSEDED / RETIRED は decided。
- REJECTED は material change が検出されたときだけ REOPEN_ELIGIBLE section に載る。NOT_READY は除外。
- context = candidate の sibling group member（recommendation を問わず）。表示のみで、queue から決められない。
- 件数は実行時に必ず動的に決まる（実装に固定値なし）。

## 2. sibling / group（v1 凍結）

関係 = Phase 3.9.2 contradiction index と同じ key: **EVIDENCE_OUTLOOK** の `evidence` categories + outlook `target`。
STATE_OUTLOOK / THEME_OUTLOOK には広げない。member ごとに direction / recommendation / decision state / DNA
classification / eligible_support / relationship（OPPOSITE・SAME・NON_COMMITTED）を示し、
`group_state_digest`（member の pattern_id・direction・recommendation・decision_state・material_digest）で束縛する。

## 3. packet

`<data_root>/compass_formal_review/packets/<pattern_id>.json`。block: identity / recommendation / axes /
reference（`NON_DECISIONAL_REFERENCE_ONLY`）/ consistency / dna / replay / shadow_history / decision / group /
freshness / warnings。原文・ファイル名・path は入らない（Phase 3.9.3 forbidden key を再利用して scan）。

### 3.1 二つの digest

| digest | 意味 | 用途 |
|---|---|---|
| `material_digest` | Phase 3.9.3 の凍結 semantics（recommendation・axis state・applicability・eligible_support・2D cells・contradiction block・lifecycle・policy digest 2 種） | 機械側の material change 追跡、REOPEN 適格、「何が変わったか」 |
| `packet_evidence_digest` | 人間が見た証拠そのもの（identity・recommendation 規則・6 軸・consistency・dna・replay run digest と指標・shadow 現在状態と履歴 digest・decision head・group state・全 policy digest） | formal Decision 書き込み前の freshness anchor |

`packet_evidence_digest` に含めないもの: 生成時刻、`corpus_size` / `corpus_milestone` / `corpus_eligible_at_build` /
`evidence_age_eligible_docs`（corpus 増加だけで変わる）、`evaluation_id` / `inputs_digest`（corpus_size を含むため
informational）、replay_run_id（run_digest で束縛）、warnings（証拠から派生）。
`packet_id = frp_ + sha256(pattern_id | packet_evidence_digest | schema | formal review digest)[:16]`（決定的）。

### 3.2 corpus-only growth

eligible 139 → 140 で証拠 field が不変なら packet は有効なまま。Decision metadata に
`corpus_eligible_at_packet` と `corpus_eligible_at_write` を記録する。

## 4. ordering（凍結・section は交互に混ぜない）

1. REJECT_RECOMMENDED: first_reject_position ASC → reject_persistence_ratio DESC → eligible_support DESC → pattern_id
2. APPROVE_RECOMMENDED: stability rank（STABLE, MOSTLY_STABLE, RECENT_TRANSITION, INSUFFICIENT_HISTORY, OSCILLATING）
   → first_approve_position ASC → eligible_support DESC → span_days DESC → pattern_id
3. REOPEN_ELIGIBLE: first_reject_position ASC → pattern_id

## 5. warnings（表示と並びのみ・新 gate なし）

W_SIBLING_OPPOSITE_APPROVED（C1 が block）/ W_SIBLING_OPPOSITE_APPROVE_RECOMMENDED（C3 acknowledgement）/
W_REPLAY_EVIDENCE_MISSING / W_REPLAY_EVIDENCE_NOT_CURRENT / W_OSCILLATING / W_INSUFFICIENT_HISTORY /
W_RECENT_TRANSITION / W_MOSTLY_STABLE_SHOW_HISTORY / W_REPLAY_EVIDENCE_AGE（current − captured ≥ 5）/
W_DNA_CONFLICT / W_CONTRADICTION_ACTIVE / W_APPEARED_ONLY_AFTER_100 / W_SHADOW_DISAGREEMENT_HISTORY。
RECENT_TRANSITION の APPROVE candidate は自動では block しない。

## 6. formal outcome（既存 Decision state のみ）

| head | recommendation | 許される action |
|---|---|---|
| NONE / KEEP_REVIEWING / REOPENED_FOR_REVIEW | APPROVE_RECOMMENDED | APPROVED, KEEP_REVIEWING |
| 同上 | REJECT_RECOMMENDED | REJECTED, KEEP_REVIEWING |
| APPROVED | — | SUPERSEDED（replacement_pattern_id 必須）, RETIRED |
| REJECTED | — | REOPENED_FOR_REVIEW（REOPEN_ELIGIBLE のときだけ） |
| SUPERSEDED / RETIRED | — | terminal |

symmetry は凍結: APPROVE_RECOMMENDED → REJECTED、REJECT_RECOMMENDED → APPROVED は v1 で禁止。人間が推奨に
同意しないときは KEEP_REVIEWING + reason。重複・重なりは KEEP_REVIEWING + `disposition=DUPLICATE_OR_OVERLAPPING`
+ `related_pattern_id`（新 state なし）。

## 7. reason

Phase 3.9.1 の HUMAN actor・非空 reason は不変。追加の最小: APPROVED 20 / REJECTED 20 / KEEP_REVIEWING 10 /
REOPENED_FOR_REVIEW 20 / SUPERSEDED 20 / RETIRED 20 文字。推奨ラベルだけの reason は拒否。REJECTED は packet に
active な contradiction indicator が必要。KEEP_REVIEWING は任意の `reason_category`
（MORE_DOCUMENTS / MORE_REGIMES / LONGER_SPAN / BETTER_QUALITY）。

## 8. guard（書き込み前の検査順・fail closed）

1 Decision store 有効 → 2 evaluation store 有効 → 3 candidate 存在（queue に載っている）→ 4 packet 帰属 →
5 recommendation 一致 → 6 symmetry → 7 material_digest 不変 → 8 packet_evidence_digest 不変 →
9 全 policy digest 一致 → 10 formal gate（evaluation record と live corpus）→ 11 lifecycle → 12 head 不変 →
13 transition / reopen 適格 → 14 replay evidence（APPROVED / REJECTED は current-compatible 必須）→
15 sibling C1（反対方向 sibling が APPROVED なら block・override なし）/ C3（未決 APPROVE_RECOMMENDED は
`--acknowledge-sibling` 必須・metadata に記録）→ 16 reopen → 17 HUMAN actor → 18 reason → 19 metadata 制約 →
20 forbidden key → 21 `DecisionService.validate` → 22 `DecisionService.decide`。

replay evidence の current-compatible = replay run の policy digest 4 種が現在と一致、pattern が replay に存在、
replay の current_recommendation が現在の recommendation と一致、captured ≤ current eligible。

## 9. Decision 書き込み経路と metadata

```
FormalReviewGuard → DecisionRequest → DecisionService.validate → DecisionService.decide → DecisionStore.append
```
guard も CLI も DecisionStore に直接触れない。`promotion_status` は常に NOT_PROMOTED（schema 1.0.0 が許す唯一の値）。
`idempotency_key = packet_id` なので、同じ fresh packet に対する同じ判断の retry は重複 row を作らない
（`DUPLICATE_OF_HEAD_IDEMPOTENT`）。

metadata（20 key / 500 chars 制約）: packet_id, packet_evidence_digest, material_digest, recommendation,
policy_digests（`layer:digest;...` 6 層を 1 key に束ねる）, replay_run_id, replay_run_digest, group_state_digest,
stability_class, formal_review_schema_version, corpus_eligible_at_packet, corpus_eligible_at_write,
head_decision_id_at_packet, metadata_payload_digest（個別 digest を含む全 binding の canonical digest）、
必要時のみ acknowledged_sibling / disposition / related_pattern_id / replacement_pattern_id / reason_category。
tradeoff: policy digest 6 個を個別 key にすると 20 key を超えるため 1 key に束ね、個別値は payload digest で束縛する。

## 10. reopen

REJECTED は `現在の material_digest ≠ REJECTED decision metadata の material_digest` のときだけ REOPEN_ELIGIBLE。
corpus 増加のみ・score のみ・経過時間のみでは変わらない。packet binding の無い REJECTED は検証不能（非適格）。
system は表示するだけで、REOPENED_FOR_REVIEW を書くのは人間だけ（`reopen-check` は read-only）。

## 11. DNA relation

表示は既存 classification のまま: EXPLAINED_BY_EXISTING_RULE / PARTIALLY_EXPLAINED / NEW_PATTERN_CANDIDATE /
CONFLICTS_WITH_EXISTING_RULE / NOT_COMPARABLE（best_rule_id・direction_relation・conflict rule ids 付き）。
APPROVED は DNA を編集しない。CONFLICTS は symmetry により v1 では APPROVED になれない。promotion は別 gate。

## 12. storage / CLI / metrics

derived: `compass_formal_review/{build_manifest.json, queue.json, summary.json, packets/}`（atomic・rebuildable）。
formal truth は `compass_decisions/decisions.jsonl` のみ。
CLI: `build` / `list` / `show <pattern_id>` / `decide <pattern_id> --packet --action --reason --actor
[--acknowledge-sibling] [--related-pattern] [--replacement-pattern] [--reason-category] [--disposition] [--dry-run]` /
`status` / `reopen-check` / `validate-policy`。batch command なし、1 invocation = 1 pattern。
`--dry-run` は guard と `DecisionService.validate` まで実行し何も書かない（Windows packet validation で使う）。
metrics は運用値のみ（candidates / by recommendation / context / pending / reviewed / outcomes / blocked / acknowledged /
reopen eligible / median age / replay age）。accuracy・precision・hit rate・forecast 系はない。

## 12.1 real-data packet validation（`validation.py`）

`python -m src.intelligence.formal_review.validation --require-commit <sha> --expect-<layer> <digest> ...` は
Windows 実機の 1 操作用 driver。HEAD / 6 層 policy / baseline / build / determinism（live 再 build と固定入力
2 回組み立て）/ queue 要約 / replay 互換 / freshness / sibling 集計 / **全 primary candidate の dry-run**
（recommendation に従う action、C3 acknowledgement を packet から導出）/ symmetry / reopen-check / metadata /
safety を `::P395_*::` marker で出力し、材料となる失敗で `::P395_FAIL::` と非 0 exit。formal Decision は書かない。
console には人間の Shadow Review reason 本文・原文・ファイル名・path を出さない。

## 13. Phase 3.9.5 の閉じ方

実装完了 ≠ Phase close。実装 → local QA → 監督者実装レビュー → Windows real-data packet build → 全 candidate の
`decide --dry-run` → 監督者 process review → 明示的 HUMAN-DECISION GO → first real human formal review → 最終 audit
→ CLOSED。実装・packet validation の間に real Decision は書かない。

## 14. Windows real-data validation record（監査証跡・履歴事実）

以下は Phase 3.9.5 の human review gate を READY と判定した時点の実機検証記録である。**この節は履歴の
事実であり、semantics・policy digest・packet schema・guard 挙動のいずれも定義しない**（それらは §1〜§13）。

| 項目 | 値 |
|---|---|
| 検証日時（UTC） | 2026-09-05T18:50Z（build）／ 監督者判定 2026-09-06 |
| 検証 commit | `b73af512937421b01b1e91bdd809d46216a555bc` |
| corpus | documents 141 / eligible 139 / CORPUS_100 到達 |
| primary candidate | 16（APPROVE_RECOMMENDED 10 / REJECT_RECOMMENDED 6） |
| REOPEN_ELIGIBLE | 0 |
| context pattern | 8（decided 0・NOT_READY 除外 10） |
| 選択された replay run | `crp_2530396a5a3b8fb7` |
| replay run digest | `74d5b037498fc0de` |
| replay policy | 1.1.0 / `197db7c73eb0db77`（captured eligible 139・evidence age 0） |
| replay 互換性 | 16 / 16 |
| packet freshness | 16 / 16 fresh（changed block 0） |
| formal dry-run | 16 / 16 DRY_RUN_PASS |
| **書き込まれた formal Decision** | **0** |
| Shadow Review event 変更 | 0 |
| DNA 変更 | 0（blob identity 一致） |
| PDF 変更 | 0（inventory 一致・open せず） |
| research / evaluation / shadow derived store 変更 | 0 |
| determinism | live rebuild PASS / fixed inputs PASS |
| formal review test（Windows） | 75 passed |
| full pytest（Windows） | 2062 passed / 1 skipped |
| 唯一の skip | Linux 専用 tank shard が無い環境での明示 `skipif`。Phase 3.9.5 とは無関係 |
| 検証時点の human review | **未開始**（first human formal review session はこの記録の後） |

補足（いずれも履歴事実）:

- 当初の実機 run では全 16 candidate が `POLICY_DIGEST_MISMATCH:replay` を返した。原因は、選択された
  replay run が replay policy 1.0.0 期のものだったこと（evidence の内容ではなく policy version 束縛）。
  現行 policy 1.1.0 で **既定 mode（MILESTONE_AND_TRANSITION / CHRONOLOGICAL）を 1 回**実行しただけで
  16 / 16 が互換になった。FULL_REPLAY の再実行は不要だった。
- その既定 run は、先行 FULL_REPLAY と同一の formal-review 関連値（APPROVE first position 78 / 91 / 93 / 96 /
  117 / 125 / 128 / 129 / 136 / 136、REJECT first position 33 / 68 / 82 / 82 / 114 / 125、persistence 1.0、
  reversal 0、STABLE 5 / RECENT_TRANSITION 5）を再現した。
- sibling: group with multiple members 21 / opposite sibling を持つ candidate 1 / C1 block 0 / C3 要求 0。
  唯一 opposite sibling を持つのは REJECT candidate であり、C1・C3 は APPROVED にのみ適用されるため、
  この母集団では実データ上いずれも発火していない（synthetic test でのみ実証済み）。

## 15. First human formal review session（手順は `COMPASS_FIRST_FORMAL_REVIEW_SESSION.md`）

`session.py` は packet の事実だけを人間向けの 10 節 brief・事実文・設問・2 段階 command へ変換する
読み取り専用 module（narrative 生成なし・助言表現は語彙として禁止し test で検査・人間の Shadow Review
reason 本文は提示に載せない）。CLI は `session`（凍結順の全 step）と `brief <pattern_id>`（1 件）を提供する。

real write は 2 段階に固定する。stage 1 は `decide … --dry-run`（guard 全 22 段と
`DecisionService.validate` を実行し何も書かない）、stage 2 は同じ action を
`--confirm "CONFIRM <STATE> <pattern_id>"` 付きで再実行する。token が無い / 一致しない real write は
guard へ届く前に拒否され（exit 3）、既定 action は存在しない。batch command は無く、1 invocation = 1 pattern。

## 16. candidate #1 pilot（`pilot.py`）

`python -m src.intelligence.formal_review.pilot --require-commit <sha> --expect-<layer> <digest> [--historical-head <id>]`
は、最初の human review を **queue rank 1 の 1 件だけ**で試すための読み取り専用 driver。HEAD / 6 層 policy /
安全 baseline / fresh build（replay 互換の件数まで）/ **fresh build から rank 1 を自力で特定**（`--historical-head`
は `QUEUE_HEAD_CHANGED` の比較にだけ使い、選択には使わない）/ freshness / 10 節 brief・事実文・設問 /
機械整合 action の dry-run / KEEP_REVIEWING の dry-run / 人間判断の保留表示 / stage 1・stage 2 command /
変更なし証明を `::P395C_*::` marker で出力する。

この driver は `dry_run=True` 以外で `decide` を呼ばず（test が AST で検査）、`--confirm` の経路も持たないため
real Decision を書けない。candidate #2 以降は表示しない。`REPLAY_EVIDENCE_REQUIRED` / stale / policy 不一致は
pilot を BLOCKED にし、guard は弱めない。`SIBLING_CONFLICT_BLOCKED` と `SIBLING_ACKNOWLEDGEMENT_REQUIRED` は
人間判断が要るだけの正当な結果として記録し、pilot は継続する。


## 17. candidate #1 execution wrapper（`pilot_execute.py`）

`python -X utf8 -m src.intelligence.formal_review.pilot_execute --require-commit <sha> --expect-<layer> <digest>
 --pattern <id> --action <action> --actor <id> --confirm "<token>"` は、監督者が凍結した **candidate #1 の
human decision 1 件だけ**を実行する executor。汎用の batch executor ではなく、凍結値以外の pattern / action /
actor / reason / confirmation token をすべて `stage=ARGUMENTS` で拒否する。

pilot.py の読み取り専用 section（HEAD / policy / baseline / build / candidate / freshness）を composition で
再利用し、順序は `ARGUMENTS → HEAD → POLICY → BASELINE（Decision 0 行）→ FRESH_BUILD → EVIDENCE_RECHECK →
STAGE1_DRY_RUN → STAGE2_CONFIRM → STAGE2_WRITE → DECISION_AUDIT → SAFETY → PILOT_DECISION_OK → END`。
出力は `::P395D_*::` marker、失敗は `::P395D_FAIL:: stage= reason=` と非 0 exit
（0 ok / 3 FormalReviewError / 4 実行失敗 / 5 想定外）。

EVIDENCE_RECHECK は queue rank 1 が凍結 id であること、recommendation が凍結値であること、packet freshness、
replay 互換、formal gate 到達、Decision head が NONE、および reject 根拠（`document_contradiction` /
`document_contradiction_repeated` / `contradiction_active` / `reject_driver` /
`contradiction_recovery_positions` 空 / `reversal_count` 0 / `REJECTED` が allowed action）を要求する。
根拠が変わっていれば `HUMAN_REVIEW_EVIDENCE_CHANGED_*` で停止する。

production write は生涯 1 回だけ試行する（2 回目は `SECOND_WRITE_ATTEMPT_REFUSED`）。例外時は**自動再試行せず**、
DecisionStore を読み取り専用で確認し、packet_id まで一致する row が 1 件あれば
`POSSIBLE_WRITE_SUCCEEDED_RESPONSE_FAILED` として既存 row を監査し、無ければ `WRITE_FAILED_NO_ROW` で停止する。
DECISION_AUDIT は 1 行であること・16 項目の束縛（state / pattern / actor / actor_type / review_mode /
promotion_status / sequence / chain root / record hash 再計算 / packet_id / packet_evidence_digest /
material_digest / 6 層 policy digest / replay 束縛 / 人間 reason の完全一致 / idempotency key）を検査する。
書き込み経路は既存のまま（`FormalReviewGuard → DecisionRequest → DecisionService.validate → decide →
DecisionStore.append`）であり、この module は policy・packet schema・guard semantics を一切変更しない。
