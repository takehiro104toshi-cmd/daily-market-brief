# SOURCE_FAILURE_POLICY — ソース障害時ポリシー（Phase 1-B / 設計のみ）

2026-08-29。**本ステージではランタイム実装しない**（P1-C以降でこの設計に従って実装）。
背景となる教訓: Legacy系は同一6ソースが14日以上無警報で失敗し続けた
（SOURCE_HEALTH_AUDIT §5）。「無警報で腐る」の再発を防ぐことが本ポリシーの目的。

## 1. 役割別の障害時挙動

| role | 障害時の挙動 | ブリーフへの影響 |
|---|---|---|
| CORE | 続行するが**degraded run宣言**: 出力へ「本日は{source}が取得不能」を必ず表示。replacement_source / 同カテゴリSUPPORTへフォールバック。**連続2日でWARN、5日でエスカレーション**（人間へ通知） | 見出しに品質警告。CORE由来のFACT欠落を明示（無いことを黙って埋めない） |
| SUPPORT | 続行。フォールバック任意。**連続7日でWARN** | 品質カードに掲載のみ |
| CONTEXT | 続行。ログのみ。**連続14日で棚卸し対象**（DISABLE候補としてレビュー） | なし |
| DISABLE | 取得しない（対象外） | なし |

原則: **1ソースの障害でrun全体を落とさない**。ただしCOREが同時に過半失敗した場合は
run自体をFAILED扱いにする（「静かな空レポート」を出さない）。

## 2. 状態別の取得時ポリシー

| 観測 | その場の挙動 | 観測レコード |
|---|---|---|
| timeout / 接続不能 | リトライ（指数バックオフ、最大2回）。それでも不成立→当日skip | UNVERIFIED（http_status=0・理由note） |
| 429 | **リトライしない**。fetch_interval_minutesを当日2倍化 | RATE_LIMITED |
| 401 | リトライしない。キー設定状況の確認を促すWARN | AUTH_REQUIRED |
| 403 | リトライしない（UA/ブロック疑いのnote）。UA見直しはコード変更として扱う | DEGRADED |
| 404/410 | リトライしない。**連続3観測でDEAD確定**→role自動見直しはせず人間承認でDISABLE | DEAD候補 |
| 301/308恒久移転 | 当日は移転先を取得。カタログURL更新は**人間承認事項**（勝手に書き換えない） | MOVED（final_url記録） |
| 2xxだが0件/stale | 取得は成功扱い・品質warn | DEGRADED |

## 3. 状態遷移と復旧

- 状態は観測列からの**導出**であり、手で書き換えない（導出値を正とする）。
- DEAD→復活: 新しいHEALTHY観測が積まれれば導出状態は自動で戻る（巻き戻し作業不要）。
- DEGRADED→HEALTHY: 直近観測がHEALTHYになれば即復帰（ヒステリシスが必要になったら
  導出関数側で「直近3観測中2回HEALTHY」等へ拡張。保存データは不変）。

## 4. 節度ある取得（サイト側への配慮）

- User-Agent: 連絡先を含む正直なUAを名乗る（Fed/SEC系の要件。tankの実績パターン）。
- 頻度: カタログの `fetch_interval_minutes` を上限とし、条件付きGET
  （ETag / Last-Modified — 観測レコードにetag_present/last_modifiedを記録済み）を優先。
- 1フィード1リクエスト原則。エラー時の再試行は§2の範囲のみ。

## 5. Secret・ログ規律（docs/security/ 準拠）

- 認証はヘッダー渡しを第一候補。**URLへキーを含める実装はレビュー必須の例外**とし、
  その場合もログ・例外メッセージ・観測レコードのnote/final_urlへ**キー値を残さない**
  （tank T7の教訓）。redaction はfetcher層で一元実装する。
- 観測レコード（SourceHealthObservation）はSecretを持てない設計
  （フィールド自体が存在しない）。テストで維持。

## 6. 実装先（P1-C）

- fetcher基盤（REBUILD_ROADMAP P1-2）に §2 と §4 を実装。
- 品質カード/エスカレーション（P1-8の残り）はPhase 12 Observabilityへ接続。
- 本ポリシーの数値（リトライ回数・WARN閾値等）は実装時に `config` 化し
  ハードコードしない（knowledge/またはconfig.yamlへ。CLAUDE.mdルール8）。
