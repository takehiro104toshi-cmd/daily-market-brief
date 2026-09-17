"""predictions — Prediction Journal（Phase 5）。

- purpose: FORECAST を検証条件・検証日・horizon 付きで記録し、市場実績と自動で
  答え合わせして精度・較正（confidence calibration）を測る。
- boundary: **本番 runtime から到達してはならない研究 subsystem**である
  （`tests/intelligence/test_p43b2c_production_bundle.py` の `EXCLUDED_PACKAGES`
  に `predictions` が含まれ、production runtime closure がここへ import 到達
  しないことを機械的に固定している）。Pages / publication / producer /
  governance / Compass DNA のいずれにも依存しない。
- 現在の内容: Phase 5 Entry Contract の **research 用 module のみ**
  （A0.7 一回限りの TOPIX 取得 driver / A0.5R offline の neutral-band 測定 runner）。
  P5-1 Prediction Journal / P5-2 Automatic Evaluation は**未実装**であり、
  監督者の Entry Contract 凍結を待つ。
"""
