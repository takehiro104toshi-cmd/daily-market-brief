"""Decision Foundation（Phase 3.9.1）— research evidence と production Compass DNA の間の supervised Decision Layer の土台。

    Phase 3.8 evidence（pattern registry / DNA comparison / review queue: 読むだけ）
      → Phase 3.9 decision（append-only history、人間の明示 action）
      → APPROVED ≠ PROMOTED_TO_DNA（promotion は別 gate。3.9.1 では未実装 = 常に NOT_PROMOTED）

frozen policy（PHASE_3_9_SPECIFICATION_FREEZE_V1）:
- CORPUS_100（eligible ≥ 100）未満は SHADOW MODE: formal APPROVED は fail closed で作れない。
- auto approval なし。全 decision は HUMAN actor と非空 reason（policy v1 は保守的に全 state へ適用）。
- decision history は append-only（hash chain + 連番。改変・欠落は load 時に corrupt として拒否）。
- current state は history から決定的に導出。REJECTED → REOPENED_FOR_REVIEW、APPROVED → SUPERSEDED / RETIRED。
- production DNA（market_principles.py / market_rules.yaml）と Phase 3.8 registry / review queue には書かない。
- Compass DNA ≠ Personal DNA。評価・推奨・ranking・replay・promotion は 3.9.2 以降（ここには無い）。

1機能=1ファイル:
    policy.py        frozen policy（config.yaml compass_decision、versioned、digest、allowed transitions）
    models.py        DecisionRecord / EvidenceSnapshot / schema validation / deterministic ids / record hash
    store.py         append-only JSONL store（validate-before-append、hash chain、fail closed）
    state.py         current-state derivation（決定的）と transition check
    corpus_state.py  canonical corpus metric resolver（eligible_for_pattern_evidence）
    gates.py         CORPUS_100 formal approval gate / human action / reason
    evidence.py      compact evidence snapshot（Phase 3.8 artifact を読むだけ。本文なし）
    service.py       validate（読むだけ）/ decide（唯一の append path）
    cli.py           list / history / show / gate / validate（read）、decide（mutating、明示）
"""
