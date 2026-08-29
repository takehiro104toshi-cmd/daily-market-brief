# PROVENANCE_MODEL — 出所追跡モデル（schema 0.2.0）

Phase 1-A 成果物（2026-08-29）。

## 1. 原則: Evidence First

AIに投資判断をさせる前に、「どこから・いつ・何が事実で・何が分析で・何が予測か」を
追跡できることを証明する。全FACTは以下の連鎖で原文まで遡れる:

```
FactStatement --EvidenceLink(SUPPORTS)--> SourceDocument --raw_item_id--> RawItem --storage_ref--> 生バイト列
```

## 2. 3つの独立した軸（混同禁止）

| 軸 | 保持場所 | 意味 |
|---|---|---|
| **source_tier**（1/2/3） | SourceDocument（取得時スナップショット）・Sourceカタログ | 情報源の**格**（一次/高品質二次/一般）。真実性の確率ではない |
| **verification** | Statement＋invariantsによる導出 | その言明の**裏付け状態**（UNVERIFIED/VERIFIED/CONFLICTING/STALE/RETRACTED/UNSUPPORTED） |
| **confidence**（0-5） | ForecastMetadataのみ | **予測の確信度**（Compass DNA語彙ラダー。Phase 5でcalibration） |

Tier1文書由来でもリンクが無ければUNSUPPORTED、Tier3由来でも複数SUPPORTSで
VERIFIEDになり得る——テストで軸の独立性を検証済み。

## 3. 時刻モデル

| フィールド | 意味 | 所在 |
|---|---|---|
| event_time | 出来事の発生時刻 | Statement |
| as_of | 値が指す時点 | Observation |
| published_at | 情報源の公表時刻 | SourceDocument |
| retrieved_at | 本システムの取得時刻 | SourceDocument / RawItem |
| valid_from / valid_until | 記録の有効期間 | Statement / Observation |
| created_at / generated_at | 本システム内の生成時刻 | Statement / ForecastMetadata |

全datetimeは**timezone-aware必須**（naiveは構築時ValueError。JST固定禁止——
fixtureはJST/EST/UTC混在で検証）。シリアライズはUTC正規化ISO 8601。
日付検索（statements_on）は**UTC暦日**として契約に明記。

## 4. ID戦略（比較検討と決定）

| 候補 | 評価 |
|---|---|
| UUIDv7 | 時刻順・標準的。ただしPython 3.11 stdlibに生成器が無い（3.13+） |
| **ULID**（採用: 生成レコード） | 時刻順・26文字・stdlibのみで実装可（core/ids.py）。UUIDv7と実用同等 |
| **content-addressed**（採用: 取得物） | 同一内容→同一ID。再取得・重複配信が自然にdedupされる（tank資産の受け皿） |
| **slug**（採用: Source） | カタログ（knowledge/source_feeds.yaml）と人間可読性を優先 |

割り当て: `doc_`/`raw_`=content-addressed（sha256[:24]）、`fact_`/`ana_`/`fcst_`/`obs_`/
`link_`=ULID。prefixでドメインを識別。重複ID規約: 同一内容→冪等 / 異内容→エラー
（Evidenceは不変。変更はrevision_ofで新ID）。

## 5. 改定（Revision）と撤回

- SourceDocument.revision_of / Observation.revision_of で**過去値を消さずに**改定を積む。
  supersedes関係はrevision_ofから導出（`latest_revisions()`）。
- 情報源自身の撤回はVerificationState.RETRACTED（明示設定・導出しない）。
- 経済統計の速報→確報、記事訂正、決算修正がこの1つの機構で表現できる
  （fixture: CPI 4.1%→4.2%改定で検証）。

## 6. 矛盾（Conflict）

異なるsourceが矛盾した場合、**どちらも削除しない**。SUPPORTSとCONTRADICTSの
リンクを併置し、導出関数がCONFLICTINGを返す。解決（どちらを採るか）はPhase 2以降の
編集ポリシーの仕事であり、保存層は両論を保持する。

## 7. ANALYSISの生成トレース

AnalysisStatementは inputs（Evidence ID列）・rule_id（knowledge/のルール）・agent
（rule_engine/モデル名等の実行metadata文字列）・created_at を必須で持つ。
`trace_analysis()`により「米金利上昇(FACT) →[JP_US_001]→ グロース圧迫(ANALYSIS)
→ 半導体上値抑制(FORECAST)」の根までの遡行をテストで実証。
agentは**文字列metadata**であり、core domainはLLMベンダーSDKへ依存しない
（AST検査でvNext全域を機械検証）。
