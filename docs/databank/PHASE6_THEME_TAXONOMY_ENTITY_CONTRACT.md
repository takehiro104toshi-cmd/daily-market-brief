# Phase 6 — Theme Taxonomy ＋ Entity Catalog Contract（P6-B4B）

状態: **P6_B4B_THEME_TAXONOMY_ENTITY_VALIDATED / READY_FOR_P6_B4C_DETERMINISTIC_DISCOVERY_CONTRACT**。
本書は B4B の runtime（`src/intelligence/theme_intelligence/knowledge_loader.py` / `taxonomy_model.py` / `taxonomy.py` /
`entity_model.py` / `entity_catalog.py`）と knowledge（`knowledge/theme_intelligence/`）の契約を凍結する。監督者決定
D-B4-1 / 2 / 3 / 9 / 10（B4B 指示 §0）を前提とし、B4A 監査（`PHASE6_THEME_TAXONOMY_ENTITY_DISCOVERY_AUDIT.md`）の
推奨を実装した。Foundation（`12847bf`）・B1（`e2d5168`）・B2（`ce2402a`）・B3（`4808f5e`）は無変更。

---

## 1. Knowledge authority class

Taxonomy と entity catalog は **VERSIONED KNOWLEDGE** である。Foundation authority（5 JSONL）・proposal authority
（B3 journal）・market evidence・Theme evidence・governance record のいずれでもない。

- YAML file は **公開済み不変 snapshot**。変更は次 version の別 file で行う（in-place 変更は digest 不一致で fail closed）。
- Foundation JSONL へ追記しない。data_root 配下に authority journal を作らない（B4B は `data_root` を知らない）。
- knowledge は Theme identity に関与しない: taxonomy slug は METADATA（identity 外）、entity id は typed_reference の
  **値**として Foundation に渡るが、catalog はその値を書き換えない（§8 / §12）。

## 2. Snapshot / version model

| envelope field | 内容 |
|---|---|
| `schema_version` | `theme_taxonomy:0.1.0` / `theme_entity_catalog:0.1.0`。完全一致以外は UNSUPPORTED_SCHEMA_VERSION |
| `taxonomy_version` / `catalog_version` | `MAJOR.MINOR.PATCH`（先頭 0 なし）。caller が `expected_version` で明示する |
| `published_at` | aware UTC（ISO 8601 offset 必須、または aware datetime）。naive / date / 数値は INVALID_DATETIME |
| `content_digest` | semantic content の sha256 hex（§13）。不一致は DIGEST_MISMATCH |
| `nodes` / `entities` | record 列 |

loader API（`taxonomy.py` / `entity_catalog.py`）:

```
load_taxonomy_version(path, *, expected_version, cutoff) -> TaxonomySnapshot
load_entity_catalog_version(path, *, expected_version, cutoff) -> EntityCatalogSnapshot
taxonomy_path(knowledge_root, version) / entity_catalog_path(knowledge_root, version)
compute_taxonomy_digest(path) / compute_entity_catalog_digest(path)      # authoring 補助（構造検証は全て行う）
```

gate の順序: envelope（unknown key / 型 / schema / version 形式 / published_at / digest 形式）→ `expected_version`
完全一致（VERSION_MISMATCH）→ `published_at ≤ cutoff`（FUTURE_VERSION。cutoff は aware 必須: INVALID_CUTOFF）→ record 構築
（構造検証）→ digest 再計算と照合（DIGEST_MISMATCH）。**「latest」loader・別 version への fallback・現在時刻は存在しない。**
file 名は `theme_taxonomy.<version>.yaml` / `entity_catalog.<version>.yaml` で、`knowledge_path` は directory を列挙しない。

## 3. Taxonomy model と DAG

`TaxonomyNode(slug, label, description, parent_slugs, aliases, since_version, deprecated_in_version, superseded_by,
provenance)`。`TaxonomySnapshot(schema_version, taxonomy_version, published_at, content_digest, nodes)`（nodes は slug 順）。

| 規則 | 失敗 code |
|---|---|
| slug は `^[a-z][a-z0-9_]{0,63}$`、snapshot 内で一意 | INVALID_SLUG / DUPLICATE_SLUG |
| 正規化 token（全 slug ＋ 全 alias）の所有は snapshot 全体で一意（deprecated node も含む） | ALIAS_COLLISION / ALIAS_DUPLICATE / ALIAS_EQUALS_SLUG |
| parent は実在、self parent 禁止、≤ 8 parents、cycle 禁止（DFS）、multi-parent 可 | MISSING_PARENT / SELF_PARENT / TOO_MANY_PARENTS / CYCLE |
| 非 deprecated node の parent は非 deprecated | DEPRECATED_PARENT |
| `since_version ≤ taxonomy_version`、`deprecated_in_version ≤ taxonomy_version`、`since ≤ deprecated` | FUTURE_NODE / FUTURE_DEPRECATION / INVALID_LIFECYCLE |
| `superseded_by` は deprecated node のみが持ち、対象は同 snapshot に実在し非 deprecated、self 不可 | SUPERSESSION_WITHOUT_DEPRECATION / INVALID_SUPERSESSION |
| RELATED edge・親の自動伝播・削除による rename は存在しない | UNKNOWN_FIELD（`related` 等） |

`ancestors_of(slug)` は明示的な derived helper（表示 / grouping 用）で、resolution / validation は呼ばない。
Taxonomy identity ≠ Theme identity。

## 4. Slug lifecycle

- slug は公開後不変。label / description / aliases は version 間で変更可。
- rename ＝ 新 slug（`since_version` ＝ 新 version）＋ 旧 node の `deprecated_in_version` ＋ `superseded_by`。旧 node は
  削除せず、旧 version の metadata 値を歴史的に解決できる（0.1.0 `supply_chain_theme` → 0.2.0 `supply_chain` が実例）。
- split: 旧 node の `superseded_by` に複数。merge: 複数 node が同一後継を指す。
- deprecated node の alias は新 node へ移す（所有一意性のため）。

## 5. Taxonomy normalization

`resolve_taxonomy_token(snapshot, token) -> TaxonomyResolution(status, token, normalized_token, slug, matched_by,
superseded_by, candidates, diagnostics)`。status: EXACT_SLUG / EXACT_ALIAS / DEPRECATED / AMBIGUOUS / UNKNOWN。

- 正規化規則（`normalize_token`、slug / alias / 入力に同一適用）: NFKC → 空白圧縮 → strip → casefold。
- 辞書引きの完全一致のみ。部分一致・接頭一致・fuzzy・embedding・n-gram はない（source token guard）。
- 親へ伝播しない。AMBIGUOUS は構築時検証により通常到達しない（防御的に保持）。空 token は UNKNOWN（EMPTY_TOKEN）。

## 6. Taxonomy PIT

- cutoff T に対し `published_at ≤ T` の snapshot だけが使える。未来 snapshot は FUTURE_VERSION。
- snapshot 内の有効性は version 単位（`since_version` / `deprecated_in_version`）。`in_force_slugs()` ＝ 非 deprecated。
- 「現在の taxonomy」は存在しない。version と cutoff は常に caller が渡す。

## 7. Foundation METADATA TAXONOMY との境界

`validate_theme_taxonomy_refs(snapshot, taxonomy_slugs) -> TaxonomyRefValidation(status VALID / INVALID, valid_slugs,
unknown_slugs, deprecated_slugs, duplicate_slugs, malformed_values, diagnostics)`。

- Foundation `ThemeMetadataRecord(field=TAXONOMY).value`（set 値 ＝ 複数 slug 正当）に置く slug 集合を pinned snapshot で
  検証する純 helper。slug は正確一致のみ（alias 不可）。deprecated は INVALID（`SUPERSEDED:old->new` を diagnostics に）。
- **ThemeMetadataRecord を書かない。Foundation を import しない（値は文字列で受ける）。** version pin は呼び出し側が
  metadata record の `provenance_ref`（`taxonomy:<version>`）に置く（B4A §3.2）。Foundation 無変更。

## 8. Entity identity

- `entity_id = "<kind>:<immutable-slug>"`。kind は Foundation `ThemeEntityKind` の値（`company` / `index` / `sector` /
  `industry` / `commodity` / `currency` / `country` / `central_bank` / `government`）、slug は taxonomy と同じ規則で
  **catalog 全体で kind を跨いで一意**（SLUG_COLLISION）。
- slug は公開後 rename しない。社名変更は `canonical_name`、ticker 変更は `identifiers` の履歴、法的同一性の変更は
  `valid_to` ＋ `superseded_by` ＋ 新 id（§12）。
- ticker は identifier であって identity ではない。
- `typed_reference` は identity core に入る（A2 §12）ため、entity id の不変性は Theme identity の前提条件である。

## 9. Entity types

`EntityType` は正確に 9 種: COMPANY / INDEX / SECTOR / INDUSTRY / COMMODITY / CURRENCY / COUNTRY / CENTRAL_BANK /
GOVERNMENT。`FOUNDATION_KIND_BY_ENTITY_TYPE` で `ThemeEntityKind` に単射で写像し（name 一致・値が id 接頭辞）、
`ThemeEntityKind.PERSON` / `TICKER` は意図的に写像しない。PERSON / TICKER / TECHNOLOGY / POLICY_PROGRAM / OTHER は語彙に
存在せず INVALID_VOCABULARY。Foundation 語彙の拡張は不要（BLOCKER なし）。

## 10. Aliases

| 種別 | 規則 |
|---|---|
| `aliases_safe` | 単独で解決可。正規化 token は **catalog 全体で一意**（SAFE_ALIAS_COLLISION）。他 entity の id と一致不可。他 entity の context alias を影にしない（CONTEXT_ALIAS_SHADOWED） |
| `aliases_context` ＋ `context_terms` | context alias は複数 entity で共有可。`context_terms`（非空）の正規化 token が、caller の `context`（surface 文字列の列）の正規化 token 集合と **交差**したときだけ解決。context なし → UNKNOWN（CONTEXT_REQUIRED）、一致なし → UNKNOWN（CONTEXT_NOT_MATCHED）、複数 entity 一致 → AMBIGUOUS（候補は id 順。先頭を選ばず、順位付けしない） |
| 同一 entity 内 | safe と context は 1 つの namespace（ALIAS_DUPLICATE）。context alias があれば context_terms 必須（CONTEXT_TERMS_REQUIRED）、逆も然り |

context alias は決して safe alias に昇格しない。NLP 推論・意味類似は行わない。

## 11. Identifiers

`EntityIdentifier(identifier_type, value, scheme, valid_from, valid_to)`。`IdentifierType` は現行 model が必要とする 4 種:
TICKER（scheme ＝ 取引所 / 市場 code 必須）、INSTRUMENT_ID（market catalog の instrument_id）、ISO_COUNTRY（`^[A-Z]{2}$`）、
ISO_CURRENCY（`^[A-Z]{3}$`）。ISIN / LEI / sector code は必要になった version で追加する（additive）。

- entity type ごとの許可（`IDENTIFIER_TYPES_BY_ENTITY_TYPE`）: COMPANY ＝ TICKER / INSTRUMENT_ID、INDEX / COMMODITY ＝
  INSTRUMENT_ID、COUNTRY ＝ ISO_COUNTRY、CURRENCY ＝ ISO_CURRENCY、SECTOR / INDUSTRY / CENTRAL_BANK / GOVERNMENT ＝ なし。
- 衝突: 同 `(type, scheme, value)` を別 entity が持つのは **TICKER に限り、有効期間が重ならない場合のみ**
  （`REUSABLE_IDENTIFIER_TYPES`。開始含む・終了含まない。片側無限は重なるとみなす）。それ以外は IDENTIFIER_COLLISION。
- 外部 registry は参照しない。network なし。

## 12. Lifecycle / corporate action semantics

| 事象 | 表現 | resolve の挙動 |
|---|---|---|
| rename | 同 entity_id、`canonical_name` 変更（旧名は alias に残せる） | 旧 version では旧名、新 version では新名 |
| ticker / identifier 変更 | 同 entity_id、identifier の `valid_from` / `valid_to` | — |
| merger | 旧 entity に `valid_to` ＋ `superseded_by`（後継は同 snapshot に実在。新 id） | `as_of ≥ valid_to` → SUPERSEDED（entity_id は旧 id のまま、`superseded_by` を併記）。`as_of < valid_to` → EXACT_* |
| split | 旧 entity 終了、`superseded_by` に複数の新 id | 同上（候補は複数） |
| catalog 上の retire | `retired_in_version` | INACTIVE（RETIRED_IN:<version>） |
| 期間外 | `valid_from` 前 / 後継なしの `valid_to` 後 | INACTIVE（VALID_FROM / VALID_TO 診断） |

`valid_from` / `valid_to` は世界時間（calendar date、開始含む・終了含まない、`valid_from < valid_to`）。`as_of` は date
または aware datetime（UTC 日付へ変換。naive は INVALID_AS_OF）。`as_of` なし ＝ 有効性判定なし。
**Theme subject の typed_reference は自動で書き換えない**（旧 id は旧 identity core のまま。NEW_ROOT / SUCCESSOR は人間）。

## 13. Content digest

- `content_digest = sha256(canonical_json(semantic_payload))`。canonical JSON は key sort・最小 separator・
  `ensure_ascii=False`。semantic payload ＝ envelope の schema_version / version / published_at（UTC ISO）＋ record の
  全 semantic field（record は id 順、集合値 field は正規化 key 順に sort）。
- `content_digest` 自身・file system path・YAML の comment / key 順 / 書式 / flow style は digest に入らない。
- golden: `theme_taxonomy.0.1.0` = `f33aa28c…9b79b60`、`0.2.0` = `75c0ae8c…627d757c`、`entity_catalog.0.1.0` =
  `6f2d43c9…81e73ba`、`0.2.0` = `63a23fca…327f863`（test に全桁を固定）。

## 14. YAML loading

YAML の解析は `knowledge_loader.read_yaml_document` だけが行う（strict SafeLoader）。fail closed:

FILE_MISSING / INVALID_ENCODING / INVALID_YAML / DUPLICATE_KEY / MULTIPLE_DOCUMENTS / NOT mapping（INVALID_TYPE）/
UNKNOWN_FIELD（top-level・node・entity・identifier・provenance）/ MISSING_FIELD / INVALID_TYPE（null を含む）/
UNSUPPORTED_SCHEMA_VERSION / INVALID_VERSION / VERSION_MISMATCH / INVALID_DIGEST / DIGEST_MISMATCH / FUTURE_VERSION /
INVALID_DATETIME / INVALID_DATE / INVALID_INTERVAL / graph・alias・identifier・lifecycle の各 code（§3 / §10 / §11 / §12）/
PROHIBITED_CONTENT（credential 付き URL・secret query・drive / UNC path）/ TEXT_TOO_LONG / NOT_NORMALIZED。
未知 field を黙って無視しない。model は検証済み plain 構造だけを受ける。

## 15. Confidentiality と MVP content

- knowledge に置いてよいのは抽象 slug・公開標準（ISO code・公開指数名）・検証専用の架空 record（`MVP_FIXTURE`）のみ。
  Compass 由来の原文 / named chain / 号 / 頁 / 日付参照 / CONFIRMED 表記、historical の信号語、顧客 watchlist 由来の
  企業集合、PERSON は含めない（guard test で config.yaml watchlist の名称 / ticker 不在、Compass token 不在を検査）。
- historical slug seed（D-B4-10）: `ai` / `semiconductors` / `data_center` / `power` / `energy` / `grid` / `nuclear` /
  `supply_chain_theme` の **slug 名のみ**を再利用（provenance origin `HISTORICAL_SLUG_SEED`）。説明文・alias は本 gate で
  新規に authoring した辞書的同義語で、信号語 list ではない。`supply_chain` は `SUPERVISOR_DECISION`。
- MVP entity: country JP / US、currency JPY / USD、central bank BOJ / Fed、government、index Nikkei 225 / TOPIX
  （market catalog の instrument_id と結線）、sector / industry の語彙例、commodity crude oil（`PUBLIC_STANDARD` /
  `SUPERVISOR_DECISION`）、および架空 company 3 件（`MVP_FIXTURE`、市場 code `XMVP`）。architecture 上は production
  content ではなく、B4C 以降で `retired_in_version` により retire できる。

## 16. Import boundary

- B4B module の import: stdlib、PyYAML（`knowledge_loader` のみ・関数内 import）、`..themes.model.ThemeEntityKind`
  （`entity_model` の完全写像のみ）、package 内 `.knowledge_loader` / `.taxonomy_model` / `.entity_model`。
- 禁止（test で固定）: proposal_store / proposal 各 module、Foundation store / operations / revision、compass / reports /
  predictions / calibration / legacy、network、LLM SDK、現在時刻、乱数、書き込み token、fuzzy / embedding token。
- Foundation / B1 / B2 / B3 は B4B module を import しない。`theme_intelligence` は production closure 外（既存 test）、
  Pages manifest は `knowledge` path 断片を公開 tree で禁止、workflow / scripts / config.yaml は `theme_intelligence` を
  参照しない。

## 17. Exclusions（B4B が実装しないもの）

Discovery、rule / signal file、proposal 生成、EvidenceCandidate bridge、ThemeCandidate assembly、LLM、graph、monitoring、
public 出力、data_root 書き込み、SQLite、network、config / workflow 変更、Foundation 書き込み、latest 解決。

## 18. Tests

`tests/intelligence/test_theme_taxonomy.py`（matrix 1〜24 ＋ 補助）、`test_theme_entity.py`（25〜50）、
`test_theme_taxonomy_entity_boundary.py`（55〜64）、`test_theme_intelligence_import_boundary.py`（additive 拡張:
module 列挙・stdlib / relative 許可・closure・IO token）。51〜54・65・66 は gate 報告で git / full suite により検証。

## 19. Versioning

- schema: `theme_taxonomy:0.1.0` / `theme_entity_catalog:0.1.0`。field 追加は schema minor bump ＋ loader の受理集合
  拡張（additive）。
- knowledge version: 公開ごとに bump。公開済み file は不変。version 履歴は Git と file 名で追跡する（file 内 history は
  持たない。必要になれば additive）。
- 正規化規則（`normalize_token`）の変更は taxonomy / catalog の新 version と同時に行い、`normalization_version` の
  導入を検討する（B4C の pin 設計と合わせる）。
