# PHASE 8 / P8-LIVE0 — LIVE DATA PRE-FLIGHT: TERMS ＋ PROVIDER MAPPING AUDIT（読むだけの監査 ・決定の束）

実の J-Quants の identity bootstrap ・財務 data の取り込みの前に残っていた問い（OBS-58 ・59 の規約の境界、市場区分の写し、`accepted_at` の
運用、live の bootstrap の手順、PILOT2 の境界）を、**公式の J-Quants の文書だけ**で解く gate。runtime の変更 ・live の API request ・
PILOT2 の実行は無い。本書は project の運用の判断であり、法的な助言ではない。

- 基準: P8-ID2 `07e62c7d837716a8277b696f8e5e31ac53f1a58c`（凍結。runtime 27 module）。full pytest の基準 5827 passed ／ 2 skipped。
- 確認日: **2026-09-29（UTC）**。取得は `jpx-jquants.com` の公開 page への GET だけ（API の呼び出し ・API key の使用は無い）。
- 本書は credential ・raw の応答 ・実の code の一覧を載せない。引用は必要な最小の抜粋。

---

## 0. 結論

1. **規約（§2）**: 個人の私的利用 ・自分だけが見られる保存 ・派生の record の保存 ・条件つきの生成 AI への入力 ・自分が管理する cloud への保存は
   **公式の FAQ が明示に許す**。第三者への提供 ・raw の配布 ・app での提供 ・**継続反復の第三者への提供** ・解約後の保持は**明示に禁止**。
2. **OBS-58 → CLOSED_CONFIRMED_PROHIBITED_FOR_PUBLIC_OUTPUT**（§3）: 「分析結果を継続反復して第三者に提供 ・配信する行為は私的利用に該当
   しない」（FAQ）。本 project の公開 Pages ・Morning Brief は継続反復の公開なので、J-Quants 由来の物を載せることは規約上できない。
   private の pilot ・研究は可。**公開の firewall は恒久（§9）**。
3. **OBS-59 → CLOSED_WITH_DISPOSAL_PROCEDURE_REQUIRED**（§3）: 解約 ・退会 ・downgrade の後は「取得したデータ ・複製物 ・元データを復元できる
   派生物」の削除が義務（規約 第7条 ・第15条 5 ・FAQ）。復元できない派生物は公開しない限り削除不要。→ private の data root（A1 ・A2 ・注記 ・
   保留の journal）を**丸ごと廃棄**する運用の手順が要る（§7.3）。
4. **private PILOT2 の判断: PRIVATE_PILOT_ALLOWED_BY_DOCUMENTED_TERMS**（§4）— 条件: 本人の Light account ・本人の私的な投資分析 ・
   第三者に見せない ・公開しない ・raw を保存しない ・**J-Quants の payload を外部の LLM ／ AI service（本 Claude Code の cloud session を含む）に
   入れない** ・本人が管理する環境で実行する。
5. **市場区分（§5）**: 「S04」は本 repo の先行の監査が付けた出所の番号で、V2 の契約は **`Mkt`（市場区分コード）＋ `ProdCat`（商品区分コード）＋
   `Code` の 5 桁目**。初期の bootstrap で支えるのは `Mkt ∈ {0111, 0112, 0113}` かつ `ProdCat == 011` かつ 5 桁目 `0`。
6. **提供者の写しの発見（要 gate。§5.4）**: 凍結 ID1 の入力は `ProdCat` を読まない。`Mkt` の一覧と 5 桁目だけでは **外国株券（021）・
   外国株預託証券（024）** を除外できない（Prime ／ Standard に上場し 5 桁目 `0` を持ちうる）。1〜3 発行体の PILOT2 では人の審査で
   `ProdCat == 011` を確かめれば足りるが、それより広い live の bootstrap の前に **ID1 へ `ProdCat` の必須の適格を足す gate（P8-ID1B）** が要る。
7. `accepted_at` の運用（§6）・live の bootstrap の手順（§7）・PILOT2 の契約（§8）を定めた。
8. GO ／ NO-GO: **条件つき GO**（§13）。判定: **P8_LIVE0_PRIVATE_PILOT_READY / READY_FOR_SUPERVISOR_REVIEW**。

---

## 1. 開始の状態 ・確認した公式の出所

| 項目 | 値 |
|---|---|
| branch ／ HEAD | `claude/investment-intelligence-phase6` ／ `07e62c7d837716a8277b696f8e5e31ac53f1a58c`（clean） |
| 凍結の anchor | A1 `4162e9c` ／ A1R `e6a750f` ／ A2 `b686b00` ／ A2R `4d3540c` ／ A3A `84c2d52` ／ A3B `d8845f2` ／ A3R `f1c4a4e` ／ ST1 `e831996` ／ ADP0 `a2ccc1c` ／ EXE `5ec466b` ／ ID1 `6b5f0e6` ／ ID2 `07e62c7` すべて ancestor |

| ID | 出所（公式） | URL | 確認日 | 内容 |
|---|---|---|---|---|
| L1 | J-Quants API サービス利用規約（改定 2026-01-19） | `https://jpx-jquants.com/termsofservice` | 2026-09-29 | 第7条 データの廃棄 ・第8条 利用目的 ・第11条 禁止事項 ・第13条 権利帰属 ・第15条 退会 ・第17条 免責 |
| L2 | FAQ「利用目的およびデータの利用について」 | `https://jpx-jquants.com/ja/help/usage` | 2026-09-29 | 私的利用の定義 ・第三者 ・app ・cloud 保存 ・生成 AI ・解約後 |
| L3 | FAQ「データについて」 | `https://jpx-jquants.com/ja/help/data` | 2026-09-29 | 普通株の判別（5 桁目）・上場廃止 ・定期の再取得の推奨 |
| L4 | FAQ「サービスについて」 | `https://jpx-jquants.com/ja/help/about` | 2026-09-29 | plan ごとの rate limit（Light 60 回／分）・更新時刻 |
| L5 | 上場銘柄一覧 `/v2/equities/master` 仕様 | `https://jpx-jquants.com/ja/spec/eq-master` | 2026-09-29 | 14 欄 ・上場日 ／ 廃止日 ／ code 変更の履歴なし ・83010 ／ 84210 の例外 |
| L6 | 市場区分コード及び市場区分名 | `https://jpx-jquants.com/ja/spec/eq-master/marketcode` | 2026-09-29 | 10 値 |
| L7 | 商品区分コード及び商品区分名 | `https://jpx-jquants.com/ja/spec/eq-master/product-category` | 2026-09-29 | 8 値 ・留意点（011 は優先株を含む ・ETN ／ インフラファンドの区分なし） |
| L8 | 契約ごとに利用可能な API とデータ格納期間 | `https://jpx-jquants.com/ja/spec/data-spec` | 2026-09-29 | Light: 上場銘柄一覧 ・財務情報とも 5 年前まで |

J-Quants Pro（法人 ・学術 ・外部配信向け）は対照としてだけ言及し、本 project の対象ではない。

---

## 2. 規約の行列（個人向け J-Quants API）

| 論点 | 分類 | 根拠（短い抜粋 ・出所） |
|---|---|---|
| 個人の私的な投資分析 | **EXPLICITLY_ALLOWED** | 「私的利用とは、ご自身の投資分析のための利用やポートフォリオ管理等を指します」（L2）。「登録ユーザーのみによる私的使用の目的に限ります」（L1 第8条 1） |
| 取得 data の local 保存 | **EXPLICITLY_ALLOWED** | 「ご本人のみが閲覧可能な状態であれば…保存も可能です。保存するデータの数・保存場所について個別の指定はありません」（L2）。契約期間中に限る（L1 第7条） |
| 変換 ・派生の record の保存 | **EXPLICITLY_ALLOWED**（解約時の削除の義務つき） | 「元データを復元（リバースエンジニアリング）できる派生物の削除をお願いいたします。元データを復元できない派生物は、外部に配信・公開しない限り削除は不要です」（L2） |
| API data を AI ／ LLM service へ入力 | **EXPLICITLY_ALLOWED**（4 条件）＋ 条件の充足は **UNCLEAR_REQUIRES_CONFIRMATION**（service ごと） | 「①ご自身の分析目的 ②入力したデータが AI の学習に二次利用されない設定 ③入力したデータを第三者が閲覧できない ④生成された結果を配信・公開しない」（L2）。条件の充足は「生成AIサービス側の規約・学習利用設定・データの取扱い」を本人が確認（L2） |
| 本 project（private の daily-market-brief）内での利用 | private の研究 ・pilot: **EXPLICITLY_ALLOWED** ／ 公開 Pages ・Morning Brief への統合: **EXPLICITLY_PROHIBITED** | 前者は私的利用の定義（L2）。後者は「継続反復して第三者に提供・配信する行為は私的利用に該当しません」（L2）・「第三者が使用できる状態にすること（インターネット上での配信を含みます。）…は、私的使用の目的に該当しません」（L1 第8条 2。編集 ・加工した物を含む） |
| cloud での処理 ・保存 | **EXPLICITLY_ALLOWED**（本人が管理 ・本人だけが閲覧 ・access 制御 ／ 暗号化は本人の責任） | 「ご本人が管理する外部クラウドへの保存も可能です…アクセス制御や暗号化などの管理はご自身の責任で」（L2）。**本人が管理しない** cloud（例: 他社の AI service の session）は AI の 4 条件に従う → UNCLEAR |
| 第三者の access | **EXPLICITLY_PROHIBITED** | 「本データを第三者が閲覧できる状態である時には私的利用には該当しません」（L2）・第8条 2（L1） |
| raw data の公開 | **EXPLICITLY_PROHIBITED** | 「J-Quants APIで取得したデータそのものを閲覧できる形で配布・シェアすることは禁止」（L2） |
| 派生の分析の公開 | 単発: **EXPLICITLY_ALLOWED** ／ 継続反復: **EXPLICITLY_PROHIBITED** | 「分析結果（チャート・グラフ・レポート等）の共有は可能です。ただし、分析結果を『継続反復的に』公開・共有される場合は私的利用と認められません」（L2） |
| application を通じた提供 | **EXPLICITLY_PROHIBITED**（本 project の形態）／ 例外: 各 user が自分の key で取得し本人以外に開示しない構成 | 「J-Quantsデータそのものや分析結果をユーザー間で共有・公開する機能」「運営者側のサーバーに J-Quants 由来のデータが蓄積・中継される構成」は禁止（L2） |
| 自動の定期の取得 | **EXPLICITLY_ALLOWED**（rate limit ・過度な負荷の禁止の下で） | 「お客様側で定期的に取得してください」「必要な範囲のデータを定期的に再取得いただくことを推奨」（L3）。Light 60 回／分（L4）。「過度な負荷をかける行為」は禁止（L1 第11条 1 (5)） |
| downgrade ・解約 ・退会の後の保持 | **EXPLICITLY_PROHIBITED**（data ・複製 ・復元可能な派生物）／ 復元不能な派生物は公開しない限り可 | 「ただちに本データ及びその複製物を全て廃棄若しくは消去」（L1 第7条 ・第15条 5）。「プラン変更後には…上位プランで取得したデータ利用はできません」（L2） |

沈黙を許可に読み替えていない。分類が ALLOWED でも、私的利用の枠（本人だけ ・公開しない）の中でだけ成り立つ。

---

## 3. OBS-58 ・OBS-59 の処置

| ID | 問い | 処置 | 根拠 |
|---|---|---|---|
| **P8-OBS-58** | 継続反復の第三者への提供は私的利用でない。本 project は継続して公開する | **CLOSED_CONFIRMED_PROHIBITED_FOR_PUBLIC_OUTPUT**。J-Quants 由来の raw ・派生（指標 ・注記 ・identity の写しを含む）を公開 Pages ・Morning Brief ・第三者 ・外部 app に載せない。private の研究 ・pilot は許される | L2「継続反復して第三者に提供・配信する行為は私的利用に該当しません」・L1 第8条 2（編集 ・加工した物を含む） |
| **P8-OBS-59** | 解約 ・downgrade 時の削除の義務 | **CLOSED_WITH_DISPOSAL_PROCEDURE_REQUIRED**。削除の対象 ＝ 取得した data ・複製 ・**元 data を復元できる派生物**。A1 の写し（社名 ・code）・A2 の観測（報告値そのもの）・注記 ・保留 ・provider の digest は「複製 ／ 復元可能」に当たると保守的に扱い、**private の data root を丸ごと廃棄**する運用の手順（§7.3）を持つ。指標（比率）は元の値を復元できうる（分母が既知）ので同じ扱い | L1 第7条 ・第15条 5、L2「元データを復元（リバースエンジニアリング）できる派生物の削除」 |

両方とも公式の文書が問いを解いたので CLOSED。CLOSED は「許された」ではなく「境界が確定した」の意味。

---

## 4. private PILOT2 の判断

**PRIVATE_PILOT_ALLOWED_BY_DOCUMENTED_TERMS** — 次の条件をすべて満たす限り。

| 条件（監督の指示） | 規約上の対応 | 根拠 |
|---|---|---|
| 本人の J-Quants Light account | 登録ユーザー本人の私的使用（第8条 1） | L1 |
| 本人の私的な投資研究 ・第三者への配布なし | 私的利用の定義に合致 | L2 |
| 公開 Pages ・Morning Brief への統合なし | OBS-58 の firewall（§9） | L1 第8条 2 ・L2 |
| raw の応答の永続なし（memory だけ）・正準の bounded な record だけ保存 | 保存は本人だけが見られる状態で可。削除の義務の対象を最小にする | L2 |
| credential の非露出 | 第5条（API key の管理は本人の責任） | L1 |
| API request 最大 8 ・1〜3 発行体 | 「過度な負荷」に当たらない（Light 60 回／分） | L1 第11条 1 (5) ・L4 |
| **外部の LLM ／ provider に J-Quants の payload を渡さない** | AI の 4 条件の②③の確認を要しないので、最も安全。**本 Claude Code の cloud session で live の payload を扱うことは、この条件に反する（AI service へ入力すること）ので行わない** | L2 |
| 実行の場所 | 本人が管理する環境（本人の PC、または本人が管理し本人だけが見られる cloud）。凍結の runtime（ADP0 ・EXE ・ID1 ・ID2）と private の data root を本人の環境で動かす | L2「ご本人が管理する外部クラウド」 |

補足: 生成 AI への入力は規約上 4 条件で許されるが、条件②③（学習に使われない設定 ・第三者が見られない）の充足は AI service の規約に依り、
本 gate では確認できない → **UNCLEAR_REQUIRES_CONFIRMATION**。PILOT2 はこの経路を使わない設計（上の条件）で、確認を要しない。

---

## 5. 市場区分 ・商品区分の写し（V2 の現在の契約）

### 5.1 正しい契約

「S04」は P8-JQUANTS の公式仕様の検証で市場区分の page に付けた**出所の番号**で、V2 の欄の名前ではない。live の bootstrap の対象
endpoint `/v2/equities/master`（L5）で普通株の国内上場銘柄を絞る契約は次の 3 つ:

1. `Mkt`（市場区分コード。L6 の 10 値）・`MktNm`（名前）
2. `ProdCat`（商品区分コード。L7 の 8 値。「全期間・全銘柄で収録されており欠損はありません」）
3. `Code` の 5 桁目（予備コード。「普通株式は『0』」。L3 ・L5。「011：内国株券」には優先株式等も含まれるため、商品区分のみで国内普通株式を抽出
   することはできない。L7）

### 5.2 `Mkt` の写し

| `Mkt` | 名称（公式） | 分類 | 理由 |
|---|---|---|---|
| 0111 | プライム | **SUPPORTED_FOR_INITIAL_BOOTSTRAP** | 現行の市場区分（2022-04-04 以後） |
| 0112 | スタンダード | **SUPPORTED_FOR_INITIAL_BOOTSTRAP** | 同上。日本銀行（83010）・信金中央金庫（84210）は制度上の区分が無いが J-Quants はスタンダードで返す（L5）→ 5 桁目 `0` ・ProdCat 011 なら機械の提案に入る。**人の審査で確認**（普通の株式会社ではない） |
| 0113 | グロース | **SUPPORTED_FOR_INITIAL_BOOTSTRAP** | 現行の市場区分 |
| 0105 | TOKYO PRO MARKET | **HOLD** | 特定投資家向け市場。初期の範囲外 |
| 0109 | その他 | **HOLD** | ETF ・REIT 等の受け皿。普通株の国内上場銘柄が入ることは想定しない。現れれば人の審査 |
| 0101 ／ 0102 ／ 0104 ／ 0106 ／ 0107 | 東証一部 ／ 二部 ／ マザーズ ／ JASDAQ スタンダード ／ グロース | **NOT_APPLICABLE**（D0 が 2022-04-04 以後の snapshot に現れない）。現れたら **HOLD** | 再編前の区分。過去日の snapshot でだけ返る |

### 5.3 `ProdCat` の写し

| `ProdCat` | 名称（公式） | 分類 | 理由 |
|---|---|---|---|
| 011 | 内国株券 | **SUPPORTED_FOR_INITIAL_BOOTSTRAP**（5 桁目 `0` と組み合わせて） | 優先株式等を含むので単独では不十分（L7） |
| 012 | 優先出資証券 | **NOT_APPLICABLE**（除外） | 普通株ではない |
| 013 | REIT | **NOT_APPLICABLE**（除外） | ID1 の範囲外。A2R でも REIT の DocType は OUT_OF_SCOPE |
| 014 | ETF | **NOT_APPLICABLE**（除外） | 発行体の財務諸表の対象ではない |
| 021 | 外国株券 | **NOT_APPLICABLE**（除外） | 外国の発行体。会計基準 ・通貨の方針の外（D4） |
| 022 ／ 023 ／ 024 | 外国 REIT ／ 外国 ETF ／ 外国株預託証券 | **NOT_APPLICABLE**（除外） | 同上 |
| （ETN ・インフラファンド） | 区分なし（L7） | **HOLD** | 直接示す区分が無い。`Mkt` `0109` と名前で人が見る |

### 5.4 凍結 ID1 との差（要 gate）

凍結 ID1 の `MasterRow` は `Date` ・`Code` ・`CoName` ・`CoNameEn` ・`Mkt` だけを読み、`ProdCat` は捨てる。`Mkt ∈ {0111, 0112, 0113}` かつ
5 桁目 `0` の条件は、**外国株券（021）・外国株預託証券（024）** の除外を保証しない（Prime ／ Standard に上場し 5 桁目 `0` を持ちうる）。
ETF ・REIT は `Mkt` `0109` で落ちる見込みだが、公式の対応表は無い（L7「市場・商品区分との公式な対応表は提供していません」）。

→ **P8-ID1B（提案）**: `MasterRow` に `ProdCat` を必須の欄として足し、`ProdCat != "011"` を `HELD / PRODUCT_CATEGORY_UNSUPPORTED` にする。
凍結 ID1 の変更なので監督の承認と別の gate が要る。**PILOT2（1〜3 発行体）ではこの gate を待たず、人の審査の checklist（§7.2）で
`ProdCat == 011` を確かめる**。1〜3 発行体より広い live の bootstrap は ID1B の後。これは mapping の blocker ではなく、実装の gate の要件。

---

## 6. `accepted_at` の運用の手順（code なし）

| 項目 | 手順 |
|---|---|
| 意味 | **人の審査の event の時刻**（manifest を読み、APPROVE ／ REJECT ／ DEFER を確定した瞬間）。provider の有効時間でも D0 でも取得の時刻でもない。A1 の `known_at` になる |
| 誰が渡すか | 審査した人（本 project では監督 ＝ ChatGPT の判断を受けて user 本人が確定する。reviewer class は `HUMAN` だけ） |
| timezone | **aware** な datetime。JST（`+09:00`）で記録し、直列化は A1 の規則で UTC の ISO 8601 になる。naive は ID1 の model が拒む |
| 形式 | ISO 8601（例 `2026-07-01T18:05:00+09:00`）。分の精度で足りる。秒は 0 でよい |
| いつ記録するか | manifest の `manifest_digest` を人が確認し、各提案の disposition を決めた**直後**。取得の時刻 ・ID2 の実行の時刻ではない |
| manifest との結びつき | `ReviewedManifest(manifest_digest, reviews[(proposal_id, proposal_digest, disposition)], accepted_at)` → `reviewed_digest`。この 4 つの値を人の審査の記録（private。repo の外）に書き留める |
| 欠落 ／ naive ／ 変更 | 欠落 ・naive → `ReviewedManifest` が作れない（拒否）。後で値を変えれば `reviewed_digest` が変わり、A1 の provenance（`review:<batch>.<digest24>`）と `known_at` が変わる → ID2 は新しい reviewed manifest として扱い、既存の登録は identity の事実の一致で再利用、出所の差は事実の差ではない。ただし **A1 の最後の `known_at` より前の値は `KNOWN_AT_NOT_MONOTONIC` で拒否** |
| replay | 同じ manifest ・同じ reviews ・同じ `accepted_at` を渡すこと（審査の記録から読み戻す）。ID2 は `REUSED`。自動の timestamp は無い（ID1 ・ID2 とも時計を読まない。boundary の guard） |
| 保管 | 審査の記録（manifest の JSON ・reviews ・accepted_at）は private の data root の隣に置く（repo ・Pages には置かない）。J-Quants 由来の社名を含むので OBS-59 の廃棄の対象 |

---

## 7. live の identity bootstrap の手順（将来の運用の列。自動の承認なし）

### 7.1 列

1. **前提**: 本人の環境。本人の API key は環境変数 ・secret 保管から読み、log ・print ・repo に出さない。private の data root（例: 本人だけが読める
   directory）に `IdentityStore.initialize` ・`ObservationStore.initialize` ・`SemanticMetadataStore.initialize` ・`HeldObservationStore.initialize`
   を 1 度だけ行う（既にあれば開くだけ）。
2. **live の master の取得**（request 1）: `GET /v2/equities/master?date=D0`。応答は memory だけ。file ・log ・cache に書かない。取得の時刻を控える。
3. **memory だけの bounded な parse**: 応答の各行から ID1 の 5 欄 ＋ **`ProdCat`** を人が見られる一覧（memory ／ 画面）にし、pilot の対象の
   1〜3 の code だけを ID1 の `MasterRow` に渡す（他の行は捨てる）。`ProdCat == "011"` ・5 桁目 `0` ・`Mkt ∈ {0111,0112,0113}` を人が確認する。
4. **ID1 の提案**: `propose_bootstrap(rows, BootstrapBatch(batch_id="p8boot1", d0=D0, supported_markets=("0111","0112","0113")))`
   → manifest。`manifest_digest` を控える。
5. **人の審査**: §7.2 の checklist で各提案を見る。APPROVE ／ REJECT ／ DEFER を決め、**`accepted_at` を記録**（§6）。
   `review_manifest(manifest, reviews, accepted_at=…)` → `reviewed_digest` を控える。
6. **ID2 の実行**: `execute_identity_registration(rows, batch, reviewed, data_root)`。結果が `APPENDED`（初回）／ `REUSED`（replay）以外なら止まる。
   `REJECTED` の理由 code を記録し、人が判断する。
7. **A1 の状態の確認**: `IdentityStore.open(data_root)` の `counts()` と、対象 code の `IdentifierAssignment` → `security_id` → `issuer_id` を控える。
   これが後の `AdapterContext.issuer_id` になる（Code から作らない）。
8. **その後だけ** 財務の取り込み（§8）。

### 7.2 APPROVE の前に人が見る checklist

- 行の `Date` が D0 と同じ。`Code` が 5 桁 ・数字 ・5 桁目 `0`。`ProdCat` が `011`。`Mkt` が `0111` ／ `0112` ／ `0113`。
- `CoName` が対象の会社の正式名で、空 ・placeholder でない。`CoNameEn` は空でもよい。
- 同じ先頭 4 桁の別の code が snapshot に無い（あれば ID1 が HUMAN_REVIEW_REQUIRED にする。承認しない）。
- 対象が普通の株式会社（日本銀行 ・信金中央金庫のような例外でない）。
- 過去に code の変更 ・上場廃止 ・再上場の疑いが無い（JPX の上場廃止銘柄一覧を人が見る。ID1 は A1 の状態からだけ疑いを出す）。
- 提案の `issuer_anchor` ・`security_anchor` が `p8boot1:iss.<Code>` ・`p8boot1:sec.<Code>` で、id が anchor から導かれている。
- `manifest_digest` が、自分が読んだ manifest のものと一致する。
- code の変更 ・廃止 ／ 再上場 ・複数の上場物 ・合併 ・同名の別会社は**自動の経路に載せない**（DEFER し、A1R の訂正の手順へ）。

### 7.3 廃棄の手順（OBS-59）

解約 ・退会 ・downgrade の請求対象期間の終了の時点で: private の data root（A1 ・A2 ・注記 ・保留の journal）・審査の記録（manifest ・reviews）・
memory 以外に残った一時 file を**丸ごと削除**し、その事実（日時 ・削除した path の一覧の件数）を private の運用記録に残す。runtime は削除の
機能を持たない（append-only）。廃棄は運用者の操作であって、authority の record の削除ではない。復元できない派生物（例: 公開しない集計の
所感）だけ残してよい。

---

## 8. PILOT2 の契約（提案）

| 項目 | 内容 |
|---|---|
| 発行体 | 1〜3。JP_GAAP ・連結 ・3 月期 ・普通株 ・Prime ／ Standard ／ Growth。人が選ぶ（例示の code は本書に書かない） |
| request の予算 | **最大 8**。内訳: master 1（`/v2/equities/master?date=D0`）＋ fins 1 発行体あたり 1〜2（`/v2/fins/summary?code=<Code>`。pagination が要れば 2）＝ 3 発行体で最大 7。予備 1。**8 を超えたら止める** |
| endpoint | `/v2/equities/master` ・`/v2/fins/summary` だけ。株価 ・指数 ・他は使わない |
| 順序 | master → ID1 → 人の審査 → ID2 → A1 の確認 → fins（発行体ごと）→ ADP0 → EXE（発行体ごと）→ 指標（A3A ・A3B。memory）→ private の所感 |
| 保持する欄 | master: ID1 の 5 欄（＋ 人の確認に `ProdCat`。保存しない）。fins: ADP0 の 14 欄（`Code` `DiscDate` `DiscTime` `DiscNo` `DocType` `CurPerType` `CurPerSt` `CurPerEn` `CurFYSt` `CurFYEn` `Sales` `OP` `NP` `TA`） |
| 捨てる欄 | master の他 9 欄、fins の他 97 欄（予想 ・配当 ・EPS ・BPS ・CF ・株式数 ・NC 系 …） |
| raw の応答の寿命 | process の memory の中だけ。ADP0 ／ ID1 に渡した後は参照を捨てる。file ・log ・cache ・test fixture ・repo ・artifact に書かない |
| identity の登録 | §7 |
| 財務の観測 | 行ごとに `execute_financial_summary_row(row, AdapterContext(issuer_id=<A1 の id>, acquired_at=<取得の時刻>), data_root)`。ELIGIBLE の JP_GAAP ・連結だけが A2 に入る。IFRS 等 ・4Q ・不正は HELD |
| A2R の意味 | 凍結の `map_row_semantics`（DocType の写し）だけ。基準の橋渡しなし |
| EXE | 凍結の executor。`APPENDED` ／ `REUSED` ／ `HELD` ／ `REJECTED` ／ `PARTIAL_FAILURE` を記録。PARTIAL は再実行で収束を確認 |
| 後で計算する指標 | `revenue_growth` ・`operating_margin` ・`net_margin` ・`roa_point_in_time`（凍結 A3A ・A3B。memory。保存しない） |
| 公開の出力 | **無し**。Pages ・Morning Brief ・artifact ・第三者へ出さない |
| 成功の基準 | (a) 8 request 以内で master 1 ・fins 各 1 が取れる；(b) ID2 が `APPENDED`、replay が `REUSED`；(c) 各発行体の直近 FY と 1 つ前の FY の 4 欄が ADP0 で ELIGIBLE になり EXE で `APPENDED`、replay が `REUSED`；(d) 4 指標のうち少なくとも `operating_margin` ・`net_margin` が `VALUE`、`revenue_growth` が 2 期あれば `VALUE`；(e) HELD になった行の理由がすべて閉じた code で説明できる；(f) raw が どこにも残らない（data root の file は 4 journal だけ）；(g) 指標の値を人が決算短信（公開情報）と目で照合して一致（1〜3 発行体の点の確認） |
| 失敗の基準 | 凍結層の defect（例外 ・不変条件の破れ）、request の超過、raw の残留、A1 ／ A2 の不整合、指標の不一致（写しの誤り）。→ 該当の gate の DEFECT として報告 |
| 主張しないこと | 母集団の精度 ・再現率 ・網羅性。1〜3 発行体の点の検証だけ |

---

## 9. 公開の firewall（恒久）

private の pilot の結果に関わらず、**J-Quants 由来の公開 ・第三者向けの出力は、公式の規約が別に許すか JPXI の明示の許可があるまで無効**:
Pages の統合なし ・公開 Morning Brief の統合なし ・顧客向けの出力なし ・外部の application ／ service なし ・第三者への配布なし。
凍結 runtime は Pages ・reports ・narrative ・themes を import しない（boundary の guard `FORBIDDEN_MODULE_TOKENS`）。将来 J-Quants の
data を触る code が公開の経路に繋がる変更は、監督の明示の承認と本書の改定が要る。

---

## 10. AI ／ LLM ・cloud の境界

- **AI ／ LLM**: J-Quants の payload（raw ・14 欄 ・5 欄 ・そこから導いた値）を外部の LLM ／ AI service に入れない（PILOT2 の条件）。
  本 project の LLM を使う経路（narrative ・brief）は J-Quants 由来の data を受けない。規約上は 4 条件で許されるが、条件②③の確認を要する
  ので使わない。**本 Claude Code の cloud session で live の payload を扱わない**（session は AI service への入力に当たる）。
- **cloud**: 本人が管理し本人だけが見られる環境なら保存 ・処理は可（access 制御 ・暗号化は本人の責任）。GitHub の repo ・Actions の artifact ・
  Pages は第三者が見られる ／ 本人が管理しない → 置かない。

---

## 11. 未解決の規約の問い

1. 「元データを復元できる派生物」の線引きは J-Quants が個別判定しない（L2）。本 project は保守的に private の data root を丸ごと廃棄する。
2. 生成 AI の条件②③の充足（service ごと）。PILOT2 は使わないので保留。
3. 本 project が将来、公開の brief に J-Quants 由来の物を載せる道は、規約上は無い（J-Quants Pro ＝ 法人向けの別契約）。個人の user のままでは閉じている。
4. 法人格 ・共同利用の疑いを生む構成（複数人が data root を見る）は避ける。

---

## 12. 変更の範囲

| 対象 | 状態 |
|---|---|
| `docs/databank/PHASE8_LIVE0_PRELIVE_AUDIT.md` | **新規**（本書） |
| `tests/intelligence/phase8_runtime_registry.py` ・`test_screener_intelligence_boundary.py` | 本書の登録（PHASE8_DOCS ・先行の anchor の guard の除外の tuple）だけ。runtime の登録なし |
| 凍結 runtime 27 module ・Phase 8 の test ・先行の記録 | 無変更 |

---

## 13. GO ／ NO-GO

**条件つき GO**（PILOT2）:

1. 実行は本人の環境（本 cloud session の外）。API key は本人だけが持つ。
2. 対象 1〜3 発行体は人が選び、`ProdCat == 011` を §7.2 で確かめる（ID1B の前の代替）。
3. request 8 以内。raw は memory だけ。data root は private。
4. 公開の firewall（§9）を守る。J-Quants の payload を LLM に入れない。
5. 廃棄の手順（§7.3）を運用記録に持つ。
6. 1〜3 発行体より広い bootstrap は **P8-ID1B（`ProdCat` の必須の適格）** の後。

**推奨の次 gate**: P8-ID1B（凍結 ID1 への `ProdCat` の追加。監督の承認つき）→ P8-LIVE1（live の取得 client: memory だけ ・request の予算 ・
credential の境界 ・retry なし ／ 1 回。合成の transport で test）→ PILOT2（本人の環境で実行し、結果の要約だけを報告）。

## 14. 判定

**P8_LIVE0_PRIVATE_PILOT_READY / READY_FOR_SUPERVISOR_REVIEW**
