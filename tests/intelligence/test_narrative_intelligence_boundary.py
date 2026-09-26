"""P7-A1 — Phase 7 Narrative Intelligence の境界 guard（test matrix AP〜AS）と、Phase 6 の語彙の複製の一致。

- AP: import 境界（package の module・直接の import・runtime closure）
- AQ: I/O・時計・乱数・network・永続化・LLM・公開経路の不在
- AR: 上流（Phase 6・P4・legacy・scripts）は Narrative を import しない
- AS: production bundle の閉包から外れている／Phase 6 と A0 は凍結のまま／Phase 6 の test への登録は宣言どおりだけ

契約: `docs/databank/PHASE7_NARRATIVE_SEMANTICS_MODEL_CONTRACT.md`。
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from src.intelligence.narrative_intelligence import synthesis_model as m
from src.intelligence.theme_intelligence import change as b1_change
from src.intelligence.theme_intelligence import lifecycle_model, relation_model
from src.intelligence.theme_intelligence import model as b1_model
from src.intelligence.themes import model as foundation
from tests.intelligence.phase7_runtime_registry import (ADDITION_STATUSES, PHASE6_TEST_REGISTRATION,
                                                        PHASE7_EXCLUDED_PATHSPECS, PHASE7_PACKAGE, PHASE7_RUNTIME,
                                                        is_phase7_addition, only_phase7_registration,
                                                        registration_diff)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules
from tests.intelligence.test_theme_model import observation

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE7_PACKAGE
MODULES = ("__init__", "synthesis_model")
PHASE6_COMPLETION = "5ef313a6a9477f05b4e46756fb8b79c0f0c3d685"
P7_A0 = "2fe7d0f03c3c8ab2e566508079b788f9e69fcb71"
A0_DOC = "docs/databank/PHASE7_NARRATIVE_ARCHITECTURE_AUDIT.md"
A1_DOC = "docs/databank/PHASE7_NARRATIVE_SEMANTICS_MODEL_CONTRACT.md"
SURFACE = ("src", "knowledge", "config.yaml", ".github", "scripts", "docs/pages", "docs/v2", "data", "main.py",
           "requirements.txt", "pyproject.toml")
PHASE7_TESTS = ("tests/intelligence/phase7_runtime_registry.py", "tests/intelligence/test_narrative_synthesis_model.py",
                "tests/intelligence/test_narrative_intelligence_boundary.py")
ALLOWED_IMPORTS = {"__future__", "json", "re", "dataclasses", "datetime", "enum", "typing", "..core.ids",
                   "..core.time"}
ALLOWED_CLOSURE = {"src", "src.intelligence", "src.intelligence.core", "src.intelligence.core.ids",
                   "src.intelligence.core.time", "src.intelligence.narrative_intelligence",
                   "src.intelligence.narrative_intelligence.synthesis_model"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _sources():
    return [(path.stem, path) for path in sorted(PACKAGE_DIR.glob("*.py"))]


# ================================================================ AP import 境界

def test_ap_the_package_holds_only_the_registered_modules() -> None:
    assert tuple(sorted(stem for stem, _ in _sources())) == MODULES
    assert tuple(f"{PHASE7_PACKAGE}/{name}.py" for name in MODULES) == PHASE7_RUNTIME
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {f"{n}.py" for n in MODULES}


@pytest.mark.parametrize("name,path", _sources())
def test_ap_modules_import_only_core_and_the_standard_library(name, path) -> None:
    assert imported_modules(path) <= ALLOWED_IMPORTS, imported_modules(path) - ALLOWED_IMPORTS


def test_ap_the_runtime_closure_is_core_and_this_package_only() -> None:
    code = ("import sys\nimport src.intelligence.narrative_intelligence.synthesis_model\n"
            "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('src'))))\n")
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                          env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    assert set(proc.stdout.split()) == ALLOWED_CLOSURE


FORBIDDEN_MODULE_TOKENS = ("themes", "theme_intelligence", "compass", "reports", "facts", "context", "internals",
                           "predictions", "evaluation", "calibration", "corpus", "formal_review", "decision", "thesis",
                           "screening", "personalization", "replay", "pipeline", "enrichment", "contracts", "sources",
                           "ingestion", "jquants", "market", "databank", "analysis", "report", "notifier", "delivery",
                           "anthropic", "openai", "requests", "httpx", "urllib", "socket", "sqlite3", "subprocess")


@pytest.mark.parametrize("name,path", _sources())
def test_ap_no_phase6_p4_p5_legacy_provider_or_network_import(name, path) -> None:
    for module in imported_modules(path):
        assert not any(token in module.split(".") for token in FORBIDDEN_MODULE_TOKENS), module


def test_ap_the_p4_narrative_names_are_not_reused() -> None:
    names = set(dir(m))
    assert not names & {"NarrativePlan", "NarrativeGenerator", "DeterministicNarrativeGenerator",
                        "FakeNarrativeGenerator", "LLMNarrativeGenerator"}


# ================================================================ AQ I/O・時計・乱数・network・永続化なし

FORBIDDEN_NAMES = {"open", "print", "input", "eval", "exec", "compile", "__import__", "getattr", "setattr", "globals",
                   "Path", "os", "sys", "subprocess", "socket", "urllib", "requests", "sqlite3", "pickle", "shelve",
                   "random", "secrets", "uuid", "time", "new_id", "new_ulid", "environ", "getenv"}
FORBIDDEN_ATTRIBUTES = {"now", "utcnow", "today", "time", "write", "write_text", "write_bytes", "read_text",
                        "read_bytes", "mkdir", "unlink", "touch", "rename", "rmdir", "remove", "makedirs", "environ",
                        "getenv", "urlopen", "connect", "request", "fsync", "flush"}


@pytest.mark.parametrize("name,path", _sources())
def test_aq_no_io_clock_randomness_network_or_dynamic_code(name, path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in FORBIDDEN_NAMES, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in FORBIDDEN_ATTRIBUTES, (name, node.attr)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "://" not in node.value and "\\\\" not in node.value, (name, node.value)


@pytest.mark.parametrize("name,path", _sources())
def test_aq_nothing_persists_journals_or_publishes(name, path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {node.name.lower() for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for word in ("save", "persist", "store", "journal", "append", "write", "publish", "render", "notify", "send",
                 "assemble", "engine", "generate", "provider", "llm", "prompt"):
        assert not any(word in item for item in defined), (name, word)
    source = executable_source(path)
    for token in ("data_root", "jsonl", ".github", "docs/pages", "docs/v2", "Authorization", "Bearer"):
        assert token not in source, (name, token)


def test_aq_the_only_credential_like_strings_are_rejection_vocabulary() -> None:
    tree = ast.parse((PACKAGE_DIR / "synthesis_model.py").read_text(encoding="utf-8"))
    constants = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    credential_like = {c for c in constants if c in ("api_key", "token", "secret")}
    assert credential_like <= set(m.PROHIBITED_FIELDS)


# ================================================================ AR 上流は Narrative を import しない

def test_ar_no_upstream_module_imports_narrative_intelligence() -> None:
    offenders = []
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")),
                 *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if not path.exists() or PACKAGE_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "narrative_intelligence" in text or "synthesis_model" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_ar_phase6_and_p4_packages_reference_no_phase7_name() -> None:
    for package in ("themes", "theme_intelligence", "compass", "reports", "facts", "context", "internals",
                    "predictions"):
        for path in sorted((REPO_ROOT / "src" / "intelligence" / package).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            assert "NarrativeSynthesis" not in text and "NarrativeClaim" not in text, path


# ================================================================ AS bundle・凍結・登録

def test_as_excluded_from_the_production_bundle_closure() -> None:
    closure = runtime_closure()
    assert closure, "runtime closure could not be computed"
    assert not any("narrative_intelligence" in module for module in closure)


def test_as_since_the_phase6_completion_only_the_registered_runtime_was_added() -> None:
    changes = {tuple(line.split("\t")) for line in _git("diff", "--cached", "--name-status", PHASE6_COMPLETION, "--",
                                                        *SURFACE).splitlines()}
    assert changes == {("A", path) for path in PHASE7_RUNTIME}                            # commit ／ index の差
    pending = [line for line in _git("status", "--porcelain", "--", *(p for p in SURFACE if p != "data")).splitlines()
               if not is_phase7_addition(line[:2].strip(), line[3:])]
    assert pending == []                                                                  # 作業木の未登録の変更なし
    assert _git("diff", "--name-status", PHASE6_COMPLETION, "--", "knowledge") == ""        # DNA・語彙の knowledge 不変
    for anchor in (PHASE6_COMPLETION, P7_A0):
        assert subprocess.run(["git", "merge-base", "--is-ancestor", anchor, "HEAD"], cwd=REPO_ROOT).returncode == 0


def test_as_phase6_documents_and_the_a0_audit_are_frozen() -> None:
    changes = {tuple(line.split("\t")) for line in _git("diff", "--name-status", P7_A0, "--",
                                                        "docs").splitlines()}
    assert changes <= {("A", A1_DOC)}
    assert _git("show", f"{P7_A0}:{A0_DOC}") == (REPO_ROOT / A0_DOC).read_text(encoding="utf-8")


def test_as_phase6_tests_changed_only_by_the_declared_registration() -> None:
    changed = {tuple(line.split("\t")) for line in _git("diff", "--name-status", PHASE6_COMPLETION, "--",
                                                        "tests").splitlines()}
    assert changed <= {("M", path) for path in PHASE6_TEST_REGISTRATION} | {("A", path) for path in PHASE7_TESTS}
    for path, (removed, added) in PHASE6_TEST_REGISTRATION.items():
        anchored = _git("show", f"{PHASE6_COMPLETION}:{path}")
        got_removed, got_added = registration_diff(anchored, (REPO_ROOT / path).read_text(encoding="utf-8"))
        assert sorted(got_removed) == sorted(removed) and sorted(got_added) == sorted(added), path


def test_as_the_registration_check_rejects_any_other_change() -> None:
    for path in PHASE6_TEST_REGISTRATION:
        anchored = _git("show", f"{PHASE6_COMPLETION}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase7_registration(path, anchored, current)
        assert not only_phase7_registration(path, anchored, current + "assert True\n")        # 未登録の追加
        assert not only_phase7_registration(path, anchored, anchored)                           # 登録の欠落
    unregistered = "tests/intelligence/theme_freeze_pins.py"
    text = (REPO_ROOT / unregistered).read_text(encoding="utf-8")
    assert only_phase7_registration(unregistered, text, text)
    assert not only_phase7_registration(unregistered, text, text.replace("ADDITION_STATUSES = (\"A\", \"??\")",
                                                                         "ADDITION_STATUSES = (\"A\", \"??\", \"M\")"))


def test_as_the_registry_exempts_only_additions_of_registered_files() -> None:
    assert ADDITION_STATUSES == ("A", "??")
    for path in PHASE7_RUNTIME:
        assert is_phase7_addition("A", path) and is_phase7_addition("??", path)
        for status in ("M", "D", "R", "R100", "C", "T", "U"):
            assert not is_phase7_addition(status, path), status
    for path in (f"{PHASE7_PACKAGE}/other.py", f"{PHASE7_PACKAGE}/sub/synthesis_model.py", PHASE7_PACKAGE,
                 f"{PHASE7_PACKAGE}/", "src/intelligence/theme_intelligence/synthesis_model.py",
                 "src/intelligence/themes/__init__.py", "knowledge/theme_intelligence/x.yaml"):
        assert not is_phase7_addition("A", path), path
    assert PHASE7_EXCLUDED_PATHSPECS == tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME)
    assert not any(p.startswith(("src/intelligence/themes", "src/intelligence/theme_intelligence", "knowledge"))
                   for p in PHASE7_RUNTIME)


# ================================================================ Phase 6 の語彙の複製（runtime は Phase 6 を import しない）

@pytest.mark.parametrize("mirror,upstream", [
    (m.GovernancePosition, lifecycle_model.GovernanceLifecycleState), (m.MechanismCertainty, foundation.MechanismCertainty),
    (m.ComponentType, foundation.ComponentType), (m.EvidenceKind, foundation.EvidenceKind),
    (m.EvidenceRole, foundation.EvidenceRole), (m.ProvenanceClass, foundation.ProvenanceClass),
    (m.EvidenceTimeQuality, foundation.EvidenceTimeQuality), (m.RelationType, relation_model.RelationType),
    (m.AssertionClass, relation_model.AssertionClass), (m.ChangeKind, b1_model.ChangeKind)])
def test_mirrored_vocabularies_equal_the_phase6_vocabularies(mirror, upstream) -> None:
    assert [e.value for e in mirror] == [e.value for e in upstream]


def test_mirrored_formats_equal_the_phase6_formats() -> None:
    assert m.CHANGE_FACETS == b1_model.FACET_ORDER
    assert {k.value: v for k, v in m.REF_ID_PREFIX_BY_KIND.items()} == {
        k.value: v for k, v in foundation.REF_ID_PREFIX_BY_KIND.items()}
    assert m._KEY_RE.pattern == foundation._KEY_RE.pattern
    assert m._ROOT_ID_RE.pattern == foundation._ROOT_ID_RE.pattern
    assert m._RELATION_ID_RE.pattern == relation_model._ID_RE[relation_model.ASSERTION_ID_PREFIX].pattern
    assert m._EVIDENCE_REF_RE.pattern.endswith("{0,%d}$" % (foundation.MAX_REF_LEN - 1))
    assert m.REVIEWED_POSITIONS == (m.GovernancePosition.ACCEPTED,)


def test_real_phase6_values_fit_the_narrative_refs_without_any_runtime_link() -> None:
    """Phase 6 の test fixture が作る reviewed observation の値を、そのまま Narrative の ref に写せる（写すのは test 側）。"""
    theme = observation(certainty_class=foundation.MechanismCertainty.HYPOTHESIZED_MECHANISM)
    root = m.ThemeObservationRef(root_id=theme.root_id, observation_id=theme.observation_id,
                                 governance_position="ACCEPTED", mechanism_certainty=theme.certainty_class.value)
    mech = theme.mechanism
    components = [m.MechanismComponentRef(root_id=theme.root_id, observation_id=theme.observation_id,
                                          component_type=c.component_type.value, component_key=c.component_key)
                  for c in (*mech.drivers, *mech.channels, *mech.domains, *mech.consequences)]
    conditions = [m.InvalidationConditionRef(root_id=theme.root_id, observation_id=theme.observation_id,
                                             condition_key=c.condition_key) for c in theme.invalidation_conditions]
    attachments = [m.EvidenceAttachmentRef(root_id=theme.root_id, observation_id=theme.observation_id, ref_id=a.ref_id,
                                           evidence_kind=a.evidence_kind.value, consequence_key=a.consequence_ref,
                                           role=a.role.value, role_provenance=a.role_provenance.value,
                                           attached_at=a.attached_at,
                                           invalidation_condition_key=a.invalidation_condition_ref)
                   for a in theme.attachments]
    assert [ref.attachment_key for ref in attachments] == [a.attachment_key for a in theme.attachments]
    items = [m.EvidenceItemRef(ref_id=a.ref_id, evidence_kind=a.evidence_kind.value, evidence_time=a.evidence_time,
                               time_quality=a.evidence_time_quality.value) for a in theme.attachments]
    claim = lambda klass, kind, predicate, *refs, code=None: m.NarrativeClaim(  # noqa: E731
        epistemic_class=klass, claim_kind=kind, predicate=predicate, refs=refs, uncertainty_code=code)
    claims = [claim("REVIEWED_INTERPRETATION", "STATE", "THEME_REVIEWED_STATE", root),
              claim("UNCERTAINTY", "MECHANISM", "IS_UNCERTAIN", root, code="MECHANISM_HYPOTHESIZED")]
    claims += [claim("REVIEWED_INTERPRETATION", "MECHANISM", "RECORDS_MECHANISM_COMPONENT", c) for c in components]
    claims += [claim("REVIEWED_INTERPRETATION", "INVALIDATION", "RECORDS_INVALIDATION_CONDITION", c) for c in conditions]
    claims += [claim("REVIEWED_INTERPRETATION", "EVIDENCE", "EVIDENCE_ATTACHED", a) for a in attachments]
    claims += [claim("OBSERVED_FACT", "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", i) for i in items]
    cutoff = max(theme.recorded_at, *(a.attached_at for a in theme.attachments), *(i.evidence_time for i in items))
    synthesis = m.NarrativeSynthesis(kind="THEME_STATE", subject_root_ids=(theme.root_id,), cutoff=cutoff,
                                     knowledge_pins=(("theme_mechanism_vocabulary", "0.1.0"),),
                                     input_digest="narin_" + "0" * 24, claims=tuple(claims))
    assert m.NarrativeSynthesis.from_json(synthesis.to_canonical_json()) == synthesis
    for field_name in b1_change.SEMANTIC_FIELDS:                                     # B1 の subject_id の形も受け取れる
        m.ThemeChangeRef(root_id=theme.root_id, from_cutoff=cutoff.replace(year=cutoff.year - 1), to_cutoff=cutoff,
                         change_kind="SEMANTIC_FIELD_CHANGED", facet="observation", subject_id=field_name)
    for field_value in foundation.MetadataField:
        m.ThemeChangeRef(root_id=theme.root_id, from_cutoff=cutoff.replace(year=cutoff.year - 1), to_cutoff=cutoff,
                         change_kind="METADATA_CHANGED", facet=f"metadata:{field_value.value}", subject_id="thmeta_x")
