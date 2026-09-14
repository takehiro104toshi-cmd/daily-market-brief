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

## 18. Candidate #1 real-write audit record（監査証跡・履歴事実）

本節は **Phase 3.9.5 で初めて書かれた実 human formal Decision の記録**である。履歴の事実であり、
semantics・policy digest・packet schema・guard 挙動のいずれも定義しない（それらは §1〜§13）。

| 項目 | 値 |
|---|---|
| 実行日（UTC） | 2026-09-07 |
| 実行 commit | `f48d934`（`pilot_execute.py` 導入時点） |
| 実行 driver | `src/intelligence/formal_review/pilot_execute.py`（凍結 1 候補・real write 1 回） |
| pattern_id | `cpt_4d2f4477a946c17e` |
| pattern_type | EVIDENCE_WHY |
| machine recommendation | REJECT_RECOMMENDED |
| **human formal decision** | **REJECTED** |
| decision_id | `cdc_884ab4cafff2dbf3` |
| sequence | 1 |
| actor_type / review_mode | HUMAN / FORMAL |
| promotion_status | NOT_PROMOTED |
| packet_id | `frp_52ac7d90c182f3de` |
| packet_evidence_digest | `4b1bc098c84cd313` |
| material_digest | `b7025083c160de43` |
| replay run id / digest | `crp_2530396a5a3b8fb7` / `74d5b037498fc0de` |
| record hash | `ed8a0c6497c6e1e82c7e28670c5c75cb33cbb1c0895fb9491858652b9d0006c0` |
| Decision hash chain | VALID |
| Decision rows | 0 → 1 |
| 束縛監査 | 16 項目すべて OK（state / pattern / actor / actor_type / review_mode / promotion / sequence / chain root / record hash 再計算 / packet_id / packet_evidence_digest / material_digest / 6 層 policy digest / replay 束縛 / 人間 reason 完全一致 / idempotency key） |
| Shadow Review event 変更 | 0 |
| DNA 変更 | 0（blob identity 一致） |
| PDF 変更 | 0（inventory 一致・open せず） |
| derived store 変更 | なし（`derived_changed=[]`） |
| tracked worktree | 不変 |
| 処理した candidate | 1 件のみ（candidate #2 は未処理） |
| policy digest | 6 層とも凍結値のまま（`decision 0c54ec01e2a251d9` / `evaluation 1a8443098f64d679` / `recommendation 0a979d8421a01d08` / `shadow_review e6f5094cacef6fec` / `replay 197db7c73eb0db77` / `formal_review cca7b43627b9a355`） |
| Phase 状態 | この書き込み後も **Phase 3.9.5 は OPEN**（candidate #1 pilot のみ CLOSED） |

human formal decision reason（formal Decision の理由本文。本節にのみ記録し、他所へ複製しない）:

> Supporting evidence remains directionally contradictory across a long observation span; the contradiction is
> repeated and active, with no recovery or reversal in replay.

補足（履歴事実）:

- 実行 envelope は当初 7,799 文字の inline `python -c` として準備されたが、cmd.exe の行長上限に近すぎたため
  監督者判断で専用 module へ移設し、`git pull --ff-only` を用いる 742 文字の 1 操作に置き換えた（§17）。
  Decision semantics は移設前後で同一。
- 書き込み経路は既存のまま（`FormalReviewGuard → DecisionRequest → DecisionService.validate → decide →
  DecisionStore.append`）。この Decision により `cpt_4d2f4477a946c17e` は primary queue から外れ、
  queue の decided context に `REJECTED` として現れる（§19 の QUEUE_EXCLUSION がこれを検査する）。

## 19. next candidate read-only review（`next_candidate.py`）

`python -X utf8 -m src.intelligence.formal_review.next_candidate --require-commit <sha> --expect-<layer> <digest>
 [--expect-decided <pattern_id>] [--reaudit-pattern / --reaudit-decision / --reaudit-state / --reaudit-record-hash]`
は、**Decision が 1 件以上ある状態から次の 1 件を提示する汎用の読み取り専用 driver**。candidate 固有の値を
持たず、書き込み経路も持たない（`decide` を直接呼ばず、confirmation の口も無い。AST test で静的に検査）。

pilot.py の section を composition で再利用し、本 module 固有の検査は 2 つ:

- **DECISION_CHAIN**: Decision row ≥ 1 / sequence 連番 / head sequence 一致 / 各行の `record_hash` 再計算一致と
  chain 連結 / 全行 HUMAN・FORMAL・NOT_PROMOTED・packet 束縛あり。任意で既存 1 行の再監査
  （decision_id・decision_type・record hash・packet 束縛・material digest・6 層 policy・replay 束縛・reason 在席）。
- **QUEUE_EXCLUSION**: 既決 pattern が primary queue（REJECT / APPROVE / REOPEN section）に残っていないこと。
  残っていれば `DECIDED_PATTERN_STILL_IN_PRIMARY_QUEUE` で fail closed し、次候補の提示へ進まない。
  `--expect-decided` を渡した pattern は queue の decided context にも在席していることを要求する。

その後は fresh build から現在の queue rank 1 を自力で特定して 1 件だけ提示し（historical な次候補を hardcode
しない）、10 節 brief・事実文・設問 → 機械整合 action の dry-run → KEEP_REVIEWING の dry-run → 人間判断は
PENDING → stage 1 / stage 2 command → 変更なし証明、を `::P395N_*::` marker で出力する（再利用した pilot
section は `::P395C_*::` も出す）。失敗は `::P395N_FAIL:: stage= reason=`、exit 0 / 3 / 4 / 5。

## 20. generic formal execution session（`execute.py`）

`python -X utf8 -m src.intelligence.formal_review.execute --require-commit <sha> --expect-<layer> <digest>
 --pattern <id> --action <approve|reject|keep-reviewing> --actor <id> --reason "<human reason>"
 --confirm "CONFIRM <STATE> <id>" --expect-rows-before <N> --expect-current-state <STATE|NONE>
 [--expect-machine-recommendation <REC>] [--require-queue-rank 1] [--expect-group-state-digest <digest>]
 [--expect-group-material-digest <digest>] [--expect-fact key=value ...] [--acknowledge-sibling <id> ...]`

Phase 3.9.5 の残りの formal Decision はすべてこの **1 本**で実行する。candidate 固有の凍結値は持たない
（test が `cpt_` / `frp_` / `cdc_` / 人間 reason / actor の literal 不在を静的に検査）。candidate #1 専用の
`pilot_execute.py`（§17）は最初の production write の監査履歴として残すが、以後は使わない。

### 20.1 orchestration only

Decision state model・遷移・population・recommendation・packet schema・policy・replay・group の semantics は
一切変更しない。本 module は「呼び出し側が束縛したレビュー時点の期待状態」を検査してから、既存の
authoritative write path（`FormalReviewGuard → DecisionRequest → DecisionService.validate → decide →
DecisionStore.append`）をそのまま使うだけである。`FormalDecisionRequest` の生成は 1 箇所、`decide` の呼び出しは
dry-run 1 箇所と real write 1 箇所のみ（AST test で固定）。batch / 複数 pattern の入口は持たない。

### 20.2 順序と marker

`ARGUMENTS → HEAD → POLICY → DECISION_CHAIN → BASELINE → FRESH_BUILD → TARGET → PACKET_FRESHNESS →
EXPECTED_FACTS → GROUP_CONTEXT → STAGE1_DRY_RUN → STAGE2_CONFIRM → STAGE2_WRITE → DECISION_AUDIT → SAFETY → END`
を `::P395X_*::` marker で出力する。失敗は `::P395X_FAIL:: stage= reason=` と非 0 exit（0 / 3 / 4 / 5）。
人間 reason の本文は出力せず、文字数と digest だけを出す。

### 20.3 caller-bound expectations（汎用のため hardcode しない）

- `--expect-rows-before N`: 書き込み直前の Decision 行数。**generic な不変条件として 1 や 0 を固定しない。**
- `--expect-current-state`: レビュー時点の formal head（`NONE` / `KEEP_REVIEWING` / `REOPENED_FOR_REVIEW` など）。
  正当な再レビューでは `NONE` 以外になるため、呼び出し側が必ず束縛する。
- `--expect-machine-recommendation` / `--require-queue-rank`: rank 1 以外が来たら `CANDIDATE_HEAD_CHANGED` で停止し、
  新しい pattern を自動で代替しない。
- `--expect-fact key=value`: 凍結 allowlist（`document_contradiction` / `document_contradiction_repeated` /
  `narrow_sibling_contradiction` / `narrow_sibling_repeated` / `contradiction_active` / `direction_class` /
  `dna_conflict_count` / `reject_driver` / `reversal_count` / `recovery_count` / `opposite_sibling_count` /
  `sibling_member_count` / `eligible_support` / `formal_review_gate_reached` / `replay_current_compatible` /
  `stability_class`）の型付き比較のみ。任意の object path も式評価も受け付けない。
  不一致は `HUMAN_REVIEW_EVIDENCE_CHANGED:<keys>` で停止する。

### 20.4 group context

`--expect-group-state-digest` が一致すれば `GROUP_CONTEXT_UNCHANGED`。異なる場合は**黙って無視しない**:
material view（`sibling_group_key` / `own_direction` / member id / opposite member id / member ごとの formal
decision state / C1 / C3）の digest を `--expect-group-material-digest` と比較し、一致すれば
`EQUIVALENT_REPRESENTATION_REGENERATED` として継続、不一致または baseline 未指定なら
`HUMAN_REVIEW_EVIDENCE_CHANGED_GROUP_CONTEXT` で停止して人間の再レビューを要求する。

### 20.5 same-packet / one-write / no-retry

Stage 1 で解決した packet identity を保持し、Stage 1 と Stage 2 の間で rebuild しない。real write は
`write_attempts == 0` を検査してから 1 回だけ試み、2 回目は `SECOND_WRITE_ATTEMPT_REFUSED`。例外時は
**自動再試行せず** DecisionStore を読み取り専用で確認し、pattern / decision_type / packet_id が一致する
新規行が 1 件なら `POSSIBLE_WRITE_SUCCEEDED_RESPONSE_FAILED`（その行を監査）、0 件なら `WRITE_FAILED_NO_ROW`、
複数なら `AMBIGUOUS_WRITE_RESULT` で停止する。

### 20.6 post-write audit（汎用）

行数が `expect_rows_before + 1` ちょうどで、既存行が 1 行も変化していないこと。新規行について pattern /
decision_type / actor / actor_type HUMAN / review_mode FORMAL / promotion_status NOT_PROMOTED /
`sequence == 直前の global sequence + 1` / `previous_record_hash == 直前 global 行の record_hash` /
`previous_decision_id`・`previous_state == その pattern の直前 head`（空だと仮定しない）/ reason 完全一致 /
packet_id・packet_evidence_digest・material_digest・group_state_digest 一致 / 6 層 policy 束縛 / replay 束縛 /
idempotency key = packet / record hash 再計算 / chain VALID。

### 20.7 KEEP_REVIEWING duplicate hazard（既知の性質）

`KEEP_REVIEWING → KEEP_REVIEWING` は凍結遷移表で**許可されている**。したがって packet 束縛の idempotency だけでは、
rebuild 後の新しい packet による 2 本目の KEEP_REVIEWING 行を防げない。本 module は Decision semantics を変えて
これを解こうとはしない。代わりに **呼び出し側が束縛した `--expect-rows-before` と `--expect-current-state` が
書き込み直前に一致すること**を要求することで、事故による再走を write の前に止める
（1 回目成功後は行数が +1 になり head も変わるため、同じ引数の再走は必ず失敗する）。

### 20.8 queue progression は本変更では未解決

KEEP_REVIEWING の head が primary queue に残り、順序 key が decision state に依存しないため同じ pattern が
再び rank 1 になり得る。これは実在の設計・運用課題だが、**本変更では解決しない**（`population.py` 不変・
cooldown なし・抑制なし・順序変更なし・rank 1 の自動スキップなし・reviewed packet digest による抑制なし）。
既知の挙動として記録するにとどめ、candidate #2 の書き込みと監査の後に別途審議する。

## 21. Candidate #2 real-write audit record（監査証跡・履歴事実）

本節は **Phase 3.9.5 で 2 番目に書かれた実 human formal Decision の記録**であり、§18（candidate #1）とは
別の事例として記録する。履歴の事実であり、semantics・policy digest・packet schema・guard 挙動のいずれも
定義しない（それらは §1〜§13、実行 envelope は §20）。

| 項目 | 値 |
|---|---|
| 実行日時（UTC） | 2026-09-12T01:18:10Z |
| 実行 commit | `8a29bed`（`execute.py` 導入時点） |
| 実行 driver | `src/intelligence/formal_review/execute.py`（汎用 execution session・§20） |
| pattern_id | `cpt_8c96e2070cd4c702` |
| pattern_type / lifecycle | EVIDENCE_OUTLOOK / STRONG_PATTERN_CANDIDATE |
| fresh queue rank | 1（REJECT_RECOMMENDED section） |
| **machine recommendation** | **REJECT_RECOMMENDED** |
| **human formal decision** | **KEEP_REVIEWING**（意図的な不同意・凍結 symmetry の範囲内） |
| decision_id | `cdc_0a420b63cc1257ed` |
| sequence | 2 |
| previous_record_hash | `ed8a0c64…0006c0`（= candidate #1 の record hash。global append-only chain を実測確認） |
| previous_decision_id / previous_state | 空 / 空（この pattern では初回の Decision） |
| actor_type / review_mode | HUMAN / FORMAL |
| promotion_status | NOT_PROMOTED |
| packet_id | `frp_b118d3272d4382c1`（read-only review 時と同一・fresh build で再解決） |
| packet_evidence_digest | `387e2252004dbac9` |
| material_digest | `8f410ca4e7da1e58` |
| group_state_digest | `037f307fe6fd2efb`（`GROUP_CONTEXT_UNCHANGED`） |
| group material digest（§20.4 の material view） | `e94e576ba2b8f005` |
| replay run id / digest | `crp_2530396a5a3b8fb7` / `74d5b037498fc0de`（captured eligible 139・evidence age 0） |
| record hash | `179146cd9e368ecc7b2b8e55ee14ab66f2b03da0003814ebc1aef66dca5843ca` |
| Decision hash chain | VALID |
| Decision rows | 1 → 2 |
| 束縛監査 | 19 項目すべて OK（pattern / decision_type / actor / actor_type / review_mode / promotion / sequence 連番 / global tail / pattern head の previous_decision_id・previous_state / record hash 再計算 / reason 完全一致 / packet_id / packet_evidence_digest / material_digest / group_state_digest / 6 層 policy digest / replay 束縛 / idempotency key） |
| Stage 1 dry-run | guard 18 checks / validation ok / mutation NONE / NOT_PROMOTED（Stage 2 と同一 packet） |
| expected facts（11 項目） | すべて一致: `document_contradiction=false` / `document_contradiction_repeated=false` / `narrow_sibling_contradiction=true` / `narrow_sibling_repeated=true` / `contradiction_active=true` / `reject_driver=NARROW_SIBLING_CONTRADICTION` / `reversal_count=0` / `recovery_count=0` / `opposite_sibling_count=3` / `replay_current_compatible=true` / `formal_review_gate_reached=true` |
| sibling group | `JAPAN_EQUITY,SECTOR|target=JAPAN_EQUITY`（own direction UP・member 8・opposite 3・全 member の formal state NONE・C1 / C3 は本 action に非適用） |
| Shadow Review event 変更 | 0 |
| DNA 変更 | 0（blob identity 一致） |
| PDF 変更 | 0（inventory 141 件・digest 一致・open せず） |
| derived store 変更 | なし（`derived_changed=[]`・intake 活動なし） |
| tracked worktree | 不変 |
| 処理した candidate | 1 件のみ |
| 実行時間 | 18.6 秒 |
| policy digest | 6 層とも凍結値のまま（`decision 0c54ec01e2a251d9` / `evaluation 1a8443098f64d679` / `recommendation 0a979d8421a01d08` / `shadow_review e6f5094cacef6fec` / `replay 197db7c73eb0db77` / `formal_review cca7b43627b9a355`） |
| Phase 状態 | この書き込み後も **Phase 3.9.5 は OPEN** |

human formal decision reason（formal Decision の理由本文。本節にのみ記録し、他所へ複製しない）:

> The candidate evidence itself remains directionally consistent, while the active contradiction comes from
> unresolved opposite-direction sibling patterns that have not yet received formal decisions.

補足（履歴事実）:

- これは Phase 3.9.5 で最初の **human / machine 不同意事例**である。機械が誤りだったという記録ではない。
  candidate 自身の supporting document には矛盾がなく（`document_contradiction=false`、direction counts は
  UP のみ）、active contradiction は同一 sibling group 内の**未決の opposite-direction sibling 3 件**に由来する
  関係的なもの（`reject_driver=NARROW_SIBLING_CONTRADICTION`）だったため、Human Final Review は sibling の
  formal decision が出るまで継続レビューを選んだ。
- fresh build 時点の packet 束縛（packet_id / evidence digest / material digest / group digest）は read-only
  review（§19）時点と同一であり、レビューから書き込みまでに証拠は変化していない。
- 書き込み後の queue 挙動（§20.8）: `KEEP_REVIEWING` は終端ではなく primary queue に残るため、次の fresh build
  でもこの pattern が rank 1 に現れ得る。本記録時点で queue progression は未解決のままである。

## 21.1 Phase 3.9.5 Decision ledger（累積・履歴事実）

| seq | pattern_id | machine | human | decision_id | record hash（先頭） | 記録 |
|---|---|---|---|---|---|---|
| 1 | `cpt_4d2f4477a946c17e` | REJECT_RECOMMENDED | REJECTED | `cdc_884ab4cafff2dbf3` | `ed8a0c64` | §18 |
| 2 | `cpt_8c96e2070cd4c702` | REJECT_RECOMMENDED | KEEP_REVIEWING | `cdc_0a420b63cc1257ed` | `179146cd` | §21 |
| 3 | `cpt_30701289cfb0d151` | REJECT_RECOMMENDED | REJECTED | `cdc_087f4cf39db6ee97` | `36646cf9` | §24 |
| 4 | `cpt_8c96e2070cd4c702` | REJECT_RECOMMENDED | KEEP_REVIEWING（2 回目・再入後） | `cdc_43d36c7b6626eab7` | `21025da6` | §26 |
| 5 | `cpt_3831c38233ab1fcd` | REJECT_RECOMMENDED | REJECTED | `cdc_f41559274158993b` | `5a78b695` | §27 |

chain: 各 seq の `previous_record_hash` は直前 seq の record hash（seq 2 → 1、seq 3 → 2、seq 4 → 3、seq 5 → 4）。
全行 HUMAN / FORMAL / NOT_PROMOTED。seq 4 は seq 2 と同じ pattern の 2 回目の Decision であり、
pattern head 連鎖は `previous_decision_id=cdc_0a420b63cc1257ed` / `previous_state=KEEP_REVIEWING`。

## 22. Queue Progression v1（KEEP_REVIEWING の提示制御・formal_review policy 1.1.0・凍結）

Phase 3.9.5 は OPEN のまま。§20.8 / §21 で未解決だった「KEEP_REVIEWING が primary queue に残り続け、次の
fresh build でも rank 1 に現れ得る」問題を、監督者採択 **D — zero-new-storage hybrid progression model +
queue post-filter（packet 構築後・`order_queue()` 前）** で解決する。実装 module は
`src/intelligence/formal_review/progression.py`（**READ-ONLY**。Decision / Shadow / DNA / corpus / derived のどれにも
書かない）。`FormalReviewService.build()` の流れは
`population → packet 構築 → progression 分類 → primary_for_queue → order_queue` となる。

### 22.1 Decision state と derived queue status の区別（最重要）

| 概念 | 値 | 権威 | 変更可否 |
|---|---|---|---|
| **Decision state**（Phase 3.9.1・凍結） | KEEP_REVIEWING / APPROVED / REJECTED / REOPENED_FOR_REVIEW / SUPERSEDED / RETIRED | `compass_decisions/decisions.jsonl`（append-only・hash chain） | **本変更で 1 つも増減しない**。transition 表も不変 |
| **derived queue status**（1.1.0・新設） | NOT_APPLICABLE / DEFERRED_UNCHANGED_KEEP_REVIEWING / REENTERED_KEEP_REVIEWING / PROGRESSION_UNVERIFIABLE | `compass_formal_review/queue.json`（derived・rebuildable） | build ごとに再計算。store も enum も持たない |

KEEP_REVIEWING は **NON-TERMINAL のまま**。progression は「今すぐ ranked primary に見せるか」だけを決める
**presentation suppression** であり、deferred の pattern も凍結 Decision model の下で合法に decide できる
（`FormalReviewService.decide()` は queue["deferred"] の pattern を tracked candidate として解決する。
`FormalReviewGuard` は弱めていない）。cooldown なし・ad hoc な rank skip なし・履歴の書き換えなし。

### 22.2 review-relevant change（M1〜M4・凍結）

baseline は **その pattern の最新 KEEP_REVIEWING Decision row だけ**（新 metadata は追加しない。zero-new-storage）。

| 成分 | reviewed 側（Decision row） | current 側 | 変化 → |
|---|---|---|---|
| **M1 machine evidence** | `metadata.material_digest` | 現在の `material_digest`（Phase 3.9.3 凍結 semantics・拡張しない） | `M1_MATERIAL_DIGEST_CHANGED` |
| **M2 group / sibling** | `metadata.group_state_digest` | 現在 packet の `group.group_state_digest` | `M2_GROUP_STATE_CHANGED`（+ member の formal Decision sequence が reviewed head より新しければ `SIBLING_DECIDED_SINCE_REVIEW`）。sibling evidence drift による過提示は許容 |
| **M3 replay review view** | `metadata.replay_run_id` の run の summary から {stability_class, reversal_count, reject_driver, recovery_count, current_recommendation} | 現在の **current-compatible** replay の同 5 field | `M3_REPLAY_REVIEW_VIEW_CHANGED:<field>`。run id / digest だけの違いでは再入しない |
| **M4 DNA relation** | Decision `evidence` snapshot の {dna_classification, dna_best_rule_id, conflict_rule_ids} | dna_comparisons 末尾 + conflicts（evidence snapshot と同じ導出） | `M4_DNA_RELATION_CHANGED:<field>` |

### 22.3 非 material noise（単独では再入しない）

generated timestamp / local path / packet_id の変化 / corpus 件数・milestone の増加 / evidence age / replay run id・
run digest の変化 / 表現・順序だけの差 / 等価な再生成 / formal head が KEEP_REVIEWING になったこと自体。
**`packet_evidence_digest` は trigger に使わない**（Decision / freshness block が write 後に変わるため構造的に不適）。

### 22.4 fail closed = 見せる

DEFERRED は **不変を積極的に確定できたときだけ**。baseline 欠落（material / group）・reviewed replay run の
未束縛・不読・pattern 不在・現在 replay の不在・非互換・evidence snapshot の不完全（`pattern_found=false`、
field 欠落、conflict 行があるのに rule id が無い）はすべて `PROGRESSION_UNVERIFIABLE` として
**ranked primary に残す**（理由 code を `unverifiable_reasons` に出す）。Decision chain の破損は従来どおり
DecisionStore が build を失敗させる。

### 22.5 出力・監査面

- `queue["deferred"]`（非 ranked・文脈のみ・`role=DEFERRED_NON_RANKED`）と `queue["progression"]`（primary 全 pattern の
  status / 理由 code / reviewed・current digest / run id）。ranked section（REJECT → APPROVE → REOPEN）の
  順序 semantics は不変。REVISIT section も再入優先も無い（再入は通常順序）。
- metrics: `suppressed_keep_reviewing_count` / `reentered_keep_reviewing_count` / `progression_unverifiable_count`。
- CLI `list` / `status`、`next_candidate.py`（`::P395N_PROGRESSION::`・`--expect-deferred`・deferred が ranked に
  混ざれば `DEFERRED_PATTERN_IN_PRIMARY_QUEUE` で fail closed）、`validation.py`（determinism に deferred list と
  progression map を含める）。`execute.py` は deferred target を既定で拒否（`TARGET_DEFERRED_KEEP_REVIEWING`）し、
  `--allow-deferred` の明示 opt-in でのみ扱う。人間 reason 本文・PDF 名・原文・path は一切出さない。

### 22.6 formal_review policy version bump（必須訂正）

queue progression は「Human Formal Review candidate を提示するか defer するか」を決める **formal-review policy
挙動**であるため、6 層のうち **formal_review だけ** を bump し、progression semantics を digest に含める。
第 7 の policy 層は作らない。

| layer | version | digest | 変更 |
|---|---|---|---|
| decision | 1.0.0 | `0c54ec01e2a251d9` | UNCHANGED |
| evaluation | 1.0.0 | `1a8443098f64d679` | UNCHANGED |
| recommendation | 1.0.0 | `0a979d8421a01d08` | UNCHANGED |
| shadow_review | 1.0.0 | `e6f5094cacef6fec` | UNCHANGED |
| replay | 1.1.0 | `197db7c73eb0db77` | UNCHANGED |
| **formal_review** | **1.0.0 → 1.1.0** | **`cca7b43627b9a355` → `d2fb015ca827dd15`** | **CHANGED**（canonical policy serialization が計算） |

### 22.7 歴史的 Decision との互換（migration なし）

Candidate #1（`cdc_884ab4cafff2dbf3` / REJECTED）と Candidate #2（`cdc_0a420b63cc1257ed` / KEEP_REVIEWING）の row は
**書き換えない**。両 row の `metadata.policy_digests` は 1.0.0 digest `cca7b43627b9a355` に束縛されたままで、これは
正しい provenance である（`config.SUPERSEDED_FORMAL_REVIEW_DIGESTS` に記録。policy digest には含めない）。
`next_candidate.py` の row 再監査は formal_review layer についてのみ「現行 digest または歴史的 digest」を認め、
他 5 層は現行一致を要求する。Decision chain は migration 無しで VALID。progression の baseline は Candidate #2 の
既存 metadata（material `8f410ca4e7da1e58` / group `037f307fe6fd2efb` / replay run `crp_2530396a5a3b8fb7`）と
Decision evidence snapshot（DNA relation）をそのまま消費する。

### 22.8 Candidate #2 の期待挙動（Windows 実データ・未実行）

review-relevant change が無ければ `cpt_8c96e2070cd4c702` は formal_head `KEEP_REVIEWING` /
queue_status `DEFERRED_UNCHANGED_KEEP_REVIEWING` / ranked primary に無し / queue["deferred"] に有り /
`reentry_triggered=false`。Decision state・履歴は不変で新 Decision は書かれない。次の primary candidate が rank 1
になり得るが、その review / Decision は本変更では**行わない**。Candidate #1 は REJECTED / reopen 挙動のみ
（`reopen.py` 不変）。

### 22.9 Windows READ-ONLY 確認の形（identity-only・v4.52.1）

`next_candidate.py --identity-only` は fresh build 後に rank 1 の identity（pattern_id / pattern_type /
recommendation / decision_state）だけを出し、brief・dry-run・human boundary・command 提示を行わない（SAFETY は常に
実行し、書き込み経路は無い）。`--expect-row <seq>:<pattern_id>:<record_hash>`（複数可）は既存 Decision row の
不変証明で、その sequence の row が同じ pattern・同じ record_hash でなければ `EXPECTED_ROW_CHANGED_OR_MISSING:<seq>`
で DECISION_CHAIN 段階に fail closed する（fresh build の前）。Candidate #2 の確認は
`--expect-row 1:<#1>:<hash1> --expect-row 2:<#2>:<hash2> --expect-decided <#1> --expect-deferred <#2> --identity-only`
の 1 回で、2 行 chain 不変・candidate #1 decided・candidate #2 deferred・次 rank 1 identity を同時に検証する。
新 Decision は書かれず、次 rank 1 の review / Decision は別途の監督者 GO を要する。

### 22.10 READ-ONLY review の head binding（v4.52.2）

`next_candidate.py --expect-rank-1 <pattern_id>` は fresh build と rank 1 選定の直後、freshness・brief・explanation・
questions・dry-run・command 提示のいずれよりも前に、fresh rank 1 の pattern_id を期待 id と比較する。違えば
`CANDIDATE_HEAD_CHANGED` で fail closed する。出るのは CANDIDATE section の identity / derived metrics と
`expected_rank_1` / `fresh_rank_1` までで、brief・explanation・questions・dry-run・command は出ない
（別 candidate を自動的に review しない）。`--actor <actor_id>` は技術的 dry-run（機械整合 action と KEEP_REVIEWING）
の actor を差し替えるだけで、省略時は pilot の既定 actor のまま、いずれも dry-run なので永続化は起きない。
Candidate #3 の READ-ONLY review は `--expect-rank-1 cpt_30701289cfb0d151 --actor P395_HUMAN_REVIEW_PREP` を
§22.9 の引数に加えた 1 回の操作で行い、Decision は書かない。

## 23. real write の reviewed 束縛（v4.52.3・execute.py）

### 23.1 chain integrity と reviewed-history identity は別物

`DECISION_CHAIN` が従来から検査するのは **chain integrity**（row 数・sequence 連番・各 record_hash の再計算一致・
`previous_record_hash` の連結・全 row `NOT_PROMOTED`）であり、これは「store が自己整合か」しか示さない。
履歴 row の内容を書き換えて record_hash を再計算すれば、chain integrity は通ったままになる。
**reviewed-history identity**（人間がレビュー時に見たその row か）は別の性質で、呼び出し側が期待値を束縛して
初めて検証できる。`--expect-row <sequence>:<pattern_id>:<record_hash>`（複数可）が後者を担う。

- 検証は `DECISION_CHAIN` 段階、fresh build・dry-run・write のいずれよりも前。
- 書式不正は `EXPECT_ROW_MALFORMED:<spec>`、sequence 欠落・pattern 相違・record_hash 相違は
  `EXPECTED_ROW_CHANGED_OR_MISSING:<sequence>` で fail closed。`next_candidate.py` §22.9 と同じ語彙。
- 履歴 row は書き換えない。束縛は読み取り専用の照合のみ。

### 23.2 human が review した packet そのものへの束縛

`--expect-packet-id` / `--expect-material-digest` / `--expect-packet-evidence-digest` は、`FRESH_BUILD` → `TARGET` →
`PACKET_FRESHNESS` が解決した現在の packet を、人間がレビューした packet と一致させる。検査は
`PACKET_FRESHNESS` 段階、**Stage 1 dry-run の前**に行い、相違があれば
`HUMAN_REVIEW_PACKET_CHANGED:<field>` で停止する（複数相違は `packet_id,material_digest,packet_evidence_digest` の
固定順で連結した決定的な 1 行）。freshness だけでは不十分で、内部的に fresh でも別 packet は同じ人間判断の対象では
ないため、rebuild 後の packet を黙って採用しない。3 つとも任意で、無指定なら従来どおり fresh 追従（`NOT_BOUND`）。

### 23.3 保持される既存の実行安全性

1 invocation = 1 candidate = real write 1 回・自動再試行なし・Stage 1 と Stage 2 で同一 packet・
rows before / current state / machine recommendation / queue rank / 型付き expected fact allowlist /
group digest / 6 層 policy digest の呼び出し側束縛・書き込み後の Decision 監査・global chain 監査・
pattern 固有 prior head 監査・Shadow / DNA / PDF 安全性・`NOT_PROMOTED`・main 未マージ。
candidate 固有の定数は持たない（すべて引数）。

## 24. Candidate #3 real-write audit record（監査証跡・履歴事実）

本節は **Phase 3.9.5 で 3 番目に書かれた実 human formal Decision の記録**であり、§18（candidate #1）・
§21（candidate #2）とは別の事例として記録する。履歴の事実であり、semantics・policy digest・packet schema・
guard 挙動のいずれも定義しない（それらは §1〜§13、実行 envelope は §20、reviewed 束縛は §23）。

| 項目 | 値 |
|---|---|
| 実行 driver | `src/intelligence/formal_review/execute.py`（汎用 execution session・§20 + §23 の reviewed 束縛） |
| 実行 commit（`--require-commit` 束縛） | `78e3545`（v4.52.3・reviewed packet / reviewed history 束縛の導入） |
| pattern_id | `cpt_30701289cfb0d151` |
| pattern_type | EVIDENCE_WHY |
| fresh queue rank | 1（REJECT_RECOMMENDED section・`--require-queue-rank 1` で束縛） |
| **machine recommendation** | **REJECT_RECOMMENDED** |
| **human formal decision** | **REJECTED**（機械推奨と同方向） |
| decision_id | `cdc_087f4cf39db6ee97` |
| sequence | 3 |
| previous_record_hash | `179146cd…5843ca`（= candidate #2 の record hash） |
| previous_decision_id / previous_state | 空 / 空（この pattern では初回の Decision） |
| actor / actor_type / review_mode | `P395_HUMAN_SUPERVISED_REVIEW` / HUMAN / FORMAL |
| promotion_status | NOT_PROMOTED |
| packet_id | `frp_fae93b89c646e012`（read-only review 時と同一・`--expect-packet-id` で束縛） |
| packet_evidence_digest | `841d526dadadc886`（`--expect-packet-evidence-digest` で束縛） |
| material_digest | `8fc381f70b6bcfd3`（`--expect-material-digest` で束縛） |
| group_state_digest | `9ae6617da0fc96ef`（sibling group なし・`GROUP_CONTEXT_UNCHANGED`） |
| replay run id / digest | `crp_2530396a5a3b8fb7` / `74d5b037498fc0de` |
| stability_class | STABLE |
| corpus eligible（packet / write 時点） | 139 / 139 |
| idempotency_key | `frp_fae93b89c646e012`（= packet_id） |
| record hash | `36646cf98a78a429edb6dc9dc26e3625f0443c4ff64aaa3da9540d0350a771dd` |
| Decision rows | 2 → 3 |
| 束縛した歴史行 | `--expect-row 1:cpt_4d2f4477a946c17e:ed8a0c64…0006c0` / `--expect-row 2:cpt_8c96e2070cd4c702:179146cd…5843ca` |
| expected facts（14 項目） | `document_contradiction=true` / `document_contradiction_repeated=true` / `narrow_sibling_contradiction=false` / `narrow_sibling_repeated=false` / `contradiction_active=true` / `reject_driver=SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION` / `reversal_count=0` / `recovery_count=0` / `opposite_sibling_count=0` / `replay_current_compatible=true` / `formal_review_gate_reached=true` / `direction_class=NON_DIRECTIONAL` / `eligible_support=21` / `stability_class=STABLE` |
| sibling group | なし（`sibling_group_key` 空・group_size 0・member 0・opposite 0・C1 / C3 は本 action に非適用） |
| policy digest | 6 層とも凍結値（`decision 0c54ec01e2a251d9` / `evaluation 1a8443098f64d679` / `recommendation 0a979d8421a01d08` / `shadow_review e6f5094cacef6fec` / `replay 197db7c73eb0db77` / `formal_review d2fb015ca827dd15`） |
| Phase 状態 | この書き込み後も **Phase 3.9.5 は OPEN** |

human formal decision reason（formal Decision の理由本文。§18 / §21 と同じく本節にのみ記録し、他所へ複製しない）:

> The supporting evidence remains directionally contradictory across a long observation span, and the
> contradiction is repeated, active, and unrecovered despite persistent evidence over time.

理由カテゴリ（他文書で参照してよい要約表現）: **repeated active supporting-document contradiction with no
replay recovery**。

補足（履歴事実）:

- candidate #1（§18）と同じく human と machine が同方向の事例だが、reject driver が異なる。#3 は candidate 自身の
  supporting document 間の**繰り返す方向矛盾**（`SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION`）が現在も active で、
  replay 上の recovery が 0 件（`recovery_count=0` / `reversal_count=0` / stability STABLE）であることによる。
  sibling 由来の関係的矛盾（#2）ではない。
- 本書き込みは §23 の reviewed 束縛（reviewed packet 3 値 + 歴史行 2 行）を初めて使った Decision であり、
  「人間がレビューしたその packet・その履歴」以外では write が起きない状態で実行された。
- 書き込み後の queue 挙動: REJECTED は既決なので primary queue から外れる（`reopen.py` の REOPEN 判定のみが
  以後この pattern を扱う）。#2 の deferred KEEP_REVIEWING（§22）は変わらない。
- 本節の値は実行環境（Windows 実データ）で得られた報告に基づく。監督者へ未報告の項目（実行日時・実行時間・
  guard check 件数・group material digest・lifecycle）は本表に記載しない。

## 25. Re-entry guard と M2 observability（v4.54）

### 25.1 Candidate #2 の M2 member delta は復元不能（履歴上の限界）

Candidate #2（`cpt_8c96e2070cd4c702`）は formal head `KEEP_REVIEWING` のまま
`REENTERED_KEEP_REVIEWING` / `M2_GROUP_STATE_CHANGED` で再入した。しかし **その再入を引き起こした
member を特定することはできない**。理由は persistence の構造そのものにある。

- Decision row の metadata（20 key / 500 chars 制約）は `group_state_digest`（16 hex）だけを持ち、member 一覧を持たない。
- `group_state_digest` は `{pattern_id, own_direction, members[{pattern_id, direction, recommendation,
  decision_state, material_digest, relationship}]}` の SHA-256 先頭 16 桁であり、一方向。digest から view は戻せない。
- Decision の evidence snapshot は pattern 単位（support / axes / DNA）で group member を含まない。
- packet は build ごとに上書きされるため、review 時点の packet `frp_b118d3272d4382c1` は現存しない。

したがって以下は **PROGRESSION_DELTA_UNRESOLVED** として記録する（推測で埋めない・backfill しない・row 2 を書き換えない）。

| 判定 | 内容 |
|---|---|
| 判明している | 旧 `group_state_digest` `037f307fe6fd2efb`（row 2 metadata）/ 新 digest（fresh build）/ `changed_components=["M2"]` |
| 復元不能 | 旧 member id・旧 member ごとの recommendation / decision state / material digest・旧 direction relation・原因 member |
| 決定的に除外: B | sibling の formal Decision が原因（`sibling_decided_since_review=false`。row 2 以降の Decision は row 3 のみ） |
| 決定的に除外: D | 表現の再生成のみ（digest は semantic field のみを含むため、同値の再生成では変化しない） |
| 残る因果クラス | **A**（新しい corpus 証拠で group membership が変化）または **C**（既存 sibling の recommendation / material 変化）。**どちらかを特定して主張しない** |

再入 reason が M2 のみであることから、M1（candidate 自身の material 証拠）・M3（replay review view）・
M4（DNA relation）は review 時点と同一である。これは frozen progression semantics からの決定的帰結であり、
Human Review は「自分の証拠は不変・group 文脈だけが変わった」という前提で現在の証拠を見て判断してよい。

### 25.2 re-entry guard（呼び出し側束縛・fail closed）

`next_candidate.py` に target（fresh rank 1）レベルの束縛を追加した。

- `--expect-queue-status <status>`: 違えば `QUEUE_STATUS_CHANGED`。
- `--expect-reentry-reason <reason>`（複数可）: reason 集合が完全一致しなければ `REENTRY_REASON_CHANGED`
  （値の相違・過剰・不足のいずれも失敗。比較は sorted set で決定的）。

判定は queue / progression 計算と rank 1 束縛の直後、**freshness・brief・explanation・questions・dry-run・
command 提示より前**。無指定なら従来どおり（束縛なし）。

### 25.3 M2 observability（read-only）

PROGRESSION section は各 pattern について `reviewed_group_state_digest` / `current_group_state_digest` /
`changed_components` を出す。いずれも progression 成果物（`queue.json` の `progression`）に既にある値で、
新しい semantics・policy・persistence ではない。target については `target_progression` 行にも同じ 3 値を出す。

### 25.4 将来の reviewed group snapshot（設計メモのみ・未実装・別 gate）

将来の M2 再入を完全に説明可能にするには、review 時点の group member view を保存する必要がある。
本節は**設計メモであり、本 patch では実装しない**（write atomicity と audit persistence に触れるため別 design gate）。

- forward-looking のみ。既存 Decision row の migration・書き換え・backfill は行わない。
- append-only / immutable。formal Decision（decision_id）と packet_id に keyed。
- 記録内容: group key・own direction・member ごとの pattern_id / direction / recommendation / decision_state /
  material_digest / relationship（M2 semantic view を再構成できる最小十分集合）。
- 自身の digest を持ち、Decision row 側の `group_state_digest` と一致することを検証できる。
- partial write / crash 時の挙動を明示設計する（Decision append と snapshot write の順序と、片方だけ残った場合の
  読み取り側の扱い）。snapshot の失敗が Decision の二重書き込みを誘発してはならない。
- `ONE_CANDIDATE_ONE_WRITE`（1 invocation = 1 candidate = real write 1 回・再試行なし）を弱めない。

## 26. Candidate #2 second KEEP_REVIEWING audit record（再入後の 2 回目・履歴事実）

本節は **同一 pattern に対する 2 回目の human formal Decision** の記録であり、§21（1 回目の KEEP_REVIEWING）とは
別事象として記録する。履歴の事実であり semantics を定義しない（progression は §22、reviewed 束縛は §23、
re-entry guard は §25）。

| 項目 | 値 |
|---|---|
| 実行 driver | `src/intelligence/formal_review/execute.py`（§20 + §23 の reviewed 束縛） |
| 実行 commit（`--require-commit` 束縛） | `7868617`（v4.54） |
| pattern_id / pattern_type | `cpt_8c96e2070cd4c702` / EVIDENCE_OUTLOOK |
| 直前の formal state | KEEP_REVIEWING（§21・seq 2） |
| 再入 | queue status `REENTERED_KEEP_REVIEWING` / reason `M2_GROUP_STATE_CHANGED` / `changed_components=["M2"]` |
| fresh queue rank | 1 |
| **machine recommendation** | **REJECT_RECOMMENDED** |
| **human formal decision** | **KEEP_REVIEWING**（2 回目・機械推奨への不同意を維持） |
| decision_id | `cdc_43d36c7b6626eab7` |
| sequence | 4 |
| previous_record_hash | `36646cf9…a771dd`（= candidate #3 の record hash・global tail） |
| previous_decision_id / previous_state | `cdc_0a420b63cc1257ed` / KEEP_REVIEWING（pattern head 連鎖） |
| actor / actor_type / review_mode | `P395_HUMAN_SUPERVISED_REVIEW` / HUMAN / FORMAL |
| promotion_status | NOT_PROMOTED |
| packet_id | `frp_fbd37f23ac6ffa46`（再入後の fresh packet・`--expect-packet-id` で束縛） |
| packet_evidence_digest | `a4dd35beaf13716d` |
| material_digest | `8f410ca4e7da1e58`（§21 の 1 回目と同一＝候補自身の material 証拠は不変） |
| group_state_digest | `7c244c81b2f16dda`（1 回目の `037f307fe6fd2efb` から変化。これが M2 再入の実体） |
| replay run id / digest | `crp_2530396a5a3b8fb7` / `74d5b037498fc0de`（captured 139・current 144・evidence age 5・
`W_REPLAY_EVIDENCE_AGE`・compatible。KEEP_REVIEWING は replay evidence 必須 action ではないため blocker ではない） |
| stability_class | STABLE |
| corpus eligible（packet / write 時点） | 144 / 144 |
| idempotency_key | `frp_fbd37f23ac6ffa46`（= packet_id。1 回目とは別 packet なので二重書き込みではない） |
| record hash | `21025da696ec775aad5b830d83e7f6cccb942b1447433de8c8ba8c53437d8863` |
| Decision rows | 3 → 4 |
| expected facts（14 項目） | `document_contradiction=false` / `document_contradiction_repeated=false` /
`narrow_sibling_contradiction=true` / `narrow_sibling_repeated=true` / `contradiction_active=true` /
`reject_driver=NARROW_SIBLING_CONTRADICTION` / `reversal_count=0` / `recovery_count=0` /
`opposite_sibling_count=3` / `replay_current_compatible=true` / `formal_review_gate_reached=true` /
`direction_class=DIRECTIONAL` / `eligible_support=5` / `stability_class=STABLE` |
| sibling group | `JAPAN_EQUITY,SECTOR|target=JAPAN_EQUITY`（group size 9 / member 8 / opposite DOWN 3 件は
いずれも recommendation KEEP_REVIEWING・formal state NONE。C1 / C3 は本 action に非適用） |
| policy digest | 6 層とも凍結値（§24 と同一） |
| Phase 状態 | この書き込み後も **Phase 3.9.5 は OPEN** |

human formal decision reason（本節にのみ記録し、他所へ複製しない）:

> The candidate's own supporting evidence remains directionally consistent, while the active contradiction is
> still confined to unresolved opposite-direction sibling patterns; the changed group state does not provide
> sufficient evidence to reject the candidate.

理由カテゴリ（他文書で参照してよい要約表現）: **candidate's own evidence remained directionally consistent;
contradiction remained confined to unresolved opposite-direction siblings**。

補足（履歴事実）:

- material_digest が 1 回目と同一である一方 group_state_digest だけが変わっており、§25.1 の記録どおり
  「候補自身の証拠は不変・group 文脈のみ変化」という再入だったことが Decision 側からも確認できる。
  どの member が変えたかは §25.1 のとおり復元不能（`PROGRESSION_DELTA_UNRESOLVED`）。
- 本 Decision により **新しい M2 状態が reviewed baseline になる**。以後 review-relevant な変化が無ければ、
  次の fresh build で本 pattern は `DEFERRED_UNCHANGED_KEEP_REVIEWING` に戻る。これは進行の結果であって
  手で設定するものではなく、書き込み後の監査で確認する。
- 同一 pattern の 2 回目 KEEP_REVIEWING は凍結 transition（`KEEP_REVIEWING → KEEP_REVIEWING`）の範囲内であり、
  §20.7 の duplicate hazard は呼び出し側束縛（`--expect-rows-before` / `--expect-current-state` /
  §23 の packet 束縛）で閉じている。

## 27. Candidate #4 real-write audit record（監査証跡・履歴事実）

本節は Phase 3.9.5 で 5 番目に書かれた実 human formal Decision の記録であり、§18 / §21 / §24 / §26 とは
別事例として記録する。履歴の事実のみで semantics は定義しない。

| 項目 | 値 |
|---|---|
| 実行 driver | `src/intelligence/formal_review/execute.py`（§20 + §23 の reviewed 束縛） |
| 実行 commit（`--require-commit` 束縛） | `4589b31` |
| pattern_id / pattern_type | `cpt_3831c38233ab1fcd` / **EVIDENCE_RISK**（本 Phase で最初の EVIDENCE_RISK） |
| 直前の formal state | NONE（この pattern では初回の Decision） |
| fresh queue rank | 1 |
| **machine recommendation** | **REJECT_RECOMMENDED** |
| **human formal decision** | **REJECTED**（機械推奨と同方向） |
| decision_id | `cdc_f41559274158993b` |
| sequence | 5 |
| previous_record_hash | `21025da6…37d8863`（= Candidate #2 2 回目の record hash・global tail） |
| previous_decision_id / previous_state | 空 / 空 |
| actor / actor_type / review_mode | `P395_HUMAN_SUPERVISED_REVIEW` / HUMAN / FORMAL |
| promotion_status | NOT_PROMOTED |
| packet_id | `frp_128f51cfd53b1674` |
| packet_evidence_digest | `258c9aa883ee8d2f` |
| material_digest | `079a7d021d71a006` |
| group_state_digest | `151d41b8867b0b4b`（sibling group なし・member 0・opposite 0・C1 / C3 非適用） |
| replay run id / digest | `crp_2530396a5a3b8fb7` / `74d5b037498fc0de`（captured 139 / current 144 / age 5 /
`W_REPLAY_EVIDENCE_AGE` / compatible。first REJECT position 82・2026-06-08・current-state eligible 57・
persistence 1.0000・reversal 0・recovery 0） |
| stability_class | STABLE |
| corpus eligible（packet / write 時点） | 144 / 144 |
| idempotency_key | `frp_128f51cfd53b1674`（= packet_id） |
| record hash | `5a78b69580afac6842b1cfba1cc1922a63b24770039a4ce011348d9508c24814` |
| Decision rows | 4 → 5 |
| **reject driver** | **`SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION`**（document contradiction true / repeated true /
first material contradiction position 41 / currently active / recovery なし / reversal 0 /
recommendation before reject KEEP_REVIEWING / was_review_before_reject false） |
| 証拠 | support 6 / eligible_support 6 / span 109 日 / 4 calendar months / distinct 2D cells 4 /
confirmed 2D cells 2 / valid ratio 1.00 / direction counts UP 3・DOWN 2・RANGE 1 |
| axis 状態 | Consistency LOW / Strength HIGH / Time HIGH / Cross-Regime HIGH / Data Quality HIGH |
| DNA | classification PARTIALLY_EXPLAINED / best rule `JP_DIR_002` / direction relation UNKNOWN / conflicts 0
（DNA promotion は別 gate・本 Decision は DNA を編集しない） |
| policy digest | 6 層とも凍結値 |
| Phase 状態 | この書き込み後も **Phase 3.9.5 は OPEN** |

human formal decision reason（本節にのみ記録し、他所へ複製しない）:

> The supporting evidence remains directionally contradictory across multiple observations and months; the
> contradiction is repeated, active, and unrecovered, with no replay reversal or recovery.

理由カテゴリ（他文書で参照してよい要約表現）: **candidate's own supporting evidence remained directionally
contradictory across repeated observations with no recovery**。

補足（履歴事実）:

- support が 6 と小さいが、**低 support は REJECT の理由になり得ない**。凍結 rule（`rules.py` の REJECT 分岐）は
  Consistency LOW かつ Strength HIGH 以上かつ Time MEDIUM 以上かつ「反復した矛盾」を同時に要求し、証拠不足は
  Strength を下げて REJECT を **block** する側に働く。本件は Strength HIGH のまま document 間の反復矛盾が
  成立した事例である（§24 の Candidate #3 と同じ driver、Candidate #2 の sibling 由来矛盾とは別系統）。
- `W_REPLAY_EVIDENCE_AGE`（age 5）は警告であり、REJECTED の gate は replay の *compatibility* のみを要求する。
  本 Decision で replay の再生成は行っていない。
