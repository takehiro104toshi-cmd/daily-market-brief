# OBSERVATION_NORMALIZATION_SPEC — 数値観測の正規化仕様（Phase 1-D）

数値source（index level / yield / FX rate / 経済統計 / 決算数値）をP1-A Observationへ
変換する枠組み。**明示schemaからのみ生成**（意味推測による数値抽出は禁止）。

## 1. JSON normalizer framework

- `JsonProviderSpec`: provider別の宣言的mapping（value_path / entity_id / metric /
  unit / currency / as_of_path / required）。ドットパスでフィールドを指す。
- `JsonRecordNormalizer` Protocol: 将来のEDINET / e-Stat adapterの共通口。
  P1-Dではsynthetic provider（synthetic_market_v1）でframeworkを実証済み。
  本格business mappingはP1-E以降。
- 例外を投げない: malformed JSON / 欠損 / 非数値 / 未知通貨は
  structured issue（invalid_numeric / missing_required_field / unknown_currency /
  unsupported_format）→ PARTIAL/REJECTED。

## 2. Decimal規律（P1-A方針維持）

- 金融数値にfloat禁止。`json.loads(..., parse_float=Decimal)` で**floatを経由せず**
  Decimal化（intもDecimalへ）。Observation構築時にも型検査（P1-A）。
- serializationはDecimal→文字列（精度保持）。roundtripテスト済み。

## 3. RAW vs DERIVED

| kind | 例 | 必須provenance |
|---|---|---|
| RAW | APIが直接 USDJPY=147.25 を提供 | source_id・calculation_method="api_field:{provider}:{path}" |
| DERIVED | 前日比・MA乖離等を本システムが計算 | **input_observation_ids＋calculation_method**（P1-A型が強制） |

`derived_observation()` ヘルパーで決定論的に生成（inputs空はValueError）。

## 4. 単位の取り違え防止（units.py）

「4.25 %」「0.0425 ratio」「425 bps」を雑に同一視しない:

- unit語彙: `pct` / `bps` / `ratio` / `pct_point`（差分。%と区別）＋ index/通貨単位等。
- 変換は明示的なDecimal演算のみ（pct_to_bps等6関数）。
- `same_quantity(a, unit_a, b, unit_b)`: 異unit比較は必ず変換経由。
  unit無視の同値判定はテストで拒否を検証。
- currencyはISO 4217主要通貨のallowlist検査（未知→unknown_currency issue）。

## 5. ID・決定論

observation_id = `content_id("obs", raw_item_id, entity_id, metric, as_of_utc_iso, version)`
— 同一入力＋同一versionで常に同一ID（再処理・再実行が冪等になる）。
処理時刻はNormalizationEventのみ。

## 6. Entity参照（推測mapping禁止）

sourceが明示提供する識別子（ticker / ISIN / country code / series ID等）は
entity_id（例: "fx:USDJPY", "rates:JGB10Y"）としてmapping specに**宣言的に**書く。
名寄せ・推測mappingはPhase 2 entity resolverの責務（P1-Dではしない）。
