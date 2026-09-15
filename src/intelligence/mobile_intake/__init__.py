"""Mobile / One-Tap Compass Intake（Phase 3.75）。

    iPhone → native Share Sheet「羅針盤に追加」→ private synced Inbox folder
    → Windows local filesystem → bounded Inbox processor → CompassIntakeService → Corpus

Phase 3.7 の境界（IntakeRequest → CompassIntakeService.submit() → Corpus）を保持する。
本パッケージは **incoming file を intake boundary へ届けるだけ**。Corpus core は cloud SDK に依存しない
（本パッケージも SDK を使わない: 同期フォルダ＝ローカル filesystem のみ）。

- 原本 PDF は Git 非管理の private Inbox（機械ローカル設定）に置く。repository には commit しない。
- offline。外部 LLM・public endpoint・telemetry なし。credential を扱わない。
- log / status は full path を出さない（basename / hash / 論理 locator）。

1機能=1ファイル:
    config.py        repository 設定（config.yaml mobile_intake）
    local_config.py  機械ローカル設定（env / ~/.compass_intake）と path privacy
    adapters.py      provider 評価と SyncFolderAdapter（iCloud Drive / OneDrive / Google Drive / local）
    result.py        処理結果・reason code・ユーザー向けヒント
    processor.py     bounded inbox processor（discover → stability → lock → intake → ledger → status）
    status.py        human-readable / machine-readable status と milestone feedback
    scheduler.py     Windows Task Scheduler（bounded scheduled invocation）と single-instance guard
    shortcut.py      iOS Shortcut「羅針盤に追加」の作成手順と MOBILE_ACTION_COUNT
    setup.py         readiness check（MOBILE_INTAKE_READY / PARTIAL / NOT_READY）と init
    pilot.py         end-to-end local pilot（::P375_*::）
"""
