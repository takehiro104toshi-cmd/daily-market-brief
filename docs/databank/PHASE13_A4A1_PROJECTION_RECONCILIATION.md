# PHASE 13 — A4a1: PROJECTION CONTRACT RECONCILIATION（public ／ private の identity の分離 ・frontmatter ・中断の staging）

凍結の P12.5-A0 と凍結の P13-A4a の 2 つの本物の衝突（frontmatter ・中断した公開の収束）と、A4a が公開の Markdown に出す digest の
逆算の可能性を、後継の純粋な契約 `src/intelligence/market_memory/projection_contract.py` で調整する（P13-A4a1）。I/O ・filesystem ・
vault ・network ・process ・時計 ・資格情報 ・scheduler は無い。A4a の 0.1.0 の model（`memory_projection.py` ・`P13_A4A` ＝
`bc7f990df2ae8983a27a1d02b1f8a0a1738c5dd1`）は byte 一致のまま凍結し、変えない（登録の規則が runtime の修正を決して認めないため ・後継の
追加だけ）。A1（`P13_A1` ＝ `ccfc8e57885fabc5936a39034a9e816c66b2fbbc`）・A2a（`P13_A2A` ＝ `12de956637bb1df5fcff8846ba9d7fcb606421a3`）・
A3（`P13_A3` ＝ `12dcfb2143527ca44a3e55afa7a2daa9bab2c33d`）・A4a の blob は HEAD ・index ・作業木で pin する。B-track は HOLD ・P14 は未着手。
本記録は A4b の実装を承認しない。A4b は後継だけを使い、0.1.0 の model を import しない。

| 項目 | 値 |
|---|---|
| runtime（登録 ・認可: gate `P13-A4a1` ・anchor `P13_A4A`） | `src/intelligence/market_memory/projection_contract.py` |
| import | stdlib `__future__` ・`dataclasses` ・`enum` ・`json` ・`re` ・`typing` と、相対の `.canonical` ・`.memory_generation` ・`.memory_projection`（承認した不変の定数 ・固定の文 ・走査 ・error の class だけ）・`.review_state_change` ・`.review_state_sample` |
| 版 | note `p13_memory_projection:0.2.0` ・規則 `p13_projection_rules:0.2.0` ・pointer `p13_projection_pointer:0.2.0` ・public な export の manifest `p13_projection_public_export:0.2.0` ・private な binding `p13_projection_binding:0.2.0` ・intent `p13_projection_intent:0.2.0` ・完了 `p13_projection_completion:0.2.0` ・中止 `p13_projection_abort:0.2.0` |
| domain | `p13.projection_public_version.v2` ・`p13.projection_public_note.v2` ・`p13.projection_public_export.v2` ・`p13.projection_pointer_slot.v2` ・`p13.projection_binding.v2` |

## 1. digest の privacy（J3）: hash は秘匿ではない

A4a の 0.1.0 は標本 ・区間 ・generation ・A3 の manifest ・投影 ・export の完全な digest と 24 hex の略記を公開の note ・file 名 ・link に
出した。これらの入力の entropy が低いと、**候補の列挙**で逆算できる（合成の値での実演 ・調査の報告に記録）:

- 空の標本の digest から、cutoff の正確な瞬間と、export しない人の窓（review の先読みの日数）が数万の候補 ・数秒で戻る。
- cutoff が 1 つの generation の digest から、項目を知らなくても cutoff の瞬間が秒の精度で戻る（公開した標本の digest と日付を使う）。
- 計画の digest は cutoff の瞬間と定数だけに依るので常に戻る。投影 ・export の digest は上の digest の公開の関数で、秘匿を足さない。
- 24 hex の略記は推測の確認に完全な digest と同じだけ役に立つ。項目が少ない標本は、発行体の id の候補 ・作成の瞬間の列挙で発行体を推論できる。

従って **0.1.0 の出力が公開に安全だったとは主張しない**（実際の vault への export は一度も行われていない ・A4b は未実装）。

**後継の規則**: public の identity は公開する欄だけから導く。public の digest を逆算して得られるのは、既に note に印字した値だけ。

| 面 | 内容 |
|---|---|
| public な版の digest（`build_id`）| 承認した公開の model（schema ／ 規則の version ・adapter ／ view の schema の version ・標本の序数 ・cutoff の日 ・承認した件数と分類の件数 ・区間の序数 ・2 つの日 ・件数）だけの正準 digest |
| public な note の identity（`item_id`）| public な版の digest ・note の種類 ・序数だけ（接頭 `p13pvn_` 版の index ・`p13psm_` 標本 ・`p13piv_` 区間）|
| pointer の slot の identity | `p13ptr_` ＋ pointer の schema ・規則 ・note の名前だけの定数（指す版 ・source に依らない）|
| public な export の digest | 版の folder の note の名前 ・長さ ・sha256（公開の byte）と public な版の digest ・最後の日だけ |
| file 名 ・link | `p13pvn_<24>` ・`p13pvn_<24>-s001` ・`p13pvn_<24>-i001` ・`p13-memory`（序数 ・public な版の digest の略記だけ）|
| private だけ | generation ・A3 の manifest ・計画 ・標本 ・変化の digest ・`PrivateBinding`（public な版 ／ export と、検証した generation ／ manifest の完全な digest の結び付き）|

**正の検査**（拒否の一覧ではない）: 全ての note で、16 hex 以上の列は全て「その note の公開の欄から再計算できる値」（public な版の
digest ・note の identity ・pointer の slot ・public な export の digest ・それらの 24 hex の略記）でなければならない。`parse_public_version`
は note だけから public な model を再構成し、描画し直した byte との完全一致と public な版の digest の一致を要する（公開の欄だけから
再計算できることの証明）。描画の関数は public な model だけを受け、private な属性を読まない（boundary の AST の guard）。

**限界**: この仕組みが防ぐのは **digest を介した漏えい** であり、公開する値そのもの（件数 ・日付が語ること）からの推論を含む
**全ての推論を防ぐものではない**。秘密 ・暗号 ・乱数の label は無い（J8）。鍵つきの導出は将来の別の gate。

## 2. frontmatter（J1 ・J4 ・J5）と P12.5-A0 からの限定した逸脱

全ての値を quote する（§6.3）。種類ごとの鍵の列の順序つきの完全一致:

```
p13_schema ・p13_rules ・p13_note ・generated ・authority ・item_id ・build_id ・p13_build_basis ・as_of ・p13_as_of_basis ・
known_at ・acquisition_time ・p13_provenance ・p13_source_ref ・（標本 ／ 区間）p13_ordinal ・（pointer）p13_export
```

- **`generated: "true"`（J1）**: §6.1 の表記 `generated: true` と §6.3 の「frontmatter の値は quote する」は文字どおりには両立しない。
  後継は quote した **文字の値** `"true"` とする（YAML の真偽ではない）。§6.3 の明示の規則に従う限定した解釈であり、§6.1 の型を YAML の
  真偽として要求する条文は凍結の文書に無い。
- **`authority: "DERIVED"`**。
- **`item_id`（J4）**: 生成した note を識別する（source の事実 ・private な authority の record の identity ではない）。§5.4 の `p13mem_`
  の式は `MemoryItem` のためであり使わない。
- **`build_id`（J5）**: public な export の build の identity（＝ public な版の digest）。private な Memory Store の build ・計画の identity
  ではない（Memory Store の build ・計画の identity ではない ・それらは計画の digest の逆算のため公開しない）。`p13_build_basis:
  "PUBLIC_EXPORT_BUILD_IDENTITY_PRIVATE_MEMORY_BUILD_WITHHELD"` がそれを明記する。
- **`as_of`**: 日だけ（瞬間ではない）。`p13_as_of_basis` が何の日かを明記する: 版の index `GENERATION_FINAL_CUTOFF_AS_OF_DATE` ・標本
  `SAMPLE_CUTOFF_AS_OF_DATE` ・区間 `INTERVAL_THROUGH_CUTOFF_AS_OF_DATE_NOT_TRANSITION_TIME` ・pointer `POINTED_VERSION_FINAL_CUTOFF_AS_OF_DATE`。
  標本の cutoff の日を source の known_at ・取得の時刻 ・遷移の時刻と同一視しない。
- **`known_at: "NOT_AVAILABLE"` ・`acquisition_time: "NOT_AVAILABLE"`**: この族は source の known_at も取得の時刻も持たない（P12.5-A0 §5.3 ・
  §6.4 の「明示」を、無いことの明示で満たす ・捏造しない）。`p13_provenance` は A1 の provenance の class（source の known_at と P10 の
  revision の digest が無いこと）。
- **`p13_source_ref: "PRIVATE_EVIDENCE_ONLY"`（J2）— 限定した逸脱**:
  - 影響を受ける条文: P12.5-A0 §6.1「source の参照（id と digest）を持ち」と、§7 の「digest は出してよい」。
  - 理由: source の digest は低い entropy の private な入力の関数であり、§1 の実演のとおり公開すると逆算できる。
  - 範囲: Review State Memory の投影の public な note だけ。実際の source の id と完全な digest は `PrivateBinding` ・private な証拠に在る。
  - **文字どおりの充足ではない**（§6.1 を文字どおりに満たすとは主張しない）。§7 の「digest は安全」は高い entropy の内容にだけ成り立つ。
  - 将来の調整: 鍵つきの導出 ・private な参照の解決の面などの別の gate で、P12.5-A0 の source の参照の要件との **将来の調整** を要する。

## 3. 公開が同じ入力と provenance（J6）

公開の欄が同じ 2 つの generation（cutoff の瞬間 ・項目の id ・人の窓だけが違う）は byte 一致の public な出力になる。分類は
`NO_CHANGE` であり、新しい private な binding が未記録なら `RECORD_PRIVATE_BINDING`（private な証拠だけへの追加 ・vault は不変）を提案し
`target_binding_recorded` を偽にする（provenance が同じとは主張しない ・新しい private な証拠を黙って捨てない）。記録の後は `NO_CHANGE` ・
`NONE`。追加の binding は完了した版にだけ結べる（それ以外は `UNREFERENCED_BINDING`）。前の公開と同じでない既知の版への戻しは HOLD。

## 4. 中断した staging の継続 ・明示の保存（純粋な提案だけ）

| staging の観測（検証済みの開いた intent ・manifest） | 状態 | 提案 | 適格 |
|---|---|---|---|
| 無い | INTENT_PREPARED | STAGE_VERSION（対象が要る） | 自動 |
| 空 ・byte 一致の厳密な部分集合 | STAGING_PARTIAL_VERIFIED | CONTINUE_STAGING（足りない file の排他の作成だけ ・在る file は触らない） | 自動（対象が要る） |
| 完全 ・byte 一致 | STAGED_VERIFIED | MOVE_STAGED_TO_VERSION | 自動 |
| 期待の名前の file が対象の byte の厳密な接頭（長さ 0 を含む） | STAGING_TORN | PRESERVE_STAGING | 明示の保存だけ |
| 改竄（接頭でも完全でもない） | FAIL_CLOSED | STAGING_TAMPERED | HOLD |
| manifest に無い名前 | FAIL_CLOSED | STAGING_FOREIGN_ENTRY | HOLD |
| 対象が無く不一致を区別できない | FAIL_CLOSED | STAGING_UNVERIFIED | HOLD |
| staging と空でない版の両方 | FAIL_CLOSED | AMBIGUOUS_STAGING_AND_VERSION | HOLD |
| 完全な staging ＋ 開いた intent の空の版（POSIX の予約） | VERSION_RESERVED_EMPTY | PRESERVE_EMPTY_RESERVATION | 明示の保存だけ |
| 空の版 ＋ 不完全 ／ 無い staging ・完了した版の空 | FAIL_CLOSED | VERSION_UNVERIFIED | HOLD |
| 中止した intent の staging（在る file は全て byte 一致 ・未知の名前は無い） | STAGING_OF_CLOSED_INTENT | PRESERVE_STAGING | 明示の保存だけ |
| 中止した intent の切れ ／ 改竄 ・完了した intent の staging ・intent の無い staging | FAIL_CLOSED | STAGING_OF_CLOSED_INTENT ／ ORPHAN_STAGING | HOLD |

`check_preservation_proposal` は観測を分類し直し、明示だけの適格 ・ちょうど次の遷移 ・対象が staging か空の予約 ・保存の後の状態が
FAIL_CLOSED でないことを要する。保存の対象は決して **前の有効な版** ではない（有効な版は 1 つ以上の file と完了の record を持つ）。
壊れた公開の pointer ・変えられた公開の note ・未知の entry ・壊れた証拠は HOLD のまま。前の有効な版を消す ・上書きする ・移す ・
archive する action は存在しない。実行（排他の作成 ・置き換えない移動 ・interrupted への保存）は A4b。

## 5. 版 ・互換（0.1.0）

後継の schema ／ 規則は 0.2.0。0.1.0 の note ・pointer ・manifest は受けない（変換しない ・fail closed）。0.1.0 の model は byte 一致のまま
残る。実際の vault の移行は認めない。A4a1 は A3 の store の読みを証明しない（`SOURCE_ATTESTATION` ＝
`A4A1_RECHECKED_RECORD_BYTES_STORE_READ_NOT_ATTESTED` ・A4b が A3 の公開の読み `MemoryStore.read_generation` で確立する）。

## 6. 試験（合成の値だけ）

- `test_market_memory_projection_contract.py`: 再利用の面 ・明示の完全な digest ・種類ごとの frontmatter の完全一致 ・counts-only ・
  private な digest とその 16 hex 以上の部分列の不在（note ・名前 ・link ・pointer ・public な manifest）・正の hex の検査 ・note だけからの
  public な digest の再計算 ・候補の列挙の回帰（瞬間 ・窓 ・項目 ・発行体を変えても public な digest は不変 ・照らす相手が無い）・偽の
  public な digest ・private な binding の注入 ・frontmatter の型 ／ 鍵 ／ 値 ・0.1.0 の拒否 ・決定論 ・公開が同じ入力の NO_CHANGE と
  binding の記録 ・部分の staging の継続 ・切れ ／ 改竄 ／ 未知 ・空の予約 ・閉じた intent ・保存が公開の版を狙わない ・HOLD ・I/O の不在。
- `test_market_memory_boundary.py`: 認可 ・registry の digest ・A1 ／ A2a ／ A3 ／ A4a の blob の pin ・後継の import ・再利用の名前の完全一致 ・
  描画の private な読みの不在 ・公開の面 ・本記録の guard ・負の control。
