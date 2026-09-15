# P4-3a Morning Delivery v0.1.0

- 対象: `src/intelligence/reports/delivery.py`（packaging）/ `delivery_emit.py`（artifact 出力）
- 状態: **凍結仕様**（監督者承認済み決定 D-1〜D-5 に基づく）
- 前提: P4-1 Morning Brief と P4-2 Market Signal は CLOSED / FROZEN
- 関連: `docs/rebuild/MIGRATION_PLAN.md` Stage 4 / `docs/databank/PHASE4_ENTRY_CONTRACT.md` /
  `docs/databank/MARKET_SIGNAL_SPEC.md`

---

## 1. 役割

Morning Delivery は、**凍結済み Phase 4 成果物を 1 つの不変な配信物へ束ねるだけ**の層である。

| Morning Delivery である | Morning Delivery ではない |
|---|---|
| packaging 層 | renderer（本文を作り直さない） |
| 決定論的な純関数 ＋ 薄い artifact emitter | 分析器・予測器 |
| 並走出力（`output/v2/`）の生成 | Pages 導線の切替 |
| — | 通知経路への接続 |

新しい市場判断も、新しい文章も、新しいラベル語彙も作らない。

**P4-3a は P4-3 の全体ではない。** Pages routing と既存 notifier 接続は、後続の
**P4-3b bridge gate**（別途承認）に残す。

---

## 2. 入力

```python
build_morning_delivery(
    brief: MorningBrief,      # P4-1・凍結
    signal: MarketSignal,     # P4-2・凍結
    markdown: str,            # P4-1B renderer の戻り値（逐語）
) -> MorningDelivery
```

純関数。Compass も MorningBrief 合成も MarketSignal 写像も**再実行しない**。
呼び出し側が凍結済み成果物を渡す。

入出力・永続化・data root・時刻・乱数・環境変数・ネットワーク・生成モデルに触れない。
ファイルへ書くのは `delivery_emit.py` だけ。

---

## 3. モデル

```python
MORNING_DELIVERY_SCHEMA_VERSION = "0.1.0"

class DeliveryFormat(str, Enum):
    MARKDOWN = "MARKDOWN"
    JSON     = "JSON"

DELIVERY_FORMATS = (DeliveryFormat.MARKDOWN, DeliveryFormat.JSON)

@dataclass(frozen=True, kw_only=True)
class MorningDelivery:
    delivery_id: str
    session_date: str
    reference_session: str
    brief: MorningBrief        # 不変参照（分解しない）
    signal: MarketSignal       # 不変参照（分解しない）
    markdown: str              # 逐語
    markdown_sha256: str
    markdown_bytes: int
    formats: Tuple[DeliveryFormat, ...] = DELIVERY_FORMATS
    schema_version: str = MORNING_DELIVERY_SCHEMA_VERSION
```

HTML 値は持たない（将来値を先置きしない）。`formats` が承認済みの組と異なれば **fail closed**。

---

## 4. binding 規則

束ねる前に、凍結 2 成果物が同じ朝のものであることを確かめる。1 つでも食い違えば
`UnmappedDeliveryState` で**止める**（配信物を作らない）。

| 検査 | 内容 |
|---|---|
| `signal.brief_id == brief.brief_id` | provenance の一致 |
| `signal.session_date == brief.session_date` | 同じ朝 |
| `signal.reference_session == brief.reference_session` | 同じ前営業日 |

`__post_init__` でさらに `markdown_sha256` / `markdown_bytes` が本文と一致することを検証する。

---

## 5. Markdown バイト保存契約

**P4-3 は Markdown を書き換えない。**

```
delivery.markdown.encode("utf-8") == original_markdown.encode("utf-8")
```

- Market Signal の見出し・バッジを**前置しない**。
- footer を**付けない**。
- id を**足さない**。
- 空白・末尾改行を**変えない**。
- Market Signal は P4-3a では **JSON artifact にのみ**現れる。

`markdown_sha256` / `markdown_bytes` は UTF-8 の厳密なバイト列から計算する。

---

## 6. 公開 JSON 契約

**公開 JSON は配信契約であって監査 dump ではない。**
`MorningBrief.as_dict()` / `MarketSignal.as_dict()` を丸ごと出さない
（内部語彙が誤って配信 API になるのを防ぐため）。

### top-level key（`PUBLIC_KEYS`。この集合以外を出さない）

```json
{
  "schema_version": "0.1.0",
  "delivery_id": "delivery_…",
  "session_date": "2026-09-15",
  "reference_session": "2026-09-14",
  "brief_id": "brief_…",
  "signal_id": "signal_…",
  "markdown_sha256": "…",
  "markdown_bytes": 1234,
  "signal": { "available": true, "label": "やや上昇寄り", "unavailable_reason": "" }
}
```

### signal key（`PUBLIC_SIGNAL_KEYS`）

| available | label | unavailable_reason |
|---|---|---|
| `true` | P4-2 の承認済み日本語ラベル（`signal.label` をそのまま。写像を作り直さない） | `""` |
| `false` | `""`（**方向を作らない**） | `PUBLIC_UNAVAILABLE_REASONS` のいずれか |

公開してよい理由は固定語彙のみ：
`draft_not_usable` / `draft_abstained` / `tier3_unavailable` / `no_outlook` /
`direction_mixed` / `direction_uncertain`。
これ以外（内部自由文を含む）は **fail closed**。将来 UI が「本日は方向を出せません」を
出し分けるための安定状態語彙であり、内部理由をそのまま配信面へ流すものではない。

### 出さないもの

`draft_id` / `package_id` / `claim_id` / `fact_id` / `ctx_id` / `rule_ref` /
principle refs（`JP_*`）/ `UPWARD_BIAS` `DOWNWARD_BIAS` `RANGE_BOUND` `MIXED` `UNCERTAIN` /
`HIGH` `MEDIUM` `LOW` / `next_tokyo_session` / 生 dimension key / `SignalLevel` の生値 /
`BriefPoint.text` などの逐語・監査テキスト / formal-review 情報 / candidate id /
Decision record / raw article 本文 / filesystem path。

`FORBIDDEN_PUBLIC_SUBSTRINGS` を最終防壁として正規化後の文字列に対して走査し、
1 つでも混入していれば **fail closed**。

`delivery_public_json()` は `ensure_ascii=False` / `sort_keys=True` / `indent=2` ＋ 末尾改行の
**決定論的**な文字列を返す。これが artifact のバイト列そのものである。

---

## 7. artifact ファイル名

出力先は `output/v2/`（`MIGRATION_PLAN` Stage 4）。**承認済み 4 file 以外を書かない。**

```
output/v2/YYYY-MM-DD_morning_brief.md      … 凍結 Markdown の逐語バイト
output/v2/YYYY-MM-DD_morning_brief.json    … 顧客向け公開 JSON
output/v2/latest_morning_brief.md          … 同上（最新）
output/v2/latest_morning_brief.json        … 同上（最新）
```

legacy 成果物（`output/latest_market_brief.*` / `output/history/**`）には触れない。
Pages deployment route も変更しない。

---

## 8. 同一性

既存規約（`content_id` ＋ 正規化 JSON）を使う。第二のハッシュ機構は作らない。prefix は `delivery_`。

| 含める | 除く |
|---|---|
| `schema_version` | `delivery_id` 自身 |
| `session_date` | **Markdown 本文**（`markdown_sha256` が完全に決定するため） |
| `reference_session` | 日本語 signal ラベル |
| `brief_id` | 出力先 path |
| `signal_id` | ファイル名 |
| `markdown_sha256` | 時刻 |
| `markdown_bytes` | hostname / PID |
| `formats` | 乱数状態 |

保証：**同じ brief ＋ 同じ signal ＋ 同じ Markdown → 同じ `MorningDelivery` と同じ `delivery_id`。**

---

## 9. atomic write の意味論

- 各ファイルは、同一ディレクトリの temp file へ書いてから `os.replace` で差し替える。
  `os.replace` は同一ファイルシステム上で atomic であり、**個々のファイルは
  「古い正しい内容」か「新しい正しい内容」のいずれか**にしかならない。
- 書き込み失敗時は temp を削除する（`.part` の残骸を残さない）。
- **4 file 一括の原子性は保証しない。** POSIX のファイルシステム API が複数ファイルに
  またがるトランザクションを提供しないためである。これは仕様上の既知の境界であり、
  「4 file トランザクション」として扱ってはならない。
- 緩和策：置換を始める**前に全バイトを用意する**（`delivery_artifacts()`）。
  直列化段階で失敗した場合、1 file も差し替わらない。
- 置換の途中で失敗した場合は例外が伝播する。既に差し替えた file はそのまま残るが、
  壊れた内容にはならない。呼び出し側は失敗として扱うこと。

---

## 10. 冪等

同じ `MorningDelivery` を 2 回出せば、4 file とも同じバイト列になる。
時刻・乱数・host・出力先に依存する内容を持たない
（`generated_at` / `timestamp` / `hostname` / `pid` などのフィールドを持たない）。

---

## 11. 機密

顧客／公開 artifact は次を含まない：絶対パス / PDF ファイル名 / 資格情報 /
raw source doc / formal-review record / candidate id / Decision record / raw article 本文。

- **Markdown**: 既に P4-1 が凍結した顧客安全バイト列。
- **JSON**: §6 の明示的な公開射影のみ。

内容アドレス ID（`delivery_id` / `brief_id` / `signal_id`）は構造化メタデータとして許容する。
`draft_id` / `package_id` / claim・fact・context id は公開 artifact に出さない。

---

## 12. governance 隔離

Delivery が消費するのは **MorningBrief / MarketSignal / 凍結 Markdown のみ**。

直接アクセスしない：Market Bank / `CompassDraft` / `EvidencePackage` / Production DNA /
formal review / corpus / replay / Decision / candidate recommendation / article tank。

promotion しない。DNA を変更しない。

---

## 13. legacy / notifier 隔離（D-3: N-1 file handoff）

`src/intelligence/**` は次を **import しない**：
`notifiers` / `main` / `src.report` / `src.analysis` / `src.collectors` / `src.data` /
`src.date` / `scripts`（＝`test_import_boundary.py` の `LEGACY_FORBIDDEN_PREFIXES`）。

`LEGACY_FORBIDDEN_PREFIXES` は**緩和しない**。`test_import_boundary.py` に例外も作らない。

依存の向きは：

```
new intelligence → files          （これのみ）
new intelligence → legacy notifier code   （禁止）
```

P4-3a は artifact を出すだけである。後続の P4-3 bridge 作業で、外部／legacy 側の
consumer がその artifact を**読む**ことは別途認可され得る。P4-3a は通知もしない。

---

## 14. Phase 5 境界

Delivery は Phase 4 の出力を束ねて配るだけであり、次を導入しない：
prediction / theme engine / narrative engine / screening / watchlist / personalization。

import ゼロ：`predictions` / `themes` / `thesis` / `screening` / `personalization`。
生成モデル（`llm` / `anthropic` / `openai`）も使わない。

---

## 15. Phase 11 / 12 境界

| P4-3a で行う | 後続 Phase に残す |
|---|---|
| 決定論的 packaging | PWA 骨格（P11-1） |
| 構造化 JSON の生成 | service worker / manifest / offline cache（P11-1） |
| `output/v2/` への並走 artifact | Push 通知（P11-3） |
| — | 旧 HTML レポートからの導線移行（P11-2） |
| — | スケジューラ統合（P12-1） |
| — | hosting 自動化 / Cloudflare 変更 |

静的 HTML / Pages route 切替は **P4-3b bridge gate**（別途承認）。

---

## 16. P4-3b bridge（繰り延べ）

本仕様の範囲外。承認後に別途定義する：

- 静的 HTML の生成（HTML escaping / sanitization 契約を伴う）
- Pages 導線の切替（`MIGRATION_PLAN` Stage 4 の「**要承認**」）
- 既存 notifier 経路への接続（N-1 file handoff の consumer 側）
- real-data Actions pilot（`delivery_pilot.py`）

P4-3a はこれらを**一切実装していない**。
