# PHASE 8 / P8-A1R — IDENTITY REMEDIATION CONTRACT（訂正 ＋ 遡及の解決）

Phase 8 の identity の authority に、追記専用の訂正と、2 つの時間軸の解決を足す契約。**A1 ／ A2 の runtime は 1 byte も変えない
拡張**で、合成 data だけで検証した。実の identity の登録 ・bootstrap の実行 ・J-Quants ・screen ・指標 ・Theme ・LLM は無い。

- runtime（新規）: `src/intelligence/screener_intelligence/identity_correction_model.py` ・`identity_correction_store.py` ・
  `identity_remediation_resolver.py`
- test: `tests/intelligence/test_screener_identity_remediation.py`（A〜BS）・`tests/intelligence/test_screener_intelligence_boundary.py`
  （A1R の境界 ／ 凍結）・`tests/intelligence/phase8_runtime_registry.py`（A1R の完全一致の path と P8-VR の anchor）
- 基準: P8-VR `7b8d375`、P8-V `fc91ee1`、P8-A2.5 `5713a56`、P8-A2 `b686b00`、P8-A1 `4162e9c`。A1 の runtime は `4162e9c` と、A1 ／ A2 の
  runtime と先行の Phase 8 の文書は `7b8d375` と byte 一致。

---

## 1. 目的

2 つの別の問題を解く。

- **訂正**: authority の record が後で誤りと分かる。履歴を書き換え ／ 消さずに、無効化 ／ 置き換えを追記する。
- **遡及の解決**: authority は、分析する過去の市場の出来事より後に作られ得る。「過去の時刻 T に system が知っていた事」と
  「後で選んだ審査済みの authority の版が、時刻 T について言う事」を区別し、黙って混ぜない。

A1 の原則は保つ: IssuerId ≠ SecurityId、code は安定の identity ではない、追記専用、明示の PIT、あいまい一致なし、黙った統合なし、
壊す修復なし、暗黙の latest ／ now なし、過去の record は見られるまま。

## 2. 2 つの時間軸

| 軸 | 意味 | どこにあるか |
|---|---|---|
| 有効時間（world ／ effective） | identity の事実が外の世界で成り立った時刻 | A1 の `effective_from` ／ `effective_to`（登録は全期間） |
| authority の知識の時刻（authority ／ knowledge） | Phase 8 の authority がそれを知った ／ 受け入れた時刻 | A1 の `provenance.known_at`、訂正の `accepted_at` |

例: 2024 年に上場した Security を、authority は 2026 年に初めて知る。2 つの時刻は矛盾しない。1 つにまとめない（test E）。

## 3. 解決の mode

`ResolutionMode` は閉じた 2 値: `STRICT_KNOWLEDGE`（既定）・`RETROSPECTIVE_AUTHORITY`。STRICT から RETROSPECTIVE への暗黙の
切り替えは無い（引数の組が合わなければ `MODE_PARAMETER_MISMATCH`）。mode の値は enum だけ（文字列は `INVALID_MODE`）。

## 4. STRICT_KNOWLEDGE

- 引数は `cutoff`（aware の datetime。無い ・None ・文字列 ・naive は fail closed）だけ。
- `cutoff` までに知られた A1 の record と `accepted_at <= cutoff` の訂正だけで authority の像を作り、有効時間 `cutoff` を解く。
- 訂正が無ければ、結果の `identity` は凍結の A1 の `resolve(history, query, cutoff=cutoff)` と byte 一致（test AV ・data root でも）。

## 5. RETROSPECTIVE_AUTHORITY

- 引数は `effective_at`（過去の有効時間）と `authority_as_of`（選んだ後の authority の知識の cutoff）の**両方が必須**。無ければ
  `EFFECTIVE_AT_REQUIRED` ／ `AUTHORITY_AS_OF_REQUIRED`（data root を読む前に止める）。`authority_as_of < effective_at` は
  `RETROSPECTIVE_REQUIRES_LATER_AUTHORITY`。
- 結果は必ず遡及と印される: `mode = RETROSPECTIVE_AUTHORITY`、`retrospective = true`、`interpretation =
  ACCORDING_TO_THE_SELECTED_LATER_REVIEWED_AUTHORITY_VIEW_NOT_A_TRUTH_CLAIM`。
- **遡及は事実を意味しない**: 「選んだ後の審査済みの authority の像によれば」であって「客観的な過去の事実」ではない。事実の主張をしない。

## 6. authority_as_of

「今ある authority を使う」は無い。呼び手が時刻を明示し、その時刻までに知られた record と訂正だけが像に入る。未来の append
（`known_at` ／ `accepted_at` が `authority_as_of` より後）は像に入らない（test AN）。

## 7. authority の版

- `authority_version = content_id("p8idv", canonical_json({像を作った A1 の record id の列（journal 順）, 訂正の id の列（journal 順）,
  A1 の schema ・規則の版, 訂正の schema の版, 像の規則の版}))`。
- 同じ bytes → 同じ版（record id は正準の行の内容の hash）。像に入る append → 別の版。path ・mtime ・時計 ・乱数 ・hash の seed に
  依らない（test AH〜AL）。
- 下流の再生は `expected_authority_version` で版を固定できる。違えば `AUTHORITY_VERSION_MISMATCH`（identity の結果を返さない）。
  `authority_as_of` が journal の末尾より先にあり、後から `authority_as_of` 以前の record が append された場合も、版の固定で検知する。

## 8. 訂正の record

原始の record は 2 種類だけ（`IdentityCorrection`。追記専用 ・不変 ・内容 address `p8idc_…`）:

| action | 意味 | 置き換え |
|---|---|---|
| `INVALIDATE_RECORD` | 対象を、訂正を知った以後の authority の像から外す | 無い |
| `SUPERSEDE_RECORD` | 対象を、明示の置き換えの claim で替える | 対象ごとに 1 つ（A1 の record の型） |

field: `action` ・`reason`（閉じた語彙）・`targets`（A1 の record id、1〜16、重複なし）・`replacements` ・`review`（§16）・
`accepted_at`（authority の知識の時刻、`review.reviewed_at` 以後）。`CORRECT_MAPPING` は SUPERSEDE で表せるので別の種類にしない。
`MERGE_IDENTITY` ・`SPLIT_IDENTITY` は作らない（§14 ・§15）。

理由の語彙: `WRONG_ISSUER_MAPPING` ・`WRONG_ISSUE_CLASS` ・`WRONG_IDENTIFIER_VALUE` ・`WRONG_EFFECTIVE_INTERVAL` ・`WRONG_CONTINUITY` ・
`DUPLICATE_IDENTITY` ・`WRONG_DISPLAY_NAME` ・`WRONG_COVERAGE` ・`NOT_SUPPORTED_BY_EVIDENCE`。自由記述は持たない。

## 9. 無効化

古い record は消えない（A1 の journal はそのまま。訂正は別の journal）。無効化を知る前の STRICT の問い合わせは古い結果を再現する
（test J は byte 一致）。知った後の STRICT と、後の版を選んだ遡及の問い合わせは無効化を適用する（test K ・L）。依存する record
（例: 登録を参照する割り当て）が残って像が A1 の不変条件に反すれば、訂正は拒否される（依存も明示で無効化する）。

## 10. 置き換え

- 置き換えは明示の対象を要し、対象と同じ種類（`CROSS_KIND_CORRECTION`）。登録の置き換えは同じ id を保つ
  （`IDENTITY_CHANGE_NOT_ALLOWED`）。置き換えの出所は `HUMAN_REVIEWED`、`known_at` は `accepted_at` と同じ。
- 像では置き換えが対象の位置に入る（依存の順を保つ）。Issuer の登録 → Security の登録 → その他の順に並べ、同じ段の中は journal の
  位置の順で、A1 の不変条件（参照 ・重なり ・分岐 ・継続の権限 ・登録の衝突）で検査し直す。
- **append の順で「最新が勝つ」ことは無い**: 1 つの対象を訂正できるのは 1 回だけ（2 つ目は `CONFLICTING_CORRECTION`）。訂正の訂正は
  置き換えの record を対象にする（明示の鎖。test N）。

## 11. Security → Issuer の対応の訂正

`SecurityRegistration` の置き換え（同じ anchor ＝ 同じ SecurityId、直した `issuer_id`）。対象 ・置き換えの claim ・受理の時刻を持つ。
有効の範囲は登録の全期間（登録は時間で変わらない claim。日付で分けた付け替えは企業の再編で、訂正ではない）。SecurityId は変わらず、
元の IssuerId は traceable のまま（test T〜V）。

## 12. 識別子の割り当ての訂正

誤った値 ・誤った有効期間 ・誤った継続を、元の割り当てを変えずに置き換える。期間の訂正は終わりの record と始まりの record を 1 つの
訂正で一緒に置き換える（片側だけで重なれば `CORRECTION_BREAKS_AUTHORITY`。test X）。訂正の前の STRICT は古い割り当て、後は
直した割り当て、遡及は選んだ版の割り当て（test Y 〜 AA）。

## 13. 継続

継続の record の種類は足さない。A1 は既に、同じ Security の 2 本目の識別子と再上場に継続の出所（取引所 ・発行体の開示 ・人の審査）を
要する。A1R では、誤って別にした継続 ／ 誤って立てた継続を、人の審査の置き換え（`WRONG_CONTINUITY`）で直す（test AD）。継続は
名前 ・code の形 ・事業の説明から推し量らない（test AB ・AC）。

## 14. 統合の方針

- 統合は暗黙に起きない（同名の Issuer は別。test AE）。訂正で IssuerId ／ SecurityId を変えられない。
- 誤って 2 つ作った IssuerId は、原始の訂正で直せる: 重複した Issuer の Security の登録を正しい Issuer へ置き換え、重複した Issuer の
  登録を無効化する。元の id は journal に残り、訂正の前の STRICT で見える。
- 別名 ・転送（古い IssuerId の問い合わせを正しい id へ導く）を持つ `MERGE_IDENTITY` は、A1R の範囲より広いので延期する（P8-OBS-44）。
- 鎖は元の record へ戻れない（`CORRECTION_CYCLE`。test R ・AF）。戻したい時は新しい claim を明示で出す（別の record id）。

## 15. 分割の境界

データの取り違えの訂正と、実の企業の再編（spin-off ・会社分割）を分ける。訂正の語彙に分割 ・spin-off は無く、登録の訂正は全期間に
効く（日付で分けられない）。再編は後の別の model の仕事（test AG）。

## 16. 人の governance

- 訂正の authority を作れるのは `ReviewerClass.HUMAN` だけ（`MACHINE` は `REVIEWER_NOT_AUTHORIZED`。store に紛れても破損として止まる）。
- machine ／ adapter ／ LLM は将来、訂正の候補を**提案**できるが、authority は作れない。提案の仕組みは A1R に無い。
- 合成の test では人の審査の record を fixture として作る。

## 17. 出所

`CorrectionReview`: `reviewer_class`（HUMAN）・`reviewed_at` ・`evidence`（1〜8 件の `ReviewEvidence`: 出所の class ・有界の参照
（`/`・空白なし ・160 文字まで）・任意の sha256）。個人の審査者の identity ・自由記述 ・raw の payload は持たない（未知の field は
`UNKNOWN_FIELD`、payload の形の参照は `INVALID_EVIDENCE_REF`、認証情報に見える語は `CREDENTIAL_LIKE_TEXT`）。

解決の結果は、mode ・有効時間 ・authority_as_of ・版 ・使った authority の record（A1 の record ・置き換え ・関わる訂正）・訂正の鎖
（訂正 ・action ・理由 ・対象 ・置き換え ・受理 ・審査者の種類 ・審査の時刻 ・証拠の参照）・有界の status を持つ（test AO）。
下流の過去の screen は「市場の日 X を、Y までに受け入れた identity の authority（版 V）で解いた」と言える。

## 18. 訂正の鎖

決定論。拒否するもの: 対象の欠落（`MISSING_TARGET`）・未来の対象（`FUTURE_TARGET`）・自己（`SELF_TARGET`）・循環
（`CORRECTION_CYCLE`）・競合（`CONFLICTING_CORRECTION`）・重複の対象 ／ 置き換え ・種類の違い（`CROSS_KIND_CORRECTION`）・id の変更
（`IDENTITY_CHANGE_NOT_ALLOWED`）・受理の時点で A1 の不変条件を破る訂正（`CORRECTION_BREAKS_AUTHORITY`）・`accepted_at` の逆行
（`NON_MONOTONIC_ACCEPTED_AT`）。

## 19. coverage

遡及は coverage を迂回しない。選んだ版の像が有効時間を覆う coverage を持たなければ fail closed（`BEFORE_COVERAGE` ／
`OUTSIDE_COVERAGE` ／ `NOT_YET_KNOWN`）。coverage の record も訂正できる（無効化すれば覆われない）。現在の master で任意の過去を埋めない
（test AT ・AU）。

## 20. status

`RemediationStatus` ＝ A1 の 9 値（FOUND ・NOT_FOUND ・NOT_YET_KNOWN ・NOT_ACTIVE_AT_CUTOFF ・AMBIGUOUS ・BEFORE_COVERAGE ・
OUTSIDE_COVERAGE ・AUTHORITY_MISSING ・STORE_CORRUPTION）＋ `CORRECTION_CONFLICT`（像が A1 の不変条件に反する）＋
`AUTHORITY_VERSION_MISMATCH`。要求の違反は例外（`RemediationRequestError`）で、既定に落とさない。A1 の journal の欠落 ／ 破損、訂正の
journal の欠落（`CORRECTIONS_MISSING`）／ 破損は status として返し、空の成功にしない。

## 21. A1 との互換

- A1 の 4 module は `4162e9c` と byte 一致。A1 の record の型 ・検査 ・直列化 ・resolver をそのまま使う。
- 拡張だけで実装できる理由: A1 の `resolve` は知識を `history.known_by(cutoff)` だけで扱う。A1R の像（`PinnedAuthorityView`。
  `IdentityHistory` の subclass）は知識を固定して `known_by` で自身を返し、journal の append の順の規則（`known_at` の非減少）だけを
  持たない。A1 の他の不変条件の検査はすべて再利用する。よって A1 の変更は不要で、新しい identity の凍結の anchor も要らない。
- 訂正の無い authority では、STRICT の結果は A1 と byte 一致（test AV: A1 の年表の 15 の問い合わせ × 11 の cutoff、pure と data root）。
  code の再利用 ・上場廃止 ・複数の Security の意味も同じ（test AW〜AY）。

## 22. A2 の境界

- A2 の runtime は変えない（`b686b00` と byte 一致）。A2 の主語の検査は凍結の A1 の STRICT の解決（A1 の journal）をそのまま使い、
  通常の運用ではこれでよい。A2 を黙って遡及にしない。
- 訂正は A2 の観測を書き換えない。観測は SecurityId に付いたまま。発行体の読み方は、選んだ identity の authority の像を通して変わる
  （test W ・BA ・BB）。観測の自動の移行はしない。
- 将来の過去の screen の組み立ては、先に A1R で identity を解き（版を記録 ・固定）、それから A2 に問い合わせる。A2 の主語の受理は
  A1 の journal の水準で、訂正（無効化した登録 ・直した上場の期間）を見ない（P8-OBS-42）。

## 23. bootstrap への引き継ぎ

将来の流れ: 出所の証拠 → machine の bootstrap 候補 → 人の審査 → identity の authority → 必要なら訂正。A1R は候補の生成も J-Quants の
取り込みもしないが、審査済みの bootstrap の決定を受け取れる: 後から作る authority は RETROSPECTIVE で過去を解け（版で固定）、誤りは
原始の訂正で直せる。data から計算した anchor は使わず、bootstrap の一括で一度だけ割り当てる（P8-OBS-29 の方針）。

## 24. store

訂正は別の journal `<data_root>/screener_intelligence/identity_corrections.jsonl`。分けた理由: 凍結の A1 の store は A1 の record 以外を
受け付けず（同じ file では A1 の読み込みが破損として止まる）、A1 の journal を A1 の再生のためにそのまま保つため。規律は A1 と同じ:
明示の data_root、正準の行だけ、write → flush → fsync、同じ訂正は収束、破損 ／ 非正準 ／ 切断 ／ 空行 ／ 重複 ／ 鎖の違反は fail closed
（読み飛ばし ・修復 ・削除なし）、byte 長で外部の変更を検知、read-only で何も書かない、SQLite なし。初期化は A1 の authority が先に
在ることを要する。append は最新の A1 の journal に対して、受理の時点と両 journal の全体の像の両方で検査する。A1 の journal への後の
append は訂正を知らないので、訂正と矛盾する像は `CORRECTION_CONFLICT` として止まる（P8-OBS-43）。

## 25. security

合成の identity だけ（架空の anchor ・code ・名前）。実在の code ・社名 ・J-Quants ・network ・credential ・LLM は無い。証拠の参照は有界で、
raw の payload ・path ・URL ・認証情報を持てない。審査者の個人の identity は不要で、持たない。
A1R が新しく足す合成の code は先頭が `Z` の 5 文字（例 `Z0016`）にする。取引所の code は先頭が数字で `Z` を使わないので、
実在の code と形の上で重ならない（凍結の A1 の fixture の数字だけの code は変えない。P8-OBS-47）。

## 26. 規約 ／ 削除の境界

P8-OBS-41 を引き継ぐ。A1R は authority の record の削除を実装しない。identity の authority は許諾された市場の raw の payload を要さず、
訂正は有界の出所 ／ digest だけを持つ。適用される規約が provider の data の削除を求める場合、それは将来の出所 ／ snapshot の層で扱う。
追記専用の identity の authority を先回りで弱めない。

## 27. 延期する事

- 別名 ・転送つきの `MERGE_IDENTITY`（P8-OBS-44）、企業の再編の model、訂正の候補の提案の仕組み。
- A1 の journal への append を訂正に対して検査する組み立ての writer（P8-OBS-43）。
- A2 の主語の検査を A1R の像で行う選択（P8-OBS-42）。
- 実の bootstrap の実行、発行体の識別子の scheme、Light の master の過去日の意味の確認（LUV-25 ・26）。

## 28. 凍結の方針

- A1R の runtime は `tests/intelligence/phase8_runtime_registry.py` の `PHASE8_A1R_RUNTIME`（完全一致の 3 path）に登録した。Phase 6 ／ 7 の
  guard は registry を通して読む（Phase 6 ／ 7 の test は無変更）。
- A1 ／ A2 の runtime と先行の Phase 8 の文書（A1 ・A2 ・A2.5 ・P8-V ・P8-VR）は `7b8d375` と byte 一致（guard）。
- 以後の gate は A1R の module と本書を凍結の対象として扱う（監督の宣言の anchor に従う）。

---

## 付録: 所見

引き継ぐ所見の状態（real data の検証まで CLOSED にしない）:

| id | 所見 | A1R の後 |
|---|---|---|
| P8-OBS-10 | identity の訂正 ／ 統合の record が無い | STRUCTURALLY_ADDRESSED（原始の訂正。別名つきの統合は延期） |
| P8-OBS-11 | 遡及の mode が無い | STRUCTURALLY_ADDRESSED（RETROSPECTIVE_AUTHORITY と版の固定） |
| P8-OBS-18 | identity の知識の時刻の食い違い | STRUCTURALLY_ADDRESSED（2 軸を分け、遡及を明示の mode にした） |
| P8-OBS-29 | bootstrap の authority の穴 | STRUCTURALLY_ADDRESSED（審査済みの決定を受け取り、後で直せる）。実の bootstrap は未実行 |
| P8-OBS-12 | 実の登録の手順 | 将来の bootstrap の実行に依存（変わらず） |
| P8-OBS-41 | 規約が削除を求める場合の store | 条件つきの規約の仕事（変わらず。§26） |

新しい所見は P8-OBS-42 から（最終報告に分類を記す）: 42 A2 の主語の受理は訂正を見ない、43 A1 の journal への append は訂正に対して
検査されない、44 別名 ・転送つきの統合の延期、45 版を固定しない遡及の再生は後の append で変わり得る、46 登録の無効化は依存の明示の
無効化を要する（運用の負担）、47 凍結の A1 ／ A2 の test の数字だけの合成の code は 5 桁の実の形と重なり得る（照合はしていない。
A1R の新しい code は `Z` で始めて重ならないようにした。A1 の test は凍結なので変えない）。
