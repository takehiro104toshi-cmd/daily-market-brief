# PHASE 8 / P8-EPOCH1R — HELD PERIOD METADATA REMEDIATION（保留 ／ 記載なしの entry の期間 ・区分）

P8-OBS60-F1 の監査（`P8_OBS60_F1_STRICT_SEMANTIC_GAP`。監督が確認）と P8-OBS60-F1-R の設計（監督: R-B ＋ C1 選定）に従い、
**EPOCH1 の manifest を狭く再開**して、HELD_SEMANTIC ／ UNSUPPORTED ／ NOT_REPORTED_ONLY の entry にも、凍結 ADP0 が決定論で確定した
期間 ・区分を持たせた gate。ProviderHoldingsCoverage ・F1 ・遡及の解決の変更 ・A3 ・PILOT2B ・実 request は**無い**。

- 基準: P8-A2C `0942218b4e5cfb520533e80bd1e2e576af7e8a9c`（凍結。runtime 39）。full pytest の基準 6156 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の値 ・会社名を載せない。例はすべて合成。

---

## 0. 結論

1. **なぜ期間が要るか**: F1 の監査で、保留の行（例: 連結は canonical ・単体は値の形で保留）と同じ period_end P に G3 coverage を作ると、凍結
   STRICT_PIT が保留の slot に偽の `NOT_FOUND` を返し、後の provider の修正が `COVERAGE_CONTRADICTION` で永久に拒まれることを示した。
   EPOCH1 の保留の entry は期間を持たなかったので、F1 は「どの P が影響を受けないか」を証明できなかった。本 gate はその metadata を足す。
2. **R-B（監督の決定 D-E1R-1）**: `ManifestEntry.period` ・`statement_basis` は既存の任意の欄のまま。CANONICAL は両方必須（不変）。
   HELD_SEMANTIC ／ UNSUPPORTED ／ NOT_REPORTED_ONLY は、凍結の意味論が確定したときだけ値を持ち、確定できなければ `None`。
   disposition の語彙は変えない（D-E1R-5）。
3. **公開 helper（D-E1R-2）**: 凍結 ADP0 に `derive_reporting_period(row)` を足した。既存の `_period` に**委譲するだけ**（算法の複製なし ・
   判定 ・写像 ・知識 ・区分 ・基準 ・通貨 ・値に触れない ・純 ・時計なし）。manifest の builder は私的名を import しない。
4. **既知の期間 vs 未知の期間**: 期間は凍結 ADP0 の `_period`（`CurPerType` ＋ 4 つの日付。FY ・累計 1Q〜3Q）で決まる。保留の理由に依らず
   行の欄だけから決まるので、`PERIOD_UNSUPPORTED`（4Q ・OtherPeriod ・日付の不整合 ・不正）のときだけ `None`。番兵の日付 ・取得日 ・開示日 ・
   推定の年度末で埋めない。
5. **区分**: 保留の行は保留 record（ST1）の `attempted_statement_basis`（凍結 ADP0 の `map_row_semantics` の結果そのもの）。`STATEMENT_BASIS_UNKNOWN`
   のときだけ `None`（DOCTYPE_UNRECOGNIZED ・DOCTYPE_OUT_OF_SCOPE は常に伴う）。記載なしの行は凍結 ADP0 の適格の材料（`adapt_financial_summary_row`
   が ELIGIBLE を返す）から期間 ・区分を取る。第 2 の区分の写像は作らない。
6. **整合の検査（fail closed）**: `PERIOD_UNSUPPORTED` の有無と期間の `None` の有無が合わなければ `ENTRY_INVALID / HELD_PERIOD_INCONSISTENT`、
   `STATEMENT_BASIS_UNKNOWN` の有無と区分の `None` が合わなければ `HELD_BASIS_INCONSISTENT`。黙って正規化しない。
7. **汚染の意味（D-E1R-3 ・D-E1R-4。F1 は未実装）**: HELD_SEMANTIC ／ UNSUPPORTED は将来の不在の authority を汚す（`contaminates_absence`）。
   期間が既知 → その period_end だけ withhold。`None` → 取得全体で ProviderHoldingsCoverage を 0 件。NOT_REPORTED_ONLY は汚さない
   （行は在り ・値は記載なし ＝ 将来の `VALUE_ABSENT`。`NOT_FOUND` ではない）。
8. **版 ・id**: `MANIFEST_SCHEMA_VERSION` 0.1.0 → 0.2.0、`MANIFEST_RULES_VERSION` 0.1.0 → 0.2.0、`BUILDER_RULES_VERSION` 0.1.0 → 0.2.0
   （別々の定数。executor ・mapping の版は触らない）。非 canonical の entry を持つ manifest の id は EPOCH1 の合成の表現から変わる（期待どおり）。
   実の authoritative な manifest は存在しないので移行 ・backfill は無い。同じ意味の manifest → 同じ id、保留の metadata が違う → 違う id。
9. **store**: `ManifestStore` の runtime は変えていない。新しい schema の record は既存の parser（`from_dict`）で往復する。REUSED ・
   MANIFEST_CONFLICT ・破損の fail closed は不変。
10. **privacy**: 足した metadata は期間と区分だけ。値 ・会社名 ・raw の行 ・credential ・HTTP の metadata は構造上入らない。
11. **provider の修正**: epoch 1 で保留（期間 P 既知）→ manifest1 は HELD ＋ P。epoch 2 で修正された canonical の行 → manifest2 は CANONICAL ＋
    観測 id。manifest1 は不変 ・遡及の canonical membership は無い。
12. **凍結の層**: 再開は ADP0 の adapter（公開 helper の追加だけ。`_period` ・判定の AST は不変）・EPOCH1 の model ・builder だけ。
    A1 ・A1R ・A2 ・A2C ・A3 ・ACQ0 ・EXE-R ・ST1 ・I1 ・ID1 ・ID2 ・LIVE1 ・LIVE2 ・PILOT2A ・manifest store は A2C の anchor と byte 一致
    （guard `test_epoch1r_*`。差は AST の形で該当の def ／ class ／ 定数に限る）。

---

## 1. 保留の理由と metadata（凍結 runtime で確認）

| 保留の理由 | 期間 | 区分 | disposition |
|---|---|---|---|
| VALUE_UNPARSEABLE | 既知 | 既知 | UNSUPPORTED |
| DOCTYPE_UNRECOGNIZED（＋ STATEMENT_BASIS_UNKNOWN ・基準 ・通貨） | 既知 | None | UNSUPPORTED |
| DOCTYPE_OUT_OF_SCOPE（REIT 等。＋ STATEMENT_BASIS_UNKNOWN） | 既知 | None | UNSUPPORTED |
| PERIOD_UNSUPPORTED（4Q ・日付の不整合） | **None** | 既知 | UNSUPPORTED |
| STATEMENT_BASIS_UNKNOWN（OtherPeriod …。PERIOD_UNSUPPORTED を伴うことが多い） | 理由に従う | None | UNSUPPORTED |
| ACCOUNTING_STANDARD_UNKNOWN（Foreign。＋ CURRENCY_UNKNOWN） | 既知 | 既知 | HELD_SEMANTIC |
| ACCOUNTING_STANDARD_UNSUPPORTED | 現在到達しない（4 基準が pilot 適格） | — | HELD_SEMANTIC |
| KNOWLEDGE_TIME_INVALID（時刻の形 ・期末より前の知識） | 既知 | 既知 | UNSUPPORTED |
| MAPPING_UNSUPPORTED（参照の token の形） | 既知 | 理由に従う | UNSUPPORTED |
| IDENTITY_UNRESOLVED | — | — | manifest を阻む（EXECUTION_INCOMPLETE。不変） |
| SEMANTIC_CHAIN_CONFLICT（executor。基準の不連続） | 既知 | 既知 | HELD_SEMANTIC |
| NO_REPORTED_FIELDS（EXE） | 既知 | 既知 | NOT_REPORTED_ONLY |

---

## 2. 将来の C1 ／ F1 との関係

- **P8-A2C-R**: `ProviderHoldingsCoverage`（主語 ・period_end ・holdings_as_of ・取得 ・manifest の参照。`complete_through` を持たない）を
  別の追記専用 store に置き、遡及の resolver は epoch をそこから選び、不在の authority を manifest の期間（本 gate の metadata）から導く。
- **P8-OBS60-F1**: CANONICAL の entry が 1 つ以上ある period_end ごとに 1 record。HELD_SEMANTIC ／ UNSUPPORTED の期間が既知ならその P の
  不在を withhold、`None` が 1 つでもあれば取得全体で 0 record。A2 の `ObservationCoverage` は書かない（STRICT は不変）。
- 本 gate はそのどちらも実装しない。

---

## 3. 次の gate

P8-A2C-R（ProviderHoldingsCoverage の model ・store ・遡及 resolver の epoch の源と不在の導出）→ P8-OBS60-F1 → P8-A3-RA → P8-PILOT2B。
