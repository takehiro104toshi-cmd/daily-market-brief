# CONFLICT_REVISION_POLICY — 矛盾・改定・撤回・重複の扱い（Phase 1-E）

## 1. CONFLICT（P1-A方針維持）

- CONTRADICTS Evidenceが存在しても**自動でFALSEと判定しない**。
  矛盾Evidenceは両方保持される（P1-A: 削除しない・REFUTED状態は作らない——監督者決定①）。
- QAでは `conflicting_evidence`（支持＋反証）/ `contradiction_only`（反証のみ）を
  明示し、policyの conflicting_status（既定LIMIT）で用途制限する。
- 決着（adjudication）は将来の上位層の責務。Trust Gateは状態の可視化と制限まで。

## 2. CORROBORATION（独立性の会計）

- 支持Evidenceの**独立系統数**を数える: 系統キー = duplicate_group（あれば）
  または source_id。
- 転載・同系統の複数支持（例: reuters本体＋Yahoo経由reuters）は1系統と数え、
  `syndicated_duplicate`＋`single_source_only` をWARN付与。
- 2系統以上の独立支持 → `corroborated_independent`（PASS情報として記録）。
- **semantic claim clusteringは未実装**（P1-E指示。同一claim IDへの明示リンクを
  synthetic fixtureで検証済み。意味的同一判定はPhase 2以降）。

## 3. REVISION（破壊的削除禁止）

- revision_of/supersedes関係（P1-D detect_revisionが決定論的に付与）を利用。
- 最新版が存在する旧文書 → `superseded` issue。
  - 現在値用途（DAILY_MARKET）→ LIMITED_USE
  - 歴史・文脈用途（GENERIC）→ ACCEPT_WITH_WARNINGS
- 旧統計値・訂正前記事はストアに残り続ける（歴史分析・監査の材料）。

## 4. RETRACTION（推測禁止）

- RETRACTEDは**明示的なevidenceがある場合のみ**:
  - Statement: P1-A VerificationState.RETRACTED（明示設定。導出で上書きされない）
  - SourceDocument: 呼び出し側が明示的に渡す retracted_ids 集合
- 内容の類似・削除検知等からの**推測でretracted扱いしない**。
- retracted → 現在分析用途はREJECT。レコード自体は監査・歴史用途のため保存継続
  （削除APIは存在しない）。

## 5. 依存関係への波及

矛盾・改定・撤回によるGate低下は、依存伝播規則（EVIDENCE_GATE_RULES §4）を通じて
Analysis/Forecastへ**警告として**伝わる。上流の変化で下流が黙って消えることはない。
