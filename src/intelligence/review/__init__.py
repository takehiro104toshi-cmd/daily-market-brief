"""Human Review層（Phase 2-F）。

原則: THE DATA BANK MUST BE EXPLAINABLE, CORRECTABLE, AND REBUILDABLE。
- 全review対象は根拠（reason_codes / evidence_refs）付きで提示される
- 人間のdecisionはappend-onlyで永続され、algorithm判定より優先できる
- 履歴削除は構造的に不可能（statusの更新も新version追記）
"""
