# research/source_docs/compass/ — 羅針盤PDF置き場（PDF本体はgit非管理）

「グローバル投資の羅針盤」PDF（社外秘）を研究資料として置く場所。

**重要: このリポジトリはpublicのため、PDF本体は絶対にコミットしないこと。**
`research/source_docs/` は `.gitignore` で保護されている（このREADMEのみ例外的に追跡）。

- 命名規則: `2026-08-17.pdf` 形式（YYYY-MM-DD）を推奨。既存の `2026_0817_1.pdf` 形式でも可。
- Phase 0.5（8月号Out-of-Sample検証）は、ここに8月分10冊
  （08-17〜08-21, 08-24〜08-28）が配置されると再開できる。
- 安全な受け渡し経路（推奨順）:
  1. Privateリポジトリ経由（例: investment-intelligence-research を新設し、そこへpush →
     セッションでadd_repoして読む）
  2. ユーザーPC上のローカルClaude CodeセッションでUSBから直接コピー
- 既に `date/rashinban/` にコミット済みの6-7月分10冊の扱い（public露出の解消）は
  `docs/rebuild/RASHINBAN_INVENTORY.md` §3 の承認事項。
