"""Automatic Compass Corpus Analyzer（Phase 3.8）。

    CorpusSnapshot（3.7）→ DocumentAnalyzer → AnalyticalStructure → MarketAlignment
    → CrossDocumentComparator → PatternEvidence → PatternCandidate → Coverage / Benchmark
    → CompassCorpusResearchSnapshot

研究対象は「どんな市場状態で、どの Evidence を選び、何を Main Theme とし、どう解釈し、WHY をどう組み立て、
どの Outlook へつなげ、どの Risk を提示したか」という分析構造。

境界（3.7 を維持）:
- Compass source statement ≠ Market Fact。printed number ≠ Fact Store truth。interpretation ≠ market principle。
  forecast ≠ realized outcome。
- 客観 market state は J-Quants / Market Bank / Fact / Context / Internals を優先（3.6 J-Quants First）。
  本文から客観市場状態を捏造しない。
- production Compass DNA（market_principles.py / market_rules.yaml）は変更しない。Pattern Registry は研究 evidence。
- pattern status は STRONG_PATTERN_CANDIDATE まで。APPROVED は Phase 3.9 の監督者 process のみ。
- 決定的・versioned・append-only・idempotent。外部 LLM / embedding を使わない（OPTIONAL_FUTURE_ENHANCEMENT）。
- offline。PDF / 本文 / full path を research artifact・log に出さない（observation_id で provenance を辿る）。

1機能=1ファイル:
    config.py            analyzer versions / thresholds（config.yaml compass_research）
    categories.py        editorial selection の controlled vocabulary
    statements.py        3.7 observation → 文単位 Statement index（順序・block・level）
    salience.py          versioned salience（見出し / 配置 / 初出 / 反復 / 専用段落 / outlook・why 連結）
    links.py             analytical link（EVIDENCE→INTERPRETATION→OUTLOOK / →RISK / EVENT→WATCH）
    why_model.py         EXPLICIT_WHY / IMPLICIT_ASSOCIATION / NO_WHY / UNKNOWN
    outlook_model.py     direction / horizon / confidence / target / conditions / caveat
    risk_model.py        explicit risk / counterargument / invalidation / uncertainty / watch item
    regime.py            market regime alignment（Context / calendar / Market Bank connector、known_at）
    structure.py         AnalyticalStructure（document 単位の分析構造）
    comparator.py        cross-document comparison と explainable similarity
    patterns.py          pattern identity / components / assignments（partial pattern types）
    lifecycle.py         pattern status と support / regime diversity thresholds（versioned）
    store.py             research store（canonical JSONL、rebuild 可、idempotent）
    dna_comparison.py    既存 Compass DNA rule との比較・conflict 記録
    benchmark.py         Corpus Benchmark（analytical reconstruction。予測精度ではない）
    review_queue.py      Supervisor Review Queue（auto approval なし）
    acquisition.py       coverage-guided acquisition recommendations
    research_snapshot.py CompassCorpusResearchSnapshot
    engine.py            incremental / full rebuild / equivalence orchestration
    intake_hook.py       Phase 3.75 との event/service boundary（研究失敗を Corpus から隔離）
    batch_import.py      historical Compass の private batch 追加
    pilot.py             実 10 document pilot ＋ N+1 fixture mechanics（::P38_*::）
"""
