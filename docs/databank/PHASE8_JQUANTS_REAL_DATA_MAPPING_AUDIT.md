# PHASE 8 / P8-A2.5 — J-QUANTS REAL-DATA MAPPING AUDIT

J-Quants Light の実データの意味を、凍結した A1（identity）／ A2（PIT 観測）の契約へ対応付けられるかを **read-only** で監査した記録。
**取り込み ・live API ・network ・credential ・adapter ・A3 の指標 ・実の identity の登録は無い。** runtime は変えていない。

- 対象の問い: J-Quants の各欄は何を意味するか ／ いつ知り得るか ／ どの identity を指すか ／ 意味を作らずに A1 ／ A2 へ写せるか。
- 基準: P8-A2 `b686b008fe240eeb115b6c485ac4c5c642ebe2c9`（A2 の runtime はここと byte 一致）、P8-A1 `4162e9c`（A1 の runtime は
  byte 一致）、P8-A0 `76ebf0c`、Phase 7 `c1e95d3`、Phase 6 `5ef313a`。
- 変更: 本書（新規）・`CHANGELOG.md` ・凍結の登録に要る Phase 8 の registry と guard だけ（§34）。

---

## 0. 結論

1. **A1 ／ A2 は構造としては J-Quants Light を受け止められるが、欄の意味の大半は repo の証拠で確定しない。** repo にある一次の証拠は
   「欄の名前 ・entitlement ・件数 ・日付指定の可否」などの実測（OBSERVED_IN_PILOT）までで、期間の意味 ・純資産の定義 ・株数の定義 ・
   EPS の種類 ・単位 ／ 桁 ・欠損の表現 ・DiscTime の意味 ・訂正の挙動は INFERRED か UNKNOWN。後の認可 gate で確かめる事を V01〜V24
   に列挙した（§3）。
2. **identity**: J-Quants は発行体の identity も継続も証明できない（発行体の識別子が無い）。A1 は J-Quants だけでの Issuer ／ Security の
   登録を認めない（設計どおり）。実データの bootstrap には人の審査（一括の証明 ＋ 例外の個別審査）か別の authority が要り、**実の
   identity の authority を作る前に A1 の拡張の gate（訂正 ・統合 ・2 軸の遡及の解決）が必要**（§6〜§8）。A1 の宣言した範囲
   （合成 data ・単一 cutoff）での欠陥ではないので、本 gate で A1 は直さない。
3. **時刻**: 財務は DiscDate ／ DiscTime を確かめるまで `DATE(DiscDate)` だけが安全。一定の公表時刻（15:30 等）は使わない。日次四本値の
   公表時刻は repo に文書が無い（TOPIX の 16:30 頃だけが公式の記載として repo にある）。前向きの取得は取得時刻を上限とする。
   業者の調整値を後から取った履歴は PIT の authority にしない（§10・§11・§15）。
4. **raw snapshot の層が要る**（A2 runtime の外）。既存の light store の canonical は自然 key で先勝ち（後の改訂を黙って捨てる）で、
   SQLite 索引は canonical とずれる仕組みを持つ（§26・§27）。
5. **A3**: 最小の安全な集合は「同じ基準の売上成長率（as-reported）」と「営業利益率」の 2 つ。ROE ・PER ・PBR ・時価総額 ・EPS 成長率 ・
   価格の return ・変動率 ・流動性は BLOCKED（§28・§29）。
6. **過去の screen ／ backtest は NOT READY**（§31）。
7. **adapter の時期**: 案 C（本 gate で mapping を監査 → A3 は合成 data で最小集合 → 認可した公式確認 gate ・A1 の拡張 gate の後に
   最小の前向き取得の adapter → 直後に実データの検証）を推奨（§30）。
8. A1 ／ A2 ／ Phase 6 ／ Phase 7 の変更は不要。判定は §35。

---

## 1. この gate の目的と判定の軸

A2 は PIT の意味を構造として持つが、正しさは adapter の対応付けに依存する。本書は引き継いだ所見（P8-OBS-1 ・2 ・6 ・9 ・10 ・11 ・
12 ・14 ・17 ・18 ・22 ・23 ・24 ほか）が、次のどれを止めるかを決める（§32 の「止める gate」の列）。

| 略号 | gate |
|---|---|
| A3 | A3 の派生指標の実装（合成 data） |
| ADP | 実 J-Quants の adapter が A1 ／ A2 の authority へ書くこと |
| HIST | 過去の screen ・backtest を PIT として認めること |
| CLOSE | Phase 8 の完了 |

---

## 2. 証拠の出所と分類

本書は network ・API ・credential ・data root を使っていない。読んだのは git の中身だけ。

| 記号 | 出所 |
|---|---|
| [HEAD] | 現在の系統: `src/intelligence/market/jquants_light_datasets.py`（dataset 台帳。run #1 の実測）・`jquants_records.py`（parser）・`jquants_light_store.py` ・`jquants_v2.py` ・`jquants_v2_client.py` ・`tokyo_calendar.py` ・`topix_freshness.py` ・`src/intelligence/facts/jquants_builder.py` ・`src/intelligence/internals/universe.py` ・`price_movement.py` ・`knowledge/market_series/core_series.yaml` ・`docs/databank/PHASE5_ENTRY_CONTRACT.md` |
| [UNMERGED] | 現在の系統に無い履歴 branch（先頭 `247b85b`）: `docs/databank/JQUANTS_LIGHT_CAPABILITY_MATRIX.md` ・`JQUANTS_LIGHT_CORE_ARCHITECTURE.md` ・`JQUANTS_PRODUCTION_DATA_STRATEGY.md` ・`JQUANTS_FIRST_RULE.md` ・`src/intelligence/jquants_ops/`（registry ・master_refresh ・corporate_actions ・financial_summary ・earnings_calendar）・その test と CHANGELOG |
| 実測の記録 | P2-H run #1（entitlement の probe）／ #3（pilot）2026-09-01、Phase 3.5 run #20 2026-09-02、Phase 3.6 run #21 2026-09-02、P5 A0.7B-R2（TOPIX 5 年）2026-09-17 |

証拠の分類（各 mapping に付ける）:

| 分類 | 意味 |
|---|---|
| DOCUMENTED | J-Quants の公式文書の内容が repo に書かれているもの。**該当は TOPIX の経路だけ**（V2 の base URL ・`x-api-key` の header ・TOPIX の path と `from` ／ `to` ／ `pagination_key` ・応答の `data` ・TOPIX は Light 以上 ・更新は毎営業日 16:30 頃。`jquants_v2.py` ・`topix_freshness.py` ・`core_series.yaml` が公式クイックスタート V2 を出典として記す）。個別銘柄 ・財務の欄の公式文書は repo に無い |
| OBSERVED_IN_PILOT | live の実行の記録（2026-09-01〜02、2026-09-17）。entitlement（200 ／ 403 ／ 400）・欄の名前 ・件数 ・日付指定の可否 ・master の差分 ・AdjFactor ≠ 1 の発生 |
| INFERRED | 開発者の comment ・parser の命名 ・fixture の形（[UNMERGED] の test の fixture 行は run #1 の欄名に「基づいて」手で書いた例で、値は観測ではない）・欄名の読み ・一般知識 |
| UNKNOWN | repo に証拠が無い |

- 実測はすべて日付つきで、その後に確かめていない。Light plan ・V2 の schema は変わり得る。
- P8-A0 §4 ／ §6 は一部を強く書いていた（「調整値は遡って変わる」「訂正は新しい DiscNo」）。本書はこれらを **INFERRED に分類し直す**
  （A0 は凍結なので本書に記録する。P8-OBS-34）。
- 本書は実在の code ・社名 ・応答の本文を再掲しない。

---

## 3. 外部確認の決定（NEEDS_OFFICIAL_JQUANTS_VERIFICATION）

repo の証拠で意味が決まらない欄は推測で埋めず、以下を後の**認可された** gate で確かめる（本 gate は live を呼ばない）。確かめ方は
公式の API 仕様を一次とし、足りない所だけ最小の標本の取得で補う（credential は runtime injection だけ、応答の本文 ・実の code を
repo に残さない）。

| id | 確かめる事 | 影響する mapping |
|---|---|---|
| V01 | DiscDate ／ DiscTime の意味（TDnet の公表時刻か）・time zone ・書式 ・精度（分 ／ 秒）・DiscTime が無い行の意味 | §15 の知識の時刻 |
| V02 | DiscNo の一意性 ・再取得での安定性 ・訂正開示と元の開示の DiscNo の関係 | §16・§25 |
| V03 | DocType の全値。連結 ／ 単体 ・会計基準 ・決算 ／ 予想の修正 ／ 訂正の区別を含むか | §13・§14・§23 |
| V04 | CurPerType の全値と CurPerSt ／ CurPerEn の関係。四半期の値が期首からの累計か単独の四半期か | §14 |
| V05 | F* と NxF* が指す会計年度（DocType ／ CurPerType ごと）。予想の幅（上限 ／ 下限）・半期の予想の有無 | §13 |
| V06 | NC*（単体）の欄の名前と意味。子会社の無い発行体で接頭辞なしの欄が何を持つか | §14 |
| V07 | Eq ・ShEq ・EqAR ・BPS ・TA の定義（純資産 ／ 株主資本 ／ 親会社の所有者に帰属する持分） | §20 |
| V08 | NP の帰属（親会社株主 ／ 全体）・EPS ／ DEPS の種類（基本 ／ 希薄化） | §19・§28 |
| V09 | AvgSh ・ShOutFY ・TrShFY の定義（基準日 ・自己株式を含むか ・どの種類の株式か）。四半期の行での基準日 | §17・§18 |
| V10 | CFO ・CFI ・CFF ・CashEq が載る期間の種類と、累計 ／ 期間の別 | §21 |
| V11 | 金額 ・1 株当たり ・株数の単位 ・桁 ・通貨。円以外で報告する発行体の扱い | §22 |
| V12 | 欠損の表現（null ・空文字 ・key が無い ・`-` ・その他の印） | §23 |
| V13 | 行が後から上書きされるか。後の問い合わせが旧版なしに訂正値だけを返すか。RetroRst の意味 | §15・§16・§26 |
| V14 | 日次四本値: O ／ H ／ L ／ C が生値か ・売買の無い日の表現 ・Vo ／ Va の単位 ・公表時刻 ・訂正の挙動 | §10 |
| V15 | AdjO〜AdjC ・AdjVo ・AdjFactor の意味、後の corporate action で過去の値が書き換わるか、対象の事象の種類。MktCap の定義 | §11・§18 |
| V16 | UL ／ LL ・ExRT（日次四本値）・Mrgn ・ProdCat（master）の意味 | §10・§5 |
| V17 | master の `?date=` の深さ、過去の snapshot がその日の状態の再現か（現在の属性を遡って当てたものでないか）、Mkt の値の一覧、東証以外の上場を含むか、5 桁の code と 4 桁の code の関係 ・5 桁目の意味 | §5・§9 |
| V18 | code の変更 ・再利用の規則（取引所の規則。J-Quants の外の公式文書） | §5 |
| V19 | 決算発表予定の履歴の保持と変更の表し方 | §4 |
| V20 | HolDiv の全値（観測は `0` ・`1` ・`3`） | §4 |
| V21 | Light の dataset ごとの履歴の深さ（実測は TOPIX の 5 年だけ） | §9・§31 |
| V22 | 利用規約上の raw の保存 ・再配布 ・派生 data の条件 | §26 |
| V23 | 同じ開示が code 指定と date 指定で同じ行として返るか | §24 |
| V24 | 複数の上場物を持つ発行体の財務サマリーが、どの code で何行返るか | §5・§24 |

---

## 4. dataset の棚卸し

Phase 8 に関わる Light の dataset。identifier ・欄 ・件数は OBSERVED_IN_PILOT、意味の欄は明記した分類に従う。

| dataset（endpoint） | Phase 8 の役割 | identifier | 時間の意味 | 履歴（実測） | 改訂 | PIT の適性 | 制約 |
|---|---|---|---|---|---|---|---|
| listed_master（`/equities/master`） | Security の候補 ・識別子 ・表示名 ・市場区分 ／ 業種 ／ 規模区分の参照 | Code（5 桁。英字を含む code を観測） | snapshot の基準日 `Date`。`?date=` で過去の日付を指定できる（run #20 で 1 日を取得） | 当日 4,441 行。過去日 4,439 行。週 1 の snapshot 8 本（run #21） | snapshot の間の変化は差分でしか見えない（約 7 週（2 本の snapshot の間）で追加 16 ・削除 18 ・市場の変更 1 ・規模区分の変更 1） | **取得した snapshot の日だけ**。上場日 ・廃止日の欄が無い | 発行体の識別子（法人番号 ・EDINET code ・ISIN）が欄に無い。削除が廃止か code の変更かを区別できない |
| daily_bars（`/equities/bars/daily`） | 市場の観測（生値 ・業者の調整値） | Code ＋ Date | session の日。公表時刻は repo に文書なし（UNKNOWN。registry の「夕方」は INFERRED） | code 指定 1 年 244 session。date 指定 46 session × 約 4,441 行 | 生値の訂正は UNKNOWN。調整値の遡及は INFERRED（§11） | 生値は前向きの取得なら可。調整値は取得時点の版だけ | MktCap ・Va は A2 に欄が無い |
| fins_summary（`/fins/summary`） | 実績 ・会社予想 | Code ＋ DiscNo（INFERRED の開示の単位） | DiscDate ／ DiscTime（意味は V01） | code 指定 20〜31 行 ／ code。date 指定 1 日 14 行（run #21） | 世代が複数ある（件数から INFERRED）。上書きの有無は UNKNOWN | 規則つきで可（§15）。期間 ・単位 ・定義の確認が前提 | 株数 ・単体（NC*）は legacy の parser に無い |
| equities_earnings_cal（`/equities/earnings-calendar`） | 前向きの財務の取得の予定づくりだけ（A2 の観測ではない） | Code ＋ Date | 取得時点で公表済みの予定。知り得た時刻は取得時刻 | 将来の分だけ（run #1 は 1 行） | 予定の変更は新しい record（[UNMERGED] の設計） | 過去の screen には使えない | 履歴の保持は V19 |
| markets_calendar（`/markets/calendar`） | window の指標の session の定義（将来の参照の authority） | Date | 参照 data。HolDiv の `1` だけを営業日（TOPIX の観測日と 21／21 一致を実測） | 401 暦日（run #3）、P5 で 1,827 行 | 将来の日の追加 | 営業日の判定に使える。Phase 8 に authority が無い（P8-OBS-28） | `0` ・`3` を営業日としない。全値は V20 |
| topix（`/indices/bars/daily/topix`） | 市場の文脈だけ（screen の基準に使わない） | Code `0000` | 更新は毎営業日 16:30 頃（DOCUMENTED）。P5 は 15:30 を as_of に使う（P8-OBS-5） | 2021-09-17〜2026-09-17（10 年の要求は plan で拒否） | UNKNOWN | Market Data Bank の所有。Phase 8 は読まない | — |

Phase 8 の設計に効く NOT_ENTITLED ほか:

| dataset | 状態（実測） | Phase 8 への影響 |
|---|---|---|
| fins_details（`/fins/details`） | 403（Standard） | 詳細な財務の定義で純資産 ・株数を確かめる道が無い。財務サマリーの欄だけで進める |
| fins_dividend（`/fins/dividend`） | 403（Standard） | 配当 ・配当利回りは使えない（DEFER） |
| indices_bars_daily ・markets_short_ratio ・equities_bars_am ・markets_breakdown | 403（Standard ／ Premium） | Phase 8 に不要 |
| fins_earnings_date（`/fins/earnings-date`） | 400（引数の契約違い）。entitlement UNKNOWN | 使わない |
| investor_types（`/equities/investor-types`） | 200（週次・市場区分の単位） | 銘柄の単位ではないので NOT_RELEVANT |
| 分割 ・併合などの corporate action の専用の dataset | Light の台帳に無い（観測されていない） | 事象の入力は AdjFactor から検知するか、別の認可が要る（P8-OBS-24） |
| 上場 ／ 廃止の履歴 ・発行体の識別子の dataset | Light の台帳に無い | identity の bootstrap に人の審査か別の authority が要る（§6） |

---

## 5. identity の対応

J-Quants の Code → A1 の SecurityId → A1 の IssuerId。

| 問い | J-Quants の master で示せる事 | 示せない事 | 証拠 | A1 への写し方 |
|---|---|---|---|---|
| 4 桁 ／ 5 桁 | Code は 5 桁（英字を含む値もある） | 4 桁の code との関係、5 桁目の意味（legacy は「末尾 `0` が普通株」とする） | 5 桁: OBSERVED_IN_PILOT ／ 関係: INFERRED（V17） | `IdentifierAssignment(JQUANTS_CODE)`（A1 の形 `^[0-9A-Z]{5}$` に合う）。4 桁の `LOCAL_CODE` は V17 の後だけ |
| code の変更 | 旧 code が消え新 code が現れる事実（snapshot の差分） | 同じ上場物かどうか | UNKNOWN（V18） | 継続は A1 の継続の出所（取引所 ・発行体の開示 ・人の審査）が要る。J-Quants では立てない（A1 の設計どおり） |
| code の再利用 | ある日にその code の行がある事実 | 前の保持者と同じか | UNKNOWN（V18） | A1 §10 の規則（前の割り当ての終わりが先に知られている時だけ） |
| 上場の始まり | 初めて現れた snapshot の日（週 1 なら 7 日の幅） | 実の上場日 | 上場日の欄なし: OBSERVED_IN_PILOT | `ListingStart` の `effective_from` を作らない。日次の snapshot で初出の日 ＝ 上場日と確かめられた時だけ（V17）。既に上場していた物の「少なくとも D から上場」を A1 は表せない（P8-OBS-6） |
| 上場廃止 | 行が消えた snapshot の日 | 廃止か code の変更か data の欠けか | INFERRED | 自動で `ListingEnd` を書かない（A1 に訂正が無いので取り消せない）。保留して審査 |
| 市場区分の変更 | Mkt ／ MktNm の変化 | その時刻 | OBSERVED_IN_PILOT（約 7 週で 1 件） | A1 の venue は `TSE` だけで区分を持たない（P8-OBS-14）。参照の観測の gate まで写さない |
| 1 発行体の複数の上場物 | 行は code ごと | 同じ発行体か | 発行体の識別子なし: OBSERVED_IN_PILOT | 候補の束ね（code の先頭 4 文字が同じ等）は INFERRED で、人の審査を通す |
| 発行体の継続 | なし | すべて | — | J-Quants では立てない |
| 再上場 | なし | すべて | UNKNOWN | 既定は新しい SecurityId（A1 §13） |

- 社名（CoName ／ CoNameEn）は `DisplayName` にだけ写す。**同じ社名 ＝ 同じ IssuerId としない。**
- 登録の anchor は data から計算し直さない。「code ＋ 初出の日」を anchor にすると、後で履歴を深く取った時に初出の日が変わり、同じ
  上場物に別の SecurityId ができる。anchor は bootstrap の一括の中で一度だけ割り当てる（P8-OBS-29）。
- 財務サマリーは Code で返る。複数の上場物を持つ発行体で、どの code で何行返るかは V24。Issuer への写しは Code → Security →
  Issuer の登録済みの鎖を通し、鎖が無ければ写さない。

---

## 6. Issuer の bootstrap

A1（凍結）の制約: `ISSUER_REGISTRATION` ／ `SECURITY_REGISTRATION` の出所は取引所 ・発行体の開示 ・人の審査だけ（J-Quants 単独は不可）。
anchor は不変。`SecurityRegistration` の `issuer_id` は payload の一部で変えられない。訂正の record は無い。

| 案 | 内容 | 正しさ | 規模 | 将来の訂正 | A1 との適合 |
|---|---|---|---|---|---|
| A. 1 Security ＝ 仮の 1 Issuer | 普通株の code ごとに Issuer を 1 つ | 単一の上場物の発行体では正しい。複数の上場物では発行体が割れ、発行体の財務が重複 ／ 誤帰属 | 小 | 後の統合が要る（P8-OBS-10） | 仮の状態は A1 に無い。出所に人の審査が要るので実質は D |
| B. 人の審査の一括 | 約 4,400 行を人が確かめて登録 | 高い（疲れによる誤りは残る） | 大 | 少ないが 0 ではない | 適合（`HUMAN_REVIEWED`） |
| C. 別の authority の対応表 | EDINET code ・法人番号 ・ISIN などで発行体を決める | 最も高い | 中 | 少ない | 新しい出所の認可が要る。A1 に発行体の識別子の scheme が無い（`IdentifierAssignment` は Security だけ）→ A1 の拡張 |
| D. 混成 | J-Quants の master から規則で候補（普通株 1 code ＝ 1 Issuer）を決定論で作り、規則と例外の一覧を人が一括で証明（`HUMAN_REVIEWED`）。例外（先頭 4 文字の共有 ・同名 ・code の変更 ・消えた行）は個別審査。後で C の識別子を足す | 規則の範囲で高い。例外は人が見る | 中 | 例外の誤りは残るので訂正の意味論が前提 | 適合。発行体の識別子は A1 の拡張の後 |

**推奨: D**（D-P8-A2.5-2）。普通株から始め、他の種類は審査を通るまで登録しない。人の審査の理由の文は repo に残さない（出所の参照
だけ）。**最初の実の登録の前に §7 の訂正の意味論が要る。** 実装しない。

---

## 7. identity の訂正

凍結の A1 で bootstrap が誤った場合:

| 誤り | A1 の現状 | 結果 |
|---|---|---|
| IssuerId（別の会社を 1 つに ／ 1 社を 2 つに） | Issuer の登録を取り消す ・統合する record が無い | 発行体の財務が恒久に誤った Issuer に付く |
| Security → Issuer の対応 | `issuer_id` は登録の payload の一部で不変 | 付け替えられない |
| code の割り当て | `IdentifierRetirement` は「終わった」の意味で「誤りだった」ではない。重なる正しい割り当ては `CONFLICTING_ASSIGNMENT` で入らない | 誤りが正しい data を塞ぐ（自動の修復はしない） |
| 継続の判断（2 本目の識別子） | 取り消せない | 別の上場物の履歴が混ざる |

実の authority を作る前に要る意味論（提案。実装しない）:

1. **取り消し**（対象の record id ・known_at ・人の審査 ／ 取引所の出所 ・閉じた理由の語彙）。取り消した record は消さない。厳密の
   解決は cutoff 時点の知識どおり（取り消しを知る前は誤りのまま）、遡及の解決は訂正後の像を返す。
2. **Issuer の統合 ／ 別名**（存続する id と別名。id を書き換えない）。
3. **Security → Issuer の対応の supersession**（対応を独立した record にするか、訂正の record を足す）。
4. **継続の取り消し**。
5. 訂正の状態を示す resolver の status と、未来の訂正が過去の cutoff の厳密の答えを変えない決定論。

**明記: 実の identity の authority を作る前に、A1 の拡張 ／ 是正の gate（仮称 P8-A1R: identity の訂正 ・遡及の解決 ・bootstrap の
意味論）が必要。** A1 の凍結範囲（合成 data）での欠陥ではないため、本 gate では直さない（D-P8-A2.5-3）。

---

## 8. identity の知識の時刻

A1 の `known_at` は authority が知った時刻（system の知識）、A2 の `known_at` は世界で知り得た時刻。2026 年に bootstrap した
identity では、2024 年の cutoff で主語が `NOT_YET_KNOWN` になり、A2 は 2024 年の観測を `SUBJECT_NOT_RESOLVED` にする（P8-OBS-18。
A2 の test で示した挙動）。

| 案 | 内容 | 正しさ | 過去の screen | A1 への影響 | 危険 |
|---|---|---|---|---|---|
| A. 厳密な system の知識の再生 | 今のまま | 最も厳密 | bootstrap より前は不可 | なし | 過去を見られない |
| B. 世界の時刻での再生 | A1 の `known_at` を世界の時刻にする | 誤り（system の知識を偽る） | 可 | A1 §8 の意味に反する | bootstrap の判断の時刻と後の訂正が再生に見えない |
| C. 明示の遡及 ／ 参照の mode | 知識の cutoff ＝ 固定した authority の版 R、有効時間 ＝ 過去の cutoff で解決し、結果に「identity は遡及（R）」の印を付ける。観測は厳密の PIT のまま | identity だけ後知恵を明示 | 可（R で再現） | **A1 の resolver は単一 cutoff で、知識と有効時間を分けられない**（A1 の外の包みでは作れない）→ A1 の拡張 | survivorship: authority が過去の上場物（廃止済み）を含まないと偏る |
| D. identity の 2 時刻の model | record に世界の時刻と system の時刻の両方 | 最も表現力が高い | 可 | A1 の大きな変更 | 世界の時刻（上場日）を J-Quants が持たないので効果が薄い |

**推奨**（D-P8-A2.5-1）: **A を既定**にし、過去の screen の前に **C を A1 の拡張の gate で導入**する（既定にしない ・版 R を必ず記録 ・
過去の上場物を日次の snapshot から登録してから）。B は採らない。D は今は採らない。実装しない。

---

## 9. master の PIT

- 現在の snapshot 1 つからは任意の cutoff の上場の母集団を作れない（上場 ／ 廃止の履歴の欄が無い: OBSERVED_IN_PILOT）。
- `?date=` の過去の snapshot（run #20 で 1 日を取得: OBSERVED_IN_PILOT）で、取得できる日の有効時間の母集団は作れる。ただし深さは
  UNKNOWN（V17 ・V21）、過去の snapshot がその日の状態の忠実な再現かも UNKNOWN（V17）、知り得た時刻は取得時刻。
- 週 1 の snapshot は最大 7 日の穴を残す（[UNMERGED] の既知の制約）。session の単位で正確にするには session ごとの snapshot が要る
  （1 session ＝ 1 request、約 1.45 MB）。
- **最も早い擁護できる境界**:
  - 厳密（§8 の A）: 前向きに取った最初の snapshot の取得時刻。それより前は `BEFORE_COVERAGE`。
  - 遡及（§8 の C を認めた場合）: V17 ・V21 で確かめた深さの範囲で、ある session S0 から後の**全 session** の snapshot を取得 ・検証
    済みのとき、その S0。S0 より前は fail closed。
- **後の snapshot を前の session へ当てない。** HEAD の universe の「最古の master を遡って適用し印を付ける」は Phase 8 では禁止。
- A1 の coverage（J-Quants を出所にできる）はこの境界とちょうど一致させ、上限の無い範囲にしない。

---

## 10. 日次四本値（生値）

| 欄 | 意味 | 生値 ／ 調整値 | 証拠 | A2 への写し | 条件 |
|---|---|---|---|---|---|
| Date | 取引の session の日 | — | OBSERVED_IN_PILOT（1 年 244 session、カレンダー ・TOPIX と一致） | `session_date` | — |
| O ／ H ／ L ／ C | その日に付いた四本値 | 生値 | INFERRED（命名、Adj* と別の欄で併存: OBSERVED、生値と調整値の騰落率の食い違いの検出: OBSERVED） | `OPEN` ／ `HIGH` ／ `LOW` ／ `CLOSE` ・`RAW_REPORTED` ・`PRICE` ・JPY ・`ONE` ・`source_field` は欄名そのまま | V14 |
| Vo | 出来高 | 生値 | INFERRED（株数） | `VOLUME` ・`TRADED_VOLUME` ・`ONE` | V14 |
| Va | 売買代金 | — | INFERRED（円） | A2 に欄なし（P8-OBS-27） | — |
| UL ／ LL | 値幅の上限 ／ 下限 | — | INFERRED | 写さない | V16 |
| ExRT | UNKNOWN | — | UNKNOWN | 写さない | V16 |
| MktCap | 業者の時価総額 | — | 定義 UNKNOWN | 写さない（§18） | V15 |

- **公表の時刻**: 日次四本値の公表時刻の公式の記載は repo に無い（TOPIX の 16:30 頃だけ DOCUMENTED）。[UNMERGED] の registry は
  日次四本値の既知の時刻を「session 15:30 JST（東京クローズ）」とするが、これは立会の終わりの慣習で公表時刻ではない（INFERRED）。立会の時間が時期で違った
  可能性も repo では確かめられない。**写し方: 前向きの取得は `TIMESTAMP(取得時刻)`（安全な上限）。** 公式の公表時刻は V14 で
  確かめた後だけ使う。一定の時刻は使わない。
- **訂正**: UNKNOWN（V14）。取り直して生値が変われば A2 の新しい revision（知識 ＝ 取得時刻）にし、上書きしない。
- **売買の無い日 ／ 停止**: UNKNOWN（V14）。legacy は「行はあるが C が空」を想定する（`no_close`: INFERRED）。行があって C が空 →
  `MISSING`（`NOT_APPLICABLE` と推測しない）。Vo が `0` → `VALUE_PRESENT` の 0。行が無い → A2 の record を作らない（coverage の下で
  `NOT_FOUND`）。0 の出来高の record を作らない。価格は正でなければ A2 が拒否する（`INVALID_SIGN`）→ adapter は保留。

---

## 11. 調整後価格

- 欄 AdjO ・AdjH ・AdjL ・AdjC ・AdjVo ・AdjFactor: OBSERVED_IN_PILOT。AdjFactor ≠ 1 の日がある（Phase 3.5 の実測で 45 session に除外 26 件、
  run #21 で 3 session に 7 件。検知の規則は「AdjFactor ≠ 1 または生値と調整値の騰落率の食い違い」）。
- 分割 ・併合の調整という意味: INFERRED。**後の corporate action で過去の調整値が書き換わるか: INFERRED（観測は無い）→ V15。**
  配当 ・権利落ちを含むか: UNKNOWN（総 return の欄は無い: INFERRED）。
- 業者の調整値の位置づけの比較:

| 位置づけ | 評価 |
|---|---|
| A2 の authority（取得時刻を知識とする版つき・前向きだけ） | PIT として正しい。後の分割の後は取り直すまで古い版のまま → 使う側は版の知識を確かめる |
| 派生の参照だけ（A2 に入れない） | 安全だが、前向きの版を捨てる |
| PIT の screen に使わない | 最も安全 |
| 業者の版の時刻つきで版を持つ | 業者は版の時刻を出さない（UNKNOWN）ので不可 |

**推奨**（D-P8-A2.5-5）: `PROVIDER_ADJUSTED` は**前向きに取った版だけ**を A2 の authority にし、知識は `TIMESTAMP(取得時刻)`、
`adjustment_ref` は raw snapshot の id。値が変われば新しい revision。**後から取った調整値の履歴は、その取得より前の cutoff の authority に
しない**（参照だけ）。corporate action を跨ぐ PIT の指標は、生値 ＋ cutoff までに知り得た調整係数（session ごとに取った AdjFactor を
将来の corporate action の入力として）で作る方向。A2 は意図して `ADJUSTMENT_FACTOR` を持たない（guard CI〜CL）。調整は実装しない。

---

## 12. 財務サマリーの棚卸し

欄の名前はすべて OBSERVED_IN_PILOT（run #1）。意味の列は **INFERRED**（欄名 ・legacy の comment）で、確認の id を付けた。

| 欄 | 推定の意味 | 種類 | A2 への写し | 確認 |
|---|---|---|---|---|
| Code | 上場物の code | 鍵 | Code → Security → Issuer の鎖 | V24 |
| DiscDate ／ DiscTime | 開示の日 ／ 時刻 | 時刻 | `KnowledgeTime`（§15） | V01 |
| DiscNo | 開示の単位の番号 | 鍵 | 出所の record の参照（§25） | V02 |
| DocType | 書類の種類 | 分類 | 連結 ／ 単体 ・予想の修正の判定 | V03 |
| CurPerType ・CurPerSt ・CurPerEn | 当期の期間の種類と期間 | 期間 | `ReportingPeriod`（§14） | V04 |
| CurFYSt ・CurFYEn | 当期の会計年度 | 期間 | 同上 | V04 |
| NxtFYSt ・NxtFYEn | 翌期の会計年度 | 期間 | 翌期予想の対象の期間 | V05 |
| Sales | 売上高 | 実績 | `REVENUE` | V03 ・V11 |
| OP | 営業利益 | 実績 | `OPERATING_INCOME` | V03 ・V11 |
| OdP | 経常利益 | 実績 | A2 に欄なし | — |
| NP | 当期純利益（帰属は未確認） | 実績 | `NET_INCOME`（V08 の後） | V08 |
| EPS ／ DEPS | 1 株当たり利益 ／ 希薄化後 | 実績 | `EPS`（基本と確かめた時だけ）／ 写さない | V08 |
| BPS | 1 株当たり純資産 | 実績（1 株当たり） | A2 に欄なし | V07 |
| ROE ・EqAR | 業者の比率 | その他 | 写さない | V07 ・V11 |
| TA | 総資産 | 実績 | `TOTAL_ASSETS` | V07 |
| Eq ／ ShEq | 純資産 ／ 株主資本の類（どちらが何かは未確認） | 実績 | `EQUITY` は**保留**（§20） | V07 |
| CFO ・CFI ・CFF ・CashEq | CF 3 種 ・現金同等物 | 実績 | CFO → `OPERATING_CASH_FLOW`（V10 の後）。他は写さない | V10 |
| AvgSh ・ShOutFY ・TrShFY | 期中平均株数 ・期末発行済 ・期末自己株式 | 実績 | `SHARES_OUTSTANDING` は**保留**（§17） | V09 |
| FSales ・FOP ・FOdP ・FNP ・FEPS | 会社予想（対象の年度は未確認） | 予想 | `FUNDAMENTAL_FORECAST`（OdP を除く） | V05 |
| NxFSales ・NxFOP ・NxFOdP ・NxFNp ・NxFEPS | 翌期の会社予想 | 予想 | 同上（対象 ＝ NxtFYSt〜NxtFYEn） | V05 |
| RetroRst | 遡及修正の印 | その他 | A2 に欄なし（P8-OBS-27） | V13 |
| NC* | 単体の値（存在の記述だけ・欄名は未記録） | 実績 ／ 予想 | `NON_CONSOLIDATED`（V06 の後） | V06 |

- 欄名は大文字 ／ 小文字を含め観測どおりに照合する（`NxFNp` の小文字 `p` を正規化しない）。
- 経常利益は日本の会計基準の概念で A2 に欄が無い。最小の A3 に要らない。

---

## 13. 実績と予想

| 欄の群 | 種類 | A2 の class | 規則 |
|---|---|---|---|
| Sales ・OP ・NP ・EPS ・TA ・Eq ／ ShEq ・CFO ・株数 | ACTUAL（INFERRED） | `FUNDAMENTAL_ACTUAL` | 期間 ＝ 当期の期間 |
| F*（FSales ・FOP ・FNP ・FEPS） | COMPANY_FORECAST（INFERRED） | `FUNDAMENTAL_FORECAST` | 対象の期間は V05 まで決めない |
| NxF*（NxFSales ・NxFOP ・NxFNp ・NxFEPS） | COMPANY_FORECAST（INFERRED） | `FUNDAMENTAL_FORECAST` | 対象 ＝ NxtFYSt〜NxtFYEn（V05） |
| FOdP ・NxFOdP ・OdP | ACTUAL ／ FORECAST | 写さない | A2 に欄なし |
| ROE ・EqAR ・BPS ・DEPS ・RetroRst | OTHER ／ UNKNOWN | 写さない | — |

- **予想は実績の slot に入らない**: A2 は class ・型 ・slot が別で、予想は `FORECAST_FIELDS` だけ（test AA〜AC）。adapter は class を
  **欄名だけ**で決め（完全一致の対応表）、値や DocType の推測では決めない。
- 予想の修正の開示（DocType の推定）に実績の欄が載るかは UNKNOWN → 載っていたら保留。
- 予想の欄は一部だけ埋まることがあり得る → 欄ごとに `MISSING`。
- F* の対象の年度は曖昧（決算の開示の「当期」が終わった年度か始まった年度か）。V05 で確かめるまで F* を写さない（P8-OBS-31）。

---

## 14. 財務の期間の意味（P8-OBS-22）

repo で分かるのは「期間の欄がある」ことだけ（OBSERVED_IN_PILOT）。値の例は fixture（年度: 期首 ＝ 年度の初め、期末 ＝ 年度の終わり）で
INFERRED。

| 期間 | 現在の証拠 |
|---|---|
| 年度（FY） | 欄の形から構造で判定できる（期間 ＝ 年度）。CurPerType の値は UNKNOWN |
| 第 1 四半期の累計 ／ 上半期の累計 ／ 第 3 四半期の累計 | UNKNOWN（V04） |
| 通期 | 年度と同じ（UNKNOWN の値の名前を除く） |
| 単独の四半期 | UNKNOWN（V04） |

写し方（V04 の後。今は写さない）:

- 期間 ＝ 年度（CurPerSt ＝ CurFYSt かつ CurPerEn ＝ CurFYEn）→ `FISCAL_YEAR`。
- 四半期の種類で CurPerSt ＝ CurFYSt → `CUMULATIVE_YEAR_TO_DATE`（quarter は CurPerType から。上半期 ＝ 2）。**値が
  [CurPerSt, CurPerEn] に対応すると確かめた時だけ。**
- 四半期の種類で CurPerSt ≠ CurFYSt → `SINGLE_QUARTER`（同上）。
- CurPerType と日付が合わなければ保留（fail closed）。単独の四半期を**引き算で作らない**（A2 ・本 gate とも）。
- 会計年度の初め ／ 終わりは CurFYSt ／ CurFYEn。決算期の変更で年度が 12 か月でない場合、A2 は 550 日まで受ける。比べられるかは
  A3 の規則（NOT_COMPARABLE）。
- 連結 ／ 単体: 接頭辞なしの欄 ＝ 連結は INFERRED（legacy の comment）、NC* の存在は OBSERVED_IN_PILOT（名前は未記録）。子会社の無い
  発行体で接頭辞なしの欄が単体の値を持つかは UNKNOWN。`StatementBasis` は V03 ・V06 の後に決める。

P8-OBS-22 は repo では解けない。構造の規則だけを決めた（BLOCKED_PENDING_OFFICIAL_VERIFICATION）。

---

## 15. 開示時刻（CRITICAL）

- DiscDate: OBSERVED_IN_PILOT（必須の欄。`?date=` の鍵として 1 日 14 行を取得）。DiscTime: 欄は OBSERVED_IN_PILOT、書式 ・意味 ・time zone ・
  欠損の挙動は UNKNOWN（fixture の `15:00` 形は INFERRED）。他の公表の時刻の欄は観測されていない。
- legacy の `jquants_builder._known_at` は DiscTime を無視して開示日の 15:30 JST を一律に使う（P8-OBS-1。Phase 8 は使わない）。

| 条件 | A2 の `KnowledgeTime` |
|---|---|
| DiscDate が正しく、DiscTime があり、書式と意味を V01 で確かめた | `TIMESTAMP`（DiscDate ＋ DiscTime、確かめた time zone）。精度は与えられたまま（丸めない） |
| DiscDate が正しく、DiscTime が空 ・null ・無い | `DATE(DiscDate)` |
| DiscTime があるが未確認 ・解釈できない | `DATE(DiscDate)`（時刻を推測しない）＋ 印 |
| DiscDate が無い ・不正 | 行を保留（取得時刻を開示時刻として使わない） |
| すべて | 一定の時刻（15:30 等）を作らない。A2 の不変条件（実績は期末の翌日より前に知り得ない）を満たす |

- `DATE(DiscDate)` が安全なのは DiscDate が実の開示日より早くない場合（V01）。`DATE` の日の途中の cutoff は A2 が
  `INSUFFICIENT_TIME_PRECISION` を返す（構造で検証済み）。
- **前向きの取得と後からの取得の違い（P8-OBS-17）**: 開示時刻は**元の値**を知り得た時刻。開示から時間が経って取った値に開示時刻を
  付けてよいのは、V13 で「行は開示ごとに不変で、訂正は別の行で来る」と確かめた時だけ。そうでなければ知識は取得時刻にする
  （過去の cutoff では使えない）。

---

## 16. 訂正 ／ 修正 ／ 遡及修正

| 事象 | 現在の証拠 | 写し方 |
|---|---|---|
| 予想の修正 | 別の開示の行（1 code に 20〜31 行ある件数から INFERRED） | 同じ slot の revision（`supersedes`） |
| 訂正開示 | 新しい行か ・行の置き換えか ・両方か UNKNOWN（V02 ・V13） | 別の行なら revision。置き換えなら取り直しの差（下） |
| 遡及修正 | RetroRst の欄: OBSERVED_IN_PILOT。値 ・意味は UNKNOWN。過去の期の修正後の比較値の欄は観測されていない | A2 は as-reported だけを持つ |
| 重複 ／ 再発行 | UNKNOWN | §24 |

- 訂正と元の開示を結ぶ provider の指し先は観測されていない → 結び付けは A2 の slot（発行体 ・欄 ・基準 ・期間）と知識の時刻の順で行う。
- **後の問い合わせが旧版なしに訂正値だけを返す可能性は否定できない（UNKNOWN）→ 返すものとして設計する。**
- adapter が保つべき事: すべての取得を raw snapshot に残す（§26）。行ごとに自然 key と digest。slot ごとに異なる値を revision にする。
  **同じ DiscNo が後で別の digest で返れば、業者側の改訂として新しい revision（知識 ＝ 取得時刻）＋ 印**にし、上書きしない。
- A2 の制約: 開示時刻（TIMESTAMP）の元の値の後に、同じ日の `DATE` 精度の訂正を足すと `NON_MONOTONIC_KNOWLEDGE` で拒否される（DATE の
  最初の瞬間はその日の 0 時）→ adapter は保留する（P8-OBS-30）。

---

## 17. 株数（P8-OBS-23）

- 欄 AvgSh ・ShOutFY ・TrShFY: OBSERVED_IN_PILOT。legacy の parser は読まない。意味は欄名からの INFERRED だけ。

| 求める量 | 候補の欄 | 証拠 |
|---|---|---|
| 発行済株式数 | ShOutFY | INFERRED（自己株式を含むかは UNKNOWN） |
| 自己株式数 | TrShFY | INFERRED |
| 自己株式を除く株数 | 観測なし（差で作るのは本 gate ・A2 とも禁止） | — |
| 期末の株数 | 「FY」の付く欄。四半期の行で四半期末か年度末かは UNKNOWN | UNKNOWN |
| 期中平均株数 | AvgSh | INFERRED |
| 希薄化後の株数 | 観測なし | — |

- どの種類の株式の数か（普通株だけか）・単位 ・桁も UNKNOWN（V09 ・V11）。
- A2 の `SHARES_OUTSTANDING` は Security の単位の 1 つの欄で、定義を A2 の契約が固定していない。**V09 と、発行済 ／ 自己株式 ／ 平均を
  分けるか 1 つの定義に固定する A2 の拡張（P8-OBS-27）の前は写さない。どの株数の欄も時価総額に使わない。**

---

## 18. 時価総額の前提

A3 が要する入力（計算しない）:

1. 価格: Security S の session D の生の終値（`RAW_REPORTED`）で、cutoff までに知り得たもの。
2. 株数: S と同じ種類の株式の、定義を確かめた株数（例: 自己株式を除く発行済）と基準日 E。
3. 日付の整合: E ≤ D で、(E, D] に株数を変える事象（分割 ・併合など）が無いこと、または cutoff までに知り得た係数で合わせること。
   E と D の間の発行 ・自己株式の取得は分からないので、variant 名で「最新の開示済みの株数による」と明示する。
4. corporate action の整合: 事象の入力（P8-OBS-24）が要る。
5. Security ／ Issuer の対応: 株数は S の種類のもの（複数の上場物の発行体）。
6. 知識の時刻: 株数の開示の時刻の規則（§15）。

業者の MktCap（欄は OBSERVED_IN_PILOT）は定義 UNKNOWN（V15）で、A2 に欄が無く authority にしない。**A3 の時価総額: BLOCKED**
（D-P8-A2.5-7）。

---

## 19. EPS

| 項目 | 現在の証拠 |
|---|---|
| 実績 ／ 予想 | EPS ・DEPS は実績、FEPS ・NxFEPS は予想（INFERRED） |
| 基本 ／ 希薄化 | EPS ＝ 基本、DEPS ＝ 希薄化後（INFERRED。V08） |
| 期間 | 行の期間と同じ（累計か単独かは V04） |
| 単位 | 円 ／ 株（INFERRED。fixture は小数） |
| 修正 | 分割の後に過去の EPS を修正して開示するかは UNKNOWN（V08 ・V13） |

- A2: `EPS` → `FundamentalField.EPS`（`PER_SHARE_AMOUNT` ・JPY ・`ONE`）は V08 で基本と確かめた時だけ。DEPS は写さない（A2 に欄なし）。
- PER は計算しない。EPS 成長率は分割を跨ぐと比べられないので BLOCKED（§28）。

---

## 20. 純資産 ／ 総資産

- Eq と ShEq の**両方**の欄が観測されている（OBSERVED_IN_PILOT）。EqAR ・BPS ・TA も観測。定義はどれも UNKNOWN。候補は純資産 ／ 株主資本 ／
  親会社の所有者に帰属する持分（自己資本）。
- legacy の parser は Eq だけを `equity` と読み ShEq を捨てる（未確認の選択: INFERRED）。
- 確かめ方の提案（V07。今は行わない）: 標本の行で EqAR × TA が Eq と ShEq のどちらに一致するかを見る。BPS × 株数との整合も見る。
- A2 の `EQUITY` は 1 つの欄で、どの持分かを契約が固定していない → ROE ／ ROA ／ PBR の前に定義の固定か欄の分割が要る
  （P8-OBS-27）。**黙って正規化しない。**
- TA → `TOTAL_ASSETS` は INFERRED（総資産）。V07 の後に写す。

---

## 21. キャッシュフロー

- CFO ・CFI ・CFF ・CashEq: 欄は OBSERVED_IN_PILOT。どの期間の種類で載るか ・累計か期間かは UNKNOWN（V10）。一部の四半期で開示されない
  可能性は repo に証拠が無い。
- 空の欄は、V10 ／ V12 で「開示していない」の表現と確かめた時だけ `NOT_REPORTED`、それ以外は `MISSING`。
- A2: CFO → `OPERATING_CASH_FLOW`（V10 の後）。他は写さない。FCF は作らない。

---

## 22. 単位 ／ 桁 ／ 通貨

| 欄の群 | 通貨 | 単位 | 桁 | 1 株当たり ／ 絶対値 | 証拠 |
|---|---|---|---|---|---|
| 金額（Sales ・OP ・OdP ・NP ・TA ・Eq ・ShEq ・CF ・予想の金額） | JPY（INFERRED） | 円（INFERRED） | UNKNOWN（fixture は円単位の整数） | 絶対値 | V11 |
| 1 株当たり（EPS ・DEPS ・BPS ・FEPS ・NxFEPS） | JPY（INFERRED） | 円 ／ 株 | `ONE`（INFERRED） | 1 株当たり | V08 ・V11 |
| 比率（ROE ・EqAR） | — | %か割合か UNKNOWN（fixture でも不揃い） | — | — | 写さない |
| 株数（AvgSh ・ShOutFY ・TrShFY） | — | 株（INFERRED） | UNKNOWN | 絶対値 | V09 ・V11 |
| 価格（O ／ H ／ L ／ C） | JPY（INFERRED） | 円 | `ONE`（INFERRED） | 1 株当たり | V14 |
| 出来高 Vo ／ 売買代金 Va | — ／ JPY | 株 ／ 円（INFERRED） | UNKNOWN | 絶対値 | V14 |

- **暗黙の百万円の換算をしない。** A2 は桁の明示を必須にするので、V11 の前は adapter が財務の金額を書けない。
- 円以外で報告する発行体の有無は UNKNOWN。A2 は JPY だけなので、円以外の行は保留（換算しない）。
- legacy の builder の単位 `jpy` ／ `jpy_per_share`（桁なし）は INFERRED の慣習で authority ではない。

---

## 23. 欠損の表現

- provider の表現は UNKNOWN（V12）。
- legacy の parser（HEAD の code を読んだ事実）: `_text` は null ・key が無い ・空文字をすべて空文字にする（3 つの表現を潰す）。
  `to_decimal` は空文字と数でない文字（`-` など）を黙って None にする。client は `parse_float=str` で小数を文字列のまま、整数は
  文字列化する。**legacy の canonical からは provider の表現を復元できない → Phase 8 の adapter は raw snapshot の本文から読む**
  （P8-OBS-26）。

写し方（提案。V12 の後に確定）:

| 出所の表現 | A2 |
|---|---|
| 数の token（`0` を含む） | `VALUE_PRESENT`（0 も値） |
| null | `MISSING` |
| 空文字 | `MISSING` |
| schema にある欄の key が行に無い | `MISSING` ＋ schema のずれの印 |
| dataset の schema に無い欄 | 観測を作らない（`MISSING` にしない） |
| `-` などの数でない印 | **保留**（意味が不明。`MISSING` にも 0 にもしない） |
| 文書で「開示なし」と定まった表現 | `NOT_REPORTED`（V10 ・V12 の文書がある時だけ） |
| 文書で概念が当てはまらないと定まった場合 | `NOT_APPLICABLE`（V03 の文書がある時だけ） |

空 → 0、`-` → 0、空 → `NOT_REPORTED` の推測は禁止。parser の都合を財務の意味にしない。

---

## 24. 重複

| 場合 | 扱い |
|---|---|
| 同じ行が code 指定と date 指定で返る（V23） | raw の行の digest が同じ → 冪等（2 つ目は既存） |
| 元の開示と訂正開示（同じ期間の値） | 重複ではなく revision（A2 の `supersedes`） |
| 同じ日 ・同じ期間の別の書類（決算と予想の修正など） | 別の開示。欄ごとに class と slot を決める |
| 連結と単体 | 別の `StatementBasis` の slot（重複ではない） |
| 複数の上場物を持つ発行体の行（V24） | 発行体 ＋ DiscNo で束ね、値では束ねない。食い違えば保留 |
| 同じ Security ・同じ日の四本値を 2 回取得 | digest が同じなら冪等、違えば revision（知識 ＝ 取得時刻） |

**adapter の dedup の identity**: snapshot の層は（dataset ・provider の自然 key ・raw の行の digest）、A2 の層は slot ＋ `supersedes`。
**値だけで dedup しない。**

---

## 25. 出所の record の identity

| 候補 | 安定 ・一意 | 証拠 | 評価 |
|---|---|---|---|
| DiscNo | UNKNOWN（V02） | 「開示の単位の識別子」は INFERRED | 確認の後に provider の鍵として使う。単独では使わない |
| dataset ＋ 日付 ＋ code（＋ 順番） | 四本値 ・master は（Code, Date）で pilot の重複 0（OBSERVED_IN_PILOT）。順番の欄は無い | 一部 OBSERVED | 四本値 ・master ・決算予定の自然 key |
| 正準の raw の行の digest | 決定論 ・どんな変化も検知 | — | 改訂を結び付けられないので単独では使わない |

**推奨（fail closed）**:

- `source_record_ref` ＝ `jq.<dataset>:<自然 key>:<digest の先頭 24 hex>`。自然 key は財務 ＝ DiscNo、四本値 ＝ Code ＋ Date、master ＝
  Code ＋ 基準日。digest は raw の行の正準の JSON（key を整列 ・出所の token をそのまま ・null を残す）の sha256 で、正規化の**前**に作る。
  A2 の参照の形（最大 160 文字 ・英数と `._:#-`）に合わない値（例えば想定外の文字の DiscNo）は保留。
- 同じ自然 key ・同じ digest → 冪等。同じ自然 key ・違う digest → 業者の改訂（新しい revision ・知識 ＝ 取得時刻 ・印）。上書きしない。
- 自然 key が無い行 → 保留（他の鍵へ落とさない）。
- A2 の runtime に raw の本文を置かない（参照だけ）。

---

## 26. 正準の raw snapshot

**必要**（D-P8-A2.5-4）。provider が過去の応答を改訂し得る（UNKNOWN を安全側に）うえ、legacy の canonical は先勝ちで改訂を捨てる。

| 区分 | 内容 |
|---|---|
| 必ず残す | page ごとの応答の本文（sha256 の content address）、取得の event（dataset ・endpoint の path ・秘密でない引数 `date` ／ `code` ／ `from` ／ `to` ・pagination の順と完了 ・HTTP の status ・API の版 ・要求の開始と応答の受信の UTC 時刻 ・観測した欄の集合 ・normalizer ／ adapter の版）、行ごとの digest、snapshot の manifest（page の hash の順 ・行数 ・digest） |
| 捨ててよい | 200 以外の本文（scrub した診断は残す）、transport の header（content type を除く）、同じ本文の 2 つ目の実体（取得の event は残す） |
| 必ず hash する | 本文 ・行 ・manifest。読むたびに照合する |
| 必要な時刻 | 取得時刻（system の知識）、provider が宣言する時刻（DiscDate ／ DiscTime ／ Date ／ snapshot の基準日の引数）。adapter の実行時刻は知識に使わない |
| 入れてはならない | credential（API key は header だけ。既存の client の規律を保つ）、machine の path（相対の locator だけ）、個人の data |
| 場所 | A2 の runtime ・package の外（A2 は raw を持たない） |
| 公開 | しない。git に commit しない。利用規約（V22）を確かめるまで保存の期間 ・範囲は最小 |

既存の `JsonlRawRepository` ／ `BlobStore`（content address ・atomic ・照合）は考え方として再利用できる（CONCEPTUALLY_REUSABLE）。port は
決めていない。実装しない。

---

## 27. SQLite 索引（P8-OBS-2）

legacy の `JQuantsLightStore` の危険（HEAD の code を読んだ事実）:

1. canonical の `append` は自然の record_id（`px_<code>_<date>` ・`fin_<code>_<DiscNo>` ・`sec_<code>_<date>`）が既にあれば書かない
   → **先勝ちで、後の業者の改訂を黙って捨てる**。
2. `_index` は canonical が飛ばした record を含む batch 全体を `INSERT OR REPLACE` で索引に入れる → **索引は canonical に無い値を持ち、
   `rebuild_index` で元に戻る**（ずれの仕組み）。
3. 破損した行を `_existing_ids` ／ `iter_canonical` が黙って飛ばす（fail closed でない）。
4. `latest_price` ・`latest_company_forecast` などは cutoff の無い「最新」で PIT でない。

推奨の構成（D-P8-A2.5-4 と一体）:

```
正準の追記専用 raw snapshot（A2 の外）
  → 決定論の adapter（純粋関数: snapshot → A1 ／ A2 の候補の record。版つき。再生で bytes 一致）
  → A1 ／ A2 の authority（追記専用 JSONL ・fail closed）
  → 任意の再構築できる索引（派生だけ。PIT の判断に読まない。再構築の一致を test）
```

legacy の SQLite は authority にしない ・移行しない ・本 gate で直さない（P8-OBS-25 に記録）。

---

## 28. A3 の準備度

| 指標 | 分類 | A2 の入力 | 止めている事 |
|---|---|---|---|
| 売上成長率 | READY_WITH_RESTRICTIONS | `REVENUE`（実績）×2 | 同じ `PeriodBasis` ・quarter ・`StatementBasis`、会計年度の長さが比べられる、as-reported の variant。実データは V03 ・V04 ・V11 の後 |
| 営業利益率 | READY_WITH_RESTRICTIONS | `OPERATING_INCOME` ・`REVENUE` | 同じ期間 ・基準。売上 ≤ 0 は NOT_MEANINGFUL。欠損は伝播。実データは V03 ・V11 の後 |
| 純利益率 | READY_WITH_RESTRICTIONS | `NET_INCOME` ・`REVENUE` | 上と同じ ＋ 純利益の帰属（V08） |
| EPS 成長率 | BLOCKED | `EPS`×2 | 分割を跨ぐと比べられない（P8-OBS-24）、基本 ／ 希薄化（V08） |
| ROE | BLOCKED | `NET_INCOME` ・`EQUITY` | 持分の定義（V07 ・P8-OBS-27）、平均の variant |
| ROA | DEFER | `NET_INCOME` ・`TOTAL_ASSETS` | 総資産 ・純利益の定義の確認（V07 ・V08）、年換算をしないので年度だけ。最小集合に要らない |
| PER | BLOCKED | 価格 ・`EPS` | EPS の基準、EPS の期間と価格の日の間の分割、実績 ／ 予想の variant（D-P8-A0-11） |
| PBR | BLOCKED | 価格 ・BPS か持分 ／ 株数 | A2 に BPS なし、持分 ・株数の定義 |
| 時価総額 | BLOCKED | 価格 ・株数 | §18 |
| 価格の return | BLOCKED | `CLOSE` の列 | corporate action の入力が無い（P8-OBS-24）、カレンダーの authority が無い（P8-OBS-28）、業者の調整値は前向きの版だけ |
| 変動率 | BLOCKED | return の列 | 同上 |
| 流動性 | BLOCKED | `VOLUME`（売買代金の欄なし） | 売買代金が A2 に無い（P8-OBS-27）、分割を跨ぐ出来高、カレンダー |

分類の意味: READY ＝ 意味が確定し A2 で表せる ／ READY_WITH_RESTRICTIONS ＝ 明示の制約で意味が確定する ／ BLOCKED ＝ 未確定の
意味 ・入力が要る ／ DEFER ＝ 今は要らず後の gate の後。READY は無い。

---

## 29. A3 の最小の安全な集合

**推奨**（D-P8-A2.5-8）: **2 つだけ**。

1. 売上成長率（同じ基準の前年比 ・as-reported）。
2. 営業利益率（同じ期間 ・同じ `StatementBasis`）。

理由: A2 の `REVENUE` ・`OPERATING_INCOME` と、明示の期間 ・基準だけで意味が決まる。株数 ・持分の定義 ・調整 ・カレンダー ・corporate
action に依存しない。主語は Issuer の cutoff での解決をそのまま使う（`SUBJECT_NOT_RESOLVED` ・欠損は数にしない）。純利益率は V08 の
後の候補。

制約: 合成 data だけ（adapter の gate まで）。指標は `metric_id:version`。結果の状態は NOT_COMPUTABLE ／ NOT_MEANINGFUL ／
NOT_COMPARABLE を持ち、順位 ・score ・TTM ・年換算 ・引き算で作る四半期を持たない。

---

## 30. 実データの adapter の gate

| 案 | 内容 | 評価 |
|---|---|---|
| A. A3 の前 | 先に adapter | 公式確認 ・A1 の拡張を待つ間、A3 も止まる |
| B. A3 の model の後 ・A4 の前 | — | 前提の gate が明示されない |
| C. 分割 | mapping の監査（本 gate）→ A3 の意味論 → 最小の adapter → 直後に実データの検証 | 意味論を進めつつ実データの危険を隔離できる |
| D. 別の順 | — | — |

**推奨: C（前提の gate つき）**（D-P8-A2.5-9）:

1. P8-A2.5（本 gate）。
2. P8-A3: 最小集合（§29）を合成 data で。
3. P8-V: 認可した公式確認の gate（V01〜V24。credential は runtime injection だけ ・標本は最小 ・応答の本文 ／ 実の code を repo に
   残さない）（D-P8-A2.5-10）。
4. P8-A1R: identity の訂正 ・遡及の解決 ・bootstrap の意味論（§7・§8）。
5. P8-A2X（V の結果しだい）: A2 の欄の拡張（株数 ・持分 ・売買代金 ・調整係数 ・遡及修正の印 ・参照の観測 ／ カレンダー）。
6. P8-ADP: raw snapshot の層 ＋ 最小の前向き取得の adapter（小さい universe ・隔離した data root ・再生の決定論の test）。
7. P8-RV: 実データの検証（前向きの取得の期間 ・PIT の再生）。

---

## 31. 過去の screen の準備度

**NOT READY。** PIT として認めるまでに要る事:

1. identity の過去の coverage: P8-A1R の遡及の mode（§8 の C）と、確かめた日次の `?date=` の snapshot からの過去の上場物の登録
   （遡っての適用なし）。
2. raw snapshot の保持が履歴の窓より前から動いていること。後から取った履歴は印を付ける。
3. DiscTime の意味の確認（V01）。できなければ DATE 精度（開示の日は `INSUFFICIENT_TIME_PRECISION`）を受け入れる。
4. 財務の改訂: 後から取る履歴は provider の行の不変性（V13）の確認が前提。無ければ前向きに取った履歴だけが PIT。
5. 調整後価格: 業者の調整値の後からの履歴を使わない。生値 ＋ PIT の係数（corporate action の入力の gate）。
6. corporate action の入力（P8-OBS-24）。
7. 上場の母集団の履歴: 窓の全 session の master の snapshot、市場区分 ／ venue の履歴（P8-OBS-14）、survivorship の確認（廃止済みの
   上場物がいること）。
8. 取引カレンダーの authority（P8-OBS-28）。
9. identity と観測の coverage の record が窓を覆うこと。
10. 実データでの再生の不変（後の record が過去の答えを変えない）の test。

---

## 32. 所見の登録

分類: STRUCTURALLY_ADDRESSED ／ BLOCKED_PENDING_ADAPTER ／ BLOCKED_PENDING_IDENTITY_POLICY ／ BLOCKED_PENDING_OFFICIAL_VERIFICATION ／
NON_BLOCKING_DEFERRED ／ CLOSED。A2 で表せるだけでは CLOSED にしない。**本 gate（A2.5 の監査）を止める所見は無い。**

| id | 所見 | 分類 | 止める gate | 根拠 ／ 次の行動 |
|---|---|---|---|---|
| P8-OBS-1 | 財務の既知の時刻が開示時刻を無視（legacy） | BLOCKED_PENDING_OFFICIAL_VERIFICATION | ADP ・HIST ・CLOSE | A2 は TIMESTAMP ／ DATE を構造で持つ。写しの規則は §15。V01 |
| P8-OBS-2 | 既存の SQLite 索引のずれ | STRUCTURALLY_ADDRESSED | — | 構成を決めた（§27）: adapter は raw snapshot を読み索引を読まない。仕組みは P8-OBS-25 |
| P8-OBS-3 | J-Quants の運用層が現在の系統に無い | NON_BLOCKING_DEFERRED | — | port か作り直しかは P8-ADP で決める |
| P8-OBS-4 | J-Quants の部品に test が無い | NON_BLOCKING_DEFERRED | — | Phase 8 は legacy の parser を authority に使わない（§23） |
| P8-OBS-5 | TOPIX の既知の時刻が 1 時間早い | NON_BLOCKING_DEFERRED | — | Phase 5 の領域。Phase 8 は TOPIX を screen に使わない |
| P8-OBS-6 | master に上場 ／ 廃止の履歴が無い | BLOCKED_PENDING_OFFICIAL_VERIFICATION | ADP ・HIST ・CLOSE | `?date=` の深さと忠実さ（V17 ・V21）。A1 は「少なくとも D から上場」を表せない（P8-A1R） |
| P8-OBS-7 | P7 の引き継ぎの文言の食い違い | NON_BLOCKING_DEFERRED | — | 変更なし |
| P8-OBS-8 | 凍結 guard への登録 | CLOSED | — | registry の仕組みが A1 ・A2 ・本 gate の文書の登録で働き、未登録の file の検出を A1 ・A2 で示した |
| P8-OBS-9 | 調整後価格の遡及 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | A3 ・ADP ・HIST | 遡及の書き換えは INFERRED（V15）。方針は §11（D-P8-A2.5-5） |
| P8-OBS-10 | identity の訂正 ／ 統合の record が無い | BLOCKED_PENDING_IDENTITY_POLICY | ADP ・HIST ・CLOSE | 実の authority の前に P8-A1R（§7） |
| P8-OBS-11 | cutoff が 1 つで遡及の mode が無い | BLOCKED_PENDING_IDENTITY_POLICY | HIST ・CLOSE | A1 は知識と有効時間を分けられず、外の包みで作れない。P8-A1R（§8） |
| P8-OBS-12 | 実の Issuer ／ Security の登録の手順 | BLOCKED_PENDING_IDENTITY_POLICY | ADP ・CLOSE | 案 D（§6・D-P8-A2.5-2） |
| P8-OBS-13 | coverage の期限に上限が無い | NON_BLOCKING_DEFERRED | — | 変更なし |
| P8-OBS-14 | 市場区分 ／ venue の履歴が未 model | BLOCKED_PENDING_ADAPTER | HIST ・CLOSE | master は Mkt と名前の対を持つ（OBSERVED）。参照の観測の model（P8-A2X）と adapter |
| P8-OBS-15 | 凍結の test の comment のずれ | NON_BLOCKING_DEFERRED | — | 変更なし |
| P8-OBS-16 | `core.ids` が `secrets` を import | NON_BLOCKING_DEFERRED | — | 変更なし |
| P8-OBS-17 | 知識の時刻が真の公表時刻かを store は検証できない | BLOCKED_PENDING_ADAPTER | ADP ・HIST | raw snapshot ＋ §15 ／ §16 の規則。後からの取得は V13 が前提 |
| P8-OBS-18 | identity の知識の時刻の食い違い | BLOCKED_PENDING_IDENTITY_POLICY | HIST | §8 の推奨（A を既定、C を P8-A1R で） |
| P8-OBS-19 | coverage が dataset の単位で出所を区別しない | NON_BLOCKING_DEFERRED | — | 変更なし |
| P8-OBS-20 | 同じ日の DATE 精度の保守的な COVERAGE_CONTRADICTION | NON_BLOCKING_DEFERRED | — | adapter は TIMESTAMP を優先 |
| P8-OBS-21 | 出所が違えば値が同じでも AMBIGUOUS | NON_BLOCKING_DEFERRED | — | 最初は J-Quants の単一の出所 |
| P8-OBS-22 | 財務の期間の意味 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | ADP（A3 の実データ） | 構造の規則だけ決めた（§14）。V04 |
| P8-OBS-23 | 株数の意味 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | A3（時価総額 ・PBR）・ADP | §17。V09 ＋ P8-OBS-27 |
| P8-OBS-24 | corporate action の入力 ・参照の観測の延期 | BLOCKED_PENDING_ADAPTER | A3（return 等）・HIST ・CLOSE | P8-A2X と adapter。AdjFactor が検知の候補 |
| P8-OBS-25【新】 | legacy の light store: canonical は自然 key で先勝ち（改訂を捨てる）、索引は飛ばした record も `INSERT OR REPLACE`、破損行を黙って飛ばす | NON_BLOCKING_DEFERRED | — | Phase 8 は読まない。直さない（§27） |
| P8-OBS-26【新】 | legacy の parser が null ／ key なし ／ 空文字を潰し、数でない印を黙って None にする | BLOCKED_PENDING_ADAPTER | ADP | adapter は raw snapshot の本文から読む（§23） |
| P8-OBS-27【新】 | A2 の欄が J-Quants より狭い ／ 定義が曖昧: `EQUITY` ・`SHARES_OUTSTANDING` は 1 つで定義なし（J-Quants は持分 2 欄 ・株数 3 欄）、経常利益 ・売買代金 ・BPS ・希薄化 EPS ・調整係数 ・MktCap ・遡及修正の印が無い | BLOCKED_PENDING_OFFICIAL_VERIFICATION | A3（ROE ・PBR ・時価総額 ・流動性）・ADP | V07 ・V09 ・V15 の後に A2 の拡張の gate（P8-A2X） |
| P8-OBS-28【新】 | Phase 8 に取引カレンダーの authority が無い（休日 ・停止 ・未取得を区別できない） | BLOCKED_PENDING_ADAPTER | A3（window の指標）・HIST | 参照の観測の gate（P8-A2X） |
| P8-OBS-29【新】 | bootstrap の authority の穴: J-Quants 単独で Issuer ／ Security を登録できない（A1 の設計）、発行体の識別子の scheme が無い、上場日の出所が無い、data から計算した anchor は履歴を深く取ると変わる | BLOCKED_PENDING_IDENTITY_POLICY | ADP ・CLOSE | §5 ・§6。anchor は一括で一度だけ割り当てる |
| P8-OBS-30【新】 | 開示時刻の元の値の後の、同じ日の DATE 精度の訂正を A2 が `NON_MONOTONIC_KNOWLEDGE` で拒否 | NON_BLOCKING_DEFERRED | — | adapter は保留する（§16） |
| P8-OBS-31【新】 | F* ／ NxF* の対象の会計年度が DocType ごとに曖昧 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | ADP（予想の写し） | V05 まで F* を写さない |
| P8-OBS-32【新】 | raw snapshot の保存 ・再配布の利用規約が未確認 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | ADP | V22 |
| P8-OBS-33【新】 | Light の dataset ごとの履歴の深さが未測定（TOPIX の 5 年だけ） | BLOCKED_PENDING_OFFICIAL_VERIFICATION | HIST | V21 |
| P8-OBS-34【新】 | P8-A0 §4 ／ §6 の一部の記述が証拠より強い（調整値の遡及 ・訂正は新しい DiscNo） | NON_BLOCKING_DEFERRED | — | 本書で INFERRED に分類し直した。A0 は凍結で編集しない |

---

## 33. 監督判断

監督の方針が要る選択だけ。

| id | 論点 | 案 | tradeoff | 推奨 |
|---|---|---|---|---|
| D-P8-A2.5-1 | identity の遡及の mode | A 厳密だけ ／ C 明示の遡及（版 R ・印）／ D 2 時刻の model | A は過去を見られない。C は A1 の拡張と survivorship の対策が要る。D は大きい割に J-Quants が世界の時刻を持たない | **A を既定、過去の screen の前に C を P8-A1R で** |
| D-P8-A2.5-2 | Issuer の bootstrap | A 1 Security ＝ 仮の Issuer ／ B 人の全件審査 ／ C 別の authority ／ D 混成 | A は複数の上場物で誤る。B は重い。C は新しい出所の認可 ・A1 の拡張。D は例外の審査に絞る | **D（普通株から。C の識別子は後で）** |
| D-P8-A2.5-3 | identity の訂正の gate | 実の登録の前 ／ 後 ／ 作らない | 後では誤りが恒久化し、正しい data を塞ぐ | **実の登録の前（P8-A1R）** |
| D-P8-A2.5-4 | raw snapshot | 必須 ／ 任意 ／ 不要 | 不要なら業者の改訂 ・欠損の表現が失われる。必須は保存の費用と規約の確認 | **必須（A2 の外 ・非公開 ・V22 の後に範囲を決める）** |
| D-P8-A2.5-5 | 調整後価格 | 前向きの版だけ A2 の authority ／ 参照だけ ／ 使わない | 前向きの版は正しいが取り直しが要る。参照だけは安全で情報を捨てる | **前向きの版だけ authority（知識 ＝ 取得時刻）。後からの履歴は参照だけ。PIT の指標は生値 ＋ PIT の係数へ** |
| D-P8-A2.5-6 | 財務の改訂の保持 | すべての版 ／ 最新だけ ／ 開示ごとの初版だけ | 最新だけは PIT を壊す。初版だけは業者の訂正を捨てる | **すべての版（snapshot ＋ A2 の鎖）** |
| D-P8-A2.5-7 | 時価総額の前提 | 株数の確認 ＋ A2 の拡張 ＋ corporate action の整合まで止める ／ 業者の MktCap を参照に ／ ShOutFY で今すぐ | 後の 2 つは定義が未確認 | **止める** |
| D-P8-A2.5-8 | A3 の最小集合 | 売上成長率 ・営業利益率 ／ ＋純利益率 ・ROA ／ ＋市場の指標（制約つき） | 増やすほど未確認の意味に依存 | **売上成長率 ・営業利益率の 2 つ** |
| D-P8-A2.5-9 | adapter の時期 | A ／ B ／ C ／ D（§30） | — | **C（P8-V ・P8-A1R を前提に）** |
| D-P8-A2.5-10 | 公式確認の gate の認可 | 後の gate で認可 ／ offline のまま | 認可なしでは V01〜V24 が閉じない。credential と network を使う | **後の gate として明示の認可（本 gate では呼ばない）** |

---

## 34. 検証と凍結の確認

### 34.1 本 gate の変更

- `docs/databank/PHASE8_JQUANTS_REAL_DATA_MAPPING_AUDIT.md`【新規】（本書）
- `CHANGELOG.md`（v5.53）
- `tests/intelligence/phase8_runtime_registry.py`: `PHASE8_DOCS` に本書、A2 の凍結の anchor `P8_A2` と `PHASE8_A2_RUNTIME`
- `tests/intelligence/test_screener_intelligence_boundary.py`: 本書の登録と、A1 ／ A2 の runtime ・A2 の契約が `P8_A2` と byte 一致する guard
- runtime ・config.yaml ・workflow ・Pages ・Phase 6 ／ 7 の test ・A1 ／ A2 の module は無変更

### 34.2 実行した検証

監督指示の §36 の順:

| # | 対象 | 結果 |
|---|---|---|
| 1 | Phase 8 の境界 ／ 凍結の guard | 51 passed（A2 の 50 ＋ A2 の凍結の guard 1） |
| 2 | A2 | 120 passed |
| 3 | A1 | 101 passed |
| 4 | Phase 7 の closeout ／ 凍結（全 suite） | 1002 passed |
| 5 | Phase 6 の completion ／ 凍結 | 552 passed |
| — | P4 ／ P5 の guard（参考） | 877 passed |
| 6 | full pytest | 5221 passed ／ 2 skipped（基準 5220 ／ 2 ＋ 1） |

否定の証明（scratch の clone）: A2 の runtime を 1 byte 変える → 新しい guard と BL が落ちる。A2 の契約を変える → 新しい guard が
落ちる。本書を registry から外す → Phase 8 の BM と Phase 7 の文書の guard が落ちる。未登録の Phase 8 の文書を足す → Phase 8 の BL と
Phase 7 の文書の guard が落ちる。

### 34.3 凍結

- A2 の runtime（`observation_model` ・`observation_store` ・`observation_resolver`）と A1 の runtime（4 module）は `b686b00` と byte 一致。
  A1 は `4162e9c` とも byte 一致。
- Phase 6 ／ 7 の runtime ・test は無変更。

---

## 35. 最終の判定

**P8_A2_5_REAL_DATA_MAPPING_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_DECISIONS**

A1 ／ A2 ／ Phase 6 ／ Phase 7 の是正は不要。実データの前に要る A1 の拡張（P8-A1R）・公式確認（P8-V）・A2 の拡張（P8-A2X）は後の gate
として §30・§33 に記した。A3 ・adapter ・live の J-Quants ・実の identity の登録 ・指標の計算 ・Theme exposure ・screen ／ 順位は行っていない。
