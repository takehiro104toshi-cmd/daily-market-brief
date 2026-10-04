# PHASE 8 / P8-OBS60-I1 — IDENTITY CONTINUITY COVERAGE AUTHORITY（model I3: 明示の継続 authority）

P8-OBS60 の coverage authority の設計（監督: DESIGN ACCEPTED。identity は model I3 を承認）と P8-ACQ0（取得 event の証拠。凍結
`b210798cc99cbd503a52a0af190d171675eead3d`）に続き、**取得に成功した master snapshot の日 T について、凍結 A1 の
`Coverage(JP_LISTED_EQUITY_IDENTITY, [T 00:00 JST, T＋1 日))` を 1 つだけ append する authority** を足した gate。
財務開示の coverage（OBS60-F）・A2 の coverage の意味 ・`complete_through` の規則 ・日次の自動化の起動 ・実 request は**無い**。

- 基準: P8-ACQ0 `b210798cc99cbd503a52a0af190d171675eead3d`（凍結。runtime 34）。full pytest の基準 6013 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・会社名 ・実の code を載せない。例はすべて合成。実 PILOT2 は PASS ／ CLOSED のまま（再実行しない）。

---

## 0. 結論

1. **なぜ D0 の bootstrap coverage では足りなかったか**: ID1 ／ ID2 の coverage は snapshot の日 D0 の 1 日だけで、identity の record は人の
   `accepted_at` に知られる。審査が D0 の後なら「identity が知られていて、かつ宣言された coverage が cutoff を覆う」瞬間が存在せず、
   凍結 A1 ／ A2 ／ A3 は正しく fail closed した（実 PILOT2: `SUBJECT_NOT_RESOLVED`。P8-OBS60R0）。
2. **I3 の authority**: 新しい日 T の master snapshot を取得（凍結 ACQ0 の event ＝ `COMPLETE` ・master ・日 T ・内容の digest が行と一致）
   → 凍結 ID1 の分類で**既存の審査済み identity と整合する**と確かめられた日だけ coverage を宣言する。「反する record が無い」ことを
   継続にしない。前の coverage から推定しない。
3. **確かめた 1 日 ＝ 1 区間**: coverage は常に `[T 00:00 JST, T＋1 日 00:00 JST)`。確かめていない日（取得の失敗 ・審査待ち）は gap。
   gap は後から埋めない（`[D0, D3)` を作らない）。凍結 A1 の resolver は gap の日の cutoff に `NOT_YET_KNOWN`（厳密 PIT）を返す。
4. **継続の条件（監督の既定）**: `ALL_RELEVANT_REGISTERED_IDENTITIES_REUSE`。関係する登録済み identity のすべてが凍結 ID1 で `REUSE`。
5. **関係する登録済み identity の範囲（§6 の監査の結論。凍結 A1 から決定論で導く）**:
   - **有効**: 退役していない `JQUANTS_CODE` の割り当てを持ち、上場が終わっていない Security とその Issuer。すべて `REUSE` が要る。
   - **退役 ／ 上場の終わった identity**: snapshot に居なくてよい（凍結 ID1 `_absent_codes` と同じ）。snapshot に現れれば凍結 ID1 が
     `CODE_PREVIOUSLY_RETIRED` ／ `LISTING_ENDED_IN_AUTHORITY` で人の審査にし、coverage を妨げる（再上場の疑い）。
   - **A1 に無い code（市場の他の銘柄）**: 範囲の外。coverage を妨げない（A1 はそれらを `NOT_FOUND` と答える。D0 の bootstrap coverage
     と同じ意味で、1 発行体の pilot でも日の coverage を宣言できる）。
   - **登録済み identity に関わる新しい code**: 同じ先頭 4 桁の別の code（`MULTIPLE_LISTINGS_SUSPECTED`）・anchor が登録済みで code が
     結ばれていない（`EXISTING_IDENTITY_INCOMPLETE`）等は凍結 ID1 が人の審査にし、coverage を妨げる。
   - anchor が bootstrap の形（`<batch>:iss.<code>` ／ `<batch>:sec.<code>`）でない有効な結び ・同じ code の複数の有効な結びは
     `IDENTITY_SCOPE_UNRESOLVED`（coverage なし）。有効な identity が 1 つも無ければ宣言しない。
6. **第 2 の分類器を作らない**: 行の適格は凍結 LIVE1 `assess_master_row`、分類は凍結 ID1 `propose_bootstrap(rows, batch(T), existing=A1)`
   を登録済みの batch id ごとに再導出（anchor は batch id に依るので、登録時と同じ batch id で `REUSE` を確かめる）。
7. **取得 event の provenance**: `Coverage.provenance = (JQUANTS, AcquisitionEvent.reference = jq.acq:<digest>, known_at = acquired_at)`。
   event は `AcquisitionEventStore` に存在しなければならず、provider ・endpoint ・日 ・digest ・行数 ・状態を照合する。
   `EMPTY` ・`PARTIAL_PAGINATED` ・`FAILED` は決して coverage を作らない。
8. **人の審査の 2 時刻**: identity の `known_at` は人の `accepted_at`、coverage の `known_at` は取得の `acquired_at`。審査が D0 の
   後でも、取得の時点で identity が知られていれば T の coverage を作れる（遅れた審査は構造的に解けた）。`known_at` を遡らせない。
   取得の時点でまだ知られていない identity があれば `IDENTITY_NOT_KNOWN_BY_ACQUISITION`。後の日の coverage が既にあれば
   `AUTHORITY_KNOWN_AFTER_ACQUISITION`（A1 の known_at の単調性。古い日を後から埋めない）。D0 の coverage は書き直さない。
9. **変化の日**: 有効な code が snapshot に無い ・市場区分 ・商品区分の変化 ・再上場の疑い ・関係する新しい code → `REVIEW_REQUIRED`
   ＋ 凍結 LIVE1 ／ ID1 の型つきの理由。identity の生成 ・退役 ・統合 ・再上場 ・mutation は自動で行わない（人の別の workflow）。
10. **書くのは A1 の `Coverage` だけ**: 登録 ・識別子 ・名前 ・上場 ・退役 ・訂正 ・A2 の record は書かない。既存の record を変えない。
11. **冪等**: 同じ A1 ・行 ・event の再実行は `REUSED`。同じ区間に別の provenance の coverage があれば `COVERAGE_CONFLICT`
    （削除 ・修復 ・置き換えなし。D0 の日自体を本 authority で宣言し直すことはできない）。
12. **OBS60-F との関係**: 本 gate の後、identity は確かめた日に解ける。A2 の財務の coverage（`FUNDAMENTAL_DISCLOSURE`）は無いままなので
    A3 の指標は typed の `OUTSIDE_COVERAGE` になる。OBS60-F は公式確認 ・監督決定の後（別 gate）。

---

## 1. 結果の語彙（`ContinuityResult`）

| outcome | 意味 |
|---|---|
| `APPENDED` | T の coverage を 1 つ append した |
| `REUSED` | 同じ authority（同じ event ・同じ日）の coverage が既にある |
| `REVIEW_REQUIRED` | 関係する identity の変化の疑い（`review` に凍結 LIVE1 ／ ID1 の項目）。書かない |
| `ACQUISITION_NOT_COMPLETE` | event が `EMPTY` ／ `PARTIAL_PAGINATED` ／ `FAILED` |
| `ACQUISITION_MISMATCH` | event が無い ・provider ／ endpoint ／ 日 ・digest ・行数が合わない ・行が bounded でない |
| `IDENTITY_SCOPE_UNRESOLVED` | 有効な identity が無い ・anchor が bootstrap でない ・複数の結び ・取得の時点で知られていない ・分類の失敗 |
| `COVERAGE_CONFLICT` | 同じ区間に別の provenance の coverage |
| `STORE_FAILURE` | A1 ／ ACQ0 の store の欠落 ・破損 ・append の拒否（code は `failure_code`） |

`review` の項目: `code` ・`origin`（`LIVE1_ELIGIBILITY` ／ `ID1_CLASSIFICATION`）・`disposition` ・`reasons`（凍結の語彙そのまま）・
既存の issuer ／ security id。名前 ・値は持たない。

---

## 2. 手順（`execute_identity_continuity(data_root, day, rows, event_reference, supported_markets)`）

1. ACQ0 store で `event_reference` の event を探す → 無ければ `ACQUISITION_MISMATCH`。provider ・endpoint ・`date=T` ・bounded な行の
   digest ・行数を照合 → 違えば `ACQUISITION_MISMATCH`。状態が `COMPLETE` でなければ `ACQUISITION_NOT_COMPLETE`。
2. 凍結 A1 の store を開く。T の `Coverage` record を組み立て、同じ record があれば `REUSED`、同じ区間の別の coverage があれば
   `COVERAGE_CONFLICT`。
3. 範囲（§0 の 5）。有効な結びの anchor が読めない ・複数 → `IDENTITY_SCOPE_UNRESOLVED`。
4. A1 のすべての record の `known_at ≤ acquired_at` を要求（identity → `IDENTITY_NOT_KNOWN_BY_ACQUISITION`、coverage →
   `AUTHORITY_KNOWN_AFTER_ACQUISITION`）。
5. 凍結 LIVE1 の適格（登録済み code の行）＋ 凍結 ID1 の分類（batch ごと）。関係する項目が 1 つでもあれば `REVIEW_REQUIRED`。
6. 有効な code がすべて `REUSE` → `Coverage` を append（A1 の不変条件で検査）→ `APPENDED`。

---

## 3. 変更 ・凍結

| 対象 | 変更 |
|---|---|
| `identity_continuity_coverage.py` | 【新規】package の中（IO は凍結 store 経由だけ。network ・時計なし） |
| A1 ・A1R ・A2 ・A2R ・A3 ・ADP0 ・ST1 ・EXE ・ID1 ・ID2 ・LIVE1 ・LIVE2 ・PILOT2A ・ACQ0 ・P4〜P7 ・main.py | 変更なし（ACQ0 の anchor と byte 一致。guard `test_obs60_i1_*`） |
| 配線 | 無し（runner ・main は I1 を知らない。日次の自動化の起動は別 gate） |

---

## 4. 次の gate

- P8-OBS60-F: 公式確認（pagination の完全性 ・Light の保持期間 ・反映の時刻）と監督決定（A2 の subject-scoped coverage ・
  `complete_through` ・EMPTY）の後に、財務開示の coverage authority。
- 配線: 本人の環境の runner に「master の取得 → ACQ0 event → I1」の段を足す gate（日次の自動化の起動は監督の承認の後）。
