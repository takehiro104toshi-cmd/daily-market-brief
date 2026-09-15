"""J-Quants Production Data Strategy（Phase 3.6）。

J-Quants Light を pilot data source から **production-grade incremental market data
source** へ昇格させるための運用設計層。新しい分析機能は追加しない。

- capability registry（実測済み endpoint の machine-readable 台帳）と **J-Quants First** gate
- dataset frequency classification / morning data contract
- rolling window（seed / retention / calculation / safety buffer を分離）
- daily incremental update（欠落 session だけ取得・冪等・rerun-safe）
- session gap detection / repair policy / master refresh & diff
- corporate action / weekly flow / financial summary / earnings calendar / TOPIX の contract
- storage & request budget / failure & retry policy / schema drift / health snapshot /
  morning readiness / plan upgrade register / 52週高値安値の判断

Standard / Premium endpoint を迂回しない。plan upgrade を自動実施しない。
credential は runtime injection のみ。canonical は append-only（rolling ≠ 削除）。
"""
