"""Replay / Simulation（Phase 3.9.4）— 凍結規則を過去の corpus prefix に適用する回顧的安定性研究。

NOT_PREDICTIVE / NOT_FORMAL_APPROVAL / HUMAN_FEEDBACK_ONLY / IMMUTABLE_INPUT_UNIVERSE

境界（絶対）:
- Decision / human review event / DNA を書かない（書き込み API を import しない）
- production corpus / research / evaluation / shadow review を読まない・書かない
  （corpus は SQLite backup で凍結 copy を取り、Context は行を 1 回だけ書き出して凍結する）
- PDF を開かない（corpus に保存済みの artifact だけを使う）
- Phase 3.8 / 3.9.2 / 3.9.3 の規則・閾値・policy を変更しない

1機能=1ファイル:
    errors.py     fail-closed 例外
    config.py     compass_replay policy（versioned + digest・stability 閾値は v1.1.0 で CALIBRATED_CORPUS_139_V1 として凍結）
    snapshot.py   corpus の一貫 SQLite backup / Context の immutable export / drift 観測
    manifest.py   入力宇宙の確定（identity・除外・digest・改変検出）
    view.py       prefix 外アクセスを例外で拒む CorpusStore 互換 view
    ordering.py   CHRONOLOGICAL / INGESTION 順序と position 計画
    research.py   run_incremental 前進・checkpoint・rebuild 等価
    evaluate.py   一時 3.9.2 / 3.9.3 実行・leakage / identity / sanity 監査
    timeline.py   timeline row（禁止 key 検査・semantic digest）
    events.py     FIRST_* / *_CHANGED 派生
    metrics.py    安定性指標・provisional 分類
    stress.py     APPROVE / REJECT stress・formal_review_input（production 参照は read-only）
    store.py      compass_replay/ 出力（derived・atomic）
    runner.py     orchestration
    cli.py        run [--retain-temp --from-run --enable-full-replay] / summary / show / list-runs / validate-policy
    validation.py Windows 実機 1 操作の real-data validation（::P394_*:: marker、fail closed）
"""
