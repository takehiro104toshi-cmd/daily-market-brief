# PHASE 11 / P11-A3 — STATIC PWA SHELL

Phase 11 の 3 つ目の実装 gate。loopback の server（P11-A2）が配る **static な PWA の shell**（HTML ・CSS ・vanilla JS ・manifest ・shell だけの
service worker ・local で生成した icon）を足し、P11-A1 の read-only の UI model を browser で描く。**Phase 11 の凍結ではない。**
書き込み ・実行器 ・profile ／ attention の編集 ・保有 ・公開の配備 ・通知 ・外部の network ・LLM ・API の応答の cache は無い。

- 基準: `P11_BASE` ＝ `d01f6bc…`。P11-A1 ＝ `da80675…` ・P11-A2 ＝ `3ceb36b…`（registry の `P11_A1` ・`P11_A2`。凍結 anchor ではない）。
- server の変更は static の配信だけ（`STATIC_ROUTES` の allowlist ・起動の時に package の `static/` から読んだ committed な byte ・
  static の header ・起動の出力に `app_url`）。`/health` ・`/version` ・`/api/view` の意味 ・header は A2 のまま。A1 は不変。

## 1. asset（`src/intelligence/personal_ui/static/`。runtime として登録 ・git blob の id を pin）

| 経路 | asset | 内容 |
|---|---|---|
| `/app/` ・`/app/index.html` | `index.html` | 最小の意味的な shell（inline の script ／ style ／ handler なし） |
| `/app/app.js` | `app.js` | 描画 ・時点の form ・`POST /api/view` ・SW の登録 |
| `/app/app.css` | `app.css` | 表示だけ |
| `/app/manifest.webmanifest` | `manifest.webmanifest` | install 用（§3） |
| `/app/sw.js` | `sw.js` | shell だけの service worker（§4） |
| `/app/icon-192.png` ・`/app/icon-512.png` | `icon-*.png` | stdlib で local に生成した単色の PNG（外部の出所なし） |
| — | `.gitattributes`（`* -text`） | Windows の checkout でも byte をそのまま（配る byte ＝ committed な byte） |

外部の CDN ・font ・JS ・CSS ・framework ・bundler ・npm は無い。`.gitattributes` 以外の全ての asset が allowlist の経路で配られ、他の
path（`/app`（斜線なし）・query 付き ・`..` ・`/app/static/…` ・`.gitattributes` ・package の file）は 404。directory の一覧は無い。

## 2. static の応答の方針

全ての static の応答: `Content-Type`（asset ごと）・`Content-Length` ・`Cache-Control: no-cache`（簡単で決定論。validator は出さない）・
`Pragma: no-cache` ・`X-Content-Type-Options: nosniff` ・`Referrer-Policy: no-referrer` ・`Cross-Origin-Resource-Policy: same-origin` ・
`Cross-Origin-Opener-Policy: same-origin` ・`Content-Security-Policy`（§6）・`Connection: close`。`Date` ・`Server` ・`ETag` ・cookie ・
CORS は出さない。同じ要求は status ・header ・body の全体が同じ。Host の規則（`127.0.0.1:<port>` の完全一致）は static にも効く。

## 3. manifest

`id` ・`start_url` ・`scope` ＝ `/app/` ・`display: standalone` ・`name` ・`short_name` ・`lang` ・色 ・icon 2 つ（192 ・512 ・PNG ・
`/app/` の下）。shortcuts ・screenshots ・外部の URL は無い。icon は Chromium の install の条件（192 px 以上の icon）のために要った。

## 4. service worker（shell だけ）

- `install`: `SHELL_CACHE`（`p11-shell-<12 hex>`。precache の 7 asset の git blob の id から sha256 で導く ・registry の
  `P11_SHELL_CACHE_NAME` と sw.js の定数が一致することを test が pin ・時刻は使わない）を開き、`PRECACHE`（`/app/` ・`index.html` ・
  `app.js` ・`app.css` ・`manifest` ・icon 2 つ。`sw.js` 自身は含まない）を `cache: 'reload'` ・`credentials: 'omit'` で `addAll`。
- `activate`: `p11-shell-` で始まり今の名前でない cache だけを消す（他の cache には触れない）。`clients.claim`。
- `fetch`: GET でない ・他の origin ・`/api/` ／ `/health` ／ `/version` ・precache に無い path は **何もしない**（network）。precache の
  path だけ cache-first（無ければ network）。実行の時に `put` ・`add` はしない（install の `addAll` だけ）。
- push ・sync ・periodic sync ・message ・notification の handler は無い。

## 5. browser の保存 ・時点 ・描画

- 保存は **何も使わない**（localStorage ・sessionStorage ・IndexedDB ・cookie ・URL ／ history に model ・時点 ・id を入れない。
  model は closure の変数だけ）。console にも出さない。
- 時点: 欄は空で始まる。「この端末の時計で欄を埋める（送信はしない）」は人が押した時だけ欄を埋め、要求は出さない。「読み込む」が
  明示の送信。`at` は offset 付きの瞬間 ・`as_of_date` は `YYYY-MM-DD`（browser 側で形を検査し、server が再検査）。
- 要求は `POST /api/view` だけ（`same-origin` ・`credentials: 'omit'` ・`cache: 'no-store'` ・`redirect: 'error'` ・`no-referrer` ・
  body の JSON。query なし）。
- 描画は P11-A1 の欄だけ（profile: ACTIVE の有無 ・窓 ・除外の件数 ／ 件数の 2 つの dl ／ 見直しの列: ordinal ・種類 ・状態 ・出所 ・期日 ・
  区分 ・印 ・除外 ・組 ・link の ordinal ／ as of ・版）。応答の順のまま ・並べ替えない ・点数 ／ 順位 ／ 推奨は計算しない。MUTE ・除外の
  行も見える（data 属性で薄く ／ 背景だけ）。`textContent` ・`createElement` だけ（`innerHTML` ・`eval` ・`Function` ・inline の handler なし）。
- 失敗（拒否 ・届かない ・offline）: 前の model を DOM から消し、安全な code（`[A-Z0-9_:]`）か一般の文だけを出す。offline の時は
  "App shell available offline; private data requires the local server."。古い private な data を今のものとして見せない。

## 6. CSP

`default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; manifest-src 'self'; worker-src 'self';
base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'`。`unsafe-inline` ・`unsafe-eval` は無い（shell に inline
が無いので要らない）。browser の test が inline の script の実行を CSP が止めることを確かめる。API の header は A2 のまま（CSP は足さない）。

## 7. 証拠

`tests/intelligence/test_personal_ui_static.py`: asset の集合と blob の pin ・LF ・cache の名前の導出 ・icon の PNG ・manifest ・HTML ・
JS ・SW の静的な検査 ・経路 ・header ・CSP ・404 の面 ・Host ・API の header の不変 ・起動の asset の読み込みと欠落の拒否。
`tests/intelligence/test_personal_ui_browser.py`（Playwright が在る時だけ）: shell の load ・SW と precache の中身 ・空の欄 ・明示の時点 ・
描画と順 ・MUTE ／ 除外の可視 ・DOM に private な値なし ・保存なし ・Cache Storage に API なし ・offline ・失敗で DOM が消える ・CSP。
`tests/intelligence/test_personal_ui_boundary.py`: registry と allowlist の一致 ・blob の pin ・A1 の不変 ・公開 ／ Pages ／ Cloudflare の不変。

## 8. 登録 ・guard

- static な asset は `PHASE11_RUNTIME` に登録（凍結の P7 〜 P10 の guard は名前で参照するので再開なし）。`PHASE11_PY_RUNTIME`（.py の 4 file）が
  import ／ AST の規則の対象。`P11_STATIC_BLOB_IDS` が asset の git blob を pin し、`P11_STATIC_ROUTES` が server の allowlist と一致。
- Phase 11 は凍結していないので、`is_phase11_addition` は A1 以外の登録済み runtime の gate の中の修正（`M`）も Phase 11 の変化として
  受ける（A1 の不変は commit ・index ・worktree で別に守る）。凍結の P7 の helper `is_phase7_addition` はこれに委ねる形で**行の単位で
  再開**し、`PHASE11_TEST_REGISTRATION` に pin（他の凍結の test は不変）。
- A2 の test の event の確認は sink の呼び出し（body の後）を短く待つ形にした（test だけ ・競合の修正）。

## 9. 観察

P11-OBS-001 〜 037 を引き継ぐ。P11-OBS-038 〜（gate の報告に記録）。
