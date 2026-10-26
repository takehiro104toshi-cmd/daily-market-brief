# M0-D1: MOBILE SECURITY AND ACCESS CONTRACT（文書だけ ・本記録は実装を承認しない）

監督が設計の水準で固定した M0 の決定（H1 の脅威 model ・platform ・認証 ・保存 ・network ・等級ごとの表示 ・fail closed ・browser の証拠）を、
守られた文書だけの記録として残す。本記録は実装を承認しない。合成の data だけを扱い、実の data ・実の source ・private な root への接続は無い。
H1 ・M1 ・deploy は HOLD。

| 項目 | 値 |
|---|---|
| gate | `M0-D1`（文書 ・registry ・guard だけ） |
| 基準の HEAD | `69fb4396a797566b2b70f435721892f9e096344f`（H0-D1 の commit） |
| 前提の記録 | `docs/databank/H0_D1_HOME_INFORMATION_CONTRACT.md`（blob `ce5fbce76b30b700c58b619452fbf8f1433c3c81` ・本記録は変えない） |
| 端末の payload | `home_client:0.2-synthetic`（H0-D1 §4 の投影。内部の `home_snapshot:0.2-synthetic` は端末に渡さない） |
| digest の domain | `home.snapshot.v0.2` ・`home.client.v0.2`（H0-D1 §11。表示の方針の識別子 `h0_render_policy:0.1` とは別の物） |
| 状態 | 本記録は実装を承認しない。H1 ・M1 ・S0-D1 ・UI0 ・H0-D2 の記録は監督の別の承認まで HOLD |

## 1. 範囲と主張しないこと

- 本記録は、合成の data だけの H1 prototype が端末で何を表示 ・保存 ・送信してよいか、どう fail closed するかの契約だけを書く。
  実装 ・browser の実行 ・CDP の client ・fixture の生成 ・hosting ・認証の実装 ・deploy を承認しない。
- 合成の data だけ。実の金融の data ・実の source ・private な root への access は無い。
- 本記録は OS の水準の隔離を主張しない。CSP だけで隔離を証明したとは主張しない。browser の中で暗号の検証を行うとは主張しない。
- H0-D1 の契約（項目 ・状態 ・表示の集約 ・時刻 ・等級 ・禁止）を再定義しない。H0-D1 の記録の byte は変えない。
- scenario の意味は S0-D1 が持つ。項目ごとの正確な key と上限は H0-D2 が持つ（§19）。表示の設計は UI0 が持つ。

## 2. 再利用する契約

- roadmap の記録 §22（M0 の範囲: 脅威 model ・認証の方式 ・端末の紛失 ・等級ごとの可否 ・browser の保存の方針。H1 は H0 と M0 を要する）。
- roadmap の記録 §24（凍結の P11 の transport は mobile に使えない。再利用できるのは防御の様式だけ）・§25（privacy ・権利 ・mobile ・deploy は独立の gate）。
- H0-D1 §4（封筒）・§5（表示の集約 `h0_render_policy:0.1`）・§6（時刻）・§7（8 つの状態と後継）・§10（等級）・§11（digest）・§12（合成の印）・§14（禁止）。
- P11 の防御の様式（storage を使わない ・inline を許さない CSP ・`textContent` だけの描画 ・鍵の集合の完全一致 ・失敗の時の消去 ・明示の時点）。
  凍結の P11 の runtime は import しない ・変えない。
- P13-A1 の `src/intelligence/market_memory/canonical.py`（`canonical_json` ・`domain_digest`）。試験の時に import して使い、複製しない。
- P8 の `KnowledgeTime` の意味（H0-D1 §6 が採る）。

## 3. H1 の脅威 model

| # | 脅威 | 対処 |
|---|---|---|
| 1 | 実の data が fixture ・asset に入る | `synthetic` が true でない ・`syn_` でない id ・架空 ／ 合成 で始まらない label を拒む ・private な形の走査 |
| 2 | prototype を実の市場の情報と取り違える | 全ての画面に「合成データ・投資判断に使えない」の watermark ・日付は 2099 年 |
| 3 | 誤って公開の面に載る | 公開の面が参照しない専用の path ・boundary の guard ・Pages ・Cloudflare ・artifact に出さない |
| 4 | network の利用 ・第三者の読み込み | CSP の `connect-src 'none'` ・外部の font ・CDN ・analytics は無い ・静的な走査 |
| 5 | browser に data が残る | 保存と cache の API を禁じる ・一時の profile |
| 6 | fixture の文字列による XSS | 閉じた schema ・有界な欄の形 ・template ・`textContent` だけ |
| 7 | 資格情報 | 存在しない ・server を使う場合は資格情報の変数が在れば起動を拒む |
| 8 | LAN への露出 | LAN に配らない ・listener は無い（`file://`） |
| 9 | 禁止の意味が UI に入る | H0-D1 §14 の禁止の欄 ・語を検証器が拒む |
| 10 | H1 を M1 の準備と取り違える | H1 が主張しないことの明示（§18） |

- 受け入れた境界: 完全に侵害された OS ・browser ・拡張は守る範囲の外（P11-OBS-074 と同じ）。
- 本記録は脅威の対処を「観測した」と言えるだけで、OS が「強制した」とは言わない。

## 4. 実行の platform

- H1 は `file://` から開く 1 つの file `index.html`（素の HTML ・CSS ・JS ・build の道具は無い）。
- script と style は inline で、CSP の hash で覆う。fixture は `<script type="application/json">` の data の block として埋め込み、browser は実行しない。
- 画像 ・icon ・web font ・manifest ・service worker は無い。install できる PWA ではない。
- browser は Edge。実行ごとに新しい一時の専用の profile（repository と fixture の外）を使い、sync ・拡張 ・背景の network ・component の更新 ・既定の app を無効にする。
- 検証は desktop の browser の iPhone の大きさの viewport（375×812 と 430×932 CSS px ・pixel 比 3）で行う。実機の iPhone ・Safari ・WebKit は検証しない。
- listener ・port ・Host の検査 ・HTTP の cache は無い（`file://` なので HTTP の応答が無い）。
- CDP の transport は pipe（`--remote-debugging-pipe`）を H1 の設計の優先とする。実装の前の feasibility の試験を要し、本記録は検証済みとは主張しない。
  debugging port の transport への fallback は監督の別の承認を要する。
- native か PWA かの決定は M1 に延期する。

## 5. 認証と資格情報

- H1 に認証は無い。account ・password ・token ・OAuth ・session は無い。
- 合成の data に秘匿の価値は無く、PC の外に配るものも無い。
- server を使う場合（本記録は承認しない）は、資格情報の変数が在れば起動を拒む（P11-A2 の先例）。
- 認証の方式（passkey ・端末の束縛）・hosting ・TLS ・revocation ・keychain は M1 の範囲（§18）。

## 6. 保存

| API ・場所 | H1 での扱い |
|---|---|
| localStorage | 禁止 |
| sessionStorage | 禁止 |
| IndexedDB | 禁止 |
| cookie | 禁止 |
| Cache Storage | 禁止 |
| service worker | 禁止 |
| URL ・history の state | 禁止 |
| memory の変数 | 読み込みごとに fixture を読み直す ・失敗で参照を消す |

- 保存の API は静的な走査で禁じ、実行の後に DOM storage ・IndexedDB ・Cache Storage ・service worker ・`file` origin の cookie が空であることを確かめる。
- browser の vendor 自身の cookie は範囲外とし、件数だけ記録する（P11-OBS-072 と同じ）。
- memory の消去は参照を無くすだけであり、process の memory の消去は保証しない。

## 7. network と CSP

| 指令 | 値 |
|---|---|
| default-src | 'none' |
| script-src | 'sha256-…'（inline の script の hash だけ） |
| style-src | 'sha256-…'（inline の style の hash だけ） |
| connect-src | 'none' |
| img-src | 'none' |
| font-src | 'none' |
| media-src | 'none' |
| object-src | 'none' |
| frame-src | 'none' |
| worker-src | 'none' |
| manifest-src | 'none' |
| base-uri | 'none' |
| form-action | 'none' |

- CSP は `<head>` の最初の要素の `<meta>` で与える。`file://` では self の source が使えないので hash を使う。
- 加えて `<meta http-equiv="x-dns-prefetch-control" content="off">` を置く。
- 禁止の API（静的な走査で 0 件）: `fetch` ・`XMLHttpRequest` ・`WebSocket` ・`EventSource` ・`sendBeacon` ・`Worker` ・`serviceWorker` ・
  `importScripts` ・`localStorage` ・`sessionStorage` ・`indexedDB` ・`caches` ・`document.cookie` ・`console` ・`innerHTML` ・`outerHTML` ・
  `insertAdjacentHTML` ・`eval` ・`Function` ・`location` ・`open` ・`RTCPeerConnection`。
- 禁止の要素 ・属性: `<a href>` ・`<link>` ・`<img>` ・`<iframe>` ・`<form>` ・`<base>` ・`http:` ・`https:` ・`ws:` ・`wss:` の URL ・`//` で始まる URL ・属性の `data:`。
- browser の起動の flag: 全ての DNS を失敗させる（`--host-resolver-rules="MAP * ~NOTFOUND"`）・全ての HTTP を死んだ local の proxy へ送る
  （`--proxy-server=127.0.0.1:9`）・WebRTC の直接の UDP を無効にする ・背景の network ・component の更新 ・sync ・拡張を無効にする。
- 限界（明示）: CSP は page だけを縛り、top-level の navigation ・DNS prefetch ・WebRTC ・browser 自身の通信を縛らない。`<meta>` の CSP は
  `frame-ancestors` と sandbox を表せない。flag は browser 自身の通信を失敗させるが、無いことを証明しない。OS の水準の隔離は無い。

## 8. 等級ごとの表示

| 等級 | 端末での扱い |
|---|---|
| PUBLIC_SAFE | 出す |
| PRIVATE_DERIVED | 出す ・「非公開表示（合成）」の badge を付ける |
| PRIVATE_AUTHORITY | fixture は無効 ・snapshot 全体を fail closed |
| NEVER | fixture は無効 ・snapshot 全体を fail closed |

- 等級の語彙と項目の上限は H0-D1 §10 のもの。本記録は等級を足さない ・変えない。
- screenshot は合成の watermark つきの時だけ許し、人の審査のためだけに残す。

## 9. 端末の payload と識別

- 端末が受け取るのは `home_client:0.2-synthetic` だけ。schema の版の文字列は完全一致で検査し、他の版は拒む。
- digest の domain は `home.snapshot.v0.2`（内部）と `home.client.v0.2`（投影）。`h0_render_policy:0.1` は表示の方針の識別子であり、digest の
  domain ではない。
- 完全性の検査は試験の時に行う: 保存した byte と `canonical_json` の byte の一致 ・`domain_digest` と最上位の `digest` の一致 ・pin した fixture の
  許可の一覧（`fixture_id` と digest）・`index.html` の git の blob の pin。P13 の code を import して使い、複製しない。
- browser は暗号の検証を行わない。`fixture_id` と digest を label として表示するだけ。local の file の改変を実行の時に検出できないことを明示し、
  検出は試験と blob の pin に委ねる。
- Unicode は NFC であることを検査し、正規化はしない（非 NFC は拒む）。
- 本記録は runtime の digest の実装を含まない。

## 10. 時刻

- 入力の瞬間は UTC の正準の形 `YYYY-MM-DDTHH:MM:SS+00:00` だけ（H0-D1 §6 と同じ）。日は `YYYY-MM-DD`。
- 拒む形: `Z` の接尾 ・小数の秒 ・空白の区切り ・UTC の offset の欠落 ・0 でない offset ・暦として不正な値 ・2099 年でない合成の日時。
- 報告の順は 形 → 暦 → 年: 形の不正は TIME_FORMAT_INVALID、形は正しいが暦として不正な値は TIME_CALENDAR_INVALID、形も暦も正しいが 2099 年でない値は
  SYNTHETIC_YEAR_INVALID として報告する。文字列でない値は時刻の検査に届かず TYPE_MISMATCH（§12 の順）。
- parse は正規表現と整数の算術だけで行う。JavaScript の `Date` による parse は使わない。
- 表示は JST（UTC に 9 時間を足す算術）で行い、時間帯を明示する。相対の表現（「○分前」）は使わない。
- `as_of` の見出しは常に表示する。時刻の適格（`known_at` ・`acquired_at` ・`as_of`）の意味は H0-D1 §6 のまま。

## 11. 表示の状態と fail closed

- 項目の表示の状態は H0-D1 §5 の `h0_render_policy:0.1` の 5 つ（SUPPRESSED ・EMPTY ・UNAVAILABLE ・PARTIAL ・AVAILABLE）。本記録は状態を足さない ・
  方針を変えない。
- entry の 8 つの状態の印と後継の規則（SUPERSEDED は出さない ・後継は同じ項目に在る ・後継が無ければ MISSING（`SUCCESSOR_MISSING`）・前の版を
  代わりに示さない）は H0-D1 §7 のもの。
- 検証は描画の前に行う。1 つでも失敗すれば、画面には §12 の code だけを出し、前の表示と memory の参照を消す。部分の描画は無い。
- INTEGRITY_FAILURE が在れば `snapshot_status` は FAILED_CLOSED であり、全ての項目は SUPPRESSED。
- INTEGRITY_FAILURE の entry が在るのに `snapshot_status` が OK なら STATE_RECOMPUTE_MISMATCH（入力の拒否）。`snapshot_status` が FAILED_CLOSED の
  有効な fail closed の結果（SNAPSHOT_FAILED_CLOSED）は、該当する入力と整合の検証が全て通った後にだけ認める。
- offline ・読み込みの失敗の時も、古い data を今のものとして見せない。

## 12. 失敗の code

端末の検証と描画の失敗の code は次の閉じた集合だけ。code は `[A-Z_]` の文字列で、値 ・本文 ・path を含まない。

| code | 意味 |
|---|---|
| FIXTURE_BLOCK_INVALID | fixture の block が無い ・JSON として読めない |
| SCHEMA_VERSION_MISMATCH | `schema_version` が `home_client:0.2-synthetic` でない |
| UNKNOWN_KEY | 閉じた key の集合の外の key |
| MISSING_KEY | 必須の key の欠落 |
| TYPE_MISMATCH | 値の型が契約と違う |
| BOUND_EXCEEDED | 大きさ ・長さ ・入れ子 ・項目ごとの entry の件数の上限の超過（6 つの項目の数 ・順 ・重複は ITEM_ORDER_INVALID） |
| NOT_NFC | 文字列が NFC でない |
| NOT_SYNTHETIC | `synthetic` が true でない |
| SYNTHETIC_ID_INVALID | id が `syn_` で始まらない ・`fixture_id` が `syn_fx_` で始まらない |
| SYNTHETIC_LABEL_INVALID | label が 架空 ／ 合成 で始まらない |
| SYNTHETIC_YEAR_INVALID | 日時が 2099 年でない |
| TIME_FORMAT_INVALID | §10 の形でない |
| TIME_CALENDAR_INVALID | 暦として不正 |
| AFTER_AS_OF | `acquired_at` または `issued_at` が `as_of` より後 |
| ITEM_ORDER_INVALID | 6 つの項目の数 ・順 ・重複が契約と違う |
| FORBIDDEN_FIELD | H0-D1 §14 の禁止の欄 |
| FORBIDDEN_WORD | H0-D1 §14 の禁止の語 ・表示の文の確信の語 |
| GRADE_FORBIDDEN | PRIVATE_AUTHORITY ・NEVER の data が在る |
| GRADE_CEILING_EXCEEDED | 項目の等級の上限を超える |
| STATE_RECOMPUTE_MISMATCH | 宣言した状態と再計算が違う ・INTEGRITY_FAILURE の entry が在るのに `snapshot_status` が OK |
| RENDER_STATE_MISMATCH | 宣言した表示の状態と再計算が違う |
| COVERAGE_MISMATCH | coverage と再計算が違う |
| REFERENCE_UNRESOLVED | 後継 ・宣言した鮮度の窓 ・証拠の参照が snapshot の中で解けない |
| SUCCESSOR_CYCLE | 後継の鎖が循環する |
| CLAIM_RULE_VIOLATION | FACT ／ HYPOTHESIS の規則の違反 |
| SNAPSHOT_FAILED_CLOSED | `snapshot_status` が FAILED_CLOSED（有効な fail closed の結果 ・全ての項目は SUPPRESSED ・入力の拒否ではない） |
| RENDER_ABORTED | 描画の途中の例外（表示を消して止める） |

- 分類: A. 入力の不正 ・検証の拒否 25 ・B. 有効な fail closed の結果 1（SNAPSHOT_FAILED_CLOSED）・C. 描画の失敗 1（RENDER_ABORTED）・計 27。
- 検証の順（決定論。段の中は列挙の順。検証の段（1 〜 10）は最初に当たった失敗で止める）:
  1. 解析: FIXTURE_BLOCK_INVALID
  2. 封筒と構造: SCHEMA_VERSION_MISMATCH ・NOT_SYNTHETIC ・UNKNOWN_KEY ・MISSING_KEY ・TYPE_MISMATCH ・BOUND_EXCEEDED ・NOT_NFC
  3. 合成の識別: SYNTHETIC_ID_INVALID ・SYNTHETIC_LABEL_INVALID
  4. 時刻: TIME_FORMAT_INVALID ・TIME_CALENDAR_INVALID ・SYNTHETIC_YEAR_INVALID ・AFTER_AS_OF
  5. 項目: ITEM_ORDER_INVALID
  6. 語彙: FORBIDDEN_FIELD ・FORBIDDEN_WORD
  7. 等級: GRADE_FORBIDDEN ・GRADE_CEILING_EXCEEDED
  8. 主張: CLAIM_RULE_VIOLATION
  9. 参照: REFERENCE_UNRESOLVED ・SUCCESSOR_CYCLE
  10. 再計算: STATE_RECOMPUTE_MISMATCH ・RENDER_STATE_MISMATCH ・COVERAGE_MISMATCH
  11. 有効な fail closed の結果: SNAPSHOT_FAILED_CLOSED
  12. 描画: RENDER_ABORTED
- 端末は最初に当たった失敗の code を 1 つだけ出す。同じ code の複数の違反は、契約が定めた欄の順と配列の順で決める（辞書の走査の順 ・browser の
  振る舞いに依らない）。試験は診断のために複数の違反を集めてよい。
- SNAPSHOT_FAILED_CLOSED は、該当する入力と整合の検証（1 〜 10）が全て通った後にだけ認める。FAILED_CLOSED の宣言は先の検証の失敗を覆さない。
- 参照の検査は snapshot の中で閉じる（外部の照会 ・network は無い）。H0-D1 の `SUCCESSOR_MISSING` は有効な MISSING の entry の理由であり、
  本記録の失敗の code ではない。
- digest ・許可の一覧 ・blob の不一致は試験の時の失敗であり、端末の code ではない（§9）。
- code の集合を広げる ・意味を変えるには、本記録の改訂と guard の更新を要する。

## 13. 合成の識別と watermark

- 合成の印: `synthetic` は true ・`fixture_id` は `syn_fx_` で始まる ・全ての id は `syn_` で始まる ・表示の label は 架空 か 合成 で始まる ・
  全ての日時は 2099 年 ・fixture の digest は pin した許可の一覧に在る。
- watermark「合成データ・投資判断に使えない」を全ての状態（通常 ・EMPTY ・UNAVAILABLE ・失敗の code の表示）で出す。watermark は固定で、
  他の要素で覆われない。
- 試験の時に private な形（path ・瞬間 ・5 桁の code ・id の接頭辞 ・資格情報の名前）を走査する。

## 14. browser の証拠

| 規則 | 要件 |
|---|---|
| N1 | page が始めた全ての request ・navigation ・WebSocket（CDP）は許可の集合 { pin した `file` の URL, `about:blank` } だけ。回数は問わない。他の URL は 0 |
| N2 | 失敗した読み込みは 0（失敗も試みである）・WebSocket ・EventSource の接続は 0 |
| N3 | 実行の間の CSP 違反の報告は 0。加えて正の control: hash の無い inline の script を 1 つ持つ変種が実行されないこと |
| N4 | 承認された場合だけ NetLog: 非 loopback への成功した接続 0 ・成功した DNS の解決 0。browser 自身の失敗した試みは件数と分類を報告し、隠さない |
| N5 | `index.html` の静的な走査: §7 の禁止の API ・要素 ・属性 ・URL の形が 0 件 |

- CDP は `about:blank` の tab に先に attach してから navigate し、読み込み ・操作 ・再読み込み ・60 秒の idle の間 attach したままにする。
- 文書の request は何度も報告されてよい。正確な回数は要件にしない。要件は認可の無い試みが 0 であること。
- 主張の文言: 「page が始めた認可の無い network の試みは観測しなかった。DNS と HTTP は browser の水準で失敗するよう設定した。OS の水準の隔離は無く、
  page の外の browser 自身の通信は完全には観測していない。」
- 一時の profile は試験の artifact であり、証拠は CDP の報告。profile の削除は監督の明示の承認の後だけ（既存の片付けの規則と同じ）。

## 15. 静的と実行時の保証

| 方法 | 保証すること | 保証しないこと |
|---|---|---|
| 静的な走査 | 禁止の API ・URL が書かれた code に無い | 実行の時の振る舞い |
| CSP | page の中の禁止の source を browser が止める | browser 自身の通信 ・拡張 ・navigation |
| CDP の観測 | その browser の版 ・その実行で観測した事実 | 全ての code の経路 ・browser の内部の通信 |
| DNS ・proxy の flag | その browser の process の試みを失敗させる | 試みが無いこと |
| OS の水準の閉じ込め | 無し | 無し |

- 検証しない事項: Safari ・WebKit ・実機の iPhone ・touch ・safe area ・iOS の Dynamic Type ・browser を閉じた後の memory。
- accessibility の自動の検査は使えることを証明しない。決定論はその browser の版についてだけ。

## 16. H1 の受け入れの契約（H1 の gate で課す ・本 gate では走らせない）

1. schema と data の契約（Python ・offline）: 正準の byte ・digest ・許可の一覧 ・blob の pin ・閉じた key と上限 ・適格と鮮度の再計算 ・coverage の再計算 ・
   FACT ／ HYPOTHESIS の規則 ・禁止の欄と合成の印 ・全ての壊れた fixture が §12 の code で拒まれる ・生成器が byte の一致で再生する。
2. browser の security（Edge ・CDP）: N1 〜 N5 ・保存の API が全て空（読み込み ・操作 ・再読み込みの後）・console の出力 0 ・全ての失敗の経路で画面が消える ・
   CSP の正の control。`RTCPeerConnection` は静的な走査で 0（WebRTC の観測は要件にしない）。
3. DOM と accessibility（CDP）: 6 つの項目の順 ・状態の印が文として在る ・FACT ／ HYPOTHESIS の label ・出所と時刻の表示 ・同じ DOM の hash ・
   role と名前 ・`lang="ja"` ・見出しの段階 ・tap の対象は 44×44 CSS px 以上 ・文字の contrast は 4.5:1 以上 ・reduced motion で animation 無し ・
   既定の文字の大きさを 2 倍にしても横の溢れと切れが無い。
4. 見た目（375×812 と 430×932）: 横の scroll 無し ・見出しが上に留まる ・watermark が見える。screenshot は人の審査だけで、自動の合否ではない。

## 17. 禁止

- 本記録と H1 の表示の文に無いこと: 売買の推奨 ・確率 ・順位 ・score ・目標株価 ・おすすめ ・注目銘柄 ・最新 ・相対の時刻。
- 根拠の無い確信の語（確実 ・必ず）は市場の見通しの表示の文 ・template に無い（H0-D1 §14 と同じ。不確実 は使ってよい）。
- 実の data ・実の source への接続 ・LAN への露出 ・hosting ・Pages ・Cloudflare ・deploy ・認証の実装 ・browser での暗号の検証 ・`Date` による parse ・
  OS の水準の隔離の主張 ・CSP だけで隔離を証明したとの主張。

## 18. 境界（H1 ・M1 ・deploy）

- H1 が主張しないこと: 実機での検証 ・M1 の準備 ・production の security ・実の data の扱い ・認証 ・hosting。
- M1 に延期: passkey と端末の束縛（password は無い）・private な hosting と TLS（G-DEPLOY を経る ・Pages は使わない）・session の寿命 ・revocation ・
  再認証 ・実機での等級ごとの表示 ・端末の紛失と回復 ・privacy の gate ・第三者の表示の権利 ・redacted な監視 ・書き込みの前の別の脅威の審査
  （P11-OBS-073）・token の保存（keychain）・native か PWA かの決定。
- deploy は G-DEPLOY の別の審査。本記録は deploy を承認しない。

## 19. 延期と依存

- H0-D2: 項目ごとの正確な key の集合と上限。本記録は schema ・fixture を実装しない。
- S0-D1: scenario ・条件 ・確信の意味（PROVISIONAL(S0) のまま。本記録は値を確定しない）。
- UI0: 表示の設計（本記録の規則と H0-D1 の欄 ・label を使う）。
- H1: code の置き場 ・決定論の生成器 ・fixture と許可の一覧 ・単一の `index.html` ・pipe の CDP の harness（feasibility の試験の後）・
  `PHASE13_TESTS` への試験の登録。HOLD。
- A5-W ・A6 は HOLD のまま。本記録はそれらに触れない。

## 20. 本記録の承認の範囲

- 本記録は文書 ・registry ・guard だけ。product の機能 ・runtime の振る舞い ・認可 ・P13-A4b の凍結の runtime ・H0-D1 の記録は変わらない。
- 本記録は実装を承認しない。H1 ・M1 ・S0-D1 ・UI0 ・H0-D2 の記録は監督の別の承認を要する。
