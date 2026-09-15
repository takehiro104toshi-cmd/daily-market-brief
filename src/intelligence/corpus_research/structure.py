"""AnalyticalStructure（Phase 3.8 §5）— 1 document の分析構造。支持のない field は空のまま（捏造しない）。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence

from ..corpus.store import CorpusStore
from .categories import OTHER, UNKNOWN, primary_category
from .config import ResearchConfig
from .links import build_links
from .outlook_model import extract_outlook, outlook_summary
from .regime import MarketConnector, RegimeAlignment, regime_alignment
from .risk_model import extract_risk, risk_summary
from .salience import salience_profile
from .statements import build_statements
from .why_model import classify_why, why_summary

STRUCTURE_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class AnalyticalStructure:
    structure_id: str
    document_id: str
    document_date: str
    corpus_analysis_version: str
    versions: Mapping[str, str]
    version_key: str
    quality: str
    eligible: bool
    market_state: Mapping[str, str]
    regime: Mapping[str, object]
    selected_evidence: List[Dict[str, object]]
    main_theme: Mapping[str, object]
    supporting_themes: List[str]
    interpretations: List[Dict[str, object]]
    why_links: List[Dict[str, object]]
    why_summary: Mapping[str, int]
    outlook: List[Dict[str, object]]
    outlook_summary: Mapping[str, object]
    risk: List[Dict[str, object]]
    risk_summary: Mapping[str, object]
    watch_items: List[Dict[str, object]]
    coverage_labels: Mapping[str, str]
    market_alignment: Mapping[str, object]
    salience_profile: List[Dict[str, object]]
    links: List[Dict[str, object]]
    field_support: Mapping[str, bool]
    p2_mode: str
    created_at: str
    pattern_assignments: List[str] = field(default_factory=list)
    schema_version: str = STRUCTURE_SCHEMA_VERSION

    def as_dict(self) -> Dict[str, object]:
        return {"structure_id": self.structure_id, "document_id": self.document_id,
                "document_date": self.document_date, "corpus_analysis_version": self.corpus_analysis_version,
                "versions": dict(self.versions), "version_key": self.version_key, "quality": self.quality,
                "eligible": self.eligible, "market_state": dict(self.market_state), "regime": dict(self.regime),
                "selected_evidence": list(self.selected_evidence), "main_theme": dict(self.main_theme),
                "supporting_themes": list(self.supporting_themes), "interpretations": list(self.interpretations),
                "why_links": list(self.why_links), "why_summary": dict(self.why_summary),
                "outlook": list(self.outlook), "outlook_summary": dict(self.outlook_summary),
                "risk": list(self.risk), "risk_summary": dict(self.risk_summary),
                "watch_items": list(self.watch_items), "coverage_labels": dict(self.coverage_labels),
                "market_alignment": dict(self.market_alignment),
                "salience_profile": list(self.salience_profile), "links": list(self.links),
                "field_support": dict(self.field_support), "p2_mode": self.p2_mode,
                "created_at": self.created_at, "pattern_assignments": list(self.pattern_assignments),
                "schema_version": self.schema_version}


def structure_id_for(document_id: str, corpus_analysis_version: str, version_key: str) -> str:
    seed = f"{document_id}|{corpus_analysis_version}|{version_key}"
    return "crs_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def analyze_structure(store: CorpusStore, document_id: str, config: ResearchConfig,
                      connector: MarketConnector, now: datetime) -> Optional[AnalyticalStructure]:
    doc = store.document(document_id)
    record = store.current_analysis(document_id)
    if doc is None or record is None:
        return None
    artifacts = store.artifacts_for(document_id)
    quality_row = store.quality_for(document_id) or {}
    quality = str(quality_row.get("quality", ""))
    eligible = bool(quality_row.get("eligible_for_pattern_evidence"))
    coverage = store.coverage_for(document_id)
    temporal = store.temporal_for(document_id)
    alignments = store.alignments_for(document_id)

    statements = build_statements(record, artifacts)
    links = build_links(statements)
    why_links = classify_why(statements, links)
    main_theme_obs = (record.get("observations") or {}).get("main_theme") or []
    main_theme_text = str(main_theme_obs[0].get("text", "")) if main_theme_obs else ""
    profile = salience_profile(statements, links, main_theme_text)
    outlook_items = extract_outlook(statements, str(record.get("p2_mode", "")))
    risk_items = extract_risk(statements)
    regime = regime_alignment(document_id=document_id, document_date=doc.document_date, coverage=coverage,
                              temporal=temporal, alignments=alignments, connector=connector)

    selected = [dict(c.as_dict(), text_hash_sample=None) for c in profile]
    for item in selected:
        item.pop("text_hash_sample", None)
    theme_cat = primary_category(main_theme_text) if main_theme_text else (profile[0].category if profile else UNKNOWN)
    main_theme = {"category": theme_cat, "source_observation_id": str(main_theme_obs[0].get("observation_id", "")) if main_theme_obs else "",
                  "basis": "P1_HEADING" if main_theme_obs and str(main_theme_obs[0].get("note", "")) == "" else
                  "THIRD_BULLET" if main_theme_obs else "TOP_SALIENCE",
                  "top_salient_category": profile[0].category if profile else UNKNOWN}
    supporting = [c.category for c in profile if c.category != theme_cat][:3]
    interpretations = [s.as_ref() for s in statements if s.level == "ANALYST_INTERPRETATION"]
    watch = [r.as_dict() for r in risk_items if r.risk_type == "WATCH_ITEM"]
    field_support = {
        "market_state": regime.known_dimensions > 0, "selected_evidence": bool(profile),
        "main_theme": bool(main_theme_obs) or bool(profile), "supporting_themes": bool(supporting),
        "interpretations": bool(interpretations), "why_links": any(w.why_type == "EXPLICIT_WHY" for w in why_links),
        "outlook": bool(outlook_items), "risk": any(r.risk_type != "WATCH_ITEM" for r in risk_items),
        "watch_items": bool(watch), "coverage_labels": coverage is not None,
        "market_alignment": regime.comparable_values > 0,
    }
    return AnalyticalStructure(
        structure_id=structure_id_for(document_id, str(record.get("analysis_version", "")), config.version_key),
        document_id=document_id, document_date=doc.document_date,
        corpus_analysis_version=str(record.get("analysis_version", "")), versions=config.versions(),
        version_key=config.version_key, quality=quality, eligible=eligible,
        market_state=dict(regime.labels), regime=regime.as_dict(), selected_evidence=selected,
        main_theme=main_theme, supporting_themes=supporting, interpretations=interpretations,
        why_links=[w.as_dict() for w in why_links], why_summary=why_summary(why_links),
        outlook=[o.as_dict() for o in outlook_items], outlook_summary=outlook_summary(outlook_items),
        risk=[r.as_dict() for r in risk_items if r.risk_type != "WATCH_ITEM"], risk_summary=risk_summary(risk_items),
        watch_items=watch, coverage_labels=dict((coverage or {}).get("labels", {})),
        market_alignment={"summary": dict(regime.alignment_summary), "comparable_values": regime.comparable_values,
                          "referenced_session": regime.referenced_session},
        salience_profile=[c.as_dict() for c in profile], links=[l.as_dict() for l in links],
        field_support=field_support, p2_mode=str(record.get("p2_mode", "")), created_at=now.isoformat())
