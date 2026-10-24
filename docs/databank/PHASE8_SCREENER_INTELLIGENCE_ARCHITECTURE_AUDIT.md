# PHASE 8 / P8-A0 — SCREENER INTELLIGENCE ARCHITECTURE ＋ DATA-CAPABILITY AUDIT

READ-ONLY の architecture ／ data 能力の監査。Screener の runtime・schema・model・永続化・J-Quants の live 接続・
Theme → 企業の推定・順位 ／ score は作っていない。network ／ API の呼び出しはしていない。Phase 7（凍結 anchor `c1e95d3`）・
Phase 6（`5ef313a`）・P4 ／ P5・公開出力は変更していない。本 gate の変更は本書・CHANGELOG と、Phase 7 の文書 guard への
本書 1 件の登録（test だけ。§33）。

基準: Phase 7 final freeze `c1e95d35026652fb27c637318593fa8688219cf7`、Phase 6 final freeze `5ef313a`、Phase 5 closeout
`edbd0f2`、P4 production promotion の trust anchor `29c3bea`。branch は `claude/investment-intelligence-phase6`。基準の test 数は
4949 passed / 2 skipped。

証拠の印:

- **[HEAD]** 現在の branch の系統（`c1e95d3` まで）の tracked file。
- **[UNMERGED]** 現在の系統に無い履歴 branch（`origin/claude/investment-intelligence-phase0-rvdplu`、その中の `keep/progression-58709cb`。
  merge-base は `34f7f98`）。`git show` で読んだだけで、port していない。
- **UNKNOWN / NEEDS EXTERNAL VERIFICATION** repo に証拠が無い。推測で埋めない。

---

## 0. 結論

**Phase 8 Screener Intelligence は、凍結した Phase 4〜7 を変えずに設計できる。blocker は無い。** 判定:
`P8_A0_ARCHITECTURE_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_DECISIONS`。

要点:

1. **今の repo に Screener の土台は無い。** 企業 ／ 発行体の master、財務の PIT 観測、銘柄単位の identity、screen の契約、
   Theme → 企業の exposure の authority は、どれも HEAD に無い。legacy の「銘柄」処理はすべて config の手書きの 30 銘柄と
   見出しの語数に立つ UNSAFE な順位付けで、流用できない（§3・§29）。
2. **J-Quants Light で取れるもの**（2026-09-01〜02 の live probe の記録。A0 では再確認していない）: security master
   （snapshot）、日次の四本値（生値と調整値）、財務サマリー（開示単位の実績と会社予想）、決算予定、取引カレンダー、TOPIX、
   投資部門別（市場全体）。配当・詳細財務・空売り比率・TOPIX 以外の指数・前場・売買内訳は Light で NOT_ENTITLED（§4）。
3. **J-Quants の運用層（`jquants_ops`：master の履歴 snapshot、corporate action、session の欠落補修、capability registry）と
   J-Quants 戦略の文書は [UNMERGED] にしか無い。** HEAD にあるのは P4 の production closure に入った取得・parse・保存の
   部品（test なし）だけ。Phase 8 がどちらに依存するかは監督判断（§32 D-P8-A0-2）。
4. **PIT の最大の穴は 3 つ**: (a) Light の master に上場 ／ 廃止の履歴が無く、過去の universe は保存した snapshot の範囲でしか
   再現できない。(b) 調整後価格は遡って書き換わるので、配られた値のままでは PIT でない。(c) HEAD の財務の `known_at` は
   開示時刻（DiscTime）を無視して開示日の 15:30 JST とみなす（P8-OBS-1）。Phase 8 はこれらを自前の規則で閉じる（§6）。
5. **推奨の骨子**（すべて監督判断待ち。§32）: 識別は SecurityId と IssuerId を分け、code は時間つきの属性にする。
   出力は**順位を付けない filter**（基準ごとの PASS ／ FAIL ／ UNKNOWN と根拠）。汎用の score は作らない。
   Theme の exposure は Phase 8 が持つ**人の審査を経た exposure の主張**とし、Phase 6 の reviewed authority を認可した
   読み取り adapter 1 つから読む。描画済みの日本語は機械の入力にしない。LLM は Phase 8 の core に入れない。
6. **guard の事実**: Phase 6 ／ Phase 7 の凍結 guard は runtime surface（`src`・`knowledge`・`config.yaml` ほか）と Phase 7 の
   文書集合への追加を拒む。Phase 8 の最初の実装 gate は、Phase 7 が P7-A1 でしたのと同じ形の**明示の登録**（完全一致の
   path 一覧）を要する。本 gate も文書の追加のために Phase 7 の文書 guard へ本書 1 件だけを登録した（§33・§34 P8-OBS-8）。

---

## 1. 中核の区別

同じ語に見えても別の物で、互いに置き換えない。

| 概念 | 定義 | authority の種類 | 何ではないか |
|---|---|---|---|
| Company ／ Issuer | 法人としての発行体 | 人の審査を経た identity | 上場銘柄ではない（1 社が複数の上場物を持ち得る） |
| Security ／ listed issue | 市場で取引される個々の上場物（普通株・優先株・ETF 等） | 人の審査を経た identity | 会社ではない。code ではない |
| code ／ ticker | ある時点で上場物に付いている識別子 | 時間つきの属性 | identity ではない（変更・再利用があり得る） |
| Theme exposure | 発行体の事業が reviewed Theme の機構に晒されているという、根拠つきの主張 | 人の審査を経た主張 | 業績への影響ではない。受益の順位ではない |
| Business exposure | 事業の構成（segment・製品・顧客・供給者）に関する観測 | 出所つきの観測 | Theme との結び付けではない |
| Financial characteristic | 開示された財務の値、またはそこから決定論で作った指標 | 観測 ／ 派生 | 「良い会社」ではない |
| Market characteristic | 価格・出来高・時価総額など市場の観測と派生 | 観測 ／ 派生 | 「割安」ではない |
| Screening criterion | 明示・version つきの 1 条件（指標・演算子・閾値・欠損の扱い） | 人が書いた契約 | 好み ／ 重み ／ AI の判断ではない |
| Screening observation | ある security × criterion の、cutoff 時点での評価の材料 | 派生 | 結論ではない |
| Screening result | 契約・universe・cutoff に対する基準ごとの PASS ／ FAIL ／ UNKNOWN の集合 | 派生（再計算できる） | 推奨ではない |
| Candidate | 契約のすべての基準を PASS した security | 派生 | 推奨・買い候補・thesis ではない |
| Investment thesis | 特定の security について人が持つ、保有 ／ 監視の理由と無効化の条件 | 人の authority（Phase 9） | screen の結果から自動で作られない |

守る区別: Theme 受益 ≠ 良い会社 ／ 良い会社 ≠ 割安 ／ 割安 ≠ 良い投資 ／ Theme exposure ≠ 業績 exposure ／ Company ≠ 上場物 ／
Candidate ≠ 推奨 ／ Candidate ≠ Watchlist thesis。Phase 8 はこれらを型で分け、ある型から別の型へ暗黙に格上げしない。

---

## 2. Phase 8 と Phase 9 の境界

| 項目 | Phase 8 Screener | Phase 9 Watchlist ／ Thesis |
|---|---|---|
| 問い | 明示の基準と authoritative な data のもとで、どの security が基準を満たすか。なぜ。何を根拠に | この security について、私はなぜ持つ ／ 見るのか。前提は崩れたか |
| 状態 | 状態を持たない。同じ契約・universe・cutoff・data なら同じ bytes | security ごとの持続する仮説・改訂の履歴 |
| 入力 | screen 契約・PIT 観測・派生指標・reviewed な exposure の主張 | 人が書いた thesis・監視の条件・Phase 8 の結果（任意の参照） |
| 出力 | 基準ごとの評価と根拠の鎖。順位なし | thesis の状態（強まった ／ 弱まった等は Phase 9 の契約で） |
| 時間 | cutoff ごとの独立な評価。2 回の結果の差分は派生の比較 | 時間をまたいで同じ thesis を追う |
| 人 | 契約を書く・exposure を審査する | thesis を書く・改訂する・無効化する |

Phase 8 が Phase 9 を作ってしまわないための禁止:

- security ごとの持続する状態（「前回も候補だった」の記憶・候補の追跡・alert）を持たない。2 つの結果の差分は、P7 の差分と
  同じく明示の 2 つの入力から作る派生で、保存しない。
- candidate に理由の自由文・保有の理由・「なぜ買うか」を付けない。根拠は基準の評価の鎖だけ。
- candidate への人のメモ・手動の追加 ／ 除外を screen の結果に混ぜない（それは Phase 9 の watchlist 操作）。
- 無効化の条件・thesis の強弱・監視の規則を持たない。

---

## 3. 既存 repository の棚卸し

分類: REUSABLE（そのまま依存してよい）／ CONCEPTUALLY_REUSABLE（考え方だけ。import しない）／ HISTORICAL_ONLY ／ UNSAFE ／
NOT_RELEVANT。**何も port ／ 変更していない。**

### 3.1 HEAD の intelligence 層（P4 production closure・Phase 5〜7）

| 資産 | 内容 | 分類 | 理由 |
|---|---|---|---|
| `core/ids.py`・`core/time.py`・`core/serialization.py` | content id（sha256 先頭 24 hex）・aware datetime・float 拒否 | REUSABLE | Phase 5〜7 と同じ identity ／ 時間の規約 |
| `core/paths.py` の `data_root()` | env ／ config ／ 既定の順で解決 | NOT_RELEVANT | Phase 5〜7 は data root を明示で受ける。Phase 8 も同じにする |
| `market/jquants_v2_client.py`・`jquants_v2.py` | V2 の取得・pagination・403 → NOT_ENTITLED・key を header だけに置き error から消す | CONCEPTUALLY_REUSABLE | 取得は Phase 8 の決定論の core の外。P4 の closure で凍結 |
| `market/jquants_records.py` | master ／ 日次四本値 ／ 財務サマリー ／ 決算予定 ／ カレンダー ／ 投資部門別の parser。生値と調整値の分離、数値を文字列 ／ Decimal で保持 | CONCEPTUALLY_REUSABLE | 欄の対応は有用。ただし test が無く、`security_id = jp:security:<code>`（code を identity に使う）、`listing_status` は常に `listed` |
| `market/jquants_light_store.py` | canonical JSONL（append-only・record_id で冪等）＋ SQLite 索引 | CONCEPTUALLY_REUSABLE（canonical）／ UNSAFE（索引を PIT の源にすること） | 索引の再構築の癖（P8-OBS-2）。Phase 8 は canonical だけを読む |
| `market/jquants_light_datasets.py` | dataset の台帳（endpoint・entitlement・観測した欄。run #1 の実測） | REUSABLE（文書の証拠として） | 日付つきの実測。live の真実ではない（再確認が要る） |
| `market/tokyo_calendar.py` | HolDiv `1` だけを営業日とし TOPIX の観測日で検証 | REUSABLE | 検証済みの営業日の規則 |
| `market/model.py`・`market/ingest.py` | Observation（as_of・revision_of） | CONCEPTUALLY_REUSABLE | 改訂を新しい行で残す型 |
| `facts/model.py` | `FactValue` は欠損を `None` のまま（0 で埋めない）、`known_at`、`DateRole` | CONCEPTUALLY_REUSABLE | 欠損と PIT の型の手本 |
| `facts/store.py` | 値が変われば `revision_of` で追記、旧行は**索引だけ** SUPERSEDED | CONCEPTUALLY_REUSABLE（canonical）／ UNSAFE（索引） | 索引の問い合わせは現在の状態で PIT ではない |
| `facts/jquants_builder.py` の `_known_at` | 開示日の 15:30 JST を既知の時刻とする | UNSAFE（Phase 8 の PIT 規則として） | DiscTime を無視（P8-OBS-1） |
| `facts/availability.py` | `known_at` が無ければ未知（fail closed） | CONCEPTUALLY_REUSABLE | fail closed の手本 |
| `facts/calculations.py` | `name:version` の計算の台帳、欠損の補完なし | CONCEPTUALLY_REUSABLE | 派生指標の台帳の手本 |
| `internals/universe.py` | プライム・普通株（5 桁目 `0`）・S33 ありで絞る。snapshot が無ければ最古を遡って適用し印を付ける | CONCEPTUALLY_REUSABLE（絞り込み）／ UNSAFE（遡っての適用） | 過去の screen では遡って適用せず fail closed にする |
| `internals/sector.py`・`size.py` | S17 ／ ScaleCat での集計 | CONCEPTUALLY_REUSABLE | 分類は snapshot 日つきの属性として扱う |
| `themes/model.py` の `EntityRef`・`ExposureKind`・`ExposureUncertainty`・`InferredExposureLink`・`EntityLinkClass` | Theme の observation が持つ entity への推定 exposure（推奨ではない） | CONCEPTUALLY_REUSABLE | 語彙は有用。Phase 6 は凍結で、読むのは認可した adapter だけ（§9・§15） |
| `theme_intelligence/entity_model.py`・entity catalog | 9 種の entity、ticker は有効期間つきの識別子、改名・ticker 変更・合併の lifecycle | CONCEPTUALLY_REUSABLE | 中身は架空の fixture だけ（実の企業は 0） |
| `narrative_intelligence/*`（Phase 7） | reviewed Theme の決定論の説明 | REUSABLE（人向けの添付として）／ NOT_RELEVANT（exposure の源として） | claim は entity ／ 企業を参照しない |
| `predictions/*`（Phase 5） | TOPIX の翌営業日の方向の記録と評価 | NOT_RELEVANT（除外） | 銘柄単位の予測・score は無い（§16） |
| `compass/*`・`knowledge/compass_dna` | 市場の解釈の規則と Compass の生成 | NOT_RELEVANT（除外） | 銘柄単位の規則は無い（§17） |
| `databank/identity_*`・`review/identity_ledger.py` | news 記事の同一性（dedup） | NOT_RELEVANT ／ 考え方だけ CONCEPTUALLY_REUSABLE | 「誤った統合は見逃しより悪い」は発行体の対応付けにも当てはまる |

### 3.2 HEAD の legacy（`src/analysis/`・`src/collectors/`・`config.yaml`・`main.py`）

legacy には財務の値・発行体の master・17 ／ 33 業種・screen が**無い**。「銘柄」の処理はすべて config の手書きの watchlist（30 銘柄）と
独自の 8 業種と `causal_rules` に立ち、見出しの語数で判断する。詳細は §29。

| 資産 | 分類 | 理由 |
|---|---|---|
| `collectors/tdnet.py`（適時開示の一覧。code を持つ唯一の collector） | CONCEPTUALLY_REUSABLE | 将来の exposure 根拠の出所の候補。scraping で壊れやすい |
| `collectors/edinet.py`（EDINET v2 の書類一覧。公式 API） | CONCEPTUALLY_REUSABLE | 将来の開示根拠の出所の候補。今は件数を log に出すだけで、code ／ EDINET code を保持しない |
| `collectors/market_data.py`（yfinance ／ Stooq の最新値） | CONCEPTUALLY_REUSABLE（取得の仕組みだけ） | 常に live で過去を再現できない。source により前日比の意味が違う |
| `collectors/earnings.py`（yfinance の次回決算日） | HISTORICAL_ONLY | 現在の予定だけ。履歴なし |
| `analysis/news_ranking.py`・`news_impact.py` | CONCEPTUALLY_REUSABLE（news の重要度の採点）／ UNSAFE（銘柄の付与） | 恣意的な加点。銘柄は config の対応表から |
| `analysis/strategist_engine.py` の `CausalRule` | CONCEPTUALLY_REUSABLE（構造だけ）／ UNSAFE（対応表） | 手書きの「恩恵が及びやすい銘柄」 |
| `analysis/stock_ranking.py`・`top_picks.py`・`long_term_picks.py`・`sector_ranking.py`・`sector_strength.py`・`market_impact.py`・`themes_forecast.py`・`future_intelligence.py`（銘柄の部分）・`ai_summary.py`・`causal_chain.py`・`executive_summary.py`（銘柄の文） | UNSAFE | 恣意的な重み、手書きの Theme ／ 業種 → 銘柄の対応、「注目銘柄」「長期投資候補」の語、LLM による理由の書き直し |
| `analysis/watchlist_analysis.py`・`watchlist_quicklist.py`・`theme_rotation.py`・`theme_learning.py`・`investment_journal.py` | HISTORICAL_ONLY | 日経平均を代理に使う評価・評価済みの標本 0・今日の watchlist を過去へ当てる |
| `config.yaml` の `watchlist`・`sectors.related_tickers`・`causal_rules`・`theme_relations` | UNSAFE（Phase 8 の入力として） | 手で調整された現在の状態で PIT でない。保有の signal を含み得る。一部の規則は機密資料由来とコメントされている |
| `data/theme_learning/theme_learning.json`・`data/investment_journal/journal.json` | HISTORICAL_ONLY | 評価済みの結果が無い legacy の記録 |

### 3.3 [UNMERGED] の資産（現在の系統に無い）

| 資産 | 内容 | 分類 | 理由 |
|---|---|---|---|
| `src/intelligence/jquants_ops/`（22 module） | capability registry ／ gate、master の日付指定 snapshot の蓄積、corporate action の除外、session の欠落 ／ 補修、差分取得、schema drift、health ／ readiness、request ／ storage の予算 | CONCEPTUALLY_REUSABLE | 最も有用な運用の設計だが HEAD に無い。port は監督判断（D-P8-A0-2） |
| `docs/databank/JQUANTS_FIRST_RULE.md`・`JQUANTS_LIGHT_CAPABILITY_MATRIX.md`・`JQUANTS_PRODUCTION_DATA_STRATEGY.md` ほか | J-Quants First の規則・Light の entitlement 実測・運用設計 | CONCEPTUALLY_REUSABLE（証拠として） | 本書の §4 はこれを証拠の 1 つとして読んだ。HEAD には無い |
| `src/intelligence/screening/__init__.py` | 「Financial Quality × Structural Trend の複合 score で 5〜10 年保有候補を探索」の docstring だけの骨組み | HISTORICAL_ONLY（考え方は UNSAFE） | 複合 score と保有候補の語は §13・§14・§21 と矛盾する |
| `src/intelligence/thesis/__init__.py`・`personalization/__init__.py` | Phase 9 ／ 10 の docstring だけの骨組み | HISTORICAL_ONLY | 中身なし |
| `src/intelligence/evaluation/score.py` | Compass の review の参照 score（状態を先に、score は並べ替えの補助） | NOT_RELEVANT | 銘柄の評価ではない |

HEAD の作業木には、上記の [UNMERGED] package の `__pycache__` だけが ignored として残っている（source は無い）。削除していない。

---

## 4. J-Quants の能力

A0 は network を使っていない。以下は repo の記録（[HEAD] の dataset 台帳と parser、[UNMERGED] の実測文書）だけに基づく。
entitlement の実測は 2026-09-01（run #1 ／ #3）〜 2026-09-02（run #20 ／ #21）のもの。**この session の環境に J-Quants の
credential は無い**（env の名前だけを確かめ、値は見ていない）。

| dataset（endpoint） | data | identifier | 履歴 | PIT | 頻度 | 制約 | 実装 | Phase 8 が依存してよいか |
|---|---|---|---|---|---|---|---|---|
| listed_master（`/equities/master`） | Code・社名（和 ／ 英）・市場（Mkt ／ MktNm）・S17 ／ S33（名前つき）・ScaleCat・信用区分・商品区分・Date | Code（実測 5 桁。英字を含む code の観測あり [UNMERGED]） | 引数なしで当日 snapshot [HEAD]。`?date=` で過去の snapshot を取れた（2026-06-26 を取得。深さは未測定）[UNMERGED] | snapshot の Date。**上場日・廃止日の履歴なし**。`listing_status` は常に listed [HEAD] | snapshot（[UNMERGED] の運用は週 1） | 発行体の識別子（法人番号・EDINET code・ISIN）が観測欄に無い | [HEAD] 取得・parse・保存（pilot だけ・test なし）。日付指定の蓄積は [UNMERGED] だけ | **条件つき**: 保存した snapshot の日以後の session だけ。それより前は fail closed。`?date=` の深さは NEEDS EXTERNAL VERIFICATION |
| daily_bars（`/equities/bars/daily`） | O ／ H ／ L ／ C・Vo・Va・AdjO〜AdjC・AdjVo・AdjFactor・UL ／ LL・MktCap | Code | 1 年分（2025-09-01〜2026-09-01、244 session）を実測 [UNMERGED]。それ以上の深さは UNKNOWN | session の日付。**公表時刻は repo に無い**（下流は 15:30 JST とみなす）。調整値は遡って変わる | 日次 | 総 return の欄なし [HEAD]。MktCap の定義（株数の基準・調整）は UNKNOWN | [HEAD] code 指定で標本 8 銘柄の pilot だけ。日付指定の全銘柄取得は [UNMERGED] | **はい（生の四本値・出来高・売買代金）**。調整値と MktCap は定義の確認まで NO |
| fins_summary（`/fins/summary`） | 開示単位: DiscDate ／ DiscTime ／ DiscNo・書類種別・期間区分（CurPerType）・期首 ／ 期末・売上・営業利益・経常利益・純利益・EPS ／ 希薄化 EPS・BPS・ROE・総資産・純資産・自己資本比率・CF 3 種・現金同等物・当期予想（F*）・翌期予想（NxF*）・遡及修正（RetroRst） | Code | 1 銘柄 20 件 [HEAD run #1] ／ 22〜31 件 [UNMERGED]。期間の深さは UNKNOWN | DiscDate ＋ DiscTime で決まる。**HEAD の `known_at` は DiscTime を無視**（P8-OBS-1）。訂正は新しい DiscNo | 開示ごと | 株数（期末発行済・自己株・期中平均）は観測されたが parse していない。単体（NC*）は未 parse。配当の欄の有無は UNKNOWN。値が累計か四半期単独かは NEEDS EXTERNAL VERIFICATION | [HEAD] 取得・parse・保存・facts 化（手動 pilot だけ・test なし） | **はい**（Phase 8 の known_at 規則と期間の意味の確認を条件に） |
| equities_earnings_cal（`/equities/earnings-calendar`） | Code・予定日・社名・四半期・年度・市場・業種名 | Code | 将来分だけ。run #1 は 1 行 | 開示日が無く、既知の時刻は取得時刻 | 日次で再取得 | 予定は変わる（新しい record） | [HEAD] 実装 | **前向きの蓄積だけ**。過去の screen には使えない |
| markets_calendar（`/markets/calendar`） | Date・HolDiv | — | 2021-09-17〜2026-09-17 の 1,827 行 [HEAD P5 の記録] | 参照 data。HolDiv `1` だけを営業日（検証済み） | 参照 | `0` ／ `3` は営業日としない（fail closed） | [HEAD] 実装・test あり | **はい** |
| topix（`/indices/bars/daily/topix`） | Date・O ／ H ／ L ／ C | Code `0000` | 最大 2021-09-17〜2026-09-17（10 年の要求は plan で拒否）[HEAD P5] | as_of 15:30 JST。公表は 16:30 頃と記録（P8-OBS-5） | 日次 | 遅延の plan 差は UNVERIFIED のまま | [HEAD] production で取得 | 市場の文脈としてだけ。screen の基準には通常使わない |
| investor_types（`/equities/investor-types`） | 市場区分ごとの投資部門別の売買 | 市場区分（銘柄なし） | 直近 120 日 | PubDate 16:00 JST を既知の時刻 | 週次 | 銘柄単位ではない | [HEAD] 実装 | NOT_RELEVANT（銘柄の screen には使えない） |
| fins_earnings_date（`/fins/earnings-date`） | — | — | — | — | — | HTTP 400（引数の契約違い）。entitlement UNKNOWN | 未実装 | **いいえ** |
| indices_bars_daily・fins_dividend・fins_details・markets_short_ratio・equities_bars_am・markets_breakdown | TOPIX 以外の指数・配当・詳細財務・業種別空売り比率・前場・売買内訳 | — | — | — | — | **Light で NOT_ENTITLED**（403 を実測）。迂回しない | 未実装 | **いいえ**。必要なら plan の変更は監督 ／ 利用者の判断 |
| 信用残・V1 の `listed/info` ／ `statements` ／ `announcement`・派生商品 | — | — | — | — | — | NOT IN REPO | — | UNKNOWN |

補足:

- HEAD の production が J-Quants から取るのは **TOPIX だけ**（morning delivery の workflow から `pilot_runner` が V2 の TOPIX provider
  を登録）。他の dataset は手動の pilot でしか取得されていない。
- 「Light-first」の方針の文書は [UNMERGED] にしか無い。HEAD では dataset 台帳の comment が根拠。
- Phase 8 の実データ段階の前に、J-Quants First の規則（[UNMERGED] の文書）に沿って**entitlement と欄の意味を再確認**する gate が
  要る（実測は 2026-09-01〜02 で、それ以後に確かめていない）。再確認は credential と network を使うので、監督の明示の許可が要る（§30）。

---

## 5. Company と Security の identity

### 5.1 現状

- HEAD の security の id は `jp:security:<Code>`（`jquants_records.py`。comment は「ticker そのものを ID にしない」とするが、中身は
  code そのもの）。4 桁 ↔ 5 桁の正規化は無い。発行体（company）の id は**どこにも無い**。
- universe は 5 桁目 `0` を普通株とみなす（`internals/universe.py`）。
- Light の master の観測欄には、発行体を法的に識別する欄（法人番号・EDINET code・ISIN・LEI）が無い [UNMERGED の実測欄の一覧 ／ HEAD の
  parser]。1 つの Code ＝ 1 つの上場物の行。
- Phase 6 の契約は「ticker は識別子で identity ではない」とし、catalog の fixture は ticker 変更（同じ entity_id）・改名・合併を
  有効期間と `superseded_by` で表す。Phase 6 A2 §13 は entity の typed reference の例に `jp:security:<code>` を挙げる。

### 5.2 code だけを永続の identity にできない理由

- code の変更・再利用・上場廃止後の扱いは repo に証拠が無い（NEEDS EXTERNAL VERIFICATION）。Phase 6 の catalog 自身が ticker の変更を
  想定している。
- 英字を含む code が観測されている [UNMERGED]。数値として扱う実装は壊れる。
- 1 社が複数の上場物（普通株と優先株など。5 桁目で区別）を持ち得る。財務は会社の値だが、Light の財務は Code で配られる。
- master に廃止の履歴が無いため、code がいつ有効だったかを repo の data だけで確定できない。

### 5.3 案

| 案 | 内容 | 利点 | 欠点 |
|---|---|---|---|
| A | code を identity（HEAD の `jp:security:<code>` のまま） | 単純。既存の部品と一致 | code の変更 ／ 再利用で別物が同じ id になる。会社と上場物が混ざる |
| B | **SecurityId と IssuerId を別に作る**。code・社名・市場・業種は snapshot の日つきの属性（valid_from ／ valid_to）。同一性の継続（code 変更・再利用・合併）は、曖昧なら人の審査。曖昧さの無い 1:1 の継続だけを決定論で認める | 会社と上場物を分けられる。code の変化に耐える。Phase 6 の catalog の考え方と一致 | 最初の対応付けに人の審査の仕組みが要る |
| C | 外部の正準の識別子（ISIN ／ 法人番号 ／ EDINET code ／ LEI）を identity にする | 法的に強い | Light に無い。別の出所（EDINET 等）と新しい取得の許可が要る |

**推奨: B**（D-P8-A0-1）。`jp:security:<code>` は Phase 6 の EntityRef と既存の record との互換のための**識別子の値**として残す。
C は後で識別子を足す拡張にする。財務（会社の値）は、Code → Security → Issuer の対応を明示の provenance つきで通して発行体に結び、
対応が曖昧なら UNKNOWN にする（推測で結ばない）。上場物の種類は普通株から始め、他の種類は明示の契約で足す。

---

## 6. PIT の要件

原則: cutoff `T` の screen は、`T` までに**既知だった**情報だけを使う。既知の時刻が分からない data は、保守的な規則（遅い側）で
既知とみなすか、使わない。現在の metadata で過去を screen しない。

| 出所 | 事象の時刻 | 既知 ／ 公表の時刻 | 改訂 | as-of の意味 | 判定 |
|---|---|---|---|---|---|
| 日次四本値（生値） | session の日 | 公表時刻は repo に無い（下流は 15:30 JST とみなす） | 業者の訂正は repo に証拠なし | その session の値 | **取り込み後は PIT_SAFE**。既知の時刻は取得時刻か、監督が決める保守的な上限（15:30 とみなさない） |
| 調整後の四本値・AdjFactor | session の日 | 取得時刻 | **後の分割等で遡って変わる** | 取得した時点の調整 | **配られた値のままは NOT_PIT**。生値 ＋ cutoff までに既知の調整係数から作り直せば PIT |
| MktCap（日次の欄） | session の日 | 同上 | UNKNOWN | UNKNOWN | **UNKNOWN**（定義を確かめるまで使わない） |
| security master（上場 ／ 市場 ／ 業種 ／ 規模区分） | snapshot の Date | 取得時刻 | snapshot の間の変化は見えない（≤ 7 日。[UNMERGED] の記録） | snapshot 日の状態 | **保存した snapshot の範囲だけ PIT**。最初の snapshot より前の session は fail closed（HEAD の遡っての適用はしない） |
| 業種分類 S17 ／ S33 | 同上 | 同上 | 分類の変更は snapshot の差で見える | 同上 | 同上。現在の業種で過去を分類しない |
| 財務サマリー | 決算期 ／ 期間末 | **DiscDate ＋ DiscTime（JST）** | 訂正は新しい DiscNo。遡及修正は RetroRst | 開示の時点の値（as-reported） | **規則つきで PIT_SAFE**: 既知の時刻は開示の日時で、それより前にしない。DiscTime が無ければ開示日の終わり（または取得時刻の遅い方） |
| 会社予想（F* ／ NxF*） | 対象期 | 開示の日時 | 予想の修正は新しい開示 | 開示の時点の予想 | 財務と同じ。**実績と別の class** |
| 決算予定 | 予定日 | 取得時刻 | 予定は変わる（新しい record） | 取得時点の予定 | **前向きの蓄積だけ**。過去には遡れない |
| 社名などの metadata | snapshot の Date | 取得時刻 | snapshot の差 | snapshot 日 | 表示のための属性。screen の基準にしない |
| Phase 6 の Theme（reviewed） | observation ／ evidence の時刻 | `recorded_at`（evidence は `evidence_time ≤ attached_at`） | governance の event（訂正の鎖） | resolver が cutoff で解決 | **PIT_SAFE**（Phase 7 A2 と同じ読み方） |
| Phase 8 の exposure の主張（将来） | 根拠の時刻 | 記録の時刻 | append-only の改訂 | cutoff での解決 | 設計で PIT にする（§25） |
| legacy の yfinance ／ config の対応表 | — | 現在 | 手で調整 | 現在 | **NOT_PIT → 禁止** |

追加の要件:

- 窓を使う指標（return・変動率・平均売買代金）は、検証済みのカレンダーの session のうち cutoff 以前だけで作り、欠けた session を
  補わない。必要な session 数に足りなければ UNKNOWN。
- data の保存時刻（取得時刻）を必ず残す。「T に既知だったか」は取得時刻と公表時刻の遅い方で判定する（backfill した過去の値を、
  過去の時点で既知だったとみなすかは D-P8-A0-10 の判断）。
- 過去の screen は、その cutoff より後に保存 ／ 改訂された record を加えても bytes が変わらないことを test で示す（Phase 7 A5 の E03〜E07 と同じ型）。

---

## 7. 財務データ

「財務 score」を 1 つ作らない。指標ごとに種類・期間の意味・改訂の扱いを分ける。

| 指標 | 種類 | Light での出所 | 期間の意味 | 改訂 ／ 修正 | 注意 |
|---|---|---|---|---|---|
| 売上高 | RAW_REPORTED | fins_summary `Sales` | CurPerType ごと。累計か四半期単独かは NEEDS EXTERNAL VERIFICATION | 新しい DiscNo ／ RetroRst | 業種により概念が違う（金融等） |
| 営業利益 | RAW_REPORTED | `OP` | 同上 | 同上 | IFRS ／ 金融では NOT_APPLICABLE があり得る |
| 経常利益 | RAW_REPORTED | `OdP` | 同上 | 同上 | 日本基準の概念。IFRS では NOT_APPLICABLE |
| 純利益 | RAW_REPORTED | `NP` | 同上 | 同上 | 帰属の定義は要確認 |
| EPS ／ 希薄化 EPS | RAW_REPORTED | `EPS` ／ `DEPS` | 同上 | 同上 | 株式分割の後は過去の EPS と比べられない |
| BPS | RAW_REPORTED | `BPS` | 期末 | 同上 | |
| ROE | RAW_REPORTED（業者の欄）または DERIVED | `ROE` の欄 ／ 純利益 ÷ 自己資本 | 欄の定義は UNKNOWN | — | 派生で作るなら分母（期首 ／ 期末 ／ 平均）を variant として明示 |
| ROA | DERIVED | 純利益 ／ 営業利益 ÷ 総資産 | variant を明示 | — | Light に欄なし |
| 自己資本比率 | RAW_REPORTED | `EqAR` | 期末 | — | |
| 総資産 ／ 純資産 | RAW_REPORTED | `TA` ／ `Eq` | 期末 | — | |
| 営業 ／ 投資 ／ 財務 CF・現金同等物 | RAW_REPORTED | `CFO` ／ `CFI` ／ `CFF` ／ `CashEq` | 開示される期だけ | — | 開示されない期は NOT_REPORTED（0 ではない） |
| 利益率 | DERIVED | 営業利益 ÷ 売上高 等 | 同じ開示の同じ期間どうし | 入力の改訂に従う | 分母 0 ／ 負は NOT_MEANINGFUL |
| 成長率（前年比） | DERIVED | 同じ期間区分の前年の開示 | cutoff までに既知の前年値 | as-reported と最新の遡及修正後を別の variant にする | 決算期の変更で比べられない場合は NOT_COMPARABLE |
| TTM | DERIVED | 四半期の値の合計 | 四半期単独の値が要る（累計なら差を取る） | 同上 | 期間の意味が確認できるまで作らない |
| 配当 | — | `/fins/dividend` は NOT_ENTITLED。fins_summary の配当の欄は未 parse で有無は UNKNOWN | — | — | Light では**使えない**扱いから始める |
| 株数（期末発行済・自己株・期中平均） | RAW_REPORTED | 観測されたが HEAD は未 parse | 期末 ／ 期中 | — | 時価総額の自前計算に要る |
| 時価総額 | MARKET_DERIVED | 終値 × 株数（基準を明示）または業者の MktCap（定義 UNKNOWN） | 価格の session と株数の基準日が違う | — | 株数の基準日のずれを provenance に残す |
| PER | MARKET_DERIVED | 価格 ÷ EPS | **variant を別の指標にする**: 実績 EPS ／ 会社予想 EPS ／ TTM EPS | 入力に従う | EPS ≤ 0 は数値にしない（NOT_MEANINGFUL） |
| PBR | MARKET_DERIVED | 価格 ÷ BPS（cutoff までに既知の最新） | BPS の基準日を残す | 入力に従う | BPS ≤ 0 は NOT_MEANINGFUL |
| 会社予想（売上 ／ 利益 ／ EPS） | COMPANY_FORECAST | F* ／ NxF* | 当期 ／ 翌期 | 予想の修正は新しい開示 | 実績と混ぜない。基準に使うなら class を明示（D-P8-A0-11） |

派生指標は台帳で `metric_id:version` を持ち、式・入力の欄・期間の variant・欠損の伝播を固定する。同じ名前で意味の違う
variant（PER の 3 種など）を 1 つにまとめない。

---

## 8. 市場データ

| 指標 | 種類 | PIT ／ 調整の要件 |
|---|---|---|
| 終値・四本値 | RAW | 生値を正とする。session の日と取得時刻を残す |
| 調整後の価格 | DERIVED（as-of） | cutoff までに既知の調整係数から作り直す。業者の Adj* をそのまま過去に使わない |
| return | DERIVED | 同じ調整の基準の価格どうし。corporate action の日は除外か調整を明示（[UNMERGED] は生値 ＋ 除外） |
| 出来高・売買代金 | RAW | 分割の前後で出来高は比べにくい（調整の有無を variant にする） |
| 変動率 | DERIVED | 窓の長さ・return の種類・標本の定義を固定。欠けた session を補わない |
| 流動性（平均売買代金など） | DERIVED | 窓と統計量（平均 ／ 中央値）を固定 |
| 時価総額 | MARKET_DERIVED | §7 |
| 値幅制限の到達（UL ／ LL） | RAW の flag | 意味の確認は NEEDS EXTERNAL VERIFICATION |

A0 は technical analysis の戦略を作らない。窓の指標は「定義を明示した記述統計」に留め、方向・signal を付けない。

---

## 9. Theme → 企業の exposure

### 9.1 現状

- Phase 6 の Theme の observation は `InferredExposureLink`（entity・`ExposureKind` BENEFICIARY ／ ADVERSELY_EXPOSED ／ MIXED ／
  UNSPECIFIED・`ExposureUncertainty` HYPOTHESIZED ／ PARTIALLY_EVIDENCED ／ SOURCE_ASSERTED・provenance HUMAN ／ RULE ／ LLM_PROPOSAL）を
  持てる。docstring は「推奨ではない（BUY ／ SELL ／ weight なし）」。evidence の `subject_refs` からは DIRECTLY_EVIDENCED の link が派生する。
- ただし**実の Theme authority は 0 件**、catalog の企業は架空の fixture だけ。Phase 7 は entity ／ exposure を投影しない。
- Phase 6 の completion audit は「会社別 thesis・受益 ranking」を Phase 9 に延期した（P6-DEF-29）。Phase 6 を読む正式の
  interface は production 統合の前に必須（P6-DEF-15）。

### 9.2 根拠の種類の評価（推定は実装しない）

| 根拠 | 出所の候補 | authority | PIT | 評価 |
|---|---|---|---|---|
| 会社の開示（有報 ／ 決算短信 ／ 適時開示） | EDINET（公式 API）・TDnet（legacy の scraping） | 出所つきの一次情報 | 開示の日時 | **最有力**。人の審査で exposure の主張にする |
| segment 別の売上 | 開示（Light の財務サマリーには無い） | 一次情報 | 開示の日時 | 強い。取得の手段は未整備 |
| 製品 ／ サービスの exposure | 開示・公式の資料 | 一次情報 | 開示の日時 | 強いが解釈を含む → 人の審査 |
| 顧客 ／ 供給者の関係 | 開示（主要顧客の記載） | 一次情報 | 開示の日時 | 関係の存在だけ。影響の大きさは別 |
| 設備投資 | 開示 | 一次情報 | 開示の日時 | 意図の根拠。実現ではない |
| 契約 ／ 受注 | 適時開示 | 一次情報 | 開示の日時 | 個別の事実 |
| 公式の戦略 | 中期計画等 | 会社の主張（SOURCE_ASSERTED） | 開示の日時 | 会社の言い分として限定して扱う |
| 規制の exposure | 公的機関 ＋ 開示 | 一次情報 | 公表の日時 | 強い |
| 業種分類（S17 ／ S33） | master | 分類（TAXONOMIC） | snapshot | **exposure の根拠にしない**。分類の連想だけ（Phase 6 の TAXONOMIC_ASSOCIATION と同じ扱い） |
| news の見出しの語 | legacy | なし | — | 使わない |
| LLM の抽出 | 将来の任意 gate | 提案だけ | — | 人の審査を経るまで根拠にしない（§27） |

**推奨**（D-P8-A0-4）: Theme → 企業は Phase 8 が持つ**exposure の主張**（issuer ／ security・reviewed Theme root・exposure の経路・極性の
主張・根拠の ref・審査の記録）とし、人の審査を経たものだけを screen の基準に使う。Phase 6 の `InferredExposureLink` は Theme 側の
仮説として読めるが、screen の authority に格上げしない（表示の文脈に留める）。業種分類は exposure の根拠にしない。

---

## 10. 受益の model

Phase 8 は**exposure の関係を先に model 化し、順位は延期**する。受益の 1 次 ／ 2 次 ／ 3 次の順位は Phase 6（P6-DEF-29）と
Phase 7（§19・D-P7-14）で延期され、Phase 6 の契約は受益の順位 ／ BUY 候補の生成を禁じている。

| 経路（channel） | 意味 | 極性の主張 |
|---|---|---|
| DIRECT | 自社の製品 ／ サービスが Theme の機構に直接関わる | 正 ／ 負 ／ 混合 ／ 未特定 |
| ENABLER | 機構を支える道具 ／ 部材を供給（picks-and-shovels） | 同上 |
| SUPPLIER_TO | Theme の中心の企業に供給する | 同上 |
| CUSTOMER_OF | Theme の成果を買う側 | 同上 |
| COMPETITOR | Theme の中心の企業と競合 | 同上 |
| SUBSTITUTE | 代替の技術 ／ 製品の側 | 同上 |
| ADVERSELY_EXPOSED | 機構が逆風になる | 負 |

- 極性は**主張**で、業績への影響の大きさや確度の数値ではない（Phase 6 の `ExposureUncertainty` と同じく class で持つ）。
- 「受益者」の語・「恩恵が大きい順」は出力に出さない。
- 大きさ（segment の売上比率など）は、根拠のある**観測**として別に持てる。それを順位に変えるのは別の契約（§13）。

---

## 11. evidence の authority の梯子

| 段 | 名前 | authority | 作る者 | 持続 |
|---|---|---|---|---|
| L0 | 取得した raw payload | 出所の記録だけ | 取得の工程 | 監査のための保存（secret を含めない） |
| L1 | 正規化した観測（市場 ／ 財務） | SOURCE_RECORD（業者に帰属） | 決定論の parser | append-only |
| L2 | 派生指標 | 派生（authority なし） | 版つきの式 | 再計算。保存しない（必要なら cache） |
| L3 | 企業の exposure の根拠 | 出所つきの主張 | 開示の参照 ／ 人 ／（将来）LLM の提案 | append-only |
| L4 | 審査済みの exposure の主張 | 人の authority | 人の審査 | append-only の governance |
| L5 | screen の契約 | 人が書いた契約 | 人 | 版つき・不変 |
| L6 | screen の評価 | 派生 | 決定論の評価 | 保存しない |
| L7 | candidate の結果 | 派生 | 決定論 | 保存しない（任意の運用記録は入力にしない） |
| L8 | 審査済みの thesis | 人の authority | 人（Phase 9） | Phase 9 の範囲 |

天井: 上の段は下の段を書き換えない。L6 ／ L7 は Production DNA ／ Theme authority ／ exposure の主張 ／ thesis にならない
（書き込みの経路を作らない）。LLM の出力は L3 の提案が上限。

---

## 12. screening の基準

基準は**明示・版つき・監査できる・決定論**のデータで、コードに埋め込んだ好みにしない。

```
ScreenContract   := contract_id（content id）・version・universe_spec・cutoff の意味・criteria（順序つき）・combination = ALL_OF
UniverseSpec     := 市場区分・上場物の種類・業種の包含 ／ 除外（S17 ／ S33 の code）・規模区分（すべて snapshot の日で評価）
Criterion        := criterion_id・metric_ref（metric_id:version と variant）・operator・threshold（Decimal ＋ 単位）
                    ・missing_policy（UNKNOWN_IS_NOT_PASS のみを既定）・staleness_bound（何日前までの値を使うか）
operator         := LT ／ LE ／ GT ／ GE ／ BETWEEN ／ IN ／ NOT_IN ／ EXISTS ／ NOT_EXISTS（閉じた集合）
```

例: `PER（会社予想 EPS）< X`・`ROE（variant 明示）> Y`・`売上成長率（前年比・as-reported）> Z`・`時価総額 BETWEEN a AND b`・
`審査済みの exposure の主張が Theme root R に対して EXISTS`・`S33 NOT_IN {...}`。

- 重み・点数・「好ましさ」の欄を持たない。
- 閾値は契約の中身で、`config.yaml` に置かない（`config.yaml` は凍結 guard の対象でもある。§33）。
- 初期は ALL_OF だけ。OR や入れ子は、評価の説明の鎖が保てることを示してから別の契約で。

---

## 13. filter と rank

| 案 | 内容 | 評価 |
|---|---|---|
| A | 決定論の filter だけ（PASS した集合） | 安全。説明が単純 |
| B | filter ＋ 決定論の順位 | 順位の関数が暗黙の好み ／ 重みになる。「上位 N」が推奨として読まれる |
| C | filter ＋ 順位の無い多次元の結果（基準ごとの値・PASS ／ FAIL ／ UNKNOWN・閾値からの距離・網羅度） | 説明が最も豊か。並べ方は中立の固定鍵（SecurityId）だけ |
| D | C ＋ 後の別契約での「利用者が明示した 1 指標での並べ替え」 | 並べ替えは表示の操作で、合成 score ではない |

**推奨: C**（D-P8-A0-3）。順位は、screener が伝統的に並べるという理由だけでは入れない。
将来に並べ替えを許すなら、別の契約で少なくとも次を要する: 並べ替えの鍵は契約に明示した**1 つの**指標（合成しない）・向き・同順位の
決定論の解消・UNKNOWN の置き場所・「上位」「おすすめ」の語の禁止・表示に「X による並び」と明記・N 件で切ることの禁止（または理由の明示）。

---

## 14. score の方針

**汎用の銘柄 score は作らない。** 分けて持つもの:

| 量 | 扱い |
|---|---|
| raw の指標の値 | そのまま（Decimal ＋ 単位 ＋ 期間 ＋ 出所） |
| 正規化した指標（universe 内の百分位など） | 初期は作らない。universe と cutoff に依存し、暗黙の比較を生む。作るなら別の契約で version と universe の digest を付ける |
| 基準の PASS ／ FAIL ／ UNKNOWN | 基準ごとに持つ。合計しない |
| 閾値からの距離 | 符号つき・指標の単位のまま。説明のためだけ（並べ替えに使わない） |
| 網羅度 ／ 完全性 | 評価できた基準の数 ／ 全体。**data の品質**であって魅力ではない |

「投資の魅力度」「総合点」「星の数」を作らない。これらを作る関数・欄の名前（score ／ rank ／ rating ／ attractiveness 等）は、
Phase 7 の `PROHIBITED_FIELDS` と同じ形で型と guard で禁じる。

---

## 15. Theme Intelligence との境界

| 候補 | 評価 |
|---|---|
| Phase 6 の reviewed Theme authority を直接読む | **推奨**。Phase 7 の `pit_assembler` と同じく、認可した読み取り adapter 1 つだけが Phase 6 の read API を import する。cutoff を明示し、B3〜B7 の提案 ／ 監視は読まない |
| Phase 7 の `NarrativeSynthesis`（構造の claim） | 表示の文脈としてだけ。claim は entity ／ 企業を参照しないので exposure の源にならない。screen の基準に使わない |
| Phase 7 の `NarrativePresentation` | 同上（表示の authority） |
| Phase 7 の `RenderedNarrative`（日本語の文） | **機械の入力にしない**。人向けに添えるなら、提示と synthesis から作り直して `rendered_id` の一致を確かめ、文を並べ替え ／ 削らない |
| 専用の派生 exposure interface | 推奨（§9 の exposure の主張）。Theme root の id だけを参照し、Theme の中身を複製しない |

Phase 7 completion audit §27 は「P8 が使えるのは内部の `RenderedNarrative` ／ `RenderedNarrativeDiff` だけ」と書いたが、P7-A0 §19 は
「構造化された欄だけを認可された interface で」と書いた。両者は表示の消費と機械の消費を区別していない。本書の推奨は、
**機械の消費は構造（Phase 6 authority の adapter）、描画は人向けの添付だけ**とすること（D-P8-A0-5。Phase 7 の runtime ／ 文書は
変えない。Phase 8 の契約が機械の消費について定める）。

---

## 16. P5 の境界

- Phase 5 は TOPIX の翌営業日の方向（5 段階の signal と確度）の記録と評価だけで、銘柄単位の予測・score は無い。
  Phase 5 の entry contract は「Screener（8）以降は本書の対象外」とし、`predictions` は production から到達不能（除外 package）。
- **Phase 8 に正当な役割は無い。除外する。** 予測 → 銘柄の score への feedback の経路を作らない（import guard で禁じる）。

---

## 17. Production DNA の境界

- `knowledge/compass_dna/market_rules.yaml` は市場の状態 → 市場の含意の規則（13 本。code に登録されているのは 6 本）で、
  銘柄単位の規則は無い。業種 ／ style 群の含意を持つ規則はあるが、それは Compass の解釈で、事実ではない。
- Phase 5〜7 は DNA の自動の変更 ／ 昇格を禁じ、`knowledge/compass_dna` は guard で凍結されている。
- **Phase 8 は DNA を使わない。** 将来に使う理由が示されても、上限は「人向けの文脈の表示」で、screen の基準・exposure の根拠・
  順位にはしない。screen の結果から DNA へ書く経路は作らない。

---

## 18. 除外する入力

| 入力 | 既定 | 理由 |
|---|---|---|
| 未審査の Theme の提案（B3） | 除外 | authority ではない |
| B4 discovery の hit | 除外 | 提案の材料 |
| B5C の relation の提案 | 除外 | 未審査 |
| B6 の MonitoringFinding | 除外 | 監視の所見で authority ではない |
| B7 の LLM の提案 | 除外 | 提案だけ |
| Compass の raw な資料 | 除外 | CONFIDENTIAL_SOURCE |
| formal review の候補 | 除外 | [UNMERGED] の governance の途中の物 |
| P5 の予測 ／ calibration | 除外 | §16 |
| `RenderedNarrative` の文 | 除外（機械の入力として） | §15 |
| legacy の watchlist ／ config の対応表 ／ news の語の採点 | 除外 | §3.2 |

後の gate が構造化された使い方を明示で認めない限り除外のまま。除外は import の guard と、adapter が読む store の完全な一覧で固定する。

---

## 19. データ品質

閉じた語彙を持ち、**欠損を 0 に変えない**。

| 状態 | 意味 | 基準の評価 |
|---|---|---|
| PRESENT | 値がある | 評価する |
| MISSING | 出所が値を配らなかった（取得の失敗・欄の欠け） | UNKNOWN |
| NOT_REPORTED | 発行体がその期に開示していない | UNKNOWN |
| NOT_APPLICABLE | 概念が当てはまらない（例: 金融業の営業利益） | UNKNOWN（理由つき） |
| ZERO | 0 が報告された | 0 として評価 |
| NOT_MEANINGFUL | 計算はできるが意味を持たない（EPS ≤ 0 の PER など） | UNKNOWN（理由つき） |
| STALE | 契約の鮮度の上限より古い | UNKNOWN |
| RESTATED | 後に遡及修正された（as-reported を使うかは variant で決める） | variant に従う |
| FORECAST | 会社予想（実績ではない） | 予想の基準でだけ評価 |
| PARTIAL_COVERAGE | universe の一部で data が無い | 結果に網羅度を出す |
| IDENTIFIER_MISMATCH | code ／ security ／ issuer の対応が合わない・曖昧 | UNKNOWN |
| CORPORATE_ACTION_AFFECTED | 分割等で比べられない | UNKNOWN |
| NO_TRADE | その session に約定が無い | 価格の基準は UNKNOWN |

基準の結果は PASS ／ FAIL ／ UNKNOWN（理由の code つき）の 3 値。UNKNOWN は PASS にしない（candidate にならない）。
UNKNOWN の件数は隠さず結果に出す。

---

## 20. 説明可能性

すべての candidate と、候補にならなかった security の各基準の結果は、次の鎖で辿れる。

```
candidate ／ 基準の結果
  → criterion（contract_id・criterion_id・version）
  → 派生指標の値（metric_id:version・variant・入力の record の id）
  → 観測（record_id・出所・session ／ 開示の日時・既知の時刻・取得時刻）
  → raw payload の digest（secret を含まない）

exposure の基準の場合:
candidate → exposure の主張（id・経路・極性・審査の記録） → 根拠の ref（開示の locator・時刻）
          → reviewed Theme root（cutoff で Phase 6 の resolver が解決した状態）
```

結果は contract の digest・universe の digest・cutoff・knowledge の pin（台帳 ／ 式の version）・入力 data の digest を持ち、
同じ入力なら別 process でも同じ bytes（Phase 7 と同じ再現の証明を要する）。

---

## 21. 推奨なし

- 出力は「明示の契約を満たす」だけを意味する。買い ／ 売り ／ 保有・「最良の銘柄」・期待 return・目標株価・portfolio の比率を
  持たない。
- 型の欄の禁止（recommendation ／ target_price ／ expected_return ／ weight ／ rank ／ score ／ rating ／ best ／ buy ／ sell 等）と、
  出力の語の禁止（「注目」「おすすめ」「有望」「割安」「上位」等を評価として使わない）を guard で固定する。
- legacy の「今日の注目 5 銘柄」「長期投資候補 TOP5」の型は作らない。

---

## 22. 個人化なし

利用者の portfolio・リスク許容度・年齢・収入・好みを使わない（Phase 10）。Phase 8 は読み手に中立。config の watchlist（保有の signal を
含み得る）も入力にしない。screen の契約を書く人の意図は契約の中身として明示されるだけで、個人の属性を推定しない。

---

## 23. 実データの戦略

| 問い | この環境での答え |
|---|---|
| 実の市場 data はあるか | **無い**（J-Quants の canonical ／ SQLite・日次四本値の保存は repo にも作業環境にも無い） |
| 実の財務 data はあるか | **無い** |
| 実の company master はあるか | **無い**（Phase 6 の catalog は架空の fixture だけ） |
| 実の Theme authority はあるか | **無い**（Phase 6 ／ 7 の completion audit と同じ。`REAL_DATA_E2E = NOT_RUN`） |
| J-Quants の credential ／ config はあるか | この session の env に J-Quants の変数の名前は無い（値は見ていない）。`config.yaml` に J-Quants の key は無い。workflow は secret の名前 `JQUANTS_API_KEY` を runtime で注入する |
| 過去の標本はあるか | 作業環境には無い。[UNMERGED] の記録では 2026-06 下旬〜09 初めの約 2 か月の全銘柄の日次四本値と週次の master snapshot を隔離 root で取得した実績があるが、その data は repo に無い |

Phase 7 と違い、Phase 8 は実データでの検証に意味がある（閾値・欠損・期間の意味は合成 data では確かめられない）。推奨（D-P8-A0-7）:

1. A1〜A6 は合成の fixture（実の欄の形を写した架空の値）で決定論と PIT を固める。
2. 実データの取得は、監督の明示の許可のもとで credential を runtime で注入できる環境（GitHub Actions の secret か利用者の端末）で
   行い、repo に data を commit しない。
3. closeout の前に最低限の実データ検証: 検証済みカレンダーの連続した session（窓の指標が作れる長さ）・その期間の master の
   snapshot・標本の発行体の財務の開示・code の変更 ／ 廃止の実例の確認。

---

## 24. package の境界

- 名前の衝突: `screener_intelligence` は tracked file に 0 件。`screening` は P4 の production bundle guard の除外 package の名前で、
  [UNMERGED] の骨組みの package 名でもある。`screener_intelligence` なら衝突しない。
- **推奨の場所: `src/intelligence/screener_intelligence/`**（Phase 6 の `theme_intelligence`、Phase 7 の `narrative_intelligence` と
  同じ命名）。production bundle guard の除外一覧への追加は、P8-A1 の登録と同時に監督の許可で行う。

読んでよい package（案。P8-A1 で完全一致の許可一覧として固定）:

| package | 許可 | 条件 |
|---|---|---|
| `core`（ids ／ time ／ serialization） | 可 | 純関数だけ |
| `themes` ／ `theme_intelligence` の read API | 1 つの adapter module だけ | Phase 7 の `PHASE7_SANCTIONED_IMPORTERS` と同じ形。読む API を完全一致で固定 |
| `narrative_intelligence` | 表示の添付の module だけ（任意） | 構造 ／ 描画を機械の入力にしない |
| `market`（J-Quants の記録の型） | 原則不可 | canonical JSONL の形を入力の契約として受け、P4 の module を import しない（D-P8-A0-2） |
| `predictions`・`compass`・`context`・`reports`・`databank`・`analysis`・`collectors`・`report` | 不可 | §16〜§18 |

逆向き: 既存の package は `screener_intelligence` を import しない（Phase 7 と同じ上流の guard）。

---

## 25. 永続化

| artifact | class | 永続化 | 時期 |
|---|---|---|---|
| security ／ issuer の identity の登録 | AUTHORITY（人の審査） | append-only の journal | identity の gate の後 |
| identifier の履歴（code ／ 名前 ／ 市場 ／ 業種の有効期間） | SOURCE_RECORD から派生 | snapshot から再計算。保存は source の snapshot だけ | — |
| raw の観測（四本値 ／ 財務 ／ master の snapshot） | SOURCE_RECORD | append-only（業者に帰属。変更しない） | 取得の gate |
| 派生指標 | DERIVED | 保存しない（必要なら再構築できる cache。入力にしない） | — |
| screen の契約 | AUTHORITY（人が書く） | 版つき・不変・content id | 評価の gate |
| screen の実行 ／ candidate の結果 | DERIVED | 保存しない。任意の運用の記録（監査用・入力にしない）は別の gate | — |
| exposure の主張 | AUTHORITY（人の審査） | append-only ＋ governance | exposure の gate |

保存するものは authority と source record に限る（D-P8-A0-6）。SQLite 等の索引は canonical から作り直せる cache とし、PIT の源に
しない（P8-OBS-2）。data root は明示で受け、repo の既定の場所に書かない。

---

## 26. 人の governance

| 操作 | 人の審査 | 理由 |
|---|---|---|
| Theme → 企業の exposure の主張 | **必須** | 解釈を含む。Theme authority を銘柄選択の authority にしないため |
| 曖昧な issuer ／ security の対応（code の変更・再利用・合併・複数上場） | **必須** | 誤った統合は見逃しより悪い |
| 事業の関係（顧客 ／ 供給者 ／ 競合） | **必須** | 開示の読み取りを含む |
| 手動の包含 ／ 除外 | screen の結果には入れない | Phase 9 の watchlist の操作 |
| screen の契約の作成 ／ 改版 | 人が書く（authority） | 暗黙の好みを入れないため |
| 投資 thesis | Phase 9 | Phase 8 の範囲外 |
| 曖昧さの無い 1:1 の identifier の継続 | 不要（決定論） | 規則を契約で固定 |

LLM の判断が審査なしに authority になる経路は作らない。

---

## 27. LLM の役割

- **Phase 8 の core（identity・観測・指標・基準・評価・結果）に LLM を入れない**（D-P8-A0-8）。
- 将来の正当な役割は 1 つ: 開示から exposure の根拠の候補を**提案**として抽出すること（出所の locator つき・決定論の検証・人の審査の後に
  だけ L4 になる）。Phase 6 の B7 と同じ形の別の gate にし、Phase 8 の closeout の後に置く。
- LLM が作る score ／ 順位 ／ 推奨 ／ 理由の文は作らない。

---

## 28. security

| 対象 | 境界 |
|---|---|
| J-Quants の credential | runtime の注入だけ（env の名前 `JQUANTS_API_KEY`）。git ／ config ／ log ／ 例外の文 ／ raw payload ／ record ／ 取得の試みの記録に入れない。header だけで URL に入れない（HEAD の V2 の部品はこの規則を実装済み）。新しい key を要求しない |
| その他の API key（LLM ／ EDINET ／ 通知） | Phase 8 は使わない |
| 顧客の情報 | 扱わない。Phase 8 の data model に顧客の欄を作らない |
| portfolio ／ 保有 | 扱わない（§22） |
| machine 固有の path | config ／ source ／ 文書 ／ tracked file に書かない。data root は実行時に明示で渡す |
| Compass の機密資料 | 入力にしない。PDF を git に入れない |
| 出力 | 評価の語 ／ 推奨の語の guard。公開 ／ Pages ／ P4 への接続は別の gate |

A0 の確認: 本書と CHANGELOG の追加分に、秘密の値・machine の path・PDF の名前 ／ 本文・利用者の identity は無い（§33）。

---

## 29. legacy screener の監査

legacy に screen は無いが、**銘柄の順位付け**がある。どれも Phase 8 に import ／ port しない。

| 資産 | 何をするか | unsafe な前提 | 分類 |
|---|---|---|---|
| `stock_ranking.py` | 前日比の絶対値で 10 銘柄を並べ、短期 ／ 中期 ／ 長期の見通しの文を付ける | 当日の見出しの数から長期の見通しを作る。手書きの銘柄 → 業種 | UNSAFE |
| `top_picks.py` | 前日比の絶対値の上位 5 を「本日の注目銘柄として選定」 | 推奨の語。値動き ＝ 注目 | UNSAFE |
| `long_term_picks.py` | `score = (追い風 − 逆風) × 2 ＋ 決算予定 0.5` で「長期投資候補 TOP5」 | 恣意的な重み。業種不明は 0。LLM が理由を書き直す。journal に `top_picks` として残す | UNSAFE |
| `future_intelligence.py`（銘柄の部分） | Theme の勢い（語数 × 6 ＋ 加点、上限 100）と確度 → 銘柄の判断の label（「押し目待ち」等）・2 次の「まだ注目されにくい企業」 | 恣意的な加点。欠損は 0。対応は config だけ。買いに近い語。受益の 2 次の列挙 | UNSAFE |
| `sector_ranking.py`・`sector_strength.py`・`market_impact.py` | 見出しの数で業種を並べ、矢印 ／ 星を付ける。業種の語に企業名を埋め込む | 語数 ＝ 強さ。「AI 予測」の表示 | UNSAFE |
| `news_ranking.py`・`news_impact.py` | 見出しの重要度の加点（watchlist の名前 ＋3 など） | 重みは恣意的。銘柄の付与は config | CONCEPTUALLY_REUSABLE（news の採点の型だけ）／ UNSAFE（銘柄） |
| `strategist_engine.py` | 見出し → Theme → 業種 → 「恩恵が及びやすい銘柄」 | 手書きの因果の規則 | CONCEPTUALLY_REUSABLE（規則の構造だけ）／ UNSAFE（対応表） |
| `theme_learning.py`・`investment_journal.py` | 30 日後に日経平均で「勝ち」を判定 | 銘柄でなく指数で評価。評価の時点が実行日によってずれる。評価済み 0 件 | HISTORICAL_ONLY |
| config の watchlist ／ 業種 ／ 因果の規則 | 手で「一致率を上げる」ために調整した現在の状態 | **現在の data の過去への当てはめ**（選択の偏り） | UNSAFE |
| [UNMERGED] `screening` の骨組み | 「財務の質 × 構造の趨勢の複合 score で 5〜10 年保有候補」 | 汎用の score と保有候補の語 | HISTORICAL_ONLY（考え方は UNSAFE） |

確認した危険の型: 恣意的な重み・未来 ／ 現在の data の過去への当てはめ・LLM による理由の書き直し・推奨の語・欠損 → 0。
Phase 8 はこれらを guard で禁じる。

---

## 30. Phase 8 の gate 案

監督の草案（A0 → A1 identity → A2 PIT 観測 → A3 派生指標 → A4 Theme exposure → A5 基準 ／ 評価 → A6 結果 ／ 説明 → A7 実データ → A8 E2E ／
closeout）は方向として妥当。次の 4 点を変えると安全になる。

1. **観測の model と source の adapter を分ける**: PIT の型（raw と調整・既知の時刻・改訂・品質の状態）を、実 payload の形に触る前に
   純 model として固める。
2. **Theme exposure を評価と結果の後に置く**: 最も解釈の危険が大きい部分を、客観的な data での screen の core が検証された後に、
   基準の 1 種（exposure の主張の EXISTS）として差し込む。
3. **guard の登録を A1 で行う**: Phase 6 ／ 7 の凍結 guard への Phase 8 の完全一致の登録（Phase 7 の `phase7_runtime_registry` と同じ形）と、
   Phase 8 自身の境界 guard を最初の実装 gate で作る。
4. **実データの前に capability の再確認**: J-Quants の entitlement と欄の意味は 2026-09-01〜02 の [UNMERGED] ／ HEAD の記録しか無い。
   network と credential を使う確認は、監督が明示で許可する別の段にする。

提案（D-P8-A0-9）:

| gate | 内容 | 出力 |
|---|---|---|
| P8-A0 | architecture ／ data の監査（本書） | 監督判断 |
| P8-A1 | security ／ issuer の identity model（純・合成 fixture）・identifier の有効期間・code の変更 ／ 再利用 ／ 廃止 ／ 複数上場・Phase 8 の guard の登録 | identity の契約 |
| P8-A2 | PIT 観測の model（純）: 市場 ／ 財務の観測・生値と調整・既知の時刻の規則（DiscTime を含む）・改訂 ／ 遡及修正・品質の語彙 | 観測の契約 |
| P8-A3 | source の adapter（read-only・network なし）: 明示の data root の canonical record → P8 の観測。索引を読まない。capability の記録の文書化 | adapter の契約 |
| P8-A4 | 派生指標の台帳（`metric_id:version`・variant・Decimal・欠損の伝播） | 指標の契約 |
| P8-A5 | screen の契約 ＋ 決定論の評価（filter・3 値・順位なし） | 評価の契約 |
| P8-A6 | 結果 ／ 説明の鎖 ／ 2 つの結果の差分（Phase 7 の差分と同じ型） | 結果の契約 |
| P8-A7 | Theme exposure の model（人の審査の主張・Phase 6 の認可した adapter・exposure の基準） | exposure の契約 |
| P8-A8a | capability の再確認（監督の許可・credential の runtime 注入・既知の 403 は再 probe しない） | 能力の記録 |
| P8-A8b | 実データの検証（隔離 root・commit しない） | 実データの報告 |
| P8-A9 | 敵対的 E2E ＋ closeout | 凍結 |

代案: exposure を草案どおり A4 に置く案は、Theme との接続を早く見せられるが、exposure の審査の仕組みと screen の core を同時に
固めることになり、欠陥の切り分けが難しくなる。

---

## 31. Phase 9 への引き継ぎ

Phase 8 が Phase 9 に渡してよいもの:

- security ／ issuer の identity と identifier の履歴
- screen の契約（id ／ version ／ 中身）
- screen の結果（基準ごとの PASS ／ FAIL ／ UNKNOWN と値）
- 基準の根拠の鎖（観測の record ／ 派生の式 ／ 時刻）
- 審査済みの exposure の主張とその根拠
- PIT の provenance（cutoff・pin・digest）

渡さないもの: 推奨・自動の thesis・portfolio の行動・順位・score・候補であることを理由にした保有の提案。Phase 9 は Phase 8 の
結果を**参照**できるが、thesis は人が書く。

---

## 32. 監督判断の表

| id | 決めること | 案 A | 案 B | 案 C | trade-off | 推奨 |
|---|---|---|---|---|---|---|
| D-P8-A0-1 | identity の model | code を identity | SecurityId と IssuerId を分け、code 等は有効期間つきの属性。曖昧な継続は人の審査 | 外部の正準 id（ISIN ／ 法人番号 等） | A は単純だが code の変化で壊れる。C は Light に無い | **B**（C は後の拡張） |
| D-P8-A0-2 | J-Quants の運用層の出所 | HEAD の `market/jquants_light_*` を直接 import | [UNMERGED] の `jquants_ops` を port | Phase 8 は canonical record の形を入力の契約として受ける read-only の adapter を持ち、取得は別の gate | A は test の無い P4 closure に依存。B は大きく、現行の governance で審査されていない | **C**（B の設計は文書の証拠として参照だけ） |
| D-P8-A0-3 | filter と rank | filter だけ | filter ＋ 順位 | filter ＋ 順位の無い多次元の結果 | B は暗黙の重み ／ 推奨の読み。C は説明が豊か | **C**（明示の 1 指標の並べ替えは別の契約で後から検討） |
| D-P8-A0-4 | Theme exposure の authority | Phase 6 の `InferredExposureLink` を使う | Phase 8 の人の審査を経た exposure の主張（reviewed Theme root を参照） | Phase 8 では Theme exposure を扱わない | A は Theme 側の仮説で、実データ 0。C は Theme と screen が繋がらない | **B**（A は表示の文脈だけ） |
| D-P8-A0-5 | Theme ／ Narrative の interface | Phase 6 authority を認可した adapter で | `NarrativeSynthesis` の構造 | `RenderedNarrative` の文 | C は描画の文を機械の入力にする。B は entity を持たない | **A**（B ／ C は人向けの添付だけ。P7 §27 の文言は Phase 8 の契約で機械の消費について上書きする） |
| D-P8-A0-6 | 永続化の境界 | すべて保存 | authority（identity ／ exposure ／ 契約）と source record だけ。結果は保存しない | 何も保存しない | A は派生が authority に見える。C は審査の記録が残らない | **B** |
| D-P8-A0-7 | 実データの最低条件 | 合成だけで closeout | closeout 前に監督の許可した環境で実データの検証（§23 の最低条件） | A2 から実データ | A は Phase 8 では不十分。C は PIT の型が固まる前に実 payload に引きずられる | **B** |
| D-P8-A0-8 | LLM の上限 | Phase 8 では使わない | closeout の後の別の gate で exposure の根拠の抽出の提案だけ | score ／ 順位にも使う | C は禁止の対象 | **A**（B は後の任意の gate） |
| D-P8-A0-9 | gate の順序 | 監督の草案どおり | §30 の改訂案（観測と adapter の分離・exposure を後ろへ・A1 で guard の登録・capability の再確認） | — | A は exposure と core を同時に固める | **B** |
| D-P8-A0-10 | 過去の universe の扱い | 最古の snapshot を遡って適用し印を付ける（HEAD の universe） | 保存した snapshot より前の cutoff は fail closed | `?date=` で過去の snapshot を backfill（深さは要確認） | A は survivorship の偏りを残す。C は再確認と取得の許可が要る | **B**（C は capability の再確認の後に任意で） |
| D-P8-A0-11 | 会社予想の扱い | FORECAST の class を明示して基準に使える | 使わない | — | A は PER（予想）等の一般的な指標を作れる。予想と実績の混同の危険は class で防ぐ | **A** |
| D-P8-A0-12 | 凍結 guard への Phase 8 の登録の方式 | Phase 8 の追加のたびに Phase 6 ／ 7 の guard を個別に編集 | P8-A1 で Phase 8 の登録 module（完全一致の path）を作り、Phase 6 ／ 7 の guard はそれを 1 度だけ参照 | — | A は凍結した test を何度も触る | **B**（本 A0 の文書の登録は例外の 1 行。§33） |

---

## 33. 検証と凍結の確認

### 33.1 本 gate の変更

| file | 変更 |
|---|---|
| `docs/databank/PHASE8_SCREENER_INTELLIGENCE_ARCHITECTURE_AUDIT.md` | 新規（本書） |
| `CHANGELOG.md` | v5.50 の監査だけの記録 |
| `tests/intelligence/test_narrative_intelligence_boundary.py` | Phase 7 の文書 guard の許可集合に本書 1 件を登録（`P8_A0_DOC`）。他の判定は不変 |

Phase 7 の文書 guard（`test_as_phase6_documents_and_the_a0_audit_are_frozen`）は「P7-A0 以後の `docs` の差分は Phase 7 の 6 文書の
追加だけ」を確かめる。監督が本書の作成を指示したため、この集合に本書の完全な path だけを加えた（glob ／ prefix にしない）。
登録しない状態でこの guard が落ちることを確かめてから登録した。Phase 7 の runtime ／ 契約 ／ 他の test は変えていない。

### 33.2 実行した検証

| 順 | 対象 | 結果 |
|---|---|---|
| 1 | Phase 7 の境界 ／ 凍結 guard ＋ closeout の E2E（`test_narrative_intelligence_boundary.py`・`test_narrative_phase7_e2e.py`） | 209 passed |
| 2 | Phase 7 の全 suite（A1〜A4b） | 793 passed |
| 3 | Phase 6 の completion ／ closeout ／ 凍結（`test_theme_phase6_completion.py`・`test_theme_llm_closeout.py`・monitoring の rerun 2 本） | 202 passed |
| 4 | architecture ／ import の guard（Theme の import 境界 4 本・P4 production bundle・機密の guard） | 70 passed |
| 5 | full pytest | **4949 passed / 2 skipped**（基準と同じ。test の追加なし） |

full pytest の後に legacy の journal を元に戻した。security の走査（本書と CHANGELOG ／ guard の追加行）: 秘密の値・machine の path・
PDF の名前・利用者の identity・model の識別子は 0 件。

### 33.3 凍結の確認

- Phase 7 の runtime（`narrative_intelligence` の 11 module）は `c1e95d3` と byte 一致。`git diff c1e95d3 -- docs` は本書の追加だけで、
  Phase 7 の A0〜A5 の文書と Phase 6 以前の文書は不変。`c1e95d3` は HEAD の祖先。
- `src`・`knowledge`・`config.yaml`・`.github`・`scripts`・`docs/pages`・`main.py`・`requirements.txt`・`pyproject.toml` に変更なし
  （`c1e95d3` との差分 0 件）。Production DNA 不変。
- 作業木の既存の未追跡 ／ ignored の file（`__pycache__`・ignored の data ／ research の directory・[UNMERGED] package の残りの bytecode）は
  削除していない。

---

## 34. 所見の登録

どれも Phase 8 の設計の制約で、Phase 6 ／ 7 の変更を要しない（blocker なし）。

| id | 所見 | 影響 | 扱い |
|---|---|---|---|
| P8-OBS-1 | HEAD の `facts/jquants_builder._known_at` は財務の開示を開示日の 15:30 JST に既知とし、DiscTime を無視する | 引け後の開示を実際より早く既知とみなす（同日の夕方の screen で未来の漏れ）。P4 の朝の用途（翌朝 06:00）には影響なし | Phase 8 は再利用せず、開示の日時で既知とする規則を A2 で固定 |
| P8-OBS-2 | `market/jquants_light_store.append` は canonical で既知の record を飛ばすが、新規が 1 件でもあれば batch 全体を `INSERT OR REPLACE` で索引する | 同じ record_id で値の違う再配信があると SQLite の索引が canonical とずれる（`rebuild_index` で戻る） | Phase 8 は canonical だけを読む。P4 側の修正は別の判断 |
| P8-OBS-3 | J-Quants の運用層（`jquants_ops`）と J-Quants 戦略の文書は [UNMERGED] にしか無い | HEAD だけでは master の履歴 snapshot・corporate action・欠落の補修が無い | D-P8-A0-2 |
| P8-OBS-4 | HEAD の `jquants_light_*`・`jquants_records`・`jquants_builder`・`internals/*` に test が無い（関連の test は [UNMERGED] にだけある） | 直接依存すると検証されていない部品に立つ | D-P8-A0-2（案 C） |
| P8-OBS-5 | TOPIX の既知の時刻は as_of 15:30 JST。記録上の公表は 16:30 頃 | 同日の夕方の用途で 1 時間早い | Phase 8 の基準は通常 TOPIX を使わない。使うなら保守的な規則 |
| P8-OBS-6 | master の `listing_status` は常に `listed`。上場 ／ 廃止の履歴なし。universe は snapshot が無ければ最古を遡って適用 | 過去の universe の survivorship の偏り | D-P8-A0-10 |
| P8-OBS-7 | Phase 7 completion §27（RenderedNarrative だけ）と P7-A0 §19（構造の欄だけ）の P8 への引き継ぎの文言が食い違う | 機械の消費と表示の消費が区別されていない | D-P8-A0-5（Phase 8 の契約で定める。Phase 7 は変えない） |
| P8-OBS-8 | Phase 6 ／ 7 の凍結 guard は `src`・`knowledge`・`config.yaml` と Phase 7 の文書集合への追加を拒む | Phase 8 の実装には明示の登録が要る。`config.yaml` への設定の追加（CLAUDE.md 規則 8）は凍結と衝突 | D-P8-A0-12。閾値は契約の中身にし、`config.yaml` を使わない |
| P8-OBS-9 | 業者の調整後価格は遡って変わる | 配られた値のままでは PIT でない | A2 で生値 ＋ as-of の調整を規則にする |

---

## 35. 最終の判定

**P8_A0_ARCHITECTURE_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_DECISIONS**

- 既存の資産の分類・J-Quants の能力・identity・PIT・財務 ／ 市場の指標・Theme exposure・受益の model・authority の梯子・基準・
  filter と rank・score・境界（Theme ／ P5 ／ DNA ／ 除外）・品質・説明・推奨 ／ 個人化なし・実データ・package・永続化・governance・
  LLM・security・legacy・gate 案・Phase 9 への引き継ぎを監査し、監督判断を 12 件にまとめた（§32）。
- Phase 6 ／ 7 の変更は要しない。所見 9 件は Phase 8 の設計の制約（§34）。
- HARD STOP: P8-A1 を実装しない。screener の runtime・順位 ／ score・J-Quants の live 接続・Theme → 企業の推定を作らない。
  Phase 9 を始めない。監督の判断を待つ。
