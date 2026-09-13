"""End-to-Endパイプライン編成（Phase 2-A）。

Phase 1の全層を実データで一本通す:

    SourceRegistry → SourceEndpoint → HttpTransport → FetchAttempt → RawItem
    → RawStore → Feed Parser → Normalizer → SourceDocument
    → EvidenceAssessment → GateDecision

途中をmockしない（テストはtransport注入のみ・他層は実物）。

NO FALSE EVIDENCE原則:
    fetch失敗 / parser失敗 / normalization REJECT から
    EvidenceAssessment ACCEPT が生成されることは**絶対にない**
    （integration testで機械的に固定）。
"""
