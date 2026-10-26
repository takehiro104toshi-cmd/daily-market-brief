# PHASE 7 / P7-A4b — DETERMINISTIC HUMAN-READABLE NARRATIVE RENDERER CONTRACT（STRUCTURE → TEXT / NO LLM / NO NEW SEMANTICS）

A4b は A4a の提示（`NarrativePresentation`）と差分（`NarrativeDiff`）を、固定の日本語の見出しと決定論の template で**人が読める
平文**にする純関数だけを持つ。LLM・provider・永続化・公開 ／ P4 ／ P8 への接続は無い（内部の出力）。
module: `src/intelligence/narrative_intelligence/rendered_model.py`（描画済みの model・文字の安全・上限）・
`render_templates_ja.py`（日本語の template の registry）・`text_renderer.py`（再検証と描画）。
test: `tests/intelligence/test_narrative_renderer.py`（matrix A〜BS）・`tests/intelligence/test_narrative_intelligence_boundary.py`
（BT〜BY: A1 / A2 / A3 / A4a / Phase 6 の byte 凍結・runtime の import closure・module 状態なし・未登録 runtime の検出）・
`tests/intelligence/phase7_runtime_registry.py`（A4b の 3 module を登録）。

anchor: P7-A4a freeze `50b24ef6325da82999eae76c0b2982285a6ce3d5`、P7-A3 freeze `9b336091b2348cc2311872b76a7b4c1d82f92ccf`、
P7-A2 freeze `2dfd85c757d96b3b546f6723f88d70b94a191f97`、P7-A1 freeze `a02ad60878054b5846b11acac720fa2811f32505`、
Phase 6 freeze `5ef313a6a9477f05b4e46756fb8b79c0f0c3d685`。入る前の基準: 4765 passed / 2 skipped。

**本 gate の設計判断（監督の確認を求める）**

| id | 事項 | 選択 |
|---|---|---|
| D-P7-A4B-1 | 入力の境界 | 入力は `(presentation, synthesis)`。何を・どの順で・どの義務で見せるかは提示だけが決める。synthesis は (1) A4a の `plan_presentation` で作り直した提示が与えられた提示と **byte 一致**することの検証と、(2) A4a が許した item の claim の ref の閉じた属性と key を読むためだけに使う（§4）。A4a の `PresentationItem` は relation の向き・型、component の型と key、変化の種類、evidence の種類を持たない（A4a 契約 §26 の引き継ぎどおり synthesis から読む）。提示だけでは §19（向き）・test R ／ M8・BF（欠けた REQUIRED の検出）を満たせない。A4a を迂回する経路（提示に無い claim を読む・並べ替える・選ぶ）は無い |
| D-P7-A4B-2 | FULL ／ SELECTED | FULL だけ（§21）。選択の mode・引数を持たない |
| D-P7-A4B-3 | テーマの label | A1 にテーマの名前は無いので、root id の末尾 8 文字の中立な label `テーマ〈XXXXXXXX〉`（序数・A/B/C を使わない。衝突は `TRACEABILITY_FAILURE`）（§20） |
| D-P7-A4B-4 | 参照の印 | claim id の 16 進の先頭 8 文字（同じ claim は提示と差分で同じ印。衝突は fail closed）（§23） |
| D-P7-A4B-5 | 文に入れる材料 | 固定の label（enum → 日本語）・テーマの label・A1 の key の token（component ／ 無効化条件。A1 の正規表現で作り直して確かめる）・UTC の時刻だけ。evidence の ref id は文に出さず、印で辿る（§8） |
| D-P7-A4B-6 | 0.1.0 で文にしない属性 | 帰結の key・role の出所・機構の確度の分類・変化の facet と subject id（延期。仮説の機構は不確実性の文として必ず出る）（§25 の延期） |
| D-P7-A4B-7 | 差分の出力 | 追加 ／ なくなった ／ 変わらず存在する の 3 区分すべて（圧縮表示の mode は持たない）。なくなった要素は previous の synthesis の材料で書く（§22） |
| D-P7-A4B-8 | 提示 item の id | A4a の item は自身の id を持たないので、`narpit` ＝ content_id（提示 id ＋ item の直列化）を A4b が派生する（§7） |
| D-P7-A4B-9 | boundary guard | 既存の Phase 7 guard は定義名に `render` を禁じている。A4b の 3 module だけ、この 1 語を例外にした（他の語・import・I/O の禁止はそのまま） |

A1 ／ A2 ／ A3 ／ A4a の変更は不要だった（remediation の条件に当たらない）。

---

## 1. 目的

A4a が表示を許した構造を、読みやすい日本語にする。凍結文言 `RENDERING_RULE`:

```
rendering may change wording; rendering may not change epistemic meaning
```

新しい市場の意味（原因・結果・重要度・確率・予測・推奨・確信度・順位）を作らない。

```
NarrativePresentation（A4a・凍結）＋ NarrativeSynthesis（A1・凍結）→ 再検証（A4a で作り直して byte 一致）
  → item ごとに registry の template（narrative_renderer_ja 0.1.0）→ RenderedNarrative
NarrativeDiff ＋ previous ＋ current → 再検証（A4a の diff_syntheses で byte 一致）→ 同じ template → RenderedNarrativeDiff
```

## 2. authority の分類

`AUTHORITY_CLASS = ("DERIVED", "NON_AUTHORITY", "NON_PERSISTENT")`。描画済み Narrative は新しい knowledge authority ではない。
A4b は Theme・observation・attachment・governance・relation・提案・Production DNA・synthesis・提示・差分を書かず変えない（test BJ:
data_root・repo・入力の bytes・module の定数が不変）。内部の出力で、P4 /v2・legacy report・Pages・HTML ／ PDF の配布・email・
LINE・Slack・notifier・scheduler・P8 に接続しない（使い道は後の認可された adapter が決める）。

## 3. 純関数の境界

- 同じ提示（と同じ version）→ 同じ bytes と id（C: 別 process・別 hash seed・`LC_ALL=C`）。
- 時計・乱数・network・filesystem の読み書き・store・環境変数・locale に依存する暗黙の振る舞いを使わない。時刻は UTC にして
  数字だけで `YYYY-MM-DD HH:MM UTC` と書く（`strftime` を使わない）。
- 実行時の証明: `open` ／ `os.open` ／ `os.replace` ／ `os.rename` ／ `os.remove` ／ `os.mkdir` ／ `os.makedirs` ／ `socket` を失敗させても
  同じ出力（BJ / BK）、`time` ／ `random` ／ `secrets` ／ `uuid` ／ `os.urandom` ／ `os.getenv` を失敗させ `os.environ` を空にしても同じ
  出力（BC）、別の path に作った同じ world・mtime の変更で同じ bytes（BB）。

## 4. 入力の境界

- 受け取る: A4a の `NarrativePresentation` ／ `NarrativeDiff` と、その元の A1 `NarrativeSynthesis`（D-P7-A4B-1）。
- 受け取らない: A2 の `NarrativeInputSnapshot`・A3 の engine の実行・Phase 6 の authority・Theme ／ Evidence ／ Relation の store。
- synthesis を**生のまま**描画に使わない。A4a の検証 API（`revalidate_synthesis` → `plan_presentation` ／ `diff_syntheses`）で
  作り直した提示 ／ 差分が、与えられたものと canonical bytes と id まで一致したときだけ描画する。以後は提示の item の順に、
  その claim id の ref だけを読む。

**再検証**（盲信しない）:

1. 提示 ／ 差分の型が違えば `INVALID_PRESENTATION`（dict・JSON・synthesis・None も）。synthesis が A1 の型でなければ
   `INVALID_PRESENTATION`。
2. 提示 ／ 差分の schema と規則表（`narrative_presentation_rules` 0.1.0 ／ `narrative_diff_rules` 0.1.0）が既知でなければ
   `UNSUPPORTED_PRESENTATION_VERSION`（A4a の値の複製。一致は test で固定）。A4a の synthesis の version の拒否もこの code。
3. 提示・section・item（差分と差分の item）の型と属性の集合が完全一致（足された `score` 等を拒否）。
4. item を A4a の constructor で作り直し（section・義務・規則は constructor が決める）、提示 ／ 差分を作り直して id と
   canonical bytes が一致すること（提示 id・item の claim id・義務・section・role・規則・SOURCE_ASSERTED の属性・順序の改ざん）。
5. 元の synthesis から A4a で作り直した提示 ／ 差分と完全一致すること（欠けた REQUIRED の item・足された item・別の synthesis）。

2 以外の違反は `PRESENTATION_INTEGRITY_FAILURE`（BD / BE / BF / BG・AG〜AJ）。

## 5. 出力の model

`rendered_model.py`（不変・`frozen`・`kw_only`）:

- `RenderedItem`: `presentation_item_id`・`claim_ids`（1 つ）・`section`・`rule_id`・`template_id`・`visibility`・`theme_root_ids`・
  `reference_marker`・`text`（平文）。
- `RenderedSection`: `section`・`heading`（固定の日本語）・`items`。
- `RenderedNarrative`: `kind`・`presentation_id`・`source_synthesis_id`・`subject_root_ids`・`theme_labels`（root id → label）・`title`・
  `sections`・`rendered_id`（派生）。`lines()` は題名・【見出し】・`・文［参照 印］` の行の並び（改行文字を含まない）。
- `RenderedDiffGroup` ／ `RenderedNarrativeDiff`: 区分（追加 ／ なくなった ／ 変わらず存在する）ごとの文と、元の差分 ／ 両方の
  synthesis ／ 両方の提示の id。

任意の文字列 1 つだけを返すことはしない。`from_dict` ／ `from_json` ／ 保存の API は持たない（BI）。

## 6. 言語

0.1.0 は日本語だけ（`LANGUAGE = "ja"`。凍結）。言語の引数・多言語化は無い（延期）。言語は identity に束ねる（BA）。

## 7. 追跡

意味を持つ `RenderedItem` は A4a の `PresentationItem` ちょうど 1 つに結び付く: `presentation_item_id =
content_id("narpit", canonical_json({"presentation_id", "item"}))`・`claim_ids = (claim_id,)`・参照の印（D-P7-A4B-8）。辿り方:
描画された文 → `presentation_item_id`（提示 id と item）→ claim id（A1 の `NarrativeClaim`）→ 上流の ref（E / F）。見出しと題名は
構造の label で claim を持たない。それ以外の文は無い（G: 行は題名・見出し・item の文だけで、item の文の数 ＝ claim の数）。

## 8. template の registry

`render_templates_ja.py`（`narrative_renderer_ja` 0.1.0。静的・監査できる表）:

- A4a の規則（P01〜P14）と変種（不確実性 code）ごとに template がちょうど 1 つ（T01〜T18）。各 template は書いた対象の認識 class と
  差し込む field の集合を宣言する。認識 class が合わない item・表に無い組み合わせ・label の無い enum 値・field の不一致は
  `UNSUPPORTED_TEMPLATE`。推測で文言を選ぶ汎用の fallback は無い（BH）。
- 差し込む値は固定の label・テーマの label・A1 の key の token・UTC の時刻だけ（D-P7-A4B-5）。外の知識・記事の本文・欠けた事実の
  補完・推論が要る言い換えは無い（H: 文の可変な部分がすべて claim の材料と一致することを、template から作った正規表現で確かめる）。
- registry の全体の digest を version ごとに test で固定する。canonical な出力を変える文言の変更は `RENDERER_VERSION` を上げる
  （D。描画の golden も固定）。

## 9. 事実の文言

OBSERVED_FACT（P07）は「{時刻}時点の{事実の記録 ／ 観測の記録}が存在します（時刻の扱い: {信頼できる時刻 ／ 申告された時刻}）。」だけ。
解釈・因果・示唆の語を持たない（I）。材料が足りなければ文を作らない（A1 が OBSERVED_FACT の材料を保証する）。

## 10. レビュー済みの解釈の文言

REVIEWED_INTERPRETATION は「…と整理されています」で解釈と分かる形にする（J）。「…が原因です」「…に違いありません」などの断定は無い。
SOURCE_ASSERTED は §16。

## 11. evidence の role

- SUPPORTS（P03）: 「{テーマ}の見方を支持する材料として、{種類}が整理されています。」支持であって証明ではない（証明・確定・
  間違いない を使わない。K）。
- CONTRADICTS（P05）: 「一方、{テーマ}の見方と矛盾する材料として、{種類}が整理されています。」文脈にしない。既定の全体の描画から
  落とさない（L・AG）。
- CONTEXT（P04）: 「{テーマ}に関する文脈の材料として、{種類}が整理されています。」支持・裏付け・反証・矛盾の語を使わない（M）。

## 12. 無効化

条件と材料を区別する（N / O）:

- 条件（P08）: 「{テーマ}の解釈が成り立たなくなる条件として、「{key}」が整理されています。」
- INVALIDATES の材料（P06）: 「{テーマ}の無効化条件「{key}」に関係する材料として、{種類}が整理されています。」
- 条件と材料の結び付き（P09）: 「…結び付けられていると整理されています。これはテーマの状態を変えるものではありません。」

「テーマは無効です」とは書かない。A4b は governance を決めず変えない。

## 13. 不確実性

5 つの code に固定の文言（T10〜T14）: NO_SUPPORTING_EVIDENCE「見方を支持する材料が確認されていません」・SINGLE_SOURCE_EVIDENCE
「単一の出所によるものです」・STALE_EVIDENCE「定められた鮮度の期間より古いものです」・CONTESTED_EVIDENCE「支持する材料と矛盾する
材料が併存しています」・MECHANISM_HYPOTHESIZED「仮説の段階として整理されています」。REQUIRED の不確実性はすべて出る。数値の確率・
確信度の段階を作らない（P）。

## 14. 代替の説明

「同じ材料（{種類}）について、{テーマ〈…〉、テーマ〈…〉}のレビュー済みの説明が並列に記録されています（順不同）。」テーマは root id の
順（順位ではない）で、関係するすべてのテーマを並べる。本命・有力・第一候補・最も可能性が高い などの語は無い（Q）。

## 15. relation

A4a の relation の item だけを書く（推移・逆向きを足さない。S）。向きは上流の relation の source → target のまま（R）:
「{source}が{target}{を引き起こす ／ を増幅する ／ を緩和する ／ に依存する}という関係が、レビュー済みの解釈として整理されています。」
関係の型は上流の `relation_type` の固定の label で、共起を因果にしない。

## 16. SOURCE_ASSERTED

「出典は、{source}が{target}{関係}という関係を主張しています。これは出典による主張であり、この説明が主張する関係ではありません。」
（T17。P13 の唯一の template。限定を外す経路は無い。T / U）。提示の item の assertion class と claim の relation の assertion class が
食い違えば `TRACEABILITY_FAILURE`、提示の改ざんは `PRESENTATION_INTEGRITY_FAILURE`（BG）。

## 17. 変化

比較 cutoff が無い synthesis には変化の文が無い（V）。変化の item は「{テーマ}について、{時刻}と{時刻}の比較から「{変化の種類}」という
構造上の変化が導かれています。」だけ（W）。変化の種類 30 個の label は構造の語（出現・消失・追加・除外・変更・改訂・確定 等）で、
加速・改善・悪化・強まった・弱まった・強気・弱気 を使わない（X / Y）。

## 18. 見出し

A4a の section に固定の日本語の見出し: テーマの状態・機構・材料・矛盾する材料・無効化の条件と材料・不確実性・比較時点との構造上の
変化・テーマ間の関係・並列する別の説明（Z）。差分: 追加された説明要素・なくなった説明要素・変わらず存在する説明要素。
凍結文言 `HEADING_ORDER_MEANING`: 見出しの順は読みやすさのための提示の順で、重要度の順位ではありません（AA / AB）。直列化に順位・
優先度・重みの field は無い。

## 19. THEME_STATE

題名「テーマ〈…〉についての整理」。明示の 1 テーマの状態・機構・材料・反証・無効化・不確実性を A4a の順に並べる。A4a の item が
明示的に参照しない他のテーマは出ない（A4a が THEME_STATE の subject の外を拒否する）。推奨の結論は無い（BS）。

## 20. THEME_SET

題名「複数のテーマについての整理（順不同）」。テーマを平等に扱う: 中心テーマ・最重要テーマ・主役・第一候補 は無い（AD）。canonical な
順は順位ではない。テーマの label は root id の末尾から作る中立な識別子（D-P7-A4B-3。AC）。入力のテーマの順を逆にしても同じ bytes。

## 21. FULL ／ SELECTED

FULL だけ（D-P7-A4B-2）。描画した claim id の並び ＝ 提示の claim id の並び（1 つも落とさない・足さない。内部でも検査）。REQUIRED の
反証・無効化・不確実性・代替を落とした提示は、A4a で作り直した提示と一致しないので描画しない（AE〜AJ）。

## 22. 差分の描画

`render_diff(diff=..., previous=..., current=...)`: 区分ごとに「追加された説明要素」「なくなった説明要素」「変わらず存在する説明要素」の
見出しで、同じ template の文を並べる（AK / AL）。題名「{時刻}時点から{時刻}時点までの説明要素の差分」。ADDED の SUPPORTS を「強まった」、
REMOVED の反証を「改善した」にしない（AM / AN）。区分は claim id の完全一致だけ（AO）。圧縮表示の mode は無い（UNCHANGED も出す）。

## 23. 参照の印

`reference_marker` ＝ claim id の 16 進の先頭 8 文字（D-P7-A4B-4）。平文の行では `［参照 xxxxxxxx］`。同じ claim は提示と差分で同じ印
（AP）。data_root・絶対 path・journal の file 名・秘密値・実装の内部は出さない（AQ / AR）。将来の UI は印 → claim id → ref と辿る。

## 24. 文字の安全と上限

- 平文の値は許可した文字の集合だけ: ひらがな・カタカナ・漢字・`、。「」〈〉【】（）［］`・ASCII の英数字と空白 `_ . : -`。
  `< > & * # \` [ ] ( ) | ~ { } / \`・制御文字・双方向の制御文字を含む値は `UNSAFE_TEXT`（raw HTML・Markdown の注入・path の余地が
  無い）。URL ／ journal ／ 秘密の語（`www.`・`http`・`mailto:`・`javascript:`・`data:`・`file:`・`.json`・`journal`・`api_key` 等）も
  `UNSAFE_TEXT`（AS / AT / AU。URL の形の key を持つ synthesis は描画しない）。
- 上限: item の文 400 字・見出し 40 字・題名 80 字・印 8 文字・item 256 件（差分 512 件）。超えたら `RENDER_LIMIT_EXCEEDED`。切り詰めない
  （AV〜AX）。

## 25. identity と失敗

`rendered_id = content_id("narrnd", canonical_json(payload))`（差分は `narrdf`）。payload は schema（`rendered_narrative:0.1.0`）・
renderer（`narrative_renderer_ja` 0.1.0）・言語・提示 id（差分は差分 id と両方の id）・描画した構造の全体。時計・乱数・path・mtime は
入らない（AY / AZ / BA）。

`FAILURE_CODES`（`NarrativeRenderError`）:

| code | 条件 |
|---|---|
| INVALID_PRESENTATION | 提示 ／ 差分 ／ synthesis の型が違う |
| PRESENTATION_INTEGRITY_FAILURE | 改ざん・作り直しとの不一致・A4a で作り直した提示 ／ 差分との不一致 |
| UNSUPPORTED_PRESENTATION_VERSION | 提示 ／ 差分 ／ synthesis の schema・規則表の version が未知 |
| UNSUPPORTED_TEMPLATE | registry に無い組み合わせ・label の無い値・認識 class ／ field の不一致 |
| UNSAFE_TEXT | 許可した文字の外・URL ／ journal ／ 秘密の語・A1 の key の形でない key |
| RENDER_LIMIT_EXCEEDED | 長さ・件数の上限を超えた |
| TRACEABILITY_FAILURE | claim との結び付き・テーマの label ／ 参照の印の衝突・描画の漏れ |

detail は上流の code・型名・field 名だけで、本文・path・秘密値を含まない。

**security ／ import 境界**: import は A4a（`presentation_model`・`presentation_planner`・`narrative_diff`）・A1（`synthesis_model`）・
`..core.ids`・標準 library（`re`・`dataclasses`・`datetime`・`typing`）だけ。A2・A3 の engine・adapter・Phase 6・P5・legacy・provider ／
LLM・公開 ／ 通知 ／ 売買・locale は import しない（BM〜BQ・boundary）。個人化（初心者 ／ 営業 ／ 顧客 ／ 投資家の型）の mode は無い（BR）。
買い・売り・保有推奨・投資判断・目標株価・期待リターン・ポジションの語は registry にも出力にも無い（BS）。Phase 6 を import してよい
module は P7-A2 の adapter だけのまま（BY）。A1 ／ A2 ／ A3 ／ A4a の runtime と契約は `50b24ef` と byte 一致（BT〜BW）、Phase 6 の runtime は
不変（BX）。scratch の clone で mutation M1〜M15 をすべて検出（結果は CHANGELOG v5.48）。

## 26. A5 への引き継ぎ

1. A5 は `RenderedNarrative` ／ `RenderedNarrativeDiff` を使い、描画をやり直さずに文言を変えない。使う場所（Markdown ／ HTML ／ UI 等）は
   後の認可された adapter が決め、その adapter が形式ごとの escape を持つ（A4b の平文は escape 不要の文字だけ）。
2. 描画を信用するときは、元の提示と synthesis から `render_presentation` を作り直し、`rendered_id` の一致を確かめる（保存されない）。
3. 参照の印・`presentation_item_id`・claim id で文から上流の ref まで辿れる。これを落とさない。
4. 延期（P7-A4B-DEF）: 多言語・読み手別の表現（個人化）・圧縮した差分の表示・帰結の key ／ role の出所 ／ 機構の確度 ／ 変化の facet の
   文・テーマの名前（A1 に無い）・一部だけの描画（入れるなら A4a の `validate_display_selection` を必ず通す）・LLM による文言（別の gate）。
