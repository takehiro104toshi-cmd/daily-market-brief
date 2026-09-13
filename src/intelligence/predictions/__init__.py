"""predictions — Prediction Journal（Phase 5）。

- purpose: FORECASTを検証条件・検証日・horizon付きで記録し、市場実績と自動で
  答え合わせして精度・較正（confidence calibration）を測る。
- boundary: 予測はEvidenceRecord(FORECAST)としてのみ受け入れる。検証は
  market層の実データに対して行い、全予測を単一指数で採点しない
  （Legacy investment_journalの既知の弱点を繰り返さない）。
- future responsibility: 記録・評価・較正統計（P5-1〜P5-3）。
"""
