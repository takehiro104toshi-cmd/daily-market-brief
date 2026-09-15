# PHASE 4 ENTRY CONTRACT（Phase 3.9.5 最終 gate による凍結・監督者承認事項）

本書は **Phase 3.9.5 の最終 gate closure に伴って凍結された、Phase 4（Morning Brief）の入口契約**である。
Phase 4 の実装は本書の契約を満たす形でのみ開始してよい。

本書は設計事項であり、**変更は監督者（ChatGPT）の決定による**。Claude Code は独自判断で本書を変更しない
（`CLAUDE.md`「設計原則」）。実装は含まない。

- 対象 Phase: Phase 4 = Morning Brief（`docs/rebuild/REBUILD_ROADMAP.md` の P4-1 / P4-2 / P4-3）。
  Prediction Journal（Phase 5）・Theme Map（6）・Narrative（7）・Screener（8）以降は本書の対象外。
- 前提 Phase: Phase 3.9.5（formal human review）。監査証跡は `COMPASS_FORMAL_REVIEW_SPEC.md` §18〜§32。

---

## 1. 用語の凍結（Phase 4 はこの 3 つを絶対に混同しない）

| 用語 | 定義 | Phase 4 での意味 |
|---|---|---|
| **Production Compass DNA** | `knowledge/compass_dna/market_rules.yaml` に登録され、`src/intelligence/compass/market_principles.py` の registry を通して参照できる経験則。`rule_id`（例 `JP_DIR_001`）を持つ | **唯一の authoritative rule DNA。** Morning Brief の投資解釈はここだけを典拠にできる |
| **APPROVED**（formal review state） | 人間が formal review で明示的に承認した Decision state。Decision chain 上の履歴事実 | **人間が検証した分析知識だが rule DNA ではない。** 別レイヤとして扱う |
| **NOT_PROMOTED** | すべての formal Decision が持つ promotion_status。Production DNA を一切変更していないことを示す | Phase 4 は promotion を行わない。読む側も「未昇格」を保持して表示する |
| **Promotion** | APPROVED 知識を Production Compass DNA へ昇格させる将来の別プロセス | **Phase 3.9.5 にも Phase 4 にも存在しない。将来の独立した監督者 gate。** |

凍結文（Phase 4 実装時にこの行を破ってはならない）:

> **APPROVED ≠ Production DNA。APPROVED ≠ PROMOTED。Phase 4 はこの 2 つを collapse させない。**

この境界は既に実装側の宣言としても存在する（`src/intelligence/decision/__init__.py`:
「APPROVED ≠ PROMOTED_TO_DNA（promotion は別 gate。3.9.1 では未実装 = 常に NOT_PROMOTED）」、
`src/intelligence/corpus_research/__init__.py`: 「production Compass DNA … は変更しない。Pattern Registry は
研究 evidence」）。本書はそれを Phase 4 の消費側契約として固定する。

---

## 2. Phase 4 knowledge boundary（読んでよい source の分類）

Phase 4 が触れうる source を 7 + 1 クラスに分解し、権限レベルを与える。

| # | source class | 実体 | 権限レベル |
|---|---|---|---|
| 0 | 市場観測・Evidence 基盤 | Fact Store / Context Snapshot / Market Internals / Market Bank / News Bank | `OBSERVATION`（Phase 1〜3.5 の通常入力。従来どおり） |
| 1 | **Production Compass DNA / frozen rules** | `knowledge/compass_dna/market_rules.yaml`、`market_principles.py` registry | **`AUTHORITATIVE_RULE`** |
| 2 | Formal Decision layer | `compass_decisions/decisions.jsonl`（append-only・hash chain） | `GOVERNANCE_RECORD`（履歴事実。知識ではない） |
| 3 | **APPROVED-but-NOT_PROMOTED pattern** | Decision current state = APPROVED の pattern | **`VALIDATED_REVIEW_KNOWLEDGE`**（rule ではない） |
| 4 | REJECTED pattern | current state = REJECTED | **`NOT_KNOWLEDGE`（消費禁止）** |
| 5 | KEEP_REVIEWING / deferred pattern | current state = KEEP_REVIEWING（progression 上 deferred を含む） | **`UNDECIDED`（承認知識として扱わない）** |
| 6 | raw corpus / research evidence | Compass corpus（PDF 由来 structured record）、`compass_research/*`（pattern registry・DNA comparison） | `RESEARCH_EVIDENCE`（未審査） |
| 7 | replay artifacts | `compass_replay/*`（run id / digest / stability / persistence） | `PROCESS_ARTIFACT`（review 用の検証物） |

### 2.1 現状の実装事実（Phase 4 開始前の時点で既に fail-closed）

以下は実装を読んで確認した事実であり、Phase 4 が「既定で閉じている」ことの根拠である。

- **Morning Brief / Compass generator 系は `decisions.jsonl` も `patterns.jsonl` も読んでいない。**
  `decisions.jsonl` の読み手は `formal_review/`・`review/`・`decision/` のみ。
  `patterns.jsonl` の読み手は `formal_review/`・`evaluation/`・`corpus_research/`・`decision/`・`shadow_review/` のみ。
  `src/intelligence/compass/` 配下にはどちらも現れない。
- **generator が見てよい入力は `EvidencePackage` に限定されている**（`compass/evidence_package.py`:
  「generatorが見られるのはこのpackageだけ（それ以外の情報は存在しない扱い）」）。
- **投資解釈の典拠は Compass DNA registry に限定されている。** `compass/principle_validation.py` は
  `rule_ref` が registry に無ければ `unknown_market_principle` を **error** とし、
  FACTUAL claim が `rule_ref` を持てば `factual_with_principle` を error とする。
  したがって formal review の `pattern_id`（`cpt_…`）を `rule_ref` として通すことはできない。
- **promotion のコード経路が存在しない。** `src/` 配下に `promote` 関数・`PROMOTED` 状態は 1 件も無い
  （`NOT_PROMOTED` のみ）。`knowledge/` へ書き込むコードも存在しない。

Phase 4 はこの状態を**維持**する。緩めるときは本書の改訂（監督者承認）が先。

---

## 3. Phase 4 input contract（Morning Brief が消費してよいもの）

各 class について allowed / authority / provenance / required state / staleness / fallback を定める。

### 3.1 Compass DNA rule

| 項目 | 内容 |
|---|---|
| allowed | **ALLOWED**（Morning Brief の投資解釈の唯一の典拠） |
| authority | `AUTHORITATIVE_RULE` |
| required provenance | `rule_ref`（registry 登録済み rule_id）＋ `market_principle_version` |
| required current state | catalog `status: active`、registry に存在すること |
| staleness | catalog の `version` 不一致は error（`principle_validation` が検出） |
| fallback | 該当 rule が無ければ**解釈を語らない**（rule_ref 無しの含意表現は warning、捏造は禁止） |

### 3.2 APPROVED Formal Pattern（NOT_PROMOTED）

| 項目 | 内容 |
|---|---|
| allowed | **CONDITIONALLY ALLOWED**。ただし Phase 4（P4-1〜P4-3）の既定は **consume しない**（下記 3.8） |
| authority | `VALIDATED_REVIEW_KNOWLEDGE`（**rule DNA ではない**） |
| required provenance | `pattern_id` / `decision_id` / `sequence` / `record_hash` / `actor_type=HUMAN` / `review_mode=FORMAL` / `promotion_status=NOT_PROMOTED` を**全て保持**して表示・記録する |
| required current state | Decision history から**その場で再導出**した current state が `APPROVED` であること（過去行の decision_type を直接読まない） |
| staleness | 消費時点で Decision chain が VALID であること。chain 検証に失敗したら消費しない |
| fallback | 上記のいずれかが欠ければ**存在しない扱い**（決して「承認済み」に丸めない） |
| 禁止 | `rule_ref` として使うこと / Compass DNA と同じ語調・同じ権威で述べること / promotion 済みと読める表現 / `market_rules.yaml` への書き戻し |

### 3.3 REJECTED Formal Pattern

| 項目 | 内容 |
|---|---|
| allowed | **DISALLOWED**（validated knowledge として消費禁止） |
| authority | `NOT_KNOWLEDGE` |
| required provenance | — |
| required current state | — |
| staleness | — |
| fallback | 参照しない。「棄却された」という事実を governance 文脈で述べる以外の用途を持たない |

### 3.4 KEEP_REVIEWING / deferred Pattern

| 項目 | 内容 |
|---|---|
| allowed | **DISALLOWED as knowledge**（審査中であり承認されていない） |
| authority | `UNDECIDED` |
| required provenance | — |
| required current state | — |
| staleness | — |
| fallback | 参照しない。deferred（`DEFERRED_UNCHANGED_KEEP_REVIEWING`）も同じ扱い |

### 3.5 未審査の APPROVE_RECOMMENDED / REJECT_RECOMMENDED Pattern

| 項目 | 内容 |
|---|---|
| allowed | **DISALLOWED**（機械推奨であって人間の承認ではない） |
| authority | `RESEARCH_EVIDENCE` |
| required provenance | — |
| required current state | formal state = NONE のため消費対象にならない |
| staleness | — |
| fallback | 参照しない。**`APPROVE_RECOMMENDED` を `APPROVED` と読み替えることを禁じる** |

### 3.6 raw corpus / research evidence

| 項目 | 内容 |
|---|---|
| allowed | **DISALLOWED for Morning Brief 本文**（Phase 3.7 / 3.8 の境界を維持） |
| authority | `RESEARCH_EVIDENCE` |
| required provenance | 参照する場合も `observation_id` 経由。**PDF 本文 / ファイル名 / ローカル path を出さない** |
| required current state | — |
| staleness | — |
| fallback | 客観市場状態は J-Quants / Market Bank / Fact / Context / Internals を優先（J-Quants First・3.6） |

### 3.7 Replay result

| 項目 | 内容 |
|---|---|
| allowed | **DISALLOWED as brief content**（formal review 内部の検証物） |
| authority | `PROCESS_ARTIFACT` |
| required provenance | 参照する場合は `replay_run_id` / `run_digest` を伴う |
| required current state | `current_compatible = true` |
| staleness | age（captured eligible と current eligible の差）は **warning のみ**。§6 参照 |
| fallback | Morning Brief の主張の根拠にしない |

### 3.8 Phase 4 既定（fail-closed default）

> **Phase 4（Morning Brief P4-1〜P4-3）の既定は「class 0 と class 1 のみを消費する」。**
> class 2〜7 は既定で consume しない。class 3（APPROVED）を実際に使うのは、本書 3.2 の provenance 要件を
> 満たす表示設計が監督者に承認された後に限る。

### 3.9 fail-closed consumption rule（凍結）

Phase 4 の consumption は **default deny** とする。

1. 既定は「読まない」。本書で ALLOWED と明記された class のみ読める。
2. ある pattern の知識を使う条件は **current state を再導出して `APPROVED` であること**。
   履歴行の `decision_type` を直接読んで判断しない（`REOPENED_FOR_REVIEW` / `SUPERSEDED` / `RETIRED` を取り違えるため）。
3. state が判定できない・chain が VALID でない・provenance field が欠ける場合は、
   **「未承認」ではなく「存在しない」として扱う**（欠落を承認に丸めない）。
4. `APPROVE_RECOMMENDED` は承認ではない。`KEEP_REVIEWING` は承認ではない。`REJECTED` は知識ではない。
5. Phase 4 のどの経路も **Compass DNA を書かない**。`knowledge/` への書き込みを追加しない。
6. Phase 4 のどの経路も **promotion を実行しない**。promotion 相当の state・flag・metadata を新設しない。
7. 上記に反する必要が生じたら、実装ではなく**本書の改訂提案**を出して停止する。

---

## 4. APPROVED ≠ PROMOTED の凍結（Task D）

- **APPROVED** = 人間が formal review で検証した状態。Decision chain 上の履歴事実。
- **NOT_PROMOTED** = Production DNA を一切変更していない。全 Decision 行に付く不変値。
  `promotion_status` は書き込み経路で無条件に `NOT_PROMOTED` が設定され（`formal_review/service.py`）、
  policy でも凍結される（`formal_review/config.py`: promotion boundary is frozen）。
- **Promotion** = 将来の独立した監督者 gate。**Phase 3.9.5 の closure には含まれない。**
  必要になった時点で別 Phase として設計する（本書はその存在を予約するだけで、要件も日程も定めない）。

Phase 4 実装時に「APPROVED なのだから DNA に入れてよい」と判断してはならない。それは promotion であり、
別 gate である。

---

## 5. remaining queue policy（Task E）

- Phase 3.9.5 の formal review は **代表性（representative coverage）で閉じる**。
  **全候補の審査完了は Phase 4 の前提条件ではない。**
- したがって queue には以下が残ってよく、いずれも Phase 4 を block しない。
  - 未審査の `APPROVE_RECOMMENDED`
  - 未審査の `REJECT_RECOMMENDED`
  - deferred の `KEEP_REVIEWING`（現時点では Candidate #2 = `cpt_8c96e2070cd4c702`）
- Formal Review は「Phase 4 前に使い切る前提条件」ではなく、**継続的な分析ガバナンス process** として
  Phase 4 以降も並行して続く。
- 残候補は Phase 4 の入力にならない（本書 3.5）。未審査であること自体が Phase 4 のリスクにならない。

---

## 6. replay age と Phase 4 entry（Task F）

現状: captured eligible 139 / current eligible 144 / age 5 / `W_REPLAY_EVIDENCE_AGE` / compatible = true。

凍結 policy と実装を読んだ結果:

- formal review の replay gate は `action in replay_evidence_required_for` のとき
  **`available` と `current_compatible` のみ**を検査する（`formal_review/guard.py`）。**age は検査しない。**
- age は `replay_evidence_age_warning_eligible_docs`（既定 5）を超えたときに
  `W_REPLAY_EVIDENCE_AGE` を**警告として出すだけ**で、blocking guard ではない
  （`formal_review/warnings.py`。blocking 一覧にも含まれない）。
- replay artifact の消費者は `formal_review/` と `replay/` 自身だけであり、
  **Morning Brief / Compass generator 系は replay を読まない。**

結論: **Phase 4 entry は replay の再生成を要求しない。** Phase 4 側に replay freshness への具体的依存は無い。
したがって「見た目を揃えるため」だけの再生成は行わない（本ターンでも行っていない）。

将来 replay freshness が必要になる具体条件（参考・要件ではない）: 新たな formal Decision を書くときに
`current_compatible` が false になった場合、または replay を Phase 4 の表示内容に使う設計が承認された場合。
そのときは実行前に報告する。

---

## 7. Phase 4 entry checklist（凍結）

Phase 4 実装着手前に、以下が**すべて**満たされていること。

| # | 項目 | 判定根拠 |
|---|---|---|
| 1 | Phase 3.9.5 CLOSED | 監督者 gate 決定 + 最終 Windows read-only 検証 |
| 2 | Decision chain VALID | 8 行 / seq 1..8 / hash chain / 全行 HUMAN・FORMAL・NOT_PROMOTED |
| 3 | formal_review policy digest 凍結 | `d2fb015ca827dd15`（policy 1.1.0）。6 層とも凍結値 |
| 4 | APPROVED / NOT_PROMOTED 境界の凍結 | 本書 §1・§4 |
| 5 | Phase 4 input contract 凍結 | 本書 §3（default deny） |
| 6 | hidden auto-promotion が無いこと | `src/` に promote 経路・`PROMOTED` state が存在しない |
| 7 | Candidate #2 の deferred 状態を理解していること | `DEFERRED_UNCHANGED_KEEP_REVIEWING`。Phase 4 では消費しない |
| 8 | 残 queue が non-blocking であること | 本書 §5 |
| 9 | corpus milestone が CORPUS_100 であること | `corpus/milestones.py`（100 = Compass DNA v2 review target） |
| 10 | Phase 4 は Morning Brief として始まること | P4-1 三段組版 / P4-2 Market Signal / P4-3 配信。予測・テーマ・物語・スクリーナーは Phase 5 以降 |

チェックリストのどれかが崩れたら Phase 4 実装を開始しない。

---

## 8. 本書の変更手続き

- 本書は監督者の設計決定である。Claude Code は**変更せず提案のみ**行う。
- Phase 4 実装が本書の契約に収まらないと判明した場合、実装を進めずに停止し、改訂提案を出す。
- 本書は Decision data・policy digest・Compass DNA を一切変更しない（documentation only）。
