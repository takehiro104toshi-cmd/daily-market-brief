#!/usr/bin/env bash
# Stage 1.7 履歴除去の実行スクリプト（承認A/C。DRY RUN検証済み手順の自動化）
# 前提: git-filter-repo導入済み・push権限（force push許可）がある環境で実行。
# 安全機構: フレッシュミラー取得→書き換え→検証→レース検査→force push→リモート検証。
# どの検証に失敗してもpushせず終了する。冪等（何度でも安全に再実行可能）。
set -euo pipefail

REPO_URL="https://github.com/takehiro104toshi-cmd/daily-market-brief"
WORK="$(mktemp -d)/rewrite.git"
BRANCHES=(main claude/investment-intelligence-phase0-rvdplu)

echo "[1/7] fresh mirror clone -> $WORK"
git clone --mirror -q "$REPO_URL" "$WORK"
cd "$WORK"

declare -A BASE
for b in "${BRANCHES[@]}"; do
  BASE[$b]=$(git rev-parse "refs/heads/$b")
  echo "  base $b = ${BASE[$b]}"
done

echo "[2/7] pre-stats"
PRE_COMMITS=$(git rev-list --all --count)
echo "  commits=$PRE_COMMITS pdf_objects=$(git rev-list --all --objects | grep -cE '\.pdf$' || true)"

echo "[3/7] filter-repo (exact 12 confidential paths only)"
git filter-repo --force \
  --path date/rashinban/2026_0618_1.pdf --path date/rashinban/2026_0619_1.pdf \
  --path date/rashinban/2026_0622_1.pdf --path date/rashinban/2026_0623_1.pdf \
  --path date/rashinban/2026_0624_1.pdf --path date/rashinban/2026_0625_1.pdf \
  --path date/rashinban/2026_0626_1.pdf --path date/rashinban/2026_0629_1.pdf \
  --path date/rashinban/2026_0630_1.pdf --path date/rashinban/2026_0701_1.pdf \
  --path cloudflare/private-insight-wrangler.toml \
  --path cloudflare/.wrangler/cache/wrangler-account.json \
  --invert-paths

echo "[4/7] post-rewrite verification"
POST_COMMITS=$(git rev-list --all --count)
PDFS=$(git rev-list --all --objects | grep -cE '\.pdf$' || true)
IDENT=$(git rev-list --all --objects | grep -cE 'wrangler-account|private-insight-wrangler\.toml$' || true)
echo "  commits=$POST_COMMITS pdf_objects=$PDFS identifier_objects=$IDENT"
[ "$PDFS" -eq 0 ] || { echo "ABORT: pdf objects remain"; exit 1; }
[ "$IDENT" -eq 0 ] || { echo "ABORT: identifier objects remain"; exit 1; }
[ "$POST_COMMITS" -eq "$PRE_COMMITS" ] || { echo "ABORT: commit count changed ($PRE_COMMITS -> $POST_COMMITS)"; exit 1; }
for b in "${BRANCHES[@]}"; do git rev-parse -q --verify "refs/heads/$b" >/dev/null || { echo "ABORT: branch $b lost"; exit 1; }; done

echo "[5/7] race check (remote must still be at base SHAs)"
for b in "${BRANCHES[@]}"; do
  NOW=$(git ls-remote "$REPO_URL" "refs/heads/$b" | cut -f1)
  [ "$NOW" = "${BASE[$b]}" ] || { echo "ABORT: remote $b moved (${BASE[$b]} -> $NOW). Re-run the script."; exit 3; }
done

echo "[6/7] force push rewritten branches"
git push --force "$REPO_URL" \
  "refs/heads/main:refs/heads/main" \
  "refs/heads/claude/investment-intelligence-phase0-rvdplu:refs/heads/claude/investment-intelligence-phase0-rvdplu"

echo "[7/7] remote verification"
for b in "${BRANCHES[@]}"; do
  NEW_LOCAL=$(git rev-parse "refs/heads/$b")
  NEW_REMOTE=$(git ls-remote "$REPO_URL" "refs/heads/$b" | cut -f1)
  echo "  $b local=$NEW_LOCAL remote=$NEW_REMOTE"
  [ "$NEW_LOCAL" = "$NEW_REMOTE" ] || { echo "WARN: remote mismatch on $b"; exit 4; }
done
echo "DONE. Next: fresh clone verification (docs/security/POST_REWRITE_VERIFICATION.md)"
