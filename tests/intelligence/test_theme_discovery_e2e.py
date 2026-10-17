"""P6-B4D — discovery E2E / false-positive gate（§2 敵対 corpus、§3 golden 期待、§4 混同行列、§9 機構 firewall、§19 集計表）。

- 期待値は `discover()` の出力から snapshot したものではなく、B4C contract と公開 knowledge（taxonomy 0.2.0 /
  entity catalog 0.2.0 / discovery_rules 0.1.0）から独立に authoring した golden fixture である（§3 / §17）。
- runtime（rule / taxonomy / entity catalog / discovery module）は本 gate で一切変更しない。期待と実装が食い違った場合は
  期待を緩めず、blocker として報告する。
- 合成入力のみ。実在記事・保有銘柄一覧・受益連鎖・過去 rule 原文は含めない。store も Foundation も書かない。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Tuple

import pytest

from src.intelligence.core.types import SourceTier
from src.intelligence.databank.news_model import ClassificationProvenance, EntityKind, EntityReference
from src.intelligence.facts.model import FactStatus
from src.intelligence.theme_intelligence.discovery_adapter import adapt_inputs
from src.intelligence.theme_intelligence.discovery_model import DiscoveryInputRecord
from src.intelligence.theme_intelligence.proposal_model import (DecisionKind, DedupClass, ProposalDecision, ProposalType,
                                                                ThemeCandidateProposal)
from src.intelligence.themes.model import OTHER_CATEGORY
from src.intelligence.themes.resolver import ResolutionStatus
from tests.intelligence.test_theme_discovery import (CUTOFF, JP, RUN_AT, catalog, did, document, evaluation, fact, fid,  # noqa: F401
                                                     load_rules, news, nid, observation, of_type, oid, prov, rule, ruleset,
                                                     run, taxonomy, theme_rule)

UTC = timezone.utc
PUBLISHED_RULE_IDS = ("boj_context_evidence", "data_center_alias_evidence", "jp_data_center_power_demand_theme",
                      "jp_grid_power_demand_theme", "legacy_supply_chain_evidence", "nikkei_series_observation_evidence",
                      "policy_rate_fact_evidence")


# ---------------------------------------------------------------- tmp rule builders（公開 ruleset に無い trigger 面だけを補う）


def _mechanism(change: str = "INCREASE", statement: str = "electricity demand statistics rise relative to trend") -> dict:
    return {"drivers": [{"category": "DEMAND_SHIFT", "normalized_statement": "data center construction raises electricity demand"}],
            "channels": [{"category": "VOLUME_DEMAND", "normalized_statement": "higher electricity volume is demanded"}],
            "domains": [{"category": "REGION", "typed_reference": "${entity}"}],
            "consequences": [{"category": "MACRO_STATISTIC", "observable_target": "japan electricity demand statistics",
                              "expected_change": change, "normalized_statement": statement}]}


def theme_variant(rule_id: str, subject: str, predicate: dict, taxonomy_refs, **override) -> dict:
    data = theme_rule(rule_id, taxonomy_refs=list(taxonomy_refs), predicate=predicate,
                      subject_template={"normalized_subject": subject, "typed_reference": "${entity}"},
                      mechanism_template=_mechanism())
    data.update(override)
    return data


JP_PRESENT = {"kind": "ENTITY_PRESENT", "entity_id": "country:jp"}
OFFICIAL_RULE = rule("official_release_evidence", entity_refs=[], input_kinds=["SOURCE_DOCUMENT"],
                     predicate={"kind": "SOURCE_KIND", "source_kind": "OFFICIAL_RELEASE"})
FED_RULE = rule("fed_context_evidence", entity_refs=["central_bank:fed"],
                predicate={"kind": "ENTITY_PRESENT", "entity_id": "central_bank:fed"})
MOTORS_RULE = rule("example_motors_evidence", entity_refs=["company:example_motors"],
                   predicate={"kind": "ENTITY_PRESENT", "entity_id": "company:example_motors"})
SUCCESSOR_RULE = rule("example_successor_evidence", entity_refs=["company:example_energy_systems"],
                      predicate={"kind": "ENTITY_PRESENT", "entity_id": "company:example_energy_systems"})
POWER_RULE = rule("power_signal_evidence", entity_refs=[], taxonomy_refs=["power"],
                  predicate={"kind": "TAXONOMY_SIGNAL", "slug": "power"})
GRID_RULE = rule("grid_signal_evidence", entity_refs=[], taxonomy_refs=["grid"],
                 predicate={"kind": "TAXONOMY_SIGNAL", "slug": "grid"})
SUPPLY_RULE = rule("supply_chain_evidence", entity_refs=[], taxonomy_refs=["supply_chain"],
                   predicate={"kind": "TAXONOMY_SIGNAL", "slug": "supply_chain"})
FIREWALL_RULES = (
    theme_variant("theme_dc_only", "japan data center construction activity",
                  {"kind": "ALL", "children": [JP_PRESENT, {"kind": "TAXONOMY_SIGNAL", "slug": "data_center"}]}, ["data_center"]),
    theme_variant("theme_power_only", "japan electric power supply",
                  {"kind": "ALL", "children": [JP_PRESENT, {"kind": "TAXONOMY_SIGNAL", "slug": "power"}]}, ["power"]),
    theme_variant("theme_grid_only", "japan power transmission network",
                  {"kind": "ALL", "children": [JP_PRESENT, {"kind": "TAXONOMY_SIGNAL", "slug": "grid"}]}, ["grid"]))
CONFLICTING_RULES = (
    theme_variant("theme_demand_up", "japan electricity demand outlook",
                  {"kind": "ALL", "children": [JP_PRESENT, {"kind": "TAXONOMY_SIGNAL", "slug": "data_center"}]}, ["data_center"]),
    theme_variant("theme_demand_down", "japan electricity demand outlook",
                  {"kind": "ALL", "children": [JP_PRESENT, {"kind": "TAXONOMY_SIGNAL", "slug": "data_center"}]}, ["data_center"],
                  mechanism_template=_mechanism("DECREASE", "electricity demand statistics fall relative to trend")))
TAXONOMY_TOKEN_RULE = theme_variant("theme_two_signals", "japan electricity demand from data center construction", JP_PRESENT,
                                    ["data_center", "power"],
                                    aggregate_predicates=[{"kind": "MIN_DISTINCT", "dimension": "TAXONOMY_TOKEN", "min_count": 2}])


# ---------------------------------------------------------------- golden case model（§3）


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    inputs: Tuple[object, ...]
    truth_evidence: bool
    truth_theme: bool
    rules: Tuple[dict, ...] = ()
    record_ids: Tuple[str, ...] = ()
    normalized: Tuple[Tuple[str, str, str, str], ...] = ()
    excluded: Tuple[Tuple[str, str], ...] = ()
    rule_hits: Tuple[Tuple[str, str], ...] = ()
    evidence_ids: Tuple[str, ...] = ()
    theme_evidence: Tuple[Tuple[str, ...], ...] = ()
    origin_groups: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    report_diagnostics: Tuple[str, ...] = ()
    record_diagnostics: Tuple[str, ...] = ()
    forbidden_diagnostics: Tuple[str, ...] = ()
    fail_closed: bool = False
    note: str = ""

    @property
    def expected_evidence(self) -> bool:
        return bool(self.evidence_ids)

    @property
    def expected_theme(self) -> bool:
        return bool(self.theme_evidence)


def ent(input_id: str, entity_id: str, level: str) -> tuple:
    return (input_id, "ENTITY", entity_id, level)


def tax(input_id: str, slug: str, level: str = "L2") -> tuple:
    return (input_id, "TAXONOMY", slug, level)


def jp_both(input_id: str) -> tuple:
    """構造化 ref（L1）と本文 alias（L2）の両方で country:jp が立つ入力の正規化形。"""
    return (ent(input_id, "country:jp", "L1"), ent(input_id, "country:jp", "L2"))


def arts(*tags: str) -> tuple:
    return tuple(sorted((f"article:art_{t}", (nid(t),)) for t in tags))


# ---------------------------------------------------------------- §2 敵対 corpus（すべて合成。generic 語のみ）

N1 = news("1", "Data centre construction lifts electric power demand")
N2 = news("2", "Datacenter operators sign electric power contracts")
G1 = news("1", "Data centre and 送電網 build-out lifts electric power demand")
G2 = news("2", "Datacenter and power grid expansion raises 電力 demand")
L1_ONLY = news("1", "Japan data centre build-out lifts electric power demand", refs=())
L2_ONLY = news("2", "Japan datacenter operators buy electric power", refs=())

CORPUS: Tuple[Case, ...] = (
    # ---- TP control（§2 正例）
    Case("tp_structured_entity_l1", "TP_CONTROL", (observation("o"),), True, False,
         record_ids=(oid("o"),), normalized=(ent(oid("o"), "index:nikkei225", "L1"),),
         rule_hits=(("nikkei_series_observation_evidence", oid("o")),), evidence_ids=(oid("o"),),
         origin_groups=(("series:src_m/nikkei225_close", (oid("o"),)),),
         note="Observation の entity_id と series が L1 で一致する正例"),
    Case("tp_fact_type_l1", "TP_CONTROL", (fact("f"),), True, False,
         record_ids=(fid("f"),), normalized=(ent(fid("f"), "central_bank:boj", "L1"),),
         rule_hits=(("policy_rate_fact_evidence", fid("f")),), evidence_ids=(fid("f"),),
         origin_groups=((f"derived:{fid('f')}", (fid("f"),)),),
         note="Fact の宣言された fact_type が L1 の正例（lineage 不明のため DERIVED origin）"),
    Case("tp_source_kind_l1", "TP_CONTROL", (document("r1", "Quarterly results release", tier=SourceTier.TIER1),), True, False,
         rules=(OFFICIAL_RULE,), record_ids=(did("r1"),),
         rule_hits=(("official_release_evidence", did("r1")),), evidence_ids=(did("r1"),),
         origin_groups=(("release:src1/hash_r1", (did("r1"),)),),
         note="TIER1 文書の OFFICIAL_RELEASE source kind が L1 の正例"),
    Case("tp_evidence_trigger_valid", "TP_CONTROL", (news("b1", "Bank of Japan keeps policy steady", refs=()),), True, False,
         record_ids=(nid("b1"),), normalized=(ent(nid("b1"), "central_bank:boj", "L2"),),
         rule_hits=(("boj_context_evidence", nid("b1")),), evidence_ids=(nid("b1"),), origin_groups=arts("b1"),
         note="safe alias（longest-alias-wins で 'japan' ではなく 'bank of japan'）による EVIDENCE 正例"),
    Case("tp_theme_trigger_valid", "TP_CONTROL", (N1, N2), True, True,
         record_ids=(nid("1"), nid("2")),
         normalized=(ent(nid("1"), "country:jp", "L1"), tax(nid("1"), "data_center"), tax(nid("1"), "power"),
                     ent(nid("2"), "country:jp", "L1"), tax(nid("2"), "data_center"), tax(nid("2"), "power")),
         rule_hits=(("data_center_alias_evidence", nid("1")), ("data_center_alias_evidence", nid("2")),
                    ("jp_data_center_power_demand_theme", nid("1")), ("jp_data_center_power_demand_theme", nid("2"))),
         evidence_ids=(nid("1"), nid("2")), theme_evidence=((nid("1"), nid("2")),), origin_groups=arts("1", "2"),
         report_diagnostics=("EVIDENCE_REFS:2;ORIGIN_KEYS:2;NOT_AN_INDEPENDENCE_CLAIM",),
         note="L1 entity ＋ 2 taxonomy signal ＋ MIN_DISTINCT 充足の THEME 正例"),
    Case("tp_same_rule_multi_evidence", "TP_CONTROL",
         (news("c1", "Datacenter capacity additions announced", refs=()), news("c2", "Datacenter cooling upgrades planned", refs=()),
          news("c3", "Datacenter lease terms extended", refs=())), True, False,
         record_ids=(nid("c1"), nid("c2"), nid("c3")),
         normalized=(tax(nid("c1"), "data_center"), tax(nid("c2"), "data_center"), tax(nid("c3"), "data_center")),
         rule_hits=(("data_center_alias_evidence", nid("c1")), ("data_center_alias_evidence", nid("c2")),
                    ("data_center_alias_evidence", nid("c3"))),
         evidence_ids=(nid("c1"), nid("c2"), nid("c3")), origin_groups=arts("c1", "c2", "c3"),
         note="同一 rule から複数 evidence。件数は score にならない"),
    Case("tp_cross_rule_convergence", "TP_CONTROL", (G1, G2), True, True,
         record_ids=(nid("1"), nid("2")),
         normalized=(ent(nid("1"), "country:jp", "L1"), tax(nid("1"), "data_center"), tax(nid("1"), "grid"), tax(nid("1"), "power"),
                     ent(nid("2"), "country:jp", "L1"), tax(nid("2"), "data_center"), tax(nid("2"), "grid"), tax(nid("2"), "power")),
         rule_hits=(("data_center_alias_evidence", nid("1")), ("data_center_alias_evidence", nid("2")),
                    ("jp_data_center_power_demand_theme", nid("1")), ("jp_data_center_power_demand_theme", nid("2")),
                    ("jp_grid_power_demand_theme", nid("1")), ("jp_grid_power_demand_theme", nid("2"))),
         evidence_ids=(nid("1"), nid("2")), theme_evidence=((nid("1"), nid("2")),), origin_groups=arts("1", "2"),
         note="異なる trigger の 2 rule が同じ意味・同じ evidence 集合に収束（1 proposal）"),
    Case("tp_context_alias_with_context", "TP_CONTROL", (news("f1", "Fed holds rates after the fomc meeting", refs=()),), True, False,
         rules=(FED_RULE,), record_ids=(nid("f1"),), normalized=(ent(nid("f1"), "central_bank:fed", "L2"),),
         rule_hits=(("fed_context_evidence", nid("f1")),), evidence_ids=(nid("f1"),), origin_groups=arts("f1"),
         note="context alias は context term が同じ限定面にあるときだけ解決する"),

    # ---- L2 攻撃（§5）
    Case("tn_alias_inside_unrelated_word", "L2_ATTACK", (news("t1", "Turbojet engine orders rise", refs=()),), False, False,
         record_ids=(nid("t1"),), origin_groups=arts("t1"),
         note="'boj' は 'turbojet' の部分文字列だが境界一致しないため hit しない"),
    Case("tn_alias_only_in_url_and_author", "L2_ATTACK",
         (news("u1", "Quiet headline", refs=(), author="Bank of Japan", url="https://example.invalid/data-centre"),), False, False,
         record_ids=(nid("u1"),), origin_groups=arts("u1"),
         note="URL / author / body locator は限定 text 面ではない"),
    Case("tn_context_alias_missing_context", "L2_ATTACK", (news("f2", "Fed up with long delays", refs=()),), False, False,
         rules=(FED_RULE,), record_ids=(nid("f2"),), origin_groups=arts("f2"),
         note="context term が無い context alias は解決しない"),
    Case("tn_context_alias_wrong_context", "L2_ATTACK", (news("f3", "Fed up after the opec meeting", refs=()),), False, False,
         rules=(FED_RULE,), record_ids=(nid("f3"),), origin_groups=arts("f3"),
         note="別 entity の context term では解決しない"),
    Case("fn_l2_only_theme_language", "L2_ATTACK", (L1_ONLY, L2_ONLY), True, True,
         record_ids=(nid("1"), nid("2")),
         normalized=(ent(nid("1"), "country:jp", "L2"), tax(nid("1"), "data_center"), tax(nid("1"), "power"),
                     ent(nid("2"), "country:jp", "L2"), tax(nid("2"), "data_center"), tax(nid("2"), "power")),
         rule_hits=(("data_center_alias_evidence", nid("1")), ("data_center_alias_evidence", nid("2")),
                    ("jp_data_center_power_demand_theme", nid("1")), ("jp_data_center_power_demand_theme", nid("2"))),
         evidence_ids=(nid("1"), nid("2")), origin_groups=arts("1", "2"),
         report_diagnostics=("THEME_CANDIDATE_REQUIRES_L1_HIT",), fail_closed=True,
         note="L2 だけの theme 的文面は意図的に fail closed（FN と数える）"),
    Case("tn_causal_prose_without_l1", "L2_ATTACK",
         (news("c1", "Construction activity raises electricity demand across the country", refs=()),
          news("c2", "New facilities lift electricity consumption nationwide", refs=())), False, False,
         record_ids=(nid("c1"), nid("c2")), origin_groups=arts("c1", "c2"),
         note="因果的な散文だけでは L1 も L2 も立たない"),

    # ---- entity lifecycle / 曖昧性（§7）
    Case("tn_ambiguous_entity", "ENTITY_LIFECYCLE", (news("a1", "Example plant makes motors and battery cells", refs=()),), False, False,
         rules=(MOTORS_RULE,), record_ids=(nid("a1"),), origin_groups=arts("a1"),
         record_diagnostics=("AMBIGUOUS_ENTITY:example:company:example_battery,company:example_motors",),
         note="複数 context owner が残れば勝者を選ばない"),
    Case("tn_unknown_entity", "ENTITY_LIFECYCLE",
         (news("k1", "Quantum widgets shipped", refs=(EntityReference(kind=EntityKind.COMPANY, value="unknown_co",
                                                                     provenance=ClassificationProvenance.SOURCE_EXPLICIT),
                                                     EntityReference(kind=EntityKind.TICKER, value="ZZZZ",
                                                                     provenance=ClassificationProvenance.SOURCE_EXPLICIT))),),
         False, False, record_ids=(nid("k1"),), origin_groups=arts("k1"),
         record_diagnostics=("UNKNOWN_STRUCTURED_REF:company:unknown_co", "UNKNOWN_IDENTIFIER:TICKER:zzzz"),
         note="未知 entity は推測しない"),
    Case("tn_inactive_entity", "ENTITY_LIFECYCLE",
         (news("i1", "Example Energy Systems expands", refs=(), published=datetime(2026, 6, 1, tzinfo=UTC)),), False, False,
         rules=(SUCCESSOR_RULE,), record_ids=(nid("i1"),), normalized=(tax(nid("i1"), "energy"),), origin_groups=arts("i1"),
         record_diagnostics=("INACTIVE_ENTITY:company:example_energy_systems",),
         note="valid_from 前の entity は trigger しない"),
    Case("tn_superseded_entity", "ENTITY_LIFECYCLE", (news("s1", "Example Battery output climbs", refs=()),), False, False,
         rules=(SUCCESSOR_RULE,), record_ids=(nid("s1"),), origin_groups=arts("s1"),
         record_diagnostics=("SUPERSEDED_ENTITY:company:example_battery->company:example_energy_systems",),
         note="後継 entity への暗黙の付け替えをしない"),

    # ---- taxonomy 階層（§6）
    Case("tn_child_where_parent_rule", "TAXONOMY_HIERARCHY", (news("g1", "送電網 upgrades in Japan", refs=()),), False, False,
         rules=(POWER_RULE,), record_ids=(nid("g1"),),
         normalized=(ent(nid("g1"), "country:jp", "L2"), tax(nid("g1"), "grid")), origin_groups=arts("g1"),
         note="子 slug（grid）は親 rule（power）を満たさない"),
    Case("tn_parent_where_child_rule", "TAXONOMY_HIERARCHY", (news("g2", "Electric power investment rises", refs=()),), False, False,
         rules=(GRID_RULE,), record_ids=(nid("g2"),), normalized=(tax(nid("g2"), "power"),), origin_groups=arts("g2"),
         note="親 slug（power）は子 rule（grid）を満たさない"),
    Case("tn_deprecated_taxonomy_token", "TAXONOMY_HIERARCHY", (news("d1", "supply_chain_theme review published", refs=()),), False, False,
         rules=(SUPPLY_RULE,), record_ids=(nid("d1"),), origin_groups=arts("d1"),
         record_diagnostics=("DEPRECATED_TAXONOMY_TOKEN:supply_chain_theme",),
         note="deprecated slug は後継 slug へ暗黙に解決されない"),
    Case("tp_successor_taxonomy_slug", "TAXONOMY_HIERARCHY", (news("d2", "supply chain resilience review", refs=()),), True, False,
         rules=(SUPPLY_RULE,), record_ids=(nid("d2"),), normalized=(tax(nid("d2"), "supply_chain"),),
         rule_hits=(("supply_chain_evidence", nid("d2")),), evidence_ids=(nid("d2"),), origin_groups=arts("d2"),
         note="後継 slug 自体は正しく trigger する（前ケースの対照）"),

    # ---- negative predicate（§10）
    Case("tn_negative_predicate_collision", "NEGATIVE_PREDICATE",
         (news("n1", "Nuclear power backs data centre demand in Japan"),
          news("n2", "Nuclear power and datacenter electric power demand in Japan")), True, False,
         record_ids=(nid("n1"), nid("n2")),
         normalized=jp_both(nid("n1")) + (tax(nid("n1"), "data_center"), tax(nid("n1"), "nuclear"))
                    + jp_both(nid("n2")) + (tax(nid("n2"), "data_center"), tax(nid("n2"), "nuclear"), tax(nid("n2"), "power")),
         rule_hits=(("data_center_alias_evidence", nid("n1")), ("data_center_alias_evidence", nid("n2"))),
         evidence_ids=(nid("n1"), nid("n2")), origin_groups=arts("n1", "n2"),
         report_diagnostics=(f"EXCLUDED_BY_NEGATIVE_PREDICATE:{nid('n1')}", f"EXCLUDED_BY_NEGATIVE_PREDICATE:{nid('n2')}"),
         note="negative 一致は部分点なしで入力ごと除外する"),
    Case("tn_positive_and_negative_mixed", "NEGATIVE_PREDICATE",
         (news("p1", "Data centre demand lifts electric power use in Japan"),
          news("p2", "Nuclear power and data centre plans in Japan")), True, False,
         record_ids=(nid("p1"), nid("p2")),
         normalized=jp_both(nid("p1")) + (tax(nid("p1"), "data_center"), tax(nid("p1"), "power"))
                    + jp_both(nid("p2")) + (tax(nid("p2"), "data_center"), tax(nid("p2"), "nuclear")),
         rule_hits=(("data_center_alias_evidence", nid("p1")), ("data_center_alias_evidence", nid("p2")),
                    ("jp_data_center_power_demand_theme", nid("p1"))),
         evidence_ids=(nid("p1"), nid("p2")), origin_groups=arts("p1", "p2"),
         report_diagnostics=(f"EXCLUDED_BY_NEGATIVE_PREDICATE:{nid('p2')}", "MIN_DISTINCT_NOT_MET:INPUT_ID:1<2"),
         note="除外された入力は MIN_DISTINCT を満たす数にも入らない"),

    # ---- source origin（§8）
    Case("tp_same_article_two_wrappers", "SOURCE_ORIGIN",
         (news("w1", "Datacenter capacity report", refs=()), document("w1", "Datacenter capacity report")), True, False,
         record_ids=(did("w1"), nid("w1")),
         normalized=(tax(did("w1"), "data_center"), tax(nid("w1"), "data_center")),
         rule_hits=(("data_center_alias_evidence", did("w1")), ("data_center_alias_evidence", nid("w1"))),
         evidence_ids=(did("w1"), nid("w1")), origin_groups=(("article:art_w1", (did("w1"), nid("w1"))),),
         note="同一記事の 2 表現は 2 evidence 候補・1 origin"),
    Case("tp_same_article_fact_news_document", "SOURCE_ORIGIN",
         (news("x1", "Bank of Japan policy note", refs=()), document("x1", "Bank of Japan policy note"),
          fact("x1", refs=(("document", did("x1")),))), True, False,
         record_ids=(did("x1"), fid("x1"), nid("x1")),
         normalized=(ent(did("x1"), "central_bank:boj", "L2"), ent(fid("x1"), "central_bank:boj", "L1"),
                     ent(nid("x1"), "central_bank:boj", "L2")),
         rule_hits=(("boj_context_evidence", did("x1")), ("boj_context_evidence", nid("x1")),
                    ("policy_rate_fact_evidence", fid("x1"))),
         evidence_ids=(did("x1"), fid("x1"), nid("x1")),
         origin_groups=(("article:art_x1", (did("x1"), fid("x1"), nid("x1"))),),
         note="Fact は lineage が一意なら上流 origin を継ぐ（独立 source 数は増えない）"),
    Case("tp_single_origin_theme_is_not_independence", "SOURCE_ORIGIN",
         (news("y1", "Data centre demand lifts electric power in Japan"),
          document("y1", "Data centre demand lifts electric power in Japan")), True, True,
         record_ids=(did("y1"), nid("y1")),
         normalized=(ent(did("y1"), "country:jp", "L2"), tax(did("y1"), "data_center"), tax(did("y1"), "power"))
                    + jp_both(nid("y1")) + (tax(nid("y1"), "data_center"), tax(nid("y1"), "power")),
         rule_hits=(("data_center_alias_evidence", did("y1")), ("data_center_alias_evidence", nid("y1")),
                    ("jp_data_center_power_demand_theme", did("y1")), ("jp_data_center_power_demand_theme", nid("y1"))),
         evidence_ids=(did("y1"), nid("y1")), theme_evidence=((did("y1"), nid("y1")),),
         origin_groups=(("article:art_y1", (did("y1"), nid("y1"))),),
         report_diagnostics=("EVIDENCE_REFS:2;ORIGIN_KEYS:1;NOT_AN_INDEPENDENCE_CLAIM",),
         note="MIN_DISTINCT は INPUT_ID 次元のため契約上は成立する。origin が 1 である事実を診断に明示する"),
    Case("tn_repeated_identical_input", "SOURCE_ORIGIN",
         (news("r1", "Data centre demand lifts electric power in Japan"),
          news("r1", "Data centre demand lifts electric power in Japan")), True, False,
         record_ids=(nid("r1"),),
         normalized=jp_both(nid("r1")) + (tax(nid("r1"), "data_center"), tax(nid("r1"), "power")),
         rule_hits=(("data_center_alias_evidence", nid("r1")), ("jp_data_center_power_demand_theme", nid("r1"))),
         evidence_ids=(nid("r1"),), origin_groups=arts("r1"),
         report_diagnostics=(f"DUPLICATE_INPUT_ID:{nid('r1')}", "MIN_DISTINCT_NOT_MET:INPUT_ID:1<2"),
         note="同一入力の反復は distinct 数を水増ししない"),

    # ---- PIT / 使用不可入力（§15）
    Case("tn_future_input", "PIT_INPUT", (news("z1", "Bank of Japan statement", refs=(), published=CUTOFF + timedelta(microseconds=1)),),
         False, False, excluded=((nid("z1"), "AFTER_CUTOFF"),),
         note="cutoff より後に公開された入力は正規化されない"),
    Case("tn_unusable_fact", "PIT_INPUT", (fact("q1", status=FactStatus.LIMITED_USE),), False, False,
         excluded=((fid("q1"), "FACT_NOT_USABLE:limited_use"),),
         note="USABLE 以外の Fact は入力にならない"),

    # ---- 機構 firewall（§9）
    Case("tn_mechanism_requires_same_input", "MECHANISM_FIREWALL",
         (news("m1", "Data centre construction accelerates in Japan"), news("m2", "Electric power tariffs rise in Japan")), True, False,
         record_ids=(nid("m1"), nid("m2")),
         normalized=jp_both(nid("m1")) + (tax(nid("m1"), "data_center"),) + jp_both(nid("m2")) + (tax(nid("m2"), "power"),),
         rule_hits=(("data_center_alias_evidence", nid("m1")),), evidence_ids=(nid("m1"),), origin_groups=arts("m1", "m2"),
         note="別入力に分かれた signal は 1 rule の predicate を満たさない"),
    Case("fw_partial_rules_do_not_combine", "MECHANISM_FIREWALL",
         (news("f1", "Data centre construction in Japan"), news("f2", "Electric power supply in Japan"),
          news("f3", "送電網 upgrades in Japan")), False, True,
         rules=FIREWALL_RULES, record_ids=(nid("f1"), nid("f2"), nid("f3")),
         normalized=jp_both(nid("f1")) + (tax(nid("f1"), "data_center"),) + jp_both(nid("f2")) + (tax(nid("f2"), "power"),)
                    + jp_both(nid("f3")) + (tax(nid("f3"), "grid"),),
         rule_hits=(("theme_dc_only", nid("f1")), ("theme_grid_only", nid("f3")), ("theme_power_only", nid("f2"))),
         theme_evidence=tuple(sorted(((nid("f1"),), (nid("f2"),), (nid("f3"),)))), origin_groups=arts("f1", "f2", "f3"),
         note="部分的な根拠を持つ 3 rule は合成されず、それぞれの機構のまま残る"),
    Case("fw_conflicting_rules_do_not_arbitrate", "MECHANISM_FIREWALL",
         (news("k1", "Data centre plans in Japan"), news("k2", "Datacenter permits in Japan")), False, True,
         rules=CONFLICTING_RULES, record_ids=(nid("k1"), nid("k2")),
         normalized=jp_both(nid("k1")) + (tax(nid("k1"), "data_center"),) + jp_both(nid("k2")) + (tax(nid("k2"), "data_center"),),
         rule_hits=(("theme_demand_down", nid("k1")), ("theme_demand_down", nid("k2")),
                    ("theme_demand_up", nid("k1")), ("theme_demand_up", nid("k2"))),
         theme_evidence=((nid("k1"), nid("k2")), (nid("k1"), nid("k2"))), origin_groups=arts("k1", "k2"),
         note="矛盾する帰結は勝者を選ばず 2 候補として残り、identity core 一致の dedup review が付く"),

    # ---- MIN_DISTINCT（§11）
    Case("tn_min_distinct_not_met", "MIN_DISTINCT", (news("mn", "Data centre demand lifts electric power in Japan"),), True, False,
         record_ids=(nid("mn"),), normalized=jp_both(nid("mn")) + (tax(nid("mn"), "data_center"), tax(nid("mn"), "power")),
         rule_hits=(("data_center_alias_evidence", nid("mn")), ("jp_data_center_power_demand_theme", nid("mn"))),
         evidence_ids=(nid("mn"),), origin_groups=arts("mn"),
         report_diagnostics=("MIN_DISTINCT_NOT_MET:INPUT_ID:1<2",),
         note="INPUT_ID 1 件では THEME にならない"),
    Case("tp_min_distinct_taxonomy_token", "MIN_DISTINCT",
         (news("t1", "Data centre and electric power plans in Japan"),), False, True,
         rules=(TAXONOMY_TOKEN_RULE,), record_ids=(nid("t1"),),
         normalized=jp_both(nid("t1")) + (tax(nid("t1"), "data_center"), tax(nid("t1"), "power")),
         rule_hits=(("theme_two_signals", nid("t1")),), theme_evidence=((nid("t1"),),), origin_groups=arts("t1"),
         note="TAXONOMY_TOKEN 次元の MIN_DISTINCT は 1 入力内の 2 slug で満たされる"),
)

GROUPS = ("TP_CONTROL", "L2_ATTACK", "ENTITY_LIFECYCLE", "TAXONOMY_HIERARCHY", "NEGATIVE_PREDICATE", "SOURCE_ORIGIN",
          "PIT_INPUT", "MECHANISM_FIREWALL", "MIN_DISTINCT")


# ---------------------------------------------------------------- 実行 / 照合


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory, taxonomy, catalog, ruleset):
    root = tmp_path_factory.mktemp("b4d_rulesets")
    out = {}
    for case in CORPUS:
        rules = load_rules(root / case.case_id, list(case.rules), taxonomy, catalog) if case.rules else ruleset
        result = run(case.inputs, taxonomy, catalog, rules)
        adapted = adapt_inputs(list(case.inputs), taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
        out[case.case_id] = (case, result, adapted)
    return out


def _normalized(records) -> tuple:
    out = []
    for record in records:
        out.extend((record.input_id, "ENTITY", h.entity_id, h.level.value) for h in record.entity_hits)
        out.extend((record.input_id, "TAXONOMY", h.slug, h.level.value) for h in record.taxonomy_hits)
    return tuple(sorted(out))


def _diagnostic_pool(result) -> set:
    report = result.run_report
    return set(report.diagnostics) | {d for e in report.rule_evaluations for d in e.diagnostics}


def check_case(case: Case, result, adapted) -> None:
    where = case.case_id
    assert tuple(r.input_id for r in adapted.records) == case.record_ids, where
    assert _normalized(adapted.records) == tuple(sorted(case.normalized)), where
    assert tuple((e.input_id, e.reason) for e in adapted.excluded) == case.excluded, where
    assert tuple(sorted((h.rule_id, h.input_id) for h in result.run_report.rule_hits)) == tuple(sorted(case.rule_hits)), where
    evidence = of_type(result, ProposalType.EVIDENCE_CANDIDATE)
    assert tuple(sorted(p.ref_id for p in evidence)) == case.evidence_ids and len(evidence) == len(case.evidence_ids), where
    themes = of_type(result, ProposalType.THEME_CANDIDATE)
    emitted_refs = tuple(sorted(tuple(sorted(a.ref_id for a in t.evidence_refs)) for t in themes))
    assert emitted_refs == tuple(sorted(case.theme_evidence)), where
    assert result.run_report.origin_groups == case.origin_groups, where
    assert result.run_report.normalized_input_count == len(case.record_ids), where
    pool = _diagnostic_pool(result)
    for token in case.report_diagnostics:
        assert any(token in d for d in pool), (where, token)
    for token in case.forbidden_diagnostics:
        assert not any(token in d for d in pool), (where, token)
    record_pool = {d for r in adapted.records for d in r.diagnostics}
    for token in case.record_diagnostics:
        assert any(token in d for d in record_pool), (where, token)


@pytest.mark.parametrize("case_id", [c.case_id for c in CORPUS])
def test_01_golden_case_matches_authored_expectation(outcomes, case_id) -> None:
    check_case(*outcomes[case_id])


def test_02_corpus_is_well_formed_and_covers_every_group() -> None:
    assert len(CORPUS) == 35 and len({c.case_id for c in CORPUS}) == 35
    assert {c.group for c in CORPUS} == set(GROUPS)
    assert sum(1 for c in CORPUS if c.fail_closed) == 1
    assert all(c.note for c in CORPUS)


# ---------------------------------------------------------------- §4 混同行列


def classify(truth: bool, emitted: bool) -> str:
    return {(True, True): "TP", (False, False): "TN", (False, True): "FP", (True, False): "FN"}[(truth, emitted)]


def confusion(cases=CORPUS) -> dict:
    out = {}
    for case in cases:
        out[case.case_id] = {"evidence": classify(case.truth_evidence, case.expected_evidence),
                             "theme": classify(case.truth_theme, case.expected_theme)}
    return out


def totals(dimension: str, group: str = "") -> dict:
    counts = {"TP": 0, "TN": 0, "FP": 0, "FN": 0}
    table = confusion()
    for case in CORPUS:
        if group and case.group != group:
            continue
        counts[table[case.case_id][dimension]] += 1
    return counts


def test_03_theme_false_positives_are_zero(outcomes) -> None:
    """PASS 条件: ThemeCandidate の FP = 0（§4）。実測 emission と突き合わせる。"""
    false_positives = []
    for case_id, (case, result, _adapted) in outcomes.items():
        emitted = bool(of_type(result, ProposalType.THEME_CANDIDATE))
        assert emitted == case.expected_theme, case_id
        if not case.truth_theme and emitted:
            false_positives.append(case_id)
    assert false_positives == [] and totals("theme")["FP"] == 0


def test_04_evidence_false_positives_are_zero(outcomes) -> None:
    false_positives = []
    for case_id, (case, result, _adapted) in outcomes.items():
        emitted = bool(of_type(result, ProposalType.EVIDENCE_CANDIDATE))
        assert emitted == case.expected_evidence, case_id
        if not case.truth_evidence and emitted:
            false_positives.append(case_id)
    assert false_positives == [] and totals("evidence")["FP"] == 0


def test_05_confusion_totals_match_authored_counts() -> None:
    assert totals("evidence") == {"TP": 18, "TN": 17, "FP": 0, "FN": 0}
    assert totals("theme") == {"TP": 6, "TN": 28, "FP": 0, "FN": 1}


@pytest.mark.parametrize("group,evidence,theme", [
    ("TP_CONTROL", {"TP": 8, "TN": 0, "FP": 0, "FN": 0}, {"TP": 2, "TN": 6, "FP": 0, "FN": 0}),
    ("L2_ATTACK", {"TP": 1, "TN": 5, "FP": 0, "FN": 0}, {"TP": 0, "TN": 5, "FP": 0, "FN": 1}),
    ("ENTITY_LIFECYCLE", {"TP": 0, "TN": 4, "FP": 0, "FN": 0}, {"TP": 0, "TN": 4, "FP": 0, "FN": 0}),
    ("TAXONOMY_HIERARCHY", {"TP": 1, "TN": 3, "FP": 0, "FN": 0}, {"TP": 0, "TN": 4, "FP": 0, "FN": 0}),
    ("NEGATIVE_PREDICATE", {"TP": 2, "TN": 0, "FP": 0, "FN": 0}, {"TP": 0, "TN": 2, "FP": 0, "FN": 0}),
    ("SOURCE_ORIGIN", {"TP": 4, "TN": 0, "FP": 0, "FN": 0}, {"TP": 1, "TN": 3, "FP": 0, "FN": 0}),
    ("PIT_INPUT", {"TP": 0, "TN": 2, "FP": 0, "FN": 0}, {"TP": 0, "TN": 2, "FP": 0, "FN": 0}),
    ("MECHANISM_FIREWALL", {"TP": 1, "TN": 2, "FP": 0, "FN": 0}, {"TP": 2, "TN": 1, "FP": 0, "FN": 0}),
    ("MIN_DISTINCT", {"TP": 1, "TN": 1, "FP": 0, "FN": 0}, {"TP": 1, "TN": 1, "FP": 0, "FN": 0})])
def test_06_group_breakdown_matches_authored_counts(group, evidence, theme) -> None:
    assert totals("evidence", group) == evidence and totals("theme", group) == theme


def test_07_only_intentional_fail_closed_theme_false_negatives(outcomes) -> None:
    table = confusion()
    negatives = [c for c in CORPUS if table[c.case_id]["theme"] == "FN"]
    assert [c.case_id for c in negatives] == ["fn_l2_only_theme_language"]
    for case in negatives:
        assert case.fail_closed and case.report_diagnostics
        _case, result, _adapted = outcomes[case.case_id]
        assert any(token in d for token in case.report_diagnostics for d in _diagnostic_pool(result))


# ---------------------------------------------------------------- §9 機構 firewall / §18 FC-1 / §20 主張の不在


def test_08_no_cross_rule_mechanism_assembly_in_the_corpus(outcomes) -> None:
    for case_id, (_case, result, _adapted) in outcomes.items():
        for theme in of_type(result, ProposalType.THEME_CANDIDATE):
            statements = {c.normalized_statement for c in theme.mechanism.drivers + theme.mechanism.channels + theme.mechanism.domains}
            assert len(theme.mechanism.drivers) == len(theme.mechanism.channels) == len(theme.mechanism.domains) == 1, case_id
            assert len(theme.mechanism.consequences) == 1 and len(statements) <= 3, case_id
    _case, firewall, _adapted = outcomes["fw_partial_rules_do_not_combine"]
    themes = of_type(firewall, ProposalType.THEME_CANDIDATE)
    assert len(themes) == 3 and all(len(t.evidence_refs) == 1 for t in themes)
    assert {t.subject.normalized_subject for t in themes} == {"japan data center construction activity", "japan electric power supply",
                                                              "japan power transmission network"}
    assert len({t.proposal_id for t in themes}) == 3 and firewall.run_report.dedup_review_ids == ()


def test_09_conflicting_rules_produce_two_candidates_and_a_human_review(outcomes) -> None:
    _case, result, _adapted = outcomes["fw_conflicting_rules_do_not_arbitrate"]
    themes = of_type(result, ProposalType.THEME_CANDIDATE)
    assert len(themes) == 2 and len({t.proposal_id for t in themes}) == 2
    assert {t.mechanism.consequences[0].expected_change.value for t in themes} == {"INCREASE", "DECREASE"}
    assert len({t.identity_core_fingerprint for t in themes}) == 1 and len({t.semantic_fingerprint for t in themes}) == 2
    reviews = of_type(result, ProposalType.DEDUP_REVIEW)
    assert len(reviews) == 2 and all(r.dedup_class is DedupClass.EXACT_IDENTITY_CORE_MATCH for r in reviews)
    assert {r.subject_proposal_id for r in reviews} == {t.proposal_id for t in themes}


def test_10_fc1_no_theme_candidate_needs_the_foundation_other_category(outcomes) -> None:
    usage = {"driver": 0, "channel": 0, "domain": 0, "consequence": 0}
    themes = 0
    for _case_id, (_case, result, _adapted) in outcomes.items():
        for theme in of_type(result, ProposalType.THEME_CANDIDATE):
            themes += 1
            mechanism = theme.mechanism
            for name, items in (("driver", mechanism.drivers), ("channel", mechanism.channels), ("domain", mechanism.domains),
                                ("consequence", mechanism.consequences)):
                usage[name] += sum(1 for item in items if item.category == OTHER_CATEGORY)
    assert themes == 9 and usage == {"driver": 0, "channel": 0, "domain": 0, "consequence": 0}


def test_11_no_scores_ranking_or_independence_claims_anywhere_in_the_corpus(outcomes) -> None:
    for case_id, (_case, result, _adapted) in outcomes.items():
        plain = json.dumps(result.run_report.to_plain()).lower()
        for token in ("score", "rank", "confidence", "qualif", "stance", "weight", "independent_source", "source_diversity",
                      "buy", "sell") + CONFIDENTIAL_TOKENS:
            assert token not in plain, (case_id, token)
        for proposal in result.proposals:
            assert not any(hasattr(proposal, attribute) for attribute in ("score", "rank", "confidence", "qualification",
                                                                          "root_id", "theme_root_id"))
        assert all(p.proposal_type in (ProposalType.EVIDENCE_CANDIDATE, ProposalType.THEME_CANDIDATE, ProposalType.DEDUP_REVIEW)
                   for p in result.proposals), case_id


def test_12_published_ruleset_surface_is_unchanged(ruleset) -> None:
    assert tuple(sorted(r.rule_id for r in ruleset.rules)) == PUBLISHED_RULE_IDS
    assert (ruleset.ruleset_version, ruleset.taxonomy_version, ruleset.catalog_version) == ("0.1.0", "0.2.0", "0.2.0")
    assert [r.rule_id for r in ruleset.rules if r.status.value == "DEPRECATED"] == ["legacy_supply_chain_evidence"]


# ---------------------------------------------------------------- §12 収束 / §13 decision 履歴 / §14 dedup


def _decision(proposal_id: str, kind: DecisionKind, *, at=RUN_AT + timedelta(hours=1)) -> ProposalDecision:
    return ProposalDecision.build(proposal_id=proposal_id, decision=kind, actor_ref="reviewer:r9", reason="reviewed", recorded_at=at)


def test_13_same_semantics_and_evidence_converge_while_a_different_evidence_set_diverges(tmp_path, taxonomy, catalog, ruleset) -> None:
    converged = run((G1, G2), taxonomy, catalog, ruleset)
    theme = of_type(converged, ProposalType.THEME_CANDIDATE)[0]
    dc, grid = evaluation(converged, "jp_data_center_power_demand_theme"), evaluation(converged, "jp_grid_power_demand_theme")
    assert dc.emitted_proposal_ids == grid.emitted_proposal_ids == (theme.proposal_id,)
    assert dc.converged_proposal_ids == grid.converged_proposal_ids == (theme.proposal_id,)
    assert converged.run_report.proposal_ids.count(theme.proposal_id) == 1
    other = run((N1, news("3", "Datacenter power tariffs in Japan")), taxonomy, catalog, ruleset)
    diverged = of_type(other, ProposalType.THEME_CANDIDATE)[0]
    assert diverged.proposal_id != theme.proposal_id and diverged.semantic_fingerprint == theme.semantic_fingerprint
    left = load_rules(tmp_path / "left", [theme_rule("rule_left")], taxonomy, catalog)
    right = load_rules(tmp_path / "right", [theme_rule("rule_right", rule_version="4.1.2")], taxonomy, catalog)
    a = of_type(run((N1, N2), taxonomy, catalog, left), ProposalType.THEME_CANDIDATE)[0]
    b = of_type(run((N1, N2), taxonomy, catalog, right), ProposalType.THEME_CANDIDATE)[0]
    assert a.proposal_id == b.proposal_id and a.identity_payload() == b.identity_payload()
    assert (a.provenance.proposer_ref, a.provenance.rule_version) != (b.provenance.proposer_ref, b.provenance.rule_version)
    assert "rule_left" not in json.dumps(a.identity_payload()) and "provenance" not in a.identity_payload()


@pytest.mark.parametrize("kind,token", [(None, "OPEN"), (DecisionKind.DEFER, "OPEN_DEFERRED"), (DecisionKind.ACCEPT, "ACCEPTED"),
                                        (DecisionKind.REJECT, "REJECTED")])
def test_14_every_decision_state_suppresses_regeneration_and_stays_visible(taxonomy, catalog, ruleset, kind, token) -> None:
    inputs = (N1, N2, observation("o"), fact("f"))
    first = run(inputs, taxonomy, catalog, ruleset)
    decisions = tuple(_decision(p.proposal_id, kind) for p in first.proposals) if kind else ()
    second = run(inputs, taxonomy, catalog, ruleset, existing_proposals=first.proposals, existing_decisions=decisions,
                 run_created_at=RUN_AT + timedelta(days=1))
    assert second.proposals == () and set(second.run_report.suppressed_existing_ids) == {p.proposal_id for p in first.proposals}
    assert all(f"EXISTING_{token}_PROPOSAL:{p.proposal_id}" in second.run_report.diagnostics for p in first.proposals)
    assert tuple(sorted(second.run_report.diagnostics)) == second.run_report.diagnostics


def test_15_rejected_history_is_visible_and_never_mutated(taxonomy, catalog, ruleset) -> None:
    first = run((N1, N2), taxonomy, catalog, ruleset)
    theme = of_type(first, ProposalType.THEME_CANDIDATE)[0]
    decisions = (_decision(theme.proposal_id, DecisionKind.REJECT),)
    second = run((N1, N2), taxonomy, catalog, ruleset, existing_proposals=first.proposals, existing_decisions=decisions,
                 run_created_at=RUN_AT + timedelta(days=1))
    assert f"EXISTING_REJECTED_PROPOSAL:{theme.proposal_id}" in second.run_report.diagnostics
    assert second.proposals == () and not any(isinstance(p, ProposalDecision) for p in second.proposals)
    assert tuple(d.decision for d in decisions) == (DecisionKind.REJECT,)


class _Derived:
    def __init__(self, semantic: str, core: str) -> None:
        self.semantic_fingerprint = semantic
        self.identity_core_fingerprint = core


FIXTURE_ROOT_ID = "theme_" + "0" * 26
FIXTURE_OBSERVATION_ID = "thobs_" + "0" * 24


class _Observation:
    def __init__(self, observation_id: str) -> None:
        self.observation_id = observation_id


class _Resolution:
    """read-only の ThemeResolution 相当（B3 dedup が読む面だけを持つ duck type。Foundation store は読まない）。"""

    status = ResolutionStatus.RESOLVED

    def __init__(self, root_id: str, semantic: str, core: str) -> None:
        self.root_id = root_id
        self.derived = _Derived(semantic, core)
        self.observation = _Observation(FIXTURE_OBSERVATION_ID)


@pytest.mark.parametrize("mode,dedup_class", [("semantic", DedupClass.EXACT_SEMANTIC_MATCH),
                                              ("identity_core", DedupClass.EXACT_IDENTITY_CORE_MATCH), ("none", None)])
def test_16_dedup_against_an_existing_theme_resolution(taxonomy, catalog, ruleset, mode, dedup_class) -> None:
    base = of_type(run((N1, N2), taxonomy, catalog, ruleset), ProposalType.THEME_CANDIDATE)[0]
    semantic = base.semantic_fingerprint if mode == "semantic" else "thsem_" + "0" * 24
    core = base.identity_core_fingerprint if mode in ("semantic", "identity_core") else "thcore_" + "0" * 24
    result = run((N1, N2), taxonomy, catalog, ruleset, theme_resolutions=(_Resolution(FIXTURE_ROOT_ID, semantic, core),))
    reviews = of_type(result, ProposalType.DEDUP_REVIEW)
    if dedup_class is None:
        assert reviews == [] and result.run_report.dedup_review_ids == ()
    else:
        assert [r.dedup_class for r in reviews] == [dedup_class]
        assert [c.ref_id for c in reviews[0].counterparts] == [FIXTURE_ROOT_ID]
        assert reviews[0].subject_proposal_id == base.proposal_id


def test_17_not_duplicate_decision_stops_re_review(taxonomy, catalog, ruleset) -> None:
    first = run((N1, N2), taxonomy, catalog, ruleset)
    second_inputs = (news("3", "Data centre power tariffs in Japan"), news("4", "Datacenter electric power contracts in Japan"))
    second = run(second_inputs, taxonomy, catalog, ruleset, existing_proposals=first.proposals)
    review = of_type(second, ProposalType.DEDUP_REVIEW)[0]
    assert review.dedup_class is DedupClass.EXACT_SEMANTIC_MATCH
    third = run(second_inputs, taxonomy, catalog, ruleset, existing_proposals=tuple(first.proposals) + tuple(second.proposals),
                existing_decisions=(_decision(review.proposal_id, DecisionKind.NOT_DUPLICATE),),
                run_created_at=RUN_AT + timedelta(days=2))
    assert of_type(third, ProposalType.DEDUP_REVIEW) == [] and third.run_report.dedup_review_ids == ()


def test_18_discovery_emits_no_theme_root_and_writes_nothing(tmp_path, taxonomy, catalog, ruleset) -> None:
    result = run((N1, N2, observation("o"), fact("f")), taxonomy, catalog, ruleset)
    assert not list(tmp_path.iterdir())
    assert all(isinstance(p, (ThemeCandidateProposal,)) or p.proposal_type is not ProposalType.THEME_CANDIDATE for p in result.proposals)
    plain = json.dumps(result.run_report.to_plain())
    for token in ("throot", "root_id", "observation_id", "revision", "ThemeStore"):
        assert token not in plain, token


# ---------------------------------------------------------------- §20 hygiene（本 gate が追加した成果物の内容）

B4D_ARTIFACTS = ("tests/intelligence/test_theme_discovery_e2e.py", "tests/intelligence/test_theme_discovery_false_positive.py",
                 "tests/intelligence/test_theme_discovery_replay.py", "docs/databank/PHASE6_THEME_DISCOVERY_E2E_GATE.md")
# 検査対象の literal が本 file 自身に現れないよう、token は分割して組み立てる。
CONFIDENTIAL_TOKENS = tuple("".join(parts) for parts in (
    ("Comp", "ass"), ("comp", "ass"), ("羅針", "盤"), ("THEME_DISCOVERY", "_RULES"), ("watch", "list"), ("Watch", "list"),
    ("顧", "客"), ("custo", "mer"), ("benefi", "ciar"), ("target ", "price"), ("recom", "mend")))
SECRET_TOKENS = tuple("".join(parts) for parts in (("api", "_key"), ("API", "_KEY"), ("tok", "en="),
                                                   ("pass", "word"), ("Author", "ization")))
_BS, _SEP = chr(92), chr(47)
MACHINE_PATH_RE = __import__("re").compile("|".join(("[A-Za-z]:" + _BS * 2, _SEP + "User" + "s" + _SEP,
                                                     _SEP + "hom" + "e" + _SEP + "[a-z]+" + _SEP, _BS * 4)))


def test_19_b4d_artifacts_contain_no_confidential_or_machine_specific_content() -> None:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    config = __import__("yaml").safe_load((repo_root / "config.yaml").read_text(encoding="utf-8"))
    names, tickers = set(), set()
    for group in (config.get("".join(("watch", "list"))) or {}).values():
        for item in group or []:
            if isinstance(item, dict):
                if item.get("name"):
                    names.add(str(item["name"]))
                if item.get("ticker"):
                    tickers.add(str(item["ticker"]))
    assert names and tickers
    for relative in B4D_ARTIFACTS:
        path = repo_root / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        for token in CONFIDENTIAL_TOKENS:
            assert token not in text, (relative, token)
        for company in names | tickers:
            assert company not in text, (relative, company)
        assert not MACHINE_PATH_RE.search(text), relative
        for secret in SECRET_TOKENS:
            assert secret not in text, (relative, secret)
