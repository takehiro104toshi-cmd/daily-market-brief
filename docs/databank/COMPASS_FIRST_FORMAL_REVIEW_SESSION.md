# First Human Formal Review Session — 手順書（Phase 3.9.5）

**HUMAN / ONE_PATTERN_AT_A_TIME / NO_BATCH / PACKET_BOUND / NO_DNA_PROMOTION**

この文書は「最初の formal human review」を人間が 1 件ずつ実施するための手順である。機械は証拠を提示し、
freshness と整合性を検査するだけで、**action を選ばない**。APPROVE_RECOMMENDED ≠ APPROVED、
REJECT_RECOMMENDED ≠ REJECTED、APPROVED ≠ Compass DNA promotion。

実行は監督者の明示的な HUMAN-DECISION GO の後に限る。この文書の存在は実行許可ではない。

## 1. session の目的と選べる action

| 機械推奨 | 人間が選べる formal action |
|---|---|
| APPROVE_RECOMMENDED | `APPROVED` または `KEEP_REVIEWING` |
| REJECT_RECOMMENDED | `REJECTED` または `KEEP_REVIEWING` |

推奨に反対する方向（APPROVE 候補を REJECTED にする等）は v1 で禁止。反対なら `KEEP_REVIEWING` に理由を書く。
自動 action・既定 action・batch は存在しない。全 decision は `promotion_status = NOT_PROMOTED` で残る。

## 2. 順序（凍結・並べ替えない）

queue の凍結順をそのまま使う。section 1 = REJECT_RECOMMENDED、section 2 = APPROVE_RECOMMENDED、
section 3 = REOPEN_ELIGIBLE。主観で優先度を変えない。

**session 開始時に queue を必ず再 build する**。以下は 2026-09-05 の Windows 実機で検証された履歴順であり、
参照情報にすぎない（production logic には一切埋め込まない。実施時の順序は再 build 結果が決める）。

| # | section | pattern_id | pattern_type |
|---|---|---|---|
| 1 | REJECT | `cpt_4d2f4477a946c17e` | EVIDENCE_WHY |
| 2 | REJECT | `cpt_8c96e2070cd4c702` | EVIDENCE_OUTLOOK |
| 3 | REJECT | `cpt_30701289cfb0d151` | EVIDENCE_WHY |
| 4 | REJECT | `cpt_3831c38233ab1fcd` | EVIDENCE_RISK |
| 5 | REJECT | `cpt_2beb409780e71951` | EVIDENCE_RISK |
| 6 | REJECT | `cpt_1fde85f01d393e44` | EVIDENCE_RISK |
| 7 | APPROVE | `cpt_e6a847467534e87d` | STATE_OUTLOOK |
| 8 | APPROVE | `cpt_05548cdeda5cf3fb` | THEME_OUTLOOK |
| 9 | APPROVE | `cpt_d83bd5cf10698289` | THEME_OUTLOOK |
| 10 | APPROVE | `cpt_e67725daf99fb481` | THEME_OUTLOOK |
| 11 | APPROVE | `cpt_ba7d28bbd278e06d` | THEME_OUTLOOK |
| 12 | APPROVE | `cpt_b93f09539c61263d` | STATE_OUTLOOK |
| 13 | APPROVE | `cpt_d4278da594a0a797` | STATE_OUTLOOK |
| 14 | APPROVE | `cpt_6271c0764c5ca7c4` | STATE_OUTLOOK |
| 15 | APPROVE | `cpt_c12bb4da3b396908` | THEME_OUTLOOK |
| 16 | APPROVE | `cpt_f70da4467bf45553` | EVIDENCE_OUTLOOK |

## 3. 1 候補あたりの提示（`brief <pattern_id>`）

`session.candidate_brief` が返す 10 節。原文・ファイル名・path・人間の review reason 本文は含まない。

| 節 | 内容 |
|---|---|
| 1 identity | queue rank / pattern_id / pattern_type / lifecycle / packet_id |
| 2 recommendation | 機械推奨・triggered rule・supporting rules・blocking rules・formal gate・corpus |
| 3 evidence | eligible_support / support_count / span_days / calendar months / 2D cells / 品質分布 / valid ratio / 6 軸の state・applicability・reason（Reference Score は `NON_DECISIONAL_REFERENCE_ONLY`） |
| 4 replay | first recommendation position・date / persistence / reversal / 現状態の eligible 文書数 / stability class と calibration / worst consistency / time・cross-regime HIGH 履歴 / first surfaced in MAIN / evidence age / run digest / appeared_only_after_100 / reversions |
| 5 dna relation | classification / best_rule_id / direction_relation / candidate rule count / conflict rule ids |
| 6 contradiction | reject driver / first material contradiction position / recovery positions / 現在 active か / document・narrow sibling・DNA の各指標 / direction counts |
| 7 group context | sibling group size / opposite-direction member とその formal state / C1・C3 status |
| 8 human history | Shadow Review 件数・現在 outcome・history digest（**reason 本文は出さない**） |
| 9 decision state | 現在の formal state / head decision id / 履歴長 / promotion status / 許可 action |
| 10 warnings | RECENT_TRANSITION / replay age / contradiction active / sibling / その他 |

### 説明文の規則

`session.explanation` は packet にある事実だけを短文へ変換する（生成 AI も推論も使わない）。

- 例（APPROVE）: `Recommendation became APPROVE at eligible position 91 (2026-06-30) and has remained APPROVE through the current replay with 0 reversals.`
- 例（REJECT）: `Recommendation became REJECT at eligible position 82 (2026-05-10) due to repeated supporting-document directional contradiction and has not recovered.`

禁止語彙（test で機械検査）: `should be approved` / `should be rejected` / `safe to approve` / `clearly reject` 等。
使う語彙: `machine recommendation` / `evidence supports the current recommendation` / `Human formal decision required`。

## 4. 人間が明示的に答える設問

APPROVE 候補:

- **A1** この pattern が何を主張しているか理解したか。
- **A2** 機械側の証拠はその主張と内部整合しているか。
- **A3** Replay は「1 文書の偶発」ではないと言えるだけ持続しているか。
- **A4** DNA 関係や group 文脈から見て、formal approval は時期尚早でないか。
- **A5** `APPROVED` か `KEEP_REVIEWING` か。
- **A6** 実質的な理由を書く（20 文字以上・推奨ラベルだけは不可）。

REJECT 候補:

- **R1** 矛盾 / reject driver を理解したか。
- **R2** 矛盾は現在も active か。
- **R3** Replay に回復はあったか。
- **R4** formal REJECTED は「本当に矛盾する・信頼できない pattern」を落とすものか。個人的な好みではないか。
- **R5** `REJECTED` か `KEEP_REVIEWING` か。
- **R6** 実質的な理由を書く（20 文字以上・推奨ラベルだけは不可）。

## 5. 1 件あたりの実行手順（2 段階・厳守）

```
1. python -m src.intelligence.formal_review.cli build            # queue と packet を再構築
2. python -m src.intelligence.formal_review.cli session          # 凍結順の全 step（読むだけ）
3. python -m src.intelligence.formal_review.cli brief <pattern>  # 当該 1 件の提示と設問
4. 人間が action と理由を決める（機械は選ばない）
5. stage 1: decide … --dry-run                                    # guard 22 段 + validate。書かない
6. dry-run が PASS したら、人間が最終確認を宣言する
7. stage 2: 同じ action を --confirm "CONFIRM <STATE> <pattern>" 付きで実行  # ここで初めて書く
8. 直後に監査（§6）
9. build し直して次の候補へ
```

stage 2 の token は `CONFIRM <decision_type> <pattern_id>`（例 `CONFIRM APPROVED cpt_e6a847467534e87d`）で、
大文字小文字・pattern・state のすべてが一致しなければ guard へ届く前に拒否される（exit 3・無書き込み）。
**16 件を 1 操作で書く script は作らない。** 「機械 APPROVE を一括承認」も「機械 REJECT を一括却下」も禁止。

C3（未決の反対方向 APPROVE_RECOMMENDED sibling）がある候補では、`brief` が提示する
`--acknowledge-sibling <pattern_id>` を stage 1・stage 2 の両方に付ける。無ければ guard が
`SIBLING_ACKNOWLEDGEMENT_REQUIRED` で止める。C1（反対方向 sibling が既に APPROVED）は override 不能。

## 6. 各 decision 直後の監査（次へ進む前に必ず）

```
python -m src.intelligence.decision.cli history --pattern <pattern_id>
python -m src.intelligence.formal_review.cli status
```

確認項目:

- 新規 Decision 行が **ちょうど 1 行**
- hash chain 妥当（`decision.cli list` が corrupt を出さない）
- pattern_id が正しい / 結果 state が意図どおり
- metadata に packet binding（`packet_id` / `packet_evidence_digest` / `material_digest`）
- `promotion_status = NOT_PROMOTED`
- Shadow Review event が増えていない
- DNA・PDF が変わっていない

異常があればその場で停止する。16 件終わってから探さない。

## 7. 書き込み前に毎回再検証されるもの（guard・自動）

packet freshness（`packet_evidence_digest`）/ recommendation 一致 / material digest / 6 層 policy digest /
formal gate（evaluation record と live corpus の両方）/ lifecycle / Decision head 不変 / transition /
replay evidence の current 互換 / sibling C1・C3 / HUMAN actor / reason 最小長 / metadata 制約 / forbidden key。
1 つでも外れれば書かない。packet を再 build して人間へ戻す。

## 8. session 終了時の要約

```
reviewed / APPROVED / REJECTED / KEEP_REVIEWING / remaining pending
```

pattern ごとに: `pattern_id` / 機械推奨 / 人間の formal state / 短い理由 / `packet_id` / `decision_id` /
promotion status。加えて Decision hash chain 妥当・DNA 不変・PDF 不変・Shadow Review 不変・
全 APPROVED が NOT_PROMOTED であること。原文・PDF 名・path は出さない。

## 9. Phase 3.9.5 closure

この session の完了だけでは close しない。closure には最終 Decision audit、chain 妥当性、全 decision の
packet binding、全 APPROVED が NOT_PROMOTED、DNA 不変、監督者の最終判定が要る。
DNA promotion は別 gate であり、この Phase では一切行わない。

## 10. session 実績（運用記録・履歴事実）

| 回 | 日付(UTC) | 対象 | 機械推奨 | 人間の formal state | decision_id | sequence | 書き込み |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-07 | `cpt_4d2f4477a946c17e`（EVIDENCE_WHY） | REJECT_RECOMMENDED | **REJECTED** | `cdc_884ab4cafff2dbf3` | 1 | 1 行（0 → 1） |

1 回目の詳細な監査証跡（packet 束縛・digest・replay run・record hash・無変更証明・formal reason 本文）は
`COMPASS_FORMAL_REVIEW_SPEC.md` §18 に一元記録する。本表には理由本文を複製しない。

進行中: reviewed 1 / APPROVED 0 / REJECTED 1 / KEEP_REVIEWING 0。残りは毎回 fresh build で再導出する
（既決 pattern は primary queue から外れるため、書き込み前の順位をそのまま持ち越さない）。

次の 1 件は `next_candidate.py`（`COMPASS_FORMAL_REVIEW_SPEC.md` §19）で読み取り専用に提示する。
Decision chain の妥当性と既決 pattern の primary queue 除外を先に検査し、そのあとで現在の rank 1 を
1 件だけ出す。§9 のとおり、この記録が増えても Phase 3.9.5 は自動的には close しない。
