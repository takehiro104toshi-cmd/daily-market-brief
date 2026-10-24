"""predictions — Prediction Journal（Phase 5）。

- purpose: FORECAST を検証条件・検証日・horizon 付きで記録し、市場実績と自動で
  答え合わせして精度・較正（confidence calibration）を測る。
- boundary: **本番 runtime から到達してはならない研究 subsystem**である
  （`tests/intelligence/test_p43b2c_production_bundle.py` の `EXCLUDED_PACKAGES`
  に `predictions` が含まれ、production runtime closure がここへ import 到達
  しないことを機械的に固定している）。Pages / publication / producer /
  governance / Compass DNA のいずれにも依存しない。
- 現在の内容: Phase 5 Entry Contract の research 用 module
  （A0.7 一回限りの TOPIX 取得 driver / A0.5R offline の neutral-band 測定 runner）と、
  P5-1A の `prediction_record`（不変の PredictionRecord schema ＋ 決定論的 identity）、
  P5-1B の `prediction_store`（`<data_root>/predictions/predictions.jsonl` への追記専用
  journal）、P5-1C の `prediction_ingest`（in-process の凍結 MorningBrief ＋ MarketSignal ＋
  生成 context を PredictionRecord へ**写す** offline adapter。再計算・評価は含まない）、
  P5-2A の `evaluation_record`（不変の EvaluationRecord schema ＋ identity ＋ realized outcome
  契約。TOPIX 参照・カレンダー照会・return 計算・較正は含まない）、P5-2B の
  `evaluation_store`（`<data_root>/predictions/evaluations.jsonl` への追記専用 journal。
  supersession は append であり前の行を変更しない。「現在の評価」の解決は含まない）、P5-2C の
  `evaluation_engine`（PredictionRecord ＋ カレンダー証拠 ＋ TOPIX 観測 → EvaluationRecord の
  offline 純関数。市場 outcome のみを評価し、予測の正誤・較正・network を含まない）、P5-3A の
  `calibration_contract`（較正の分析契約: 分析用 5→3 方向写像・active evaluation resolver・
  cohort・分母・sample disclosure・lineage。観測的 analytics であり production authority ではない。
  journal を読む analyzer と persistence は含まない）、P5-3B の `calibration_analyzer`
  （凍結 P5-3A 契約をそのまま適用する純粋 offline analyzer。record の iterable ＋ 明示 cohort →
  決定論的 CalibrationReport。store / market / calendar / engine / persistence を含まない）。
  P5-3C（`tests/intelligence/test_calibration_e2e.py`）と Phase 5 closeout（chain 合成
  `test_phase5_chain_e2e.py`、`docs/databank/PHASE5_COMPLETION_AUDIT.md`）まで完了し、
  Phase 5 の機構は OFFLINE で検証済み。runtime での capture / 評価 scheduling / 較正の
  永続化は N-6 により別の認可 gate（未着手）。
"""
