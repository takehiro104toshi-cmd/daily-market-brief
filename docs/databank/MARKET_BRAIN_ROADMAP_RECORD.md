# MARKET BRAIN ROADMAP RECORD（長期の設計の記録 ・runtime の実装を承認しない）

利用者が承認した長期の vision（自動で育つ ・証拠に根ざした Market Brain）と、repository の実際の能力の目録を突き合わせた
**設計の記録**。本記録は **いかなる runtime の実装も承認しない**。以下の track（P13-E ・P13-K ・P13-R ・P14-I ・P14-V ・P14-L ・P12-B0 ・L0）は
roadmap の設計の track であり、完了した機能 ・存在する API ・検証の完了のいずれも主張しない。各 track の各 gate は、それぞれ監督の個別の GO を要する。

| 項目 | 値 |
|---|---|
| 基準の HEAD | `12dcfb2143527ca44a3e55afa7a2daa9bab2c33d`（P13-A3 の受理した commit） |
| 記録の種類 | 文書だけ（`src/` ・config ・workflow ・Pages ・scheduler ・pin ・資格情報 ・private root は変えない） |
| 凍結の扱い | P8 〜 P12 ・P12.5 の設計の契約（A0 ・A2 ・closeout）・P13-A0 〜 A3 は変更しない ・再開しない |
| 優先 | 本記録と凍結の契約が食い違えば **凍結の契約が優先**し、差は監督の決定に回す |
| 表記 | [VERIFIED CODE] code で確かめた事実 ・[FROZEN CONTRACT] 凍結の契約 ・[APPROVED VISION] 利用者の承認した方向 ・[PROPOSED DESIGN] 設計の提案 ・[OPEN DECISION] 監督の決定待ち |

## 1. 範囲と非主張

- 本記録は roadmap の設計だけを記録する。実装 ・試験 ・登録 ・取得 ・LLM の利用 ・公開を承認しない。
- 「〜する」と書く箇所は全て将来の設計の提案（[PROPOSED DESIGN]）であり、現在の挙動ではない。現在の挙動は [VERIFIED CODE] の行だけ。
- 推定の工数は暫定の幅であり、期日 ・約束ではない（§13）。
- 投資の推奨 ・順位 ・score ・配分 ・取引 ・自動の portfolio の執行は、どの track にも無い（A0 の不変量）。

## 2. 承認された vision [APPROVED VISION]

1. 承認された市場情報（news ・会社の開示 ・財務 ・市場の観察 ・経済指標）を自動で取得する。
2. 情報を provenance と時刻を持つ構造化の知識に正規化する。
3. 会社 ・業種 ・政策 ・技術 ・マクロ ・市場の theme ・投資の仮説 ・証拠の間の意味のある関係を保つ。
4. 過去の観察 ・過去の分析を黙って書き換えずに、知識を時間とともに蓄積する。
5. 日々の分析のたびに、関連する過去の知識を自動で取り出す。
6. 新しい観察と過去の知識を合わせ、より深く文脈のある分析にする。
7. 分析の主張 ・支持する証拠 ・矛盾する証拠 ・不確かさ ・仮説を無効にする条件を記録する。
8. 過去の分析を、後から利用できた証拠で、先読み（look-ahead）なしに評価する。
9. 再現できる評価に基づいて、分析の改善を **提案**する。
10. 蓄積した知識を Obsidian の Markdown の note と意味のある link として見せる。

利用者は手で note を書き保守するより **自動の蓄積 ・再利用**を優先する。人の介入は、意味のある承認 ・例外 ・統治の決定 ・
必要な Windows の検証に限る。

## 3. 実行の 4 つの領域（混ぜない）

### 3.1 public の legacy production [VERIFIED CODE]

- `.github/workflows/daily-market-brief.yml` が 1 日 6 回 `main.py` を実行し、GitHub Pages に公開する。`main.py` は `src.intelligence` を
  import しない。
- collector（RSS の見出し ・価格 ・FRED ・EDINET の書類の metadata ・TDnet の一覧 ・経済の予定）は memory の中だけで使い、証拠を保存しない。
- 任意の LLM の呼び出しが 1 箇所在り（`src/analysis/llm_enhancer.py`）、失敗 ・未設定では規則ベースの文に戻る。
- 実行は public な repository に journal ・theme の学習 ・run の記録 ・翻訳の cache を commit する。

### 3.2 parked な vNext [VERIFIED CODE]

- `ingestion`（content-addressed な raw store）・`sources` ・`normalization` ・`facts`（fail closed の `known_at`）・`evidence` ・`evidence_qa`
  （`USAGE_RIGHTS` を含む trust gate）・`market` ・`databank` ・`compass` ・`context` ・`reports` は production の閉包に在る。
- producer の workflow は手動の起動だけ（cron は無い）で、data の root は run ごとの一時領域 ＝ 蓄積しない。`/v2` の graft は検証に通った時だけ
  （無ければ legacy だけを公開する）。

### 3.3 隔離された governed な P5 〜 P13 [VERIFIED CODE ・FROZEN CONTRACT]

| Phase | 内容（凍結 ／ 状態） |
|---|---|
| P5 | 予測の記録 ・評価 ・calibration の機構（TOPIX の方向 ・訂正は supersede）。実の履歴は蓄積していない ・production の閉包の外 |
| P6 | entity の目録 ・taxonomy ・theme（mechanism ・証拠の役割 SUPPORTS ／ CONTRADICTS ／ CONTEXT ／ INVALIDATES）・theme の間の関係の graph（人 ／ source の主張だけ）・LLM の提案の経路（偽 ／ 記録の provider だけ）。合成の検証だけ |
| P7 | P6 の PIT の状態からの決定論の narrative。実 data の E2E は未実行 |
| P8 | private な screener（`KnowledgeTime` ・取得の event ／ manifest ・発行体の identity ・PIT の観察）。J-Quants は人が実行する local の transport だけ。anchor `0a32d86` |
| P9 | 人が書く thesis（無効化の条件 ・支持 ／ 反対の証拠の種類）。anchor `4c19701` |
| P10 | profile ・attention。anchor `1a7b9a2` |
| P11 | loopback の read-only な PWA。anchor `43c0b85` |
| P12 | A-track v1（network の無い local の scheduler）凍結。anchor `e390cdd`（validated `3056e25`）。B-track（取得の自動化）は HOLD |
| P12.5 | Market Memory ／ Obsidian の設計の契約。anchor `2d18133` |
| P13 | A0 登録 ・A1 純粋な model（`ccfc8e5`）・A2a governed な P10 の adapter（`12de956`）・A3 private な Memory Store（`12dcfb2`）。Review State Memory（件数 ・構造だけ） |

- src の全体に embedding ・vector ・RAG ・検索 ・retrieval の code は **無い** [VERIFIED CODE]。

### 3.4 将来の private な Market Brain の実行 [PROPOSED DESIGN]

- Market Brain は **private ・local**（Windows ・P12 A-track の様式）で動く。public な GitHub Actions ・Pages には、別に承認された
  公開の gate なしに何も出さない。
- private な root（証拠 ・memory ・graph ・vault）は repository の外 ・互いに重ならない ・同期の folder の外。

## 4. 能力の目録（実装 ／ 設計 ／ 将来）

| 能力 | 状態 | 根拠 |
|---|---|---|
| 自動の取得 | 部分（legacy は live だが保存しない ・vNext は蓄積しない ・P8 は人の実行） | [VERIFIED CODE] |
| 歴史の証拠の保存 | append-only の store の code は在るが production で蓄積しない | [VERIFIED CODE] |
| entity の解決 | P6 の目録 ・P8 の発行体の identity だけ（news ／ 開示との結び付けは無い） | [VERIFIED CODE] |
| 型付きの関係の graph | theme の間だけ | [VERIFIED CODE] |
| 知識の retrieval | 無い | [VERIFIED CODE] |
| 過去の文脈の注入 | legacy の journal の再採点だけ | [VERIFIED CODE] |
| 主張の単位の provenance | vNext の Statement ／ EvidenceLink ・compass の validator（純粋） | [VERIFIED CODE] |
| 時刻 ／ PIT | 強いが分散（P8 ・facts ・P6 ・P13） | [VERIFIED CODE] |
| 仮説の改訂 ・評価 | P9 は人の thesis ・P5 は TOPIX の方向だけ（結び付きは無い） | [VERIFIED CODE] |
| Obsidian | P13-A4 の設計だけ（counts-only） | [FROZEN CONTRACT] |
| 統制した学習 | governed なものは無い | [VERIFIED CODE] |

## 5. 既存の legacy の学習（運用中 ・governed な PIT-safe の学習ではない）

- [VERIFIED CODE] `src/analysis/theme_learning.py` は可変の JSON に theme の予測を書き、日数の経過後に **評価の時点の価格**で評価し、
  その勝率が `main.py` の future intelligence の確信の表示に入る。`src/analysis/investment_journal.py` は過去の snapshot を今日の価格で
  再採点する。これは運用中の自動の feedback であり、PIT-safe ではなく ・governed でもない。
- 本 gate はこれを **変更しない ・無効にしない**。
- 将来の要件 [PROPOSED DESIGN]: P14-V の PIT-safe な再評価（予測の時点で固定した対象 ・後から知られた観察だけ）による shadow の比較 ・
  feedback の隔離は別の governed な gate ・履歴は消さない ・legacy の JSON を governed な証拠として扱わない。

## 6. 層の区別（authority は一方向）[PROPOSED DESIGN]

| 層 | 内容 | authority | 禁じる流れ |
|---|---|---|---|
| SOURCE EVIDENCE | 取得した文書 ・観察 ・source の known_at ・取得の時刻 ・権利 | 不変の証拠（訂正は supersede） | 生成物 ・人の note からの流入 |
| MEMORY | 証拠から決定論で作る構造化の record（P13 の様式） | DERIVED ・再構成できる | 証拠の書き換え |
| KNOWLEDGE GRAPH | 型付きの entity ・関係（§8） | DERIVED ＋ 承認した主張 | 類似度だけの edge ・model の提案の事実化 |
| RETRIEVAL | as-of の cutoff での関連の取り出し（§9） | 無い（読むだけ ・trace を残す） | 将来の情報 ・自己の出力の証拠化 |
| ANALYSIS | 日々の分析 ・Context Pack（§10） | system の出力（origin＝SYSTEM） | 証拠として再利用 |
| EVALUATION | 過去の分析と後の観察の比較（§11） | DERIVED ・規則の版つき | 先読み ・原本の書き換え |
| CONTROLLED IMPROVEMENT | 改善の提案 ・人の承認 ・版の release（§11） | 提案は非 authority | 自動の production の規則の変更 |
| OBSIDIAN PROJECTION | 承認した知識の Markdown の投影（§12） | 投影（authority ではない） | vault ／ 人の note からの自動の取り込み |

- 流れは SOURCE EVIDENCE → MEMORY → KNOWLEDGE GRAPH → RETRIEVAL → ANALYSIS の一方向。EVALUATION は ANALYSIS と後の観察を読む。
  OBSIDIAN PROJECTION は MEMORY ／ GRAPH を投影するだけ。
- **Markdown は system の authority ではない**。人の note は **決して自動で取り込まない**。system の分析 ・model の生成物は証拠にならない。

## 7. 証拠の統治（P12-B0 ・L0 ・P13-E）[PROPOSED DESIGN]

- **取得の権利**: source ごとの取得の可否 ・頻度 ・方法を source の登録に持つ。登録の無い source は取得しない。
- **licensing ・保持**: source ごとの利用の等級 ・保持の期間 ・再現の権利。**承認の無い全文の再現 ・保存はしない**（metadata ・digest ・
  権利の範囲の短い抜粋だけ）。J-Quants の利用条件の確認（保存 ・LLM の利用）は P8 の先送りのまま、取得 ・保存の前に要る。
- **時刻**: source の `known_at`（公表 ・開示の時刻）と、こちらの取得の時刻を別の欄に保つ。精度を落とさない。
- **不変の証拠**: 証拠は content-addressed で不変 ・訂正は supersede ・消さない。
- **資格情報 ・private root の隔離**: 資格情報の保管（credential custody）は P12-B0 の設計で決める。private な data を public な repository ・
  Pages ・CI の log に出さない。

## 8. Knowledge Graph の要件（P13-K）[PROPOSED DESIGN]

- **型付きの関係**: node の型（発行体 ・証券 ・業種 ・theme ・政策 ・機関 ・マクロの系列 ・event ・文書 ・主張 ・仮説 ・分析 ・観察）と、
  意味を文で定義した edge の型（例: 証券の発行 ・業種の分類 ・exposure ・政策の影響 ・P6 の CAUSES ／ AMPLIFIES ／ MITIGATES ／ DEPENDS_ON ・
  言及 ・主張 ・SUPPORTS ／ CONTRADICTS ／ INVALIDATES ・SUPERSEDES ／ CORRECTS ・DERIVED_FROM）。**類似度 ・共起だけの edge は無い**。
- **provenance**: edge は source の provenance（文書の digest ・位置）と主張の provenance（SOURCE_ASSERTED ／ HUMAN_ASSERTED ／ RULE_DERIVED ／
  MODEL_PROPOSED）を持つ。
- **時刻の有効性**: 世界の有効の区間と、知識の時刻（known ・recorded ・retracted）を別に持つ。
- **矛盾 ・supersession**: 矛盾する edge は両方を残し CONTESTED と示す ・自動で解決しない ・置き換えは supersede で前の状態を残す。
- **事実と仮説**: 証拠で支持された主張と仮説を別の型にする ・確信は数値の score ではなく列挙。
- **model の提案と検証済みの事実の分離**: MODEL_PROPOSED は検証 ・人の決定なしに主張にならない（P6 の先例）。
- **決定論の再構成**: graph の generation ＝（memory の generation の digest ・規則の版 ・承認した主張）の純粋な関数 ・完全な digest。
- **export の等級**: node ／ edge ごとに PUBLIC_SAFE ／ PRIVATE_DERIVED ／ PRIVATE_AUTHORITY ／ NEVER（§12 の gate が使う）。

## 9. Retrieval の要件（P13-R）[PROPOSED DESIGN]

- **明示の as-of の cutoff**: 全ての段（構造化の filter ・型付きの graph の走査 ・決定論の keyword の索引）が cutoff を再び適用する。「最新」は無い。
- **source の適格性**: 権利 ・privacy ・origin（SYSTEM ／ MODEL_GENERATED は既定で証拠から除く）で絞る。
- **引用の trace**: 結果は query の digest ・規則の版 ・memory ／ graph の generation の digest ・filter ・候補の件数 ・切り詰めの flag ・全項目の
  完全な digest と known_at を持つ。
- **有界の文脈**: 種類ごとの件数 ・byte の予算。順序は明示の sort の鍵。
- **将来の情報の漏えいの防止**: 将来の日付の囮の文書を使う試験で、cutoff の後の情報が 1 件も出ないことを確かめる。
- **循環の自己確認の防止**: system の分析 ・model の生成物を証拠に数えない ・同じ源の文書の複製を 1 つに数える。
- embedding ／ RAG は別の gate（固定の offline の model ・PIT で切った索引 ・score を品質や確信として出さない）。本記録は承認しない。

## 10. 日々の分析への統合（P14-I）[PROPOSED DESIGN]

- **private な Context Pack が先**: 継続する仮説 ・前の知識に対する新しい展開 ・有効な仮説への矛盾 ・変わった前提を、引用つき ・予算つきで
  private に作る。memory が無い ／ 壊れていれば Context Pack は fail closed（部分の文脈は作らない）で、分析は「過去の文脈は利用できない」と
  示して進む。
- **legacy の `main.py` には自動で取り込まない**。
- **public な GitHub Actions ／ Pages への露出は、別に承認された公開の gate なしに無い**。
- **凍結の P4 は承認なしに再開しない**: `compass` ／ `reports` への入力は、無い時に出力が byte 一致となる任意の入力として、別の gate で決める。
- 取り出した文書の文は data であり、指示の位置に置かない（prompt injection の対策）。

## 11. 評価と統制した改善（P14-V ・P14-L）[PROPOSED DESIGN]

- **記録**: 分析の時点の予測 ・主張を、入力の digest と PIT の印つきで不変に残す（**過去の予測は保存する**・原本を書き換えない）。
- **結果**: 予測の後に知られ、評価の cutoff の前に知られた観察だけを使う（**先読み無し**）。対象は予測の時点で固定する（生存の偏りの防止）。
- **評価**: 純粋 ・規則の版つき ・再現できる。
- **提案**: 改善の提案は別の record ・**証拠とは別** ・自動で適用しない。
- **release**: 人の承認 ・版つき ・shadow の評価の後 ・巻き戻し可能。**自律の production の規則の変更は無い**（取引 ・執行も無い）。

## 12. Obsidian（P13-A4 以後）[FROZEN CONTRACT ・PROPOSED DESIGN]

- 現在の P13-A4 は **counts-only** のまま（P13-A4 の設計の調査と監督の決定に従う）。
- より豊かな note（業種 ・theme ・会社 ・証拠 ・仮説の履歴）は、段階ごとの将来の **export の許可の gate** を要する（export の識別子の規則 ・
  会社の名前の権利 ・外部 link の可否 ・個人の authority の privacy）。
- Markdown は system の authority ではない ・人の note は決して自動で取り込まない ・生成 note と人の note は分ける（A0 §6）。

## 13. 依存 ・track ・milestone [PROPOSED DESIGN]

```
P13-A4 → P13-A5 → P13-A6（Market Memory v1 の freeze）
P12-B0（取得の統治 ・資格情報の保管）─┐
L0（licensing ・保持の方針）──────────┼→ P13-E（Evidence Memory: 永続の証拠 ・G2 〜 G5 の取り込み）
                                       └→ P12-B1 以後（local の定時の取得）
P13-E → P13-K（Knowledge Graph）→ P13-R（Retrieval）→ P14-I（日々の分析への統合）
P14-I ＋ 後の観察（P13-E）→ P14-V（評価）→ P14-L（統制した改善）
Obsidian の段階の拡張は P13-K と export の許可の gate の後
```

並行に調べられるもの: P13-A4 の実装 ・P12-B0 ・L0 ・P13-E0 ／ P13-K0 の設計の草案。先に統治の決定を要するもの: 自動の取得（資格情報の保管）・
実の LLM の provider（P6-DEF-07）・公開の露出。

| track | 前提 | 成果物 | 客観的な受け入れ試験 | Windows | 中止の条件 | 暫定の工数（gate の session 数） |
|---|---|---|---|---|---|---|
| P13-A4 | A4 の決定 D1 〜 D11 | counts-only の投影 | byte の再生 ・generated ／ notes の分離 ・privacy ・公開の途中の障害 | A5 | 証拠の位置の未決 | 2 〜 4 |
| P13-A5 | A4 | private の検証の記録 | junction ／ reparse ・ACL ・開いた handle ・中断 | 要 | private root の変更 | 1 〜 3 |
| P13-A6 | A5 | v1 の freeze の記録 | freeze の guard | — | — | 1 |
| P12-B0 | — | 取得の統治 ・資格情報の保管の設計 | — | 設計 | 資格情報の露出の経路 | 1 〜 2 |
| L0 | — | source の登録 ・licensing の方針 | — | — | 解決できない利用条件 | 1 〜 2 |
| P13-E | A6 ・B0 ・L0 | 永続の証拠 ・P8 の証拠 ／ 観察の取り込み | 不変 ・PIT ・権利の走査 ・再生 | 要 | 全文の保持が必要になる | 6 〜 12 |
| P13-K | P13-E | 型付きの graph ・主張の流れ | 決定論 ・矛盾 ・類似度の edge の不在 | 要 | 証拠の無い edge | 6 〜 10 |
| P13-R | P13-K | 決定論の retrieval ・trace | PIT の囮 ・予算 ・trace の完全性 | 要 | 将来の情報の漏えい | 4 〜 8 |
| P14-I | P13-R | private な Context Pack → gate つきの入力 | fail closed ・引用 ・自己確認の防止 | 要 | gate 無しの P4 の再開 | 5 〜 9 |
| P14-V ／ P14-L | P14-I ・P13-E | 評価 ・提案の record ・承認の流れ | 後知恵 ・生存の偏り ・自動の deploy の不在 | 要 | 自動の規則の変更 | 6 〜 12 |

工数の幅は暫定であり、期日 ・約束ではない。各 gate の調査で見直す。残る不確かさ: licensing ・日本語の会社名の entity の解決 ・決定論の
索引の規模 ・legacy の pipeline への依存 ・Windows の file system の挙動。

## 14. 保留の決定（監督）[OPEN DECISION]

1. P13-A4 の証拠の root の構成（A0 は memory root の証拠と書くが、A3 の layout は新しい entry を拒む）。
2. P13-A4 の回復の状態機械（明示の再開だけか ・次の run の自動の収束か）。
3. P12-B の資格情報の保管（credential custody）。
4. source の licensing ・保持 ・再現の権利。
5. private ／ public の実行の分離（Market Brain の出力を public の brief に出すか ・どの gate で）。
6. Knowledge Graph と Retrieval の契約（型 ・edge の意味 ・export の等級 ・予算）。
7. P14 の評価と release の統治（承認者 ・shadow の期間 ・巻き戻し）。
8. phase の構成（P13 の track E ／ K ／ R と P14 の track I ／ V ／ L ・または P13.5 の設計の phase）。
9. legacy の学習の feedback の扱い（隔離 ・移行 ・比較）。

## 15. 凍結の保護

- 不変: P4 〜 P12 の runtime ・P12 A-track v1 の 43 file ・P12.5 の設計の契約 ・P13-A0 〜 A3 の runtime ・公開の面 ・config ・workflow ・Secrets ・
  runtime の pin。本記録はどの anchor も再開しない。
- 将来、凍結の境界の再開が要る箇所（それぞれ別の gate と risk の評価）: P4 の `compass` ／ `reports` への入力 ・P12-B の取得 ・実の LLM の
  provider ・公開の gate ・（P13-A4 の決定次第で）A3 の layout の拡張。

## 16. 本記録の承認の範囲

**本記録はいかなる将来の runtime の実装も承認しない**。次の順序は提案であり、各段は監督の個別の GO を要する: P13-A4 の決定 → P13-A4 の実装 ・
検証 → P13-A5 → P13-A6 → P13-E0 の設計（P12-B0 ・L0 の設計の調査と並行）。
