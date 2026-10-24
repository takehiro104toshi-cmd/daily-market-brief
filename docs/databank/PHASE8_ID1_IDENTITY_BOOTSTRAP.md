# PHASE 8 / P8-ID1 — J-QUANTS IDENTITY BOOTSTRAP（機械の提案 → 人の審査 manifest → 登録 plan。A1 に書かない）

実の J-Quants の観測が Phase 8 に入る前に要る identity の bootstrap の手順を、**A1 の store を変えずに**実装した gate。監督の決定 D1
（P8-A3R §4。凍結）に従う: 機械の候補 → 人の審査の manifest → A1 の登録。本 gate は前の 2 段と「登録 plan の導出」までで、
**登録（A1 への append）は行わない**。合成の master の行だけ。live の J-Quants request は無い。

- 基準: P8-EXE `5ec466b773e696d6084533bbf25d252cd09996bb`（凍結。runtime 23 module）。full pytest の基準 5752 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の code の一覧を載せない。例はすべて合成。
- 語: 監督の指示の「candidate（候補）」は、本 repo の語彙の guard（`candidate` は screening の語として禁止）に合わせて **`Proposal`（提案）**
  と実装している。意味は同じ（機械が作る審査の対象。authority ではない）。

---

## 0. 結論

1. 追加した runtime は 2 module: `identity_bootstrap_model`（入力 ・提案 ・manifest ・審査 ・plan の型）、`identity_bootstrap`
   （`propose_bootstrap` ・`review_manifest` ・`plan_registration`。純関数）。先行の 23 module は byte 一致。
2. **authority の境界**: provider の code は provider の識別子（A1 の `IdentifierAssignment(JQUANTS_CODE)` になる）で、canonical の identity
   ではない。`IssuerId(Code)` ・`SecurityId(Code)` は無い。canonical の id は凍結 A1 の `derive_issuer_id` ／ `derive_security_id` に
   anchor `p8boot<n>:iss.<Code>` ／ `p8boot<n>:sec.<Code>` を渡して導く（A3R §4.2）。anchor は承認の後は不変の token で、後の provider の
   data から計算し直さない（別の一括 ＝ 別の anchor ＝ 別の id）。
3. 機械の提案 ・manifest ・登録 plan は **DERIVED ・NON_AUTHORITY ・NON_PERSISTENT**。A1 ・A2 ・注記 ・保留の store に書かない。
   filesystem に触れない（manifest の直列化は `as_dict` ／ `from_dict` の純関数。書く場所は caller が決める）。
4. 人の審査 `ReviewedManifest`（reviewer は `HUMAN` だけ）が登録の前に要る authorization の artifact。審査は manifest の digest と各提案の
   digest に結びつき、内容が変われば失効する。自動の承認 ・既定の承認 ・古い承認の再利用 ・暗黙の繰り越しは無い。
5. D0 は caller が明示に渡す（`BootstrapBatch.d0`）。時計を読まない。有効時間 ・coverage は D0 から（`[D0, D0＋1 日)`）。D0 より前を作らない。
6. 適格は保守的（§4）。曖昧 ・不整合 ・支えない物は提案にせず、保留 ／ 人の審査 ／ 再利用 ／ 衝突として manifest に載せる。名前 ・類似で結ばない。
7. code の変更 ・廃止 ・再上場 ・複数の上場物 ・Issuer と Security の関係の食い違いは **HUMAN_REVIEW_REQUIRED**（§10）。
8. P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION** のまま（§12）。
9. 判定: **P8_ID1_IDENTITY_BOOTSTRAP_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§14）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `5ec466b773e696d6084533bbf25d252cd09996bb`（期待どおり。working tree は clean） |
| 凍結の anchor | A1 `4162e9c` ／ A1R `e6a750f` ／ A2 `b686b00` ／ A2R `4d3540c` ／ A3A `84c2d52` ／ A3B `d8845f2` ／ A3R `f1c4a4e` ／ ST1 `e831996` ／ ADP0 `a2ccc1c` ／ EXE `5ec466b` と byte 一致 |
| full pytest の基準 | 5752 passed ／ 2 skipped |

---

## 2. 変更の範囲（不変の宣言）

| 対象 | 状態 |
|---|---|
| `src/intelligence/screener_intelligence/identity_bootstrap_model.py` | **新規** |
| `src/intelligence/screener_intelligence/identity_bootstrap.py` | **新規** |
| `tests/intelligence/test_screener_identity_bootstrap.py` | **新規**（27 test） |
| `tests/intelligence/phase8_runtime_registry.py` ・`test_screener_intelligence_boundary.py` | ID1 の登録 ・EXE の anchor の guard |
| 先行の 23 module ・Phase 8 の test 9 file ・先行の記録 18 | **byte 一致**（guard `test_id1_*`） |
| A1 の model ・store | **無変更**（A1 は要る record をすべて表せた。`P8_A1_IDENTITY_MODEL_BLOCKER` は無い） |
| `main.py` ・Pages ・config ・workflow ・Secrets ・legacy ・P4/P5 ・P6 ・P7 ・Production DNA | 変更なし |

---

## 3. 入力の契約（`MasterRow`）

| 規則 | 内容 |
|---|---|
| 読む欄（5） | `Date`（snapshot の情報適用日）・`Code`（5 桁）・`CoName` ・`CoNameEn`（空を許す）・`Mkt`（市場区分の code） |
| 公式に観測された他の欄（9） | `MktNm` `Mrgn` `MrgnNm` `ProdCat` `S17` `S17Nm` `S33` `S33Nm` `ScaleCat` → 受けるが**捨てる**（model に無い ・digest に入らない） |
| 公式の一覧に無い key | `PROVIDER_FIELD_UNKNOWN`（schema のずれを黙って通さない） |
| 型 ・境界 | 文字列 ・120 文字まで ・制御文字なし ・credential の印なし。違反は `BootstrapInputError`（HOLD ではなく拒否） |
| raw の行 | 保持しない。provider の record の参照は `jq.eq_master:<Code>.<Date>:<digest24>`（5 欄の正準 JSON の sha256） |

出所: A3R §4.1 ・real data mapping audit（repo の research）。公式の master には上場日 ・廃止日 ・code の変更 ・発行体の識別子が無い。

---

## 4. 適格（保守的）

| 場合 | 扱い | 理由の code |
|---|---|---|
| 5 桁 ・数字 ・5 桁目 `0`（公式 FAQ: 普通株）・名前あり ・支える市場 ・Date ＝ D0 | **PROPOSED**（1 Issuer ＋ 1 Security） | — |
| 形が違う code（桁 ・小文字 ・空） | HELD | `CODE_MALFORMED` |
| 5 桁目 ≠ `0` ・英字を含む（優先株 ・他の種類） | HELD | `CODE_NOT_COMMON_EQUITY` |
| 同じ code に内容の違う行 | HELD（どちらも採らない） | `CODE_CONFLICTING_ROWS` |
| 行の `Date` ≠ D0 | HELD | `SNAPSHOT_DATE_MISMATCH` |
| `CoName` が空 | HELD | `NAME_MISSING` |
| `Mkt` が caller の支える一覧に無い | HELD | `MARKET_UNSUPPORTED` |
| 同じ先頭 4 桁を別の数字 code と共有（複数の上場物 ／ 1 発行体の複数の Security の疑い） | HUMAN_REVIEW_REQUIRED | `MULTIPLE_LISTINGS_SUSPECTED` |

byte 一致の重複の行は収束する。名前 ・類似 ・fuzzy matching は使わない。支える市場区分の一覧は caller が明示に渡す（既定なし）。

---

## 5. D0

`BootstrapBatch(batch_id, d0: date, supported_markets)`。`d0` は `date` 型だけ（datetime ・文字列 ・省略は拒否）。有効時間の起点は
D0 の始まり（JST）。coverage は `[D0, D0＋1 日)`（A3R §4.2 B5）。D0 より前の identity ・coverage ・上場は作らない。提案の `d0` は一括の
D0 と一致しなければ manifest にならない。D0 より前の cutoff での解決は `FOUND` にならない（test）。

---

## 6. 機械の提案（`IdentityProposal`）

| 欄 | 内容 |
|---|---|
| Issuer | `issuer_anchor = <batch>:iss.<Code>`、`issuer_id = derive_issuer_id(anchor)` |
| Security | `security_anchor = <batch>:sec.<Code>`、`security_id = derive_security_id(anchor)`、`issue_class = COMMON_EQUITY` |
| provider の識別子の結びつき | `code`（→ `IdentifierAssignment(JQUANTS_CODE, effective_from=D0)`） |
| 表示名 | `name_ja`（`CoName`）・`name_en`（`CoNameEn`。空を許す） |
| 市場 | `market`（`Mkt`。A1 の venue は `TSE` だけ。区分は provenance の参照で追える） |
| 出所 | `provider_record_ref` ・`provider_record_digest` |
| 版 | `rules_version = p8_identity_bootstrap:0.1.0` |
| identity | `digest`（内容の正準 JSON の sha256）・`proposal_id = p8prop_<digest24>` |

model が anchor ・id の整合を検査する（anchor と違う id を渡せない）。投資の欄 ・財務 ・価格 ・Theme ・score は無い。

---

## 7. manifest（`BootstrapManifest`）

`schema_version = p8_bootstrap_manifest:0.1.0`、一括（id ・D0 ・支える市場）、提案（code 順）、`proposal_digests`、審査の項目
（保留 ・人の審査 ・再利用 ・衝突。code 順）、規則の版、authority の class、`manifest_digest`（内容の sha256）。入力の行の順序は digest に
影響しない。`from_dict` は digest が一致しなければ `MANIFEST_DIGEST_MISMATCH` ／ `PROPOSAL_DIGEST_MISMATCH` で拒む（fail closed）。
直列化の場所は caller が決める（自動の既定の path は無い。test は tmp_path）。raw の行 ・credential は含まれない。

---

## 8. 人の審査（`ProposalReview` ・`ReviewedManifest`）

| 規則 | 内容 |
|---|---|
| disposition | `APPROVE` ／ `REJECT` ／ `DEFER`（閉じた語彙） |
| reviewer | `HUMAN` だけ（他の値は拒否） |
| 結びつき | `proposal_id` ＋ `proposal_digest`（一致必須）。`ReviewedManifest.manifest_digest` は manifest と一致必須 |
| note | 境界つきの短文（200 文字 ・制御文字なし ・credential の印なし）。identity を運ばない |
| `accepted_at` | 審査の受理の時刻（caller が明示。aware）。登録 record の `known_at` になる |
| 部分の審査 | 許す。review の無い提案は **未審査 ＝ 権限なし**（plan で `NOT_REVIEWED`） |
| `reviewed_digest` | 内容（manifest の digest ・reviews ・accepted_at ・reviewer）の sha256 |

自動の APPROVE ・既定の承認は無い（`review_manifest` に reviews を渡さなければ何も承認されない）。

---

## 9. 古い審査からの保護

- 提案の内容が変われば digest が変わり、`review_manifest` は `REVIEW_TARGET_UNKNOWN` ／ `STALE_REVIEW`、`plan_registration` は
  `MANIFEST_DIGEST_MISMATCH` ／ `STALE_REVIEW` で拒む。
- manifest が変われば（提案の追加 ・削除）`manifest_digest` が変わり、古い `ReviewedManifest` は使えない。同じ内容の提案には新しい
  manifest の下で**結び直す**（新しい `reviewed_digest`）。「最新が勝つ」「best effort」「部分の黙った繰り越し」は無い。

---

## 10. 登録 plan（`RegistrationPlan`）

APPROVE の提案だけから凍結 A1 の record を組み立てる（append の順）:

1. `IssuerRegistration(anchor)` — `HUMAN_REVIEWED`、`source_record_ref = review:<batch>.<reviewed_digest24>`、`known_at = accepted_at`
2. `SecurityRegistration(anchor, issuer_id, COMMON_EQUITY)` — 同上
3. `IdentifierAssignment(security_id, JQUANTS_CODE, Code, effective_from=D0)` — `JQUANTS`、参照 ＝ provider の record
4. `DisplayName(ISSUER, JA)` ・`DisplayName(SECURITY, JA)` ・（英名があれば）`DisplayName(ISSUER, EN)` — `JQUANTS`、D0 から
5. `ListingStart(TSE, effective_from=D0)` — `JQUANTS`
6. 一括に 1 つ `Coverage(JP_LISTED_EQUITY_IDENTITY, [D0, D0＋1 日))` — `JQUANTS`

plan は **DERIVED ・NON_AUTHORITY ・NON_PERSISTENT**。ID1 は append しない。plan は memory 内の凍結 `IdentityHistory`（`existing` の
record ＋ plan の record）で検査され、不変条件（`NON_MONOTONIC_KNOWN_AT` ・`REGISTRATION_CONFLICT` ・`CONFLICTING_ASSIGNMENT` …）に
触れれば `PLAN_REJECTED_BY_AUTHORITY_RULES` で fail closed。**後の実行は manifest ・審査 ・A1 の状態を再検証してから append する**。
REJECT ／ DEFER ／ 未審査は `skipped` に理由つきで残る。

---

## 11. 重複 ・衝突 ・code の変更 ・廃止 ・再上場（`existing` ＝ 凍結 A1 の履歴）

| A1 の状態 | 扱い | 理由 |
|---|---|---|
| code が有効に結ばれ、Security ・Issuer が提案の anchor と同じ | **REUSE**（重複の登録なし。plan に入らない） | — |
| 同上だが上場が終わっている | HUMAN_REVIEW_REQUIRED（再上場か） | `LISTING_ENDED_IN_AUTHORITY` |
| code が**別の** canonical identity に結ばれている | **CONFLICT**（fail closed） | `CODE_BOUND_TO_OTHER_IDENTITY` |
| code の割り当てが退役している（code の変更 ／ 再利用の疑い） | HUMAN_REVIEW_REQUIRED | `CODE_PREVIOUSLY_RETIRED` |
| anchor の Issuer ／ Security は登録済みだが code が結ばれていない（前の実行の途中） | HUMAN_REVIEW_REQUIRED | `EXISTING_IDENTITY_INCOMPLETE`（Security の issuer が違えば ＋ `ISSUER_SECURITY_RELATION_CONFLICT`） |
| A1 で有効に結ばれた code が snapshot に無い（廃止か code の変更か分からない） | HUMAN_REVIEW_REQUIRED | `CODE_ABSENT_FROM_SNAPSHOT` |
| snapshot に新しい code（同名の会社でも） | 新しい提案（別の identity）。旧 code との継続は人の判断 | — |

ID1 は旧 code → 新 code の継続 ・廃止 → 再上場の継続 ・同一発行体か ・複数の上場物の束ねを**決めない**。A1 の履歴を上書きしない。
社名の類似は使わない。

---

## 12. 遡及の境界 ・raw ・OBS-58/59

- D0 より前の identity を再構成しない。D0 より前の期間の財務の観測は、D0 で登録した Issuer の観測として A2 に入り、登録の `known_at` より
  前の cutoff での解決は A1R の `RETROSPECTIVE_AUTHORITY` の経路だけ（A3R §4.3。本 gate は触れない）。
- raw の行 ・応答 ・credential は保持 ・直列化しない。合成の行だけ。live の J-Quants request なし。公開の出力なし。
- P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION**（変更なし）。

---

## 13. PILOT2 の前に残る事

1. **identity の実行**（別の明示の gate）: 承認済みの plan を、manifest ・審査 ・A1 の状態の再検証の上で `IdentityStore.append`。
2. 市場区分の code の一覧（公式 S04）の確認と、支える一覧の監督の決定。
3. OBS-58 ・59 の terms の確認 → live の master ・fins の取得 client（raw は memory だけ）。
4. 廃止 ・code の変更 ・再上場の人の手順（A1R の訂正 ・`ListingEnd` ・`IdentifierRetirement` を `HUMAN_REVIEWED` で）。
5. 運用の時刻（`accepted_at` ・`acquired_at`）を誰が渡すか。

---

## 14. 判定

**P8_ID1_IDENTITY_BOOTSTRAP_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**
