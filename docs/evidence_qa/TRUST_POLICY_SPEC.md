# TRUST_POLICY_SPEC — Trust Policy仕様（Phase 1-E）

## 1. 原則

- QAルールは将来変わる → policyは **name＋version** を持ち、Assessmentへ必ず記録。
- ルール変更＝**新versionの追加**（registryは同一versionの上書きを拒否）。
- 旧policyで判定済みのAssessmentは上書きせず、新policyで**再評価を追記**する
  （QA REPROCESSING。Rawの再取得は不要）。
- 「現在の判定」はassessment履歴からの**導出**（store.latest_for）。

## 2. policyパラメータ（TrustPolicy）

freshness閾値（fresh_hours / stale_hours）、horizon別許容age、状態別の厳しさ
（stale / published_unknown / superseded / conflicting / tier3 / source_dead /
usage_restricted / dependency_rejected それぞれのDimensionStatus）。

## 3. 実装済みpolicy（P1-Eの2 context）

| パラメータ | GENERIC v1.0.0 | DAILY_MARKET v1.0.0 |
|---|---|---|
| 想定用途 | 構造分析・一般Evidence | Morning Brief等「今日の材料」 |
| fresh | ≤72h | ≤24h |
| aging(WARN) | ≤30日 | ≤72h |
| stale | LIMIT | LIMIT |
| published不明 | WARN | **LIMIT** |
| superseded | WARN（歴史用途を広く許容） | **LIMIT**（現在値用途で旧版を制限） |
| conflicting | LIMIT | LIMIT |
| horizon上限 | intraday 24h / 1d 72h / 1w 14日 / medium 90日 / long 365日 | intraday 12h / 1d 48h / 1w 7日 |

freshness差はテストで実証済み（同じ48h前の文書: GENERIC=ACCEPT、
DAILY_MARKET=ACCEPT_WITH_WARNINGS。日付不明: GENERIC=WARN、DAILY=LIMITED）。

## 4. HORIZON-AWARE EVIDENCE

Assessmentは用途horizon（INTRADAY/1D/1W/MEDIUM/LONG）を文脈として受け取れる。
同じEvidenceでも「3か月前のCPI→今日の材料には弱いがmacro trendには使える」を
`stale_for_horizon`（LIMIT）で表現する。Forecast評価はForecastMetadata.horizonを
自動で引き継ぐ。

## 5. 将来の拡張（未実装・予約）

STRUCTURAL_THEME（数週間〜数か月）/ LONG_TERM_EQUITY（数四半期）等のpolicyは
register_policyで追加する。P1-Eでは2 contextでの差の実証まで（監督者指示）。
