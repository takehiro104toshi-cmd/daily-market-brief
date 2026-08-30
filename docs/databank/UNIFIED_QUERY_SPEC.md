# UNIFIED_QUERY_SPEC — 統一クエリ仕様（Phase 2-F PART F/G）

Phase 3が必要とする**読み出し**の契約（分析エンジンはまだ作らない）。
契約はdomain（`databank/query.py`）に、SQLは参照実装
（SqliteNewsIndex / SqliteMarketIndex）に隔離。

## 1. NEWS QUERIES（NewsQuery・AND結合）

date range / publisher / source / language / **entity**（entity系次元横断）/
company / ticker / country / theme / event type / trust decision /
**classification provenance**（例: "user"のみ）/ **review status**
（当該record/articleにかかるReviewItemのstatus）/ limit。

実corpus複合例（実測）:
- `theme=ai, date 6/22-7/22` → 86件
- `company=company:nvidia, theme=ai` → 5件
- `review_status=open, theme=ai` → 5件

## 2. MARKET QUERIES（MarketQuery→SqliteMarketIndex.search_market）

series / instrument（prefix）/ metric / as_of範囲 / **trading_date範囲**
（セッション日——UTC暦日joinの代替）/ kinds（raw/derived）/ source（provider）/
**QA decision**（最新判定）/ **current_only**（改定解決）/
**latest_session_only**（series毎の最新セッション1件）。

latest意味論4種（latest_trading_session / latest_as_of / latest_revision_for /
revision_chain）はP2-Dから継続。

## 3. CROSS-DOMAIN FOUNDATION（market_window.py / cross_domain.py）

**TradingWindow**（name・start/end UTC aware・trading_date・session）:
- `jst_morning_window(day)` … 日本の朝の閲覧窓（6-9時JST→前日21時-当日0時UTC）
- `same_japan_trading_day_window(day)` … 東京現物セッション（9:00-15:30 JST）
- `previous_us_session_window(index, series, before_jst_date)` …
  **実データのtrading_dateから導出**（休日カレンダーを推測しない。データ無し=None）
- `event_window(ts, before, after)`

`fetch_window_slice(news_index, market_index, window, series_ids)` →
CrossDomainSlice（同一windowのnews＋market観測）。

TIMEZONE SAFETY: windowはaware UTC範囲＋（該当時）trading_dateで表現。
market紐付けはtrading_date優先・時刻窓はas_of比較——**UTC暦日で雑にjoinしない**
（例: JST朝窓 = 前日21:00Z〜当日0:00Zと機械変換される。テスト固定）。

**IMPORTANT**: causal分析（「このニュースで株価が上がった」）はしない。
同一windowのデータを並べて返すまで（CrossDomainSliceのnoteに明記）。

## 4. TEMPORAL AGGREGATION（PART G・数値集計のみ）

- `count_by_dimension_over_time(dimension, granularity=day/week/month, 範囲)`
  → (期間, 値, 件数)。theme/entity/event type等すべての分類次元に適用可
- `count_values(dimension)` → 値ごとの記事数
- `count_publishers_over_time(granularity, 範囲)` → (期間, publisher, 件数)

trend acceleration / emerging theme / bullish等の**判断APIは存在しない**
（Phase 6以降。実測値はOBSERVED COUNTとしてのみ報告する）。

## 5. review workflowとの結線

ReviewItemはreview_itemsテーブルへ索引され、news検索のreview_statusフィルタと
結合する（HUMAN_REVIEW_WORKFLOW.md参照）。
