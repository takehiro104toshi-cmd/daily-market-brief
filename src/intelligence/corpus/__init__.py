"""Compass Corpus foundation（Phase 3.7）。

「グローバル投資の羅針盤」PDF を **historical analytical corpus** として蓄積する層。

境界（Phase 3.7 §1）:
- Corpus は training truth / market truth / Fact Store ではない。
  「その時点で人間の市場分析者が何を観測し、何を重視し、どう解釈し、どう見通したか」を研究する資料。
- Market Fact の truth source は J-Quants / approved market sources 側。
  羅針盤に書かれているから市場 Fact として真、とは扱わない（`alignment.py` は比較結果を保持するだけ）。
- 原本 PDF は immutable source（`source.py`）。analysis pipeline は原本を書き換えない。
- offline-first。本文を外部 LLM へ自動送信しない。credential を要求しない。
- Corpus から production Compass rule を自動変更しない（`versioning.py` は append-only）。

原本の置き場所は config.yaml `compass_corpus.source_dir`（承認済み local research area、Git 非管理）。
本パッケージのコードは機密パスを直接参照しない（confidential guard）。

1機能=1ファイル:
    config.py            設定（config.yaml compass_corpus）
    status.py            document status と遷移
    identity.py          deterministic document identity（hash 中心）
    source.py            immutable source record / 原本コピー・検証
    family.py            document family detection（filename 非依存）
    temporal.py          document_date / publication_date / received_at / referenced session
    validation.py        Corpus 投入前検証（fail-closed）
    extraction.py        text layer 抽出 artifact（OCR は default で行わない）
    page_sections.py     ページの section 判定
    header_values.py     P1 ヘッダー表 / P2 指数表の EXTRACTED_VALUE
    structured_record.py structured Compass record（observation level 分離）
    quality.py           document quality
    alignment.py         market data alignment foundation（Fact Store を書き換えない）
    coverage.py          coverage labels / coverage report（threshold version 化）
    milestones.py        CORPUS_10 / 30 / 50 / 100 / 200
    versioning.py        version / reanalysis / supersession
    store.py             canonical JSONL + SQLite index（rebuild 可・idempotent）
    inventory.py         既存 historical Compass の棚卸し（捏造しない）
    snapshot.py          CorpusSnapshot（Phase 3.8 への read model）
    intake.py            Mobile Intake adapter boundary（cloud 非依存）
    inbox.py             local inbox contract（Phase 3.75 用）
    pipeline.py          ingest orchestration
    pilot.py             実 corpus pilot（::P37_*::）
"""
