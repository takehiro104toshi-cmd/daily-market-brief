# PHASE 8 / P8-A1 — ISSUER ／ SECURITY IDENTITY CONTRACT

Phase 8 の identity の基盤の契約。identity の意味論だけを実装した。市場 ／ 財務の data・screen・基準・候補・順位・score・
Theme exposure・J-Quants の接続・LLM は無い。

- runtime: `src/intelligence/screener_intelligence/`（`__init__`・`identity_model`・`identity_store`・`identity_resolver`）
- test: `tests/intelligence/test_screener_identity.py`（A〜AZ）・`tests/intelligence/test_screener_intelligence_boundary.py`（BA〜BO）・
  `tests/intelligence/phase8_runtime_registry.py`（登録）
- 基準: P8-A0 の凍結 anchor `76ebf0c`、Phase 7 の最終 anchor `c1e95d3`、Phase 6 の最終 anchor `5ef313a`。

---

## 1. 目的

Phase 8 が発行体（Issuer）と上場物（Security）を区別し、code ／ ticker を永続の identity として扱わないための、
authority の record・履歴の不変条件・PIT の解決を定める。以後の gate（観測・指標・screen・exposure）は、ここで決めた
`IssuerId` ／ `SecurityId` と解決の status だけを使って銘柄を指す。

## 2. identity の区別

| 概念 | 表現 | identity か |
|---|---|---|
| Issuer（発行体） | `IssuerId`（`p8iss_` ＋ 24 hex） | はい |
| Security（上場物） | `SecurityId`（`p8sec_` ＋ 24 hex）。1 つの Issuer に束縛 | はい |
| code（J-Quants の 5 桁 ／ 4 桁の local code） | `IdentifierAssignment`（有効期間つき） | いいえ（属性） |
| 名前（発行体名 ／ 銘柄名、和 ／ 英） | `DisplayName`（有効時刻つき） | いいえ（表示） |
| 上場（市場） | `ListingStart` ／ `ListingEnd`（venue と有効期間） | いいえ（状態） |
| 完全性の宣言 | `Coverage`（有効時間の範囲） | いいえ（authority の範囲） |

1 つの Issuer は複数の Security を持てる（1 発行体 ＝ 1 銘柄を仮定しない）。Security から Issuer への束縛は登録時に固定し、
A1 では変えない（§24）。

## 3. IssuerId

```
IssuerId = content_id("p8iss", canonical_json({"anchor": registration_anchor, "entity": "ISSUER"}))
```

- `registration_anchor` は登録した authority の不透明な handle（`<authority>:<handle>`。例 `hr:issuer-0001`）。code・名前・
  市場の code を使わない。形は `^[a-z][a-z0-9_]{1,31}:[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`、認証情報に見える語は拒否。
- 出所・`known_at`・名前は id に入らない（同じ anchor の再記録は同じ id。名前の変更で id は変わらない）。
- 別の anchor は別の Issuer。同じ実在の発行体が 2 つの anchor で登録されても自動で統合しない（§17）。
- 固定値（test で pin）: `hr:issuer-alpha` → `p8iss_ea5b6eae65191d1666dc63a2`。

## 4. SecurityId

```
SecurityId = content_id("p8sec", canonical_json({"anchor": registration_anchor, "entity": "SECURITY"}))
```

- code・Issuer・名前を入れない。同じ anchor でも実体の種類が違えば IssuerId と別の値（名前空間は prefix と実体で分かれる）。
- `SecurityRegistration` は `issuer_id` と `issue_class`（`COMMON_EQUITY` ／ `PREFERRED_EQUITY` ／ `OTHER`）を持つ。
- 固定値（test で pin）: `hr:security-alpha-common` → `p8sec_f81a3c86ad987fa2220b9150`。
- id の形の検査（`p8iss_` ／ `p8sec_` ＋ 小文字 24 hex）で、code そのもの（`12340` 等）を id として受け付けない。

## 5. 識別子の割り当て

| scheme | 形 | 意味 |
|---|---|---|
| `JQUANTS_CODE` | `^[0-9A-Z]{5}$` | J-Quants の Code（英字を含む code を許す。数として扱わない） |
| `LOCAL_CODE` | `^[0-9A-Z]{4}$` | 4 桁の証券 code（ticker に近い code） |

- 取引所 ／ 市場の識別子は Security を識別しないので scheme にしない。上場の venue（`ListingStart.venue`、A1 は `TSE` だけ）として持つ。
- `IdentifierAssignment{security_id, scheme, value, effective_from}` は開いた範囲 `[effective_from, ∞)` で始まり、
  `IdentifierRetirement{assignment_record_id, effective_to, reason ∈ {RETIRED, REPLACED}}` で閉じる（排他）。
- 同じ scheme ・同じ値の割り当ては、どの Security の間でも有効期間が重ならない。1 つの Security は scheme ごとに同時に 1 つの値だけ。
- 2 つの scheme の間の対応（5 桁 ↔ 4 桁）を導かない。それぞれ明示の割り当て。
- 現在の code を SecurityId に焼き込まない（§4）。

## 6. 表示の metadata

- `DisplayName{subject_kind ∈ {ISSUER, SECURITY}, subject_id, name_kind, language ∈ {JA, EN}, value, effective_from}`。
  名前の種類は subject に固定（Issuer → `ISSUER_NAME`、Security → `SECURITY_NAME`）。
- 名前の変更は新しい record（新しい `effective_from`）で、identity を作らない ・変えない。解決は (種類, 言語) ごとに
  cutoff までに有効になった最後の名前。
- 同じ subject ・種類 ・言語 ・`effective_from` で値が違えば衝突（同じ値の再記録は収束）。
- 名前は 1〜120 文字、前後の空白 ・制御文字 ・`\` ・`//` を拒む。**名前で検索しない**（あいまい一致なし）。
- 市場 segment の名前（プライム等）は A1 の identity ではない（観測として A2 以降。§25）。

## 7. identity の record（event か追記専用の record か）

監査の結論: 状態遷移の event を再生する方式ではなく、**不変の追記専用 record**（有効期間と `known_at` を持つ事実）を基本にし、
区間の終わりだけを別の record（retirement ／ listing end）で表す。

- 理由: record は内容 address で冪等に扱え、衝突（重なり ・二重の終わり ・同じ id の別の登録）を構造で検出でき、
  cutoff での解決が「その時点までに知られた record の集合」の関数になる（再生順の解釈が要らない）。
- record の種類（閉じた集合）: `ISSUER_REGISTRATION` ・`SECURITY_REGISTRATION` ・`IDENTIFIER_ASSIGNMENT` ・
  `IDENTIFIER_RETIREMENT` ・`DISPLAY_NAME` ・`LISTING_START` ・`LISTING_END` ・`COVERAGE`。
- `record_id = content_id("p8idr", canonical_json({schema_version, record_kind, payload, provenance}))`。root の identity
  （IssuerId ／ SecurityId）と record の identity は別。
- 正準の直列化: key を並べ替えた compact JSON（`ensure_ascii=False`）＋ `record_id` ＋ 改行。datetime は UTC の ISO 8601。
- 版: `p8_identity_record:0.1.0`。解決の版: `p8_identity_resolver:0.1.0`。

## 8. 時間の model

- すべての時刻は aware な datetime（naive は `NAIVE_DATETIME` で拒否）。暗黙の現在時刻は無い。
- `known_at`（出所の欄）: authority がその事実を知った時刻。PIT の鍵。
- `effective_from` ／ `effective_to`: 有効時間（半開区間 `[from, to)`）。終わりが始まり以下なら `INVALID_INTERVAL`。
- 履歴は append 順に `known_at` が非減少でなければならない（`NON_MONOTONIC_KNOWN_AT`）。後から過去の知識を差し込めない。
- 有効時間が `known_at` より前（遡った終わりの記録）は認める。解決はその事実を `known_at` 以後にだけ使う。

## 9. PIT の解決

`resolve(history, query, *, cutoff)` ／ `resolve_at_data_root(data_root, query, *, cutoff)`。

- `cutoff` は keyword 必須の aware な datetime（無い ・None ・文字列は `CUTOFF_REQUIRED`）。「最新」の既定は無い。
- 手順: `known_at <= cutoff` の record だけの像を作る（`known_at` は非減少なので append 順の接頭辞）→ 有効時間 `cutoff` を
  覆う coverage を確かめる（§19）→ 問い合わせを有効時間 `cutoff` で解決する。
- 問い合わせ（閉じた種類）: `SECURITY`（SecurityId）・`ISSUER`（IssuerId）・`IDENTIFIER`（scheme ＋ 完全一致の値）・
  `ISSUER_SECURITY`（IssuerId ＋ issue class。1 つを要するときの明示の基準）。
- 結果 `IdentityResolution` は status ・問い合わせ ・cutoff ・Security ／ Issuer の像（識別子 ・名前 ・上場の区間 ・登録の
  record id）・候補 ・使った coverage ・根拠の record id を持つ。正準 JSON で byte 比較できる。
- 未来の record（`known_at > cutoff`）を足しても、過去の cutoff の結果は byte 一致（test AB）。

## 10. code の再利用

同じ code が廃止の後に別の Security に割り当てられ得る。「同じ code ＝ 同じ Security」を仮定しない。

- 再利用は、前の割り当てが `effective_to <= 新しい effective_from` で終わっていることが**先に知られている**ときだけ認める
  （重なれば `CONFLICTING_ASSIGNMENT`）。
- 過去の cutoff の code は、その時点の保持者に解決する。後の保持者の record は過去の答えに現れない（test M〜P）。
- 同じ Security の 2 本目の識別子（code の変更）は、明示の継続の出所（§15）が要る。SecurityId は変わらない（test L）。

## 11. 複数の Security

- `ISSUER` の問い合わせは Security の**明示の集合**（SecurityId の順）を返す。1 つを黙って選ばない。
- `ISSUER_SECURITY` は issue class で絞った後、有効なものがちょうど 1 つなら `FOUND`、2 つ以上なら `AMBIGUOUS`（候補を返し、
  Security を返さない）。後の gate で 1 つの Security を要する基準は、caller の選択か明示の決定論の基準を要する。

## 12. 上場廃止

- `ListingEnd` は identity を消さない。record は物理的に残る（削除 API は無い）。
- 廃止の前の cutoff は上場中として解決できる（test U）。廃止の後は Security を識別できるまま `NOT_ACTIVE_AT_CUTOFF`
  （test T ・V ・W）。
- 廃止を後から知った場合、`known_at` より前の cutoff では上場中と答える（当時の知識。test AC）。

## 13. 再上場 ／ 新しい発行

- 既定: **新しい上場物は新しい SecurityId**（新しい `SecurityRegistration`）。
- 既存の SecurityId に再び上場の区間を足すこと（同じ上場物の継続）は、前の区間が終わっていて、かつ明示の継続の出所（§15）が
  あるときだけ認める。J-Quants の record では継続を立てられない（`CONTINUITY_NOT_AUTHORIZED`）。終わっていない区間に重ねる
  上場は `OVERLAPPING_LISTING`。
- resolver は継続を推測しない。

## 14. 出所（provenance）

`SourceProvenance{source_class, source_record_ref, known_at}` をすべての record が持つ。

- `source_record_ref`: `^[A-Za-z0-9][A-Za-z0-9._:#-]{0,159}$`。`/` ・`\` ・空白 ・`=` を含めない（path ・URL ・本文 ・key=value を
  持てない）。認証情報に見える語（token ・api key ・password ・secret ・bearer ・authorization）を拒む。
- raw の本文 ・machine の path ・credential を持たない。有効期間は record の本体が持つ。
- エラーの文は field 名と code だけで、値を入れない。store のエラーは file 名と行番号だけ（path を入れない）。

## 15. 出所の class

| class | 意味 |
|---|---|
| `OFFICIAL_EXCHANGE` | 取引所の公表 |
| `JQUANTS` | J-Quants の record（vendor） |
| `ISSUER_DISCLOSURE` | 発行体自身の開示 |
| `HUMAN_REVIEWED` | 人の審査の記録 |

authority の規則（`p8_identity_authority_rules:0.1.0`。出所の優先順位の heuristic は持たない）:

| record | 認める出所 |
|---|---|
| `ISSUER_REGISTRATION` ／ `SECURITY_REGISTRATION` | OFFICIAL_EXCHANGE ・ISSUER_DISCLOSURE ・HUMAN_REVIEWED（vendor は発行体と上場物の束縛を立てない） |
| `IDENTIFIER_ASSIGNMENT` ・`IDENTIFIER_RETIREMENT` ・`DISPLAY_NAME` ・`LISTING_START` ・`LISTING_END` | 4 つすべて |
| `COVERAGE` | OFFICIAL_EXCHANGE ・JQUANTS ・HUMAN_REVIEWED（発行体は universe の完全性を宣言できない） |
| 継続（同じ Security の 2 本目の識別子 ・再上場） | OFFICIAL_EXCHANGE ・ISSUER_DISCLOSURE ・HUMAN_REVIEWED（J-Quants は不可） |

## 16. authority の model

| 対象 | class |
|---|---|
| identity の record | `AUTHORITATIVE_IDENTITY_RECORD`（Phase 8 の authority。追記専用） |
| `IdentityResolution` | `DERIVED_NON_AUTHORITY_NON_PERSISTENT`（record ではない。`record_id` を持たない） |

store は identity の record の型以外を受け付けない（解決を append すると `INVALID_TYPE`）。解決の辞書は record として parse
できない。resolver の出力が新しい identity の record になる経路は無い。

## 17. 人の governance

- 曖昧な対応は fail closed: 同じ id の別の登録は `REGISTRATION_CONFLICT`、重なる割り当ては `CONFLICTING_ASSIGNMENT`、
  同じ時刻の別の名前は `CONFLICTING_NAME`、二重の終わりは `DUPLICATE_RETIREMENT` ／ `DUPLICATE_LISTING_END`。
- あいまい一致をしない。名前 ・code の近さ ・事業の記述で Issuer を自動で統合しない。
- 将来の曖昧な identity の統合 ・訂正は、明示の人の審査の authority を要する（A1 には統合 ／ 訂正の record が無い。§24 ・所見）。

## 18. store

`<data_root>/screener_intelligence/identity_records.jsonl`（1 file）。

- 明示の data_root（空 ／ None は `DATA_ROOT_REQUIRED`。既定の場所に fallback しない）。
- 追記専用: 正準の行だけを append、write → flush → fsync。同じ record は `ALREADY_PRESENT` に収束（byte 不変）。
- 読むたびに全行を検査: 符号化 ・切断した最終行 ・空行 ・JSON ・未知の field ・版 ・id の不一致 ・非正準の行 ・物理的な重複 ・
  履歴の不変条件。違反は `IdentityStoreCorrupt`（読み飛ばさない ・修復しない ・migration しない）。
- file が無ければ `IdentityAuthorityMissing`（空の成功にしない）。
- single writer: 開いた後の外部の変更は byte 長で検知（`CONCURRENT_MODIFICATION`）。read-only で開いたら何も書かない
  （directory ・file も作らない）。
- SQLite ・索引 ・cache は持たない。索引を作るなら後の gate で、canonical から作り直せる派生の状態として。

## 19. coverage

`Coverage{scope = JP_LISTED_EQUITY_IDENTITY, effective_from, effective_to}`: authority が「この有効時間の範囲では identity が
完全」と宣言する（上限は必須。開いた範囲を認めない）。

| cutoff の位置（`known_at <= cutoff` の coverage で判断） | status |
|---|---|
| どれかの coverage が覆う | 解決を続ける |
| 見える coverage が無い | `NOT_YET_KNOWN` |
| すべての coverage の始まりより前 | `BEFORE_COVERAGE` |
| すべての coverage の終わり以後 | `NOT_YET_KNOWN`（authority がまだ延長していない） |
| coverage の間の隙間 | `OUTSIDE_COVERAGE` |

coverage の外では、identity が見えていても FOUND ／ NOT_FOUND を返さない（D-P8-A0-10: 保存された authority の範囲より前の
universe は fail closed）。「一致する identity が無い」（NOT_FOUND）と「cutoff が範囲の外」を区別する。

## 20. status ／ 失敗

| status | 意味 |
|---|---|
| `FOUND` | 見つかり、cutoff で有効（Security は上場中。Issuer は上場中の Security を 1 つ以上持つ） |
| `NOT_FOUND` | coverage の中で一致する identity ／ 有効な割り当てが無い |
| `NOT_YET_KNOWN` | cutoff の時点で authority が cutoff を覆っていない（§19） |
| `NOT_ACTIVE_AT_CUTOFF` | identity はあるが cutoff で上場していない（上場前 ／ 廃止後）。像は返す |
| `AMBIGUOUS` | 1 つを要する問い合わせで候補が 2 つ以上（候補を返し、選ばない） |
| `BEFORE_COVERAGE` ／ `OUTSIDE_COVERAGE` | §19 |
| `AUTHORITY_MISSING` | store の file が無い |
| `STORE_CORRUPTION` | store の検査に失敗（診断は `code:detail:行番号`。path ・行の中身を入れない） |

入力の誤り（cutoff が無い ・naive ・問い合わせの形が違う ・code が scheme の形に合わない ・data_root が無い）は status にせず、
例外で拒む。

## 21. 不変条件

| 不変条件 | 実装 | test |
|---|---|---|
| IssuerId と SecurityId の名前空間が別 | prefix と実体の種類 | C |
| Security は登録済みの Issuer を参照する | `UNKNOWN_ISSUER` | G ・H |
| 割り当ては登録済みの Security を参照する | `UNKNOWN_SECURITY` | I |
| 区間は正しい（終わり > 始まり） | `INVALID_INTERVAL` | AD |
| 重なる有効な割り当ては失敗 | `CONFLICTING_ASSIGNMENT` | AO ・P |
| byte 一致の同じ record は収束 | `ALREADY_PRESENT` | AN |
| 未来の record は過去の解決に影響しない | `known_at` の接頭辞 ・非減少 | AB ・AC |
| 名前の変更で安定の id が変わらない | id は anchor だけから | K |
| 廃止は履歴を消さない | 追記専用 ・削除 API なし | W ・AQ |
| 継続は明示の出所だけ | `CONTINUITY_NOT_AUTHORIZED` | L ・Y |
| 知識の時刻は非減少 | `NON_MONOTONIC_KNOWN_AT` | AO |

## 22. import の境界

| module | 許可 |
|---|---|
| `identity_model` | 標準（json ・re ・dataclasses ・datetime ・enum ・typing）・`core.ids` ・`core.time` |
| `identity_store` | 標準（os ・dataclasses ・enum ・pathlib ・typing）・`identity_model` |
| `identity_resolver` | 標準（dataclasses ・datetime ・enum ・typing）・`identity_model` ・`identity_store` ・`core.time` |
| `__init__` | なし |

- 禁止: Phase 6 ／ 7 ・P5 ・legacy ・J-Quants の transport ／ client ・provider ・network ・公開 ／ 通知 ・売買 ／ portfolio。
  時計 ・乱数 ・動的 code ・module の状態なし。filesystem は store だけ（書くのは `initialize` と `append` だけ）。
- 他の package は Phase 8 を import しない。production runtime closure に含まれない。
- runtime closure: 各 module を import して読み込まれる first-party の module は `src` ・`src.intelligence` ・`core.ids` ・
  `core.time` と本 package だけ（test BA〜BG）。

## 23. security

- credential ・API key ・顧客 ・portfolio の data ・machine の path ・機密 PDF ・Compass の本文を持たない ・記録しない。
- test は架空の identity だけ（`hr:issuer-alpha` 等。実在の企業 ・code ・legacy の watchlist を使わない）。
- 出所の参照 ・anchor の文字集合と語の拒否（§14）で、path ・URL ・本文 ・認証情報が record に入らない。
- network に接続しない。J-Quants を呼ばない。

## 24. 延期する corporate action

A1 は次を model しない（後の gate）: 分割 ・併合の経済的な意味、合併 ・会社分割 ・株式交換、発行体と上場物の束縛の変更、
株式の転換、価格の調整、identity の統合 ・訂正の record、市場 segment の履歴、複数の venue、5 桁 ↔ 4 桁の導出。
A1 は将来の対応付けに要る identity の事実（登録 ・割り当て ・上場の区間 ・名前 ・coverage）だけを保つ。

## 25. A2 への引き継ぎ

- 観測 ／ 指標は銘柄を `SecurityId`（上場物の値）または `IssuerId`（会社の値）で指し、code で指さない。
- 観測を識別子に結ぶときは、観測の時刻を cutoff にして `IDENTIFIER` を解決し、`FOUND` ／ `NOT_ACTIVE_AT_CUTOFF` 以外の
  status は data 品質の状態（`IDENTIFIER_MISMATCH` ・coverage の外）として扱う（空にしない）。
- universe の定義は coverage の範囲の中だけ（D-P8-A0-10）。
- 財務（会社の値）を発行体に結ぶ規則、市場 segment ・業種 ・規模区分の観測は A2 以降で定める。
- 実データでの identity の起動（約 4,400 銘柄の登録）には、監督が承認する人の審査の一括の手順が要る（所見 P8-OBS-12）。

## 26. 凍結の方針

- Phase 7 の runtime と文書は `c1e95d3` と byte 一致。Phase 6 の runtime ・knowledge は `5ef313a` から不変。Phase 6 の test は
  A0 から不変。
- Phase 8 の登録は `tests/intelligence/phase8_runtime_registry.py` だけが持つ（完全一致の path。追加だけ）。
  - Phase 6 の凍結 guard は `phase7_runtime_registry` の除外（`PHASE7_EXCLUDED_PATHSPECS` ／ `is_phase7_addition`）を読むので、
    その 2 つが `PHASE8_RUNTIME` も除く（Phase 6 の test は変えていない）。
  - Phase 7 の境界 guard は、登録された Phase 8 の runtime ／ test ／ 文書の追加だけを認める。
  - Phase 7 の test 2 file への変更は `PHASE7_TEST_REGISTRATION` に行単位で列挙し、Phase 8 の guard が A0 との差と完全一致を
    確かめる（登録以外の変更 ・登録の欠落を拒む）。
- 未登録の Phase 8 runtime は検出される: 登録の判定の単体の test（BN）と、実際に未登録の file を置いた実行で Phase 6 ／ 7 の
  凍結 guard 8 件が落ちることを確かめた。
- 以後の Phase 8 の gate は `phase8_runtime_registry.py` と Phase 8 の guard だけを更新し、Phase 6 ／ 7 の test を触らない。
