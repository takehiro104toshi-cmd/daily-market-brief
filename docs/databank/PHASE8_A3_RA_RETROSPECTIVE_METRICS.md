# PHASE 8 / P8-A3-RA — RETROSPECTIVE PROVIDER-AUTHORITY METRICS（遡及の provider authority の上の 4 指標）

凍結 A3（STRICT）の 4 指標の定義を、**別の解決の mode**（RETROSPECTIVE_PROVIDER_AUTHORITY）で算出する追加の層。
A2 の canonical の観測 ＋ `ProviderHoldingsCoverage`（A2C-R ・F1 が作る）＋ `AcquisitionManifest`（EPOCH1R）＋ A1R の遡及の identity ＋
凍結 `resolve_retrospective` を使う。配線（PILOT2B）・実 request ・新しい指標 ・保存 ・screening は**無い**。

- 基準: P8-OBS60-F1 `2a784a59429121070e32c367533cb30c3d0e02ec`（凍結。runtime 42）。full pytest の基準 6276 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の値 ・会社名を載せない。例はすべて合成。

---

## 0. 監督の決定（R1）

1. **P8_A3_RA_FROZEN_DEPENDENCY_FOUND を受理 ・R1 を選定（R2 は却下）**: 凍結 A3 の runtime（`metric_model.py` ・`fundamental_metrics.py` ・
   `fundamental_metrics_extended.py`）は byte 一致のまま。A3B が A3A の純 helper を in-package で再利用した先例を、sanctioned な再利用の
   authority とする。`ReasonCode` に member は足さない。
2. **sanctioned な再利用の面**（`SANCTIONED_A3_RA_IMPORTS` が完全一致で pin。他の private 名の import は新しい gate が要る）:
   `_ratio_minus` ・`_compatibility` ・`_period_relation` ・`_label_for` ・`_regular_fiscal_year` ・`_input_reasons` ・`_result` ・`_Leg`。
3. **`_resolve_leg` は使わない**: 内側で STRICT の `resolve` を呼ぶため。解決は凍結 `resolve_retrospective` に任せ、解決**後**の注記（A2R の
   注記の有無 ・観測 id ／ 区分の整合 ・値の状態 → `SEMANTICS_MISSING` ／ `SEMANTICS_MISMATCH` ／ `VALUE_ABSENT`）だけを `_annotate` が同じ順で
   再述する。式ではない。parity は test が pin する（有効 ・注記なし ・不一致 ・値なし ・基準 ・区分 ・通貨 ・桁 ・訂正後の鎖の頭）。

## 1. STRICT と RETROSPECTIVE の意味

| | STRICT A3（凍結） | RETROSPECTIVE A3（本 gate） |
|---|---|---|
| 問い | 世界 ／ PIT の authority（cutoff）で真に解けたか | 明示の後の authority で選んだ provider の保持 epoch から何を再構成できるか |
| 脚の解決 | `resolve`（世界の知識 ・A2 の coverage） | `resolve_retrospective`（保持 epoch ・manifest の membership ・A1R の遡及の identity） |
| 結果 | `MetricResult` | `RetrospectiveMetricResult`（外側）＋ 真に表せる時だけ内側の `MetricResult` |
| 式 ・互換 ・期間 ・Decimal | `fundamental_metrics` の純 helper | **同じ helper**（複製なし） |

どちらかを黙って他方に代えない。STRICT への fallback ・既定の「最新」・時計は無い。

## 2. 入口 ・入力（すべて明示）

`resolve_retrospective_metric(metric, history, *, subject_id, statement_basis, target_period, authority_as_of, identity_valid_at,
manifests, corrections, holdings, semantics, comparison_period=None)`。個別の入口 `operating_margin_retrospective` ・
`net_margin_retrospective` ・`roa_point_in_time_retrospective` ・`revenue_growth_retrospective`。`metric` は `MetricKind` の 4 つだけ
（それ以外は `UNSUPPORTED_METRIC`）。`semantics` は凍結 A3 と同じ契約（観測 id → `ObservationSemantics`。semantic store から読む）。

## 3. 外側の結果 `RetrospectiveMetricResult`

metric ・status ・subject_id ・statement_basis ・target_period ・comparison_period ・authority_as_of ・identity_valid_at ・value（VALUE の時だけ）・
metric_result（内側。真に表せる時だけ）・legs（脚ごとの `LegProvenance`: leg ・field ・period_end ・遡及の status ・diagnostic ・観測 id ・
`coverage_epoch_id`（`jq.pvh:`）・coverage_record_ids ・manifest_ref）・diagnostics ・resolution_mode ・rules_version
（`p8_retrospective_metrics:0.1.0`）・authority_class（`DERIVED_NON_AUTHORITY_NON_PERSISTENT`）。派生 ・非永続（record id ・保存 ・journal
・cache は無い。A2 ・保持の store は型で拒む）。

**外側の status**: `VALUE` ・`INVALID_INPUT` ・`INSUFFICIENT_TIME_PRECISION` ・`INSUFFICIENT_DATA` ・`SEMANTIC_HOLD` ・`NOT_COMPARABLE` ・
`UNDEFINED` ・`AUTHORITY_FAILURE` ・`AMBIGUOUS_AUTHORITY`。凍結 `ReasonCode` を overload しない。

## 4. 内側の `MetricResult` の規則

| 遡及の脚の結果 | 内側 | 外側 |
|---|---|---|
| FOUND → 値 | VALUE（凍結の式） | VALUE |
| VALUE_ABSENT ・NOT_FOUND ・OUTSIDE_COVERAGE ・BEFORE_COVERAGE ・NOT_YET_KNOWN ・SUBJECT_NOT_RESOLVED | 凍結の code（真） | INSUFFICIENT_DATA |
| 基準 ／ 区分の不一致 ・UNKNOWN ・期間の規則 | NOT_COMPARABLE（凍結の code） | NOT_COMPARABLE |
| 分母 0 ／ 負 | UNDEFINED（`DENOMINATOR_ZERO` ／ `DENOMINATOR_NEGATIVE`） | UNDEFINED |
| 入力の誤り（軸 ・像 ・期間 ・注記の lookup） | INVALID_INPUT（凍結の code。像 ・軸の違反は外側だけ） | INVALID_INPUT |
| **SEMANTIC_HOLD** | **なし** | SEMANTIC_HOLD |
| **MANIFEST_MISSING ・MANIFEST_CONFLICT ・MEMBERSHIP_INVALID** | **なし** | AUTHORITY_FAILURE |
| **AMBIGUOUS な epoch ・同じ期間の脚の epoch の不一致** | **なし** | AMBIGUOUS_AUTHORITY |

SEMANTIC_HOLD ・manifest ／ membership の失敗を NOT_FOUND ／ VALUE_ABSENT に写さない（嘘にしない）。VALUE_ABSENT は 0 ではない。

## 5. 4 指標（式は凍結のまま）

- 営業利益率 = OPERATING_INCOME ／ REVENUE、純利益率 = NET_INCOME ／ REVENUE（年度 ・累計。累計の期間の利益率）。
- ROA（時点の分母）= 年度の NET_INCOME ／ その年度の TOTAL_ASSETS（年度だけ ・平均総資産なし ・四半期の ROA なし）。
- 売上成長率 = target の REVENUE ／ comparison の REVENUE − 1（凍結 `_period_relation`: 年度 ↔ 直前の年度、累計 ↔ 直前の年度の同じ四半期の
  累計。TTM ・年率化 ・4Q の橋渡しなし。不規則な年度は NOT_COMPARABLE）。
- 基準 ・区分: 凍結 `_compatibility`（OBS57。橋渡しなし。UNKNOWN は fail closed）。通貨 ・桁 ・Decimal ・丸めは凍結 `_ratio_minus`。

## 6. epoch の provenance

- 同じ期間の全脚は 1 つの `coverage_epoch_id` を共有する（`SAME_PERIOD_EPOCH_RULE`）。違えば `AMBIGUOUS_AUTHORITY`（内側なし ・値なし）。
- 売上成長率の target と comparison は別の epoch でよい（それぞれ `LegProvenance` に記録。1 つの id に潰さない）。
- provider の修正: 修正前の authority → SEMANTIC_HOLD ／ 先の値、修正後 → 修正後の値。先の結果は再現する（不変）。
- 再取得: 同じ観測 ・同じ値 ・別の epoch ・別の manifest の参照。
- 訂正（新しい DiscNo）: 後の epoch の manifest が含む時だけ見える。前は先の member、後は訂正後の鎖の頭。

## 7. 孤立 ・非永続 ・privacy

STRICT A3 の 3 module ・STRICT の test は byte 一致（guard）。保持 record は STRICT に見えない。結果は保存しない ・authority にならない。
会社名 ・raw の行 ・credential ・header ・payload は載らない（派生の値 ・不透明な id ・参照だけ）。

## 8. 次の gate

P8-PILOT2B（本人の環境でだけの配線: 取得 → F1 → 遡及の指標の読み出し。公開の出力は無い）。
