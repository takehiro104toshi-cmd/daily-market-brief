# THEME_TAXONOMY_SPEC — テーマ分類語彙仕様（Phase 2-E）

正本: `knowledge/enrichment/theme_taxonomy.yaml` v1.0.0。
loader: `src/intelligence/enrichment/taxonomy.py` / matcher: `theme_matcher.py`。

## 1. 既存catalogの監査と位置づけ

既存 `knowledge/theme_relations/themes.yaml` v1.1.0（ja label 30種・tank en_aliases・
theme_graph）を正本として監査した上で、enrichment用に**安定slug**・**階層**・
**マッチ規則**を付与した新taxonomyを作成（既存ファイルは無変更。`ja_label`で対応、
対応先が無い新設テーマは空欄で明示）。

## 2. 30テーマ

監督者指定17（ai / semiconductors / data_center / power / grid / nuclear / defense /
robotics / optical_communication / cpo / critical_minerals / shipbuilding / india /
space / autonomous_driving / finance / pharma）＋既存catalog由来
（gx / ev / battery / quantum / cybersecurity / rates_monetary / fx）＋
tankコーパス頻出領域（geopolitics / trade_policy / supply_chain_theme / crypto /
inflation / energy——themes.yaml unmapped_tank_slugsの主要部を吸収）。

## 3. 階層foundation（THEME HIERARCHY——本格GraphはPhase 6）

```
ai ─┬─ data_center ─── optical_communication ─── cpo
power ─┬─ grid
       └─ nuclear
```
＋各テーマにrelated（theme_graph.yamlの隣接関係を反映）。
**親テーマの自動伝播はしない**（data_centerタグはaiタグを含意しない——
伝播はPhase 6のTheme Graph設計で扱う。校正fixtureで固定した設計判断）。

## 4. マッチ規則（THEME MATCHING安全則）

- **strong_signals** … 1出現でタグ（テーマ固有性の高い語句のみ:
  "generative AI"・"data center"・"半導体"…）
- **weak_signals** … **単独では絶対にタグ付けしない**（"power"だけでPower確定禁止
  ——テスト固定）。同一テーマの相異なるsignal 2つ以上で成立
- **exclude_terms** … 共起で抑止（"nuclear weapons"→原子力(電力)を付けない・
  "trade war"→geopoliticsの比喩war除外）
- role: strong signalがheadlineにあれば`primary`、それ以外`secondary`
  （**primaryの強制はしない**——根拠所在の申告であり重要度判定ではない）
- multi-label許可（実corpus: 2テーマ107件・3テーマ18件・4テーマ4件）

## 5. tank slug対応（legacy比較専用）

`tank_slugs`フィールドで旧tank英語slug 28種→新slugを対応付け
（**LegacyAnnotation比較の参考統計専用。ground truthではなく自動昇格しない**）。

## 6. 変更管理

taxonomy変更は`version`を上げる。slugの意味変更禁止（変更は新slug）。
theme_rule_matcherの規則挙動変更はmatcher versionを上げ、再分類は追記
（旧version分類は残る）。
