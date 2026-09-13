# DATE_NORMALIZATION_SPEC — 日付正規化仕様（Phase 1-D）

P1-C DateQualityの正式活用。**source提供とinferredを絶対に混同しない**
（P1-A Open Question②の監督者決定の実装）。

## 1. 保持する区別

| フィールド（SourceDocument） | 内容 |
|---|---|
| published_raw | source供給の元文字列**そのまま**（常に保持） |
| published_at | 採用値（§2）。unknown（None）は正しい結果 |
| date_quality | source_provided_tz / source_provided_naive / unparsable / missing |
| published_inferred | published_atが推定値ならTrue（**機械可読**） |
| published_inferred_from | 推定根拠（P1-Dでは "url_date" と tank互換の "tank_fetched_at" のみ） |

## 2. 採用規則（NormalizedDate.adopted_utc）

1. source提供・tz付き・異常なし → その値（UTC正規化）。最高品質。
2. それが無い場合のみ、決定論的推定値（§3）。published_inferred=True。
3. どちらも無ければ **None（published_at = unknown）**。

規律:
- naive（tz欠落）はtimezoneを勝手に確定しない（採用しない。文字列と品質は保持）。
- 異常値（future: 基準+24h超 / too_old: 20年以上前）は**採用しない**が値は保持し、
  issue `date_anomaly_*` を記録（silent correction禁止・破棄もしない）。
- **retrieved_atをpublished_atへ黙って代入しない**（テストで機械検証）。

## 3. 決定論的推定（DATE INFERENCE）

P1-Dで許可する推定はルールのみ（LLM・現在時刻・外部検索は不可）:

- **url_date**: entryリンクのパスに `/2026/08/29/`・`2026-08-29`・`/20260829` 型の
  日付がある場合、UTC 00:00の日付精度値として推定。月日範囲を検証（13月等は不採用）。
- （tank互換のみ）**tank_fetched_at**: tankが補正済みのdate_inferred=Trueレコードを
  取り込む際、その事実をそのまま機械可読に引き継ぐ。

feed-level timestamp（channelのlastBuildDate等）による推定は候補として文書化のみ
（P1-Dでは未実装——entry日付との混同リスクの検討が先）。

## 4. 決定論の担保（timezone provenance含む）

- 異常判定の基準時刻は`RawItem.retrieved_at`（現在時刻に依存しない。
  同じRawItem→常に同じ結果。テスト`test_determinism_uses_reference_time_not_now`）。
- 元のtimezone情報はpublished_raw（例: "+0900"）に残る。published_atはUTC正規化するが
  provenance（元表記）を失わない。

## 5. Observationのas_of規律（同一原則）

JSON観測のas_ofはpayload内のtz付きISOのみ採用。無ければ観測を作らず
issue `missing_required_field: as_of (tz-aware)`（retrieved_atを黙って代入しない）。
