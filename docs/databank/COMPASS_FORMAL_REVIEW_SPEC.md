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

chain: seq 2 の `previous_record_hash` = seq 1 の record hash。全行 HUMAN / FORMAL / NOT_PROMOTED。
