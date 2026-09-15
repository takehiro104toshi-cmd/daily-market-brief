"""P4-3b2a publication boundary の検証（Phase 4 P4-3b2a）。

検証するのは **公開境界だけ**である（P4-3a の意味論テストを複製しない）:

- 凍結済み公開契約を満たさない入力を **fail closed** で拒否すること
- 承認済み 5 file ちょうどの `/v2` を隔離して組み立てること
- legacy root（`index.html` / `history/**`）へ一切触れないこと
- 固定リンクページが配信内容・id・日付・JS・外部資源を含まないこと

ネットワークを使わない。リポジトリの実 Pages ファイルには触れない。
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from src.intelligence.reports.delivery import (
    PUBLIC_KEYS, PUBLIC_SIGNAL_KEYS, PUBLIC_UNAVAILABLE_REASONS,
)
from src.intelligence.reports.delivery_emit import LATEST_JSON, LATEST_MARKDOWN
from src.intelligence.reports.market_signal import SIGNAL_LEVEL_JA
from src.intelligence.reports import pages_parallel as pp

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "src" / "intelligence" / "reports" / "pages_parallel.py"
TEMPLATE = REPO_ROOT / "docs" / "pages" / "v2_index.html"
IMPORT_BOUNDARY_TEST = REPO_ROOT / "tests" / "intelligence" / "test_import_boundary.py"

SESSION = "2026-09-15"
REFERENCE = "2026-09-14"
JST_TODAY = "2026-09-15"
MARKDOWN = "# モーニングブリーフ（サンプル）\n\n本文の代わりの短い段落。\n"

#: 読み替えず凍結側から取る（5 ラベルも公開 key 集合も書き写さない）
APPROVED_LABEL = SIGNAL_LEVEL_JA["DOWNWARD_LEAN"]


# ---------------------------------------------------------------- fixtures / helpers

def build_payload(*, session=SESSION, reference=REFERENCE, markdown=MARKDOWN,
                  available=True, label=APPROVED_LABEL, reason="", **overrides):
    encoded = markdown.encode("utf-8")
    payload = {
        "schema_version": "0.1.0",
        "delivery_id": "delivery_" + "a" * 24,
        "session_date": session,
        "reference_session": reference,
        "brief_id": "brief_" + "b" * 24,
        "signal_id": "signal_" + "c" * 24,
        "markdown_sha256": hashlib.sha256(encoded).hexdigest(),
        "markdown_bytes": len(encoded),
        "signal": {"available": available, "label": label, "unavailable_reason": reason},
    }
    payload.update(overrides)
    return payload


def serialize(payload) -> str:
    """凍結 emitter と同じ決定論的バイト列。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def make_artifacts(tmp_path, *, dated_session=SESSION, markdown=MARKDOWN,
                   payload=None, json_text=None, name="artifact"):
    directory = tmp_path / name
    directory.mkdir()
    body = serialize(build_payload() if payload is None else payload) \
        if json_text is None else json_text
    for filename in (f"{dated_session}_morning_brief.md", LATEST_MARKDOWN):
        (directory / filename).write_text(markdown, encoding="utf-8")
    for filename in (f"{dated_session}_morning_brief.json", LATEST_JSON):
        (directory / filename).write_text(body, encoding="utf-8")
    return directory


def make_pages_site(tmp_path):
    """合成 legacy root（リポジトリの実 Pages ファイルは使わない）。"""
    site = tmp_path / "pages-site"
    (site / "history").mkdir(parents=True)
    (site / "index.html").write_text("<html>legacy root</html>\n", encoding="utf-8")
    (site / "history" / "example.html").write_text("<html>history</html>\n", encoding="utf-8")
    return site


def assemble(artifact_dir, site, *, jst_today=JST_TODAY):
    return pp.assemble_v2_publication(artifact_dir=artifact_dir,
                                      v2_destination=site / "v2",
                                      jst_today=jst_today,
                                      index_template=TEMPLATE)


def tree(directory):
    return sorted(entry.name for entry in directory.iterdir())


def replace_one(directory, *, drop, add, content="x"):
    (directory / drop).unlink()
    if add.endswith("/"):
        (directory / add.rstrip("/")).mkdir()
    else:
        (directory / add).write_text(content, encoding="utf-8")
    return directory


# ---------------------------------------------------------------- VALID INPUT (1-6)

def test_valid_four_file_set_is_accepted(tmp_path):
    validated = pp.validate_publication_artifacts(make_artifacts(tmp_path), jst_today=JST_TODAY)
    assert validated.session_date == SESSION
    assert validated.reference_session == REFERENCE
    assert validated.signal_available is True
    assert validated.markdown_bytes == len(MARKDOWN.encode("utf-8"))


def test_final_v2_tree_is_exactly_five_files(tmp_path):
    site = make_pages_site(tmp_path)
    assemble(make_artifacts(tmp_path), site)
    assert tree(site / "v2") == sorted([
        f"{SESSION}_morning_brief.json", f"{SESSION}_morning_brief.md",
        "index.html", LATEST_JSON, LATEST_MARKDOWN])
    assert not any(entry.is_dir() for entry in (site / "v2").iterdir())


def test_latest_and_dated_markdown_are_byte_identical(tmp_path):
    site = make_pages_site(tmp_path)
    assemble(make_artifacts(tmp_path), site)
    v2 = site / "v2"
    assert (v2 / LATEST_MARKDOWN).read_bytes() == (v2 / f"{SESSION}_morning_brief.md").read_bytes()


def test_latest_and_dated_json_are_byte_identical(tmp_path):
    site = make_pages_site(tmp_path)
    assemble(make_artifacts(tmp_path), site)
    v2 = site / "v2"
    assert (v2 / LATEST_JSON).read_bytes() == (v2 / f"{SESSION}_morning_brief.json").read_bytes()


def test_static_index_is_copied_byte_identically(tmp_path):
    site = make_pages_site(tmp_path)
    assemble(make_artifacts(tmp_path), site)
    assert (site / "v2" / "index.html").read_bytes() == TEMPLATE.read_bytes()


def test_repeat_assembly_is_deterministic(tmp_path):
    site = make_pages_site(tmp_path)
    artifacts = make_artifacts(tmp_path)
    assemble(artifacts, site)
    first = {p.name: p.read_bytes() for p in (site / "v2").iterdir()}
    assemble(artifacts, site)
    second = {p.name: p.read_bytes() for p in (site / "v2").iterdir()}
    assert first == second
    assert tree(site.parent / "pages-site") == ["history", "index.html", "v2"]


# ---------------------------------------------------------------- INPUT SET (7-21)

def test_missing_directory_is_rejected(tmp_path):
    with pytest.raises(pp.PublicationRejected):
        pp.validate_publication_artifacts(tmp_path / "absent", jst_today=JST_TODAY)


def test_empty_directory_is_rejected(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(pp.PublicationRejected):
        pp.validate_publication_artifacts(empty, jst_today=JST_TODAY)


@pytest.mark.parametrize("missing", [
    LATEST_MARKDOWN, LATEST_JSON,
    f"{SESSION}_morning_brief.md", f"{SESSION}_morning_brief.json",
])
def test_missing_approved_artifact_is_rejected(tmp_path, missing):
    artifacts = make_artifacts(tmp_path)
    (artifacts / missing).unlink()
    with pytest.raises(pp.PublicationRejected):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_fifth_file_is_rejected(tmp_path):
    artifacts = make_artifacts(tmp_path)
    (artifacts / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(pp.PublicationRejected, match="exactly 4 entries"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


@pytest.mark.parametrize("intruder", [
    "nested/", ".hidden", "leftover.part", "report.html",
    "market.sqlite3", "evidence.jsonl", "store.db", "index.json",
])
def test_unapproved_entry_kind_is_rejected(tmp_path, intruder):
    artifacts = replace_one(make_artifacts(tmp_path), drop=LATEST_JSON, add=intruder)
    with pytest.raises(pp.PublicationRejected):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


# ---------------------------------------------------------------- SESSION (22-26)

def test_mismatched_dated_filenames_are_rejected(tmp_path):
    artifacts = make_artifacts(tmp_path)
    (artifacts / f"{SESSION}_morning_brief.json").rename(
        artifacts / "2026-09-14_morning_brief.json")
    with pytest.raises(pp.PublicationRejected, match="disagree on session date"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_json_session_date_mismatch_is_rejected(tmp_path):
    artifacts = make_artifacts(tmp_path, payload=build_payload(session="2026-09-14"))
    with pytest.raises(pp.PublicationRejected, match="does not match the dated filename"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_future_session_date_is_rejected(tmp_path):
    artifacts = make_artifacts(tmp_path)
    with pytest.raises(pp.PublicationRejected, match="later than the supplied JST today"):
        pp.validate_publication_artifacts(artifacts, jst_today="2026-09-14")


def test_older_session_date_is_accepted(tmp_path):
    """連休・祝日・producer 実行間隔により古い session は正常。古さでは拒否しない。"""
    old = "2026-09-10"
    artifacts = make_artifacts(tmp_path, dated_session=old,
                               payload=build_payload(session=old, reference="2026-09-09"))
    validated = pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)
    assert validated.session_date == old


def test_malformed_session_date_is_rejected(tmp_path):
    bad = "2026-02-30"
    artifacts = make_artifacts(tmp_path, dated_session=bad, payload=build_payload(session=bad))
    with pytest.raises(pp.PublicationRejected, match="not a valid date"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_reference_session_after_session_date_is_rejected(tmp_path):
    artifacts = make_artifacts(tmp_path, payload=build_payload(reference="2026-09-16"))
    with pytest.raises(pp.PublicationRejected, match="later than session_date"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


# ---------------------------------------------------------------- PUBLIC JSON (27-36)

def test_malformed_json_is_rejected(tmp_path):
    artifacts = make_artifacts(tmp_path, json_text="{not json\n")
    with pytest.raises(pp.PublicationRejected, match="does not parse"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_invalid_utf8_json_is_rejected(tmp_path):
    """不正な UTF-8 も fail closed で拒否する（UnicodeDecodeError を外へ漏らさない）。"""
    artifacts = make_artifacts(tmp_path)
    for name in (LATEST_JSON, f"{SESSION}_morning_brief.json"):
        (artifacts / name).write_bytes(b"\xff\xfe{invalid}")
    with pytest.raises(pp.PublicationRejected, match="does not parse"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_top_level_key_drift_is_rejected(tmp_path):
    payload = build_payload()
    payload["extra_field"] = "x"
    artifacts = make_artifacts(tmp_path, payload=payload)
    with pytest.raises(pp.PublicationRejected, match="public key set drifted"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_missing_top_level_key_is_rejected(tmp_path):
    payload = build_payload()
    del payload["brief_id"]
    artifacts = make_artifacts(tmp_path, payload=payload)
    with pytest.raises(pp.PublicationRejected, match="public key set drifted"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_signal_key_drift_is_rejected(tmp_path):
    payload = build_payload()
    payload["signal"]["confidence"] = "x"
    artifacts = make_artifacts(tmp_path, payload=payload)
    with pytest.raises(pp.PublicationRejected, match="public signal key set drifted"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_markdown_digest_mismatch_is_rejected(tmp_path):
    payload = build_payload()
    payload["markdown_sha256"] = "0" * 64
    artifacts = make_artifacts(tmp_path, payload=payload)
    with pytest.raises(pp.PublicationRejected, match="markdown_sha256 does not match"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_markdown_byte_count_mismatch_is_rejected(tmp_path):
    payload = build_payload()
    payload["markdown_bytes"] = payload["markdown_bytes"] + 1
    artifacts = make_artifacts(tmp_path, payload=payload)
    with pytest.raises(pp.PublicationRejected, match="markdown_bytes"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_available_with_unknown_label_is_rejected(tmp_path):
    artifacts = make_artifacts(tmp_path, payload=build_payload(label="強気"))
    with pytest.raises(pp.PublicationRejected, match="not an approved Market Signal label"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_available_with_unavailable_reason_is_rejected(tmp_path):
    artifacts = make_artifacts(tmp_path, payload=build_payload(reason="no_outlook"))
    with pytest.raises(pp.PublicationRejected, match="must not carry an unavailable reason"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_unavailable_with_label_is_rejected(tmp_path):
    artifacts = make_artifacts(
        tmp_path, payload=build_payload(available=False, label=APPROVED_LABEL,
                                        reason=PUBLIC_UNAVAILABLE_REASONS[0]))
    with pytest.raises(pp.PublicationRejected, match="must not carry a label"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_unavailable_with_unknown_reason_is_rejected(tmp_path):
    artifacts = make_artifacts(
        tmp_path, payload=build_payload(available=False, label="", reason="internal_free_text"))
    with pytest.raises(pp.PublicationRejected, match="not publishable"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


def test_unavailable_public_form_is_accepted(tmp_path):
    for reason in PUBLIC_UNAVAILABLE_REASONS:
        artifacts = make_artifacts(
            tmp_path, name=f"artifact_{reason}",
            payload=build_payload(available=False, label="", reason=reason))
        validated = pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)
        assert validated.signal_available is False


def test_forbidden_public_vocabulary_is_rejected(tmp_path):
    payload = build_payload()
    payload["brief_id"] = "brief_" + "d" * 18 + "JP_01"
    artifacts = make_artifacts(tmp_path, payload=payload)
    with pytest.raises(pp.PublicationRejected, match="internal vocabulary reached"):
        pp.validate_publication_artifacts(artifacts, jst_today=JST_TODAY)


# ---------------------------------------------------------------- ROOT SAFETY (37-43)

def test_legacy_root_index_is_untouched(tmp_path):
    site = make_pages_site(tmp_path)
    before = (site / "index.html").read_bytes()
    assemble(make_artifacts(tmp_path), site)
    assert (site / "index.html").read_bytes() == before


def test_legacy_history_tree_is_untouched(tmp_path):
    site = make_pages_site(tmp_path)
    before = (site / "history" / "example.html").read_bytes()
    assemble(make_artifacts(tmp_path), site)
    assert (site / "history" / "example.html").read_bytes() == before
    assert tree(site / "history") == ["example.html"]


def test_no_legacy_html_is_created(tmp_path):
    site = make_pages_site(tmp_path)
    assemble(make_artifacts(tmp_path), site)
    assert not (site / "legacy.html").exists()
    assert not (site / "v2" / "legacy.html").exists()


def test_assembler_writes_only_the_v2_destination(tmp_path):
    site = make_pages_site(tmp_path)
    assemble(make_artifacts(tmp_path), site)
    assert tree(site) == ["history", "index.html", "v2"], "一時ディレクトリを残さない"


def test_destination_basename_must_be_v2(tmp_path):
    site = make_pages_site(tmp_path)
    for bad in ("", "history", "site"):
        with pytest.raises(pp.PublicationRejected, match="basename must be"):
            pp.assemble_v2_publication(artifact_dir=make_artifacts(tmp_path, name=f"a{bad}"),
                                       v2_destination=site / (bad or "index.html"),
                                       jst_today=JST_TODAY, index_template=TEMPLATE)
    assert (site / "index.html").read_text(encoding="utf-8") == "<html>legacy root</html>\n"


def test_failed_validation_writes_nothing(tmp_path):
    site = make_pages_site(tmp_path)
    artifacts = make_artifacts(tmp_path)
    (artifacts / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(pp.PublicationRejected):
        assemble(artifacts, site)
    assert tree(site) == ["history", "index.html"]
    assert not (site / "v2").exists()


def test_failed_validation_leaves_previous_good_v2_intact(tmp_path):
    site = make_pages_site(tmp_path)
    assemble(make_artifacts(tmp_path), site)
    good = {p.name: p.read_bytes() for p in (site / "v2").iterdir()}
    broken = make_artifacts(tmp_path, name="broken", json_text="{not json\n")
    with pytest.raises(pp.PublicationRejected):
        assemble(broken, site)
    assert {p.name: p.read_bytes() for p in (site / "v2").iterdir()} == good
    assert tree(site) == ["history", "index.html", "v2"]


def test_module_performs_no_wildcard_copy():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for wildcard in ("copytree", "glob(", "rglob(", "iglob", "shutil.copy(", "*.md", "*.json"):
        assert wildcard not in source, wildcard
    assert "shutil.copyfile" in source, "承認済みの論理名を 1 つずつ copy すること"


def test_missing_destination_parent_is_rejected(tmp_path):
    with pytest.raises(pp.PublicationRejected, match="parent does not exist"):
        pp.assemble_v2_publication(artifact_dir=make_artifacts(tmp_path),
                                   v2_destination=tmp_path / "absent-site" / "v2",
                                   jst_today=JST_TODAY, index_template=TEMPLATE)


def test_missing_index_template_is_rejected(tmp_path):
    site = make_pages_site(tmp_path)
    with pytest.raises(pp.PublicationRejected, match="template does not exist"):
        pp.assemble_v2_publication(artifact_dir=make_artifacts(tmp_path),
                                   v2_destination=site / "v2", jst_today=JST_TODAY,
                                   index_template=tmp_path / "absent.html")
    assert not (site / "v2").exists()


# ---------------------------------------------------------------- INDEX (44-49)

def test_index_template_contains_only_approved_links():
    import re
    text = TEMPLATE.read_text(encoding="utf-8")
    assert re.findall(r'href="([^"]+)"', text) == [LATEST_MARKDOWN, LATEST_JSON, "../"]
    assert "Morning Delivery v2" in text


def test_index_template_carries_no_report_content_or_ids():
    text = TEMPLATE.read_text(encoding="utf-8")
    for label in SIGNAL_LEVEL_JA.values():
        assert label not in text, label
    for prefix in ("brief_", "signal_", "delivery_", "compass_", "ctx_", "fact_"):
        assert prefix not in text, prefix


def test_index_template_embeds_no_date():
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}", TEMPLATE.read_text(encoding="utf-8"))


def test_index_template_has_no_script_or_external_resource():
    import re
    text = TEMPLATE.read_text(encoding="utf-8")
    for forbidden in ("<script", "src=", "stylesheet", "http://", "https://", "<style"):
        assert forbidden not in text.lower(), forbidden
    assert not re.search(r"\son[a-z]+=", text), "inline event handler を置かない"


def test_index_template_is_not_generated_dynamically():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "<html" not in source and "<body" not in source, "HTML を動的生成しない"
    for substitution in ("{{", "{%", ".format(", "Template("):
        assert substitution not in source, substitution


# ---------------------------------------------------------------- BOUNDARY (50-54)

def _imported_top_levels(path):
    tree_ = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree_):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.lstrip(".").split(".")[0]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]


def test_module_imports_no_legacy_or_governance_package():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for legacy in ("report", "analysis", "collectors", "data", "date"):
        assert f"src.{legacy}" not in source, legacy
    tops = set(_imported_top_levels(MODULE_PATH))
    forbidden = {"main", "notifiers", "scripts", "decision", "formal_review", "review",
                 "shadow_review", "corpus", "corpus_research", "replay", "evaluation"}
    assert not tops & forbidden, tops
    assert tops <= {"__future__", "argparse", "hashlib", "json", "os", "re", "shutil",
                    "tempfile", "dataclasses", "pathlib", "typing",
                    "delivery", "delivery_emit", "market_signal", "datetime"}, tops


def _executable_source(path):
    """docstring と comment を除いた**実行される内容**だけを返す。

    「〜しない」系の検査は散文ではなくコードに対して行う（module の docstring は
    「GitHub API も download も行わない」と明記しているため、素朴な文字列走査では
    その説明自体が誤検知になる）。
    """
    tree_ = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree_):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            del body[0]
    return ast.unparse(tree_)


def test_module_uses_no_network():
    code = _executable_source(MODULE_PATH).lower()
    for network in ("requests", "urllib", "socket", "http", "github", "download",
                    "subprocess", "boto", "paramiko"):
        assert network not in code, network


def test_module_creates_no_canonical_storage():
    source = MODULE_PATH.read_text(encoding="utf-8")
    for writer in ("open(", ".write_text(", ".write_bytes(", ".mkdir(",
                   "import sqlite3", "data_root"):
        assert writer not in source, writer


def test_frozen_p4_3a_contracts_are_reused_not_copied():
    """語彙そのもの（ラベル・公開理由・key 集合）を書き写さず import して使うこと。

    個々の key 名を dict の key として使うのは複製ではない。複製の禁止対象は
    **集合の定義**であり、それらは凍結 module から import されていなければならない。
    """
    source = MODULE_PATH.read_text(encoding="utf-8")
    for label in SIGNAL_LEVEL_JA.values():
        assert label not in source, f"承認済みラベルを書き写さない: {label}"
    for reason in PUBLIC_UNAVAILABLE_REASONS:
        assert f'"{reason}"' not in source, f"公開理由を書き写さない: {reason}"

    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    for symbol in ("PUBLIC_KEYS", "PUBLIC_SIGNAL_KEYS", "PUBLIC_UNAVAILABLE_REASONS",
                   "FORBIDDEN_PUBLIC_SUBSTRINGS", "SIGNAL_LEVEL_JA", "canonical_delivery",
                   "LATEST_MARKDOWN", "LATEST_JSON", "DELIVERY_DIRNAME"):
        assert symbol in imported, f"凍結シンボルを import して使うこと: {symbol}"

    assert len(SIGNAL_LEVEL_JA) == 5 and len(PUBLIC_KEYS) == 9
    assert PUBLIC_SIGNAL_KEYS == ("available", "label", "unavailable_reason")
    assert len(PUBLIC_UNAVAILABLE_REASONS) == 6


def test_import_boundary_contract_is_unchanged():
    text = IMPORT_BOUNDARY_TEST.read_text(encoding="utf-8")
    assert ('LEGACY_FORBIDDEN_PREFIXES = (\n'
            '    "src.analysis", "src.report", "src.collectors", "src.data", "src.date",\n'
            '    "notifiers", "main", "scripts",\n'
            ')') in text
    assert "pages_parallel" not in text, "境界テストへ例外を作らない"


# ---------------------------------------------------------------- isolated simulation

def test_isolated_pages_site_simulation(tmp_path):
    """temp な pages-site に対して組み立て、legacy 側の byte 不変を実測する。"""
    site = make_pages_site(tmp_path)
    before = {"index.html": (site / "index.html").read_bytes(),
              "history/example.html": (site / "history" / "example.html").read_bytes()}

    validated = assemble(make_artifacts(tmp_path), site)

    assert {"index.html": (site / "index.html").read_bytes(),
            "history/example.html": (site / "history" / "example.html").read_bytes()} == before
    assert tree(site / "v2") == list(validated.published_names)
    assert len(validated.published_names) == 5
    assert not (REPO_ROOT / "pages-site").exists(), "リポジトリ側に Pages tree を作らない"
