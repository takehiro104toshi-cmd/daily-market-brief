# PHASE 8 / P8-LIVE1 — STRICT MEMORY-ONLY J-QUANTS INGEST CLIENT ＋ PRE-ID1 ELIGIBILITY GATE

PILOT2 の前の最後の software の境界: 厳密な provider の応答の parse、**凍結 ID1 の前**の master の適格（`ProdCat` の是正）、memory だけの
transport の抽象、bounded な `fins/summary` の取得、明示の request の予算。**合成の transport だけで test。実の J-Quants の request は無い。**
規約の authority は凍結の P8-LIVE0（`17c9623`）で、本 gate は規約を解釈し直さない。

- 基準: P8-LIVE0 `17c962385be5641665f4d7904cfc710cbb575569`（凍結。runtime 27 module）。full pytest の基準 5827 passed ／ 2 skipped。
- 監督の override: P8-ID1B は実装しない。凍結 ID1 ・ID2 は変えない。是正は ID1 の前で行う。

---

## 0. 結論

1. 追加した runtime は 3 module: `jquants_live_model`（予算 ・transport の抽象 ・合成 transport ・閉じた error ・適格の型）、
   `jquants_master_ingress`（master の応答の厳密な parse ＋ ID1 の前の適格 ＋ ID1 の行の handoff）、`jquants_live_client`
   （`fetch_master` ・`fetch_fins_summary` ・identity の handoff ・fins の parse）。先行の 27 module（ID1 ・ID2 ・ADP0 ・EXE を含む）は byte 一致。
2. **ProdCat の是正は ID1 の前**: `assess_master_row` が `Date` ・`Code` ・`CoName` ・`CoNameEn` ・`Mkt` ・**`ProdCat`** を読み、
   `ELIGIBLE_FOR_ID1` ／ `HOLD` ／ `EXCLUDED` を決めてから、ELIGIBLE の行だけを凍結 ID1 の `MasterRow`（5 欄）にして渡す（§3 ・§6）。
3. **raw は memory だけ**: transport の応答は `TransportResponse`（本文は `repr` に出ない）で、client は本文を保持せず、結果には bounded な型
   だけが入る。error は大文字の code ＋ field 名だけ（本文 ・URL ・header ・credential は運べない。model が拒む）（§4 ・§5）。
4. **transport の抽象**: `Transport.get(path, params)`。本 gate の実装は決定論の `SyntheticTransport` だけ。実 network の transport は
   **無い**（`api.jquants.com` を含む文字列は package に無い。guard）。credential は model ・client ・query に現れない（§5）。
5. **request の予算**: caller が持つ `RequestBudget`（上限 8。1〜8）。transport を呼ぶ**前**に消費し、9 回目は `BUDGET_EXHAUSTED` で
   transport に届かない。reset ・隠れた retry ・背景の呼び出し ・pagination の自動追随は無い（§6）。
6. **identity が fins に先行**: `fetch_fins_summary` は凍結 A1 の履歴で code → 有効な `JQUANTS_CODE` → Security → Issuer を確かめた
   `IdentityHandoff` を要求する。無ければ request を発しない（§7）。
7. **fins → ADP0**: 応答の各行を凍結 ADP0 の `FinancialSummaryRow.from_provider_mapping` に渡し、14 欄だけを残す（97 欄は捨てる）。
   code の不一致 ・未知の key ・形の違いは fail closed。A2 の append ・EXE ・指標は LIVE1 に無い（§8）。
8. 公開 ・LLM の firewall は LIVE0 のまま（§10）。判定: **P8_LIVE1_MEMORY_ONLY_CLIENT_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§13）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch ／ HEAD | `claude/investment-intelligence-phase6` ／ `17c962385be5641665f4d7904cfc710cbb575569`（clean） |
| 凍結の anchor | A1 `4162e9c` ／ A1R `e6a750f` ／ A2 `b686b00` ／ A2R `4d3540c` ／ A3A `84c2d52` ／ A3B `d8845f2` ／ A3R `f1c4a4e` ／ ST1 `e831996` ／ ADP0 `a2ccc1c` ／ EXE `5ec466b` ／ ID1 `6b5f0e6` ／ ID2 `07e62c7` ／ LIVE0 `17c9623`。ID1 ・ID2 byte 一致を個別に確認 |
| full pytest の基準 | 5827 passed ／ 2 skipped |

---

## 2. 変更の範囲（不変の宣言）

| 対象 | 状態 |
|---|---|
| `src/intelligence/screener_intelligence/jquants_live_model.py` ・`jquants_master_ingress.py` ・`jquants_live_client.py` | **新規** |
| `tests/intelligence/test_screener_jquants_live.py` | **新規**（46 test） |
| `tests/intelligence/phase8_runtime_registry.py` ・`test_screener_intelligence_boundary.py` | LIVE1 の登録 ・LIVE0 の anchor の guard |
| 先行の 27 module ・Phase 8 の test 11 file ・先行の記録 21 | **byte 一致**（guard `test_live1_*`） |
| `main.py` ・Pages ・config ・workflow ・Secrets ・legacy ・P4/P5 ・P6 ・P7 ・Production DNA | 変更なし |

---

## 3. なぜ ProdCat は ID1 の前か ・支える行列

凍結 ID1 の `MasterRow` は `ProdCat` を捨てる（設計時の 5 欄）。LIVE0 §5.4 の発見: `Mkt ∈ {0111,0112,0113}` ＋ 5 桁目 `0` では外国株券
（021）・外国株預託証券（024）を除外できない。ID1 を変えると凍結 ・anchor ・審査の digest の意味が変わるので、監督は **ID1 の前で決める**
architecture を選んだ。LIVE1 は `ProdCat` を「ID1 の前の適格の事実」として使い、決めた後に捨てる（ID1 には届かない）。

| 欄 | 値 | 分類 | 理由の code |
|---|---|---|---|
| `Code` | 5 桁 ・数字 ・5 桁目 `0` | 支える | — |
| `Code` | 形が違う（桁 ・小文字 ・空） | HOLD | `CODE_MALFORMED` |
| `Code` | 5 桁目 ≠ `0` ・英字を含む | HOLD | `CODE_NOT_COMMON_EQUITY` |
| `Mkt` | `0111` ／ `0112` ／ `0113` | 支える | — |
| `Mkt` | `0105` ／ `0109` | HOLD | `MARKET_HOLD` |
| `Mkt` | `0101` ／ `0102` ／ `0104` ／ `0106` ／ `0107`（再編前。予期しない） | HOLD | `MARKET_HISTORICAL` |
| `Mkt` | 一覧に無い ・空 | HOLD | `MARKET_UNKNOWN` |
| `ProdCat` | `011` | 支える（5 桁目 `0` と組で） | — |
| `ProdCat` | `012` ／ `013` ／ `014` ／ `021` ／ `022` ／ `023` ／ `024` | **EXCLUDED** | `PRODUCT_CATEGORY_EXCLUDED` |
| `ProdCat` | 一覧に無い 3 桁 | HOLD | `PRODUCT_CATEGORY_UNKNOWN` |
| `ProdCat` | 無い ／ 空 ・桁 ・英字 ／ 文字列でない | HOLD | `PRODUCT_CATEGORY_MISSING` ／ `PRODUCT_CATEGORY_MALFORMED` ／ `FIELD_NOT_TEXT` |
| 他の欄 | 無い ／ 文字列でない | HOLD | `FIELD_MISSING` ／ `FIELD_NOT_TEXT` |

HOLD の理由が 1 つでもあれば HOLD（EXCLUDED は除外の理由だけのとき）。名前から種類を推定しない。enum を黙って広げない。

---

## 4. raw は memory だけ

- `TransportResponse(status, body)`: 本文は field だが `repr` ・`str` に出ない。client は parse の後に参照を持たない。
- 結果（`MasterEligibilityResult` ・`MasterFetch` ・`FinsHandoff`）は bounded な型だけ。`as_dict` に raw ・他の欄 ・本文は無い。
- error `LiveInputError(code, detail)`: code は大文字の code、detail は field 名だけ（model が文字の集合で拒む）。payload ・URL ・header ・
  credential は入らない。
- file ・log ・cache ・fixture ・journal ・artifact ・repo に raw を書く code は無い（filesystem ・logging の import なし。guard）。
- 後段に残るのは凍結の bounded な record（A1 ・A2 ・注記 ・保留）だけ。

## 5. transport の抽象 ・credential

- `Transport.get(path, params) -> TransportResponse`。path は `/v2/equities/master` ・`/v2/fins/summary` だけ。query の key は
  `code` ・`date` ・`pagination_key` だけ（`x-api-key` ・`authorization` ・`token` 等は `CREDENTIAL_IN_QUERY` で拒む）。
- 本 gate の実装は `SyntheticTransport`（`(path, 正準の query)` → 応答。無い組は `SYNTHETIC_RESPONSE_MISSING`）だけ。
- **実 network の transport は LIVE1 に無い**。将来の実装は「API key を環境の secret から読み header に付ける ・log に出さない ・1 request ＝
  1 呼び出し ・retry なし」を満たす別 gate（PILOT2 の承認の後）。
- client ・model ・error ・metadata に credential ・URL ・host は現れない。環境の secret を読む code は無い。

## 6. request の予算

`RequestBudget(limit ≤ 8)`。`reserve(path)` を transport の**前**に呼び、`used ≥ limit` なら `BUDGET_EXHAUSTED`。`used` ・`remaining` ・
`paths`（path だけ。query ・credential なし）を決定論で公開。失敗した request（HTTP の status ・parse の失敗）も 1 として数える（隠れた
retry なし）。不正な引数（date ・code）は予算を消費しない。予算は instance ごとで共有 ・reset されない。

## 7. master → ID1 の handoff ・identity が fins に先行

```
fetch_master(D0)          # 1 request。応答 → assess_master_payload → MasterEligibilityResult の tuple（raw は捨てる）
id1_rows(results)         # ELIGIBLE_FOR_ID1 だけ、凍結 ID1 の MasterRow（5 欄）
propose_bootstrap(rows, batch)      # 凍結 ID1（変更なし）
review_manifest(..., accepted_at=…) # 人の審査（LIVE0 §6）
execute_identity_registration(...)  # 凍結 ID2 → A1
verify_identity_for_code(history, code) -> IdentityHandoff   # A1 で code → Security → Issuer を確認
fetch_fins_summary(handoff)         # ここで初めて fins の request（handoff が無ければ発しない）
adapt_financial_summary_row(row, AdapterContext(issuer_id=handoff.issuer_id, ...))   # 凍結 ADP0
execute_financial_summary_row(...)  # 凍結 EXE
```

`fetch_fins_summary` は `IdentityHandoff` 以外を `IDENTITY_HANDOFF_REQUIRED` で拒み、予算も消費しない。`verify_identity_for_code` は
A1 に無い ・退役 ・曖昧な code を拒む（登録しない。ID2 の authority を代替しない）。

## 8. fins → ADP0 の handoff

`parse_fins_summary_payload(body, code)`: `{"data": [...], "pagination_key"?}` の形だけ。各行を凍結 ADP0 の
`FinancialSummaryRow.from_provider_mapping` に渡す（14 欄だけ残す。公式の他 97 欄は捨てる。公式の一覧に無い key は ADP0 が拒む →
`FINS_ROW_REJECTED`）。行の `Code` が handoff の code と違えば `FINS_ROW_CODE_MISMATCH`。`pagination_key` は返すだけで自動で追わない
（次の page は caller が予算の中で明示に要求）。A2 の append ・EXE ・指標は LIVE1 に無い。

## 9. 4 欄の pilot の境界

ADP0 の 14 欄（`Sales` ・`OP` ・`NP` ・`TA` ＋ ADP0 が要る metadata 10 欄）だけが handoff に残る。ADP0 は変えない。

## 10. 公開 ・LLM の firewall（LIVE0 のまま）

private ／ internal の pilot だけ。公開の出力 ・Pages ・公開 Morning Brief ・顧客向け ・外部 app なし。J-Quants の payload ・派生値を外部の
LLM に入れない。repo ・artifact に live の payload を置かない。LIVE1 の module は pages ・reports ・narrative ・themes ・LLM を import しない
（boundary の guard）。OBS-58 ・59 は凍結 LIVE0 が統治する。

## 11. PILOT2 の前の正確な境界

LIVE1 で終わる software: parse ・適格 ・予算 ・transport の抽象 ・identity の handoff ・fins の handoff。**残るのは人 ・本人の環境の手順だけ**:

1. 実 network の transport（PILOT2 の承認の後の小さな gate、または本人の環境で `Transport` を実装する短い script。本 package に置くなら
   `api.jquants.com` の guard を監督の承認で緩める）。
2. 本人の API key（環境の secret）。本 session ・repo ・log に出さない。
3. D0 の決定 ・1〜3 発行体の選定 ・`supported_markets=("0111","0112","0113")`。
4. 人の審査（LIVE0 §7.2 の checklist）と `accepted_at` の記録。
5. private の data root の初期化と、廃棄の手順（LIVE0 §7.3）。

## 12. 検証

| 項目 | 結果 |
|---|---|
| `test_screener_jquants_live.py` | 46 passed |
| boundary ・registry の guard（LIVE1 の登録 ・LIVE0 anchor の byte 一致 ・sanctioned import ・語彙 ・host の不在） | passed |
| full pytest | 本文の最終報告 |

## 13. 判定

**P8_LIVE1_MEMORY_ONLY_CLIENT_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**
