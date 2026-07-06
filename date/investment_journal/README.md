# data/investment_journal/ — Investment Journal（v2.8・①）

このフォルダには `journal.json` が**自動生成**されます（手で作る必要はありません）。

- 毎朝のレポート生成時に、その日のAI判断（重要ニュース・テーマ・シナリオ・
  Investment Thesis・Market Regime・Money Flow・Top Picks・Confidence・
  重要イベント、および後日比較用の主要指標の参照価格）が1日1件追記されます。
- 30日／90日／180日が経過した記録は、その時点の市場データと自動で比較され、
  AI判断が当たっていたか（★評価・的中/部分的中/外れ）が付与されます。
- 結果はレポートの「Learning History」セクションに表示されます。

## 永続化について

`journal.json` は GitHub Actions が毎朝コミットして蓄積します
（`.github/workflows/daily-market-brief.yml` が `git add` します）。
ローカルで試すと自動生成されますが、そのファイルは実行環境ごとの実データです。

本文の転載や個人情報は含みません（分析結果の要約のみ）。
