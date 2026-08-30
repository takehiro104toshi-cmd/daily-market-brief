# TOPIX_SOURCE_DECISION — TOPIX供給元の決定（Phase 2-G / G10）

原則: **TOPIX ≠ TOPIX ETF（1306.T等） ≠ TOPIX先物**。ETF・先物を指数seriesへ
投入しない（NO PROXY SUBSTITUTION——監督者裁定）。

## 1. 実測監査（probe run #6・2026-08-30）

| 経路 | 実測 | 判定 |
|---|---|---|
| Stooq `^tpx`（日足history） | HTTP 200でHTML制限ページ（共有IPダウンロード制限G9。run #1〜#7で一貫） | Actionsからは不達 |
| yfinance | TOPIX指数symbolなし（legacy configは1306.T ETFを「参考」としていた——流用禁止） | 不可 |
| JPX公式サイト | ページ到達可（HTML）。**自動取得向けの公開機械可読ヒストリカルCSV/APIは確認できず** | 自動化不適 |
| **J-Quants API** | `api.jquants.com` 到達確認（credential無しは403 JSON——到達性は実証）。JPX子会社 JPX Market Innovation & Research 運営の**公式データAPI**。`/v1/indices/topix` がTOPIX四本値（指数値そのもの）を返す | **採用（第一候補）** |

## 2. J-Quants調査結果

- **プラン**: Freeプラン=登録のみで利用可・**約2年分・12週間遅延**。
  Light（月額・有料）以上で遅延なしの当日値＋長期履歴。
  → **歴史バックフィルはFreeで可能・Phase 3朝の当日値運用にはLight以上が必要**
  （個人利用は規約上想定されている——最終確認はユーザーの契約時に）。
- **認証**: mailaddress/password → refreshToken → idToken（Bearer）。
- **取得フィールド**: Date/Open/High/Low/Close（TOPIX指数値）。

## 3. 実装（`src/intelligence/market/jquants_topix.py`）

- カタログ: `index:topix.close.closing.tokyo` preferred_source=jquants
  （PRIMARY_OFFICIAL・Tier1）。ETF/先物symbolはカタログに存在しない
  （テストで固定）。stooq ^tpxは記録として残すがchainへ入れない。
- **credential規律**: 環境変数（JQUANTS_MAIL / JQUANTS_PASSWORD または
  JQUANTS_REFRESH_TOKEN）からの**runtime injectionのみ**。Git/config/カタログへ
  保存しない。GitHub Actionsでは `secrets.JQUANTS_MAIL` 等の**参照**のみを
  workflowへ記述（値の投入はユーザー操作）。
- 値はJSONを `parse_float=str` で読みfloat非経由。応答bytesをそのままraw保存
  （複数ページは連結を申告）。永続化locatorへtoken/pagination_keyを含めない。
- credential未設定時は `no_credentials` の正直なGAP（捏造・代用をしない）。

## 4. 状態と解除条件

- 機構（provider・カタログ・パイプライン・テスト）は完成。
- **live実証はユーザーのJ-Quants登録＋repo secretsへの
  JQUANTS_MAIL / JQUANTS_PASSWORD 追加後**、次のpilot runで自動実行される
  （成功後にカタログprobe:false化→G10 RESOLVED）。
- それまでG10は**PARTIALLY_RESOLVED**（供給元決定・経路実装済み・live未実証）
  としてSOURCE_GAPS.md／health reportに正直に表示する。
