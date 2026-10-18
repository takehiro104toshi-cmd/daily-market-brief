# PHASE 12.5 — A0: MARKET MEMORY ／ OBSIDIAN ARCHITECTURE CONTRACT（設計だけ ・runtime は無い）

Phase 12.5 の最初の正式な設計契約。Market Memory（決定論の DERIVED な記憶の層）と、その private な Markdown ／ Obsidian への投影の
**architecture 水準の不変量**を定める。本文書は設計だけであり、runtime ・source adapter ・memory の store ・private root ・Obsidian の vault の
いずれも **本 gate では作らない ・存在しない**。実装は P13 の各 gate（§10 ・§12）で、監督の個別の GO があって初めて行う。

| 項目 | 値 |
|---|---|
| 状態 | **DESIGN ONLY（P12.5-A0 approved with conditions）**。実装は無い ・P12.5 全体は閉じていない ・P13 ・P14 は未着手 |
| 採用した architecture | hybrid: 統治された read-only の source adapter ＋ 構造化 ・決定論 ・DERIVED の memory ＋ private な Markdown ／ Obsidian の投影 ＋ 生成 note と人の note の分離 ＋ 人の note の自動取り込みは無い |
| 命名（architecture 水準で確定） | memory item の id の接頭辞 `p13mem_` ・authority の等級 `authority_class = DERIVED` |
| 入力の面 | P8 は凍結済みの統治された reader と PIT の意味だけ ・P9 ／ P10 は既存の承認済み safe-view の契約だけ ・P11 の read model ・P12 の ledger（全て read-only） |
| 外部 | network 無し ・J-Quants の取得無し ・資格情報無し ・B-track の自動化無し ・LLM ／ embedding ／ 自己学習 ／ 自律の決定無し |
| 凍結の phase | Phase 4 〜 11 ・Phase 12 A-track v1 は不変（§12）。本 gate で `src/` は変えない |

guard（文書の境界だけ）: `tests/intelligence/test_automation_boundary.py` の `test_p12_5_a0_the_architecture_contract_is_design_only_and_holds_no_private_values`。
登録: `tests/intelligence/phase12_runtime_registry.py` の `PHASE12_5_DOCS`（docs の面の guard が受ける追加として `PHASE12_DOCS` にも載せる。
A-track v1 の凍結の範囲 ・anchor は変えない）。

本文書の読み方: **「文書化済み」**と記した節は凍結済みの phase の契約を引くもの（変えない）。それ以外は **提案 ・将来の契約**であり、
P13 の gate で実装 ・検証されるまで存在しない。語彙の注意: 禁止する機能は NON-GOAL として名指しで書く（runtime の語彙の guard は
runtime の identifier に掛かるもので、設計の散文には掛けない）。

---

## 1. 状態と設計だけの範囲

- 本 gate の成果物は本文書 ・CHANGELOG ・文書の境界の guard だけ。`src/` ・config ・workflow ・公開の面 ・private root ・scheduled task は不変。
- 本文書が確定するのは **不変量**（§3 〜 §9）であり、field の一覧 ・API の署名 ・file の形式 ・CLI は確定しない（監督の修正 G）。
  P13 の各 gate が、本文書の不変量に反しない範囲で実装の詳細を決め、それぞれの契約文書と guard で pin する。
- 本文書は P13 の API ・adapter ・schema ・root ・vault が存在すると主張しない。以下で「adapter」「store」「projector」「vault」と呼ぶものは
  全て **将来の構成要素の名前**である。
- B-track（J-Quants の取得の自動化）は HOLD のまま。Market Memory は B-track ・network ・新しい取得が無くても動くことを要件とする（§8）。

## 2. 文書化済みの source の契約と、提案する将来の interface

### 2.1 文書化済み（凍結。Market Memory はこれを変えない）

- **roadmap**（`PHASE10_FINAL_FREEZE.md` §7）: Phase 12.5 ＝ Market Memory ／ Obsidian の設計、Phase 13 ＝ Market Brain ／ Market Memory、
  Phase 14 ＝ 継続学習の統合。「どの phase も自身の gate 無しに Phase 10 の private authority を消費しない」。
- **P8**（`PHASE8_PIT_OBSERVATION_CONTRACT.md` ・`PHASE8_EPOCH1_ACQUISITION_MANIFEST.md` ・`PHASE8_FINAL_FREEZE.md`）: 観察は
  知識の時刻（TIMESTAMP ／ DATE の精度 ・既定の開示時刻は無い）を持ち、PIT の解決は明示の aware な cutoff で行い、精度不足は
  KNOWN ／ UNKNOWN ／ UNCERTAIN の三値で答え、source が食い違えば AMBIGUOUS を返す。訂正は追記専用の supersedes の鎖（slot ごと ・分岐 ・
  非単調は失敗）。取得の証拠は型付き（acquisition event: scope ・acquired_at ・status ・content digest。COMPLETE は provider の完全性ではなく、
  EMPTY は不在の authority ではない）で、manifest が provider の record の参照 ・digest と観察の id を結ぶ。provenance は本文 ・path ・
  資格情報を持たない。J-Quants 由来の data を LLM に渡さない。id は phase の接頭辞つきの content-addressed（正準 JSON ・domain つき sha256）。
- **P9 ／ P10**（`PHASE9_FINAL_FREEZE.md` ・`PHASE10_FINAL_FREEZE.md`）: 人が統治する authority。revision は不変の鎖（seq ・前の revision ・
  reviewed_at）で PIT は「reviewed_at ≤ T の最大 seq」。stale な head は fail-closed。authority は人の決定を executor が実行して初めて生まれる。
  **承認済みの read-only の面**: P10 の `read_p9_safe_view`（P9 の件数の safe view）・`read_personal_review`（P10 の review view）。
  これより広い private の読み取り（`read_p9_private_snapshot` など）は Market Memory の入力にしない（監督の決定 3）。
- **P11**（`PHASE11_FINAL_FREEZE.md`）: `read_ui_model` が返す `UiModel`（`at` ・`as_of_date` ・entries ・source の schema version）は統治された
  DERIVED の read model。browser に永続化しない ・PIT は明示。
- **P12 A-track v1**（`PHASE12_FINAL_FREEZE.md`）: hash-chained ・追記専用の ledger が運用の実行の authority。run の identity は
  正準 JSON の domain つき digest。networkless ・資格情報の拒否 ・無人の回復は無い ・run ごとの snapshot ／ manifest ／ evidence の artifact。
- **全 phase に共通の境界**: 順位 ・score ・推奨 ・取引 ・portfolio ・配分の意味は無い ・公開の出力は無い ・private root は repo の外 ・
  private な値を repo に戻さない。

### 2.2 提案する将来の interface（P13 の gate で初めて存在する）

- **governed source adapter**: §2.1 の承認済み reader だけを呼ぶ read-only の薄い層。P8 は凍結済みの PIT resolver ・acquisition event ／
  manifest の reader を通し、P9 ／ P10 は safe-view の 2 つの関数だけ、P11 は `read_ui_model`、P12 は ledger ・artifact の reader だけ。
  新しい private の読み取り面を発明しない。P8 の広い private root を直接読む設計は **別の gate** を要する（監督の決定 2）。
- **memory store**: 構造化 ・追記専用 ・content-addressed ・決定論の DERIVED の記憶（§4 〜 §5）。
- **projector**: memory から private な Markdown ／ Obsidian の vault へ export だけを行う層（§6）。
- **acquisition interface**: P8 の型付きの取得の証拠だけを入力とする抽象（§8）。B-track はこの証拠を増やすだけで、本契約を変えない。

## 3. architecture と信頼の境界

```
[凍結の authority ・証拠]           [P13: Market Memory（全て DERIVED）]            [private な見る面]
 P8 観察 ・identity ・取得の証拠 ─┐
 P9 ／ P10 safe view ─────────────┼─ governed adapter（read-only）─▶ memory store ─▶ projector ─▶ vault/generated/
 P11 UiModel ─────────────────────┤        （再検証 ・PIT ・digest）    （追記専用）    （export だけ）   vault/notes/（人。code は読まない ・書かない）
 P12 ledger ・artifact ───────────┘
 ◀── authority への書き込みは存在しない（人の決定 → P9 ／ P10 の executor だけが唯一の経路）
```

不変量:
- **一方向**: source → memory → vault。逆方向の経路（vault → memory ・memory → authority）は v1 に存在しない。人の note の自動取り込みは無い。
- **authority は不変**: Market Memory は P8 ／ P9 ／ P10 の authority ・P12 の ledger に書かない。実装の gate では前後の root の manifest が
  不変であることを検証する（P12-A6 の様式）。
- **networkless**: socket ・DNS ・J-Quants ・通知 ・公開 ・cloud sync は無い。資格情報の環境変数が在れば起動を拒む（P12 の様式）。
- **独立の private root**: memory の store ・build の証拠は repo の外 ・既存の authority root（P8 ／ P9 ／ P10 ／ P12）の外の **新しい独立の
  private root** に置く（監督の決定 5）。vault はさらに別の private な folder。どちらも repo に commit しない ・本 gate では作らない。
- **信頼の境界の外**: Obsidian 本体 ・community plugin ・sync service ・OS の検索 index は信頼の境界の外にある（§6）。
- **LLM ／ embedding ／ 自己学習 ／ 自律の決定は v1 に無い**（監督の決定 1）。P14 で扱う場合も自身の gate を要する（§9）。

## 4. memory の authority の意味

- 全ての memory item は `authority_class = DERIVED`。削除して再構築しても情報は失われない（source に全て在る）。Market Memory は
  覚えるだけで **決めない**: 順位 ・score ・推奨 ・配分 ・取引 ・目標の意味を持つ field ・語彙は NON-GOAL として存在しない。
- source の間の食い違いは **解決しない**。P8 が AMBIGUOUS と答えたものは AMBIGUOUS のまま記録し、memory が一方を選ぶことは無い。
- 人の note（vault の `notes/`）は authority ではない。authority へ入る唯一の経路は、人が P9 ／ P10 の executor で実行する決定である。
- memory は source の「それ以上」を知らない: safe view が件数だけを返すなら memory も件数だけを持つ。source の safe surface を越える
  私的な値（P10 の note ・著者 ・provider の生の本文 ・path）は memory に入らない（§7）。
- 「最新」は無い。全ての問いは明示の PIT の cutoff を伴う（§5）。

## 5. provenance ・時刻 ・PIT ・revision ・replay の規則

### 5.1 時刻の 3 つの軸（混ぜない）

- **event time**: 世界でそれが起きた時刻（開示 ・P9 ／ P10 の決定の reviewed_at ・P12 の scheduled_for）。
- **known_at**: source がそれを知った時刻。P8 の観察は P8 の知識の時刻を **精度ごと**に（TIMESTAMP ／ DATE）そのまま運ぶ ・P9 ／ P10 は
  reviewed_at ・P12 は record の時刻。精度を落として単純化しない（監督の修正 A）。
- **observation time（build time）**: Market Memory がそれを読んだ時刻。**telemetry だけ**であり、item の identity ・内容 ・PIT の判定には
  一切使わない。

### 5.2 PIT の規則（P8 の意味を再利用する）

- 全ての rebuild は明示の aware な cutoff `as_of` を取る。item を含めるかは `known_at ≤ as_of` だけで決め、P8 の精度の規則を再利用する:
  精度が足りず判定できないものは **UNCERTAIN として除外し件数に記録**する（推測しない）。「今」「最新」を暗黙の cutoff にしない。
- **歴史の保存**: ある cutoff で「知られていたこと」は後の訂正で書き換えない。P8 の訂正（supersedes の鎖）は memory では **新しい item が
  古い item を supersedes する**形で現れ、両方が残る。cutoff T1 の build は T1 時点の知識を、T2 の build は T2 時点の知識（訂正を含む）を
  再現する。古い build の item を消したり上書きしたりしない（監督の修正 A）。
- source の supersedes ・revision の鎖（P8 の slot ごとの鎖 ・P9 ／ P10 の seq の鎖）は memory の lineage としてそのまま辿れる。

### 5.3 provenance（必須 ・identity の一部）

- 全ての item は source への **不変の参照**（phase ・store ・source 自身の record の id ・record の正準 digest ・source の schema version）を
  1 つ以上持つ。取得の事実は P8 の acquisition event の content digest ・manifest の provider record の digest を参照する。
- 参照の無い item は schema として無効。投影（Markdown）は参照を frontmatter に出す（§6）。
- rebuild の時に全ての参照を **再検証**する。digest の不一致は INTEGRITY_FAILURE（§5.5）であり、黙って再導出しない。

### 5.4 identity と replay

- **item の identity は安定**: `item_id = p13mem_ + domain つき digest(kind ・subject の参照 ・source の参照 ・known_at ・型付きの内容)`。
  build の telemetry（build time ・host ・process ・path）は identity に **含めない**（監督の修正 C）。同じ source の同じ事実は、いつ ・どこで
  rebuild しても同じ `item_id` になる。
- **build の identity** は明示の PIT（`as_of`）・入力の manifest（source root の manifest の digest）・規則の version から導く。build の
  telemetry は build の証拠に別に残す（identity には入れない）。
- **replay**: 同じ `as_of` ・同じ入力の manifest ・同じ規則の version からは byte 一致の item 集合が出る（受け入れ試験 §10）。差が出れば
  それは source の変化（manifest の差で説明できる）か INTEGRITY_FAILURE のどちらかであり、第三の説明は無い。
- 不完全な build は結果にしない: 途中で失敗した build は証拠に FAILED を残し、store へは何も昇格しない。

### 5.5 状態の区別（混同しない。監督の修正 B ・F）

| 状態 | 意味 | 原因の層 | 扱い |
|---|---|---|---|
| CURRENT | 参照が再検証でき、`as_of` 時点で有効 | — | 通常 |
| SUPERSEDED | source の訂正 ・新 revision が後継を持つ | source の意味 | 残す ・lineage で後継へ |
| MISSING | 参照先の record ・store が **存在しない** | source の不在 | 残す ・MISSING と表示 ・推測しない |
| STALE | **年齢**に基づく: 人が宣言した窓より古い（取得が無い ・review が無い） | 時間の経過 | label だけ ・trigger にしない |
| UNKNOWN | P8 の PIT 解決が UNKNOWN（cutoff 時点で知られていない） | PIT | 含めない ・件数に残す |
| UNCERTAIN | 精度不足で判定できない（P8 の意味） | PIT の精度 | 含めない ・件数に残す ・推測しない |
| AMBIGUOUS | source が食い違う（P8 の意味） | source の矛盾 | 両方の参照を記録 ・解決しない |
| INTEGRITY_FAILURE | 参照先は在るが digest ・鎖 ・正準性が **一致しない** | 改竄 ・破損 ・不正な書き換え | build を fail-closed ・黙って再導出しない ・人の手の調査 |

STALE（古い）と INTEGRITY_FAILURE（壊れている）と MISSING（無い）と UNKNOWN ／ UNCERTAIN（PIT で言えない）と AMBIGUOUS（矛盾）は
別の field ・別の表示で区別し、どれも他へ畳み込まない。

## 6. Obsidian の local export の脅威 model と方針

### 6.1 方針（不変量）

- vault は **private な local の folder**。repo の外 ・全ての authority root の外 ・memory root の外。本 gate では作らない。
- **export だけ**: projector は `generated/` 配下だけを書き、`notes/`（人の note）は書かない ・v1 では読まない。vault から memory ・authority への
  自動の経路は無い。
- **generated と人の分離**: 生成 note は frontmatter に `generated: true` ・`authority: DERIVED` ・`item_id` ・build の id ・`as_of` ・source の
  参照（id と digest）を持ち、本文は型付きの field から固定の template で作る（自由文 ・LLM の文章は無い）。人の note は id への link だけで
  生成 note を指す。
- **同期された export 先の拒否**（監督の決定 4）: 既知の sync service（OneDrive ・Dropbox ・iCloud ・Google Drive 等の folder の目印）・
  Obsidian の sync の設定が検出できる場合、projector は export を **拒む**。ただし **検出は不完全**であり、機密性の保証ではない。利用者が
  vault を後から同期対象にすれば防げない。これを vault 内の方針 note と本契約の両方に明記する。
- **plugin**: community plugin ・外部 service と連携する plugin は信頼の境界の外。生成 note は「safe surface が既に出している値」だけを含む
  ので（§7）、plugin が読んでも authority ・private な値 ・資格情報 ・path には届かない設計にする。plugin の無効化 ・制限は利用者の運用。
- **vault の目印**: projector は vault の root の目印 file が無ければ書かない。目印は人が置く（code が作らない）。

### 6.2 crash-safe な公開（監督の修正 D）

- **staged → verified → published**: 新しい build の note は vault 内の staging の領域に全て書き、検証（§6.3 の全 check ・byte の決定論 ・
  参照の整合）に通ってから初めて公開の位置へ入れ替える。**検証に通る代替が揃う前に既存の生成 note を消さない**。
- 入れ替えは atomic か、atomic でない platform では **回復可能**にする: 入れ替えの前後の manifest（file の一覧と digest）を証拠に残し、
  途中で止まった場合は次の run が manifest から「公開の途中」を検出して完了か巻き戻しのどちらかに **決定論で**収束する。黙って混在した
  状態を残さない。
- 公開後の `generated/` の全 file の digest の一覧（export manifest）を memory root の証拠に残す。vault 側には digest を含む index note だけ。
- 失敗した export は `generated/` を触らず証拠に FAILED を残す。

### 6.3 安全性の check（監督の修正 E）

projector は書く前と公開の前に、少なくとも次を検査し、1 つでも失敗すれば export 全体を拒む:

- **path**: export 先 ・staging ・全 file の path は vault の root の下に正規化後も収まる ・`..` ・絶対 path ・drive の指定を含まない ・
  **symlink ／ junction ／ reparse point** を vault の root から file までのどこにも含まない（辿らない ・作らない）。
- **file 名**: id（`p13mem_` ＋ digest の一部）か固定の alphabet に sanitize した slot 名から作る ・長さの上限 ・人や provider の文字列から作らない。
- **Markdown の安全**: 生成 note に raw HTML ・script ・iframe ・data URI ・`file://` ・外部 URL ・外部 link ・絶対 path ・embed（`![[`）を含めない。
  wikilink は生成 note の id への内部 link だけ。frontmatter の値は quote する。改行は LF に固定。
- **埋め込まれた秘密 ・private の形**: 全ての生成 byte を private の形の pattern（資格情報の変数名 ・API key の header ・provider の host ・
  Windows の user profile の path ・SID ・private root の drive ・著者の接頭辞 ・時刻つきの瞬間 ・5 桁の code 等）で走査し、1 件でも
  一致すれば拒む。走査の結果（検査した pattern と件数）は memory root の証拠に残す（vault には残さない）。
- **export 先**: vault の目印の存在 ・git の作業木でない ・repo の外 ・authority root ／ memory root の外 ・既知の sync folder でない。
- **決定論**: 同じ build からの export は byte 一致（受け入れ試験 §10）。

### 6.4 脅威 model

| 脅威 | 設計上の対処 |
|---|---|
| source の毒入れ（改竄 ・注入） | 参照の digest と root の manifest を rebuild ごとに再検証 ・不一致は INTEGRITY_FAILURE で fail-closed ・source は凍結の fail-closed な reader だけで読む |
| provenance の喪失 | 参照は必須で identity の一部 ・参照の無い item は無効 ・投影に参照を出す |
| private な値の露出 | 内容は safe surface の field だけ ・全 byte の pattern 走査 ・vault は repo ・sync folder の外 ・値 ・note ・著者 ・path ・資格情報は出さない |
| 安全でない Markdown ／ link ／ path | 固定 template ・id 由来の file 名 ・外部 link ／ HTML ／ embed の禁止 ・symlink ／ junction ／ traversal の拒否 |
| 非決定の再生成 | identity は telemetry と無関係 ・build id は入力と規則の version から ・byte 一致の受け入れ試験 |
| sync ／ plugin からの漏えい | 信頼の境界の外と明記 ・既知の sync 先は拒む（検出は不完全 ・保証ではない）・生成内容は既に safe |
| 古いものを新しいと見せる | 全 note に known_at ・取得の時刻 ・`as_of` を明示 ・STALE は宣言した窓で label ・「最新」は無い |
| 壊れた公開（途中の crash） | staged → verified → published ・manifest で回復 ・検証前に既存 note を消さない |
| memory から authority への逆流 | 書き込み経路が存在しない ・人の note は読まない ・前後の authority root の manifest の不変を検証 |

## 7. data の分類と safe-field の制限

| 等級 | 例 | memory ／ vault |
|---|---|---|
| **出してよい（safe surface）** | source の id ・状態 ・件数 ・日付 ／ 知識の時刻（精度つき）・revision の seq ・P12 の run の状態 ・digest ・schema version | 入る（生成 note に出る） |
| **出さない（private の値）** | P10 の note ・著者 ・reviewer の識別 ・provider の生の本文 ・財務の値 ・5 桁の code の生値 ・price ・local の path ・host ・SID ・user 名 | 入らない。source の safe view が返さないものは memory も持たない |
| **決して存在しない** | 資格情報 ・API key ・token ・環境変数の値 ・private root の位置 ・command line | 存在しない ・pattern 走査で拒む |

- 生成 note の本文は型付きの field を **固定の template** で並べたもの。自由文 ・要約 ・LLM の文章 ・provider の文字列の転記は無い。
- P8 の値の露出の範囲は P8 の凍結の契約と safe surface に従い、Market Memory が独自に広げない。広げるには別の gate。
- REPORT ・証拠 ・log の行は P12 と同じ規律: pid ・path ・user 名 ・SID ・raw XML ・command line ・時刻つきの瞬間 ・private な値を印字しない。

## 8. B-track の取得 interface（取得は実装しない）

- Market Memory は取得を **P8 の型付きの証拠だけ**から知る: acquisition event（scope ・acquired_at ・status ・content digest）・manifest
  （provider record の参照 ・digest → 観察の id）・P8 の観察の store。provider の値は P8 の観察（型付き ・PIT 解決済み ・provenance つき）を
  経由して初めて memory の事実になる。provider の data から暗黙の authority は生まれない。COMPLETE ／ EMPTY は P8 の限定した意味のまま。
- **鮮度は表明するもので仮定しない**: 取得の事実は取得の時刻を持ち、note は「いつの知識か」「最後の取得はいつか」を明示する。
  鮮度の等級（人が宣言した窓による）は label であり trigger ではない。
- **自動の取得が無い今の状態で動く**（監督の決定 7）: rebuild は既存の証拠だけで進み、窓の中に取得の無い subject は STALE と label する。
  何も fetch しない ・network に出ない ・資格情報を持たない。
- B-track が将来承認されても、それは P8 自身の型付きの経路で証拠を **増やすだけ**であり、本契約の interface は変わらない。B-track は
  本文書の範囲の外（HOLD）。

## 9. 将来の P13 ／ P14 の境界

- **P13（Market Brain ／ Market Memory）の v1**: 純粋な決定論の処理 ・replay と lineage ・本文書の不変量の実装。LLM ・自律の学習 ・推奨 ・
  順位 ・配分 ・取引は無い。P9 ／ P10 の authority を変えない。P8 の広い private の読み取りは別の gate。
- **P14（継続学習の統合）**: 本文書の範囲の外。P13 の replay 可能な substrate（item ・build ・lineage）の上に乗ることを想定するが、
  学習 ・LLM ・自動の決定のいずれも P14 自身の gate と脅威 model を要する。P13 は P14 を先取りする field ・経路を持たない。
- どの phase も、自身の gate 無しに Phase 10 の private authority を消費しない（roadmap の規則を再確認）。

## 10. 将来の客観的な受け入れ試験（実装の gate で課す。本 gate では走らせない）

1. **決定論 ・replay**: 同じ `as_of` ・同じ入力 manifest ・同じ規則 version で 2 回 rebuild → item の集合 ・store の byte ・export の byte が一致。
2. **identity の安定**: build time ・host ・root の位置を変えても同じ事実の `item_id` が一致。telemetry を変えた build の証拠だけが異なる。
3. **PIT の歴史の保存**: 訂正の鎖を持つ合成の source で、T1 の build と T2 の build が各時点の知識を再現し、T1 の item が T2 で消えない。
4. **精度 ・曖昧さ**: DATE 精度と TIMESTAMP の cutoff の組で UNCERTAIN が除外 ・件数に残る。食い違う source は AMBIGUOUS のまま。
5. **状態の区別**: MISSING ・STALE ・UNKNOWN ・UNCERTAIN ・AMBIGUOUS ・INTEGRITY_FAILURE を 1 つずつ起こす合成 case で、別の field ・別の
   表示になり、INTEGRITY_FAILURE だけが build を止める。
6. **authority の不変**: rebuild ・export の前後で P8 ／ P9 ／ P10 ／ P12 の root の manifest が一致。write の API が存在しない（import ・名前の guard）。
7. **networkless ・資格情報**: socket ・DNS の guard ・資格情報の変数が在れば起動を拒む（P12 の試験の再利用）。
8. **export の安全**: traversal ・symlink ／ junction ・外部 link ・HTML ・embed ・private の形の各 1 件で export 全体が拒まれる ・`notes/` は
   一切書かれない ・目印 ・sync folder ・git 作業木 ・repo 内 ・authority root 内の export 先は拒まれる。
9. **crash-safe な公開**: staging の途中 ・入れ替えの途中で止めた合成 case で、既存の生成 note が残り、次の run が manifest から決定論で収束する。
10. **語彙 ・private**: runtime の identifier に投資 ・LLM ・時計の相対語が無い ・直列化 ・文書に private の形が無い（P12 の guard の様式）。
11. **実機**: Windows の read-only の private validation（repo の外の helper ・使い捨ての vault ・前後の manifest）— A6 の様式。

## 11. 未解決の問いと明示に先送りする決定

- P9 ／ P10 の safe view は件数中心であるため、memory の P9 ／ P10 の面は件数 ・状態の粒度になる。id 粒度の記憶が要るなら **別の gate**で
  read-only の面を監督が承認する（本文書は発明しない）。
- P8 の観察 ・取得の証拠を「凍結済みの reader でどこまで読むか」（PIT resolver ・acquisition event ／ manifest の reader の範囲）は P13-A2 の
  契約で監督が確定する。
- STALE の窓（日数）・鮮度の等級の名前は人が config で宣言する。本文書は値を決めない。
- memory の store の file 形式（JSONL ＋ checkpoint を想定）・build の証拠の形式 ・Markdown の template の文面は P13 の gate で確定。
- 同期 folder の検出の方法 ・対象の一覧 ・「拒む」か「拒んだ上で人が明示に override できるか」は P13-A4 で確定（既定は拒む）。
- memory root の位置の決め方（config の key ・目印 file）は P13-A3 で確定。本文書は位置を書かない。
- P14 の学習の入力に P13 の item を使うかは P14 の gate の問い。P13 は先取りしない。

## 12. 凍結の phase の保護と closeout の基準

- **不変**: Phase 4 〜 11 の runtime ・Phase 12 A-track v1 の runtime 43 file（anchor `e390cdd…` ・validated tree `3056e25…`）・公開の面 ・
  config ・workflow ・Secrets。本 gate は `src/` を変えず、既存の anchor ・registry の定数 ・凍結の guard を弱めない。
- **本 gate の変更**: 本文書 ・CHANGELOG ・文書の境界の guard（registry への文書の登録 ＋ 文書の必須の節 ・private の形の走査）だけ。
- **P12.5-A0 の closeout の基準**: 本文書が監督に承認される ・guard が通る ・全 test suite が緑 ・`src/` の差分が無い ・private の形が文書に
  無い。これで P12.5-A0 は閉じるが、**P12.5 全体 ・P13 ・P14 は閉じない**。
- **実装の gate（P13）の順序の提案**: A1 memory model（純粋）→ A2 governed adapter（read-only ・合成の世界）→ A3 store と rebuild →
  A4 projector と vault の方針 → A5 実機の read-only 検証 → A6 freeze record。各 gate は狭い commit ・registry ・guard を P8 〜 P12 の様式で足す。
  Phase 4 〜 12 の A-track は再開しない。
- 本文書の主張の範囲: 本文書は **設計の契約**であり、実装の存在 ・検証の完了 ・運用の可否のいずれも主張しない。
