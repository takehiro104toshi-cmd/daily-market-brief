"""P12-A2 — 実行の要求 ・前提条件 ・source の manifest ・凍結の P11 の anchor ・network の拒否の test（合成の値 ・tmp の git repo）。"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.automation.canonical import domain_digest
from src.intelligence.automation.execution_request import AutomationExecutionRequest
from src.intelligence.automation.failure_codes import AutomationError
from src.intelligence.automation.frozen_anchors import (P11_FROZEN_ANCHOR, P11_FROZEN_BLOBS, git_blob_id,
                                                        p11_runtime_manifest)
from src.intelligence.automation.network_deny import NetworkDenied, NetworkPolicy, network_guard
from src.intelligence.automation.preconditions import (PRECONDITION_ORDER, PreconditionOutcome, PrivateRoots,
                                                       check_preconditions, credential_present, frozen_p11_drift)
from src.intelligence.automation.schedule_model import TOKYO
from src.intelligence.automation.source_manifests import SourceManifest, build_root_manifest
from tests.intelligence.phase11_runtime_registry import P11_A5, P11_STATIC_BLOB_IDS, PHASE11_RUNTIME

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULED_FOR = datetime(2026, 7, 1, 15, 0, tzinfo=TOKYO)
AS_OF = date(2026, 7, 1)
SCHEDULE_DIGEST = "5" * 64
POLICY = NetworkPolicy(allow_loopback=False)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def make_repo(root: Path) -> tuple:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return root, _git(root, "rev-parse", "HEAD").strip()


def request(anchor: str, **overrides) -> AutomationExecutionRequest:
    fields = dict(schedule_id="ops-daily", slot_id="slot-a", scheduled_for=SCHEDULED_FOR, as_of_date=AS_OF, session_date=AS_OF,
                  runtime_anchor=anchor, attempt=1, operator="scheduler", schedule_digest=SCHEDULE_DIGEST)
    fields.update(overrides)
    return AutomationExecutionRequest(**fields)


def roots_under(tmp: Path) -> PrivateRoots:
    (tmp / "p9").mkdir(exist_ok=True)
    (tmp / "p9" / "a.jsonl").write_bytes(b"{}\n")
    (tmp / "p10").mkdir(exist_ok=True)
    (tmp / "p10" / "b.jsonl").write_bytes(b"{}\n")
    return PrivateRoots(tmp / "p9", tmp / "p10", tmp / "p12")


# ================================================================ execution request


def test_request_is_explicit_canonical_and_recomputes_the_a1_run_identity() -> None:
    req = request("a" * 40)
    data = json.loads(req.to_json())
    assert set(data) == {"schema_version", "schedule_id", "slot_id", "scheduled_for", "as_of_date", "session_date",
                         "runtime_anchor", "attempt", "operator", "schedule_digest", "retry_of", "supersedes", "readiness_only",
                         "request_digest"}
    assert data["scheduled_for"] == "2026-07-01T06:00:00Z" and data["request_digest"] == req.request_digest
    assert AutomationExecutionRequest.from_dict(data) == req and req.to_bytes().endswith(b"\n")
    assert req.run_id == req.run.run_id == domain_digest("p12.automation_run.v1", {
        "schedule_id": "ops-daily", "slot_id": "slot-a", "scheduled_for": "2026-07-01T06:00:00Z", "runtime_anchor": "a" * 40,
        "attempt": 1})
    assert request("a" * 40, scheduled_for=datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)).run_id == req.run_id   # 同じ瞬間
    assert "started_at" not in data and "now" not in data and "clock" not in json.dumps(data)
    data["extra"] = 1
    with pytest.raises(AutomationError) as e:
        AutomationExecutionRequest.from_dict(data)
    assert e.value.detail == "REQUEST_UNKNOWN_FIELD"
    tampered = json.loads(req.to_json())
    tampered["attempt"] = 2
    with pytest.raises(AutomationError) as e:
        AutomationExecutionRequest.from_dict(tampered)
    assert e.value.detail == "REQUEST_DIGEST_MISMATCH"


def test_request_pit_fields_must_be_internally_consistent() -> None:
    for overrides, detail in ((dict(as_of_date=date(2026, 7, 2)), "AS_OF_DATE_MISMATCH"),
                              (dict(session_date=date(2026, 7, 2)), "SESSION_AFTER_AS_OF"),
                              (dict(scheduled_for=datetime(2026, 7, 1, 15, 0)), "SCHEMA_INVALID"),
                              (dict(scheduled_for=SCHEDULED_FOR.replace(microsecond=5)), "SUBSECOND_INSTANT"),
                              (dict(runtime_anchor="HEAD"), "RUNTIME_ANCHOR"),
                              (dict(attempt=0), "ATTEMPT_RANGE"),
                              (dict(operator="cron"), "OPERATOR"),
                              (dict(schedule_digest="x"), "SCHEDULE_DIGEST"),
                              (dict(retry_of="b" * 64), "RETRY_ATTEMPT"),
                              (dict(readiness_only="no"), "READINESS_ONLY")):
        with pytest.raises(AutomationError) as e:
            request("a" * 40, **overrides)
        assert e.value.code == "SCHEMA_INVALID" and (e.value.detail == detail or detail == "SCHEMA_INVALID"), detail
    utc_midnight = datetime(2026, 7, 1, 23, 0, tzinfo=timezone.utc)                         # Tokyo では翌日
    assert request("a" * 40, scheduled_for=utc_midnight, as_of_date=date(2026, 7, 2), session_date=date(2026, 7, 2)).as_of_date \
        == date(2026, 7, 2)
    with pytest.raises(AutomationError) as e:
        request("a" * 40, scheduled_for=utc_midnight)
    assert e.value.detail == "AS_OF_DATE_MISMATCH"
    retry = request("a" * 40, attempt=2, retry_of="b" * 64)
    assert retry.run.retry_of == "b" * 64 and retry.run_id == request("a" * 40, attempt=2).run_id   # 系譜は identity 外


# ================================================================ preconditions


def test_preconditions_pass_on_a_clean_repo_at_the_anchor_with_readable_roots(tmp_path: Path) -> None:
    repo, head = make_repo(tmp_path / "repo")
    outcome = check_preconditions(request(head), roots_under(tmp_path), repo_root=repo, runtime_root=REPO_ROOT, environment={},
                                  policy=POLICY)
    assert outcome.ok and outcome.failure_code is None and outcome.passed == PRECONDITION_ORDER
    assert outcome.to_dict() == {"passed": list(PRECONDITION_ORDER), "failure_code": None}
    (tmp_path / "p12").mkdir()                                                               # 既に在る root も通る
    assert check_preconditions(request(head), roots_under(tmp_path), repo_root=repo, runtime_root=REPO_ROOT, environment={},
                               policy=POLICY).ok


def test_preconditions_fail_closed_in_order_with_safe_codes_only(tmp_path: Path) -> None:
    repo, head = make_repo(tmp_path / "repo")
    roots = roots_under(tmp_path)

    def run(req=None, **kw) -> PreconditionOutcome:
        args = dict(repo_root=repo, runtime_root=REPO_ROOT, environment={}, policy=POLICY)
        args.update(kw)
        return check_preconditions(req or request(head), kw.pop("roots", roots) if "roots" in kw else roots, **{
            k: v for k, v in args.items() if k != "roots"})

    wrong = run(request("f" * 40))
    assert (wrong.failure_code, wrong.passed) == ("REPO_HEAD_MISMATCH", PRECONDITION_ORDER[:3])
    assert run(environment={"JQUANTS_API_KEY": "SENTINEL-CREDENTIAL"}).failure_code == "CREDENTIAL_PRESENT"
    assert run(environment={"JQUANTS_REFRESH_TOKEN": "x"}).failure_code == "CREDENTIAL_PRESENT"
    assert run(environment={"JQUANTS_LATER_RESERVED": "x"}).failure_code == "CREDENTIAL_PRESENT"          # 接頭辞も
    assert run(environment={"JQUANTS_API_KEY": "", "PATH": "/usr/bin"}).ok                                   # 空は不在
    assert run(policy="allow-all").failure_code == "SCHEMA_INVALID:NETWORK_POLICY"
    (repo / "dirty.txt").write_text("x", encoding="utf-8")                                                   # 未追跡でも汚れ
    assert run().failure_code == "REPO_NOT_CLEAN"
    (repo / "dirty.txt").unlink()
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    assert run().failure_code == "REPO_NOT_CLEAN"
    _git(repo, "checkout", "--", "tracked.txt")
    assert run().ok
    drifted = tmp_path / "runtime"
    for relative in P11_FROZEN_BLOBS:
        target = drifted / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    assert run(runtime_root=drifted).ok                                                                      # 複製は一致
    (drifted / "src/intelligence/personal_ui/ui_model.py").write_bytes(b"# drift\n")
    assert run(runtime_root=drifted).failure_code == "FROZEN_DRIFT:P11"
    assert frozen_p11_drift(drifted) == ("src/intelligence/personal_ui/ui_model.py",)
    (drifted / "src/intelligence/personal_ui/static/sw.js").unlink()
    assert set(frozen_p11_drift(drifted)) == {"src/intelligence/personal_ui/ui_model.py", "src/intelligence/personal_ui/static/sw.js"}
    assert run(roots=PrivateRoots(tmp_path / "absent", roots.p10_root, roots.p12_root)).failure_code == "ROOT_MISSING:P9"
    assert run(roots=PrivateRoots(roots.p9_root, tmp_path / "absent", roots.p12_root)).failure_code == "ROOT_MISSING:P10"
    assert run(roots=PrivateRoots(roots.p9_root, roots.p10_root, tmp_path / "no" / "parent" / "p12")).failure_code == "ROOT_MISSING:P12"
    assert run(roots=PrivateRoots(roots.p9_root, roots.p10_root, "")).failure_code == "ROOT_MISSING:P12"
    assert run(roots=("a", "b", "c")).failure_code == "SCHEMA_INVALID:ROOTS_TYPE"
    assert run(repo_root=tmp_path / "not-a-repo").failure_code == "REPO_HEAD_MISMATCH:GIT_UNAVAILABLE"
    for outcome in (wrong, run(repo_root=tmp_path / "not-a-repo")):
        text = json.dumps(outcome.to_dict())
        assert str(tmp_path) not in text and "fatal" not in text and "SENTINEL" not in text


def test_credential_presence_never_reads_or_returns_the_value() -> None:
    environment = {"JQUANTS_API_KEY": "SENTINEL-CREDENTIAL-VALUE"}
    assert credential_present(environment) is True and credential_present({}) is False
    assert credential_present({"OTHER_API_KEY": "x"}) is False
    assert repr(PrivateRoots("/x", "/y", "/z")) == "PrivateRoots(<private>)" and "/x" not in str(PrivateRoots("/x", "/y", "/z"))


# ================================================================ source manifests ・frozen anchors


def test_root_manifests_are_deterministic_order_independent_path_free_and_mutation_sensitive(tmp_path: Path) -> None:
    root = tmp_path / "p9"
    (root / "sub").mkdir(parents=True)
    (root / "b.jsonl").write_bytes(b"BBB\n")
    (root / "a.jsonl").write_bytes(b"AAA\n")
    (root / "sub" / "c.jsonl").write_bytes(b"CCC\n")
    first = build_root_manifest(root, "P9")
    assert isinstance(first, SourceManifest) and first.file_count == 3 and first.byte_count == 12
    assert [n for n, _, _ in first.files] == ["a.jsonl", "b.jsonl", "sub/c.jsonl"]
    copy = tmp_path / "copy"
    shutil.copytree(root, copy)
    (copy / "sub" / "c.jsonl").write_bytes(b"CCC\n")                                        # 書く順 ・mtime は無関係
    second = build_root_manifest(copy, "P9")
    assert second == first and second.content_digest == first.content_digest and second.to_private_json() == first.to_private_json()
    assert build_root_manifest(root, "P10").content_digest != first.content_digest        # source_id は domain の一部
    (copy / "a.jsonl").write_bytes(b"AAB\n")
    mutated = build_root_manifest(copy, "P9")
    assert mutated.content_digest != first.content_digest and mutated.byte_count == first.byte_count
    safe = first.to_safe_dict()
    assert set(safe) == {"schema_version", "source_id", "file_count", "byte_count", "content_digest"}
    for text in (json.dumps(safe), first.to_private_json()):
        assert str(tmp_path) not in text and "/" not in text.replace("sub/c.jsonl", "") and "AAA" not in text
    assert "sub/c.jsonl" in first.to_private_json() and "sub/c.jsonl" not in json.dumps(safe)
    with pytest.raises(AutomationError) as e:
        build_root_manifest(tmp_path / "absent", "P9")
    assert e.value.public_code == "ROOT_MISSING:P9"
    with pytest.raises(AutomationError):
        build_root_manifest(root, "P8")
    (root / "link.jsonl").symlink_to(root / "a.jsonl")
    with pytest.raises(AutomationError) as e:
        build_root_manifest(root, "P9")
    assert e.value.public_code == "ROOT_MISSING:P9_UNREADABLE"


def test_frozen_p11_anchor_and_blobs_match_the_registry_and_the_worktree() -> None:
    assert P11_FROZEN_ANCHOR == P11_A5 == "43c0b856d41efed397de213a1a06178c5e97ab10"
    assert set(P11_FROZEN_BLOBS) == set(PHASE11_RUNTIME) and len(P11_FROZEN_BLOBS) == 12
    for asset, blob in P11_STATIC_BLOB_IDS.items():
        assert P11_FROZEN_BLOBS[asset] == blob
    listed = dict(line.split()[2:4][::-1] for line in _git(REPO_ROOT, "ls-tree", "-r", P11_FROZEN_ANCHOR, "--",
                                                           "src/intelligence/personal_ui").splitlines())
    assert listed == dict(P11_FROZEN_BLOBS)
    assert frozen_p11_drift(REPO_ROOT) == ()
    assert git_blob_id(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    manifest = p11_runtime_manifest()
    assert manifest["runtime_anchor"] == P11_FROZEN_ANCHOR and manifest["file_count"] == 12
    assert manifest["content_digest"] == domain_digest("p12.p11_runtime_manifest.v1", {k: v for k, v in manifest.items()
                                                                                        if k != "content_digest"})


# ================================================================ network deny


def test_network_guard_denies_external_connect_dns_and_outbound_clients_but_can_allow_loopback() -> None:
    import http.client
    import urllib.request
    with network_guard(NetworkPolicy(allow_loopback=False)) as guard:
        for attempt in (lambda: socket.create_connection(("203.0.113.1", 80), timeout=1),
                        lambda: socket.getaddrinfo("example.invalid", 443),
                        lambda: socket.socket().connect(("203.0.113.1", 80)),
                        lambda: socket.socket().connect_ex(("203.0.113.1", 80)),
                        lambda: http.client.HTTPConnection("203.0.113.1", 80, timeout=1).request("GET", "/"),
                        lambda: urllib.request.urlopen("http://203.0.113.1/", timeout=1),
                        lambda: socket.getaddrinfo("127.0.0.1", 80)):                       # loopback も policy が許さねば拒む
            with pytest.raises(NetworkDenied) as e:
                attempt()
            assert e.value.public_code == "INTERRUPTED:NETWORK_DENIED" and "203." not in str(e.value)
        assert guard.denied == 7 and guard.to_dict() == {"allow_loopback": False, "denied": 7}
    with network_guard(NetworkPolicy(allow_loopback=True)) as guard:
        assert socket.getaddrinfo("127.0.0.1", 80)[0][4][0] == "127.0.0.1" and socket.getaddrinfo("localhost", 80)
        with pytest.raises(NetworkDenied):
            socket.getaddrinfo("203.0.113.1", 80)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname(), timeout=2)                 # loopback の connect は通る
        client.close()
        listener.close()
        assert guard.denied == 1
    assert socket.getaddrinfo("127.0.0.1", 80) and "connect" not in vars(socket.socket)       # 元に戻る
    with pytest.raises(AutomationError):
        network_guard("policy")
