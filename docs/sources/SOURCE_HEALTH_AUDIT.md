# SOURCE_HEALTH_AUDIT — 全86ソース死活監査（Phase 1-B / 2026-08-29）

対象: `knowledge/source_reliability/source_feeds.yaml` v3.0.0 の86ソース。
方針: **実測evidenceのみで判定し、推測でhealthyを名乗らない**。カウントは全て実測。

## 1. 証拠レイヤー（3層）

| レイヤー | 内容 | カバレッジ | 限界 |
|---|---|---|---|
| historical（tank実績） | article-intelligence-data-tank記事ストアの取得実績（2026-06-22..07-22、3,056記事） | 42ソースでverified | **6週間前の実績。現在正常の証明にはならない**（tank自体2026-07-22から停止中） |
| recent_ci（Legacy CI実測） | Legacy日次レポート `output/2026-08-{16..29}_market_brief.html` のデータ品質カードを14日分抽出し、collectors/config.yamlのURL突合でカタログidへ対応付け | 24ソース | Legacyがfetchするソースのみ。失敗理由（DNS/403/パース不能）はカードに残らない |
| live check | `health_check.py` によるHTTP死活確認 | **0ソース（実行不能）** | 下記§3 |

## 2. 判定表（`health_check.evaluate` 実装と一致）

| 観測 | 判定 |
|---|---|
| 2xx＋フィード解釈可＋最新アイテム≤30日 | HEALTHY |
| 2xx＋JSON API到達 | HEALTHY（アイテム構造検証はP1-C） |
| 2xx だが stale（>30日）/ アイテム日付なし / HTML・解釈不能応答 | DEGRADED |
| 403 / その他4xx・5xx | DEGRADED（クライアント条件ブロック疑い等） |
| 401 | AUTH_REQUIRED |
| 429 | RATE_LIMITED |
| 301/308で別ホストへ恒久移転 | MOVED |
| 404 / 410（恒常） | DEAD |
| リクエスト不成立（DNS/timeout/プロキシ遮断） | **UNVERIFIED（DEADにしない）** |

CI実測への適用: 14/14日失敗＋腐敗根拠あり→DEAD、14/14日失敗だが提供元存命の
傍証あり→DEGRADED、14/14日成功→HEALTHY（method=legacy_ci_report）。

## 3. LIVE CHECK RESULT: 環境遮断により実行不能（0/86）

較正試行（2026-08-29）: `feeds.bbci.co.uk` / `federalreserve.gov` / `boj.or.jp` への
HTTPSが全て egress proxy の **CONNECT 403（policy denial）** で不成立。
`__agentproxy/status` により本開発環境の許可先はdev基盤（GitHub/pypi等）のみと確認。

- 対応: live checkは**実行せず**、該当ソースはUNVERIFIEDのまま
  `method: live_check_blocked` を明記（詐称しない）。
- 補完手段: `health_check.py` はtransport注入式のため、ネットワークのある環境
  （GitHub Actions runner — Legacy CIが毎日フィード取得できている実績あり）で
  そのまま実行し、`SourceHealthObservation` を積める。実行はP1-C以降の承認事項。

## 4. 監査結果サマリ（86ソース）

| state | 件数 | 根拠 |
|---|---|---|
| HEALTHY | 18 | Legacy CI 14/14日配信確認（2026-08-16..29） |
| DEGRADED | 3 | Legacy CI 14/14日失敗だが提供元存命の傍証あり |
| AUTH_REQUIRED | 2 | APIキー必須仕様（キー未設定） |
| RATE_LIMITED | 0 | — |
| MOVED | 0 | — |
| DEAD | 3 | 提供終了の傍証＋CI 14/14日失敗 |
| UNVERIFIED | 60 | 現在evidenceなし（live check遮断。うち36はtank実績あり=過去のみ検証済み） |

### HEALTHY（18）
yahoo_jp_business, nhk_business, yahoo_jp_toppicks, nhk_general, cnbc_markets,
dmb_cnbc_markets, dmb_marketwatch_top, marketwatch_market, wsj_markets,
bloomberg_markets, yahoo_finance_us_all, investing_news, dmb_ecb_press,
us_sec_press, bls_latest, eia_today, coindesk, cointelegraph

### DEGRADED（3）— Legacy CI 14/14日取得失敗・原因分析

| id | 分析 |
|---|---|
| fed_press | tankは2026-06〜07に適正UAで14記事取得済み → **クライアント条件（UA等）ブロック疑い**。Fed/SEC等の米公式サイトはUA要件が既知 |
| dmb_boj_whatsnew | RDF形式。**LegacyパーサーのRDF非対応疑い**またはクライアント条件。EN側 `boj_whatsnew` はtank実績36記事 |
| mof_whatsnew | RDF形式。同上。フィード自体の死活は本環境から未確認 |

注: CI失敗6件のうちRDF形式が3件（nikkei含む）を占める。Legacy側の取得・パース系
（RSS2中心）との形式不整合が失敗の一因である可能性が高い（P1-CのRDFアダプタで検証）。

### DEAD（3）

| id | 根拠 | 代替 |
|---|---|---|
| reuters_business | tank時点でlikely_dead（agency feed提供終了濃厚）＋CI 14/14失敗 | yahoo_finance_us_all |
| nikkei | 日経公開RSS提供終了＋CI 14/14失敗 | yahoo_jp_business |
| yahoo_jp_reuters | Yahoo!ニュースのロイター配信面消滅＋CI 14/14失敗 | yahoo_jp_business |

### AUTH_REQUIRED（2）
edinet_disclosures（EDINET API v2: Subscription-Key必須）、estat_macro（e-Stat: appId必須）。
いずれもキー未設定。**キー値はどこにも記録しない**（auth_typeの列挙記録のみ）。

### UNVERIFIED（60）
CI非対象のtank系ソース。うち**36はtank実績（articles_observed>0）を持つが、これは
2026-06-22..07-22の過去実績であり現在正常の根拠にしない**（歴史⇔現在の分離、
テストで機械強制）。残り24はtank時点でも未検証（enabled: falseが中心）。

## 5. CI実測の詳細（recent_ci、window 2026-08-16..2026-08-29）

- 抽出方法: 各日レポートのデータ品質カード `取得失敗ソース` を14日分パース。
- 結果: **14日全日でカードあり。失敗は毎日同一の6ソース**（fed / boj / mof /
  nikkei / reuters / ロイターYahoo経由）で恒常故障。他のCI対象18ソースは
  14/14日配信（2026-08-29カード: 情報源42・RSS取得221件・最新08/29 05:10）。
- 表示名→カタログid対応: fed→fed_press、boj→dmb_boj_whatsnew（JP RDF）、
  mof→mof_whatsnew、nikkei→nikkei、reuters→reuters_business、
  ロイター(Yahoo!ニュース経由)→yahoo_jp_reuters（collectors実装のURLで突合）。
- 鮮度: 8/29カードの平均鮮度599時間は死んだソースを含む全体平均。HEALTHY判定は
  「当日カードで失敗掲載なし＋レポートに当日ニュース反映」に基づく。

## 6. リスク・限界（正直な申告)

1. live check 0件のため、UNVERIFIED 60件の現在死活は不明のまま（P1-C初回接続で解消）。
2. CI実測は「Legacyパイプライン経由で取れたか」であり、フィード自体の死活と
   完全には一致しない（DEGRADED 3件の原因切り分けはlive check実行後に確定）。
3. DEAD判定3件は「CI全滅＋提供終了の傍証」による。万一復活が確認されたら
   観測を積んで導出状態を更新する（レコードは追記式なので巻き戻し不要）。
4. `declared_format: unknown`（53件）はwire形式未実証の明示であり欠陥ではない。
   P1-C初回接続時に `classify_format` で実測確定する。
