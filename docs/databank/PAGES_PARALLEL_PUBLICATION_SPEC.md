# PAGES_PARALLEL_PUBLICATION_SPEC — Morning Delivery `/v2` 並走公開（Phase 4 P4-3b2c / 2026-09-15）

legacy Pages site を保ったまま、検証済み Morning Delivery を `/v2` として**並走公開**する
ための契約を固定する。root 切替ではない（root 切替は P4-3b4 の専管）。

対象実装:

| file | 役割 |
|---|---|
| `.github/workflows/daily-market-brief.yml` | 本番公開経路（**唯一の Pages writer / deployer**） |
| `.github/workflows/p43b2c-pages-preview.yml` | deploy しない full Pages preview（検分 gate） |
| `scripts/p43b2c_select_producer.py` | 本番公開向け producer run / artifact 選定 |
| `scripts/p43b2c_pages_manifest.py` | manifest 作成・比較・tree 構造衛生 |
| `scripts/p43b2c_v2_gate.py` | 鮮度 / typed 分類 |
| `scripts/p43b2c_graft_v2.py` | 検証済み 5 file の名前指定接ぎ木 |
| `config.yaml: pages_parallel_publication` | 運用上の見取り図（定数との一致はテストで固定） |

凍結資産（本 Phase で変更しない）: `src/intelligence/reports/pages_parallel.py`（b2a）/
`docs/pages/v2_index.html` / `scripts/p43b2b_select_run.py` /
`.github/workflows/p43b2b-delivery-handoff.yml` / `main.py` / `notifiers/**`。

---

## 1. whole-site Pages semantics（実測に基づく前提）

GitHub Pages の deployment は **site 全体の置換**である。次の 3 系統で確認した。

1. `actions/upload-pages-artifact@v3` の `action.yml` 実物は、`path` ディレクトリ
   **全体**を 1 本の tar に固める（除外は `.git` と `.github` のみ。**他の dot entry は
   含まれる**）。
2. `actions/deploy-pages@v4` は「previously uploaded as an artifact」な site を deploy
   する。input は `artifact_name` **1 つだけ**で、差分・merge・incremental の概念が無い。
3. 本番 workflow は毎 run `output/history/*` を `pages-site/history/` へ**再 copy**して
   おり、`pages-site/` は `.gitignore` 対象＝毎回ゼロから再構築される。Pages が増分
   merge するならこの再 copy は不要である。

**帰結**: `/v2` だけを含む artifact を deploy すれば legacy root は消える。したがって
**`/v2` 専用の deploy 経路は禁止**であり、deploy 前に**完全な意図された tree を再構成**
しなければならない。

## 2. single-deployer invariant

本番の Pages writer / deployer は `.github/workflows/daily-market-brief.yml` **のみ**。

- Pages artifact を作るのは `generate-report` job の既存 `upload-pages-artifact` 1 箇所。
- deploy するのは `deploy-pages` job の既存 1 箇所。
- 他のどの workflow も Pages 権限（`pages` / OIDC）を持たない。

`tests/intelligence/test_pages_integration.py` が、リポジトリ全 workflow を走査して
この 1 対 1 を機械的に固定する。2 本目の deployer が入れば即座に落ちる。

## 3. current legacy public tree（実 tree の棚卸し）

```
pages-site/
  index.html                          ← output/latest_market_brief.html の copy
  history/<YYYY-MM-DD>/<slot>.html    ← output/history/** の copy
```

slot は `pre_market` / `market_open` / `morning_close` / `afternoon_open` /
`market_close` / `evening`。

- `output/*.md` と `output/YYYY-MM-DD_market_brief.html` は git 追跡下にあるが
  **Pages へは copy されない**。
- `CNAME` なし / `.nojekyll` なし / `docs/` を Pages source にしていない。
- legacy root HTML の local 参照は `#` anchor と `history/` のみ。
- **件数は固定しない**（history は毎日増える）。

## 4. manifest contract

entry は `(相対 POSIX path, sha256, byte 数)` で、相対 path の昇順。

- **BEFORE**: `/v2` 接ぎ木の直前の legacy tree 全体。
- **AFTER**: `/v2` 接ぎ木の後、**top level `v2/` だけを除いた**全体。
- **BEFORE == AFTER を完全一致で要求する**（path・sha256・byte 数のすべて）。

独立して要求する不変条件:

- root `index.html` が存在する
- legacy manifest に `v2/` が混ざっていない
- tree のどこにも dot entry が無い（staging 残骸の検出）
- symlink（file・ディレクトリとも）を**拒否**する
- 解決後の path が root の外を指すものを**拒否**する（path escape 防御）

## 5. freshness contract（beta 凍結値）

| 上限 | 値 | 判定 |
|---|---|---|
| artifact age | **24 時間** | `now_utc - artifact.created_at`。超過で `V2_UNAVAILABLE` |
| session lag | **3 暦日** | `jst_today - session_date`。超過で `V2_UNAVAILABLE` |

- **祝日カレンダーを実装しない。** 立会日かどうかは判定しない。
- 未来 session の一次拒否は**凍結 b2a の既存責務**（`session_date > jst_today`）。
  gate 側は通過してきた場合の防御としてのみ見る。
- `now_utc` / `jst_today` は呼び出し側が**明示的に渡す**（gate は時計を読まない）。
  JST 当日は凍結 Compass pilot と同一の導出
  （`datetime.now(timezone.utc) + timedelta(hours=9)`）を使う。
- **古い artifact を「今日の v2」として黙って出すことは無い。**
  `/v2/index.html` は凍結静的テンプレートで日付を持たないため、鮮度を content の
  自己記述に頼らず、この gate で止める。

## 6. Policy A — no-valid-v2 behavior

適格で新鮮な `/v2` が無いとき: **legacy だけを publish する。**

- 古い `/v2` を保持しない
- 「準備中」placeholder を作らない
- canonical な v2 store を作らない
- `output/v2` へ永続化しない

`/v2` route は一時的に消えてよい（beta として許容）。producer に production cron が
無い現状では `/v2` はほとんどの run で不在になる。**`/v2` を毎日出すには producer の
production schedule が必要**であり、それは本 Phase の範囲外（P12-1 / 監督者決定）。

## 7. failure classification

| 分類 | 原因 | 挙動 |
|---|---|---|
| `V2_UNAVAILABLE` | 適格 run なし / artifact なし / expired / 24h 超過 / 3 暦日超過 | safe-skip。legacy は publish |
| `V2_REJECTED` | 凍結 b2a の `PublicationRejected` / wrapper 形違反 | safe-skip ＋ **可視警告**（`::warning::` ＋ typed marker ＋ job summary） |
| `V2_INTERNAL_ERROR` | 設定不備 / API 異常 / download 失敗 / selector 異常終了 | safe-skip ＋ **可視警告**（**pages-site 未変更のときのみ**） |
| `LEGACY_FAILURE` | manifest BEFORE≠AFTER / `index.html` 欠落 / dot 残骸 / `/v2` が 5 file でない / graft 失敗 / 衛生違反 | **workflow 失敗。Pages deploy させない** |

**pages-site の変更が始まった後の想定外失敗はすべて致命**として扱う。

`continue-on-error: true` を任意ブロックへ被せない。許すのは **artifact download step
1 箇所のみ**で、その結果は次 step が `steps.<id>.outcome` で読み、typed result へ落とす。
テストが「`continue-on-error` を持つ step はその 1 つだけ」を機械的に固定する。

## 8. production selector contract

`scripts/p43b2c_select_producer.py`。凍結 b2b selector の**定数の複写ではなく**、
実証済みの信頼原則を明示的な本番契約として書き直したもの。

**mode は production / preview で構造的に分かれる。暗黙に落ちない。**
`github.ref` 等から branch / baseline を推測しない（テストで固定）。

production mode が要求するもの:

- `branch == "main"`（feature branch の artifact を本番 Pages へ載せない）
- **明示された trust baseline**（既定値なし。空なら `CONFIGURATION_INVALID` で fail closed）
- baseline が P4-3b2b の検証専用 baseline `a2a6222` で**ない**こと

検証する項目: workflow 同一性（path 完全一致）/ head branch / `status == completed` /
`conclusion == success` / event allowlist / trust ancestry（compare の `status ∈
{identical, ahead}` **かつ** `behind_by == 0`）/ artifact 名完全一致でちょうど 1 件 /
`expired is false` / size 範囲 / id・`created_at` の型 / attempt policy。

**event policy** は明示リストで渡す。語彙には `schedule` を含めてあるため、将来 producer
に cron を付けても trust ロジックを書き換える必要がない。**beta では `schedule` を
渡さない**（production scheduled producer を有効化しない）。

### attempt policy

GitHub の artifact record は **attempt を持たない**（P4-3b2b で実測）。したがって:

- `first-attempt-only`（**beta の既定**）: `run_attempt == 1` のみ採る。
- `verified-attempt`: `run_attempt > 1` を採るのは、`/runs/{id}/attempts/{n}` の
  `run_started_at` に対して `artifact.created_at >= run_started_at` が**実際に言える
  場合だけ**。`run_started_at` が読めない、または `created_at` が無い・古い場合は
  **推測せず fail closed**。

`REQUIRED_RUN_ATTEMPT = 1` を説明のない恒久 invariant として持ち込まない。

## 9. assembly order（本番 workflow）

```
1  Prepare GitHub Pages site                  （既存・無変更）
2  Capture the legacy Pages manifest before /v2（厳格）
3  Select a trusted producer artifact for /v2  （fail-safe・typed result）
4  Download the selected producer artifact     （pages-site の外へ）
5  Validate and stage /v2 outside the pages site（wrapper 形 → 凍結 b2a → 鮮度 gate）
6  Graft the validated /v2 into the pages site （PASS のときだけ・pages-site 唯一の書き込み）
7  Verify the legacy Pages tree is unchanged   （厳格・採否に関わらず必ず走る）
8  Record the /v2 publication status           （job summary）
9  Upload GitHub Pages artifact                （既存・無変更）
   deploy-pages job                            （既存・無変更／唯一の deployer）
```

**b2a の宛先を `pages-site/v2` に直接向けない。** 凍結 b2a は staging を
`destination.parent` の中へ作る（`.v2.tmp-XXXX`）ため、runner が強制終了すると
dot ディレクトリが pages-site に残り、`upload-pages-artifact` の除外
（`.git` / `.github` のみ）をすり抜けて**公開されうる**。よって b2a は
`${RUNNER_TEMP}/p43b2c_stage/v2` へ組み立て、PASS 後に接ぎ木する。

## 10. v2 graft contract

copy してよいのは凍結 b2a が報告した**承認済み 5 file だけ**:

```
index.html
latest_morning_brief.md
latest_morning_brief.json
<session_date>_morning_brief.md
<session_date>_morning_brief.json
```

日付入り 2 file の名前は b2a の検証済み metadata（`::P43B2A_PUBLISHED::` の `names`）
から来る。**ここで日付を組み立て直さない。**

- wildcard copy / 再帰探索 / `glob` / `fnmatch` / `copytree` を使わない（テストで固定）
- 拒否する: symlink / 6 file 目 / 欠落 / 予期しないサブディレクトリ / dot 残骸 /
  宛先の既存 / 日付 2 file の不一致 / plain file name でない名前
- copy 後に**実測で**照合する（source と byte 同一・ちょうど 5 file）
- 失敗時は作りかけの `v2/` を消してから伝播させる（pages-site を汚さない）

## 11. confidentiality

`/v2` の**内容**安全性の権威は**凍結 b2a のまま**である。b2c はその内部語彙契約
（`FORBIDDEN_PUBLIC_SUBSTRINGS` 等）を**複製しない**。

b2c が公開 tree 全体へ掛けるのは**構造・path・secret 衛生だけ**:

- 禁止拡張子（`.pdf` / `.sqlite*` / `.db` / `.jsonl` / `.parquet` / 書庫 / `.env` /
  `.pem` / `.key` / `.log` / `.part`）
- 禁止 path 断片（`compass` / `corpus` / `evidence` / `governance` / `decision` /
  `candidate` / `market_bank` / `knowledge` / `intelligence_data`）
- machine-specific 絶対 path（runner / ホーム配下）
- 形が明確に秘密のリテラル

**legacy の散文へ内部 v2 語彙を当てない。** legacy レポートには `HIGH` / `MEDIUM` /
`LOW` / `MIXED` / `breadth` 等が日常的に現れるため、当てれば誤検知になる（テストで固定）。

## 12. preview gate（deploy しない）

`.github/workflows/p43b2c-pages-preview.yml`。

- 権限は `contents: read` / `actions: read` **のみ**（Pages 権限も OIDC 権限も持たない）
- GitHub Pages 専用 action を一切呼ばない。通常の `actions/upload-artifact@v4` のみ
- artifact 名 `full-pages-site-preview` / `retention-days: 14` / `if-no-files-found: error`
- legacy tree は `${RUNNER_TEMP}` 上に再現する（リポジトリの `output/` / `pages-site`
  に触れない）。commit も push もせず、notifier も `main.py` も呼ばない
- selector は **preview mode**（feature branch と検証 baseline を明示的に渡す）
- 証跡: manifest BEFORE/AFTER digest・`/v2` の 5 file・tree 衛生

trigger は `workflow_dispatch` ＋ 専用 trigger file への path 限定 push。
**trigger file は監督者の承認まで作成しない**ため、現時点では自動発火しない。

## 13. main promotion boundary

`main` には現在 `src/intelligence` が存在せず、workflow も `daily-market-brief.yml`
1 本のみである。b2c 稼働に main へ必要な最小集合:

1. `src/intelligence/reports/` の 5 module（`pages_parallel` / `delivery` /
   `delivery_emit` / `market_signal` / `model`）＋ 空の `__init__.py` 2 本
   — **stdlib のみ。新規 pip 依存ゼロ**
2. `docs/pages/v2_index.html`
3. `scripts/p43b2c_*.py` 4 本（stdlib のみ）
4. `.github/workflows/daily-market-brief.yml` の b2c step 追加版
5. `.github/workflows/p43b1-morning-delivery-producer.yml`（本番で artifact を生むなら）
6. `tests/intelligence/test_pages_integration.py`
7. `config.yaml` の `pages_parallel_publication`

**promotion 時に必ず行うこと**: production trust baseline へ、**main 上の承認済み
producer commit** を入れる。空のままだと production mode は `CONFIGURATION_INVALID`
で fail closed し、`/v2` は永久に出ない（legacy は正常に publish され続ける）。

validation ladder:

```
Gate 1 静的テスト ＋ full pytest
Gate 2 temp 上の完全 Pages tree simulation
Gate 3 Actions の no-deploy full Pages preview
Gate 4 監督者検分
Gate 5 production promotion 承認（baseline 決定を含む）
Gate 6 main merge 後、1 回だけの実 parallel Pages deployment
Gate 7 legacy root が live で不変であることの検証
Gate 8 /v2 が live で到達可能・digest 一致
```

## 14. root cutover exclusion

b2c は次を**行わない**（すべて P4-3b4 の専管）:

`/` の redirect / root の v2 置換 / `legacy.html` の作成 / 既定通知先の変更 /
legacy renderer の変更 / history 意味論の変更。

**b2c の後も legacy root が root のままである。**

## 15. notifier exclusion

`notifiers/**` と `main.py` の通知挙動を変更しない。
`main.py` の `_resolve_pages_url()` は `https://<owner>.github.io/<repo>/`（= root）を
返し続ける。P4-3b3 は LOCKED のまま。

## 16. no repository v2 persistence

`output/v2` へ永続化しない（P4-3a の derivative / noncanonical 凍結を維持）。
cross-run artifact handoff（P4-3b2b で実証済み）と単一 Pages 組み立てで公開は完結する。
本番 workflow の commit 対象にも `v2` を足さない。

## 17. permissions

| 権限 | 変更 |
|---|---|
| `contents: write` | 変更なし（既存の report commit 用。b2c は使わない） |
| `pages: write` | 変更なし（既存 deploy 用） |
| `id-token: write` | 変更なし（既存 deploy 用） |
| **`actions: read`** | **本 Phase の唯一の追加**（cross-run artifact 参照・取得） |

`deploy-pages` job の権限は変更しない。preview workflow は Pages 権限も OIDC 権限も
持たない。既存 schedule（cron 12 本）と concurrency も変更しない。

## 18. markers

| marker | 出所 |
|---|---|
| `::P43B2C_HEAD::` / `::P43B2C_SELECTION::` / `::P43B2C_SELECTION_RESULT::` / `::P43B2C_ARTIFACT::` | production selector |
| `::P43B2C_MANIFEST::` / `::P43B2C_MANIFEST_VERIFY::` / `::P43B2C_HYGIENE::` / `::P43B2C_LEGACY_FAILURE::` | manifest utility |
| `::P43B2C_GATE::` | freshness / typed gate |
| `::P43B2C_GRAFT::` / `::P43B2C_GRAFT_REJECTED::` | graft helper |

marker はいずれも**秘密値・絶対 path を含まない設計**である。

---

# 19. Gate 3 / Gate 4 evidence（2026-09-15）

| 項目 | 値 |
|---|---|
| 実装 | `7c892d4` |
| preview guard 強化 | `ff70be8` |
| preview trigger | `95a65bc` |
| preview run | `34974303473`（push / attempt 1 / **success** / 全 11 step 実行） |
| preview artifact | `10398702881` `full-pages-site-preview`（276 file / 18,629,863 bytes / retention 14 日） |
| full suite | **2927 passed** |
| Gate 3 | **PASS**（Case A — `/v2` の実地包含を証明。fail-safe 経路ではない） |
| Gate 4 | **PASS（証跡再導出による）**。下記の retrieval 制約を参照 |

Gate 3 実測: artifact age 6.459h（上限 24h）/ session lag 0 日（上限 3 暦日）/
legacy manifest digest `345783b0…3814d3` が接ぎ木前後で一致 / `/v2` ちょうど 5 file /
tree 衛生 0 findings / Pages deploy ゼロ。

## 19.1 Gate 4 で独立に再導出した値

run の marker を信用せず、**git から再計算**して突き合わせた:

| 対象 | 方法 | 結果 |
|---|---|---|
| legacy manifest digest（271 file） | `95a65bc` の `output/` から本番と同一手順で tree を再構成し manifest を再計算 | `345783b0…3814d3` **完全一致** |
| `v2/index.html` digest | 凍結テンプレート `docs/pages/v2_index.html` の sha256（b2a は verbatim copy し byte 一致を検証する） | `11152525…17be2` **完全一致** |
| legacy tree 構造・衛生 | 再構成 tree に対し `hygiene` を実行 | top level は `index.html` と `history/` の 2 つのみ / 46 date dir / 271 file すべて `.html` / `legacy.html` なし / 入れ子 `index.html` なし / symlink なし / dot entry なし / 禁止拡張子なし / findings 0 |

`latest_morning_brief.md|json` と `2026-09-15_morning_brief.md|json` の digest
（`60f1da5f…f1c1` / `de9550c0…9284`）は producer artifact の実体を要するため本環境では
独立再計算できない。ただし **2 つの独立した run**（P4-3b2b `34963135973` と
P4-3b2c `34974303473`）が同一値を報告しており、相互検証されている。

## 19.2 artifact retrieval の制約（記録）

preview artifact の zip 実体は `*.blob.core.windows.net` 上にあり、本セッションの
egress policy がこのホストへの接続を拒否する（署名付き URL・GitHub API の redirect の
いずれも同一ホストへ着地する）。artifact の**内容を返す MCP tool も存在しない**。

したがって **zip そのものの展開検査は実施できていない**。上記 19.1 は同等の保証を
目指した独立再導出であって、zip の直接検査の置き換えではない。zip 実体の検分は
監督者側でのダウンロードに委ねる（2026-09-29 まで取得可能）。

---

# 20. 本番 promotion 計画（設計のみ・未実行）

## 20.1 実測した branch 乖離

| 項目 | 値 |
|---|---|
| `origin/main` | `3b0e183`（2026-09-15 12:04 UTC） |
| feature HEAD | `95a65bc` |
| merge-base | `34f7f98`（2026-08-28） |
| feature → main 先行 | 130 commit |
| main → feature 先行 | **103 commit（すべて bot の `Add daily market brief`）** |
| main 側が触った path | `output/` 142 file ＋ `data/` 18 file のみ |
| feature 側が `output/` `data/` を触った量 | **0 file** |
| **両側で変更が重なる file** | **0 件** |

main には merge-base 以降、**人手の production 変更が 1 件も無い**。
競合は起きないが、**merge すれば 130 commit と 352 file 規模の開発資産が本番へ入る**。

## 20.2 promotion 方式の比較

| | A 通常 merge | B squash | C cherry-pick | **D allowlist promotion commit** |
|---|---|---|---|---|
| legacy `output/`/`data/` 保全 | 安全（重なり 0） | 安全 | 条件付き | **安全（触らない）** |
| 競合リスク | 低 | 低 | **高**（18 日分の path に対し断片適用） | **無し** |
| trust ancestry | 保たれる | **破壊**（feature commit が main の祖先でなくなる） | 断片化 | 新 baseline を定義（下記） |
| rollback | merge revert（巨大） | revert（巨大） | 困難 | **1 commit の revert** |
| 監査性 | 低（130 commit） | 中 | 低 | **最高（1 diff）** |
| 本番へ入る無関係資産 | **352 file ＋ docs/knowledge 全般** | 同左 | 中〜大 | **allowlist のみ** |
| 研究・機密隣接資産の混入 | corpus / corpus_research / shadow_review / decision / formal_review / evaluation が入る | 同左 | 可能性あり | **入らない** |
| 進み続ける main との相性 | 良 | 良 | 悪 | **良（毎回 latest main 上に再構築）** |

**B は本件では有害**である。squash すると `a2a6222` も feature の全 commit も main の
祖先でなくなり、compare ベースの trust 判定が `diverged` に倒れる。

**推奨: D（allowlist から作る専用 promotion commit）。**
実装手段は repo-native（`git checkout origin/main -b promo` →
`git checkout 95a65bc -- <allowlist>` → 1 commit）。

## 20.3 production runtime closure（実測）

**b2a だけが本番面だという以前の前提は誤りだった。** `/v2` が本番で成立するには
**producer artifact が本番に存在**しなければならず、producer の closure が支配的である。

| closure | first-party file 数 |
|---|---|
| 凍結 b2a 公開境界 | **8**（`pages_parallel` / `delivery` / `delivery_emit` / `market_signal` / `reports.model` / `compass.model` / `core.ids` / `core.time`） |
| `market.pilot_runner` | 66 |
| `reports.delivery_pilot` | 127 |
| **producer union** | **133** |
| **producer ＋ b2a union** | **134** |
| feature branch の `src/intelligence` 総数 | 352 |

（注: 以前の報告で b2a closure を 5 file としたが、正しくは **8 file** である。）

producer closure に**含まれる** 15 package: `compass` `context` `core` `databank`
`enrichment` `evidence` `evidence_qa` `facts` `ingestion` `internals` `market`
`normalization` `reports` `review` `sources`。

producer closure から**除外される** 17 package（本番実行に不要）: `corpus`
`corpus_research` `decision` `entities` `evaluation` `formal_review` `jquants_ops`
`mobile_intake` `news` `personalization` `pipeline` `predictions` `replay`
`screening` `shadow_review` `themes` `thesis`。

→ Compass PDF corpus・governance・Decision 記録・research 機構は**本番 closure の外側**に
自然に落ちる。allowlist 方式ならこれらは本番へ入らない。

third-party 依存は **`pyyaml` と `yfinance` の 2 つだけ**（producer workflow の
`pip install pyyaml yfinance pytest` と一致）。secret は **`JQUANTS_API_KEY` のみ**。
producer の permissions は `contents: read` のみで、**リポジトリ書き込みは 0 箇所**。
出力は `runner.temp` 配下のみ（`INTELLIGENCE_DATA_ROOT` / `P43_DELIVERY_OUTPUT_ROOT`）。

`knowledge/compass_dna/market_rules.yaml`（6,320 bytes）と
`knowledge/market_series/core_series.yaml`（27,267 bytes）は **main に存在しない**ため
promotion が必要。

## 20.4 production trust baseline の確定手順

baseline は **promotion commit が存在してからでなければ確定できない**。
したがって promotion は 2 段階にする。

- **P1（dormant promotion）**: allowlist を latest `origin/main` 上へ 1 commit で載せる。
  `P43B2C_TRUST_BASELINE` は**空のまま**。production mode は
  `CONFIGURATION_INVALID` → `V2_INTERNAL_ERROR` で safe-skip し、**legacy は通常どおり
  publish される**。`/v2` は出ない。ここで本番 workflow が無害であることを実地確認する。
- **P2（activation）**: `P43B2C_TRUST_BASELINE` を **P1 の SHA** に設定する 1 行 commit。
  以降の producer run の `head_sha` は P1 の子孫なので compare は `ahead` を返し続ける。

baseline に **`a2a6222` を使わない**（production mode が明示的に拒否する）。
存在しない SHA を先に決め打ちしない。未レビューの main commit を焼き込まない。

rollback 時: P2 を revert すれば baseline が空に戻り `/v2` だけが止まる。
将来 main が squash / rebase されて P1 が祖先でなくなった場合は compare が `diverged` に
倒れ **fail closed（legacy のみ）** になる。これは安全側の挙動であり、
復旧は baseline の貼り替えで行う。

## 20.5 main 前進への対処

promotion は「pin した `origin/main` の SHA の上に構築 → push 直前に再 fetch →
SHA が変わっていたら**作り直す**」を必須とする。stale な main に対して黙って適用しない。

`git push origin HEAD:main` は main が進んでいれば non-fast-forward で**失敗する**。
これを検知手段として使い、失敗したら latest main から allowlist を再適用して作り直す。
allowlist は `output/` `data/` を一切含まないため、作り直しは機械的で安全である。

## 20.6 producer scheduling（設計のみ・実装しない）

producer には本番 cron が無く、artifact 鮮度上限は 24 時間である。

legacy は 1 日 6 スロット（07:30 / 09:10 / 11:30 / 12:40 / 15:40 / 17:20 JST）。
**JST 06:50 頃に 1 日 1 回**走らせれば、同日の全スロットが artifact 年齢 11 時間以内に
収まる（最も遅い 17:20 スロットでも約 10.5 時間）。これが beta の最小方針である。
workflow chaining（`workflow_run`）は trigger 依存を増やすため採らない。

**結合した必須変更**: 現在 production selector へ渡している
`--eligible-events push,workflow_dispatch` には **`schedule` が含まれていない**。
producer に cron を付けるなら、同時に `--eligible-events push,workflow_dispatch,schedule`
へ変更しなければ、scheduled producer run はすべて「event is not eligible」で拒否され
`/v2` は永久に出ない。語彙自体は既に `schedule` を許容しているため trust ロジックの
書き換えは不要である。

最終的な scheduler 統合は **P12-1 の所有**であり、上記は acceptance period のための
暫定方針にとどめる。

## 20.7 preview trigger の扱い

`.github/p43b2c_preview_trigger` は**開発 branch の inert な検証インフラとして残す**。
本 gate では削除しない。**production allowlist には含めない**（本番に trigger file を
置かない）。preview workflow 自体は allowlist に含めることを推奨する——push trigger が
feature branch 限定なので本番では自動発火せず、`workflow_dispatch` による no-deploy
検証手段として本番側でも有用だからである。preview trigger を本番スケジューリング機構に
転用してはならない。

## 20.8 test guard の依存（要決定）

`tests/intelligence/test_pages_integration.py` は凍結 b2b 資産
（`scripts/p43b2b_select_run.py` と `.github/workflows/p43b2b-delivery-handoff.yml`）の
存在を assert する。両者は**検証専用**で本番 runtime ではない。選択肢は 2 つ:

- (a) b2b の 2 file も allowlist に含める（guard を 1 文字も変えずに済む。両 workflow は
  read-only・非 deploy。ただし `workflow_dispatch` が本番側で可視になる）
- (b) promotion 時に guard を改変して b2b 資産の assertion を条件付きにする
  （本番面は最小になるが、**promotion のタイミングでテストを弱める**ことになる）

**(a) を推奨**する。promotion の瞬間にテストを弱めないことを優先する。
