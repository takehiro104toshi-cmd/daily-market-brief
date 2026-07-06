# data/theme_learning/ — Theme Confidence Learning（v2.8・②）

このフォルダには `theme_learning.json` が**自動生成**されます（手で作る必要はありません）。

- 毎朝、テーマ別診断（Momentum・Confidence・予想方向）が各テーマへ追記されます。
- 30日が経過した予想は、その時点の日経平均（地合いの代理指標）と比較して
  当否を評価し、テーマごとの勝率・平均リターン・平均継続日数を集計します。
- 集計した勝率は、Future Intelligence の Confidence を上下限つき（-20〜+10点）で
  「実績補正」するのに使われます（例: 92 → 実績が良ければ95、悪ければ72）。
- 結果はレポートの「Theme Confidence Learning」セクションに表示されます。

## 永続化について

`theme_learning.json` は GitHub Actions が毎朝コミットして蓄積します。
記録が貯まるほど勝率の精度が上がり、AIが自己改善していく仕組みです。
本文の転載や個人情報は含みません（数値の集計のみ）。
