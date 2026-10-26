"""P6-B4D — point-in-time 境界と replay / 決定性（§15, §16）。

- cutoff 等号は許し、1 マイクロ秒の超過は fail closed（入力 4 種 ＋ knowledge 3 種）。
- 旧 version に pin した replay は旧 knowledge の意味のまま再現し、新 version の語彙を混入させない。
- 同じ入力集合・同じ knowledge・同じ run 時刻なら、順序・再読み込みに依らず proposal id / canonical bytes /
  run report / 診断順序が一致する。現在時刻・乱数・network は使わない。
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from src.intelligence.facts.model import FactStatus
from src.intelligence.theme_intelligence.discovery import discover
from src.intelligence.theme_intelligence.discovery_adapter import adapt_inputs
from src.intelligence.theme_intelligence.discovery_model import DiscoveryError
from src.intelligence.theme_intelligence.discovery_rules import discovery_rules_path, load_discovery_rules_version
from src.intelligence.theme_intelligence.entity_catalog import entity_catalog_path, load_entity_catalog_version
from src.intelligence.theme_intelligence.knowledge_loader import KnowledgeError
from src.intelligence.theme_intelligence.proposal_model import (DecisionKind, ProposalDecision, ProposalType, canonical_proposal_line)
from src.intelligence.theme_intelligence.taxonomy import load_taxonomy_version, taxonomy_path
from tests.intelligence.test_theme_discovery import (CUTOFF, JP, KNOWLEDGE_ROOT, RUN_AT, T, catalog, did, document, fact,  # noqa: F401
                                                     fid, load_rules, news, nid, observation, of_type, oid, rule, ruleset,
                                                     run, taxonomy)

UTC = timezone.utc
TICK = timedelta(microseconds=1)
KNOWLEDGE_010 = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
KNOWLEDGE_020 = datetime(2026, 9, 20, 1, 0, tzinfo=UTC)
RULESET_PUBLISHED = datetime(2026, 9, 20, 2, 0, tzinfo=UTC)
EARLY_RULESET = datetime(2026, 9, 20, 0, 30, tzinfo=UTC)
EARLY_CUTOFF = datetime(2026, 9, 20, 0, 45, tzinfo=UTC)
REPLAY_INPUTS = (news("1", "Data centre construction lifts electric power demand"),
                 news("2", "Datacenter operators sign electric power contracts"),
                 news("3", "Nuclear power and data centre plans in Japan"),
                 document("d", "Bank of Japan on electric power"), observation("o"), fact("f"))


# ---------------------------------------------------------------- §15 入力側の PIT 境界


@pytest.mark.parametrize("builder,reason", [
    (lambda moment: news("z", "Bank of Japan statement", refs=(), published=moment), "AFTER_CUTOFF"),
    (lambda moment: document("z", "Bank of Japan statement", published=moment, retrieved=T), "AFTER_CUTOFF"),
    (lambda moment: document("z", "Bank of Japan statement", published=T, retrieved=moment), "KNOWN_AFTER_CUTOFF"),
    (lambda moment: observation("z", as_of=moment), "AFTER_CUTOFF"),
    (lambda moment: fact("z", known_at=moment), "KNOWN_AFTER_CUTOFF")])
def test_46_cutoff_equality_is_allowed_and_one_microsecond_later_is_excluded(taxonomy, catalog, builder, reason) -> None:
    at_cutoff = adapt_inputs([builder(CUTOFF)], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    assert len(at_cutoff.records) == 1 and at_cutoff.excluded == ()
    after = adapt_inputs([builder(CUTOFF + TICK)], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
    assert after.records == () and [e.reason for e in after.excluded] == [reason]


def test_47_a_late_input_changes_nothing_else_in_the_run(taxonomy, catalog, ruleset) -> None:
    base = run(REPLAY_INPUTS, taxonomy, catalog, ruleset)
    late = news("late", "Datacenter expansion in Japan", published=CUTOFF + TICK)
    with_late = run(tuple(REPLAY_INPUTS) + (late,), taxonomy, catalog, ruleset)
    assert [p.proposal_id for p in with_late.proposals] == [p.proposal_id for p in base.proposals]
    assert [(e.input_id, e.reason) for e in with_late.run_report.excluded_inputs] == [(nid("late"), "AFTER_CUTOFF")]
    assert with_late.run_report.normalized_input_count == base.run_report.normalized_input_count


def test_48_unusable_facts_are_excluded_regardless_of_time(taxonomy, catalog) -> None:
    for status in (FactStatus.LIMITED_USE, FactStatus.UNUSABLE):
        result = adapt_inputs([fact("u", status=status, known_at=T)], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF)
        assert result.records == () and result.excluded[0].reason == f"FACT_NOT_USABLE:{status.value}"


# ---------------------------------------------------------------- §15 knowledge 側の PIT 境界


def test_49_knowledge_published_exactly_at_cutoff_is_usable(taxonomy, catalog, ruleset) -> None:
    assert (taxonomy.published_at, catalog.published_at, ruleset.published_at) == (KNOWLEDGE_020, KNOWLEDGE_020, RULESET_PUBLISHED)
    result = run((observation("o"),), taxonomy, catalog, ruleset, cutoff=RULESET_PUBLISHED, run_created_at=RULESET_PUBLISHED)
    assert len(of_type(result, ProposalType.EVIDENCE_CANDIDATE)) == 1
    assert result.run_report.cutoff == RULESET_PUBLISHED


@pytest.mark.parametrize("cutoff,missing", [(RULESET_PUBLISHED - TICK, "ruleset"), (KNOWLEDGE_020 - TICK, "taxonomy")])
def test_50_knowledge_published_after_the_cutoff_fails_closed(taxonomy, catalog, ruleset, cutoff, missing) -> None:
    with pytest.raises(DiscoveryError) as info:
        run((observation("o"),), taxonomy, catalog, ruleset, cutoff=cutoff, run_created_at=cutoff)
    assert info.value.code == "FUTURE_KNOWLEDGE" and missing in info.value.detail


def test_51_the_loader_refuses_a_version_published_after_the_cutoff(taxonomy, catalog) -> None:
    with pytest.raises(KnowledgeError) as info:
        load_discovery_rules_version(discovery_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0",
                                     cutoff=RULESET_PUBLISHED - TICK)
    assert info.value.code == "FUTURE_VERSION"
    assert load_discovery_rules_version(discovery_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0",
                                        cutoff=RULESET_PUBLISHED).ruleset_version == "0.1.0"
    with pytest.raises(KnowledgeError) as info:
        load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=KNOWLEDGE_020 - TICK)
    assert info.value.code == "FUTURE_VERSION"


# ---------------------------------------------------------------- §15 旧 version への replay


@pytest.fixture(scope="module")
def knowledge_010():
    tax = load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=EARLY_CUTOFF)
    cat = load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=EARLY_CUTOFF)
    assert (tax.published_at, cat.published_at) == (KNOWLEDGE_010, KNOWLEDGE_010)
    return tax, cat


LEGACY_SUPPLY_RULE = rule("supply_chain_replay_evidence", entity_refs=[], taxonomy_refs=["supply_chain_theme"],
                          predicate={"kind": "TAXONOMY_SIGNAL", "slug": "supply_chain_theme"})
CURRENT_SUPPLY_RULE = rule("supply_chain_replay_evidence", entity_refs=[], taxonomy_refs=["supply_chain"],
                           predicate={"kind": "TAXONOMY_SIGNAL", "slug": "supply_chain"})


def test_52_replay_at_an_old_cutoff_uses_the_old_slug_not_its_successor(tmp_path, knowledge_010, taxonomy, catalog) -> None:
    tax1, cat1 = knowledge_010
    old_rules = load_rules(tmp_path / "old", [LEGACY_SUPPLY_RULE], tax1, cat1, cutoff=EARLY_CUTOFF, published=EARLY_RULESET,
                           taxonomy_version="0.1.0", catalog_version="0.1.0")
    item = news("s", "supply chain resilience review", refs=())
    replayed = discover([item], taxonomy=tax1, entity_catalog=cat1, ruleset=old_rules, cutoff=EARLY_CUTOFF,
                        run_created_at=EARLY_CUTOFF)
    assert [p.ref_id for p in of_type(replayed, ProposalType.EVIDENCE_CANDIDATE)] == [nid("s")]
    old_record = adapt_inputs([item], taxonomy=tax1, entity_catalog=cat1, cutoff=EARLY_CUTOFF).records[0]
    assert old_record.taxonomy_slugs() == ("supply_chain_theme",) and tax1.node("supply_chain") is None
    new_record = adapt_inputs([item], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records[0]
    assert new_record.taxonomy_slugs() == ("supply_chain",)


def test_53_an_old_ruleset_cannot_be_run_against_new_knowledge(tmp_path, knowledge_010, taxonomy, catalog) -> None:
    tax1, cat1 = knowledge_010
    old_rules = load_rules(tmp_path / "old", [LEGACY_SUPPLY_RULE], tax1, cat1, cutoff=EARLY_CUTOFF, published=EARLY_RULESET,
                           taxonomy_version="0.1.0", catalog_version="0.1.0")
    with pytest.raises(KnowledgeError) as info:
        discover([], taxonomy=taxonomy, entity_catalog=catalog, ruleset=old_rules, cutoff=CUTOFF, run_created_at=RUN_AT)
    assert info.value.code == "TAXONOMY_PIN_MISMATCH"
    with pytest.raises(KnowledgeError) as info:
        load_rules(tmp_path / "mixed", [CURRENT_SUPPLY_RULE], tax1, cat1, cutoff=EARLY_CUTOFF, published=EARLY_RULESET,
                   taxonomy_version="0.1.0", catalog_version="0.1.0")
    assert info.value.code == "INVALID_RULE_REFERENCE"                     # 0.1.0 に supply_chain は存在しない


def test_54_entity_replay_keeps_the_old_identity_surface(knowledge_010, taxonomy, catalog) -> None:
    tax1, cat1 = knowledge_010
    old_name = news("o", "Example Motors output", refs=())
    new_name = news("n", "Example Mobility output", refs=())
    old = adapt_inputs([old_name, new_name], taxonomy=tax1, entity_catalog=cat1, cutoff=EARLY_CUTOFF).records
    assert [tuple(h.entity_id for h in r.entity_hits) for r in old] == [(), ("company:example_motors",)]
    current = adapt_inputs([old_name, new_name], taxonomy=taxonomy, entity_catalog=catalog, cutoff=CUTOFF).records
    assert [tuple(h.entity_id for h in r.entity_hits) for r in current] == [("company:example_motors",), ("company:example_motors",)]
    assert cat1.entity("company:example_energy_systems") is None


# ---------------------------------------------------------------- §16 決定性


def _decision(proposal_id: str, kind: DecisionKind, *, at, supersedes: str = "") -> ProposalDecision:
    return ProposalDecision.build(proposal_id=proposal_id, decision=kind, actor_ref="reviewer:r9", reason="reviewed", recorded_at=at,
                                  supersedes_decision_id=supersedes)


def test_55_ten_shuffled_input_orders_replay_byte_identically(taxonomy, catalog, ruleset) -> None:
    base = run(REPLAY_INPUTS, taxonomy, catalog, ruleset)
    base_lines = [canonical_proposal_line(p) for p in base.proposals]
    assert base.proposals and base_lines == sorted(set(base_lines), key=base_lines.index)
    for seed in range(10):
        shuffled = list(REPLAY_INPUTS)
        random.Random(seed).shuffle(shuffled)
        again = run(shuffled, taxonomy, catalog, ruleset)
        assert [p.proposal_id for p in again.proposals] == [p.proposal_id for p in base.proposals], seed
        assert [canonical_proposal_line(p) for p in again.proposals] == base_lines, seed
        assert again.run_report.to_plain() == base.run_report.to_plain(), seed


def test_56_shuffled_existing_proposals_and_decisions_replay_identically(taxonomy, catalog, ruleset) -> None:
    first = run(REPLAY_INPUTS, taxonomy, catalog, ruleset)
    decisions = []
    for index, proposal in enumerate(first.proposals):
        deferred = _decision(proposal.proposal_id, DecisionKind.DEFER, at=RUN_AT + timedelta(hours=1 + index))
        decisions.append(deferred)                                          # chain は supersedes graph で決まる（recorded_at ではない）
        decisions.append(_decision(proposal.proposal_id, DecisionKind.ACCEPT, at=RUN_AT + timedelta(days=1, hours=1 + index),
                                   supersedes=deferred.decision_id))
    later = RUN_AT + timedelta(days=2)
    base = run(REPLAY_INPUTS, taxonomy, catalog, ruleset, existing_proposals=first.proposals, existing_decisions=tuple(decisions),
               run_created_at=later)
    assert base.proposals == () and all(d.startswith("EXISTING_ACCEPTED_PROPOSAL:") for d in base.run_report.diagnostics
                                        if d.startswith("EXISTING_"))
    for seed in range(10):
        proposals, decided = list(first.proposals), list(decisions)
        random.Random(seed).shuffle(proposals)
        random.Random(seed + 100).shuffle(decided)
        again = run(REPLAY_INPUTS, taxonomy, catalog, ruleset, existing_proposals=tuple(proposals),
                    existing_decisions=tuple(decided), run_created_at=later)
        assert again.run_report.to_plain() == base.run_report.to_plain(), seed


def test_57_reloading_the_knowledge_from_disk_replays_identically(taxonomy, catalog, ruleset) -> None:
    base = run(REPLAY_INPUTS, taxonomy, catalog, ruleset)
    tax2 = load_taxonomy_version(taxonomy_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUTOFF)
    cat2 = load_entity_catalog_version(entity_catalog_path(KNOWLEDGE_ROOT, "0.2.0"), expected_version="0.2.0", cutoff=CUTOFF)
    rules2 = load_discovery_rules_version(discovery_rules_path(KNOWLEDGE_ROOT, "0.1.0"), expected_version="0.1.0", cutoff=CUTOFF,
                                          taxonomy=tax2, entity_catalog=cat2)
    assert (tax2.content_digest, cat2.content_digest, rules2.content_digest) == (taxonomy.content_digest, catalog.content_digest,
                                                                                 ruleset.content_digest)
    again = run(REPLAY_INPUTS, tax2, cat2, rules2)
    assert again.run_report.to_plain() == base.run_report.to_plain()
    assert [canonical_proposal_line(p) for p in again.proposals] == [canonical_proposal_line(p) for p in base.proposals]


def test_58_report_orderings_are_canonical_and_stable(taxonomy, catalog, ruleset) -> None:
    report = run(REPLAY_INPUTS, taxonomy, catalog, ruleset).run_report
    assert tuple(sorted(report.diagnostics)) == report.diagnostics == tuple(dict.fromkeys(report.diagnostics))
    assert tuple(sorted(report.suppressed_existing_ids)) == report.suppressed_existing_ids
    assert tuple(sorted(report.dedup_review_ids)) == report.dedup_review_ids
    assert [(h.rule_id, h.input_id) for h in report.rule_hits] == sorted((h.rule_id, h.input_id) for h in report.rule_hits)
    assert [e.rule_id for e in report.rule_evaluations] == [r.rule_id for r in ruleset.rules]
    assert [k for k, _ids in report.origin_groups] == sorted(k for k, _ids in report.origin_groups)
    assert all(tuple(sorted(ids)) == ids for _k, ids in report.origin_groups)
    assert [e.input_id for e in report.excluded_inputs] == sorted(e.input_id for e in report.excluded_inputs)
    for evaluation_row in report.rule_evaluations:
        assert tuple(sorted(evaluation_row.emitted_proposal_ids)) == evaluation_row.emitted_proposal_ids


def test_59_run_created_at_only_moves_audit_fields_not_identity(taxonomy, catalog, ruleset) -> None:
    base = run(REPLAY_INPUTS, taxonomy, catalog, ruleset)
    later = run(REPLAY_INPUTS, taxonomy, catalog, ruleset, run_created_at=RUN_AT + timedelta(days=30))
    assert [p.proposal_id for p in later.proposals] == [p.proposal_id for p in base.proposals]
    assert {p.created_at for p in later.proposals} == {RUN_AT + timedelta(days=30)}
    themes = of_type(later, ProposalType.THEME_CANDIDATE)
    assert themes and all(a.attached_at == RUN_AT + timedelta(days=30) for t in themes for a in t.evidence_refs)
    assert [t.identity_payload() for t in themes] == [t.identity_payload() for t in of_type(base, ProposalType.THEME_CANDIDATE)]


def test_60_discovery_uses_no_wall_clock_randomness_or_network(taxonomy, catalog, ruleset) -> None:
    random.seed(1234)
    first = run(REPLAY_INPUTS, taxonomy, catalog, ruleset)
    random.seed(9999)
    second = run(REPLAY_INPUTS, taxonomy, catalog, ruleset)
    assert first.run_report.to_plain() == second.run_report.to_plain()
    assert first.run_report.run_created_at == RUN_AT and first.run_report.cutoff == CUTOFF
