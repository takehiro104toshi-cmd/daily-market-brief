# RASHINBAN_INVENTORY — 羅針盤PDFの実ファイル棚卸し

Rebuild Stage 1.5 成果物（2026-08-29）。**Gitツリーでなくファイルシステムを直接走査**した結果。

## 1. 走査範囲

- `/home/user/daily-market-brief/`（本リポジトリの作業コピー全体。`find`によるPDF全数検索）
- `/home/user/takehiro104toshi-cmd/article-intelligence-data-tank/`（READ ONLYクローン。PDFなし）
- ファイルシステム全域のPDF検索（`/proc` `/sys` `.git`除く）およびEXTERNAL_USB探索
  （`/` 直下・`/mnt`（attach=空・user-data/working=空・skills=Claude環境用）・`/media`=空・
  `/home/{user,ubuntu,claude}`・`/old_root`・`/srv`・`/opt`・`/tmp`）
- **本セッションはリモート実行環境（クラウドコンテナ）であり、ユーザーPCに接続された
  EXTERNAL_USBはマウントされていない**。USB上の実ファイルはこの環境から観測不能。

## 2. 発見結果（`date/rashinban/`・ファイルシステム実測）

| 月 | 冊数 | ファイル | git状態 |
|---|---|---|---|
| 2026/06 | **9冊** | 2026_0618_1 / 0619 / 0622 / 0623 / 0624 / 0625 / 0626 / 0629 / 0630（各.pdf） | 全て**tracked**（コミット済み） |
| 2026/07 | **1冊** | 2026_0701_1.pdf | tracked |
| 2026/08 | **0冊** | — | — |

- untracked / ignored / local-only のPDFは**存在しない**（`git status --ignored --porcelain`で確認。
  ignoredは`__pycache__`等のみ）。リポジトリ外にもPDFなし。
- 注意: この作業コピーはGitHubからのfreshクローンであり、**ユーザーのローカルPC/USBにのみ
  存在するファイル（コミットされていない8月分PDF等）はここには現れない**。
  「Gitに無い＝ユーザー環境に無い」ではない。

### 8月分（Phase 0.5対象）の判定

| 対象日 | 2026-08-17〜08-21, 08-24〜08-28（10冊） |
|---|---|
| FOUND | **NO**（本環境のファイルシステム・Git履歴のいずれにも存在しない） |
| ACCESSIBLE | NO |
| SAFE_TO_USE | 判定不能（未入手） |

→ **PHASE05_BLOCKED_MISSING_AUGUST_PDFS は継続**。

## 3. 機密性に関する重要所見（要ユーザー判断）

- `daily-market-brief` リポジトリは **public** であることを確認した（GitHub API実測）。
- 羅針盤PDF（社外秘・岡三証券社内限）10冊は、既にこのpublicリポジトリの
  `date/rashinban/` に**コミット済み＝現在すでに公開状態**にある。
- 本Stage 1.5では指示（公開repoへPDFをcommitしない）に従い、**新規のPDFコピーの
  コミットは行わない**。`research/` への複製も、publicリポジトリ内では保護にならないため
  実施しない（.gitignore整備のみ実施。§4）。
- **推奨対応（承認後に実施）**:
  1. 羅針盤PDFの保管先をPrivateな場所へ移す（例: 新規Privateリポジトリ
     `investment-intelligence-research`、またはリポジトリ自体のPrivate化）。
  2. public履歴からの除去（`git filter-repo`等の履歴書き換え）は影響が大きいため、
     実施可否・時期はユーザー・監督者の明示承認を得て別途計画する。
  3. 8月分PDFは**publicリポジトリへはpushしない**。受け渡しは（a）Privateリポジトリ経由、
     （b）ユーザーPC上でのローカルClaude Codeセッション（USB直接読取）のいずれかを推奨。

## 4. 今回実施した保護措置

- `.gitignore` に `research/source_docs/` を追加し、将来この場所に置かれる研究用PDFが
  誤ってpublicリポジトリへコミットされない構造にした（Legacyの既存パスには影響なし）。
- `research/source_docs/compass/README.md`（PDF本体を含まない説明ファイルのみ）を配置し、
  8月分PDFの正しい置き場所と受け渡し手順を明記した。

## 5. Phase 0.5 再開条件

1. 8月分10冊が上記いずれかの安全な経路で本環境から読める状態になること。
2. 監督者の再開承認。
3. 解析自体の手順はPhase 0.5指示のとおり（既存Compass DNAルールのOut-of-Sample検証＋
   scope付与）。knowledge/compass_dna/market_rules.yaml が更新先。
