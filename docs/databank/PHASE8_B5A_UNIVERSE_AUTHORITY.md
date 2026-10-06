# PHASE 8 / P8-B5A — EXPLICIT UNIVERSE SEMANTICS + PRIVATE UNIVERSE AUTHORITY

Phase 8 v1 の完了の目標（明示の有限な Universe → 発行体の identity → provider の authority → 明示の B3 の方針 → 決定論の複数発行体の評価 →
型つきの全結果の集合 → 派生の MATCH の部分集合 → private の安全な投影）の最初の欠けた入力 authority を足す gate。答える問いは
「この screen は、どの有限な上場物の provider code の集合を対象にするつもりか」だけ。推奨 ・魅力 ・順位 ・Theme の受益 ・watchlist ・
portfolio の候補の集合ではない。発見と評価の明示の範囲だけ。

- 基準: P8-B4B `ff89a75c0f6c73d4372b89e7a4acd5fc46b0c5e8`（凍結。runtime 49。実 data の検証 PASS ／ CLOSED）。full pytest の基準
  6489 passed ／ 2 skipped。
- 本 gate は model と private store だけ。複数発行体の実行 ・結果の集約 ・評価 ・取得 ・J-Quants ・batch の継続 ・run の台帳 ・安全な出力 ・
  Theme ・新しい指標 ・Phase 9 ・公開の出力は無い。実の provider の呼び出しは無い。
- 本書 ・CHANGELOG ・test は実の code ・実の発行体 ・実の Universe を載せない（test の code は構文の検査のための合成の値）。

---

## 0. v1 の主語（監督の決定）

| 概念 | 意味 |
|---|---|
| Universe の member の入力 | 明示の provider の上場物 code（J-Quants の 5 文字 code。凍結 A1 の `IdentifierScheme.JQUANTS_CODE` の形） |
| screen の主語 | 審査済みの identity で解いた **発行体**（後の実行 B5C: code → 適格な上場物 → 審査済みの SecurityId → 審査済みの IssuerId） |

provider code を発行体の正準の identity にしない。同じ発行体の複数の code の束ねは B5C（本 gate は code の Universe だけを保存する。
member は宣言の順 ・重複なしの code の tuple なので、後の束ねを妨げない）。

## 1. `UniverseSpec`（`screener_universe_model.py`）

| 欄 | 型 ・規則 |
|---|---|
| `universe_key` | `^[a-z0-9][a-z0-9_-]{0,63}$`（凍結 B1 の方針の鍵と同じ形） |
| `version` | ≥ 1 の int（bool ・文字列 ・float は拒む）。人の明示の label |
| `intent` | 1〜500 字 ・制御文字なし ・前後の空白なし ・credential の印なし ・推奨 ／ 順位の語なし（凍結 B1 の方針の意図と同じ禁止の集合。test が一致を pin） |
| `members` | `tuple[str]`。各 code は `^[0-9A-Z]{5}$`（凍結 A1 の形）。1 つ以上 ・`MAX_UNIVERSE_MEMBERS` 以下 ・重複なし。正規化しない（空白 ・小文字 ・全角 ・数は拒む） |
| `eligibility_rules_version` | 凍結 LIVE1 の `LIVE_RULES_VERSION`（`p8_jquants_live:0.1.0`）と一致を要求（閉じた束ね） |
| `authority_day_rule` | `SINGLE_AUTHORITY_DAY_D0_NO_MULTI_DAY_CONTINUITY` |
| `member_scheme` | `JQUANTS_CODE` |
| `member_order_rule` | `DECLARED_ORDER_SERIALIZATION_ONLY_NON_SEMANTIC_NOT_A_RANKING` |
| `subject_rule` | `ISSUER_RESOLVED_LATER_THROUGH_REVIEWED_IDENTITY_NOT_THE_PROVIDER_CODE` |
| `rules_version` | `p8_screener_universe:0.1.0` |

導出: `universe_id` ＝ `content_id("p8uni", canonical_json(identity_payload))`（identity payload ＝ 鍵 ・版 ・意図 ・member の宣言の順 ・
規則の束ね ・schema）。`membership_digest` ＝ 順を除いた member の集合の sha256（同じ集合の比較のため。identity ではない）。
`from_dict` は欄の完全一致 ・validator ・`universe_id` と `membership_digest` の再計算の一致を要求する。

### member の意味

- 構文 ・構造の不変条件だけを検査する。J-Quants を呼ばない ・identity を解かない ・適格を判定しない ・上場の状態 ・発行体を推定しない。
- 重複 ・曖昧な正規化 ・黙った並べ替え ・隠れた member の展開 ・曖昧な一致は無い。
- 宣言の順は保つが、**直列化と人の意図の順だけ**で意味を持たない（順位 ・優先 ・魅力 ・確信ではない）。順を変えると `universe_id` は
  変わる（内容 address）が `membership_digest` は同じ（P8-OBS-101）。

### 有限

暗黙の「日本株の全体」は無い。上限 `MAX_UNIVERSE_MEMBERS` ＝ 凍結の master の取り込みの上限 `MAX_MASTER_ROWS`（10000。1 つの master の
snapshot の行数の上限で、Universe の member はその snapshot の部分集合でしかあり得ない）。request の予算（≤ 8）は Universe の意味に入れない
（実行の batch の大きさは B5C）。

### authority の日 ・適格の規則

Universe は単一の authority の日の規則を束ねる。後の実行は D0 の master の snapshot と凍結 A1 の identity に対して明示の code を検査する。
Universe は上場の継続 ・上場の開始 ／ 終了 ・code の継続 ・発行体の継続を証明しない（I1 は延期）。適格の規則の版を束ねるので、規則が後で
変わっても既存の Universe の意味は黙って変わらない（版が違えば構築できない ＝ 後の実行は fail closed）。規則は実行しない（凍結 LIVE1 の
`assess_master_row` は import しない）。

## 2. authority（`UniverseAuthorityRecord`）

| 欄 | 規則 |
|---|---|
| `universe` | `UniverseSpec` |
| `author_ref` | `^human:[A-Za-z0-9][A-Za-z0-9_.:@-]{0,113}$`（人の出所を明示。credential の印なし） |
| `reviewed_at` | aware な datetime（naive ・文字列 ・省略は拒む。既定なし） |
| `authority_class` | `HUMAN_REVIEWED_SCREENING_UNIVERSE` だけ（提案 ・機械の object は構築できず、journal でも復元できない） |
| `schema_version` ／ `rules_version` | `p8_screener_universe_authority:0.1.0` |

`record_id` ＝ `universe.universe_id`。1 つの Universe に 1 つの審査（同じ Universe に別の審査者 ・別の審査の瞬間は衝突）。
`NOT_IMPLIED_BY_UNIVERSE`: 推奨 ・順位 ・Theme の受益 ・watchlist ・portfolio の候補 ・上場の継続 ・発行体の identity ・provider の適格を
意味しない。自動の承認 ・推定の承認 ・LLM の承認 ・既定の著者 ・既定の審査の瞬間は無い。

## 3. private store（`screener_universe_store.py`）

path: `<data_root>/screener_intelligence/screener_universe_authority.jsonl`（凍結 B3 と同じ dir。caller の明示の private root。既定 ・
config ・cwd の path は無い）。凍結 B3 の store と同じ規律:

| 条件 | 結果 |
|---|---|
| 新しい正確な authority | `APPENDED`（write → flush → fsync） |
| byte 一致の再試行 | `REUSED` |
| 同じ `universe_id` ・内容が違う（審査者 ・審査の瞬間を含む） | `UNIVERSE_CONTENT_CONFLICT` |
| 同じ `(universe_key, version)` ・違う Universe | `UNIVERSE_VERSION_CONFLICT` |
| 破損 ・非正準 ・切断 ・物理的な重複 ・鍵 ／ 版の重複 ・偽造の id ・機械の分類 | fail closed（行番号つき。修復しない） |
| read_only ・型違い ・外部の変更 | `READ_ONLY` ・`INVALID_TYPE` ・`CONCURRENT_MODIFICATION` |

選択子: 正確な `get_by_universe_id(universe_id)` か正確な `get_by_key_version(universe_key, version: int)`。無ければ `None`（後の実行が
fail closed にする）。latest ・current ・default ・最高の版 ・全市場 ・曖昧な検索は無い。`list_metadata()` は (鍵, 版, id) の辞書順の
metadata（member の code ・意図 ・著者を含まない）で「現在」の意味は無い。`validate(data_root)` は OK ／ STORE_MISSING ／ STORE_CORRUPTION を
報告し修復しない。overwrite ・update-in-place ・delete ・fallback は無い。

## 4. private ／ 公開の境界

Universe の authority は private ・local だけ。provider code ・発行体 ・member ・著者を公開しない。Morning Brief ・/v2 ・Pages ・PWA ・
顧客 ・LLM への経路は無い。本 gate で J-Quants には触れない。

## 5. 境界（guard）

- 新規 runtime は model ・store の 2 module（他の runtime 49 ・Phase 8 の test ・先行の文書は P8_B4B anchor と byte 一致）。registry: `P8_B4B` ・
  `PHASE8_B5A_RUNTIME`。store は `IO_MODULES`（`__init__`: ab ・mkdir、`append`: ab ・write ・fsync だけ）。
- import は sanctioned の名前だけ（identity の形 ・`LIVE_RULES_VERSION` ・`MAX_MASTER_ROWS` ・core）。network ・旧来 ・P5 ・P6 ／ P7 ・
  評価 ・方針 ・identity の解決 ・適格の実行 ・公開の出力は無い。凍結の層 ・runner は Universe を知らない（配線は B5C）。

## 6. 観察（監督への報告。変更はしない）

- P8-OBS-100: Universe の identity は審査者 ・審査の瞬間を含まない（record の欄）。凍結 B1 の `policy_id` は著者 ・審査の瞬間を含むので、
  方針と Universe の identity の作り方は非対称。Universe の id は「範囲」の内容 address で、審査は 1 つの Universe に 1 つ（別の審査は衝突）。
- P8-OBS-101: 順を変えると `universe_id` は変わるが `membership_digest` は同じ。順は意味を持たないので、B5C の結果の集合は member の
  集合で比較でき、直列化の順は宣言の順に従う（非意味）。
- P8-OBS-102: member の code は正規化しない（空白 ・小文字 ・全角を拒む）。J-Quants の code は英字を含み得る（凍結 A1 の形）ので、
  5 桁目が 0 でない code も構文としては受け、普通株の判定（凍結 LIVE1 の `CODE_NOT_COMMON_EQUITY`）は実行の時に行う。
- P8-OBS-103: 適格の規則の版は閉じた束ね（現在の `LIVE_RULES_VERSION` だけ）。LIVE1 の版が上がると既存の Universe は構築できなくなる
  （fail closed）。版の移行は新しい Universe の版として人が審査する。
- P8-OBS-104: 同じ発行体の複数の code は Universe では別の member。B5C は identity の解決の後で束ね、束ねた code の数だけを記録する
  （主語は発行体）。Universe は SecurityId ／ IssuerId を持たないので、束ねは審査済みの identity だけに依る。
- P8-OBS-105: 単一の authority の日の規則は Universe に束ねるが、日付は持たない（Universe は日をまたいで再利用でき、各実行が自分の D0 を
  明示する）。複数日の継続（I1）を Universe が主張することは無い。
- P8-OBS-106: 著者は `human:` で始まることを要求した（B3 の方針の著者は形だけで接頭辞を要求しない）。機械の提案と人の authority を
  識別子の水準でも分けるため。B3 は凍結のまま。

## 7. 次の gate（開始しない）

P8-B5B（結果の集合の model ・集約 ・安全な投影。純）→ P8-B5C（複数発行体の private 実行器）。
