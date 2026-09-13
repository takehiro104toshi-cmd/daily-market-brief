# EVENT_TYPE_TAXONOMY — イベント種別分類仕様（Phase 2-E）

正本: `knowledge/enrichment/event_types.yaml` v1.0.0。
matcher: `src/intelligence/enrichment/event_matcher.py`（RULE_BASED）。

## 1. 16種

EARNINGS / GUIDANCE / MA / CAPEX / PRODUCT / REGULATION / MONETARY_POLICY /
FISCAL_POLICY / MACRO_DATA / GEOPOLITICS / SUPPLY_CHAIN / PRICE_MOVE / IPO /
FINANCING / MANAGEMENT / OTHER。

- event type=「記事が報じる出来事の種類」の分類。**Factではない**
  （EARNINGSタグ≠「決算数値」のclaim）。市場影響・重要度の判定でもない。
- **OTHERの自動判定はしない**（規則で量産しない——USER/LLM由来のみ）。
  規則に合致しない記事は**未分類のまま**（正直なunclassified率として報告）。

## 2. 判定規則

- 高precisionフレーズ規則1ヒットで判定（フレーズ自体をイベント固有性の高いものに
  限定——"earnings"・"rate cut"・"agrees to buy"・"利上げ"・"新規上場"…）。
- exclude_terms: PRODUCTは"missile"/"rocket launch"共起で抑止（軍事launchと区別）・
  GEOPOLITICSは"trade war"等の比喩warを除外。
- multi-label許可（例: "Nvidia earnings beat as shares surge"→EARNINGS＋PRICE_MOVE）。
- **provenance区別**: headline規則=RULE_BASED / source提供カテゴリ=SOURCE_EXPLICIT /
  LLM判定=LLM（混同しない——classifier_nameで機械判別可能）。

## 3. 実測から校正した規則（fixture precision 1.000まで）

- "surges"等の裸の動詞は需要・輸入等にも係る→PRICE_MOVEは"shares surge"/"prices surge"
  等の主語付きフレーズに限定
- "new chip"は"new chip factory"（CAPEX）へ誤爆→PRODUCTから除去
- "cuts interest rates"系の言い回しをMONETARY_POLICYへ追加（ECB見出しの実測欠落）

## 4. TIME HORIZON（高確信規則のみ）

INTRADAY / DAYS / WEEKS / MONTHS / YEARS / UNKNOWN のうち、自動判定は
明示的時間表現のみ:
- YEARS … "by 2030"系・"next decade"・"long-term"・"中長期"等
- MONTHS … "next quarter"・"来期"・"今年度中"等
合致しなければ付けない（UNKNOWN扱い）。本格impact分析は後段フェーズ。
実corpus: YEARS 30件・MONTHS 4件（coverage 1.1%——高確信のみの正直な値）。

## 5. 変更管理

taxonomy/規則変更は`version`を上げる（分類のclassifier_version・
run manifestに記録——監査可能）。
