# H0-D1: HOME INFORMATION CONTRACT（文書だけ ・本記録は実装を承認しない）

監督が設計の水準で固定した H0 ／ M0 ／ S0 の決定と Note A ／ B に基づき、iPhone を先にする Home の情報の契約を、守られた文書だけの
記録として残す。本記録は実装を承認しない。合成の data だけを扱い、実の data ・実の source ・private な root への接続は無い。H1 は HOLD。

| 項目 | 値 |
|---|---|
| gate | `H0-D1`（文書 ・registry ・guard だけ） |
| 基準の HEAD | `9d83b5f268ac4b216210733b0e277c54c6be3ee7`（P13-A5-T の commit） |
| schema | `home_snapshot:0.2-synthetic`（内部）・`home_client:0.2-synthetic`（端末への投影） |
| digest の domain | `home.snapshot.v0.2` ・`home.client.v0.2` |
| 状態 | 本記録は実装を承認しない。H1 ・M0-D1 ・S0-D1 ・UI0 の記録は監督の別の承認まで HOLD |

## 1. 範囲と主張しないこと

- 本記録は Home の 6 つの項目の情報の契約だけを書く。実装 ・取得 ・保存 ・公開 ・deploy を承認しない。
- 合成の data だけ。実の金融の data ・実の source ・private な root への access は無い。
- §14 の禁止の意味（売買の判断の助言 ・数値化した見込み ・価格の水準の目標 ・並びの序列 ・数値の点数）は持たない。
- scenario の意味は S0-D1 が持つ。本記録の該当の規則は PROVISIONAL(S0)（§15）。
- 端末での表示 ・保存 ・network の規則は M0-D1 が定める。表示の設計は UI0 が持つ。

## 2. 再利用する契約

- roadmap の記録 §18 ・§19 ・§20 ・§22（6 つの項目 ・scenario の規則 ・track）。
- roadmap の記録 §8（export の等級 ・主張の由来 ・確信は数値ではなく列挙）。
- P12.5-A0 §5.1（時刻の軸）・§5.2（PIT）・§5.5（8 つの状態）・§7（data の分類）。
- P8 の `KnowledgeTime`（TIMESTAMP ／ DATE の精度 ・KNOWN ／ UNKNOWN ／ UNCERTAIN）。
- P13-A1 の `src/intelligence/market_memory/canonical.py`（`canonical_json` ・`domain_digest`）。試験は import して使い、複製しない。
- P4 ・P5 ・P6 の規律と語彙は概念としてだけ再利用する（凍結の runtime は import しない）。

## 3. 6 つの項目（固定の順 ・足さない ・減らさない）

| 順 | 項目 | kind | entry の数 |
|---|---|---|---|
| 1 | 市場の見通し | OUTLOOK | 0 〜 1 |
| 2 | 市場の snapshot（指数 ・金利 ・為替） | SNAPSHOT | 1 〜 12 |
| 3 | 72 時間以内の予定 | EVENTS | 0 〜 8 |
| 4 | 重要な news | NEWS | 0 〜 3 |
| 5 | 前の見通しからの変化 | CHANGE | 0 〜 1 |
| 6 | 関連する会社 ・theme | RELATIONS | 0 〜 10 |

- 項目 1（OUTLOOK）: 見通しの identity（series の id ・版の番号 ・版の digest）・`issued_at` ・`supersedes` の参照 ・`cutoff` ・対象 ・期間を持つ。
  H0 はこれらを参照として運ぶだけで、版の遷移が正しいかを検証 ・確定しない。scenario の参照 ・条件の参照 ・条件の判定の参照は PROVISIONAL(S0)。
  scenario の数 ・条件の判定 ・確信 ・版の遷移は S0-D1 が持ち、H0 は表示の項目として受け取るだけ。
- 項目 2（SNAPSHOT）: 宣言した系列の一覧の順。値は 10 進の文字列 ・単位（`index_pt` ・`%` ・`bp`）・event time ・`known_at` と精度 ・
  `acquired_at` ・状態 ・鮮度の窓の参照 ・証拠を持つ。
- 項目 3（EVENTS）: `as_of` から 72 時間の窓の予定。予定の時刻と精度を持つ。前回 ・予想 ・結果 ・前回の改訂はそれぞれ別の観察であり、
  別の `known_at` ・`acquired_at` ・状態 ・証拠を持つ。
- 項目 4（NEWS）: 関係のある見出しを最大 3 件。各 entry は選定の理由（`selection_rationale` の template）・証拠 ・`known_at` ・`acquired_at` ・
  `as_of` での適格 ・出所を持つ。3 件に満たなければ満たないまま（埋めない）。選定の algorithm は延期であり、本記録は新しい順 ・一律の時間の窓を
  定めない。全文 ・生成した要約は持たない。
- 項目 5（CHANGE）: 規則で導いた記録（`outlook_change`）。前の版と今の版の参照 ・差分の一覧 ・改訂の理由（PROVISIONAL(S0)）を持つ。claim ではない。
- 項目 6（RELATIONS）: entity の参照 ・関係の型 ・主張の由来 ・FACT ／ HYPOTHESIS ・証拠を持つ。追い風 ／ 逆風の label は任意で、scenario に依存する
  HYPOTHESIS としてだけ在る（scenario と条件の参照 ・有効期間 ・確信 ・不確かさは PROVISIONAL(S0)）。並びは分類の順で固定し、序列を付けない。

## 4. 封筒と schema

- 内部の snapshot は `home_snapshot:0.2-synthetic`、端末への投影は `home_client:0.2-synthetic`。
- 封筒の key: `schema_version` ・`synthetic`（常に true）・`fixture_id` ・`snapshot_status`（OK ／ FAILED_CLOSED）・`as_of` ・`rules_version` ・
  `declared_windows` ・`evidence` ・`items`（ちょうど 6）・`coverage` ・`digest`。
- 各 object の key の集合は閉じている（未知の key ・`__proto__` は拒む）。
- 版の移行: schema の id と digest の domain は一緒に版を上げる。互換の無い変更は新しい版で行い、古い版の data は古い版の規則で検証する。
  版を黙って読み替えない。
- build の時刻は snapshot に含めない（identity ・digest の外。必要なら build の証拠に別に残す）。

## 5. 項目と entry ・表示の集約

- 状態 ・時刻 ・鮮度 ・出所は entry ごとに持つ（項目 3 では 4 つの欄の各観察ごと）。項目は自分の状態を持たない。
- 各 entry は元の状態を保つ。集約は entry の状態を消さない ・書き換えない。
- 項目の `render_state` は表示のための派生の値であり、8 つの状態ではない。entry の状態の集合と `snapshot_status` だけの関数であり、
  時計 ・entry の並び ・端末に依らない（決定論）。集約の方針は `h0_render_policy:0.1`（上から順に最初に当たるもの）:
  - snapshot が FAILED_CLOSED なら SUPPRESSED
  - entry が 0 件なら EMPTY
  - 表示できる entry（CURRENT ・STALE ・AMBIGUOUS）が無ければ UNAVAILABLE
  - MISSING ・STALE ・UNKNOWN ・UNCERTAIN ・AMBIGUOUS の entry が 1 つでも在れば PARTIAL
  - 他は AVAILABLE
- 表示できる entry は §7 で値を出す状態だけ。SUPERSEDED の entry は SUPERSEDED のまま数え、表示できる entry に数えない。
  SUPERSEDED だけの項目は AVAILABLE にならない（UNAVAILABLE）。
- AVAILABLE の項目の entry は CURRENT か SUPERSEDED だけで、CURRENT が 1 つ以上在る。
- coverage は、項目 1 ・2 ・4 ・5 ・6 の entry と、項目 3 の各 event の entry、および event が CURRENT ・STALE ・AMBIGUOUS の時だけその 4 つの
  欄を数える。各単位を 1 回だけ数える。証拠の表は数えない。snapshot が FAILED_CLOSED の時は数を出さない。

## 6. 時刻と PIT

- 時刻の軸は混ぜない: event time ・`known_at`（精度つき）・`acquired_at` ・build の時刻（telemetry だけ）。
- H0 の data の規則: 瞬間は UTC の正準の形 `YYYY-MM-DDTHH:MM:SS+00:00`、日は `YYYY-MM-DD` で持つ。合成の data の年は 2099。
- 適格は P8 の `KnowledgeTime` と同じ: TIMESTAMP は `known_at` ≤ `as_of` で KNOWN、他は UNKNOWN。DATE は東京の暦日として扱い、翌日の始まりが
  `as_of` 以前なら KNOWN、その日の始まりが `as_of` より後なら UNKNOWN、他は UNCERTAIN。
- 加えて `acquired_at` ≤ `as_of` を要する。`as_of` の後に取得したものを含む data は無効であり、状態ではない。
- 見通しの版は `issued_at` ≤ `as_of` の時だけ snapshot に入る（時刻の適格だけ。版の遷移が正しいかは PROVISIONAL(S0)）。引用は `cutoff` の
  時点で KNOWN かつ取得済みであること。
- 過去の再構成は、その時点までに作られた記録だけを使う。後の記録 ・後の観察を過去へ適用しない（将来の観察の漏えいは無い）。
- 端末の解釈の規則は H1 の規則であり、本記録は定めない（表示の時間帯 ・parse の方法は M0-D1 ／ H1 が定める）。

## 7. 8 つの状態

| 状態 | 値 | 扱い |
|---|---|---|
| CURRENT | 出す | 通常 |
| SUPERSEDED | 出さない | 後継を出す ・lineage と項目 5 で辿れる |
| MISSING | 出さない | 欠落の理由を出す ・推測しない |
| STALE | 出す | 宣言した窓を超えた印 ・trigger にしない |
| UNKNOWN | 出さない | 件数に残す ・固定の枠では値の無い印 |
| UNCERTAIN | 出さない | 件数に残す ・推測しない |
| AMBIGUOUS | 両方の値 | 矛盾の印 ・事実の根拠にしない |
| INTEGRITY_FAILURE | 出さない | snapshot 全体を fail closed |

- 優先の順: INTEGRITY_FAILURE > MISSING > UNKNOWN > UNCERTAIN > AMBIGUOUS > SUPERSEDED > STALE > CURRENT。
- 時刻だけから導けるのは UNKNOWN と UNCERTAIN だけ。STALE は宣言した窓を要し、宣言の無い窓を参照する data は無効。
- 状態を畳み込まない（別の欄 ・別の印で区別する）。
- SUPERSEDED は、後継が `as_of` で §6 の適格を満たす時だけ。後で出た後継で過去の snapshot の entry を SUPERSEDED にしない（PIT の再構成を保つ）。
  後継の適格が UNCERTAIN なら、前の entry も UNCERTAIN（推測しない）。
- SUPERSEDED の entry は後継の参照を持つ。後継は同じ snapshot の同じ項目の entry として在る。後継の鎖は循環しない。
  参照が解けない ・循環する snapshot は無効。
- 後継の record が存在しなければ、後継の entry を MISSING（理由 `SUCCESSOR_MISSING`）として置く。後継を作らない ・推測しない ・前の版の値で埋めない。
  後継の record が壊れていれば INTEGRITY_FAILURE（snapshot 全体を fail closed）。
- 項目 1 の現在の見通しは SUPERSEDED でない版だけ。現在の版を表示できなければ、前の版を代わりに示さない（前の版は lineage と項目 5 でだけ辿れる）。

## 8. 主張の分類（Note A）

- claim は `claim_type`（FACTUAL ／ RELATIONAL ／ INTERPRETIVE ／ OUTLOOK ／ RISK）・`assertion_origin`（SOURCE_ASSERTED ／ HUMAN_ASSERTED ／
  RULE_DERIVED ／ MODEL_PROPOSED。語彙は変えない）・`epistemic`（FACT ／ HYPOTHESIS）・`citations` ・`derivation` を別の欄に持つ。
- FACT は `claim_type` が FACTUAL ／ RELATIONAL で、由来が SOURCE_ASSERTED ／ HUMAN_ASSERTED ／ RULE_DERIVED であり、引用と導出の入力が全て
  CURRENT ／ STALE の source の記録か FACT の claim である時だけ。
- MODEL_PROPOSED は常に HYPOTHESIS。OUTLOOK ／ RISK ／ INTERPRETIVE は常に HYPOTHESIS。HYPOTHESIS の入力を持つ導出は HYPOTHESIS。
- 仮説はその場で事実に昇格しない（検証は新しい claim として記録する）。
- 条件の判定と見通しの変化は claim ではない別の記録の型であり、`citations` に入らない。

## 9. 出所と証拠の参照

- 証拠の表の参照の種類: `SOURCE_RECORD` ・`DERIVED` ・`CLAIM` ・`OUTLOOK_VERSION`。
- 引用（source の鎖）と導出（規則の鎖）は別の欄で、別に辿れる。
- system ・model の出力を証拠に数えない。同じ源の複製は 1 つに数える。
- 端末への投影は表示の label ・12 文字の短い参照 ・時刻だけを残し、record の id ・完全な digest ・窓の id を落とす。

## 10. export の等級と privacy

- 等級は PUBLIC_SAFE ・PRIVATE_DERIVED ・PRIVATE_AUTHORITY ・NEVER（roadmap の記録 §8）。
- 各 entry は等級を持ち、項目の上限（項目 1 〜 6 は PRIVATE_DERIVED）を超えない。封筒の metadata と件数は PUBLIC_SAFE。
- NEVER と PRIVATE_AUTHORITY の data は snapshot に在れば無効。
- 公開の面（Pages ・公開の report ・Cloudflare）に Home の data を出さない。
- 端末で等級ごとに何を表示するかは M0-D1 が定める。
- 資格情報 ・private な root の位置 ・local の path は snapshot に存在しない。

## 11. 正準化と digest

- 正準の JSON は P13 の `canonical_json`（鍵の sort ・区切りは `,` `:` ・float を拒む）。数は 10 進の文字列か整数だけ。
- 保存した byte と正準の byte が一致すること（重複の鍵 ・並びの違い ・空白は不一致として拒む）。
- digest は `domain_digest` に、snapshot から最上位の `digest` の鍵だけを除いたものを渡して作る。domain は `home.snapshot.v0.2`（内部）と
  `home.client.v0.2`（投影）であり、製品の名前を含めない。
- 本記録の時点で、同じ文字列の domain は repository に無い（既存の domain は `p12.` ・`p13.` で始まる）。
- fixture は pin した許可の一覧（digest と git の blob）に在る時だけ受け入れる。

## 12. 合成の fixture

- 合成の印: `synthetic` は true ・id は `syn_` で始まる ・日時は 2099 年 ・表示の label は「架空」か「合成」で始まる。
- fixture は決定論の生成器（clock ・乱数 ・network ・I/O の無い試験だけの code）で作り、byte の一致で再生する。生成と pin は H1 の gate で行い、
  本記録は fixture を作らない。
- 本記録の記述は検証器で確かめた fixture ではない。

## 13. 検証の不変量

- 6 つの項目がちょうど 1 回ずつ、固定の順で在る。
- 閉じた key の集合と上限（payload は 256 KiB 以下 ・label は 60 文字以下 ・入れ子は 6 段以下）。
- §6 の時刻 ・PIT ・取得の規則。
- 宣言した状態と再計算した状態が一致する。coverage と表示の集約も再計算と一致する。
- §8 の FACT ／ HYPOTHESIS の規則と §10 の等級の規則。
- INTEGRITY_FAILURE が在れば `snapshot_status` は FAILED_CLOSED。
- SUPERSEDED の entry の後継は同じ snapshot の同じ項目に在り、後継の鎖は循環しない。
- AVAILABLE の項目には CURRENT の entry が在る。SUPERSEDED だけの項目は AVAILABLE にならない。
- §14 の禁止の欄 ・語が無い。

## 14. 禁止

- 売買の推奨 ・数値の確率 ・価格の目標 ・順位 ・数値の score を持たない。
- 禁止の欄の名前: `probability` ・`odds` ・`likelihood_pct` ・`rank` ・`ranking` ・`score` ・`rating` ・`weight` ・`target_price` ・`price_target` ・
  `expected_return` ・`recommendation` ・`buy` ・`sell` ・`hold` ・`signal` ・`full_text` ・`body` ・`article_text` ・`llm_summary`。
- 禁止の語（表示の文 ・template）: 推奨 ・買い ・売り ・目標株価 ・確率 ・的中率 ・勝率 ・期待値 ・ランキング ・順位 ・おすすめ ・注目銘柄 ・最新。
- 根拠の無い確信の語（市場の見通しの表示の文 ・template だけ）: 確実 ・必ず。本記録では表示の文 ・template を「」で囲んで書く。
  本記録の規則と契約の義務の記述は対象外。否定の 不確実 ・不確かさ は使ってよい。
- 実の data ・実の source への接続 ・公開の面への露出 ・deploy。

## 15. S0 に依存する暫定の規則（PROVISIONAL(S0)）

S0-D1 は次の権限を持つ: scenario の意味 ・版の遷移が正しいか ・条件の判定 ・確信の意味 ・基本と代替の決定。
H0 が運ぶのは見通しの identity ・`issued_at` ・`supersedes` の参照だけであり、これらの権限を持たない。

- scenario の数と型（基本 ・代替）・方向の語彙。
- 条件の型 ・比較 ・窓 ・条件の判定の状態と遷移。
- 確信の表し方と規則。
- 見通しの版の遷移と改訂の理由。
- 項目 5 の差分の欄。
- 項目 6 の追い風 ／ 逆風の label の束縛。
- 項目 4 の解釈の scenario への参照。

上の規則は S0-D1 が定め、本記録は値を確定しない。
S0 の語彙の値（条件の判定の状態 ・確信の段階 ・基本と代替の印）を本記録は列挙しない。

## 16. 依存と延期

- M0-D1: 端末の表示 ・保存 ・network ・fail closed の描画。
- S0-D1: §15 の規則。
- UI0: 表示だけ（本記録の欄と label を使う）。
- H1: 合成の data だけの prototype。H0 ・M0 ・S0 の固定と code の置き場の決定を要する。HOLD。
- 延期: 実の data（P13-E ・P12-B ・L0）・Knowledge Graph と AI Search（P13-K ・P13-R ・U1 ・Q1）・認証と deploy（M1 ・G-DEPLOY）・
  個人の note（N0）・news の選定の algorithm ・校正した確信 ・週の見通し。

## 17. 本記録の承認の範囲

- 本記録は文書 ・registry ・guard だけ。product の機能 ・runtime の振る舞いは変わらない。
- 本記録は実装を承認しない。H1 ・M0-D1 ・S0-D1 ・UI0 の記録は監督の別の承認を要する。
