"""Phase 3.9.5 First Formal DNA Review — human-bound evidence packets and a fail-closed guard in front of Phase 3.9.1.

    errors.py      fail-closed error classes（stable codes）
    config.py      compass_formal_review policy（versioned + digest、凍結: symmetry / no batch / NOT_PROMOTED）
    population.py  現在の evaluation から candidate / decided / reopen / context を動的選出
    groups.py      EVIDENCE_OUTLOOK narrow sibling group（Phase 3.9.2 contradiction key と同じ）・group_state_digest
    packet.py      evidence packet・packet_evidence_digest（人間が見た証拠の freshness anchor）・packet_id
    warnings.py    W_* warning code（表示と並び順のみ・新 gate なし）
    ordering.py    凍結 ordering（REJECT → APPROVE → REOPEN、section 非交互）
    reopen.py      REOPEN_ELIGIBLE（material_digest の変化のみ）
    progression.py queue progression（1.1.0・read-only）: KEEP_REVIEWING の DEFERRED / REENTERED / UNVERIFIABLE 分類
    guard.py       FormalReviewGuard（22 段の fail-closed 検査・metadata binder）
    metrics.py     運用 metrics（predictive 系なし）
    store.py       derived 出力（compass_formal_review/、atomic、rebuildable）
    service.py     build / decide（唯一の formal write path: guard → DecisionService.validate → decide）
    session.py     人間 1 人が 1 candidate を読むための決定的提示（10 節 brief・事実文・設問・2 段階 command）
    cli.py         build / list / show / session / brief / decide / status / reopen-check / validate-policy（batch なし）
    validation.py  Windows 実機 1 操作の real-data packet validation（::P395_*:: marker、全 candidate dry-run、fail closed）
    pilot.py       候補 #1 だけの人間 review pilot（::P395C_*:: marker、rank 1 を自力で特定、dry-run only）

APPROVE_RECOMMENDED ≠ APPROVED、REJECT_RECOMMENDED ≠ REJECTED、APPROVED ≠ DNA promotion（常に NOT_PROMOTED）。
"""
