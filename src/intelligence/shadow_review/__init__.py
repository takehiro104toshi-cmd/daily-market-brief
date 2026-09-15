"""Shadow Review（Phase 3.9.3）— 「今日、人間が何をレビューすべきか」だけを決める層。

Phase 3.9.2 が「engine は何を推奨するか」を答える。この層は推奨を**再分類せず**、
優先順位付け・型分散・説明・人間 feedback の記録だけを行う。

境界（絶対）:
- Recommendation state を書き換えない / 新しい state を作らない
- formal APPROVED / REJECTED を書かない（Decision は Phase 3.9.1 のもの）
- Compass DNA へ promote しない
- Phase 3.8 research artifact / Phase 3.9.2 evaluation record / Phase 3.9.1 decision history を変更しない
- 本文・page text・path・ファイル名を保存も表示もしない
- SHADOW MODE / NOT_PREDICTIVE / NOT_FORMAL_APPROVAL / HUMAN_FEEDBACK_ONLY / CORPUS_100_FORMAL_GATE

1機能=1ファイル:
    config.py     compass_shadow_review policy（versioned + digest・fail closed）
    models.py     event / card schema・禁止 key の再帰検査・理由要件
    material.py   material change digest（Reference Score を構造的に除外）
    ranking.py    Phase 3.9.2 ordering_key を基底にした決定的順序
    diversity.py  REVIEW の型 round-robin + hard cap（REJECT / APPROVE は bypass）
    explain.py    triggered_rule ごとの決定的テンプレート（LLM 不使用・未知は fail loud）
    cooldown.py   outcome ごとの cooldown（0 = material change のみ）
    events.py     append-only + hash chain の人間レビュー履歴
    state.py      履歴からの current state 導出（履歴は不変）
    queue.py      queue / summary / current_reviews の構築と atomic 置換
    cli.py        build / summary / list / show / history / validate / record
"""
