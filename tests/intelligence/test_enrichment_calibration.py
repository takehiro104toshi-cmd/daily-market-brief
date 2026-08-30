"""P2-E: 校正fixtureに対するprecision/recall測定（FALSE POSITIVE AUDIT）。

fixture precision/recall ≠ production precision/recall（P2-B以来のMETRIC LANGUAGE）。
- entity/ticker: **fixture false positive 0**（FALSE ENTITY LINK IS WORSE）を固定
- theme/event: fixture precisionを固定し、recallは実測値を下限つきで報告
"""
from __future__ import annotations

from src.intelligence.enrichment.entity_matcher import match_entities
from src.intelligence.enrichment.event_matcher import match_event_types, match_time_horizon
from src.intelligence.enrichment.theme_matcher import match_themes

from .enrichment_calibration import CALIBRATION
from .enrichment_fixtures import catalogs


def _run_all():
    ec, tt, et = catalogs()
    rows = []
    for case in CALIBRATION:
        fields = {"headline": case["headline"], "summary": case.get("summary", "")}
        got_entities = {m.entity.entity_id for m in match_entities(ec, fields).matches}
        got_themes = {t.theme.slug for t in match_themes(tt, fields)}
        got_events = {e.event_type.type_name for e in match_event_types(et, fields)}
        got_horizon = {h.horizon for h in match_time_horizon(et, fields)}
        rows.append((case, got_entities, got_themes, got_events, got_horizon))
    return rows


def _metrics(rows, key, got_index):
    tp = fp = fn = 0
    for row in rows:
        expected = row[0].get(key, set())
        got = row[got_index]
        tp += len(expected & got)
        fp += len(got - expected)
        fn += len(expected - got)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return precision, recall, fp, fn


class TestFixtureCalibration:
    def test_entity_fixture_precision_is_one(self):
        rows = _run_all()
        precision, recall, fp, _fn = _metrics(rows, "entities", 1)
        assert fp == 0, f"entity false positive on fixture: {fp}"
        assert precision == 1.0
        assert recall >= 0.9, f"entity fixture recall={recall:.2f}"

    def test_theme_fixture_precision(self):
        rows = _run_all()
        precision, recall, fp, _fn = _metrics(rows, "themes", 2)
        assert fp == 0, f"theme false positive on fixture: {fp}"
        assert recall >= 0.8, f"theme fixture recall={recall:.2f}"

    def test_event_fixture_precision(self):
        rows = _run_all()
        precision, recall, fp, _fn = _metrics(rows, "events", 3)
        assert fp == 0, f"event false positive on fixture: {fp}"
        assert recall >= 0.8, f"event fixture recall={recall:.2f}"

    def test_horizon_fixture(self):
        rows = _run_all()
        precision, _recall, fp, _fn = _metrics(rows, "horizon", 4)
        assert fp == 0 and precision == 1.0

    def test_report_numbers(self, capsys):
        """校正数値の記録用（final report転記のため出力）。"""
        rows = _run_all()
        for key, idx in (("entities", 1), ("themes", 2), ("events", 3)):
            p, r, fp, fn = _metrics(rows, key, idx)
            print(f"fixture {key}: precision={p:.3f} recall={r:.3f} fp={fp} fn={fn}")
        assert len(rows) == len(CALIBRATION)
