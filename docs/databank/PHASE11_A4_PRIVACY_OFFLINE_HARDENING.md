# PHASE 11 / P11-A4 — PRIVACY / OFFLINE HARDENING

Phase 11 の 4 つ目の gate。A3 の private な local PWA を **硬化**する（製品の機能は足さない）。P11 v1 は read-only のまま。
authority の書き込み ・実行器 ・保有 ・profile の note ・除外の id ／ 理由 ・LLM ・外への network ・外部の asset は無い。Pages は不変。
**Phase 11 の凍結ではない。** A1 の意味は不変。A2 ／ A3 の runtime は硬化に要る所だけ変えた。

- 基準: `P11_BASE` ＝ `d01f6bc…`。A1 ＝ `da80675…` ・A2 ＝ `3ceb36b…` ・A3 ＝ `19686a6…`（registry の `P11_A1` 〜 `P11_A3`）。

## 1. 脅威 model（結論）

| # | 脅威 | 対処 ・証拠 |
|---|---|---|
| 1 | 誤って公開に載る | 公開の面（workflow ・docs/pages ・script ・report ・Cloudflare ・output）は `personal_ui` を参照せず、static な asset の git blob は static/ の外に複製なし（boundary の guard ・mutation で確認） |
| 2 | 外の origin からの要求 | `Origin` ・`Sec-Fetch-Site` は完全一致（same-origin ／ none だけ）。CORS 無し。cross-site の form は型（415）で落ちる |
| 3 | DNS rebinding ・偽の Host | `Host` は `127.0.0.1:<port>` の 1 つだけの完全一致（重複 ・localhost ・8 進 ・IPv6 ・userinfo ・末尾の文字 ・転送の header は全て 400） |
| 4 | cross-site の form ／ fetch | 同上 ＋ `form-action 'self'` ＋ API は JSON の POST だけ。no-cors の form は 415、GET の読み込みは 405 |
| 5 | 古い service worker | cache の名前は asset の blob から決定論に導く。新しい worker は新しい cache を作り、activate で古い `p11-shell-*` だけ消す。UI は controller の交代で「新しい版 ・再読み込み」を一般の文で出す（network の polling 無し） |
| 6 | server を失った後の古い DOM | 失敗（停止 ・500 ・503 ・崩れた JSON ・schema の不一致 ・timeout ・中止 ・不正な時点 ・offline の遷移）の **全て**で、描く前に前の model を DOM と memory から消す |
| 7 | API の応答が Cache Storage に | SW は `/api/` ・`/health` ・`/version` ・query 付き ・precache 外 ・他 origin ・GET 以外を扱わない。実行時の `put` は無い。browser の test が Cache Storage の body を sentinel で走査 |
| 8–11 | localStorage ／ sessionStorage ／ IndexedDB ／ cookie | 使わない。静的な走査で API を禁じ、browser の test が各段階で空を確かめる。server は `Set-Cookie` を出さず cookie を読まない |
| 12 | URL ／ history に private な値 | form は `method="post"`（JS が無くても GET の query にならない）。fetch の body だけ。URL ・`history.state` ・history の長さは不変。reload で欄は空 |
| 13 | console に private な値 | `console.` の呼び出しは無い（静的 ＋ browser の console の採取が空） |
| 14 | server の log に private な値 | log は無効。stdlib の `handle_error`（traceback を stderr に出す）も無効化。sink は (method, route, status, kind) だけ |
| 15 | 生の id が DOM に | UI model に id は無い（A1）。client の schema の検査で未知の鍵（例: `issuer`）を持つ応答は拒む |
| 16 | profile の note ／ 除外の詳細が DOM に | 同上（A1 の model に無い ・未知の鍵は拒む）。描く欄は列挙した 10 ＋ 件数だけ |
| 17 | stack trace ・path の漏れ | 例外は class 名だけ sink に。`handle_error` 無効。起動の拒否は安全な code（path を含まない）。test が typed error ・Host ・Origin ・body の sentinel を全ての出口で確認 |
| 18 | 崩れた ／ 信用できない API の応答 | client 側で表示の schema を検査（§3）。不一致は何も描かず ・何も持たず ・一般の `RESPONSE_INVALID` |
| 19 | model の文字列からの XSS | 文字列は全て code ／ 日付 ／ 版の正規表現で縛る → 敵対的な文字列は描く前に拒まれる。描画は `textContent` ／ `createElement` だけ。CSP が inline ・eval を止める |
| 20 | 拡張 ・local の侵害 | **受け入れる境界**: OS ／ browser profile が完全に侵害されていれば（拡張の全権限 ・debugger ・process の memory の読み）、loopback の server も DOM も守れない。P11 はそれを偽の複雑さで解かない。守るのは「普通の browser ・普通の網」の中の漏れ |

## 2. fetch ・timeout ・stale data の方針（LOCK）

- `POST /api/view` だけ ・same-origin ・`credentials: 'omit'` ・`cache: 'no-store'` ・`redirect: 'error'` ・`no-referrer`。
- `AbortController` で **10 秒**（`FETCH_TIMEOUT_MS`。固定）。中止は `TIMEOUT` の一般の文。再試行 ・背景の更新 ・自動の更新は無い。
  同時には 1 要求（`inFlight`）。再試行は人の操作だけ。
- 失敗の全てで: `clearModel()`（memory の参照を null ・table ／ dl の子を全て除く ・節を隠す ・as-of ／ 版を空に）→ 安全な code か一般の文。
  成功の時も描く前に前の model を消してから入れ替える。offline の遷移（`offline` event）でも消す。
- memory: JS の変数の参照を無くすだけ。browser の process の memory の消去は保証しない（暗号学的な消去は主張しない）。

## 3. 応答の検査（表示の schema。投資の意味は JS に無い）

plain object ・鍵の集合が完全一致（11 の top ・10 の entry）・`schema_version === 'p11_ui_model:0.1.0'` ・`at` ／ `as_of_date` の形 ・
boolean ・非負の整数 ・件数の map（鍵 `[A-Za-z0-9_.]{1,80}` ・値は整数 ・≦ 64 鍵）・版の map（短い版の文字列）・code は `[A-Z0-9_]{0,80}`（空は「無し」） ・
`review_due_on` は null か日付 ・行は ≦ 2000。`__proto__` の鍵も「未知の鍵」として拒む。不一致 → 何も描かず ・持たず。

## 4. service worker

- install: asset ごとに `fetch(…, { cache: 'reload', credentials: 'omit', redirect: 'error' })` → `status === 200` ・`type === 'basic'` ・
  `!redirected` だけ `put`。1 つでも落ちれば cache 全体を消して失敗（fail closed ・部分の shell は残さない）。
- activate: `caches.keys()` で列挙し **`p11-shell-` で始まり今の名前でない cache だけ**消す。他の cache は触れない。
- fetch: GET ・同 origin ・query 無し ・`/api/` ／ `/health` ／ `/version` でない ・precache の path だけ cache-first。miss は network で保存しない。
- 毒の entry: shell の cache に `/app/unknown` や `/api/view` が入っていても配らない（precache の集合に無い ／ API は扱わない）。test で確認。
- 更新: 新しい sw.js（内容が変われば cache の名前も変わる）→ install → `skipWaiting` → activate で古い名前を消す → `clients.claim`。
  UI は `controllerchange`（最初の controller があった時だけ）で「新しい版 ・再読み込み」を出す。polling 無し。

## 5. server の硬化

- `Host` ・`Content-Length` は **1 つだけ**。`Content-Length` は ASCII の数字 1 〜 7 桁だけ（Unicode の数字 ・符号 ・空白 ・16 進を拒む。
  `str.isdigit` は他の数字も通すので正規表現に）。`Transfer-Encoding` は常に拒む。body の読みの timeout は `400 BODY_TIMEOUT`。
- stdlib の解析の失敗（長い要求行 ・大きな header ・多い header ・不明な method ・壊れた行）は正準の JSON（HTML ・Server ・Date 無し）。
- `handle_error` を無効化（traceback を stderr に出さない）。
- static な asset は symlink でない通常の file だけ（`STATIC_ASSET_INVALID`）。配る byte は index の byte と同一（templating 無し）。
- path は allowlist の完全一致（符号化 ・traversal ・query ・absolute-form ・大文字 ・末尾の `/` は全て 404）。GET 以外は 405。
  stdlib は先頭の連続する `/` を 1 つに畳む（`//app/` → `/app/`。同じ asset が返るだけ ・別の file には届かない）。
  stdlib の 505（版の不支持）は 400 の正準の JSON に（INTERNAL_ERROR と混ぜない）。
- CSP に `font-src 'self'; media-src 'none'` を足した。`unsafe-*` 無し。**COEP は足さない**（同 origin の subresource しか無く、
  cross-origin isolation の利点が無い。将来の互換の負債だけ）。COOP ・CORP ・nosniff ・no-referrer は維持。
- cookie ・session ・CSRF token は無い（read-only）。**P11.1 で書き込みを足す時は別の write の脅威の審査が要る**（CSRF ・同意 ・冪等性）。

## 6. 証拠

`test_personal_ui_hardening.py`（Python）: Host ／ Origin ／ Fetch Metadata の敵対 ・path の符号化 ・method ・Content-Length ／
Transfer-Encoding ／ 途切れ ／ 遅い body ／ 大きな header ・static の integrity（mode 100644 ・symlink ・directory ・index の byte ・
templating 無し）・header の決定 ・typed error ／ hostile な header ／ body ／ `handle_error` の漏れ無し。
`test_personal_ui_browser_hardening.py`（Playwright）: 敵対的な文字列 × 10 の欄 ＋ 鍵（> 100 件）・崩れた応答 ＋ 失敗の種類の全て ・
timeout ・URL ／ history ／ reload ・SW の更新と毒の entry ・外部の要求ゼロ ・console 空 ・cookie 空 ・6 段階の保存の証明 ・
accessibility の smoke ・keyboard。`test_personal_ui_boundary.py`: 公開の面への参照 ・asset の blob の複製の検出。

## 7. 観察

P11-OBS-001 〜 048 を引き継ぐ。P11-OBS-049 〜（gate の報告に記録）。
