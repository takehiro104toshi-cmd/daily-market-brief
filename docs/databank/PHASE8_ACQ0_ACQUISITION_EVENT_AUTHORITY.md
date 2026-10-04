# PHASE 8 / P8-ACQ0 — ACQUISITION EVENT AUTHORITY FOUNDATION（取得 event の証拠の基盤。coverage は作らない）

P8-OBS60 の coverage authority の設計（監督: DESIGN ACCEPTED。I3 承認 ・subject-scoped な財務 coverage は原則承認 ・実装は公式確認待ち ・
`complete_through` の規則 HOLD ・時計は取得 event の `acquired_at` だけ承認 ・`acquisition_events.jsonl` 承認）に従い、
**取得 event（`AcquisitionEvent`）の不変の model と追記専用 store だけ**を足した gate。identity の継続 coverage（OBS60-I1）・
財務開示の coverage（OBS60-F）・A1 ／ A2 の coverage の意味の変更 ・配線は**無い**。

- 基準: P8-ADP0R `ca3e2e4b64f99cfff3af066cdb8fcfa8d953df2b`（凍結。runtime 32 ＝ package 30 ＋ transport ＋ runner）。
  full pytest の基準 5944 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・財務の実の値 ・会社名を載せない。例はすべて合成。

---

## 0. 結論

1. **AcquisitionEvent ≠ Observation**: 「この record を受け取った」は A1 ／ A2 の観測 ・identity の record。取得 event は「何を ・どの bounded な
   範囲で ・いつ取得を試み ・完了 ／ 途中 ／ 失敗 ／ 空だったか」の**証拠**で、provider の行 ・値 ・名前を持たない。
2. **AcquisitionEvent ≠ Coverage**: coverage は「不在に意味があると言ってよい」宣言。取得 event からは本 gate で coverage を作らない。
   model ・store は A1 の `Coverage` ・A2 の `ObservationCoverage` ・resolver を import しない（guard）。
3. **COMPLETE ≠ provider の履歴の完全性**: `COMPLETE` は「caller の承認済みの手順が最後の page まで完了した」だけ。`pagination_key`
   が無いことを provider の意味の真実（履歴の完全性）にしない（公式確認待ち ＝ OBS60-F の NEEDS_OFFICIAL_VERIFICATION）。
4. **EMPTY ≠ 権威ある不在**: `EMPTY` は「bounded な手順が 0 行を返した」だけ。発行体に開示が無い ・dataset が完全 ・不在が権威ある、
   のどれでもない。coverage を作らない（監督の決定 G は HOLD）。
5. **FAILED は coverage を作らない**: 型つきの理由 code（大文字 ・credential の印なし）だけを記録する。本文 ・header ・credential ・
   identity ・値は残さない。
6. **`acquired_at` の 2 時刻の役割**: world の有効時間（`effective_from` ・開示の日時）でも、人の `accepted_at` でもない。「system が
   provider からその応答を受け取った瞬間」。将来の coverage の `known_at`（identity）・`complete_through` の根拠（財務。規則は HOLD）
   になる。時計を読んでよいのは**新しい live ／ local の取得 event を作る caller だけ**（監督の決定 D）。model ・store ・replay は
   時計を読まず、保存した `acquired_at` を使う。
7. **privacy ／ 規約の境界**: journal は取得の metadata だけ。承認済みの範囲の次元（master の `date`、fins の `code` ／ `date`）は
   replay ・監査に要るので残す（code は A1 ・保留 store が既に private root に持つ既存の方針の中）。raw の行 ・財務の値 ・会社名 ・
   API key ・header ・URL ・private の pilot の審査 material は構造上入らない（欄が無い ・digest だけ ・文字集合の制限）。
8. **追記専用**: 正準の行 ・内容 address の id ・byte 一致は `REUSED` ・同じ id で違う内容は `ACQUISITION_CONTENT_CONFLICT` ・
   破損 ／ 非正準 ／ 切断 ／ 物理的な重複は fail closed。update ・delete ・修復 ・書き直し ・圧縮は無い。
9. **将来の使い方**: OBS60-I1 は master の日次 snapshot の取得 event を A1 `Coverage` の provenance（`jq.acq:<digest>`）に結び、
   凍結 ID1 の分類で全登録 code が REUSE のときだけ日の coverage を足す。OBS60-F は fins の取得 event（COMPLETE だけ）を
   subject-scoped な `ObservationCoverage` の根拠にする（公式確認 ・監督決定の後）。本 gate は参照の形だけを定め、配線しない。

---

## 1. model（`acquisition_event_model.py`）

| 欄 | 意味 ・制約 |
|---|---|
| `provider` | `SourceClass.JQUANTS` だけ |
| `scope` | `RequestScope(endpoint, params)`。endpoint は凍結 LIVE1 の `ALLOWED_PATHS`。params は `canonical_query` で正準（整列 ・credential の key 拒否 ・未知の key 拒否 ・値の形）。master は `date` だけ、fins は `code` ／ `date` の 1 つ以上。`pagination_key` は範囲ではない（状態として別に持つ） |
| `acquired_at` | aware な datetime 必須（naive → `NAIVE_DATETIME`）。保存は UTC ISO 8601。同じ瞬間 ＝ 同じ event |
| `status` | `COMPLETE` ／ `PARTIAL_PAGINATED` ／ `FAILED` ／ `EMPTY` |
| `row_count` | 受け取った bounded な行の数 |
| `pagination_key_present` | 最後の応答に `pagination_key` があったか |
| `pages_followed` | 発した page（request）の数。FAILED 以外は ≥ 1 |
| `content_digest` | bounded な行の sha256（§2） |
| `failure_code` | FAILED だけ必須。`^[A-Z][A-Z0-9_]{0,63}$`。credential の印は拒む |
| `authority_version` | `p8_acquisition_event_authority:0.1.0` |
| `api_version` ・`row_order` ・`schema_version` ・`record_kind` | 固定値（`v2` ・`HANDOFF_ORDER_AS_RECEIVED` ・`p8_acquisition_event:0.1.0` ・`ACQUISITION_EVENT`） |

状態の整合（fail closed）: COMPLETE は行 ≥ 1 ・pagination なし。EMPTY は行 0 ・pagination なし。PARTIAL_PAGINATED は pagination あり。
FAILED は理由 code 必須（届いた分の行の digest は残してよい）。他は理由 code を持てない。

identity: `p8acq_<sha256 の 24 hex>`（全欄の正準 JSON）。参照: `jq.acq:<同じ 24 hex>`（`acquisition_reference` ・`is_acquisition_reference`）。
A1 ・A2 の `source_record_ref` の文字集合の中。

---

## 2. 内容の digest（`bounded_content_digest`）

- 欄は凍結 LIVE1 の bounded な handoff だけ: master ＝ `ELIGIBILITY_FIELDS`（6）、fins ＝ `SUPPORTED_FIELDS`（14）。他の欄がある行 ・
  欠けた行 ・文字列でない値は拒む（広げない）。
- 行の順は**受け取った順のまま**（`HANDOFF_ORDER_AS_RECEIVED`）。整列しない（provider ・caller が正準の順を宣言するまで）。
  順が違えば digest は違う。key の順には依らない。
- digest は `sha256(canonical_json({endpoint, row_order, rows: [行ごとの正準 JSON]}))`。journal には digest と行数だけが残り、
  値 ・名前 ・DocType ・開示番号は残らない（test）。

---

## 3. store（`acquisition_event_store.py`）

`<data_root>/screener_intelligence/acquisition_events.jsonl`。A1 ／ A2 ／ 注記 ／ 保留の store と同じ規律: 明示の data_root ・正準の行 ・
write → flush → fsync ・byte 一致は `REUSED` ・同じ id で違う内容は `ACQUISITION_CONTENT_CONFLICT` ・破損 ／ 非正準 ／ 切断 ／ 空行 ／
物理的な重複は `AcquisitionStoreCorrupt`（修復しない）・外部の変更は byte 長で検知 ・read_only は append 拒否。他の store には触れない。

---

## 4. 変更 ・凍結

| 対象 | 変更 |
|---|---|
| `acquisition_event_model.py` ・`acquisition_event_store.py` | 【新規】package の中（IO は store だけ。network ・時計なし） |
| A1 ・A2 ・A2R ・A3 ・ADP0 ・ST1 ・EXE ・ID1 ・ID2 ・LIVE1 ・LIVE2 ・PILOT2A ・P4〜P7 ・main.py | 変更なし（ADP0R の anchor と byte 一致。guard `test_acq0_*`） |
| 配線 | 無し（transport ・runner ・main は `acquisition_event` を知らない。guard） |

---

## 5. 次の gate

- P8-OBS60-I1: identity の継続 coverage（I3）。master の取得 event → 凍結 ID1 の分類 → 全登録 code が REUSE のときだけ A1 `Coverage`
  （provenance `jq.acq:<digest>`）。
- P8-OBS60-F: 公式確認（pagination の完全性 ・Light の保持期間 ・反映の時刻）と監督決定（A2 の subject-scoped coverage ・
  `complete_through` の規則 ・EMPTY の扱い）の後。
