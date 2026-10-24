"""P6-B7E — RecordedProvider の test fixture（合成データ。production の生成 journal ではない）。

記録済み応答は **生成入力の digest に束縛**する。digest は代表 world（`test_theme_llm_input_manifest._seed`）・
cutoff `2026-09-22`・prompt contract `theme_llm_prompt:0.1.0` から決定論的に決まる golden 値であり、
生成入力の bytes が 1 byte でも変われば replay は `RECORDED_INPUT_MISMATCH` で止まる。

応答は LLM の出力を模した合成 JSON であり、実 provider の応答ではない。
"""
from __future__ import annotations

import json

OUTPUT_SCHEMA = "theme_llm_generation_output:0.1.0"

#: EVIDENCE_EXTRACTION（Theme 2 つ ＋ evidence 4 件）の生成入力 digest
EVIDENCE_INPUT_DIGEST = "thllmgin_3aa7386d60ebd1a3e10ee296"
#: THEME_PROPOSAL（evidence 4 件 ＋ entity 3 件）の生成入力 digest
THEME_INPUT_DIGEST = "thllmgin_0c6238b7c557eaf4e3a25579"

EVIDENCE_RESPONSE = json.dumps({
    "output_schema_version": OUTPUT_SCHEMA, "outcome": "CANDIDATES",
    "candidates": [{"candidate_kind": "EVIDENCE", "evidence_handles": ["EV_003"],
                    "payload": {"target_handle": "TH_001", "proposed_role": "SUPPORTS", "component_handle": "CQ_001"},
                    "rationale": "recorded marker 7f3a: the headline reports rising power demand"}]},
    ensure_ascii=False)
THEME_ABSTENTION = json.dumps({"output_schema_version": OUTPUT_SCHEMA, "outcome": "ABSTAIN",
                               "abstention": {"reason": "INSUFFICIENT_EVIDENCE"}})

RECORDINGS = {EVIDENCE_INPUT_DIGEST: EVIDENCE_RESPONSE, THEME_INPUT_DIGEST: THEME_ABSTENTION}
