"""narrative_intelligence — Phase 7 Narrative Intelligence（派生・非 authority・非永続）。

P7-A1 は意味論と純 model だけ（`synthesis_model`）。PIT の組み立て・engine・描画・永続化・LLM・provider・公開出力は無い。

境界（`tests/intelligence/test_narrative_intelligence_boundary.py`）:
- 許可 import: `core`（id・時刻の検査）だけ。Phase 6 の語彙は複製して持ち、一致は test で固定する。
- 禁止: Phase 6 の package・P4（compass / reports / facts / context / internals）・P5・legacy・predictions・provider・
  network・filesystem・時計・乱数・公開 / 通知 / 売買の経路。上流の package は本 package を import しない。
- 本 package は production runtime closure に含まれない。

契約: `docs/databank/PHASE7_NARRATIVE_SEMANTICS_MODEL_CONTRACT.md`（P7-A1）。
"""
