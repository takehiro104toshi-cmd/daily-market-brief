"""BlockingIndex（Phase 2-C）: 総当たり禁止の候補生成。"""
from __future__ import annotations

from src.intelligence.databank.identity_blocking import BlockingIndex
from tests.intelligence.test_identity_resolver import make_doc


def test_exact_keys_always_retrieved() -> None:
    index = BlockingIndex()
    a = make_doc("doc_a", title="BOJ statement", summary="s",
                 url="https://e.org/a?utm_source=rss", guid="g1", source="boj")
    index.add(a)
    # canonical一致
    b = make_doc("doc_b", title="Totally different words entirely", summary="x",
                 url="https://e.org/a?utm_medium=feed")
    assert "doc_a" in index.candidates(b)
    # source内GUID一致
    c = make_doc("doc_c", title="Other title", summary="x",
                 url="https://e.org/zzz", guid="g1", source="boj")
    assert "doc_a" in index.candidates(c)
    # fingerprint一致（同title+summary）
    d = make_doc("doc_d", title="BOJ statement", summary="s", url="https://e.org/new")
    assert "doc_a" in index.candidates(d)


def test_title_prefix_bucket_catches_near_duplicates() -> None:
    index = BlockingIndex()
    a = make_doc("doc_a", title="Latest Oil Market News and Analysis for July 21",
                 summary="s", url="https://e.org/21")
    index.add(a)
    b = make_doc("doc_b", title="Latest Oil Market News and Analysis for July 22",
                 summary="t", url="https://e.org/22")
    assert "doc_a" in index.candidates(b)  # 数字違い連載も候補には入る（判定はresolver）


def test_unrelated_document_yields_no_candidates() -> None:
    """blocking成立の核心: 無関係文書は候補ゼロ（全件比較しない）。"""
    index = BlockingIndex()
    for i in range(200):
        index.add(make_doc(f"doc_{i}", title=f"Article number {i} about topic {i}",
                           summary="s", url=f"https://e.org/{i}",
                           source=f"src_{i % 7}"))
    probe = make_doc("doc_probe", title="完全に無関係な日本語の見出しです",
                     summary="x", url="https://jp.example/probe", source="src_jp")
    candidates = index.candidates(probe)
    assert candidates == set()
    assert index.documents_indexed == 200


def test_candidates_are_strict_subset_of_corpus() -> None:
    index = BlockingIndex()
    for i in range(100):
        index.add(make_doc(f"doc_{i}", title=f"Sector {i} outlook for quarter {i * 7}",
                           summary="s", url=f"https://e.org/{i}", source=f"s{i % 5}"))
    probe = make_doc("doc_probe", title="Sector 42 outlook for quarter 294",
                     summary="s", url="https://e.org/other", source="s2")
    candidates = index.candidates(probe)
    assert 0 < len(candidates) < 100  # 候補は全corpusの真部分集合（prefix＋同日同source分のみ）
