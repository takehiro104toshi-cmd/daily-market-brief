"""src/collectors/ の重複除去・信頼度スコア・新規情報源のオフライン検証。

新規情報源（nikkei/bloomberg/reuters/cnbc/wsj/marketwatch/investing/boj/mof/
edinet/macro）は、到達不能なローカルアドレス（http://127.0.0.1:1/...）に
差し替えることで、実ネットワークへ問い合わせずに「取得失敗時は空リストを
返し、処理全体は継続する」ことを検証する。
"""
from src.collectors import (
    bloomberg,
    boj,
    cnbc,
    edinet,
    investing,
    jpx,
    kabutan,
    macro,
    marketwatch,
    minkabu,
    mof,
    moomoo,
    nikkei,
    rakuten,
    reuters,
    sbi,
    wsj,
)
from src.collectors.news import Headline, dedupe_headlines
from src.utils import SourceRegistry

UNREACHABLE = "http://127.0.0.1:1"


def test_dedupe_headlines_keeps_higher_reliability_source():
    headlines = [
        Headline(title="日経平均が急伸", link="https://a.example.com/1", source="低信頼源", reliability=0.3),
        Headline(title="日経平均が急伸", link="https://b.example.com/1", source="高信頼源", reliability=0.9),
    ]
    result = dedupe_headlines(headlines)
    assert len(result) == 1
    assert result[0].source == "高信頼源"


def test_dedupe_headlines_normalizes_whitespace_and_punctuation():
    headlines = [
        Headline(title="日経平均、急伸。", link="https://a.example.com/1", source="A", reliability=0.5),
        Headline(title="日経平均 急伸", link="https://b.example.com/1", source="B", reliability=0.5),
    ]
    result = dedupe_headlines(headlines)
    assert len(result) == 1


def test_dedupe_headlines_preserves_distinct_headlines_and_urls():
    headlines = [
        Headline(title="ニュースA", link="https://a.example.com/1", source="A", reliability=0.5),
        Headline(title="ニュースB", link="https://b.example.com/2", source="B", reliability=0.5),
    ]
    result = dedupe_headlines(headlines)
    assert len(result) == 2
    links = {h.link for h in result}
    assert links == {"https://a.example.com/1", "https://b.example.com/2"}


def test_dedupe_headlines_handles_empty_list():
    assert dedupe_headlines([]) == []


def test_dedupe_headlines_strips_wire_service_prefix():
    # 同じ記事を別媒体が配信し、片方だけに "Analysis:" が付くケース（実運用で発生）。
    # 接頭辞を無視して重複と判定し、信頼度の高い方を残す。
    headlines = [
        Headline(title="Analysis:Could AI chip boom make ASML Europe's first trillion-dollar firm?",
                 link="https://cna.example/1", source="CNA", reliability=0.4),
        Headline(title="Could AI chip boom make ASML Europe's first trillion-dollar firm?",
                 link="https://yahoo.example/1", source="Yahoo", reliability=0.7),
    ]
    result = dedupe_headlines(headlines)
    assert len(result) == 1
    assert result[0].source == "Yahoo"


def test_dedupe_headlines_strips_update_and_japanese_prefixes():
    headlines = [
        Headline(title="UPDATE 2-Toyota raises full-year outlook", link="https://a/1", source="A", reliability=0.5),
        Headline(title="Toyota raises full-year outlook", link="https://b/1", source="B", reliability=0.5),
        Headline(title="速報：日銀が金利を据え置き", link="https://c/1", source="C", reliability=0.5),
        Headline(title="日銀が金利を据え置き", link="https://d/1", source="D", reliability=0.5),
    ]
    result = dedupe_headlines(headlines)
    assert len(result) == 2  # 2組がそれぞれ統合される


def test_dedupe_headlines_prefix_only_title_is_not_emptied():
    # 接頭辞のみの見出し（異常データ）を空文字化して誤統合しないこと。
    headlines = [
        Headline(title="Analysis:", link="https://a/1", source="A", reliability=0.5),
        Headline(title="Breaking:", link="https://b/1", source="B", reliability=0.5),
    ]
    result = dedupe_headlines(headlines)
    assert len(result) == 2  # 別々の（非空の）キーとして扱われ、統合されない


def test_nikkei_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = nikkei.fetch_nikkei_headlines(
        sources, limit=8, news_sources=[{"name": "日経テスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_bloomberg_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = bloomberg.fetch_bloomberg_headlines(
        sources, limit=8, news_sources=[{"name": "Bloombergテスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_reuters_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = reuters.fetch_reuters_headlines(
        sources, limit=8, news_sources=[{"name": "Reutersテスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_edinet_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = edinet.fetch_edinet_documents(sources, documents_url=f"{UNREACHABLE}/documents.json")
    assert result == []
    # 取得できなかった場合は出典として登録しない
    assert sources.all() == []


def test_macro_fred_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = macro.fetch_fred_series(
        sources,
        csv_url_template=f"{UNREACHABLE}/fredgraph.csv?id={{series_id}}",
        series_list=[{"id": "T10Y2Y", "name": "米10年-2年金利差"}],
    )
    assert result == []


def test_macro_fetch_macro_data_always_registers_trading_economics_reference():
    sources = SourceRegistry()
    macro.fetch_macro_data(
        sources,
        csv_url_template=f"{UNREACHABLE}/fredgraph.csv?id={{series_id}}",
        series_list=[],
    )
    labels = [ref.label for ref in sources.all()]
    assert any("Trading Economics" in label for label in labels)


def test_kabutan_moomoo_jpx_register_reference_only_without_network():
    sources = SourceRegistry()
    kabutan.register_reference(sources)
    moomoo.register_reference(sources)
    jpx.register_reference(sources)

    refs = sources.all()
    assert len(refs) == 3
    categories = {ref.category for ref in refs}
    assert categories == {"参照リンク"}
    urls = {ref.url for ref in refs}
    assert "https://kabutan.jp/" in urls


def test_cnbc_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = cnbc.fetch_cnbc_headlines(
        sources, limit=8, news_sources=[{"name": "CNBCテスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_wsj_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = wsj.fetch_wsj_headlines(
        sources, limit=8, news_sources=[{"name": "WSJテスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_marketwatch_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = marketwatch.fetch_marketwatch_headlines(
        sources, limit=8, news_sources=[{"name": "MarketWatchテスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_investing_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = investing.fetch_investing_headlines(
        sources, limit=8, news_sources=[{"name": "Investingテスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_boj_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = boj.fetch_boj_headlines(
        sources, limit=8, news_sources=[{"name": "日銀テスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_mof_headlines_degrades_gracefully_when_unreachable():
    sources = SourceRegistry()
    result = mof.fetch_mof_headlines(
        sources, limit=8, news_sources=[{"name": "財務省テスト", "url": f"{UNREACHABLE}/rss"}]
    )
    assert result == []


def test_minkabu_sbi_rakuten_register_reference_only_without_network():
    sources = SourceRegistry()
    minkabu.register_reference(sources)
    sbi.register_reference(sources)
    rakuten.register_reference(sources)

    refs = sources.all()
    assert len(refs) == 3
    categories = {ref.category for ref in refs}
    assert categories == {"参照リンク"}
    urls = {ref.url for ref in refs}
    assert "https://minkabu.jp/" in urls
    assert "https://www.sbisec.co.jp/" in urls
    assert "https://www.rakuten-sec.co.jp/" in urls
