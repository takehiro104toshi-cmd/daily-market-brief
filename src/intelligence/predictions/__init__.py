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
  supersession は append であり前の行を変更しない。評価 engine・「現在の評価」の解決は含まない）。
  P5-2C offline 評価 engine / P5-3 較正は**未実装**。
"""
