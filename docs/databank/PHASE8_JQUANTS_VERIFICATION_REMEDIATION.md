# PHASE 8 / P8-VR — J-QUANTS VERIFICATION REMEDIATION

P8-V（部分の確認の記録。凍結）の結論を、監督が確かめた公式の JPX の証拠（SV-01〜SV-08）で突き合わせ直す **証拠の整理だけ** の
gate。実装 ・adapter ・取り込み ・identity の登録 ・live ／ 認証つきの J-Quants は無い。P8-V の文書は書き換えない。

- 基準: P8-V `fc91ee17d3ad32bf0ab04b4ea49e2b2c47fa9ba4`（凍結）、P8-A2.5 `5713a56`、P8-A2 `b686b00`、P8-A1 `4162e9c`。runtime と先行の
  監査の文書は byte 一致。
- 変更: 本書（新規）・`CHANGELOG.md` ・文書の登録と凍結の証明に要る Phase 8 の registry と guard だけ（§13）。

---

## 0. 結論

1. **製品を分ける。** A ＝ 個人向けの J-Quants API（Light）、B ＝ J-Quants Pro、C ＝ JPX の元の data の一般の意味。**B の仕様を A の欄の
   契約として扱わない。** 監督の証拠のうち A に直接当たるのは SV-01 ・SV-02（過去の plan の資料）だけで、SV-03〜SV-08 は B。
2. **調整後価格の方針を VERIFIED_POLICY_SUPPORT に上げる**（SV-03）: 業者の調整値の履歴は遡って変わり得る。生値の観測を PIT の一次の
   入力とし、後から取った調整値の履歴を過去の時点で知り得たものとして使わない。前向きに取った版は実際の取得 ／ 知識の出所つきで
   だけ保つ。調整の engine はまだ作らない。
3. **財務の改訂は版を保つ方針のまま**（SV-04 が、業績 ・配当の修正の開示が財務情報の領域に含まれることを確かめた）。Light の改訂の
   仕組みは未解決。
4. **P8-V の行き過ぎを訂正する**: 規約 ・公開の懸念は問いとして正当だが、「public な repository が J-Quants の規約に反し得る」に当たる
   記述は**確定した事実として扱わない**。分類は `INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED`（個人向けの規約の本文を直接読むまで）。
   Pro の data-license を Light に当てない（SV-08）。
5. **A1R は維持する。** master ・corporate action の証拠（SV-05 ・SV-07。どちらも Pro）は過去の master の意味論が要ることを支えるが、
   P8-OBS-10 ・11 ・12 ・18 ・29 を消さない。
6. Light で直接確かめる事を LUV-01〜LUV-27 に絞った（§8）。**A3 の実データの写しは 0**（売上成長率 ・営業利益率は合成 data だけ）。
7. **A1R は LUV に依存しない**（§11）: 訂正 ・遡及の意味論は財務の欄にも Light の master の詳細にも依らない。LUV は A1R の後の
   実の登録（本 gate の範囲外）と A3 の実データ ・adapter に効く。推奨の順は P8-VR → P8-A1R → Light の仕様 ／ pilot の完了 → A3 →
   最小の adapter → 実データの検証（§12）。
8. 判定: **P8_VR_REMEDIATION_COMPLETE / READY_FOR_P8_A1R**（§14）。

---

## 1. 範囲と製品の区別

| 記号 | 製品 ／ 領域 | 本 project での位置 |
|---|---|---|
| A | 個人向けの J-Quants API（Light plan） | 本 project が契約して使う（repo の実測は 2026-09-01〜02 の Light） |
| B | J-Quants Pro（法人向け。独自の data-license と外部配布の枠組み） | 使っていない。**仕様を A に移さない** |
| C | JPX の元の data の一般の意味（例: 調整の考え方、開示の領域） | A と B の共通の背景。A の欄の形は決めない |

規則: B の文書が述べる性質は、「元の data にその性質があり得る」ことの根拠（C）にはなるが、「A の欄がその形 ・意味で配られる」ことの
根拠にはしない。A の欄の契約は A の文書か A の実測（repo）でだけ決める。

---

## 2. 監督の証拠の台帳（SV-01〜SV-08）

監督が外部で確かめた公式の証拠として扱う（発行: 日本取引所グループ ／ J-Quants）。本 session はこれらの page を開いていない
（P8-V と同じ network の制約）。URL ・節は監督の記録に従う。

| id | 内容（言い換え） | 製品 | 確かにした事 | 確かにしていない事 |
|---|---|---|---|---|
| SV-01 | JPX は J-Quants API を、過去の株価 ・企業の財務の data を API で配る個人向けの service と説明する | A | service の性質 | 欄の契約 |
| SV-02 | 公式の過去の plan の資料で、Light に上場銘柄情報 ・日次の四本値 ・財務情報 ・決算発表予定 ・投資部門別 ・TOPIX の四本値が含まれ、5 年分の data と案内されていた | A（過去の資料） | 当時の Light の dataset の構成と案内された期間 | **2026 年の現在の entitlement と深さ**（現在の文書か口座の実測が要る） |
| SV-03 | Pro の株価の文書: 調整の前 ・後の価格と調整係数を配る。corporate action に合わせた調整は遡って行う | B | 元の data の調整は遡る（C の根拠） | Light の調整値の欄 ・仕組み |
| SV-04 | Pro の財務サマリー: 上場会社の四半期の決算の要約と、業績 ・配当の修正の開示を含む。日次で配り、REST は当日のほぼ即時 | B | 財務の領域が改訂 ・開示に敏感（C の根拠） | Light の欄の契約 ・改訂の仕組み |
| SV-05 | Pro の上場銘柄情報: 社名 ・code ・市場区分 ・業種 ・信用 ／ 貸借の区分など。過去の情報と翌営業日の情報を含む | B | 元の data に過去の master の情報がある | IssuerId の継続 ・code の再利用の意味 ・Light の深さ |
| SV-06 | Pro の上場株式数の速報: 発行 ／ 上場株式数は corporate event の後に更新され、一部の過去の data は報告に基づき更新される | B | 株数の履歴は改訂に敏感（C の根拠） | Light の財務サマリーの株数の欄の意味（**写さない**） |
| SV-07 | Pro の corporate action の data: 分割 ・併合 ・合併 ／ 株式交換 ／ 株式移転 ・社名の変更 ・売買単位の変更 ・上場廃止 ・銘柄の master の変更を別に表す | B | 過去の identity ／ 母集団の再構成には明示の corporate action ／ master の履歴が要る、という設計の結論を支える | Light にこの dataset があること |
| SV-08 | Pro には独自の data-license の契約と外部配布の枠組みがある | B | Pro の license は Pro のもの | **Light の規約**（当てない） |

---

## 3. P8-V の行き過ぎの訂正

P8-V（`fc91ee1`）は凍結で書き換えない。以下を本書で訂正する。

| P8-V の箇所 | 記述の要旨 | 訂正 |
|---|---|---|
| §0 の 4 ・§12 の表 ・§12 の注記 | 規約の手掛かり（L20）と、本 repository が public であることを並べ、公開の経路を確認の対象にした | 問いとしては正当。**違反の可能性を確定した事実として扱わない。** 分類は `INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED` |
| P8-OBS-36 | 規約の手掛かりが、raw snapshot ・A2 の store ・public な repository の Actions の artifact ／ log ・出力の公開（project 全体）に関わる | 同上。関わるかどうか自体が個人向けの規約の本文の確認待ち。P4 の producer の workflow は公開しないと明記している（repo の事実） |
| D-P8-V-2 の推奨 ・最終報告 | 既存の出力を含む project 全体を確認の対象にするかは監督の判断、とした | 確認は個人向けの規約の本文（LUV-23 ・LUV-24）で行う。本書は既存の出力について何も結論しない |
| L20 | 個人向けの help ／ 規約の page に由来すると記録した手掛かり | 未検証のまま。Pro の license（SV-08）の内容と混ざっていないことも確かめていない。規約の根拠にしない |
| L15 | 調整値が遡る記述を個人向けの API の page に由来すると記録した | 検索の結果に Pro の page が含まれていた。**遡ることは SV-03（Pro）で確かめられたが、Light の文書での確認ではない。** 方針（§5）は Light の文言に依らない |
| L09 ・L11 ・L19 | Premium ／ Pro の説明を含む手掛かり（更新時刻、提供開始日、予定の更新） | 製品の範囲が混ざり得る。Light の契約に使わない（P8-OBS-40） |

P8-V の判定（PARTIAL）と「OFFICIALLY_VERIFIED は 0」は変わらない。

---

## 4. 検証済み ／ Pro のみ ／ Light 未解決 の matrix

| 論点 | A（Light） | B（Pro） | C（JPX 一般） | Phase 8 への帰結 |
|---|---|---|---|---|
| service の性質 | VERIFIED（SV-01） | — | — | 個人向けの API として扱う |
| Light の dataset の構成 | 過去の plan の資料で VERIFIED（SV-02）。現在は REPO の実測（2026-09-01）と一致するが、現在の公式は未確認 | — | — | LUV-22 |
| 履歴の深さ | 過去に 5 年と案内（SV-02）。REPO: TOPIX は 5 年 ・10 年は拒否。現在は未確認 | — | — | LUV-21 |
| 調整後価格の遡及 | 未確認 | VERIFIED（SV-03） | 元の data の調整は遡り得る | **VERIFIED_POLICY_SUPPORT**（§5） |
| 財務の改訂 ・修正の開示 | 仕組みは未確認 | VERIFIED（SV-04） | 改訂 ・修正は財務の領域の一部 | 版を保つ方針を維持（§6） |
| master の過去の情報 | REPO: 過去日の 1 日を取得。深さ ・忠実さは未確認 | VERIFIED（SV-05: 過去 ・翌営業日） | 元の data に過去の master がある | A1R を維持。LUV-25 |
| IssuerId の継続 ・code の再利用 | 未確認 | 未確認（SV-05 は示さない） | — | A1R ・人の審査 ／ 他の authority |
| 株数の履歴の改訂 | 財務サマリーの株数の欄の意味は未確認 | VERIFIED（SV-06: 速報の dataset） | 株数は改訂に敏感 | LUV-15。Pro の株数を Light の欄に写さない |
| corporate action の事象 | Light にあるか未確認（REPO の台帳に無い） | VERIFIED（SV-07: 別の dataset） | 過去の identity の再構成に事象の履歴が要る | P8-OBS-24 ・A1R。LUV-26 |
| data の license ・公開 | 未確認 | VERIFIED（SV-08: Pro 独自） | — | `INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED`（LUV-23 ・24） |
| 財務の欄の意味（DiscTime ・期間 ・利益 ・持分 ・株数 ・単位 ・通貨 ・欠損） | 未確認 | 本書の範囲外 | — | LUV-01〜20 |

---

## 5. 調整後価格の方針（VERIFIED_POLICY_SUPPORT）

根拠: SV-03（Pro の文書: corporate action に合わせた調整は遡って行う）。Light が逆の保証（過去の調整値を変えない）を与えることは
どこにも示されていないので、保守の方針は Light の文言に依らず成り立つ。

- **生値の観測を PIT の一次の入力にする**（A2 の `RAW_REPORTED`）。
- **後から取った業者の調整値の履歴を、過去の時点で知り得たものとして使わない。**
- 前向きに取った調整値の版は、実際の取得 ／ 知識の出所（A2 の知識の時刻 ・`adjustment_ref`）つきでだけ保つ。
- 調整の engine は作らない（corporate action の入力の gate を待つ。P8-OBS-24）。

A2 は既にこの方針を構造で持つ（生値と調整値の別の鎖、調整値の計算の参照の必須、知識の時刻つきの revision）。runtime の変更は要らない。

---

## 6. 財務の改訂の方針

- **版を保つ**: 前に取った版を上書きしない。改訂は A2 の slot の revision として足す。
- SV-04 は、業績 ・配当の修正の開示が財務情報の領域にあることと、配信が当日のほぼ即時であることを確かめた（Pro）。元の data が改訂に
  敏感であることの根拠（C）。
- Light の改訂の仕組み（訂正開示の表し方 ・DiscNo の関係 ・過去の応答の変化）は未解決（LUV-19 ・LUV-20）。

---

## 7. identity の方針（A1R の維持）

SV-05 ・SV-07 は、過去の master と corporate action の事象の履歴が無ければ過去の identity ／ 母集団を確かに再構成できない、という
A2.5 の結論を支える。ただし次は消えない:

| 所見 | 残る理由 |
|---|---|
| P8-OBS-10 identity の訂正 ／ 統合 | 誤った bootstrap を取り消す record が A1 に無い |
| P8-OBS-11 遡及の mode | A1 は知識の時刻と有効時間を分けて解決できない |
| P8-OBS-12 実の登録の手順 | 発行体の識別子が Light に見つかっていない。人の審査 ／ 他の authority が要る |
| P8-OBS-18 identity の知識の時刻 | 後から作る authority で過去の観測を解決する規則が要る |
| P8-OBS-29 bootstrap の authority の穴 | 上場日の出所 ・anchor の割り当て ・発行体の識別子の scheme |

**A1R を省かない。**

---

## 8. Light で直接確かめる事（LUV）

依存の略: A1R ／ A3R（A3 の実データの写し）／ ADP（adapter）／ HIST（過去の screen）／ TERMS（保存 ・公開の経路）。

| id | 確かめる事 | 元の V | 依存 |
|---|---|---|---|
| LUV-01 | DiscTime の意味（実際の公表時刻か） | V01 | ADP ・HIST |
| LUV-02 | DiscTime の time zone | V01 | ADP |
| LUV-03 | DiscTime が無い時の挙動 | V01 | ADP |
| LUV-04 | CurPerType の値の全集合 | V04 | A3R ・ADP |
| LUV-05 | 財務の値が累計か単独か | V04 | A3R ・ADP |
| LUV-06 | 連結 ／ 単体 ・会計基準の表し方 | V03 ・V06 | A3R ・ADP |
| LUV-07 | 売上の意味（業種の例外を含む） | V03 | A3R |
| LUV-08 | 営業利益の意味と有無（会計基準 ・業種） | V03 | A3R |
| LUV-09 | 純利益の意味（帰属） | V08 | A3R |
| LUV-10 | 実績の EPS の意味（基本 ／ 希薄化 ・期間） | V08 | A3R |
| LUV-11 | 予想の EPS の意味（対象の年度 ・通期 ／ 中間） | V05 ・V08 | A3R |
| LUV-12 | 純資産 ／ 株主資本 ／ 自己資本の欄の意味（2 つの欄を 1 つにしない） | V07 | A3R |
| LUV-13 | 総資産の意味 | V07 | A3R |
| LUV-14 | 営業 CF の意味（期間 ・どの書類に載るか） | V10 | A3R |
| LUV-15 | 株数の欄の定義（発行済 ・自己株式 ・平均 ・基準日 ・種類） | V09 | A3R ・ADP |
| LUV-16 | 財務の値の単位 ・桁 | V11 | A3R ・ADP |
| LUV-17 | 財務の値の通貨（円以外の扱い） | V11 | A3R ・ADP |
| LUV-18 | null ／ 空 ／ key が無い の意味 | V12 | ADP |
| LUV-19 | 訂正開示の挙動（別の行か ・置き換えか） | V13 | ADP ・HIST |
| LUV-20 | 出所 ／ 開示の record の identity（DiscNo の一意性 ・安定性） | V02 | ADP |
| LUV-21 | 現在の Light の履歴の深さ（dataset ごと） | V21 | HIST ・ADP |
| LUV-22 | 現在の Light の entitlement の表 | §5（P8-V） | ADP |
| LUV-23 | 個人向け API の保存 ・cache の規約 | V22 | TERMS ・ADP |
| LUV-24 | 個人向け API の派生の出力 ・公開の規約 | V22 | TERMS |
| LUV-25【追加】 | Light の上場銘柄一覧の過去日の意味（深さ ・その日の状態の再現か ・code の形 ・発行体の識別子の有無） | V17 ・V18 | 実の identity の登録（A1R の後）・HIST |
| LUV-26【追加】 | Light に corporate action ／ 上場日 ・廃止日の情報があるか（調整係数のほか） | V17 ・§4 | 実の identity の登録 ・HIST |
| LUV-27【追加】 | Light の調整値 ・調整係数の意味（係数を corporate action の検知に使えるか） | V15 | 将来の corporate action の入力（P8-OBS-24） |

追加の 3 つは、A1R の後の実の登録と corporate action の入力が Light の何に依るかを明示するために要る。

---

## 9. 所見の処分の更新

語彙: P8-V の分類 ＋ 監督の分類 `VERIFIED_POLICY_SUPPORT` ・`INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED`。記載の無い所見は P8-V の
処分のまま（P8-OBS-8 は A2.5 で CLOSED）。

| id | 所見 | P8-V | 本書 | 理由 |
|---|---|---|---|---|
| P8-OBS-6 | master に上場 ／ 廃止の履歴が無い | STILL_UNRESOLVED | STILL_UNRESOLVED | SV-05 は Pro。Light は LUV-25 ・26 |
| P8-OBS-9 | 調整後価格の遡及 | PARTIALLY_RESOLVED | **VERIFIED_POLICY_SUPPORT** | SV-03（§5） |
| P8-OBS-10 ・11 ・12 ・18 ・29 | identity の方針 | IDENTITY_POLICY_REQUIRED | IDENTITY_POLICY_REQUIRED | §7。A1R |
| P8-OBS-17 | 真の公表時刻 | ADAPTER_REQUIRED | ADAPTER_REQUIRED | SV-04 が版を保つ方針を支える。LUV-01 ・19 |
| P8-OBS-23 | 株数の意味 | STILL_UNRESOLVED | STILL_UNRESOLVED | SV-06 は改訂の敏感さを強めるが Light の欄は LUV-15 |
| P8-OBS-24 | corporate action ／ 参照の入力 | ADAPTER_REQUIRED | ADAPTER_REQUIRED | SV-07 が設計の結論を支える。Light は LUV-26 ・27 |
| P8-OBS-32 | raw の保存の規約 | TERMS_REVIEW_REQUIRED | **INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED** | LUV-23。Pro の license を当てない |
| P8-OBS-33 | 履歴の深さ | STILL_UNRESOLVED | STILL_UNRESOLVED | SV-02 は過去の案内（5 年）。現在は LUV-21 |
| P8-OBS-35 | 公式の host が環境で拒否 | STILL_UNRESOLVED | STILL_UNRESOLVED | 監督の証拠で一部を補ったが、Light の文書は未読 |
| P8-OBS-36 | 規約と保存 ・公開の経路 | TERMS_REVIEW_REQUIRED | **INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED** | §3 の訂正。違反を確定した事実として扱わない |
| P8-OBS-40【新】 | P8-V の手掛かりに Pro ／ Premium の説明が混ざり得る（L09 ・L11 ・L15 ・L19 ・L20） | — | NON_BLOCKING_DEFERRED | 手掛かりに製品の範囲を付け、B の内容を A の契約に使わない |
| P8-OBS-41【新】 | 個人向けの規約が保存した data ・複製の削除を求める場合、追記専用の A1 ／ A2 の store に消去の仕組みが要り得る（条件つきの設計の問い） | — | INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED | LUV-23 の結果しだい。A1R の前提ではない（§11） |

---

## 10. A3 の準備度

**READY_FOR_REAL_MAPPING に上げる指標は無い。**

| 指標 | 分類 |
|---|---|
| 売上成長率 | READY_FOR_SYNTHETIC_A3 だけ（実データは LUV-04〜07 ・16 ・17） |
| 営業利益率 | READY_FOR_SYNTHETIC_A3 だけ（実データは LUV-04〜08 ・16 ・17） |
| その他（純利益率 ・EPS 成長率 ・ROE ・ROA ・PER ・PBR ・時価総額 ・return ・変動率 ・流動性） | P8-V の分類のまま（BLOCKED ／ DEFER） |

実データの写しは、それぞれの Light の欄の意味を確かめるまで止める。

---

## 11. A1R の依存の分析

A1R の要素（A2.5 §7 ・§8 ・§5 で挙げたもの）ごとに、LUV に依るかを見た。

| A1R の要素 | LUV への依存 | 注記 |
|---|---|---|
| record の取り消し | なし | 合成 data で設計 ・検証できる |
| Issuer の統合 ／ 別名 | なし | 同上 |
| Security → Issuer の対応の supersession | なし | 同上 |
| 継続の取り消し | なし | 同上 |
| 訂正の状態の status ・未来の訂正で過去の厳密の答えを変えない決定論 | なし | 同上 |
| 2 軸の遡及の解決（知識の cutoff ＝ 固定した版 R、有効時間 ＝ 過去の cutoff） | なし（model） | survivorship の対策に要る「過去の上場物の登録」は実の登録の時の事で、LUV-21 ・25 ・26 に依る |
| 「少なくとも D から上場」の表し方 | なし | Light に上場日が無い可能性（LUV-26）への備えで、確認の結果に関わらず他の出所にも使える |
| anchor の一括の割り当て ・人の一括の証明の出所 | なし | 同上 |
| 発行体の識別子の scheme | なし | 任意の拡張。他の authority の認可しだい |
| data の消去の仕組み | 条件つき（LUV-23） | 規約が削除を求める場合の別の設計の問い（P8-OBS-41）。A1R の前提にはしない。A1R は消去を後で足せない形にしない |

**結論: A1R の訂正 ・遡及の意味論は LUV-01〜LUV-24 に依存しない**（財務の欄の確認に依らない）。LUV-21 ・25 ・26（深さ ・master の過去日の
意味 ・事象の有無）は A1R の後の**実の identity の登録**に効き、LUV-23 は保存の設計に効くが、どちらも A1R の model の設計と合成 data での
検証を止めない。

---

## 12. 次の gate の推奨

```
P8-VR（本 gate）
  → P8-A1R: identity の訂正 ・遡及の解決 ・bootstrap の意味論（合成 data。実の登録なし）
  → Light の仕様 ／ pilot の完了: LUV-01〜27 を個人向けの文書か認可された実測で確かめる（規約 LUV-23 ・24 を含む）
  → A3: 最小集合（売上成長率 ・営業利益率）。確かめた欄だけを実データに写す
  → 最小の adapter: 前向きの取得 ・版を保つ ・規約の範囲の保存
  → 実データの検証
```

- Light の仕様の確認には、公式の host を許可した環境か、監督が確かめた Light の文書が要る（P8-OBS-35）。
- 規約（LUV-23 ・24）は raw snapshot と実の store の保持の前に確かめる（P8-OBS-32 ・36 ・41）。

---

## 13. 検証と凍結の確認

### 13.1 本 gate の変更

- `docs/databank/PHASE8_JQUANTS_VERIFICATION_REMEDIATION.md`【新規】（本書）
- `CHANGELOG.md`（v5.55）
- `tests/intelligence/phase8_runtime_registry.py`: `PHASE8_DOCS` に本書、P8-V の凍結の anchor `P8_V`
- `tests/intelligence/test_screener_intelligence_boundary.py`: 本書の登録と、runtime と先行の監査の文書（A2.5 ・P8-V）が `P8_V` と byte 一致する guard
- runtime ・config.yaml ・workflow ・Pages ・Phase 6 ／ 7 の test ・A1 ／ A2 の module ・A2.5 ／ P8-V の文書は無変更

### 13.2 実行した検証

監督指示 §11 の順:

| 対象 | 結果 |
|---|---|
| Phase 8 の境界 ／ 凍結の guard | 53 passed（52 ＋ P8-V の凍結の guard 1） |
| A2 | 120 passed |
| A1 | 101 passed |
| Phase 7 の凍結（全 suite） | 1002 passed |
| Phase 6 の凍結 | 552 passed |
| full pytest | 5223 passed ／ 2 skipped（基準 5222 ／ 2 ＋ 1） |

否定の証明（scratch の clone）: P8-V の記録を変える → 新しい guard が落ちる。本書を registry から外す → Phase 8 の BM と Phase 7 の
文書の guard が落ちる。

### 13.3 凍結

runtime は `4162e9c` ・`b686b00` ・`5713a56` ・`fc91ee1` と byte 一致。A2.5 の文書は `5713a56`、P8-V の文書は `fc91ee1` と byte 一致。Phase 6 ／ 7 は無変更。

---

## 14. 最終の判定

**P8_VR_REMEDIATION_COMPLETE / READY_FOR_P8_A1R**

A1R ・A3 ・adapter ・live ／ 認証つきの J-Quants ・実の identity の登録は行っていない。
