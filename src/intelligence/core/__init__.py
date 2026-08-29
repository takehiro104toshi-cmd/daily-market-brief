"""core — vNext共有のドメイン型と抽象契約。

- purpose: ドメイン横断で共有する最小の値型（types.py）と、
  ストレージ・時刻・LLMの抽象境界（contracts.py）を定義する。
- boundary: 標準ライブラリのみに依存する。I/O・ネットワーク・ベンダーSDK・
  Legacyコードへの依存は永続的に禁止。ここに「実装」は置かない。
- future responsibility: Phase 1でEvidenceRecordの正式スキーマ拡張、
  Phase 2でRepository実装（ファイルベース）が別パッケージとして提供される。
"""
