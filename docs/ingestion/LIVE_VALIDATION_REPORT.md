# LIVE_VALIDATION_REPORT — P1-C 最小live検証結果（2026-08-29）

実行環境: GitHub Actions runner（`.github/workflows/p1c-live-validation.yml`・
feature branch限定・contents:read・**Secrets不使用**）。開発コンテナのegress遮断は
迂回していない。run 1 = 監督者指定11ソース、run 2 = 追検証3ソース。
**1ソース=1リクエスト（retryを除く）・bulk ingestionなし**。

実行ログ: Actions run 33268607384（run 1）/ 33268779962（run 2）。
以下は `::LIVE_VALIDATION_RESULT::` 行からの転記（bodyはログへ出していない）。

## 1. 結果一覧（14検証・13ソース。us_treasuryは2回実行）

| source_id | HTTP | 実測state | format実証 | entries | 最新item | 備考 |
|---|---|---|---|---|---|---|
| boj_whatsnew | 200 | **healthy** | RSS2 | 47 | 2026-08-28 | CORE実接続確認 |
| dmb_ecb_press | 200 | **healthy** | RSS2 | 15 | 2026-08-28 | CORE実接続確認 |
| nhk_business | 200 | **healthy** | RSS2 | 86 | 2026-08-09(サンプル内) | CI実測と二重に実証 |
| theverge | 200 | **healthy** | **Atom** | 10 | 2026-08-29 | Atomアダプタのlive実証 |
| fed_press | 200 | degraded | RSS2 | **20** | サンプル内未確認 | **本体稼働・Legacy失敗=クライアント条件と確定**。ETag/Last-Modified有 |
| bls_latest | 403 | —(CI実測でhealthy維持) | — | 0 | — | vNext汎用UAを拒否（UA条件。Legacy CIは毎日成功） |
| us_treasury | timeout×2回 | unverified | — | 0 | — | 全attempt timeout（bot防御疑い）。retry 2回×2実行で確認 |
| dmb_boj_whatsnew | **404** | **dead** | — | 0 | — | whatsnew.rdf提供終了（P1-B DEGRADED→実測DEAD） |
| mof_whatsnew | **404** | **dead** | — | 0 | — | 同上。**旧CORE** |
| jp_mof_press | **404** | **dead** | — | 0 | — | new.xmlも終了→**MOF公式RSS全滅** |
| jp_stat_release | **404** | **dead** | — | 0 | — | index.rdf提供終了。**旧CORE** |
| uk_gov | **404** | **dead** | — | 0 | — | announcements.atom終了（gov.uk構成変更） |
| edinet_disclosures | 404 | auth_required維持 | JSON応答 | — | — | APIホスト到達（パラメータ無しGET=404仕様。認証挙動は未実証） |

fetcher実証項目: conditional GET用validator受信（fed_press: ETag+Last-Modified）、
retry/backoff（us_treasury: timeout→2回retry）、404/403/timeoutのstructured failure記録、
content hash付与（healthy 5件）、source isolation（失敗5件を挟んでrun完走）。

## 2. Legacy CI恒常失敗6件の真因確定

| 失敗ソース | P1-B仮説 | **実測による確定** |
|---|---|---|
| fed_press | UA疑い | **クライアント条件と確定**（適正UAで200・20件パース） |
| dmb_boj_whatsnew | RDF/クライアント疑い | **フィード廃止（404）** |
| mof_whatsnew | RDF/クライアント疑い | **フィード廃止（404）** |
| nikkei / reuters_business / yahoo_jp_reuters | 提供終了 | （検証対象外。P1-B判定維持） |

## 3. カタログへの反映（v3.0.0 → v3.0.1）

- healthy 18→**20**（＋boj_whatsnew, theverge）/ degraded 3→**1**（fed_pressのみ）/
  dead 3→**8** / unverified 60→**55** / auth_required 2（不変）
- **CORE 7→5**: fed_press・boj_whatsnew・dmb_ecb_press・bls_latest・us_treasury。
  mof_whatsnew（dead）・jp_stat_release（dead）はDISABLEへ（CORE∧DEAD禁止則）。
- 歴史レイヤー（historical / recent_ci）は不変。live実測は`method: live_http`として
  current_healthのみ更新（歴史を上書きしない）。

## 4. 発覚したギャップ（P1-D以前に監督者判断が必要な事項）

1. **MOF一次情報の空白**: MOF公式RSS（whatsnew.rdf / new.xml）全滅。暫定代替=二次報道
   （nhk_business）。MOFサイトの新フィードURL調査またはHTMLスクレイピング検討が必要。
2. **JP公式統計の空白**: jp_stat_release死亡。実質的な代替はestat_macro（APIキー要）。
   e-Statキー設定の判断が挙上。
3. **us_treasury不達**: bot防御疑いのtimeout。UA/経路調整後の再検証がP1-D課題。
4. **bls.govのUA条件**: vNext汎用UAは403。Legacy CIのUAは通る→P1-C fetcherの
   UA戦略（連絡先メール入りUAの環境変数注入）を実運用前に確定する。
5. **RDFのlive実証は未達**: カタログ内のRDFフィード3件が全て死亡していたため、
   RDFアダプタはオフラインfixture検証のみ（実装は完了・実フィードでの実証は将来のRDFソース追加時）。

## 5. 節度の記録

リクエスト総数14（run1: 11ソース＋us_treasury retry 2、run2: 3ソース＋retry 2）。
条件付きGET用ヘッダは初回のため未送信。認証は一切送っていない。
body・タイトル等のコンテンツはログへ出していない（件数・形式・状態のみ）。
