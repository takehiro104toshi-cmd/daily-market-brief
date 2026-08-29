# SECURITY_REMEDIATION_PLAN — 是正計画（実施済み／承認待ち）

Rebuild Stage 1.6 成果物（2026-08-29）。
本Stageでは**履歴書き換え・force push・rotation・大量削除は実施していない**。

## 1. 実施済み（Safe Current-Tree Protection）

| # | 措置 | 状態 |
|---|---|---|
| 1 | 羅針盤PDF 10冊の存在確認とローカル研究領域への複製（`research/source_docs/compass/`、MD5一致検証済み・.gitignore保護下） | 完了 |
| 2 | `date/rashinban/*.pdf` のGit tracking解除（`git rm --cached`。**ディスク上のファイルと履歴内blobは無傷**） | 完了（本ブランチ） |
| 3 | Cloudflare識別子2ファイル（wrangler.toml実id・.wrangler/cache）のtracking解除＋.gitignore | 完了（本ブランチ） |
| 4 | .gitignoreの保護規則（date/rashinban/*.pdf・research/source_docs・cloudflare識別子・data/vnext） | 完了 |
| 5 | Guardテスト5件（tracked PDFゼロ・research配下README限定・check-ignore実地・識別子ファイル非tracking・vNext機密パス参照禁止）— **strict・例外なしで全通過** | 完了 |
| 6 | ポリシー制定（DATA_CLASSIFICATION / CONFIDENTIAL_RESEARCH） | 完了 |
| 7 | date/rashinban/README.mdへの通知（pull時の作業ツリー挙動と復元コマンド明記） | 完了 |

**mainへの反映時の注意（要ユーザー確認）**: 本ブランチをmainへマージすると、
ユーザーのローカルクローンでも`date/rashinban/*.pdf`が作業ツリーから消えます（履歴からは
`git show 128f4b9 -- <path>`で復元可能）。**マージ前にUSB等の原本保有を確認してください。**

## 2. Legacy Current Exception

なし。Guardはstrict運用（tracking解除を同時実施したため例外規定が不要になった）。
ただしLegacy CI（daily-market-brief.yml）はpytest自体を実行しないため、Guardの自動執行は
現状ローカル/開発ブランチのみ。**CIへのpytestステップ追加をStage 2承認事項として提案**する。

## 3. 履歴除去計画（HISTORY REMOVAL PLAN — 承認待ち・今回実行しない）

対象: コミット`128f4b9`のPDF 10 blob（約14.6MB）＋（任意で）Cloudflare識別子2ファイルの履歴。

**推奨手順（git filter-repo方式）**:
```
0) 事前: 全開発を一時停止し、CI cron（1日12回）を一時disable（Actionsの手動無効化）
1) ミラーバックアップ: git clone --mirror → ローカル/private保管（復旧保険）
2) git filter-repo --invert-paths --path date/rashinban --path-glob 'date/rashinban/*.pdf' \
     （必要なら --path cloudflare/private-insight-wrangler.toml --path cloudflare/.wrangler も）
3) 全ブランチをforce push（main＋claude/investment-intelligence-phase0-rvdplu）
4) GitHub側の残存への対応: 履歴書き換え後もGitHubのキャッシュ・古いコミットSHA直リンク・
   forkには旧blobが残り得る。GitHub Supportへのキャッシュパージ依頼が完全除去には必要
   （公式手順）。fork有無は実施直前に確認する（forkが存在する場合は各fork側にも旧blobが残る）
5) 検証: 新cloneで `git log --all --diff-filter=A -- '*.pdf'` が空、
   `git rev-list --all --objects | grep pdf` が空、Guardテスト通過
6) CI再有効化。全コラボレータ（実質ユーザーのみ）はローカルcloneを作り直す
   （旧cloneからのpushは履歴を復活させるため禁止）
```

**影響範囲**: 全437コミットのSHAが変わる／PR・コミットへの既存リンクは無効化／
Claude-Sessionリンク等コミットメッセージは保持されるがSHA参照はずれる／
ローカルclone全滅（作り直し必須）／Pages・output運用への影響はなし（内容不変）。

**代替案（即効性重視）**: リポジトリを**Privateへ変更**する。
- 利点: 即時に公開露出が止まる。履歴書き換え不要。作業影響ゼロ
- 欠点: GitHub Pages（現行レポート配信）はFree planではPublicリポジトリ前提のため
  **配信方式の変更が必要**（Pages有料化 or 配信専用の別public repo分離 or Cloudflare配信）
- 推奨: **短期はPrivate化 or filter-repoのどちらかをユーザーが選択**。
  Pages配信を維持したい場合はfilter-repo案、配信方式を再設計してよいならPrivate化が最小工数

## 4. ROTATION判定

`GIT_HISTORY_EXPOSURE_AUDIT.md` §4 のとおり **ROTATION_REQUIRED: なし**
（実credentialの露出ゼロ。識別子はSecretに該当せず）。rotationは実施しない。

## 5. Legacy output/（214MB）cleanup移行計画（今回削除しない）

1. 方針は制定済み: vNextはruntime生成物をGit保存しない（DATA_CLASSIFICATION §5）。
2. Legacy分の段階的cleanup（すべて要承認・Stage 5想定）:
   a) CIのコミット対象を「latest＋直近N日」へ変更（以後の増加を止める）
   b) 過去分はPages artifact/ローカルアーカイブへ退避後、ツリーから削除
   c) 履歴上の容量回収はPDF履歴除去（§3）と同時にfilter-repoで行うと1回で済む
3. 今回はplanのみ。削除・履歴操作は未実施。

## 6. tank（旧Reference System）

- READ ONLY維持。CLI 1行修正（T1）は**今回実施しない**（監督指示: 再稼働は目的でない）。
- T7（Secret-in-URL潜在経路）は実流出なしを確認済み。恒久対応はvNext移植時の
  設計要件（ヘッダ認証・redaction）として `VNEXT_RECONCILIATION.md` §3-3 に反映済み。

## 7. 承認事項の状態（Stage 1.7更新）

| # | 事項 | 決定（2026-08-29） | 実施状態 |
|---|---|---|---|
| A | PDF履歴の除去方式 | **APPROVED: filter-repo方式** | DRY RUN全PASS。**force pushのみ実行環境の権限ブロックで保留**（HISTORY_REMEDIATION_EXECUTION.md §5） |
| B | mainへの反映 | **APPROVED IN PRINCIPLE**（migration手順の一部として） | 手順確定（rewrite→reset→merge→push。同 §7） |
| C | Cloudflare識別子の履歴除去 | **APPROVED: Aと同一rewriteに含める** | 対象12パスに含めDRY RUN済み |
| D | Legacy CIへのGuard組込み | **APPROVED** | workflowへ組込み済み（migration mergeで発効） |
| E | output/ cleanup | **今回対象外**（別Stage: LEGACY_REPOSITORY_HYGIENE 候補として記録） | 未着手・変更なし |
