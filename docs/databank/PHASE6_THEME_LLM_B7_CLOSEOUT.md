# PHASE 6 / P6-B7 CLOSEOUT — LLM PROPOSAL LAYER FINAL AUDIT

新しい能力なし。本 closeout の変更は文書・CHANGELOG・凍結台帳の test（`tests/intelligence/test_theme_llm_closeout.py`）
だけで、production runtime は変更していない。

---

## 1. 結論

**P6-B7 LLM 提案層は完了条件を満たす。** 判定: `P6_B7_COMPLETE / READY_FOR_PHASE6_NEXT_GATE`。

B7 の不変条件（凍結）:

```
LLM PROPOSES.
DETERMINISTIC CODE VALIDATES.
HUMAN DECIDES.
AUTHORITY LAYER RECORDS.
```

- B7 の authority の上限は **L1 提案 authority だけ**（B3 EVIDENCE_CANDIDATE / THEME_CANDIDATE・B5C RELATION_CANDIDATE）。
- B7 は次を作らない・変えない: HUMAN decision、L2 の reviewed Theme、ThemeRoot、EvidenceAttachment、RelationAssertion、
  SourceClaimVerification、governance 状態、B6 review 状態、Production DNA、公開 / trading 出力。
- 根拠: B7G の E2E（状態と hash inventory、124 test）、各 gate の mutation（B7D 13・B7E 12・B7F 13・B7G 17 種、すべて検出）、
  guard への違反注入 10 種（すべて検出）、本 closeout の凍結台帳 test と最終回帰（§16）。
- blocker なし（§20）。runtime の remediation は不要。

## 2. architecture（最終の data flow）

```
上流 authority（Foundation Theme・B5B relation・B4 入力。PIT 入口だけ）
  │  caller が与える aware cutoff
  ▼
B7C build_input_manifest ── LlmInputManifest（visible 部分 ＋ 内部対応表 resolution）
  │  visible JSON だけ
  ▼
B7E prepare_generation ── GenerationInput（prompt contract ＋ task contract ＋ data 欄）
  ▼
FakeProvider / RecordedProvider（1 回だけ。実 provider なし）── raw response（保存しない）
  ▼
B7B parse_generation_output（厳格。修復・抽出・部分採用なし）── LlmGenerationEnvelope
  ▼
B7D validate_generation（resolution で grounding・凍結語彙・上限・template）── LlmValidationResult ＋ 検証済み plan
  ▼
正常な orchestration（caller の合成）: VALIDATED かつ生成監査 journal に記録済みのときだけ ValidatedGeneration
  ▼
B7F submit_proposals（提出境界で再検証 → 凍結 B3 / B5C constructor → check-then-reuse → 決定論的な追記）
  ▼
既存 B3 提案 journal / B5C 関係提案 journal（L1）──▶ 人間の decision（B3 / B5C）──▶ 実行 bridge（B7 の外・未接続）
```

別系統（監査だけ）:

```
B7E run_generation ──▶ 生成監査 journal（theme_intelligence/llm_generation_records.jsonl。追記専用）
```

生成監査 journal は **OPERATIONAL / AUDIT data** であり、evidence でも、提案 authority でも、governance でも、生成入力でも、
自己学習の記憶でもない（§10）。

## 3. authority model

| artifact | gate | authority class | 永続 | identity | 作る者 | 読む者 | LLM の文が authority identity に効くか |
|---|---|---|---|---|---|---|---|
| `LlmGenerationRequest` | B7B | NON-AUTHORITY（要求の記述） | 非永続（field は監査 record に写る） | `thllmreq_` content id（task・cutoff・prompt contract・出力 schema・manifest digest・knowledge pin。generated_at は除外） | caller | B7E・B7D | 効かない（LLM より前） |
| `LlmGenerationEnvelope` | B7B | UNTRUSTED 構造化出力 | 非永続（`thllmout_` digest だけ監査 record へ） | output digest | B7B parser | B7D だけ | 直接は効かない（B7D が handle 解決・template 化） |
| `LlmCandidate` | B7B | UNTRUSTED | 非永続 | なし（envelope 内） | B7B parser | B7D | 効かない |
| `LlmAbstention` | B7B | UNTRUSTED・成功した非行動 | 非永続（理由の enum は監査 record へ） | 理由の enum | B7B parser | B7D → B7E | 効かない（plan 0 件） |
| `LlmGenerationRecord` | B7B | 凍結・実行時未使用の model（KEEP FROZEN） | 永続化されない | `thllmgen_` | 実行時には誰も作らない | なし | 該当なし |
| `LlmInputManifest` | B7C | DERIVED NON-AUTHORITY（PIT 投影） | 非永続（digest は監査 record へ） | manifest digest `thllmin_`（visible ＋ resolution）・visible digest `thllmvis_` | B7C builder | B7E（visible だけ）・B7D | 効かない（LLM より前） |
| manifest resolution（内部対応表） | B7C | 内部対応表（LLM に見せない） | 非永続 | manifest digest に束縛 | B7C | B7D だけ | 効かない |
| 検証済み proposal plan | B7D | DERIVED NON-AUTHORITY | 非永続 | plan id `thllmplan_`（正規化済み material。`llm_rationale` 除外）・`upstream_proposal_id` | B7D | B7F（再検証の後） | 効かない（handle・凍結語彙の slug・構造だけが検証を経て効く。自由文は identity 外・identity 文は template） |
| `LlmValidationResult` | B7D | DERIVED NON-AUTHORITY | 非永続（id は監査 record と提案 provenance の参照文へ） | `thllmval_`（request・manifest・output digest・pin・plan id） | B7D | B7E・B7F | 提案 identity には効かない（言い換えは output digest 経由で result id だけを変える） |
| `GenerationInput` | B7E | NON-AUTHORITY | 非永続（`thllmgin_` digest だけ） | 生成入力 digest | B7E | provider | 効かない |
| `GenerationResult` | B7E | NON-AUTHORITY | 非永続 | なし | B7E | caller の orchestration | 効かない |
| `LlmGenerationAuditRecord` | B7E | OPERATIONAL / AUDIT | 永続（journal の 1 行） | attempt id `thllmatt_`（試行の event identity: request・入力 digest・provider / model / config・generated_at）・audit id `thllmaud_`（全 field） | B7E | 監査だけ | 効かない |
| 生成監査 journal | B7E | OPERATIONAL / AUDIT・APPEND-ONLY | 永続 | attempt id が key | `LlmGenerationJournal` だけ | 監査の読み手だけ | 効かない |
| `SubmissionResult` | B7F | NON-AUTHORITY（返り値） | 非永続 | なし | B7F | caller | 効かない |
| B3 / B5C 提案（参考） | 既存 | **L1 提案 authority** | 永続 | `thprop_` / `threlprop_` content id（provenance・created_at・THEME の attached_at を除く） | B7F（`append_proposal` だけ） | 人間の review・decision | 効かない（identity 文は B7D の template、rationale は保存しない） |

## 4. 信頼境界

```
[信頼しない] 出典の文（見出し・要約・題名）──▶ B7C（文は書き換えず、限定面・長さ・制御文字・path・URL・秘密を検査）
[信頼しない] LLM の出力 ──▶ B7B 厳格 parser（schema・未知 field・重複 key・code fence・handle の形式と種別）
                          ──▶ B7D 意味検証（manifest の内部対応表だけで grounding、凍結語彙、上限、template）
[opaque handle] LLM が見るのは EV_ / TH_ / CQ_ / IC_ / REL_ / ENT_ / MON_ だけ。authority id は内部対応表に隠れる
[提案 authority] B7F が再検証して既存 B3 / B5C に L1 提案として追記
[人間の governance] decision・検証（SourceClaimVerification）・実行は B7 の外
```

- **prompt は security 境界ではない**（凍結文言 `PROMPT_IS_NOT_SECURITY`: 「the prompt contract asks; the B7B schema and
  the B7D validator enforce」）。注入文は data 欄にだけ入り、制御効果が無いことを B7G H / H2 が示す。
- B7 に実 provider・network・資格情報への依存は無い（B7G BG: socket・DNS・urlopen・`os.getenv` を塞いでも全経路が通る。
  12 module の source に SDK・network・環境変数の token が無い。import 閉包に SDK が無い: BB）。

## 5. PIT / replay

- cutoff は caller が与える aware な時刻だけ（暗黙の now / latest なし）。knowledge は pin した snapshot だけ（cutoff 後に
  公開された版は `FUTURE_KNOWLEDGE`、最新版への差し替えなし: B7G Q2）。
- **integrity-before-PIT**: 壊れた authority は未来日付の行でも全体を止める（B7C O・B7G AL2）。
- 未来状態の分離: 未来の evidence・Theme observation・governance・B3 / B5C の提案と decision・B5B の assertion を加えても、
  manifest・生成入力・request / attempt id・検証結果・提案 identity は byte 一致（B7C J〜N・B7D AB・B7G S〜X）。
- replay: 同じ manifest ＋ request ＋ prompt contract から byte 一致の生成入力、RecordedProvider は生成入力 digest に束縛
  （別入力に返さない: B7G R）。
- **区別**: 過去時点の入力の再構成（B7C〜B7E は caller の cutoff で決定論的）と、**現在の authority に対する B7F の提出**は
  別物である。B7F は過去時点の提出・backtest の仕組みではない（凍結文言 `SUBMISSION_IS_NOT_A_BACKTEST`、
  `submitted_at` は cutoff 以降: B7G BQ）。LLM 自身の知識は PIT ではないため、B7 の出力を評価・backtest・P5 に使わない。

## 6. identity

| id | 束縛するもの | 変わらないもの |
|---|---|---|
| manifest digest `thllmin_` | visible 部分 ＋ 内部対応表 | path・mtime・入力順 |
| visible digest `thllmvis_` | LLM に見える部分だけ | 同上 |
| request id `thllmreq_` | task・cutoff・prompt contract・出力 schema・manifest digest・knowledge pin | generated_at・provider・model |
| 生成入力 digest `thllmgin_` | request id ＋ 指示 ＋ task contract ＋ visible JSON | 生成監査 journal の内容 |
| attempt id `thllmatt_` | request・生成入力 digest・provider / model / config・generated_at | 応答・結末 |
| 監査 record id `thllmaud_` | 監査 record の全 field | — |
| 検証結果 id `thllmval_` | request・manifest・output digest・pin・plan id の列 | provider・model・generated_at |
| plan id `thllmplan_` | 正規化済み material（handle を解決した ref・凍結語彙・template の文） | LLM の rationale・候補順・provider・model・generated_at |
| 上流 proposal id（plan 内） | B3 / B5C の identity の材料 | 同上 ＋ submitted_at |
| B3 / B5C 提案 id `thprop_` / `threlprop_` | 上流 model の identity payload | provenance（proposer_ref・rule_version・理由）・created_at・attached_at |

意味の提案 identity を変えずに変わってよいもの: **provider・model・generated_at・LLM の rationale の言い換え**・submitted_at。
provider / model / generated_at は attempt id と監査 record id だけを変える。言い換えは output digest を通じて検証結果 id を
変え、その id を参照する provenance の理由文（B3 / B5C の行の bytes）を変えるが、plan id と提案 id は変わらない
（→ CONVERGENT の再利用。B7D U・B7F B・B7G AH）。

## 7. 提案と再利用の意味論（凍結）

| 状況 | 扱い |
|---|---|
| 同じ意味の提案が無い | 既存 `append_proposal` で 1 行（NEW_PROPOSAL_APPENDED） |
| 既存の行と byte 一致 | REUSED（EXACT）。書き込みなし |
| 意味 identity が同じで provenance / created_at だけ違う | REUSED（CONVERGENT）。書き込みなし |
| 同じ id で意味が違う | PROPOSAL_CONFLICT。fail closed（上書き・修復・類似重複なし） |
| 同じ提出の中の重複 | 意味が同じなら DUPLICATE_IN_SUBMISSION（1 回だけ扱う）、違えば PROPOSAL_CONFLICT |

曖昧な意味の dedup・score / rank・自動 merge・自動 decision は無い。言い換えによる準重複は人間の review（§19 B7-DEF-11）。

## 8. SOURCE_ASSERTED（凍結）

- SOURCE_ASSERTED は「出典がその関係を主張した」ことであり、**客観的な真実ではない**。
- B7 はそれを**未検証の提案 material** としてだけ扱う（plan の `source_claim_status` は UNVERIFIED、B5C 提案は OPEN）。
- B7 は SourceClaimVerification を作らない。検証済みを名乗る出力は B7B で拒否（B7G AA）。
- 凍結 B5C 契約が要求する場合、受理の前に人間の SourceClaimVerification が必要（B5C-R1。B7 から迂回できない）。

## 9. Theme evidence の意味論（凍結）

- LLM が作る THEME_CANDIDATE の evidence は **CONTEXT**（B7D の凍結方針）。SUPPORTS に黙って上げない（role の欄は B7B
  schema に無く、付けようとすれば `UNKNOWN_FIELD`: B7G AB）。
- CONTRADICTS / INVALIDATES は提案の意味論だけ。B7 から Foundation を変えない（付与・退役・governance・新しい Theme 状態
  なし: B7D L・B7G AC / AD）。Foundation への反証付与の bridge は無い（§19 B7-DEF-13）。

## 10. 生成監査（凍結）

- 生成監査 journal は追記専用の運用監査 data。raw prompt・raw response・隠れた推論を保存しない（record にその欄が無い。
  B7E Q〜T・B7G BC〜BF）。
- 次の prompt に入れない（B7E AC・B7G AQ）。提案 authority ではない（B7F は読まず書かない: B7G AR）。evidence ではない
  （B7C は生成 record を evidence 入力として拒否: B7E・B7G AP）。
- 必要な監査 record を記録できなければ、正常な B7E 経路は検証済み plan を返さない（NOT_RECORDED。B7E・B7G AL）。
- B7B `LlmGenerationRecord` は凍結のまま残す（削除・転用・journal への移行をしない: B7G BP）。

## 11. 提出の境界（凍結）

- B7F は B3 / B5C をまたいで **ACID ではない**。追記の前に全 plan を pre-flight する（1 件でも失敗すれば書き込み 0 件）。
- 追記を始めた後に失敗したら **PARTIAL_SUBMISSION**。巻き戻し・削除・修復はしない。これは結果に明示される（B7F AG / AH・
  B7G AO）。同じ入力の再提出で収束する。
- 書き込み面は B3 / B5C の提案 journal だけ（新しい journal・authority を作らない）。

## 12. generation_ref の判定

**監督判断: ACCEPTABLE_BOUNDARY。**

- 正常な orchestration は generation_ref を VALIDATED の B7E 生成（journal に記録済みの attempt id）に束縛する（B7G AT）。
- B7F は生成監査 journal を独自に照合しない。
- 偽の単独 ref は provenance も意味の提案 authority も昇格できず、B7F の plan 整合の再検証に縛られる（影響は監査参照の
  文字列だけ）。
- closeout で journal 照合を足さない（§19 B7-DEF-5）。

## 13. 実在しない root の判定

**監督判断: ACCEPTABLE_BOUNDARY ／ DEFERRED_DEFENSE_IN_DEPTH。**

- 正常な B7C → B7D → B7F の流れは未解決の対象を作れない（B7C `THEME_NOT_RESOLVED`、未知 handle `UNKNOWN_HANDLE`、root id の
  直書き `INVALID_HANDLE`: B7G AU）。
- 単独で偽造した構築は、信頼された正常 orchestration の境界の外にある。
- B7F は既存の B3 提案 authority を超える能力を作らない（同じ record は既存 `append_proposal` で byte 一致に書ける）。
- 実行層はすでに未解決の対象を拒否する（B4E `TARGET_NOT_RESOLVED`、B5C `ENDPOINT_NOT_AVAILABLE`）。
- closeout で root lookup を足さない。**将来の提案実行 gate へ持ち越す**（§19 B7-DEF-6 / B7-DEF-16）。

## 14. security と秘匿

- 資格情報: runtime 注入だけの方針のまま（B7 は資格情報を読まない・要求しない・保存しない）。
- 永続面（生成監査 journal・B3 / B5C の行）と提出結果に、raw response・prompt・隠れた推論・LLM の rationale・資格情報・
  machine path・出典の本文（Compass / corpus を模した canary を含む）・portfolio を模した canary が無い（B7G BC〜BF）。
- 例外文と失敗 detail は有界な code だけ（B7B〜B7F の秘匿 test）。
- B7D plan はメモリ上に監査用の `llm_rationale` を持つが、identity 外で永続しない（凍結設計）。

## 15. 凍結の連鎖

| gate | anchor | 凍結対象 |
|---|---|---|
| B6 final | `7a8f8a473e6668a5cc782930dedf262818525b08` | Foundation / B1〜B6 / B3〜B5 runtime |
| B7A | `f5934e8cc45841d8224118244618376cce5ea42d` | architecture / contract audit（文書だけ。runtime 変更なし） |
| B7B | `e2aa991490d2e05dd30fe65bbea3f3ee091be66c` | `llm_proposal_model.py` |
| B7C | `95e04ae48f8e28206437923e36c6386a9a512cd9` | `llm_manifest_model.py`・`llm_manifest_builder.py` |
| B7D | `c240f6823cc5ff3239395ac0711d17c516ebf41c` | `llm_plan_model.py`・`llm_validator.py` |
| B7E | `695227a403e6582849215251c6d1190d48ce3bcd` | `llm_generation_input.py`・`llm_provider.py`・`llm_generation_model.py`・`llm_generation_journal.py`・`llm_generation.py` |
| B7F | `d06dd1b96eedca9902033df52ff80ca9c902a1aa` | `llm_submission_model.py`・`llm_submission.py` |
| B7G | `272b11d7da274dbd45cda1fd3b1d44747c854da4` | E2E 検証（test と文書だけ。runtime 変更なし） |

本 closeout で確認したこと（`test_theme_llm_closeout.py`、24 test）:

- anchor は B6 → B7A → … → B7G → HEAD の一本の祖先鎖。
- 各 gate の runtime 差分は、その gate が宣言した新規 module の追加だけ（B7A・B7G は差分なし）。
- B6 anchor 以降、runtime（src）・knowledge・config・workflow（.github）・scripts・公開出力（docs/pages）・data・
  requirements / pyproject の差分は新規 `llm_*.py` 12 個の追加だけ。B7G anchor 以降は差分なし。
- B7 の 7 文書はそれぞれの anchor で凍結されている。
- 12 module は各 anchor と byte 一致（B7G BH〜BL）。

## 16. 検証台帳

| gate | 目的 | anchor | 新規 test（file・件数） | closure 時の全体 | 増分 | mutation / 敵対的検証 | runtime 変更 | 状態 |
|---|---|---|---|---|---|---|---|---|
| B7A | architecture / contract audit | `f5934e8` | なし | 3227 passed / 2 skipped | 0 | 設計監査（D-B7-1〜12） | なし | CLOSED / FROZEN |
| B7B | 構造化 model / schema | `e2aa991` | `test_theme_llm_proposal_model.py`（256） | 3486 passed / 2 skipped | +259 | 敵対的な schema matrix（mutation campaign の記録なし） | `llm_proposal_model.py` 追加 | CLOSED / FROZEN |
| B7C | PIT 入力 manifest | `95e04ae` | `test_theme_llm_input_manifest.py`（86） | 3573 passed / 2 skipped | +87 | matrix A〜Z（8 family の未来漏れ・破損・security） | 2 module 追加 | CLOSED / FROZEN |
| B7D | 決定論的な意味検証 | `c240f68` | `test_theme_llm_validator.py`（62） | 3635 passed / 2 skipped | +62 | matrix A〜AM、mutation 13 種すべて検出 | 2 module 追加 | CLOSED / FROZEN |
| B7E | offline 生成層 ＋ 監査 journal | `695227a` | `test_theme_llm_generation.py`（79）＋ fixture | 3715 passed / 2 skipped | +80 | matrix A〜AP、mutation 12 種すべて検出 | 5 module 追加 | CLOSED / FROZEN |
| B7F | 提案提出 bridge | `d06dd1b` | `test_theme_llm_submission.py`（62） | 3778 passed / 2 skipped | +63 | matrix A〜BB、mutation 13 種すべて検出 | 2 module 追加 | CLOSED / FROZEN |
| B7G | 敵対的 E2E | `272b11d` | `test_theme_llm_adversarial_e2e.py`（124） | 3902 passed / 2 skipped | +124 | E2E A〜BO ＋ BP / BQ、mutation 17 種・guard 注入 10 種すべて検出 | なし | CLOSED / FROZEN |
| closeout | 最終監査 | （本 commit） | `test_theme_llm_closeout.py`（24） | 3926 passed / 2 skipped | +24 | 凍結台帳 | なし | 本書 |

件数は各 file の現在の収集数、増分は closure 時の全体件数の差（guard 追加を含む。重複して数えない）。**リポジトリの健全性
の最終値は最新の全体結果**:

最終回帰（本 closeout。§19 の順）:

| # | 対象 | 結果 |
|---|---|---|
| 0 | closeout 凍結台帳 | 24 passed |
| 1 | B7G | 124 passed |
| 2 | B7F | 62 passed |
| 3 | B7E | 79 passed |
| 4 | B7D | 62 passed |
| 5 | B7C | 86 passed |
| 6 | B7B | 256 passed |
| 7 | B3 / B5 / Foundation | 678 passed |
| 8 | B6 回帰 / PIT | 727 passed, 2 skipped |
| 9 | theme intelligence 一式 | 2596 passed, 2 skipped |
| 10 | guard / 凍結 pin | 515 passed, 2 skipped |
| 11 | **全体** | **3926 passed, 2 skipped**（closeout 前の 3902 passed / 2 skipped ＋ 本 closeout の 24。回帰なし） |

## 17. mutation と敵対的検証の証拠

- B7D（13 種）: 言い換えの非収束・部分採用・provenance 昇格・template 外の文など（B7D contract）。
- B7E（12 種）: raw response の保存・fence 剥がし / 修復・retry-until-valid・内部 ref の入力混入・B7D 前の VALIDATED・
  journal の入力化・提案 append の到達・非 canonical 行の受理・破損行の読み飛ばし・衝突の追記・記録済み応答の束縛外し・
  監査なしの plan 返却。
- B7F（13 種）: 確認なしの追記・衝突の再利用化・理由 / rationale の改変・HUMAN / RULE 昇格・decision 作成・authority の実行・
  重複行・時刻 / 乱数の identity 混入・新しい journal・衝突後の追記継続・型だけの信用・部分失敗の巻き戻し。
- B7G（17 種、scratch の git clone）: B7B 部分採用・B7C 未来漏れ・B7D 未知 handle の信用・provenance 昇格・B7E 修復 / retry /
  raw 保存 / journal の prompt 化・B7F 確認なし追記 / 衝突の再利用化 / HUMAN decision / authority 実行 / 再検証の迂回 /
  非 VALIDATED の受理・凍結 module の改変（B6 例外の悪用）・network import・隠れた journal。M14 以外は振る舞いの test でも
  検出、M14 は anchor pin で検出。
- guard 注入 10 種（B7G BO）: decision writer・Foundation 追記 API・B5B assertion writer・B6 review writer・provider SDK・
  network・公開出力・隠れた journal 書き込み・未登録 module・journal の生成入力化。

**guard と凍結の監査（§18）**: B7 module は HUMAN decision writer・Foundation の変更・B5B assertion の変更・B6 review の変更・
provider / network SDK・公開 / 通知 / scheduler に到達できない（import 境界 guard 17 test と B7G BB / BO）。**B6 の凍結 pin の
llm 例外はそれだけでは不十分**（commit 済みの B7 module の改変は B6 anchor から見て「追加」なので B6 pin は通る: B7G M14 の
実証で 315 passed）。**その穴は B7 の anchor ごとの byte pin が塞いでいる**。例外は導入時（B7C anchor）から byte 一致で
広げられていない（`test_theme_llm_closeout.py`）。例外を広げない。

## 18. 実データの状態

**B7G 実データ shadow = NOT_RUN（NON_BLOCKING）。** 理由: 検証環境に実 Theme authority が存在しない。production data root・
Windows research root には closeout のために触れない。実 provider を運用で使う前の前提として §19 B7-DEF-2 に持ち越す。

## 19. deferred 登録簿（統合）

分類: NON_BLOCKING_DEFERRED ／ MANDATORY_BEFORE_REAL_PROVIDER ／ MANDATORY_BEFORE_EXECUTION ／ OBSOLETE/CLOSED。
いずれも本 closeout では実装しない。（旧番号は各 gate 文書での番号。B7A 文書の B7-DEF-1〜8 は本表で番号を振り直した。）

| id | 内容 | 出所 | 分類 |
|---|---|---|---|
| B7-DEF-1 | 実 provider 接続（SDK・network・runtime 注入の資格情報・timeout・rate limit・費用） | B7A 旧 DEF-4・B7E #2 | MANDATORY_BEFORE_REAL_PROVIDER（それ自体が別 gate） |
| B7-DEF-2 | 実データ shadow（実 B7C manifest ＋ Recorded / Fake provider・提出なし・read-only） | B7G §19 | MANDATORY_BEFORE_REAL_PROVIDER（B7 closeout には non-blocking） |
| B7-DEF-3 | 再利用（収束・共同発見）の事実を永続しない | B7A 旧 DEF-7・B7F #1 | NON_BLOCKING_DEFERRED |
| B7-DEF-4 | 試行ごとに一意な `generated_at` を保証する caller 契約（違反は JOURNAL_CONFLICT で fail closed） | B7E #5・B7G §11 | MANDATORY_BEFORE_REAL_PROVIDER |
| B7-DEF-5 | generation_ref の独立した journal 照合が無い | B7F・B7G §12 | NON_BLOCKING_DEFERRED（ACCEPTABLE_BOUNDARY） |
| B7-DEF-6 | 実在しない root の多層防御（B7F の root lookup） | B7G §13 | MANDATORY_BEFORE_EXECUTION（将来の実行 gate へ持ち越す） |
| B7-DEF-7 | merge 元と先の root scope の扱い（現在は caller の scope 選択・衝突は fail closed） | B7C #4 | NON_BLOCKING_DEFERRED |
| B7-DEF-8 | 関係の出典帰属の制約（origin_key 帰属・引用元機関を表せない・帰属だけ違う辺の投影重複） | B7D #2・B7C #5 | NON_BLOCKING_DEFERRED |
| B7-DEF-9 | B4 RULE と LLM の同じ CONTEXT 候補が別 id になる（理由の template が違う） | B7D #3 | NON_BLOCKING_DEFERRED |
| B7-DEF-10 | 合成 finding の空の monitoring ruleset version（B7B request が拒否して fail closed） | B7D #7 | NON_BLOCKING_DEFERRED |
| B7-DEF-11 | 言い換え・準重複の意味照合（曖昧 dedup を authority にしない） | B7A 旧 DEF-6 | NON_BLOCKING_DEFERRED |
| B7-DEF-12 | B3 model への LLM provenance 不変条件（多層防御・D-B7-12） | B7A 旧 DEF-1・B7B #8 | NON_BLOCKING_DEFERRED（入れるなら prior phase の最小 hardening gate） |
| B7-DEF-13 | CONTRADICTS / INVALIDATES の実行 bridge が無い | B7A 旧 DEF-2 | MANDATORY_BEFORE_EXECUTION（反証・無効化を実行する gate の前提） |
| B7-DEF-14 | 実世界での LLM の品質・精度の評価 | 新規 | MANDATORY_BEFORE_REAL_PROVIDER（実 provider gate の受入条件。shadow で評価） |
| B7-DEF-15 | provider / model の運用方針（retry・backoff・timeout・rate・費用・model 変更の扱い・raw response の保持を含む） | B7E #3・#4・B7A 旧 DEF-3 | MANDATORY_BEFORE_REAL_PROVIDER |
| B7-DEF-16 | 将来の実行 gate は対象の実在を再検証しなければならない | B7G §13 | MANDATORY_BEFORE_EXECUTION |
| B7-DEF-17 | B5 RR-3 は将来の RelationAssertion 実行に必須のまま | B5 closeout・B7A | MANDATORY_BEFORE_EXECUTION |
| B7-DEF-18 | B7E → B7F の正常 orchestration（VALIDATED ＋ journal 記録済みだけを渡す）を 1 つの関数に成文化する | B7G §21-3 | MANDATORY_BEFORE_REAL_PROVIDER（運用経路で caller の合成に頼らない） |
| B7-DEF-19 | LLM の知識は PIT ではない（B7 の出力を評価・backtest・P5 に使わない） | B7A 旧 DEF-5 | MANDATORY_BEFORE_REAL_PROVIDER（実 provider gate で方針として強制） |
| B7-DEF-20 | B5C store の古い docstring（RR-1） | B7A 旧 DEF-8 | MANDATORY_BEFORE_EXECUTION（B5 closeout の推奨どおり実行 gate の前の単独 patch） |
| B7-DEF-21 | journal 記録失敗時に plan を返さない方針の見直し | B7E #7 | NON_BLOCKING_DEFERRED（現状は安全側） |
| B7-DEF-22 | THEME manifest の mechanism vocabulary は出力 schema 経由で束縛（manifest が直接 pin しない） | B7D #1 | NON_BLOCKING_DEFERRED（食い違いは fail closed: B7G Q） |
| B7-DEF-23 | THEME 候補の consequence ごとの支持（schema 拡張）・`subject_refs` が空 | B7D #4・#5 | NON_BLOCKING_DEFERRED（§9 の方針を維持） |
| B7-DEF-24 | 注釈だけの役割（正規化示唆・説明・dedup 補助）の model | B7B #7 | NON_BLOCKING_DEFERRED |
| B7-DEF-25 | 限定面より広い本文 excerpt の利用（上限・権利確認） | B7C #6 | NON_BLOCKING_DEFERRED |
| B7-DEF-26 | B7B `LlmGenerationRecord` の扱い | B7E #6 | OBSOLETE/CLOSED（監督判断: KEEP FROZEN） |
| B7-DEF-27 | B7B〜B7F の gate 内の後続 gate 向け項目（grounding・check-then-reuse・prompt / provider / journal・提出） | B7B #1〜6・B7C #1〜3・B7D #6・#8・#9・B7E #1 | OBSOLETE/CLOSED（B7C〜B7F で実装済み） |

## 20. 残る blocker

**なし。** blocker 基準（§21）に照らした結果:

| 基準 | 結果 | 証拠 |
|---|---|---|
| L1 の上限を越える | 越えない | B7G A〜C・AV〜AZ・Y / Y2・Z・AC / AD、mutant M4・M10・M11 |
| 決定論的な検証を迂回する | 迂回できない | B7G AS・AT（型・再検証）、mutant M1・M3・M12a / b |
| 未来状態が漏れる | 漏れない | B7G S〜X、B7C J〜N、mutant M2 |
| 凍結 authority を黙って変える | 変えない | 書き込み inventory（B7G AV〜BA）、凍結台帳（本 closeout） |
| 禁止された機微 / raw material を永続する | しない | B7G BC〜BF、mutant M7 |
| 実 provider / network に予期せず届く | 届かない | B7G BB・BG、mutant M15 |
| 凍結契約に B7 を無効にする形で違反する | 違反しない | 全 gate の test と §15 の凍結の連鎖 |

## 21. 推奨

**`P6_B7_COMPLETE / READY_FOR_PHASE6_NEXT_GATE` を宣言し、B7 を CLOSED / FROZEN とする。**

- B7 の runtime 12 module・7 文書・本 closeout 文書を凍結する（以後の変更は remediation gate だけ）。
- 次の gate を開く場合は、その種類に応じて §19 の MANDATORY_* を前提として扱う。

## 22. 次の gate との境界

- **実 provider gate**（B7 の外・監督判断）の前提: B7-DEF-1・2・4・14・15・18・19。B7 の契約（schema・語彙・上限・identity・
  生成入力・厳格 parse・B7D 検証・1 試行 1 呼び出し・raw 非保存・journal の意味論・check-then-reuse）は変えない。provider /
  model 名を意味の契約に入れない。
- **提案実行 gate**（Foundation / B5B への実行・監督判断）の前提: B7-DEF-6・13・16・17・20。人間の decision なしに実行しない。
  実行 gate は plan を信頼せず authoritative record から再導出・再検証する（RR-3・対象の実在確認）。
- 本 closeout の後に新しい能力を始めない。実 LLM / provider の接続・資格情報の要求・HUMAN decision の作成・Foundation /
  B5B への実行・RR-3 の実装・B6 runtime の変更・scheduler / 通知 / 公開出力 / P4 / P5 への接続は行わない。監督レビュー待ち。
