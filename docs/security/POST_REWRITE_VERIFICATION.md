# POST_REWRITE_VERIFICATION — rewrite後検証手順と結果

Rebuild Stage 1.7（2026-08-29）。
状態: **DRY RUN検証は全PASS済み**（HISTORY_REMEDIATION_EXECUTION.md §4）。
**リモートrewrite未実行のため、本書の「実測結果」欄はpush後に記入する**（手順は確定済み）。

## 1. フレッシュクローン検証（rewrite後に必須）

```bash
git clone https://github.com/takehiro104toshi-cmd/daily-market-brief /tmp/verify-clone
cd /tmp/verify-clone
git fetch origin claude/investment-intelligence-phase0-rvdplu:feature

# (a) 全到達履歴にPDF objectが存在しないこと（期待: 0）
git rev-list --all --objects | grep -cE '\.pdf$'

# (b) 対象パスに触れるコミットが存在しないこと（期待: 出力なし）
git log --all --oneline -- 'date/rashinban/*.pdf' \
  cloudflare/private-insight-wrangler.toml cloudflare/.wrangler/cache/wrangler-account.json

# (c) 識別子objectが存在しないこと（期待: 0）
git rev-list --all --objects | grep -cE 'wrangler-account|private-insight-wrangler\.toml$'

# (d) tracked files検査（期待: PDFなし・研究dirはREADMEのみ）
git ls-files '*.pdf' | wc -l

# (e) コミット数が444（rewrite時点。以後のCIコミットで増加はOK・減少はNG）
git rev-list --all --count

# (f) 全テスト（期待: 492 passed以上）
pip install -r requirements.txt && python -m pytest -q
```

### 実測結果（push後に記入）

| 項目 | 期待値 | 実測 |
|---|---|---|
| (a) PDF objects | 0 | ⬜ 未実施 |
| (b) 対象パスのコミット | 0 | ⬜ |
| (c) 識別子objects | 0 | ⬜ |
| (d) tracked PDFs | 0 | ⬜ |
| (e) コミット数 | ≥444（減少なし） | ⬜ |
| (f) テスト | 492+ passed | ⬜ |

## 2. GitHub残存露出の確認（rewrite後・可能な範囲）

```bash
# 旧コミットSHA経由のraw URL（HEADリクエストでstatusのみ確認。期待: 404）
curl -s -o /dev/null -w "%{http_code}\n" \
  https://raw.githubusercontent.com/takehiro104toshi-cmd/daily-market-brief/128f4b94ハッシュ全体/date/rashinban/2026_0618_1.pdf
# 旧コミットページ（github.com/<repo>/commit/128f4b9…）へのアクセス可否
```

### rewriteだけでは保証できない領域（明記）

1. **GitHubサーバ上のdangling object**: force push後も旧オブジェクトはGitHub内部に
   一定期間残存し、**旧コミットSHAを知っている者はcommit URL・raw URL経由で
   アクセスできる場合がある**（GitHubのGCタイミング依存）。
2. **各種キャッシュ**（raw CDN・コードサーチ・Archive系サービス）。
3. **fork**: 実施直前に確認する（現時点でOpen PR 0・fork未確認）。
4. 完全な除去保証には **GitHub Supportへの機密データ削除依頼**
   （"Remove sensitive data" request・旧コミットSHAを添えて）が必要。
   → **依頼はユーザーが実施**（Claude Codeは代行しない）。依頼要否の判定:
   PDF＝社外秘であるため**依頼推奨**。

## 3. 検証後のフォローアップ

- [ ] 作業クローン・ユーザーローカルcloneのfresh clone化（EXECUTION.md §8）
- [ ] migration merge（rewritten feature → rewritten main）とCI Guard発効確認
      （次のcronスロットでworkflowの"Security guard"ステップがPASSすること）
- [ ] 監視: 翌営業日のCI 12 runが正常（レポート生成・Pages更新）であること
- [ ] `SECURITY_REMEDIATION_PLAN.md` §7 承認事項A-Cのクローズ記録
