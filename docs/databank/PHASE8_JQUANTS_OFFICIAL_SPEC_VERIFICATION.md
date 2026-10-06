# PHASE 8 / P8-V — J-QUANTS OFFICIAL SPECIFICATION VERIFICATION

P8-A2.5 が残した J-Quants の意味（V01〜V24）を、**公式の文書**で確かめる gate の記録。実装 ・adapter ・取り込み ・identity の
登録 ・指標の計算 ・screen は無い。認証つきの data 要求 ・live の data API ・credential は使っていない。

- 基準: P8-A2.5 `5713a563e218d2b6065090343eeff7dee8f9b568`（監査の文書は凍結）、P8-A2 `b686b00`、P8-A1 `4162e9c`。runtime は byte 一致。
- 取得日: 2026-09-28（本書のすべての出所の取得日）。
- 変更: 本書（新規）・`CHANGELOG.md` ・文書の登録と凍結の証明に要る Phase 8 の registry と guard だけ（§20）。

---

## 0. 結論

1. **公式の文書の本文を 1 ページも開けなかった。** この session の network の egress policy が公式の host（`jpx-jquants.com` ・
   `jpx.gitbook.io` ・`www.jpx.co.jp`）への接続を拒否した（shell の取得と WebFetch の両方で拒否。§1）。第三者の出所では代えない。
2. 到達できたのは **web 検索の索引**（公式 domain に絞った検索の結果の要約）だけ。これは公式の page の内容に由来するが、要約の
   model を通るので逐語ではなく、問いの語を反響することも確かめた。**索引の手掛かり（本書の L01〜L24）は仕様の authority として
   扱わない。** 公式の page の URL を突き止め、次の確認で何を読むべきかを絞る材料として記録する。
3. したがって **OFFICIALLY_VERIFIED の項目は 0**。V01〜V24 はすべて `OFFICIALLY_UNRESOLVED / DOC_ACCESS_BLOCKED`（repo の実測が
   ある項目は `REPO_ONLY_OBSERVATION` を併記）。A2 の対応付けはすべて BLOCKED か NOT_USED、実データの A3 は 0 指標。
4. それでも方針に効く手掛かりがある（未検証。§3）:
   - 調整後の株価は、分割 ・併合などのたびに**最古の data まで遡って計算し直される**という記述（L15）→ 業者の調整値の履歴は
     `NOT_PIT_GUARANTEED`（§7 の規則でも、公式の保証を確かめられない限りこの分類）。
   - 財務の値は**期首からの累計**、`3Q` は 9 か月の累計という記述（L03 ・L07）。単独の四半期は見当たらない。
   - 財務の値は**単位の換算 ・丸めをしない**という記述（L06）と、**円以外で報告する発行体がある**という記述（L08）→ 通貨と桁は
     行ごとに確かめる必要がある。
   - IFRS の開示には経常利益の概念が無く**空欄**という記述（L05）→ 空欄が「概念なし」と「欠損」を兼ねる。
   - **利用規約 ・ライセンスの説明**は、個人の私的利用に限る ・第三者への配布や分析結果の継続的な提供は私的利用に当たらない ・
     解約やダウングレードの後は保存した data と複製の削除を求める、という趣旨（L20）。本 repository は **public** である（§12）。
     法的な結論は出さない。**raw snapshot の保存は認めない**（人 ／ 法務の確認まで）。
5. 判定は **P8_V_PARTIAL / OFFICIAL_INFORMATION_INSUFFICIENT**（§21）。完了には、公式の host を許可した環境で本 gate の確認を
   やり直すことが要る（§19）。

---

## 1. 出所の方針と到達性

| 項目 | 結果 |
|---|---|
| 使った出所の種類 | 公式の J-Quants の API reference ／ help（`jpx-jquants.com`）、公式の V1 文書（`jpx.gitbook.io`。V2 移行前の定義の手掛かりとしてだけ）、JPX（`jpx.co.jp`。証券コード）。第三者の blog ・Q&A ・tutorial ・LLM の記憶 ・legacy の code は使わない |
| 公式の page の本文 | **開けなかった**。shell（curl）は egress の proxy が CONNECT を 403 で拒否、WebFetch も `EGRESS_BLOCKED`（`jpx-jquants.com` ・`jpx.gitbook.io`）。`www.jpx.co.jp` も shell で到達不可 |
| 到達確認 | 公式の host の root への到達確認（credential なし ・data の path なし）を 1 回ずつ行い、すべて拒否された。API の host も含む（認証 ・data 要求ではない） |
| 使えた経路 | web 検索（公式 domain に絞る）。結果は model の要約で、逐語ではない |
| 認証 | 使っていない。API key を読んでいない ・出していない |
| 第三者の出所 | 使っていない。検索の tool が一度 公式でない domain を返したが、その内容は捨てた |

分類（監督指示 §1 の語彙）: `OFFICIALLY_VERIFIED` ／ `OFFICIALLY_UNRESOLVED` ／ `NOT_DOCUMENTED` ／ `PLAN_DEPENDENT` ／ `NOT_ENTITLED` ／
`REPO_ONLY_OBSERVATION`。本書の追加の修飾:

- `DOC_ACCESS_BLOCKED`: 公式の page は特定したが、環境の policy で本文を開けなかった（監督指示の `AUTHENTICATED_DOC_REQUIRED` と
  同じ扱いで、`OFFICIALLY_UNRESOLVED` の理由）。
- **索引の手掛かり（L-id）**: 公式 domain の検索の要約から得た内容。仕様の根拠にしない。確かめる時にどの page のどこを読むかの
  目印。問いに入れた候補の値をそのまま返した要約（反響）は捨てた。
- `NOT_DOCUMENTED`（文書に無い）は、本文を読めないので**一度も使わない**（無いことを示せない）。

---

## 2. 公式の出所の台帳

発行: `jpx-jquants.com` ・`jpx.gitbook.io` は J-Quants（JPX グループが提供する service）の公式の文書、`jpx.co.jp` は日本取引所
グループ（証券コード協議会の page を含む）。取得日はすべて 2026-09-28。**本文はどれも開けていない**（検索の索引だけ）。

| id | 文書の題（索引の表示） | URL | 関わる V |
|---|---|---|---|
| S01 | 財務情報（/fins/summary）— J-Quants API Reference | https://jpx-jquants.com/ja/spec/fin-summary ・/en/spec/fin-summary | V01〜V13 ・V24 |
| S02 | 開示書類種別 | https://jpx-jquants.com/ja/spec/fin-summary/typeofdocument | V03 ・V06 |
| S03 | 上場銘柄一覧（/equities/master） | https://jpx-jquants.com/ja/spec/eq-master | V16 ・V17 ・V24 |
| S04 | 市場区分コード及び市場区分名 ／ 商品区分コード及び商品区分名 | https://jpx-jquants.com/ja/spec/eq-master/marketcode ・/product-category | V16 ・V17 |
| S05 | 株価四本値（/equities/bars/daily） | https://jpx-jquants.com/ja/spec/eq-bars-daily | V14 ・V15 ・V16 |
| S06 | 調整済み株価の計算方法 | https://jpx-jquants.com/ja/spec/eq-bars-daily/adj | V15 |
| S07 | 提供データの更新タイミング | https://jpx-jquants.com/ja/spec/data-update | V01 ・V14 ・V19 |
| S08 | 契約ごとに利用可能なAPIとデータ格納期間 | https://jpx-jquants.com/ja/spec/data-spec | V21 ・§17 |
| S09 | V1 API から V2 API への変更点 | https://jpx-jquants.com/ja/spec/migration-v1-v2 | 欄名の対応 |
| S10 | データ内容・仕様（Help） | https://jpx-jquants.com/ja/help/data | V04 ・V05 ・V11 ・V12 ・V15 |
| S11 | サービスについて（Help） | https://jpx-jquants.com/en/help/about | V17 |
| S12 | 決算発表予定日（/equities/earnings-calendar） | https://jpx-jquants.com/ja/spec/eq-earnings-cal | V19 |
| S13 | 取引カレンダー（/markets/calendar）・休日区分 | https://jpx-jquants.com/ja/spec/mkt-cal ・/en/spec/mkt-cal/holiday-division | V20 |
| S14 | 利用目的・ライセンス（Help） | https://jpx-jquants.com/ja/help/usage | V22 |
| S15 | J-Quants APIサービス利用規約 | https://jpx-jquants.com/termsofservice | V22 |
| S16 | 財務情報（/fins/statements）（V1 の文書） | https://jpx.gitbook.io/j-quants-ja/api-reference/statements | V07 ・V08 ・V09 |
| S17 | API共通の留意事項（V1 の文書） | https://jpx.gitbook.io/j-quants-ja/api-reference/attention | V12 |
| S18 | 株価四本値（/prices/daily_quotes）（V1 の文書） | https://jpx.gitbook.io/j-quants-ja/api-reference/daily_quotes | V14 |
| S19 | 証券コード英文字組入れ（証券コード協議会） | https://www.jpx.co.jp/sicc/code-pr/ | V18 |

---

## 3. 索引の手掛かり（未検証 ・仕様の根拠にしない）

| id | 内容（言い換え） | 出所の候補 | 注記 |
|---|---|---|---|
| L01 | DiscTime は文字列で、例は `時:分:秒` の形 | S01 | 公表時刻の意味 ・time zone ・常に入るかは出ていない |
| L02 | DiscNo は文字列で、応答は DiscNo の昇順 | S01 | 一意性 ・安定性 ・訂正との関係は出ていない |
| L03 | CurPerType が `3Q` の行は期首から 9 か月の累計 | S10 ・S01 | 値の全集合は未確認（候補を問いに入れた検索の結果は反響として捨てた） |
| L04 | DocType は期間 ・連結 ・会計基準を含む名前（例: 四半期 ／ 年度 × 連結 × IFRS の形） | S02 ・S16 | 全値 ・非連結 ・予想の修正の値は出ていない |
| L05 | 出力の項目名は日本基準の開示項目に基づく。IFRS の開示には経常利益の概念が無く空欄 | S10 ・S01 | 空欄の表現（空文字 ／ null）は出ていない |
| L06 | 財務の値は service 側で単位の換算や追加の丸めをしない。項目の正確な基準は元の決算短信を参照 | S10 | 桁（円 ／ 百万円）は出ていない |
| L07 | 売上 ・営業利益 ・経常利益 ・純利益は期首からの累計 | S10 | CF ・株数については出ていない |
| L08 | 財務諸表を米ドルで報告する発行体があり、その分は米ドルで提供される | S10 | 通貨の欄の有無は出ていない（発行体の名は本書に書かない） |
| L09 | 財務の data は 18:00 と 24:30（JST）に更新（Premium は随時）。更新時刻は保証されない | S07 | provider の更新時刻で、開示時刻ではない |
| L10 | 株価四本値は取引日の立会の終了後に更新。時刻は保証されない | S07 | 同上 |
| L11 | 上場銘柄一覧は過去日 ・当日 ・翌営業日の時点の情報を返す。翌営業日の情報は 17:30 以後。Premium では提供開始日より前の日付は提供開始日の時点を返す | S03 | Light の深さは出ていない |
| L12 | 4 桁の code を指定すると、普通株と優先株の両方がある銘柄では普通株だけが返る。4 桁 ／ 5 桁のどちらも受け付ける | S03 ・S01 | 5 桁目の意味は出ていない |
| L13 | master の応答に社名（和 ／ 英）・17 ／ 33 業種名 ・規模区分 ・市場区分名 ・信用区分名 ・商品区分がある。市場区分 ・商品区分の code 表は別 page | S03 ・S04 | code 表の中身は開けていない |
| L14 | 提供は東京証券取引所の上場銘柄だけ。地方取引所 ・PTS は提供の予定なし | S11 | — |
| L15 | 調整済み株価は、分割 ・併合のたびに提供している最古の data まで遡って計算し直す（遡る期間の上限なし）。生値と調整値と調整係数を提供。調整の対象外の場合は係数 1 | S06 ・S10 ・S05 | 対象の事象の全集合 ・丸めの規則は未確認（有償の別 product の説明と混ざった可能性があり、事象の種類の記述は採らない） |
| L16 | 売買の成立しなかった日は四本値 ・出来高 ・売買代金が null | S18 ・S10 | V2 で同じかは未確認 |
| L17 | V2 は欄名を短縮（Open → O、High → H、Low → L、Close → C、Volume → Vo、TurnoverValue → Va、AdjustmentFactor → AdjFactor） | S09 | repo の実測の欄名と一致 |
| L18 | V1 の財務情報では Equity ＝ 純資産、Profit ＝ 当期純利益、EquityToAssetRatio ＝ 自己資本比率 | S16 | V2 の Eq ／ ShEq ／ NP との対応は出ていない |
| L19 | 決算発表予定日は 3 月 ・9 月決算の会社だけで、翌営業日の予定。参照先が変わった時だけ不定期に 19:00 頃更新 | S12 ・S07 | 履歴の保持は出ていない |
| L20 | 利用は個人の私的利用に限る。法人の利用 ・第三者への配信 ・data を使う app の提供は禁止。本人だけが見られる状態なら本人管理の外部 cloud にも保存できる。解約 ・ダウングレードの後は保存した data と複製を削除。data そのものを閲覧できる形で配布 ・共有しない。分析の結果を継続して第三者に提供するのは私的利用に当たらない | S14 ・S15 | 規約の本文は開けていない。法的な結論は出さない |
| L21 | 2024 年 1 月から、新しい 4 桁の証券コードは 2 桁目 ／ 4 桁目に英字（一部の文字を除く）を含み得る。既存の数字だけの code は変えない | S19 | code の再利用 ・変更の規則は出ていない |
| L22 | 財務情報は四半期の決算の要約と、業績 ・配当の予想の修正の開示を含む | S01 | 予想の対象の年度は出ていない |
| L23 | 取引カレンダーの休日区分は別 page に定義がある | S13 | 値は出ていない |
| L24 | 利用できる API と data の期間は契約で異なる（詳細は S08） | S08 | Light の年数は出ていない |

---

## 4. V01〜V24 の処分

分類の略: `UNRESOLVED/BLOCKED` ＝ `OFFICIALLY_UNRESOLVED / DOC_ACCESS_BLOCKED`、`REPO` ＝ `REPO_ONLY_OBSERVATION`。確定した答えは
**どの項目にも無い**。「暫定の扱い」は、確認までの fail closed の規則。

### 4.1 証拠と答え

| V | 問い | 公式の出所 | 手掛かり | 確定した答え | 分類 | 暫定の扱い |
|---|---|---|---|---|---|---|
| V01 | DiscDate ／ DiscTime の意味 ・time zone ・書式 ・欠損 | S01 ・S07 | L01 ・L09 | なし | UNRESOLVED/BLOCKED ＋ REPO（欄の存在） | `DATE(DiscDate)` だけ。TIMESTAMP は認めない。一定の時刻を作らない |
| V02 | DiscNo の一意性 ・安定性 ・訂正との関係 | S01 | L02 | なし | UNRESOLVED/BLOCKED | 自然 key ＋ raw の行の digest。同じ DiscNo で digest が違えば保留 |
| V03 | DocType の全値と意味 | S02 | L04 ・L05 | なし | UNRESOLVED/BLOCKED | `StatementBasis` を決めない（写さない） |
| V04 | CurPerType と期間の関係 ・累計か単独か | S01 ・S10 | L03 ・L07 | なし | UNRESOLVED/BLOCKED | 年度 ・累計 ・単独のどれにも写さない |
| V05 | F* ／ NxF* の対象の年度 | S01 ・S10 | L22 | なし | UNRESOLVED/BLOCKED | 予想を写さない |
| V06 | NC*（単体）の欄と意味 | S01 ・S02 | L04 | なし | UNRESOLVED/BLOCKED ＋ REPO（存在の記述） | 写さない |
| V07 | Eq ・ShEq ・EqAR ・BPS ・TA の定義 | S01 ・S16 | L18 | なし | UNRESOLVED/BLOCKED ＋ REPO（Eq と ShEq の両方がある） | `EQUITY` ・`TOTAL_ASSETS` に写さない。Eq と ShEq を 1 つにしない |
| V08 | NP の帰属 ・EPS ／ DEPS の種類 | S01 ・S16 | L05 ・L18 | なし | UNRESOLVED/BLOCKED | `NET_INCOME` ・`EPS` に写さない |
| V09 | AvgSh ・ShOutFY ・TrShFY の定義 | S01 ・S16 | なし（V1 の欄名の言い換えだけで意味は出ていない） | なし | UNRESOLVED/BLOCKED ＋ REPO（欄の存在） | 株数を写さない。時価総額に使わない |
| V10 | CF の欄が載る期間 ・累計か | S01 ・S10 | L07 は損益だけ | なし | UNRESOLVED/BLOCKED | 写さない |
| V11 | 単位 ・桁 ・通貨 ・円以外 | S01 ・S10 | L06 ・L08 | なし（円だけではない可能性が高い） | UNRESOLVED/BLOCKED | 暗黙の百万円の換算なし。通貨を確かめられない行は保留 |
| V12 | 欠損の表現 | S17 ・S10 | L05 ・L16 | なし | UNRESOLVED/BLOCKED | null ／ 空 → `MISSING`。`NOT_REPORTED` ・`NOT_APPLICABLE` を作らない |
| V13 | 行の上書き ・訂正値だけを返す可能性 ・RetroRst | S01 ・S10 | なし（財務について） | なし | UNRESOLVED/BLOCKED | 上書きされ得るものとして前向きに版を取る |
| V14 | 四本値の生値 ・売買なしの表現 ・単位 ・公表時刻 ・訂正 | S05 ・S07 ・S18 | L10 ・L16 ・L17 | なし | UNRESOLVED/BLOCKED ＋ REPO（生値と調整値が別の欄） | 知識 ＝ 取得時刻。null は `MISSING` |
| V15 | 調整値 ・調整係数 ・遡及 ・MktCap | S05 ・S06 ・S10 | L15 | なし。§25 の規則で **`NOT_PIT_GUARANTEED`** | UNRESOLVED/BLOCKED | 後から取った調整値の履歴を PIT の authority にしない |
| V16 | UL ／ LL ・ExRT ・Mrgn ・ProdCat | S03 ・S04 ・S05 | L13 | なし | UNRESOLVED/BLOCKED | 写さない |
| V17 | master の深さ ・過去の snapshot の忠実さ ・市場区分 ・東証以外 ・4 桁と 5 桁 | S03 ・S04 ・S11 | L11 ・L12 ・L13 ・L14 | なし | UNRESOLVED/BLOCKED ＋ REPO（過去の 1 日を取得） | 遡って当てない。前向きの snapshot だけ |
| V18 | code の変更 ・再利用の規則 | S19 ・S03 | L21 | なし（新しい code の形だけが手掛かり） | UNRESOLVED/BLOCKED | code だけで継続を認めない |
| V19 | 決算発表予定の履歴 ・変更 | S12 ・S07 | L19 | なし | UNRESOLVED/BLOCKED | 全発行体の予定表として使わない |
| V20 | HolDiv の全値 | S13 | L23 | なし | UNRESOLVED/BLOCKED ＋ REPO（`1` ＝ 営業日を 21/21 で検証） | `1` だけを営業日とする（既存の検証の範囲） |
| V21 | Light の dataset ごとの履歴の深さ | S08 | L11 ・L24 | なし（契約で異なる趣旨の手掛かりだけ） | UNRESOLVED/BLOCKED ＋ REPO（TOPIX は 5 年、10 年は plan で拒否） | 深さを仮定しない |
| V22 | 保存 ・再配布 ・派生 data の条件 | S14 ・S15 | L20 | なし（法的な結論は出さない） | UNRESOLVED/BLOCKED | **raw の保存を認めない**（§12） |
| V23 | code 指定と date 指定で同じ行が返るか | S01 | なし | なし | UNRESOLVED/BLOCKED | digest で冪等に扱う |
| V24 | 複数の上場物を持つ発行体の財務の行 | S01 ・S03 | L12（master だけ） | なし | UNRESOLVED/BLOCKED | 発行体に写さない（保留） |

### 4.2 影響

略: A1 ＝ identity の契約、A2 ＝ 観測の契約、A3 ＝ 派生指標、ADP ＝ 実データの adapter、HIST ＝ 過去の screen。「—」は影響なし。

| V | A1 | A2 | A3 | ADP | HIST |
|---|---|---|---|---|---|
| V01 | — | 構造は TIMESTAMP ／ DATE の両方を持つ（変更不要） | — | DATE 精度だけ | 開示の日は `INSUFFICIENT_TIME_PRECISION` |
| V02 | — | 出所の参照に digest を含める | — | 自然 key の確認まで保留を多く出す | 改訂の結び付けが弱い |
| V03 | — | `StatementBasis` を決められない | 実データの利益率 ・成長率を止める | 財務を写さない | 同左 |
| V04 | — | 期間の基準を決められない（手掛かりは累計） | 同上 | 同上 | 同上 |
| V05 | — | 予想の対象の期間を決められない | 予想を使う指標を止める | 予想を写さない | 同左 |
| V06 | — | 単体を写せない | — | 同左 | — |
| V07 | — | `EQUITY` の定義の固定が要る（P8-OBS-27） | ROE ・PBR を止める | 写さない | — |
| V08 | — | `NET_INCOME` ・`EPS` の定義の確認が要る | 純利益率 ・EPS 成長率 ・PER を止める | 写さない | — |
| V09 | — | `SHARES_OUTSTANDING` の拡張の判断が要る | 時価総額 ・PBR を止める | 写さない | — |
| V10 | — | — | —（最小集合に無い） | 写さない | — |
| V11 | — | JPY だけの A2 と円以外の行の扱い（P8-OBS-37） | 実データの全指標を止める | 通貨 ・桁の不明な行を保留 | 同左 |
| V12 | — | `MISSING` だけを使う | 欠損の伝播 | null ／ 空の区別を raw から | — |
| V13 | — | 版の鎖（変更不要） | — | 前向きの版の取得が必須 | 後からの取得の財務を PIT にしない |
| V14 | — | 生値の写しの確認が要る | return ・変動率 ・流動性を止める | 知識 ＝ 取得時刻 | 後からの取得の価格を PIT にしない |
| V15 | — | 業者の調整値は前向きの版だけ | return を止める | 調整値の履歴を authority にしない | 調整値の履歴を使わない |
| V16 | — | — | — | 写さない | — |
| V17 | 過去の上場物の登録の範囲 | — | — | 前向きの snapshot | 母集団の履歴を作れない |
| V18 | 継続は人の審査 ／ 他の authority | — | — | code を識別子の値としてだけ | code の継続を仮定しない |
| V19 | — | — | — | 財務の取得の予定に使わない | 使わない |
| V20 | — | — | window の指標（P8-OBS-28） | — | 同左 |
| V21 | — | — | — | 深さを仮定しない | 窓の長さを決められない |
| V22 | — | — | — | **raw の保存を始めない** | 版の保持の可否が未定 |
| V23 | — | — | — | 冪等の確認 | — |
| V24 | 複数の上場物の発行体の束ね | — | — | 保留 | — |

---

## 5. dataset の matrix

| dataset | endpoint | Light の entitlement | 履歴 | 更新（手掛かり） | 公式の PIT の保証 | adapter の扱い（提案） |
|---|---|---|---|---|---|---|
| 上場銘柄一覧 | `/equities/master` | AVAILABLE（REPO。公式の表は未確認） | 過去日の指定は受け付ける（REPO ・L11）。Light の深さは未確認 | 翌営業日の情報は 17:30 以後（L11） | UNKNOWN | 前向きに日ごとの snapshot を版として取る（VERSIONABLE_IF_CAPTURED_FORWARD） |
| 株価四本値 | `/equities/bars/daily` | AVAILABLE（REPO） | 1 年の code 指定 ・date 指定を実測（REPO）。深さは未確認 | 立会の終了後（L10） | 生値: UNKNOWN ／ 調整値: **NOT_PIT_GUARANTEED** | 生値は前向きの版。調整値の後からの履歴は参照だけ |
| 財務情報 | `/fins/summary` | AVAILABLE（REPO） | code 指定 20〜31 行 ・date 指定（REPO）。深さは未確認 | 18:00 ／ 24:30（L09） | UNKNOWN | 前向きの版（開示の日の date 指定を毎日） |
| 決算発表予定日 | `/equities/earnings-calendar` | AVAILABLE（REPO） | 翌営業日の分 ・3 月 ／ 9 月決算だけ（L19） | 不定期 19:00 頃（L19） | UNKNOWN | Phase 8 の観測に使わない |
| 取引カレンダー | `/markets/calendar` | AVAILABLE（REPO） | 5 年分（REPO） | — | UNKNOWN | 参照の authority の gate まで使わない |
| TOPIX | `/indices/bars/daily/topix` | AVAILABLE（REPO） | 5 年、10 年は拒否（REPO） | 16:30 頃（repo にある公式の記載） | UNKNOWN | Phase 8 は読まない |
| 詳細財務 ・配当 ・他の指数 ・前場 ・売買内訳 ・空売り | 各 endpoint | **NOT_ENTITLED**（REPO: 403） | — | — | — | 使わない（迂回しない） |
| 決算発表予定日（`/fins/earnings-date`） | — | UNKNOWN（REPO: 400） | — | — | — | 使わない |

公式の plan の表（S08）は開けていないので、entitlement はすべて 2026-09-01 の実測（REPO）で、現在の Light の状態としては未確認。
「API が日付の引数を受け付ける」ことと「Light が過去の深さを与える」ことは別で、後者は確かめていない（監督指示 §26）。

---

## 6. 上場銘柄一覧と code（監督指示 §4 ・§5）

| 問い | 答え | 分類 |
|---|---|---|
| Code | 5 文字（REPO）。4 桁 ／ 5 桁の両方を受け付け、4 桁の指定では普通株だけが返る（L12） | UNRESOLVED/BLOCKED ＋ REPO |
| 社名（和 ／ 英）・17 ／ 33 業種 ・規模区分 ・市場区分 ・信用区分 ・商品区分 | 欄の存在は REPO と L13 が一致。意味 ・code 表は未確認 | UNRESOLVED/BLOCKED ＋ REPO |
| Date の意味 | 指定した日の時点の情報（L11）。snapshot の忠実さは未確認 | UNRESOLVED/BLOCKED |
| 上場日 ・廃止日 | 観測した欄に無い（REPO）。公式に「無い」とは言えない | UNRESOLVED/BLOCKED ＋ REPO |
| 発行体の識別子 ・上場物の識別子 | Code 以外は観測した欄に無い（REPO） | 同上 |
| code の割り当ての履歴 ・市場区分の履歴 ・過去の母集団 | 過去日の snapshot から日ごとに組み立てられる可能性（L11）。深さ ・忠実さは未確認 | 同上 |
| 4 桁と 5 桁の関係 ・正規化 | 4 桁は普通株に解決（L12）。5 桁目の規則は未確認 | 同上 |
| 新しい code の形 | 2024 年から英字を含み得る（L21）。A1 の形（5 文字 ・英大文字と数字）と矛盾しない | UNRESOLVED/BLOCKED |
| code の変更 ・再利用 ・過去の data が古い code を保つか | 手掛かりなし | UNRESOLVED/BLOCKED |

**code だけで継続を認めない**（A1 の設計どおり）。

---

## 7. 株価四本値と調整（監督指示 §6 ・§7）

| 欄（V2 の名 ／ L17 の V1 の名） | 生値 ／ 調整 | 単位 | 日付 | 公表 | 訂正 | 売買なし |
|---|---|---|---|---|---|---|
| O ／ H ／ L ／ C（Open ・High ・Low ・Close） | 生値（REPO ・L15。未確認） | 未確認（円と推定しない） | Date ＝ 取引日（REPO） | 立会の終了後（L10） | 未確認 | null（L16。V1） |
| Vo ／ Va（Volume ・TurnoverValue） | 生値 | 未確認 | 同上 | 同上 | 未確認 | null（L16） |
| AdjO〜AdjC ・AdjVo | 調整値 | 未確認 | 同上 | 同上 | **遡って計算し直される**（L15） | 未確認 |
| AdjFactor（AdjustmentFactor） | 係数 | — | 同上 | 同上 | 未確認 | 未確認 |

調整の問い: 調整の原因の事象（分割 ・併合は L15。他は未確認）、遡及の有無（L15 は遡る）、過去の調整値の変化（L15 から変わり得る）、
基準日（未確認）、係数の履歴（日ごとの欄として取れる: REPO）。**公式の PIT の保証を確かめられないので、調整値の履歴は
`NOT_PIT_GUARANTEED`**（監督指示 §7 の規則）。

---

## 8. 財務の欄の matrix（監督指示 §8 ・§11〜§22）

欄名は repo の実測（V2 の短い名、2026-09-01）をそのまま書く。公式の V2 の欄の表は開けていない。「V1 の対応」は L18 の範囲だけ。

| 欄（実測の名） | 手掛かりの意味 | 実績 ／ 予想 | 期間 | 単位 ・通貨 | 分類 |
|---|---|---|---|---|---|
| Sales | 売上（日本基準の項目名 L05） | 実績 | 累計（L07） | 換算なし（L06）・円以外あり（L08） | UNRESOLVED/BLOCKED |
| OP | 営業利益 | 実績 | 累計（L07） | 同上 | UNRESOLVED/BLOCKED |
| OdP | 経常利益。IFRS では空欄（L05） | 実績 | 累計（L07） | 同上 | UNRESOLVED/BLOCKED |
| NP | 当期純利益（V1 の Profit ＝ 当期純利益: L18）。帰属は未確認 | 実績 | 累計（L07） | 同上 | UNRESOLVED/BLOCKED |
| EPS ／ DEPS | 1 株当たり利益 ／ 希薄化後（欄名だけ） | 実績 | 未確認 | 未確認 | UNRESOLVED/BLOCKED |
| Eq ／ ShEq | V1 の Equity ＝ 純資産（L18）。V2 の 2 欄の対応は未確認 | 実績 | 期末（未確認） | 未確認 | UNRESOLVED/BLOCKED |
| EqAR ・BPS | 自己資本比率（V1: L18）・1 株当たり純資産 | 実績（比率 ・1 株当たり） | 期末（未確認） | 比率の表し方は未確認 | UNRESOLVED/BLOCKED |
| TA | 総資産（欄名だけ） | 実績 | 期末（未確認） | 未確認 | UNRESOLVED/BLOCKED |
| CFO ・CFI ・CFF ・CashEq | CF ・現金同等物（欄名だけ） | 実績 | 未確認 | 未確認 | UNRESOLVED/BLOCKED |
| AvgSh ・ShOutFY ・TrShFY | 株数（欄名だけ） | 実績 | 未確認 | 未確認 | UNRESOLVED/BLOCKED |
| FSales ・FOP ・FOdP ・FNP ・FEPS | 会社予想（L22） | 予想 | 対象の年度は未確認 | 未確認 | UNRESOLVED/BLOCKED |
| NxFSales ・NxFOP ・NxFOdP ・NxFNp ・NxFEPS | 翌期の会社予想（欄名だけ） | 予想 | 同上 | 未確認 | UNRESOLVED/BLOCKED |
| DiscDate ・DiscTime ・DiscNo ・DocType ・CurPerType ・CurFYSt ・CurFYEn ・CurPerSt ・CurPerEn ・NxtFYSt ・NxtFYEn ・RetroRst | 時刻 ・鍵 ・分類 ・期間 ・印 | — | — | — | UNRESOLVED/BLOCKED（§9 ・§10） |

個別の問い（監督指示 §14〜§22）への答え:

- 売上（§14）: 業種の例外（金融など）は未確認。日本基準の項目名で出る（L05）。
- 営業利益（§15）: すべての会計基準 ・業種で入るかは未確認。**営業利益率の実データ化はこの確認を待つ。**
- 純利益（§16）: 「親会社株主に帰属する当期純利益」とは確かめていない。そう仮定しない。
- EPS（§17）: 基本 ／ 希薄化 ・期間 ・単位 ・修正の挙動は未確認。**PER は BLOCKED のまま。**
- 純資産 ／ 自己資本（§18）: V1 では Equity ＝ 純資産（L18）。V2 には Eq と ShEq の 2 欄がある（REPO）。**1 つにまとめない。ROE ・PBR は
  BLOCKED のまま。**
- 総資産（§19）・CF（§20）: 未確認。
- 株数（§21）: 発行済 ・自己株式 ・平均 ・自己株式を除く ・期末 ・予想の株数のどれも未確認。**「株」の付く欄を時価総額や EPS の分母に
  使わない。**
- 予想（§22）: 対象の年度 ・通期か中間か ・修正の挙動は未確認。予想は別の A2 class のまま。
- 単位（§23）: 財務は換算しない（L06）ので、**開示の単位がそのまま出る可能性**がある。桁は行ごとの確認が要り、暗黙の換算はしない。
  通貨は円だけではない（L08）。

---

## 9. 開示の identity と時刻（CRITICAL。監督指示 §9 ・§10）

| 問い | 答え |
|---|---|
| DiscNo の一意の範囲 ・安定性 | 未確認（L02 は文字列 ・昇順だけ） |
| 訂正開示は新しい番号か ・改訂を結べるか ・同じ書類が後で違う値を返すか | 未確認 |
| **DiscTime は実際の公表時刻か** | **確かめられていない。** 書式の例（L01）しか無い |
| **DiscTime は常に入るか ・無い時の仕様** | **確かめられていない** |
| time zone ・書式 | 書式は `時:分:秒` の例（L01）。time zone は未確認 |
| **DiscDate ＋ DiscTime を `KnowledgePrecision.TIMESTAMP` に写せるか** | **いいえ（公式の確認まで）。** `DATE(DiscDate)` だけ。15:30 などの一定の時刻を作らない |

provider の更新時刻（L09: 18:00 ／ 24:30）は **J-Quants で取れるようになった時刻**で、開示の時刻ではない。知識の時刻に使うなら
「取得時刻」（前向きの取得）として使い、開示時刻の代わりにしない。

---

## 10. 期間 ・連結 ／ 非連結（監督指示 §11〜§13）

- CurPerType の値の全集合: 未確認。`3Q` は 9 か月の累計（L03）。問いに値の候補を入れた検索の結果（年度 ・四半期の他の値）は反響の
  おそれがあるので採らない。
- 期間の欄（CurFYSt ・CurFYEn ・CurPerSt ・CurPerEn）と A2 の `period_start` ／ `period_end` ／ 期間の class: 手掛かり（累計）に従えば
  四半期の行は `CUMULATIVE_YEAR_TO_DATE`、年度は `FISCAL_YEAR` だが、**未確認なので写さない**。単独の四半期は累計から作らない。
- 連結 ／ 非連結 ・会計基準: DocType の名に連結 ・会計基準が入る（L04）。同じ発行体 ・期間に 2 つの record（連結と単体、または
  異なる書類）が並び得るかは未確認。出所の優先順位は作らない。

---

## 11. 欠損 ・改訂 ・深さ ・entitlement（監督指示 §23〜§27）

- 欠損（§24）: null（L16: 売買なし）・空欄（L05: IFRS の経常利益）・key が無い ・0 ・`-` の意味の区別は公式に確かめていない。
  **adapter は `MISSING` を保ち、`NOT_APPLICABLE` ・`NOT_REPORTED` を作らない。** L05 の空欄は「概念が無い」と「値が無い」を同じ表現に
  している可能性があり、なおさら区別を推測しない。
- 改訂（§25）: 財務の訂正 ・過去の応答の変化 ・後からの欄の追加 ・master の改訂について公式の保証は確かめていない。調整値は
  遡って変わる（L15）。分類は §5 の表。
- 深さ（§26）・entitlement（§27）: §5。すべて REPO の実測で、公式の plan の表は未確認。

---

## 12. 利用規約と raw snapshot（監督指示 §28 ・§32）

**法的な結論は出さない。** 規約 ・ライセンスの本文（S14 ・S15）は開けておらず、以下は索引の手掛かり（L20）。

| 論点 | 手掛かりの記述 | 未解決の文言 ／ 人 ・法務の確認が要る事 |
|---|---|---|
| 手元の保存 ・cache | 本人だけが見られる状態なら保存でき、本人管理の外部 cloud も可。管理は本人の責任 | CI ／ 共有の runner ・Actions の artifact ・log は「本人だけが見られる」に当たるか |
| 派生 data の保持 | 解約 ・ダウングレードの後は保存した data と複製の削除を求める | A2 の authority の値（出所の値の複製）・raw snapshot は削除の対象か。PIT の再現が契約で打ち切られ得る |
| raw の応答の保持 | 同上（保存は私的利用の範囲） | 期間の上限 ・再配布でない保持の範囲 |
| 再配布 | data そのものを閲覧できる形で配布 ・共有しない | **本 repository は public**。raw ・値を commit しない（既存の規律）。Actions の artifact ・log に値が載る経路の確認 |
| 公開表示 | 分析の結果を継続して第三者に提供するのは私的利用に当たらない。法人の利用 ・第三者への配信 ・app の提供は禁止 | J-Quants 由来の値 ・分析を含む出力を公開 ／ 配信する経路（現行の production を含む project 全体）が許されるか |

- 本 repository の visibility は **public**（repository の一覧で確認）。GitHub Pages で公開物を出す project である。P4 の producer の
  workflow は「公開しない」と明記し、Actions の artifact として出力する（repository の workflow の comment）。
- **raw payload の保存は認めない**（監督指示 §28）。
- 判断の材料（監督指示 §32）:

| 案 | 技術の好み | 規約 ・法務の制約（手掛かり） |
|---|---|---|
| A. 正準の raw payload snapshot | 最も良い（改訂 ・欠損の表現を保つ。A2.5 の推奨） | 保存は私的利用の範囲だけ ・解約で削除 ・再配布なし。**確認まで不可** |
| B. 正規化した出所の record の snapshot | 良い（欠損の表現を明示の token で保てば A に近い） | 値の複製なので A と同じ制約 |
| C. metadata ＋ digest だけ | 改訂の**検知**はできる（値は持たない）。A2 の版は作れない | 値を持たないので制約は最も小さい（それでも確認は要る） |
| D. 期限つき ・非公開の A ／ B（本人の環境だけ ・解約で消す ・public な場所に置かない） | A ／ B に近い | 規約の確認で許される範囲に合わせて設計 |

**推奨**: 技術の上では A（または B）。**規約の確認が済むまでは C**（本 gate の後の認可された取得でも値の保存をしない）。確認の結果で
D の範囲を決める。実装しない。

---

## 13. A1R への影響（監督指示 §29）

確かめた公式の事実が無いので、PROVABLE_FROM_JQUANTS は 0。

| 能力 | 分類 | 根拠 |
|---|---|---|
| Security の bootstrap（ある日に上場している物の集合） | UNRESOLVED | 過去日の snapshot（L11 ・REPO）が候補。深さ ・忠実さの確認が要る |
| Issuer の bootstrap | REQUIRES_HUMAN_REVIEW ／ REQUIRES_OTHER_AUTHORITY | 発行体の識別子は観測した欄に無い（REPO） |
| 識別子の継続（code の変更） | REQUIRES_OTHER_AUTHORITY ＋ REQUIRES_HUMAN_REVIEW | code の変更 ・再利用の規則は未確認（L21 は形だけ） |
| 過去の identity | UNRESOLVED | V17 ・V21 |
| 上場の開始 ／ 終了 | REQUIRES_OTHER_AUTHORITY | 上場日 ・廃止日の欄は観測されていない（REPO） |
| 市場区分の履歴 | UNRESOLVED | 日ごとの snapshot の Mkt の差（REPO）が候補。code 表（S04）未確認 |

A2.5 の結論（P8-A1R が実の登録の前に要る）は変わらない。

---

## 14. A2 の対応付けの表（提案。監督指示 §30）

状態: SAFE ／ SAFE_WITH_RESTRICTIONS ／ BLOCKED ／ NOT_USED。公式の確認が 0 のため、値の欄は**すべて BLOCKED**。「確認後の案」は
V の確認が期待どおりだった場合の写し方で、今は使わない。`source_record_ref` の形は A2.5 §25（`jq.<dataset>:<自然 key>:<digest24>`）。

| J-Quants の欄 | A2 の class | A2 の欄 ／ 量 | 主語 | 値の意味 | 単位 | 期間 ／ 日 | 知識の精度 | 出所の参照 | 状態 |
|---|---|---|---|---|---|---|---|---|---|
| O ／ H ／ L ／ C | 市場 | OPEN ／ HIGH ／ LOW ／ CLOSE ・PRICE ・RAW_REPORTED | Security | 生値（V14） | V14 | Date | TIMESTAMP（取得時刻） | `jq.daily_bars:<Code>.<Date>:<digest>` | BLOCKED |
| Vo | 市場 | VOLUME ・TRADED_VOLUME | Security | 出来高（V14） | V14 | Date | 同上 | 同上 | BLOCKED |
| AdjO〜AdjC | 市場 | 同上 ・PROVIDER_ADJUSTED | Security | 調整値（V15。NOT_PIT_GUARANTEED） | V14 | Date | 同上（前向きの版だけ） | 同上 ＋ adjustment_ref | BLOCKED |
| Va ・AdjVo ・AdjFactor ・UL ・LL ・ExRT ・MktCap | — | A2 に欄なし | — | — | — | — | — | — | NOT_USED |
| Sales | 実績 | REVENUE ・MONETARY_AMOUNT | Issuer | V03 ・V11 | V11 | V04 | DATE(DiscDate)（V01 まで） | `jq.fins_summary:<DiscNo>:<digest>` | BLOCKED |
| OP | 実績 | OPERATING_INCOME | Issuer | V03 ・営業利益の有無（§8） | V11 | V04 | 同上 | 同上 | BLOCKED |
| NP | 実績 | NET_INCOME | Issuer | V08 | V11 | V04 | 同上 | 同上 | BLOCKED |
| EPS | 実績 | EPS ・PER_SHARE_AMOUNT | Issuer | V08 | V11 | V04 | 同上 | 同上 | BLOCKED |
| TA | 実績 | TOTAL_ASSETS | Issuer | V07 | V11 | 期末 | 同上 | 同上 | BLOCKED |
| Eq ／ ShEq | 実績 | EQUITY（どちらかは未定） | Issuer | V07 | V11 | 期末 | 同上 | 同上 | BLOCKED |
| CFO | 実績 | OPERATING_CASH_FLOW | Issuer | V10 | V11 | V10 | 同上 | 同上 | BLOCKED |
| ShOutFY ・TrShFY ・AvgSh | 実績 | SHARES_OUTSTANDING（拡張の判断が要る） | Security | V09 | V09 | V09 | 同上 | 同上 | BLOCKED |
| FSales ・FOP ・FNP ・FEPS ・NxF* | 予想 | REVENUE ・OPERATING_INCOME ・NET_INCOME ・EPS | Issuer | V05 | V11 | 対象の年度（V05） | 同上 | 同上 | BLOCKED |
| OdP ・FOdP ・NxFOdP ・DEPS ・BPS ・ROE ・EqAR ・CFI ・CFF ・CashEq ・RetroRst ・NC* | — | A2 に欄なし | — | — | — | — | — | — | NOT_USED |
| DiscDate ・DiscTime | 知識の時刻 | `KnowledgeTime` | — | V01 | — | — | DATE だけ | — | BLOCKED（TIMESTAMP） |
| Code | identity | `IdentifierAssignment(JQUANTS_CODE)` | Security | 識別子の値だけ（継続を示さない） | — | — | — | — | BLOCKED（P8-A1R まで） |

---

## 15. A3 の準備度（監督指示 §31）

READY_FOR_SYNTHETIC_A3 は実データの準備ができたことを意味しない。

| 指標 | 分類 | 理由 |
|---|---|---|
| 売上成長率 | READY_FOR_SYNTHETIC_A3 | A2 の `REVENUE` と明示の期間 ・基準だけで定義できる。実データは V03 ・V04 ・V11 |
| 営業利益率 | READY_FOR_SYNTHETIC_A3 | 同上。実データは営業利益の有無（§15）・V03 ・V11 |
| 純利益率 | DEFER | 最小集合の外。純利益の帰属（V08） |
| EPS 成長率 | BLOCKED | V08 ・分割（P8-OBS-24） |
| ROE | BLOCKED | V07（純資産と自己資本の 2 欄） |
| ROA | DEFER | V07 ・V08 |
| PER | BLOCKED | V08 ・分割 ・実績 ／ 予想の variant |
| PBR | BLOCKED | V07 ・V09 ・A2 に BPS なし |
| 時価総額 | BLOCKED | V09 ・P8-OBS-27 |
| 価格の return | BLOCKED | V14 ・V15（NOT_PIT_GUARANTEED）・P8-OBS-24 ・28 |
| 変動率 | BLOCKED | 同上 |
| 流動性 | BLOCKED | 売買代金が A2 に無い ・V14 ・P8-OBS-28 |

READY_FOR_REAL_MAPPING は **0**。

---

## 16. 所見の登録（監督指示 §33）

分類: OFFICIALLY_RESOLVED ／ PARTIALLY_RESOLVED ／ STILL_UNRESOLVED ／ IDENTITY_POLICY_REQUIRED ／ ADAPTER_REQUIRED ／
TERMS_REVIEW_REQUIRED ／ NON_BLOCKING_DEFERRED。A2.5 の文書は凍結なので書き換えず、ここで更新する。**OFFICIALLY_RESOLVED は 0。**

| id | 所見 | 分類 | 本 gate での変化 |
|---|---|---|---|
| P8-OBS-1 | 財務の既知の時刻が開示時刻を無視 | STILL_UNRESOLVED | DiscTime の意味は未確認（§9）。DATE だけ |
| P8-OBS-2 | SQLite 索引のずれ | ADAPTER_REQUIRED | 構成は A2.5 のとおり |
| P8-OBS-3 ・4 ・5 ・7 ・13 ・15 ・16 | 運用層 ・test ・TOPIX の時刻 ・文言 ・coverage の期限 ・comment ・secrets | NON_BLOCKING_DEFERRED | なし |
| P8-OBS-6 | master に上場 ／ 廃止の履歴が無い | STILL_UNRESOLVED | 過去日の snapshot の手掛かり（L11）。深さは未確認 |
| P8-OBS-8 | 凍結 guard への登録 | A2.5 で CLOSED（本 gate の語彙に無いので状態を引き継ぐ） | 本書の登録も同じ仕組み |
| P8-OBS-9 | 調整後価格の遡及 | PARTIALLY_RESOLVED | 公式の保証を確かめられないので方針は `NOT_PIT_GUARANTEED` で確定（監督指示 §7）。遡る記述の手掛かり（L15）。文言の確認は残る |
| P8-OBS-10 ・11 ・12 ・18 ・29 | 訂正 ・遡及の mode ・bootstrap ・identity の時刻 ・bootstrap の穴 | IDENTITY_POLICY_REQUIRED | 変化なし（§13） |
| P8-OBS-14 | 市場区分 ／ venue の履歴 | STILL_UNRESOLVED | 東証だけの提供（L14）。code 表は未確認 |
| P8-OBS-17 | 真の公表時刻 | ADAPTER_REQUIRED | 前向きの取得と取得時刻 |
| P8-OBS-19 ・20 ・21 ・25 ・30 ・34 | coverage の粒度 ・同日の DATE ・AMBIGUOUS ・legacy store ・同日の訂正 ・A0 の記述 | NON_BLOCKING_DEFERRED | なし |
| P8-OBS-22 | 財務の期間の意味 | STILL_UNRESOLVED | 累計の手掛かり（L03 ・L07）だけ |
| P8-OBS-23 | 株数の意味 | STILL_UNRESOLVED | 手掛かりなし |
| P8-OBS-24 | corporate action ／ 参照の入力 | ADAPTER_REQUIRED | なし |
| P8-OBS-26 | legacy parser が欠損を潰す | ADAPTER_REQUIRED | null と空欄の両方がある手掛かり（L05 ・L16） |
| P8-OBS-27 | A2 の欄の狭さ ／ 定義の曖昧さ | STILL_UNRESOLVED | V1 は Equity ＝ 純資産（L18）。V2 は 2 欄 |
| P8-OBS-28 | カレンダーの authority が無い | ADAPTER_REQUIRED | なし |
| P8-OBS-31 | 予想の対象の年度 | STILL_UNRESOLVED | 手掛かりなし |
| P8-OBS-32 | raw の保存の規約 | TERMS_REVIEW_REQUIRED | 私的利用 ・削除 ・再配布なしの手掛かり（L20） |
| P8-OBS-33 | 履歴の深さ | STILL_UNRESOLVED | 契約で異なる手掛かり（L24）だけ |
| P8-OBS-35【新】 | 公式の文書の host が本 session の egress policy で拒否され、本文を開けない | STILL_UNRESOLVED | 環境の network の設定で host を許可し、確認をやり直す（§19） |
| P8-OBS-36【新】 | 規約の手掛かり（私的利用 ・第三者への提供なし ・解約で削除）が、raw snapshot ・A2 の実の store の保持 ・public な repository の Actions の artifact ／ log ・J-Quants 由来の値を含む出力の公開に関わる（project 全体） | TERMS_REVIEW_REQUIRED | 人 ／ 法務の確認まで、値の保存と公開の経路を広げない |
| P8-OBS-37【新】 | 円以外で報告する発行体がある手掛かり（L08）。A2 は JPY だけ | ADAPTER_REQUIRED | 通貨を確かめられない行は保留。換算しない |
| P8-OBS-38【新】 | 決算発表予定日は 3 月 ／ 9 月決算 ・翌営業日だけの手掛かり（L19） | ADAPTER_REQUIRED | 財務の取得の予定は date 指定の毎日の取得に拠る |
| P8-OBS-39【新】 | 財務の値は換算しない手掛かり（L06）: 開示の単位（桁）が行ごとに違う可能性 | STILL_UNRESOLVED | 桁の欄 ・規則の確認（V11）。暗黙の換算なし |

---

## 17. 監督判断（監督指示 §34）

| id | 論点 | 公式の証拠の影響 | 案 | tradeoff | 推奨 |
|---|---|---|---|---|---|
| D-P8-A2.5-1 | identity の遡及 | なし（手掛かり: 過去日の snapshot は後で C の材料になり得る） | A 厳密 ／ C 明示の遡及 ／ D 2 時刻 | A2.5 のとおり | **変更なし**（A を既定、C を P8-A1R で） |
| D-P8-A2.5-2 | Issuer の bootstrap | 発行体の識別子は観測されず（REPO） | A ／ B ／ C ／ D | 同上 | **変更なし（D）** |
| D-P8-A2.5-4 | snapshot の層 | 規約の手掛かり（L20）が保存 ・保持を制限し得る | A raw ／ B 正規化 ／ C metadata ＋ digest ／ D 期限つき非公開 | 技術は A ／ B、制約は C が最小 | **規約の確認まで C。確認の後に A ／ B ／ D の範囲を決める** |
| D-P8-A2.5-5 | 調整後価格 | 遡って計算し直す手掛かり（L15）・保証なし | 前向きの版だけ authority ／ 参照だけ ／ 使わない | 変わらず | **変更なし**（前向きの版だけ。後からの履歴は `NOT_PIT_GUARANTEED` で参照だけ） |
| D-P8-A2.5-6 | 改訂の保持 | 保証なし。規約は解約で削除を求める手掛かり | すべての版 ／ 最新だけ ／ 初版だけ | すべての版は PIT に必要だが、契約で消える可能性 | **すべての版（規約の範囲で）。保持の期間は D-P8-V-2 の結果に従う** |
| D-P8-A2.5-7 | 時価総額 | 株数の定義は未確認 | 止める ／ 業者の MktCap ／ ShOutFY | 変わらず | **止める** |
| D-P8-A2.5-8 | A3 の集合 | 実データは 0 指標 | 2 つ（合成）／ 増やす | 変わらず | **売上成長率 ・営業利益率を合成 data で** |
| D-P8-A2.5-9 | adapter の時期 | 前提の確認が未完 | C（前提つき） | — | **C。ただし P8-V の完了（§19）と規約の確認を adapter の前提に加える** |
| D-P8-V-1【新】 | 公式の確認の完了の方法 | 本文を開けなかった | a. 環境で公式の host を許可し本 gate をやり直す ／ b. 人が公式の page の該当部分を渡す ／ c. PARTIAL のまま進む | a は最も確か。b は写しの誤りの危険。c は実データの gate を止めたまま | **a** |
| D-P8-V-2【新】 | 規約の確認 | L20 | a. 人 ／ 法務が規約の本文を確認してから値の保存 ・公開の経路を決める ／ b. 確認なしで進む | b は取り返せない | **a（project 全体の既存の出力も対象に含めるかは監督の判断）** |

---

## 18. 検証の方法の注記

- 検索の要約は、問いに入れた語をそのまま返すことがあった（反響）。候補の値を問いに入れない中立の問いで取り直し、反響と思われる
  内容は捨てた（CurPerType の値の全集合 ・市場区分の code の組 ・欄の一覧の説明）。
- 一度、検索の tool が公式でない domain の結果を返した。その内容は使っていない。
- 手掛かりの記述は言い換えで、公式の文言の引用ではない。大きな引用はしない。

---

## 19. 再確認の手順（本 gate の完了に要る事）

1. 環境の network の設定で、次の host を許可する: `jpx-jquants.com`（API reference ・help ・規約）、`www.jpx.co.jp`（証券コード）、
   必要なら `jpx.gitbook.io`（V1 の文書）。
2. §2 の S01〜S19 の本文を開き、V01〜V24 を逐一確かめる（本書の L-id を目印に）。
3. 規約（S14 ・S15）の本文を人 ／ 法務に渡す（D-P8-V-2）。
4. 結果を新しい文書（または監督が決める形）に記す。本書は凍結の対象になる。

---

## 20. 検証と凍結の確認

### 20.1 本 gate の変更

- `docs/databank/PHASE8_JQUANTS_OFFICIAL_SPEC_VERIFICATION.md`【新規】（本書）
- `CHANGELOG.md`（v5.54）
- `tests/intelligence/phase8_runtime_registry.py`: `PHASE8_DOCS` に本書、A2.5 の凍結の anchor `P8_A2_5`
- `tests/intelligence/test_screener_intelligence_boundary.py`: 本書の登録と、runtime と A2.5 の監査の文書が `P8_A2_5` と byte 一致する guard
- runtime ・config.yaml ・workflow ・Pages ・Phase 6 ／ 7 の test ・A1 ／ A2 の module ・A2.5 の文書は無変更

### 20.2 実行した検証

監督指示 §38 の順:

| # | 対象 | 結果 |
|---|---|---|
| 1 | Phase 8 の境界 ／ 凍結の guard | 52 passed（51 ＋ A2.5 の凍結の guard 1） |
| 2 | A2 | 120 passed |
| 3 | A1 | 101 passed |
| 4 | Phase 7 の closeout ／ 凍結（全 suite） | 1002 passed |
| 5 | Phase 6 の completion ／ 凍結 | 552 passed |
| 6 | full pytest | 5222 passed ／ 2 skipped（基準 5221 ／ 2 ＋ 1） |

否定の証明（scratch の clone）: A2.5 の監査の文書を変える → 新しい guard が落ちる。runtime を 1 byte 変える → BL ・A1 ／ A2 ／ A2.5 の
凍結の guard の 4 件が落ちる。本書を registry から外す → Phase 8 の BM と Phase 7 の文書の guard が落ちる。

### 20.3 凍結

A1 ／ A2 の runtime は `4162e9c` ／ `b686b00` ／ `5713a56` と byte 一致。A2.5 の監査の文書は `5713a56` と byte 一致。Phase 6 ／ 7 は無変更。

---

## 21. 最終の判定

**P8_V_PARTIAL / OFFICIAL_INFORMATION_INSUFFICIENT**

理由: 公式の文書の本文を環境の network の policy で開けず、OFFICIALLY_VERIFIED の項目が 0。第三者の出所では代えていない。索引の
手掛かりは方針（調整値の `NOT_PIT_GUARANTEED`、規約の確認、通貨 ・桁の保留）を強めるが、仕様の authority ではない。A1R ・A3 ・adapter ・
live の J-Quants ・identity の登録 ・指標の計算 ・Theme exposure ・screen ／ 順位は行っていない。
