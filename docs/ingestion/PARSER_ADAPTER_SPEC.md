# PARSER_ADAPTER_SPEC — パーサー/アダプタ仕様（Phase 1-C）

## 1. 対応フォーマットと優先順（P1-B監査の帰結）

| 優先 | 形式 | 実装状況 | 根拠 |
|---|---|---|---|
| 1 | RSS2 | 実装済み（feed_parser.py） | カタログ21件がwire実証済み。最多 |
| 2 | Atom | 実装済み | EDGAR系4件＋uk_gov等が依存。旧系の「Atom無視」欠陥の解消 |
| 3 | RDF (RSS1.0) | 実装済み | CORE mof_whatsnew / dmb_boj_whatsnew の復旧に必要（CI恒常失敗の原因候補） |
| 4 | JSON API | 枠組みのみ | 検出＋Raw保存まで。EDINET/e-Statの本格正規化はP1-D以降 |

## 2. 形式検出（unknown 53件への回答）

`detect_format(body, content_type)` の判定順:
1. content-typeがjson → JSON_API
2. body signature（`{`/`[`） → JSON_API
3. XMLパース → ルート要素: `rss`→RSS2 / `rdf`→RDF / `feed`→ATOM / `html`→HTML
4. パース不能 → HTML signature確認 → それ以外は**UNKNOWN**

**判別不能を無理にRSS扱いしない**。UNKNOWNでもRawResponse/RawItemは保存される
（bodyはblobに無傷で残るため、後からパーサーを足して再処理できる）。

## 3. entry抽出（正規化前・無損失）

`FeedEntry`: title / link_original / link_canonical / guid / published_raw /
updated_raw / summary_excerpt(≤400字) / raw_xml（エントリ要素の無損失控え）。

- **published等の日時は文字列のまま**（Fact化しない）。分類はdate_quality.pyの
  `resolve_published()` → SOURCE_PROVIDED_TZ / SOURCE_PROVIDED_NAIVE / UNPARSABLE /
  MISSING ＋ anomaly（future/too_old）。naiveをUTC仮定で確定させない
  （P1-A Open Question②の監督者決定準拠）。inferred値の採用はP1-Dの明示判断。
- **link_originalを必ず保持**。link_canonical（tracking除去・表記ゆれ吸収）は
  dedup用の派生値であり、originalの代替ではない。
- guid: RSS2 `<guid>` / Atom `<id>` / RDF `rdf:about`。permalinkフォールバックあり。
- malformed itemはそのitemだけスキップし`skipped_items`で件数申告。
  malformed feedは`error`付きFeedParseResult（例外を投げない）。

## 4. エンコーディング

UTF-8固定禁止。decode優先順: BOM → HTTP charset → XML宣言encoding →
utf-8/cp1252/latin-1 → utf-8+replace（lossyフラグ）。decode失敗でも
**raw bytesはblobに保存済み**で失われない。

## 5. 認証付きAPI（EDINET / e-Stat）— 契約のみ（P1-C）

- 現状AUTH_REQUIRED。**キー未設定はP1-C完了をblockしない**。
- adapter契約: エンドポイントはSourceEndpoint（auth_type=api_key_query記録）のまま、
  資格情報は実行環境の環境変数/Secretsからtransport呼び出し直前に注入する設計とする。
  - 公式仕様がheader方式を許すなら移行（推測でheader化しない。仕様確認が先）。
  - query必須の場合: 送信URLにのみ付与し、**保存系（FetchAttempt/RawItem/ログ）へは
    redact_url通過後のURLのみ**を残す（`Subscription-Key=REDACTED` 等。テスト済み）。
- FetchRequestは資格情報ヘッダを型レベルで拒否するため、header注入方式を実装する際は
  transport実装内（保存経路の外）で付与する。

## 6. Phase 2へ残す責務

semantic/syndicated duplicate（title_hash系）・cross-publisher統合・
記事本文の取得・NewsItem構造化（tank記事モデル約70フィールドの受け皿）。
