# P4-2 Market Signal v0.1.0

- 対象: `src/intelligence/reports/market_signal.py`
- 状態: **凍結仕様**（監督者承認済み決定 D-1 / D-2 / D-3 / D-4 に基づく）
- 前提: P4-1 Morning Brief は CLOSED / FROZEN（実装 `56cf51a` / 実データ検証 run `34908731914` PASS）
- 関連: `docs/databank/PHASE4_ENTRY_CONTRACT.md` / `docs/rebuild/REBUILD_ROADMAP.md` P4-2

---

## 1. 役割

Market Signal は、**検証済みの `MorningBrief` の見通しを 5 段階の方向シグナルへ射影する決定論的な純関数**である。

| Market Signal である | Market Signal ではない |
|---|---|
| 既に検証済みの見通しのコンパクトな要約 | 第二の分析エンジン |
| session 単位の構造化フィールド | 予測エンジン |
| 方向の傾きの表現 | 投資推奨 / 売買シグナル |
| — | 確率予報 |

材料を数え直さない。閾値を持たない。方向も確度も作らない。`compass.outlook` が決定済みの
`direction` / `confidence` を写像するだけである。

roadmap の文言「強気〜弱気5段階」は **5 段階の方向スケール**の意図として解釈する。
投資スタンス語を導入する許可としては解釈しない（D-1）。

---

## 2. 承認済み 5 段階

| 安定 enum（`SignalLevel`） | 意味 |
|---|---|
| `UPWARD_LEAN` | 確認できた材料が上方向に揃っており、揃い方も十分 |
| `SLIGHT_UPWARD_LEAN` | 上方向だが、材料が少ない・反対材料がある・中核次元が欠ける |
| `NEUTRAL_RANGE` | 方向の材料が無く、主指標が横ばい（「動かない」という積極的な観測） |
| `SLIGHT_DOWNWARD_LEAN` | 下方向だが、材料が少ない・反対材料がある・中核次元が欠ける |
| `DOWNWARD_LEAN` | 確認できた材料が下方向に揃っており、揃い方も十分 |

`src.intelligence.core.types.Direction` は **再利用しない**（D-2）。用途（forecast）が異なり、
再利用すると 2 つの概念が癒着するため、Market Signal 専用の enum を持つ。

---

## 3. 顧客向け日本語ラベル

`SIGNAL_LEVEL_JA`（表示語彙。model は日本語を持たない）。

| `SignalLevel` | 日本語 |
|---|---|
| `UPWARD_LEAN` | 上昇寄り |
| `SLIGHT_UPWARD_LEAN` | やや上昇寄り |
| `NEUTRAL_RANGE` | 中立（レンジ） |
| `SLIGHT_DOWNWARD_LEAN` | やや下落寄り |
| `DOWNWARD_LEAN` | 下落寄り |

- `SignalLevel` の**全値**を明示的に持つ。対応表に無い値は fail closed。
- 順序値（+2 / +1 / 0 / −1 / −2）は**顧客へ出さない**。スコアに見えるため。
- 強気 / 弱気 / bullish / bearish は使わない（D-1）。

---

## 4. 方向・確度の写像

`LEVEL_BY_STATE`（承認済みの組み合わせだけを持つ）。

| `OutlookDirection` | `Confidence` | `SignalLevel` |
|---|---|---|
| `UPWARD_BIAS` | `HIGH` | `UPWARD_LEAN` |
| `UPWARD_BIAS` | `MEDIUM` | `UPWARD_LEAN` |
| `UPWARD_BIAS` | `LOW` | `SLIGHT_UPWARD_LEAN` |
| `DOWNWARD_BIAS` | `HIGH` | `DOWNWARD_LEAN` |
| `DOWNWARD_BIAS` | `MEDIUM` | `DOWNWARD_LEAN` |
| `DOWNWARD_BIAS` | `LOW` | `SLIGHT_DOWNWARD_LEAN` |
| `RANGE_BOUND` | `LOW` | `NEUTRAL_RANGE` |

`UNAVAILABLE_BY_DIRECTION`（**確度に依存しない**。D-3）。

| `OutlookDirection` | 結果 | 理由 |
|---|---|---|
| `MIXED` | `available=False` | `direction_mixed` |
| `UNCERTAIN` | `available=False` | `direction_uncertain` |

- `MIXED` / `UNCERTAIN` は **方向の状態だけで** unavailable になる。現行実装が
  たまたま `LOW` を出すという実装詳細に依存しない。将来 `MIXED + MEDIUM` や
  `UNCERTAIN + HIGH` が現れても、raise せず安全に unavailable を返す。
- `NEUTRAL_RANGE` へ写像される方向は **`RANGE_BOUND` だけ**。拮抗・不明を中立と表示しない。
- `RANGE_BOUND + HIGH` / `RANGE_BOUND + MEDIUM` は承認済み契約の外であり **fail closed**。
- 未知の `OutlookDirection` / 未知の `Confidence` も **fail closed**。

### 確度の扱い

`HIGH` と `MEDIUM` を同じ段階（±2）へ畳むのは、P4-2 が 5 段階に制約されているためである。
区別は失われない——`MarketSignal.confidence` が `HIGH / MEDIUM / LOW` を構造として保持する。
確度の生値は**顧客向け散文へ出さない**。

---

## 5. unavailable 方針

usable verdict の境界は P4-1 と同一（`USABLE_VERDICTS` = `VALID` / `VALID_WITH_WARNINGS`）。

| 状態 | 結果 | `unavailable_reason` |
|---|---|---|
| `VALID` / `VALID_WITH_WARNINGS` | 評価へ進む | — |
| `ABSTAINED` | `available=False` | `abstain_reason`（機械可読なら継承）／`draft_abstained` |
| `REJECTED` | `available=False` | `abstain_reason`（機械可読なら継承）／`draft_not_usable` |
| `tier3.available=False` | `available=False` | `tier3.unavailable_reason`（機械可読なら継承）／`tier3_unavailable` |
| `tier3.outlook is None` | `available=False` | `no_outlook` |
| `MIXED` | `available=False` | `direction_mixed` |
| `UNCERTAIN` | `available=False` | `direction_uncertain` |

- `unavailable_reason` は `[a-z0-9_]{1,64}` のみ。自由文・内部語彙は継承しない。
- **欠落次元・不確かな次元は、ここで再度減点しない。** Compass / MorningBrief が既に
  confidence と availability へ反映済みであり、二重計上になるため。
- 評価が不足する日を無理に方向づけしない。段階が無い日は段階を出さない。

---

## 6. 入力契約

```
build_market_signal(brief: MorningBrief) -> MarketSignal
```

**入力は `MorningBrief` のみ**（D-4）。

受け取らないもの: `CompassDraft` / `EvidencePackage` / raw claim / Market Bank 直接アクセス /
raw corpus / formal-review Decision / candidate recommendation / replay artifact / legacy report /
外部記事基盤 / Phase 5 出力 / 生成モデル。

これにより、**quality gate を通らない材料へ到達する経路が構造的に存在しない**。
Morning Brief が「出せない」と判断した日に、それを迂回して方向を出すことはできない。

副作用なし: 入出力・永続化・ネットワーク・環境変数読み取り・現在時刻・乱数を持たない。

---

## 7. 決定論と内容アドレス ID

同じ検証済み入力 → 同じ `MarketSignal`、同じ `signal_id`。

- 既存規約（`content_id` / `sort_keys=True` の正規化 JSON）を使う。第二のハッシュ機構は作らない。
- prefix: `signal_`

| 同一性に含める | 同一性から除く |
|---|---|
| `schema_version` | `signal_id` 自身 |
| `session_date` | 日本語ラベル |
| `reference_session` | 時刻 |
| `available` | path |
| `level` | hostname |
| `confidence` | PID |
| `horizon` | 乱数状態 |
| `brief_id` | |
| `unavailable_reason` | |

日本語ラベルを同一性から外すのは、表示語彙を変えても ID が動かないようにするためである。

---

## 8. provenance

- `brief_id` が**唯一の直接 provenance リンク**。
- `draft_id` / `package_id` は持たない。`brief_id` から `MorningBrief` に到達すれば辿れるため、
  二重保持は provenance の分岐点を増やす。
- `session_date` / `reference_session` は入力の値をそのまま運ぶ。
- 内部 ID を顧客向け散文へ出さない。

---

## 9. MorningBrief 境界

依存は **一方向**。

```
MorningBrief  →  MarketSignal
```

`MarketSignal → MorningBrief` は存在しない。

以下は **変更しない**（P4-1 凍結の維持）:

- `src/intelligence/reports/model.py`
- `src/intelligence/reports/morning_brief.py`
- `src/intelligence/reports/render_markdown.py`
- `src/intelligence/reports/pilot.py`

MorningBrief schema は **0.2.0 のまま**。`brief_id` の挙動も不変。
Market Signal は Morning Brief の**内側ではなく隣**に置く。

---

## 10. governance 境界

`docs/databank/PHASE4_ENTRY_CONTRACT.md` を継承する。

| 知識クラス | 権限 | Market Signal での扱い |
|---|---|---|
| Production Compass DNA | `AUTHORITATIVE_RULE` | 間接参照のみ（`outlook` が適用済みの結果を受け取る） |
| Formal Decision layer | `GOVERNANCE_RECORD` | 消費しない |
| APPROVED but NOT_PROMOTED | production rule ではない | 消費しない |
| REJECTED | 知識ではない | 消費しない |
| KEEP_REVIEWING | 知識ではない | 消費しない |

- import ゼロ: `decision` / `formal_review` / `review` / `shadow_review` / `corpus` /
  `corpus_research` / `replay` / `evaluation`
- Candidate アクセスなし。APPROVED パターンアクセスなし。
- promotion しない。DNA を変更しない。

legacy（`report` / `analysis` / `collectors`）・外部記事基盤・Phase 5
（`predictions` / `themes` / `thesis` / `screening` / `personalization`）・
生成モデル（`llm` / `anthropic` / `openai`）も import ゼロ。

---

## 11. Phase 5 境界

Market Signal は Phase 5 Prediction では**ない**。

| P4-2 が行う | Phase 5+ に残す |
|---|---|
| grounded な見通しを当日／翌東京セッション向けに 1 語へ要約 | forecast training |
| `direction` × `confidence` の決定論的写像 | prediction scoring |
| 材料不足時に段階を出さない | probability calibration |
| `horizon` をそのまま運ぶ | forward-return optimization |
| — | historical model fitting |
| — | target returns |
| — | prediction accuracy feedback loop |

判定基準: Market Signal は**過去に観測された材料の要約**であり、**将来の実績と突き合わせて
学習・採点される対象ではない**。突き合わせが始まった時点でそれは Phase 5 である。

---

## 12. 助言language 方針

段階は助言を含意しない。全ラベルが相場の**方向の傾き**のみを述べ、行動を述べない。

禁止: 売買語（買い / 売り）/ 推奨 / おすすめ / 目標株価 / ターゲット / 妙味 / 押し目 /
スタンス / 期待リターン / 確率 / 順序スコア（+2 …）/ 強気 / 弱気 / bullish / bearish。

Compass DNA 確信度ラダーの最上位「投資妙味」「押し目買いの好機」（＝明確な推奨）は**採用しない**。

投資推奨との境界: Market Signal は「すでに観測された材料が、次の東京セッションに向けて
どちら向きに傾いているか」の要約であり、**個別銘柄・売買・保有比率・時期に関する助言ではない**。

---

## 13. 表示は P4-3 へ繰り延べ

P4-2 は Market Signal を**描画しない**。

- 凍結済み Morning Brief Markdown を変更しない。
- バッジ / ヘッダを追加しない。
- P4-1C pilot を変更しない。`::P42_SIGNAL::` をまだ追加しない。
- HTML / CSS / PWA を作らない。

P4-2 が定義するのは **構造化された `MarketSignal`** と **`SIGNAL_LEVEL_JA` 対応表**のみ。
製品としての提示面・配信面は P4-3 が決定する。

---

## 14. データモデル

```python
MARKET_SIGNAL_SCHEMA_VERSION = "0.1.0"

class SignalLevel(str, Enum):
    UPWARD_LEAN / SLIGHT_UPWARD_LEAN / NEUTRAL_RANGE /
    SLIGHT_DOWNWARD_LEAN / DOWNWARD_LEAN

@dataclass(frozen=True, kw_only=True)
class MarketSignal:
    signal_id: str
    session_date: str
    reference_session: str
    available: bool
    level: Optional[SignalLevel] = None
    confidence: str = ""
    horizon: str = ""
    brief_id: str = ""
    unavailable_reason: str = ""
    schema_version: str = MARKET_SIGNAL_SCHEMA_VERSION
```

model に `label` フィールドは持たない（日本語は表示語彙）。`draft_id` / `package_id` も持たない。

---

## 15. fail closed

`UnmappedSignalState`（`KeyError`）。段階を作ることも、代替ラベルを当てることもしない。

fail closed になる構造状態:

- 未知の `OutlookDirection`
- 未知の `Confidence`
- `RANGE_BOUND + HIGH`
- `RANGE_BOUND + MEDIUM`
- `available=True` なのに `level` が無い
- `available=True` なのに `unavailable_reason` がある
- `available=False` なのに `level` がある
- `unavailable_reason` が機械可読でない
- `SignalLevel` に対応する日本語ラベルが無い

---

## 16. 公開 API

```python
build_market_signal(brief: MorningBrief) -> MarketSignal    # 主 API（純関数）

SignalLevel / MarketSignal / UnmappedSignalState
SIGNAL_LEVEL_JA / LEVEL_BY_STATE / UNAVAILABLE_BY_DIRECTION
signal_label(level) -> str
signal_payload(...) / canonical_signal(payload) / make_signal_id(payload)
R_DRAFT_NOT_USABLE / R_DRAFT_ABSTAINED / R_TIER3_UNAVAILABLE /
R_NO_OUTLOOK / R_DIRECTION_MIXED / R_DIRECTION_UNCERTAIN
MARKET_SIGNAL_SCHEMA_VERSION
```

内部ヘルパ（`_build` / `_safe_reason` / `_SAFE_REASON` / `_KNOWN_*`）は公開しない。
