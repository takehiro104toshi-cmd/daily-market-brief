# PHASE 8 / P8-A2C — SUBJECT-SCOPED DUAL-TIME COVERAGE + RETROSPECTIVE RESOLUTION（2 軸の coverage と遡及の解決）

P8-A2C-R1 の設計（監督: R1 選定）と P8-EPOCH1（manifest ＝ 明示の membership authority）に基づき、**A2 を狭く加算で再開**した gate。
主語（Issuer）つきの `ObservationCoverage`、取得の瞬間 `holdings_as_of`、明示の RETROSPECTIVE_PROVIDER_AUTHORITY の入口
（新 module `observation_retrospective_resolver.py`）、manifest による epoch membership、遡及の結果の明示の metadata を足した。
F1 の coverage の生成 ・A3 の遡及の指標 ・PILOT2B ・実 request ・screening は**無い**。

- 基準: P8-EPOCH1 `f764a11fdfc126fa3425ab4cc5e069fa8f6c0ad2`（凍結。runtime 38）。full pytest の基準 6130 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の値 ・会社名を載せない。例はすべて合成。

---

## 0. 結論

1. **2 つの時間軸（R1。混ぜない）**
   - `complete_through` ＝ **世界 ／ 公開の知識**の完全性の境界（「その時刻までに知り得た観測はすべて store にある」）。STRICT_PIT が読む。
   - `holdings_as_of` ＝ **system ／ 取得**の瞬間（「この coverage を支えた COMPLETE な bounded provider 取得をこの瞬間に保持した」）。
     RETROSPECTIVE_PROVIDER_AUTHORITY が読む。STRICT の適格 ・COVERAGE_CONTRADICTION には関わらない。大小の関係を要求しない。
2. **STRICT_PIT は不変**: 凍結 A2 の `resolve` の契約 ・手順 ・直列化は変えていない。既存の caller は STRICT のまま。主語なし ・
   `holdings_as_of` なしの record は byte ・id ともに従来と同一（新しい欄は無いときは直列化に現れない。test で固定）。
3. **主語の範囲**: STRICT の coverage の適格 ＝ dataset が合い、かつ（主語なし **または** 主語 ＝ query の主語）。遡及の適格 ＝ 主語が
   **一致**しなければならない（dataset 全体の legacy の coverage は遡及の provider authority ではない）。COVERAGE_CONTRADICTION も同じ
   主語の規則（Issuer つきの coverage には、その Issuer の観測だけが矛盾できる）。
4. **遡及の入口 `resolve_retrospective(history, query, *, authority_as_of, identity_valid_at, manifests, corrections)`**:
   すべて明示 ・既定なし ・時計なし ・「最新」なし。既存の `resolve()` の契約は触らない。
5. **identity**: 凍結 A1R の `RETROSPECTIVE_AUTHORITY`（`effective_at = identity_valid_at`、`authority_as_of`）。`identity_valid_at` は
   caller が明示に渡す「選んだ epoch の取得の営業日」。period_end から過去の identity を推定しない。A1 ／ A1R は変えていない。
6. **epoch の選択**: dataset ・主語一致 ・data の日（period_end）を覆う ・`holdings_as_of` あり ・`holdings_as_of <= authority_as_of` の
   coverage から **`holdings_as_of` が最大**のもの（`GREATEST_HOLDINGS_AS_OF_NOT_AFTER_AUTHORITY_AS_OF`）。同じ瞬間の coverage が 2 つ
   以上 → `AMBIGUOUS`（候補 ＝ coverage の id）。現在時刻 ・journal の位置は使わない。
7. **manifest の結び付き**: 選んだ coverage の provenance は `jq.acq:<digest>`（ACQ0 の取得）。その取得の authoritative な manifest が
   ちょうど 1 つ（EPOCH1 の store は 1 取得 ＝ 1 manifest を保証）。無い → `MANIFEST_MISSING`、主語 ／ 取得が合わない → `MANIFEST_CONFLICT`。
8. **membership は manifest だけ**: 選んだ manifest の entry（期間 ・区分が query と一致する CANONICAL）の欄 → 観測 id が epoch の
   member。A2 の journal の順 ・知識の時刻 ・`supersedes` の鎖 ・record の作成順 ・現在の A2 の内容から membership を推定しない。
   後から A2 に入った観測は、その epoch の manifest に無ければ見えない。
9. **鎖の規律**: 同じ鎖に member が複数（新しい DiscNo の訂正 ・provider の修正）なら、凍結の鎖（`supersedes`）の順で**member のうち最後**
   を返し、`lineage` は member だけ。member が鎖に無い → `MEMBERSHIP_INVALID`。出所の違う鎖が 2 つ以上 → `AMBIGUOUS`（manifest の
   出所は JQUANTS だけなので実際には到達しない。guard だけ）。
10. **不在の意味**:
    - 期間 ・区分が合う CANONICAL の行は在ったが、その欄は記載なし → `VALUE_ABSENT / FIELD_NOT_REPORTED_IN_EPOCH`。
    - CANONICAL の行が無く、保留（HELD_SEMANTIC ／ UNSUPPORTED）の行が在る → `SEMANTIC_HOLD`（保留の entry は期間を持たないので、
      その期間の行だったかを確定できない。偽の不在を言わないために保守的に保留とする）。
    - CANONICAL の行が無く、NOT_REPORTED_ONLY の行が在る → `VALUE_ABSENT`（同じ理由で保守的）。
    - **`NOT_FOUND`** は「主語つきの epoch が P を覆い ・その取得の authoritative な manifest があり ・一致する canonical ／ 保留 ／ 記載なし
      の membership が無い」ときだけ。意味は「選んだ provider の保持 epoch によれば、この covered な slot に一致する canonical の観測は
      無かった」。「開示が存在しなかった」「市場が知らなかった」ではない。
11. **結果の metadata**: `ObservationResolution` に加算で `resolution_mode` ・`authority_as_of` ・`coverage_epoch_id` ・`interpretation`。
    STRICT では空で、直列化にも現れない（従来の key 集合のまま）。遡及では `resolution_mode = RETROSPECTIVE_PROVIDER_AUTHORITY`、
    `coverage_epoch_id = jq.man:<digest>`（manifest の参照 ＝ membership の authority そのもの。journal の行番号ではない）、
    `interpretation = ACCORDING_TO_PROVIDER_HOLDINGS_AT_AUTHORITY_AS_OF_NOT_A_WORLD_KNOWLEDGE_CLAIM`。`cutoff` 欄には `authority_as_of`。
    `ObservationStatus` に `SEMANTIC_HOLD` ・`VALUE_ABSENT` ・`MANIFEST_MISSING` ・`MANIFEST_CONFLICT` ・`MEMBERSHIP_INVALID` を加算
    （STRICT は返さない。A3 の写像は STRICT だけを消費するので不変）。
12. **訂正 ・修正の 2 軸**（test で固定）:
    - 新しい DiscNo の訂正: それを含まない前の manifest では見えず、含む後の manifest から見える（A2 に両方あっても）。STRICT は訂正の開示日時。
    - provider の修正（EXE-R）: epoch 1 → O1、epoch 2 → O2。遡及は `authority_as_of` で epoch を選ぶ。STRICT は `acquired_at` の前後で O1 ／ O2。
    - 再取得: epoch は違うが同じ観測 id に解く。新しい revision を作らない。
13. **G3 の依存**: A2C は coverage を**消費するだけ**。将来の F1 が period_end P につき `[P, P＋1 日)` の主語つき coverage を、manifest に
    P の CANONICAL の entry が 1 つ以上あるときだけ作る（E4）。本 gate の test は合成の G3 を作る。`complete_through` の規則は F1 の監督
    決定待ち（test では中立な `P＋1 日 00:00`）。遡及の適格は `complete_through` を読まない。
14. **A3**: STRICT のまま。A2C は A3 を呼ばず、A3 は A2C を知らない。遡及の指標は P8-A3-RA（F1 の後）。

---

## 1. 変更

| 対象 | 変更 |
|---|---|
| `observation_model.py`（再開） | `ObservationCoverage.subject_id: str = ""` ・`holdings_as_of: Optional[datetime] = None` ・`applies_to()` ・payload は欄があるときだけ ・`_from_payload` は任意の 2 欄を許す ・`ObservationHistory.check` の矛盾に主語の filter |
| `observation_resolver.py`（再開） | `_coverage` に `applies_to(query.subject_id)` ・`ObservationStatus` に 5 member ・`ObservationResolution` に 4 つの任意の欄（mode があるときだけ直列化） |
| `observation_retrospective_resolver.py`【新規】 | `resolve_retrospective` ・`is_retrospective` ・定数（mode ・interpretation ・epoch の規則） |
| 凍結の test | `test_screener_identity_remediation.py`（A2 の byte guard から再開した 2 path を除く 1 箇所）・`test_screener_acquisition_manifest.py`（consumer の除外 1 箇所）。差は `test_a2c_*` が pin |
| A1 ・A1R ・A2R ・A3 ・ST1 ・ADP0 ・EXE ・ID1 ・ID2 ・LIVE1 ・LIVE2 ・PILOT2A ・ACQ0 ・I1 ・EPOCH1 ・store | 変更なし（EPOCH1 の anchor と byte 一致。A2 の 2 module の差は AST の形で `ObservationCoverage` ・`ObservationHistory` ・`ObservationStatus` ・`ObservationResolution` ・`_coverage` に限る guard） |

---

## 2. 遡及の判定の表

| 状況 | status / diagnostic |
|---|---|
| 主語つきの epoch が無い（legacy だけ） | `OUTSIDE_COVERAGE / NO_SUBJECT_SCOPED_EPOCH`（最初の epoch より前の期間は `BEFORE_COVERAGE`） |
| epoch はあるが全部 `authority_as_of` より後 | `NOT_YET_KNOWN / EPOCHS_AFTER_AUTHORITY_AS_OF` |
| 同じ `holdings_as_of` の coverage が複数 | `AMBIGUOUS / AMBIGUOUS_EPOCH`（candidates ＝ coverage id） |
| coverage の provenance が取得でない ／ manifest が無い | `MANIFEST_MISSING / EPOCH_NOT_BOUND_TO_ACQUISITION ・NO_MANIFEST_FOR_ACQUISITION` |
| manifest の主語 ／ 取得が合わない | `MANIFEST_CONFLICT / MANIFEST_SUBJECT_MISMATCH ・MANIFEST_ACQUISITION_MISMATCH` |
| identity（A1R 遡及）が解けない | `SUBJECT_NOT_RESOLVED`（`identity_status` に A1R の status）。A1R の authority の欠落 ／ 破損はそのまま |
| member が像に無い ／ 主語 ・欄 ・出所 ・期間 ／ 区分が合わない ／ 鎖に無い | `MEMBERSHIP_INVALID / OBSERVATION_*_MISMATCH ・OBSERVATION_MISSING ・MEMBER_NOT_IN_CHAIN`（candidates ＝ その id） |
| CANONICAL の行はあるが欄が記載なし | `VALUE_ABSENT / FIELD_NOT_REPORTED_IN_EPOCH` |
| 保留の行だけ ／ 記載なしの行だけ | `SEMANTIC_HOLD` ／ `VALUE_ABSENT`（`*_IN_EPOCH_WITHOUT_CANONICAL_SLOT`） |
| covered な slot に一致する membership が無い | `NOT_FOUND / NO_CANONICAL_MEMBER_FOR_COVERED_SLOT` |
| 見つかった | `FOUND`（record ＝ member の鎖の最後、lineage ＝ member だけ） |

要求の違反（`authority_as_of` ／ `identity_valid_at` の欠落 ・naive ・順の逆 ・manifest の像 ／ A1R の authority の欠落 ・市場 ／ 予想の
query ・JQUANTS 以外の出所の絞り込み）は `ObservationModelError` で fail closed（status にしない）。

---

## 3. 次の gate

P8-OBS60-F1（fins の COMPLETE 取得 ＋ manifest → 主語つき G3 coverage の生成。`complete_through` の規則の監督決定）→ P8-A3-RA
（遡及の指標。epoch で絞った像を消費）→ P8-PILOT2B。
