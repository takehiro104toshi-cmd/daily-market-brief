# MOBILE_COMPASS_INTAKE_SETUP — iPhone から 2 タップで羅針盤を Corpus に追加する

Phase 3.75。実装は `src/intelligence/mobile_intake/`、設定は `config.yaml: mobile_intake`、
テストは `tests/intelligence/test_mobile_intake.py`。Phase 3.7 の境界
（`IntakeRequest → CompassIntakeService.submit() → Corpus`）はそのまま。

## 0. 完成形（ユーザー操作）

```
iPhone で羅針盤 PDF を開く → 共有 → 「羅針盤に追加」 → 通知「追加しました」 → 終わり
```

PC 側の操作はゼロ（Discord を開く・ダウンロード・Explorer・rename・移動・project copy をすべて廃止）。
**MOBILE_ACTION_COUNT = 2**（共有、「羅針盤に追加」）。確認ダイアログを足す構成にすると 3。

## 1. 選定した経路と理由（adapter evaluation）

| 候補 | iPhone 共有シート | Windows 同期 | 新アカウント | 判定 |
|---|---|---|---|---|
| **iCloud Drive** | ショートカットの「ファイルを保存」が **確認なし** で iCloud Drive/Shortcuts 配下へ保存できる唯一の経路（2 タップ） | iCloud for Windows（Microsoft Store・無料・既存 Apple ID）→ `%USERPROFILE%\iCloudDrive` | 不要 | **選定** |
| OneDrive | OneDrive app の共有拡張は毎回フォルダ選択（4 タップ） | Windows 標準（Files On-Demand の placeholder に注意） | 不要 | fallback |
| Google Drive | 「ドライブに保存」は毎回フォルダ・アカウント選択（4 タップ） | Drive for Desktop（別途） | 不要 | fallback |
| ローカルフォルダ | iPhone からの経路なし | 不要 | 不要 | 手動 fallback（drop するだけ） |

却下: 専用アプリ / 自前サーバ / public upload endpoint / OAuth backend / Discord bot（credential・公開面・保守が増える）。
processor は「ローカルフォルダを見る」だけなので、OneDrive / Google Drive のフォルダでも同じ手順で動く。

この開発環境（Linux コンテナ）には iCloud が無いため、実 iPhone → iCloud → Windows の接続は
**ADAPTER_SETUP_REQUIRED**（未検証）。同期フォルダを模した end-to-end pilot は PASS（§8）。

## 2. iPhone 側（1 回だけ・2〜3 分）

1. 「ショートカット」app → 「＋」 → 名前を **羅針盤に追加** に変更
2. 「ⓘ」→ **共有シートに表示** をオン → 種類は **PDF** と **ファイル** だけ残す
3. アクションを 4 つ追加
   1. **ショートカットの入力を受け取る**（PDF / ファイル）
   2. **if** 入力のファイル拡張子 が `pdf` でない → 通知「PDF ではありません」→ 停止
   3. **ファイルを保存** — サービス: iCloud Drive、保存先パス: `CompassInbox/`、
      **保存場所を尋ねる: オフ**、**既存のファイルを上書き: オフ**
   4. **通知を表示**「羅針盤に追加しました（PC で自動処理されます）」
4. 完了

保存先は自動的に `iCloud Drive/Shortcuts/CompassInbox/` になる（初回保存時にフォルダ自動作成）。
ファイル名は元のまま（手入力なし）。同名なら iOS が ` 2` を付ける（上書きしない）。
同じ手順は `python -m src.intelligence.mobile_intake.setup shortcut` でも表示できる。
署名済み `.shortcut` はこの環境から生成・インストールできないため、**インストール済みとは主張しない**。

## 3. Windows 側（1 回だけ）

1. **iCloud for Windows** を Microsoft Store から入れ、既存の Apple ID でサインイン → 「iCloud Drive」をオン
   （新規アカウント・有料プラン・設定変更は不要）。`%USERPROFILE%\iCloudDrive\Shortcuts\CompassInbox` が現れる。
2. リポジトリ直下で機械ローカル設定を作る（**repository には何も commit されない**）:

   ```
   python -m src.intelligence.mobile_intake.setup init --inbox "%USERPROFILE%\iCloudDrive\Shortcuts\CompassInbox" --data-root "<Corpus を置く private フォルダ>"
   ```

   生成物（すべて `%USERPROFILE%\.compass_intake\`）: `local_config.json`（Inbox / data root / provider）、
   `run_intake.cmd`（1 回実行スクリプト）、`shortcut_instructions.md`。Inbox 内に `_status/` を作る。
3. 自動処理を登録（ユーザー権限・管理者不要・常駐なし）。表示されたコマンドをそのまま実行:

   ```
   python -m src.intelligence.mobile_intake.setup task
   schtasks /Create /F /SC MINUTE /MO 5 /TN "CompassIntake" /TR "\"%USERPROFILE%\.compass_intake\run_intake.cmd\""
   ```

4. 確認:

   ```
   python -m src.intelligence.mobile_intake.setup check
   ```

   `MOBILE_INTAKE_READY` なら完了。`PARTIAL` / `NOT_READY` のときは `diagnostics` に次の一手が出る
   （Inbox 未設定 / フォルダ未同期 / Task 未登録 / 手順未生成）。credential は表示しない。

Inbox の場所は `COMPASS_INBOX_DIR`、Corpus は `INTELLIGENCE_DATA_ROOT` の環境変数でも上書きできる。
`config.yaml` には機械固有 path を書かない。

## 4. 動作（自動処理の中身）

5 分ごとに `processor --once` が 1 回だけ走る（bounded: 最大 20 ファイル / 120 秒 / single-instance lock）。

```
discover → 安定判定（size 不変 × 2 回・mtime 20 秒以上前・open 可能・placeholder でない）
        → lock → IntakeRequest → CompassIntakeService.submit()（Phase 3.7 の検証・重複・解析）
        → ledger → status → unlock
```

- 転送中は **WAITING_UNSTABLE**（QUARANTINE にしない）。30 分を超えて完了しない場合だけ FAILED(TIMEOUT_UNSTABLE)。
- 同じ PDF を二度送っても **DUPLICATE**（「既に登録済み」）。Corpus は二重登録されない。
- Inbox の原本は削除・移動しない（Corpus の immutable copy は Phase 3.7 が別管理）。
- crash 後の lock 残骸は 15 分で回収。再実行は idempotent。busy wait・daemon なし。

## 5. 結果の見方

`_status/latest_status.txt`（iPhone の「ファイル」app からも見える）と `%USERPROFILE%\.compass_intake\latest_status.txt`:

```
2026-09-02
羅針盤追加成功
Corpus: 9 → 10
発行日: 2026-07-01
Milestone 到達: CORPUS_10
Next: CORPUS_30
Remaining: 20
```

他の表示: `既に登録済み` / `処理待ち 1 件（転送中）` / `追加できません: NOT_COMPASS` / `失敗: NOT_PDF`。
machine-readable は `latest_status.json` と `intake_ledger.jsonl`（result / document_id / document_date /
received_at / reason_code / processing_duration / corpus_count_after。本文・full path は含まない）。

## 6. 失敗時の対処

| reason_code | 意味 | 対処 |
|---|---|---|
| NOT_PDF | PDF でない | 羅針盤の PDF を共有し直す |
| NOT_COMPASS | 羅針盤として認識できない（1 ページ目欠落・別資料） | 元の PDF を確認 |
| UNSTABLE_TRANSFER / SYNC_PLACEHOLDER | 同期中 | 待つ（自動で再試行） |
| TIMEOUT_UNSTABLE | 30 分経っても完了しない | iPhone からもう一度共有 |
| UNREADABLE_PDF | PDF が読めない | もう一度開いて共有 |
| DATE_UNKNOWN | 発行日が読めない | 1 ページ目が正しいか確認 |
| SYNC_NOT_AVAILABLE | Inbox に到達できない | iCloud for Windows の同期 / `setup check` |

stack trace はユーザー向け表示に出さない（型名のみ ledger）。

## 7. 手動 fallback

iPhone / iCloud が使えなくても、PDF を Inbox フォルダに **drop するだけ**（USB / AirDrop / ブラウザ保存）。
`config.yaml` の provider を `LOCAL_FOLDER` にするか、`setup init --provider LOCAL_FOLDER --inbox <任意フォルダ>`。
その後の処理・重複・status は同じ。project ファイルの操作は不要。

## 8. テスト手順と pilot 結果

- テスト: `python -m pytest tests/intelligence/test_mobile_intake.py`（Phase 3.7 は
  `test_compass_corpus.py`。発行時刻 provenance の regression を含む）。
- pilot: `python -m src.intelligence.mobile_intake.pilot`（isolated root `compass_intake_pilot`、offline）。
  実在する private 羅針盤 9 本で Corpus を seed し、10 本目を同期フォルダへ「到着」させる:
  半分だけ書かれた状態 → WAITING_UNSTABLE（処理待ち） → 完全・安定 → SUCCESS（Corpus 9 → 10、
  CORPUS_10 到達、Next CORPUS_30 / Remaining 20） → 同名 ` 2` の再送 → DUPLICATE（既に登録済み） →
  再実行 → 変化なし → stale lock 回収 → 非 PDF FAILED(NOT_PDF) / 別資料 QUARANTINED(NOT_COMPASS) /
  `.icloud` placeholder WAITING → 30 分超の転送 FAILED(TIMEOUT_UNSTABLE) → max_files=1 で bounded。
  原本 PDF の hash 不変、Inbox 原本削除なし、repository 不変、tracked PDF 0、full path なし。

## 9. プライバシー / セキュリティ

- PDF は Git に入らない（`research/source_docs/*` と Inbox は repository 外 or gitignore）。GitHub Actions へ送らない。
- 本文を log / status / ledger に書かない。full path は末尾 2 要素に redact（`.../Shortcuts/CompassInbox`）。
- cloud token・新 secret・外部 LLM・public endpoint・telemetry なし。processor は同期フォルダ（ローカル FS）だけを見る。
- 発行時刻の由来を `publication_time_source`（DOCUMENT_TEXT / PDF_METADATA / RECEIVED_TIME /
  EXTERNAL_VERIFIED / UNKNOWN）で明示。紙面明記の 7:30 を優先し、不明なら捏造しない。`received_at` は別 field。
