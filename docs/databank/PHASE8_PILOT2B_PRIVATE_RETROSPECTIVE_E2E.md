# PHASE 8 / P8-PILOT2B — PRIVATE RETROSPECTIVE E2E RUNNER（本人の環境でだけの、取得の authority の配線）

PILOT2 runner（`src/intelligence/jquants_pilot2_local.py`。PILOT2A）の狭い再開。`execute --acquired-at` を渡した時だけ、fins の handoff から
凍結 ACQ0 の取得 event → 凍結 EXE → 凍結 EPOCH1R の manifest → 凍結 F1 の保持 record → 凍結 A3-RA の 4 指標 → 安全な要約、を composition
する。runner は orchestration だけ: 式 ・判定の複製 ・値の保存 ・時計 ・screening は無い。本 gate は**合成の検証だけ**（実 request なし）。

- 基準: P8-A3-RA `d424a720cfc20a6259a95c7a74ab9533628547a2`（凍結。runtime 43）。full pytest の基準 6301 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の値 ・会社名 ・code を載せない。例はすべて合成。
- 公開の出力（Pages ・Morning Brief）・LLM への payload ・GitHub への provider 由来の数値 ・screening ・順位 ・推奨は**無い**。

---

## 0. 監督の決定（PILOT2B-R1）

| 決定 | 内容 | 実装 |
|---|---|---|
| D-P2B-1 | 取得の瞬間は人が `--acquired-at <aware ISO8601>` で明示する。runner は時計を読まない。`accepted_at <= acquired_at`。そのまま意味の瞬間として使う。同じ取得の再開は同じ値、再取得は新しい値 | `_parse_acquired_at`（naive ・不正 ・欠落は network の前に拒む）・`ACQUIRED_AT_BEFORE_ACCEPTED_AT` |
| D-P2B-2 | `identity_valid_at = event.acquired_at`（period_end ・D0 の 0 時 ・固定の時刻 ・accepted_at は使わない） | `_retrospective_metrics`: `authority_as_of = identity_valid_at = acquired_at` |
| D-P2B-3 | EXE に `AdapterContext(issuer_id, acquired_at=event.acquired_at)` を渡す。EXE-R の規則（初見 ＝ 開示の知識 ・同じ自然 key の修正 ＝ 取得の知識 ・新 DiscNo ＝ 自身の開示）は EXE が決める | `_authority_chain`（runner は規則を選ばない。test が初見 ・修正の知識を pin） |
| D-P2B-4 | 営業利益率 ・純利益率: 支える FY ／ 累計の中で最大の period_end。ROA: FY だけ。売上成長率: 凍結の期間の関係が comparable な prior を持ち、両期間に保持 authority がある最初の target | `_target_candidates` ・`_select_target` ・`_revenue_growth_entry` |
| D-P2B-5 | pagination_key があれば event は PARTIAL_PAGINATED。page は追わない。F1 ・指標は呼ばない。pilot は PARTIAL | `_acquisition_event` ・`_authority_chain` の短絡 |

## 1. authority の鎖（1 発行体 ・1 取得）

1. **fins の handoff**（凍結 LIVE1。request 予算 ≤ 8 ・再試行なし ・page を追わない。変更なし）。
2. **ACQ0 の event**: `bounded_content_digest(FINS_SUMMARY_PATH, rows)` ・`RequestScope.of(FINS_SUMMARY_PATH, {"code": C})` ・provider JQUANTS ・
   api v2 ・`acquired_at` ＝ 明示の瞬間 ・COMPLETE（pagination_key なし）／ PARTIAL_PAGINATED。凍結 `AcquisitionEventStore` に追記
   （同じ event は REUSED ・同じ id の内容の衝突は fail closed）。
3. **resume の結び付き**（§5）: `pilot2/acquisition_state.json` に 範囲の hash → {content_digest, acquired_at, event_reference, completed}。
   同じ範囲 ・同じ内容 ・**未完**の取得を違う `acquired_at` で再開しようとすると `ACQUIRED_AT_RESUME_MISMATCH`（PILOT_FAILED ・新しい epoch は
   作らない）。完了した取得の後の再取得は新しい `acquired_at` で新しい epoch（正しい）。code ・値は書かない。
4. **EXE**（凍結 ADP0 ＋ EXE ・`acquired_at` 付き）→ A2 ・注記 ・保留。
5. **manifest**（凍結 EPOCH1R `build_manifest` → `record_manifest`。journal の順から membership を作らない。EPOCH1 が拒めば manifest は無い）。
6. **F1**（凍結 `execute_provider_holdings`。G3 ・保留 ・観測の検証 ・record の構造はすべて F1）。
7. **A3-RA**（凍結 `resolve_retrospective_metric` × 4。保持の像 ・manifest の像 ・A1R の修正の authority ・A2 の像 ・A2R の注記は明示）。
8. **安全な要約**（§3）。

## 2. target の選択（journal ・行 ・file の順は使わない）

候補 ＝ 主語の保持 record（`holdings_as_of <= acquired_at`）× 結び付いた manifest の CANONICAL の entry（`period_end` 一致 ・連結）→
period_end ごとの `ReportingPeriod` の集合。
- 営業利益率 ・純利益率: FY ／ CUMULATIVE の候補の中で period_end 最大。同じ period_end に意味の違う期間が複数 → `UNAVAILABLE / TARGET_AMBIGUOUS`
  （任意に選ばない）。候補なし → `UNAVAILABLE / NO_SUPPORTED_TARGET`。
- ROA: FY の候補の中で period_end 最大。
- 売上成長率: target を period_end の降順に見て、より前の候補を comparison に凍結 A3-RA を呼び、内側の理由に凍結の期間の関係の code
  （`PERIOD_BASIS_UNSUPPORTED` ・`FISCAL_YEAR_IRREGULAR` ・`PERIOD_BASIS_MISMATCH` ・`PERIOD_QUARTER_DIFFERS` ・`PERIOD_NOT_ADJACENT`）が無い
  最初の対を選ぶ。無ければ `UNAVAILABLE / NO_COMPARABLE_PRIOR_PERIOD`。式 ・関係の複製は無い。
- 4Q ・OtherPeriod は上流で保留（期間 None → F1 が取得全体で 0 record → `PILOT_HOLD`）。

## 3. 安全な要約（`safe_summary.json` の追加分。key は test が pin）

```
acquisition_authority:
  schema, state (NOT_REQUESTED | REQUESTED), acquired_at (ISO), issuers: [
    acquisition: {status (COMPLETE | PARTIAL_PAGINATED | INVALID | STORE_FAILURE | RESUME_MISMATCH), reused, row_count}
    manifest:    {status (APPENDED | REUSED | NOT_ATTEMPTED | <EPOCH1 の失敗>)}
    f1:          {status, appended_count, reused_count}
    holdings_epoch_count
    retrospective_metrics: [{metric, target_available, outer_status, has_value, resolution_mode, diagnostic_codes,
                             observation_id_count, epoch_ref_count}]
    failure_code ]
store_integrity: 4 store ＋ acquisition_events ・manifests ・provider_holdings
```
載らないもの: 会社名 ・code ・財務の値 ・派生の指標の値 ・raw の行 ・payload ・credential ・観測 ・manifest ・保持 record の内容 ・参照（`jq.*`）。
`has_value` だけが「値が在った」ことを伝える。private の詳細 artifact は作らない。

## 4. pilot の状態（監督が固定）

- **PILOT_PASS**: identity ・COMPLETE の取得 ・EXE に REJECTED ／ PARTIAL なし ・manifest APPENDED ／ REUSED ・F1 APPENDED ／ REUSED ／ MIXED ・
  A3-RA の orchestration が完了し `AUTHORITY_FAILURE` ・`AMBIGUOUS_AUTHORITY` ・`INVALID_INPUT` が無い。VALUE_ABSENT ・SEMANTIC_HOLD ・
  NOT_COMPARABLE ・UNDEFINED ・UNAVAILABLE は infrastructure の失敗ではない（4 指標すべての VALUE は要らない）。
- **PILOT_HOLD**: F1 `UNKNOWN_PERIOD_HELD_ROW`。
- **PILOT_PARTIAL**: PARTIAL_PAGINATED ・F1 `NO_CANONICAL_PERIODS` ・予算の枯渇 ・他の明示に不完全な取得。
- **PILOT_FAILED**: store の破損 ／ 衝突 ・ID2 の拒否 ・EXE の拒否 ・manifest の authority の失敗 ・F1 PRECHECK ／ STORE の失敗 ・A3-RA の
  AUTHORITY_FAILURE ／ AMBIGUOUS_AUTHORITY ／ INVALID_INPUT ・時間の軸の違反（resume の不一致を含む）。
- `--acquired-at` を省いた実行は PILOT2A の経路（`acquisition_authority.state = NOT_REQUESTED`。凍結 PILOT2A の契約のため残す）。

## 5. resume

既存の private root はそのまま使える。無い journal（取得 event ・manifest ・保持）だけを作る。identity ・観測 ・保留 ・event ・manifest ・保持
は書き直さない ・消さない ・修復しない。同じ `acquired_at` の正確な replay は ID2 ・EXE ・event ・manifest ・F1 のすべてが REUSED に収束する
（test）。PILOT2A だけを済ませた root に PILOT2B を重ねても A1 ・A2 ・注記 ・保留の journal は byte 不変（test）。

## 6. 既知の制約（真の typed な結果）

identity の coverage は ID1 の bootstrap の D0 の 1 日。D0 の翌日以降の `acquired_at` では A1R の遡及の identity が解けず、4 指標は
`INSUFFICIENT_DATA / SUBJECT_NOT_RESOLVED`（infrastructure は PASS）。実の検証では **prepare ・審査 ・execute を D0 の同じ営業日に**行う
（I1 の identity の continuity は未配線）。

## 7. 後で承認される実の検証の手順（本 gate では実行しない ・依頼しない）

1. 本人の Windows で private root を用意（repo の外）。credential は環境変数だけ（runner は値を出さない）。
2. `prepare --d0 <当日> --codes <≤3> --data-root <ROOT>`（request 1）→ `decision.json` を人が書く（APPROVE ・aware な accepted_at）。
3. 同じ営業日に `execute --data-root <ROOT> --acquired-at <aware な今の時刻を人が明示>`（request ≤ 3）。
4. 共有するのは `pilot2/safe_summary.json` だけ（`has_value` ・status ・診断 code。値 ・code ・会社名は無い）。
5. 再実行は同じ `--acquired-at`（収束）。新しい取得は新しい `--acquired-at`。

## 8. 次の gate

監督の審査 → 実の Windows の検証（承認後）。screening ・順位 ・推奨 ・Phase 9 は無い。
