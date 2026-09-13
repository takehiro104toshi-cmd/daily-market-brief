"""Phase 1-A synthetic fixtures（実データの大量コピーはしない・最小構成）。

P1-A指示の10ケース:
BOJ声明 / Fed声明 / CPIリリース / 日本株観測 / 米株観測 / 決算リリース /
Reuters風二次記事 / 矛盾ソース / 改定された経済統計 / 裏付けなしAI生成文
＋ 因果トレース例（金利上昇→グロース圧迫→半導体上値抑制）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.intelligence.core.ids import new_id, sha256_hex
from src.intelligence.core.types import Direction, Horizon, SourceTier
from src.intelligence.evidence.model import (
    AnalysisStatement,
    Attribution,
    EvidenceLink,
    EvidenceRelation,
    FactStatement,
    ForecastMetadata,
    ForecastStatement,
)
from src.intelligence.market.model import Observation, ObservationKind
from src.intelligence.sources.model import RawItem, SourceDocument

JST = timezone(timedelta(hours=9))
EST = timezone(timedelta(hours=-5))
NOW = datetime(2026, 8, 28, 8, 0, tzinfo=JST)


def _doc(source_id: str, tier: SourceTier, title: str, locator: str,
         published_at: datetime, body: bytes, **kw) -> SourceDocument:
    content_hash = sha256_hex(body)
    return SourceDocument(
        source_document_id=SourceDocument.make_id(source_id, locator, content_hash),
        source_id=source_id, source_tier=tier, title=title, locator=locator,
        retrieved_at=NOW, published_at=published_at, content_hash=content_hash, **kw,
    )


def boj_statement():
    """1) BOJ声明: Tier1文書 + FACT + SUPPORTSリンク。"""
    doc = _doc("boj_whatsnew", SourceTier.TIER1, "金融政策決定会合の結果",
               "https://www.boj.or.jp/example/mpm2026.pdf",
               datetime(2026, 8, 27, 12, 0, tzinfo=JST), b"boj-mpm-body",
               publisher="日本銀行", language="ja")
    fact = FactStatement(
        statement_id=new_id("fact", NOW), created_at=NOW,
        text="日銀は政策金利の据え置きを決定した",
        event_time=datetime(2026, 8, 27, 12, 0, tzinfo=JST),
        entities=("org:boj",), themes=("金利",),
    )
    link = EvidenceLink(
        link_id=new_id("link", NOW), claim_id=fact.statement_id,
        evidence_id=doc.source_document_id,
        relation=EvidenceRelation.SUPPORTS, created_at=NOW,
    )
    return doc, fact, link


def fed_statement():
    """2) Fed声明: Tier1文書 + FACT（英語・EST）。"""
    doc = _doc("fed_press", SourceTier.TIER1, "FOMC statement",
               "https://www.federalreserve.gov/example/fomc2026.htm",
               datetime(2026, 8, 26, 14, 0, tzinfo=EST), b"fomc-body",
               publisher="Federal Reserve", language="en")
    fact = FactStatement(
        statement_id=new_id("fact", NOW), created_at=NOW, language="en",
        text="The FOMC decided to raise the target range by 25bp",
        event_time=datetime(2026, 8, 26, 14, 0, tzinfo=EST),
        entities=("org:fed",), themes=("金利",),
    )
    link = EvidenceLink(
        link_id=new_id("link", NOW), claim_id=fact.statement_id,
        evidence_id=doc.source_document_id,
        relation=EvidenceRelation.SUPPORTS, created_at=NOW,
    )
    return doc, fact, link


def cpi_release_with_revision():
    """3)+9) CPIリリース: 文書 + raw観測 + 後日の改定観測（revision_of・過去値保持）。"""
    doc = _doc("us_bls", SourceTier.TIER1, "Consumer Price Index - July 2026",
               "https://www.bls.gov/example/cpi0726.htm",
               datetime(2026, 8, 12, 8, 30, tzinfo=EST), b"cpi-body",
               publisher="BLS", language="en")
    first = Observation(
        observation_id=new_id("obs", NOW), entity_id="macro:us_cpi", metric="yoy_pct",
        value=Decimal("4.1"), unit="pct",
        as_of=datetime(2026, 7, 31, 23, 59, tzinfo=timezone.utc),
        source_id="us_bls", source_document_id=doc.source_document_id,
        calculation_method="published",
    )
    revised = Observation(
        observation_id=new_id("obs", NOW + timedelta(days=30)),
        entity_id="macro:us_cpi", metric="yoy_pct",
        value=Decimal("4.2"), unit="pct",
        as_of=datetime(2026, 7, 31, 23, 59, tzinfo=timezone.utc),
        source_id="us_bls", calculation_method="published_revised",
        revision_of=first.observation_id,
    )
    return doc, first, revised


def jp_stock_observation():
    """4) 日本株観測: Decimal・JPY。"""
    return Observation(
        observation_id=new_id("obs", NOW), entity_id="equity:7203.T", metric="close",
        value=Decimal("2700.5"), unit="jpy", currency="JPY",
        as_of=datetime(2026, 8, 27, 15, 0, tzinfo=JST),
        source_id="jpx_example", calculation_method="close",
    )


def us_stock_observation():
    return Observation(
        observation_id=new_id("obs", NOW), entity_id="equity:AMZN", metric="close",
        value=Decimal("201.34"), unit="usd", currency="USD",
        as_of=datetime(2026, 8, 27, 16, 0, tzinfo=EST),
        source_id="us_market_example", calculation_method="close",
    )


def derived_observation(base: Observation):
    """派生観測: 25日MA乖離率（inputsで由来観測へトレース可能）。"""
    return Observation(
        observation_id=new_id("obs", NOW), entity_id=base.entity_id, metric="dev_25dma",
        value=Decimal("4.85"), unit="pct", as_of=base.as_of,
        kind=ObservationKind.DERIVED, calculation_method="deviation_pct_25dma",
        inputs=(base.observation_id,),
    )


def earnings_release():
    """6) 決算リリース: IR文書 + FACT + EPS観測。"""
    doc = _doc("company_ir_example", SourceTier.TIER1, "2027年3月期 第1四半期決算短信",
               "https://example.ir/7203/q1.pdf",
               datetime(2026, 8, 5, 15, 0, tzinfo=JST), b"tanshin-body",
               publisher="トヨタ自動車", language="ja")
    fact = FactStatement(
        statement_id=new_id("fact", NOW), created_at=NOW,
        text="トヨタ自動車の1Q営業利益は前年同期比10%増だった",
        event_time=datetime(2026, 8, 5, 15, 0, tzinfo=JST),
        entities=("equity:7203.T",), themes=("自動車",),
    )
    link = EvidenceLink(
        link_id=new_id("link", NOW), claim_id=fact.statement_id,
        evidence_id=doc.source_document_id,
        relation=EvidenceRelation.SUPPORTS, created_at=NOW,
    )
    eps = Observation(
        observation_id=new_id("obs", NOW), entity_id="equity:7203.T", metric="eps_q1",
        value=Decimal("62.50"), unit="jpy", currency="JPY",
        as_of=datetime(2026, 6, 30, 23, 59, tzinfo=JST),
        source_id="company_ir_example", source_document_id=doc.source_document_id,
        calculation_method="published",
    )
    return doc, fact, link, eps


def secondary_article():
    """7) Reuters風二次記事: Tier2 + 伝聞FACT（attribution=REPORTED）。"""
    doc = _doc("reuters_like", SourceTier.TIER2, "関係者によると政府は復興基金を検討",
               "https://example.news/article/123",
               datetime(2026, 8, 27, 22, 0, tzinfo=JST), b"secondary-body",
               publisher="Example Wire", language="ja")
    fact = FactStatement(
        statement_id=new_id("fact", NOW), created_at=NOW,
        text="政府が3,000億ドル規模の復興基金設立を検討していると伝わっている",
        attribution=Attribution.REPORTED,
        entities=("org:gov_example",), themes=("防衛",),
    )
    link = EvidenceLink(
        link_id=new_id("link", NOW), claim_id=fact.statement_id,
        evidence_id=doc.source_document_id,
        relation=EvidenceRelation.SUPPORTS, created_at=NOW,
    )
    return doc, fact, link


def conflicting_sources():
    """8) 矛盾ソース: 1つのFACTにSUPPORTSとCONTRADICTS → CONFLICTING（両方保持）。"""
    doc_a = _doc("wire_a", SourceTier.TIER2, "工場は9月に稼働開始へ",
                 "https://example.a/1", datetime(2026, 8, 27, 9, 0, tzinfo=JST), b"a-body")
    doc_b = _doc("wire_b", SourceTier.TIER2, "工場の稼働開始は12月に延期",
                 "https://example.b/1", datetime(2026, 8, 27, 11, 0, tzinfo=JST), b"b-body")
    fact = FactStatement(
        statement_id=new_id("fact", NOW), created_at=NOW,
        text="新工場は2026年9月に稼働を開始する",
        entities=("equity:XXXX.T",),
    )
    links = (
        EvidenceLink(link_id=new_id("link", NOW), claim_id=fact.statement_id,
                     evidence_id=doc_a.source_document_id,
                     relation=EvidenceRelation.SUPPORTS, created_at=NOW),
        EvidenceLink(link_id=new_id("link", NOW), claim_id=fact.statement_id,
                     evidence_id=doc_b.source_document_id,
                     relation=EvidenceRelation.CONTRADICTS, created_at=NOW),
    )
    return doc_a, doc_b, fact, links


def unsupported_ai_claim():
    """10) 裏付けなしAI生成文: リンクゼロのFACT → UNSUPPORTEDとして機械検出される。"""
    return FactStatement(
        statement_id=new_id("fact", NOW), created_at=NOW,
        text="ある半導体企業の受注が過去最高になった（AI生成・出典なし）",
    )


def causal_chain():
    """因果トレース例: Fed利上げFACT → [JP_US_001] グロース圧迫ANALYSIS → 半導体FORECAST。"""
    fed_doc, fed_fact, fed_link = fed_statement()
    analysis = AnalysisStatement(
        statement_id=new_id("ana", NOW), created_at=NOW,
        text="米金利の上昇は高PERグロース株のバリュエーション圧力となる",
        inputs=(fed_fact.statement_id,), rule_id="JP_US_001", agent="rule_engine",
        themes=("金利",),
    )
    forecast = ForecastStatement(
        statement_id=new_id("fcst", NOW), created_at=NOW,
        text="半導体株の上値は当面抑制されよう",
        themes=("半導体",),
        forecast=ForecastMetadata(
            target="theme:半導体", direction=Direction.SLIGHTLY_DOWN,
            horizon=Horizon.ONE_WEEK, confidence=3, generated_at=NOW,
            predictor="rule_engine",
            supporting_evidence=(analysis.statement_id, fed_fact.statement_id),
            counter_points=("AI需要の構造的成長は不変",),
            invalidation_conditions=("SOX指数が5日連続で上昇した場合",),
            evaluate_by=NOW + timedelta(days=7),
        ),
    )
    ana_link = EvidenceLink(
        link_id=new_id("link", NOW), claim_id=analysis.statement_id,
        evidence_id=fed_fact.statement_id,
        relation=EvidenceRelation.DERIVED_FROM, created_at=NOW,
    )
    fcst_link = EvidenceLink(
        link_id=new_id("link", NOW), claim_id=forecast.statement_id,
        evidence_id=analysis.statement_id,
        relation=EvidenceRelation.DERIVED_FROM, created_at=NOW,
    )
    return fed_doc, fed_fact, fed_link, analysis, forecast, ana_link, fcst_link


def raw_item_for(doc: SourceDocument, body: bytes) -> RawItem:
    return RawItem(
        raw_item_id=RawItem.make_id(doc.source_id, doc.locator, sha256_hex(body)),
        source_id=doc.source_id, locator=doc.locator, retrieved_at=NOW,
        media_type="text/html", content_hash=sha256_hex(body),
        size_bytes=len(body), storage_ref=f"data/vnext/raw/{doc.source_document_id}.bin",
    )
