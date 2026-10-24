"""screener_intelligence — Phase 8 Screener Intelligence。

P8-A1 は Issuer ／ Security の identity の基盤だけ（`identity_model` ・`identity_store` ・`identity_resolver`）。
市場 ／ 財務の data ・screen ・基準 ・候補 ・順位 ・score ・Theme exposure ・J-Quants の接続 ・LLM は無い。

境界（`tests/intelligence/test_screener_intelligence_boundary.py`）:
- 許可 import: `core`（内容 id ・時刻）だけ。store だけが filesystem を使う（明示の data_root・追記専用）。
- 禁止: Phase 6 ／ Phase 7 ・P4 ・P5 ・legacy ・J-Quants の transport ・provider ・network ・時計 ・乱数 ・公開 ／ 通知 ／ 売買の経路。
  他の package は本 package を import しない。本 package は production runtime closure に含まれない。

契約: `docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md`。
"""
