# HISTORY_REMEDIATION_EXECUTION — 履歴除去の実行記録

Rebuild Stage 1.7（2026-08-29）。承認: A（filter-repo）/ B（main反映・安全順序）/ C（識別子同時除去）/ D（CI Guard）。

## 実行状況サマリー

| ステップ | 状態 | 結果 |
|---|---|---|
| 1. PRE-FLIGHT | **完了** | §1 |
| 2. 原本安全確認 | **完了** | §2 |
| 3. ローカルバックアップ | **完了** | §3 |
| 4-6. DRY RUN（ミラーでのrewrite試験＋検証＋テスト） | **完了・全PASS** | §4 |
| 7. EXECUTION GATE | **通過→ただしpush権限で停止** | §5 |
| 8. REMOTE REMEDIATION（force push） | **未実行（権限ブロック・承認/実行待ち）** | §5 |
| 9-10. 残存露出確認・フレッシュクローン検証 | 未実行（push後に実施。手順は POST_REWRITE_VERIFICATION.md） | — |
| 11. CI Security Guard | **組込み済み**（workflowへpytest guardステップ追加。main反映はmigration mergeで有効化） | §6 |

## 1. PRE-FLIGHT実測（2026-08-29 10:42 UTC）

- remote: `https://github.com/takehiro104toshi-cmd/daily-market-brief`（fetch/push同一）
- visibility: **public**（GitHub API実測）
- default branch: `main`
- remote branches: `main` = `1a4433d…`、`claude/investment-intelligence-phase0-rvdplu` = `00370ac…` の**2本のみ**
- tags: **0** / open PRs: **0** / worktrees: 作業ディレクトリの1つのみ / working tree: clean
- branch protection: **両ブランチともprotected=false**（force pushを妨げる保護なし）
- push権限: リポジトリ権限としては`can_push=true`。ただし本リモート実行環境の
  権限クラシファイアが**force pushコマンドをブロック**（§5）
- Pages/Actions依存: Pagesは各run生成のartifactから配信＝履歴rewriteの影響なし。
  CI cron静穏窓（次スロット22:30 UTCまで約12時間）で作業
- タイミングレース対策: push直前のls-remote照合（基準SHA一致必須）をスクリプト化

## 2. 原本安全確認

- 履歴blob（`128f4b9`収載）と `research/source_docs/compass/`（.gitignore保護）と
  `date/rashinban/`（untracked・ディスク上）の**3系統でMD5全10冊一致**を確認
- Cloudflare識別子2ファイル: ディスク上に保持（untracked）。tracked `.example` は残置され、
  Legacy runtime（config.yaml＋env参照）に必要な設定値は破壊されない
- EXTERNAL_USB: **本リモート環境からは不可視**（マウントなし。Stage 1.5と同様）。
  ユーザー申告のUSB原本は本環境からは検証不能——ただし本コンテナ内3系統＋
  バックアップ（§3）で「唯一のコピー」状態ではないことを確認済み。
  **注意: 本コンテナは一時的。セッション終了前にUSB原本の実在確認を推奨**

## 3. ローカルバックアップ（publicへはpushしない）

| 種別 | 場所（コンテナ内・local-only） | 内容 |
|---|---|---|
| mirror | `/home/user/backup-stage17/daily-market-brief-pre-rewrite.git` | rewrite前の全refs（main=1a4433d, feature=00370ac）・全オブジェクト |
| bundle | `/home/user/backup-stage17/daily-market-brief-pre-rewrite.bundle`（20.9MB） | 同上の単一ファイル版 |
| 検証 | バックアップからPDF blob取得→MD5一致確認済み | — |

## 4. DRY RUN結果（`/home/user/backup-stage17/rewrite-work.git`）

対象パス（**正確に12・basename一括削除はしない**）:
`date/rashinban/2026_{0618,0619,0622,0623,0624,0625,0626,0629,0630,0701}_1.pdf`（10）＋
`cloudflare/private-insight-wrangler.toml`＋`cloudflare/.wrangler/cache/wrangler-account.json`（2）。
事前にリネーム履歴なし・他パス存在なしを`--follow`/`rev-list --objects`で確認済み。

| 検証項目 | 結果 |
|---|---|
| コミット数 | 444 → **444**（消失なし） |
| PDF objects | 10 → **0** |
| 識別子file objects | → **0** |
| 対象パスに触れるコミット | **0** |
| 無関係資産（README・.example等） | 保持 |
| featureブランチHEADツリー | 旧と**バイト同一**（tree hash一致） |
| 旧main→新mainのツリー差分 | **削除対象12ファイルのD行のみ** |
| rewrite後チェックアウトでの全テスト | **492 passed** |
| rewrite後SHA | main=`4555117…` / feature=`5e7d747…`（※実push時はフレッシュミラーで再生成されるため最終SHAは変わる） |

## 5. EXECUTION GATE — force pushのブロックと対応（STOP地点）

レース検査つきforce pushを実行したところ、**本実行環境の権限クラシファイアにより
コマンドが拒否**された（認証・権限の迂回は行わない方針に従い中断）。
リポジトリ側の障害ではない（保護なし・can_push=true）。

**再開手段（いずれか）**:
1. ユーザーが本セッション（または新しいセッション）でforce pushを許可
   （permission ruleの追加 or 実行時承認）→ Claude Codeが
   `docs/security/history_rewrite.sh` を実行（フレッシュミラー取得から検証・pushまで自動）
2. ユーザー自身がローカルで実行:
   `bash docs/security/history_rewrite.sh`
   （要: git-filter-repo `pip install git-filter-repo`・push権限。スクリプトは
   検証失敗時に必ずpush前で停止する）

実行後は `POST_REWRITE_VERIFICATION.md` の手順でフレッシュクローン検証を行う
（手段1ならClaude Codeが引き続き自動実施）。

## 6. CI Security Guard（承認D・組込み済み）

`.github/workflows/daily-market-brief.yml` の依存インストール直後に
`python -m pytest tests/intelligence/test_confidential_guard.py -q` を追加。
機密ファイルがtrackingされた場合、**レポート生成前に**workflowが失敗する。
本変更はfeatureブランチ上にあり、**migration merge（rewrite後のmain反映）で発効**する
（安全順序: 旧mainには`tests/intelligence/`が無いため、rewrite→merge→発効の順を厳守）。

## 7. ブランチ戦略（rewrite後・§12）

1. force push完了後、全開発は**rewritten history**のみを正とする
2. 作業クローンは `git fetch` → 両ブランチを `git reset --hard origin/<branch>` で追従
   （untracked/ignoredのPDF・識別子ファイルはresetの影響を受けない）
3. rewritten feature を rewritten main へ**通常merge**（両refは同一filter-repo実行で
   書き換えられており共通祖先が保たれるため、通常mergeで安全）→ push（non-force）
4. これによりmainへ: .gitignore保護・Guardテスト・CI Guard・vNext基盤・docsが反映
5. **旧SHA系統とのmerge・rebase・pushは全面禁止**（旧履歴の再混入防止）

## 8. コラボレータ影響（§13）

- 旧clone: `git pull`せず**破棄→fresh clone**が原則。旧cloneからのpushは旧履歴を
  再混入させるため禁止（万一pushされた場合はGuard＋SHA監視で検知し再rewrite）
- 旧cloneでどうしても継続する場合: `git fetch origin && git reset --hard origin/main`
  ＋ローカルブランチ全張り替え（非推奨）
- worktree: 旧cloneに紐づくものは作り直し
- open PR: 0件のため影響なし
- 旧コミットSHAへのリンク（過去の報告書・チャット内）: rewrite後は無効。
  本プロジェクトの報告書中のSHA（bb9172f/a434fc7/1fc1176/b4f5959/00370ac等）は
  **歴史的記録**として読み替える
- CIランナー: 各run独立checkoutのため特別対応不要（rewrite直後の1回が旧checkoutと
  すれ違った場合もpull --rebaseで新履歴に乗る設計を確認済み）

## 9. 組織ガバナンス注記（§14）

技術的remediationとは別に、「社外秘資料がpublicリポジトリ上で取得可能な状態が
2026-07-07〜現在まで存在した」事実について、**資料提供元（岡三証券）またはユーザーの
所属組織の情報セキュリティ・コンプライアンス手続き上の報告要否はユーザー側で
確認が必要**。Claude Codeは組織への報告を代行しない。
