# CONFIDENTIAL_RESEARCH_POLICY — 社外秘研究資料の取り扱い

Rebuild Stage 1.6 制定（2026-08-29）。対象: 「グローバル投資の羅針盤」PDFをはじめとする
CONFIDENTIAL_SOURCE分類の研究資料（分類定義は `DATA_CLASSIFICATION_POLICY.md`）。

## 1. 正式ルール（監督者承認済み）

羅針盤PDFは資料上「社外秘・岡三証券社内限・お客様への配布厳禁」であるため:

1. **PUBLIC REPOSITORYへの配置禁止**（Git tracking禁止）
2. **GitHub Pages / public artifact / release への混入禁止**
3. **外部サービスへのアップロード禁止**
4. **LLM API等への本文送信は明示承認なしでは禁止**（Phase 0/0.5の解析はユーザー指示による承認済み利用）
5. 利用は private/local research area（`research/source_docs/compass/`）からのみ
6. Git管理してよいのは**抽象化された派生物のみ**（Compass DNA仕様・一般化ルール・
   non-verbatim統計。詳細は DATA_CLASSIFICATION_POLICY §3）

## 2. 配置場所

| 場所 | 用途 | 保護 |
|---|---|---|
| `research/source_docs/compass/` | 本プロジェクトでの正式な参照位置（ローカル） | `.gitignore`でREADME以外tracking不能。Guardテストで機械検査 |
| ユーザーのUSB/ローカル保管 | 原本 | ユーザー管理 |
| （将来・要承認）Privateリポジトリ `investment-intelligence-research` 等 | セッション間の受け渡し・バックアップ | Private可視性が前提 |
| `date/rashinban/`（Legacy） | **廃止**（歴史的経緯でPDFが置かれていた場所） | Stage 1.6でtracking解除・以後PDF配置禁止（.gitignore） |

## 3. 8月羅針盤PDF（Phase 0.5入力）の受け入れ手順

1. publicリポジトリへは**commitしない**（pushもしない）。
2. 受け渡しは（a）Privateリポジトリ経由 →セッションでREAD ONLY取得、または
   （b）ユーザーPC上のローカルClaude CodeセッションでUSBから
   `research/source_docs/compass/` へコピー、のいずれか。
3. 解析（Phase 0.5）はユーザーの実行指示をもって本文のLLM処理承認とみなす。
4. Git管理してよい成果物: 検証結果（SUPPORTED/CONTRADICTED）・scope付与・
   一般化ルール・統計のみ。原文引用・ページ画像は不可。

## 4. 実装面の執行

- `.gitignore`: `research/source_docs/*`（README除く）・`date/rashinban/*.pdf`
- Guardテスト（`tests/intelligence/test_confidential_guard.py`）:
  tracked PDFゼロ検査 / research配下README限定検査 / check-ignore実地検査 /
  vNextコードの機密パス参照禁止検査 — **現在strict（Legacy例外なし）で全通過**
  （Stage 1.6でtracking解除を同時実施したため例外規定が不要になった）。
- CI組込み（pytestステップ追加）はLegacy workflow変更を伴うためStage 2の承認事項。
- vNextのreports/配信系はEvidence参照で組み立てるため、CONFIDENTIAL_SOURCE本文が
  public出力へ流れる経路を構造的に持たない（TARGET_ARCHITECTURE §4のデータ所有権）。

## 5. 既知の残存課題

- **Git履歴には10冊のPDFが残存**（コミット`128f4b9`）。除去は履歴書き換えが必要で、
  実施可否・手順は `SECURITY_REMEDIATION_PLAN.md` §3（ユーザー承認待ち）。
- 履歴書き換え完了までは、public履歴からPDFを取得可能な状態が続く。
  リポジトリのPrivate化は即効性のある代替策として選択肢に含む（同計画§4）。
