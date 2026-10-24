"""P12-A2 — 凍結の P11 の loopback server の一時的な readiness の検証（持続する lifecycle は A3。browser は無い）。

- `verify_server_readiness(roots, request, expected_model_bytes)`: `LocalServer.start(p10, p9, port=0)`（loopback だけ）→ thread で
  serve → `/health` ・`/version` ・static の shell（`/app/index.html` ＝ 凍結の blob）・明示の `/api/view`（要求の PIT）を loopback の
  `http.client` で探る → 応答の byte を P11 の定数 ・A1 ／ snapshot の byte と比べる → `shutdown`（finally）。
- 失敗は `STEP_FAILED:<DETAIL>`（port ・path ・応答の本文は出さない）。報告（`ReadinessReport`）は code と一致の真偽だけ。
"""
from __future__ import annotations

import hashlib
import http.client
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from ..personal_ui.local_server import LOOPBACK_BIND, STATUS_BYTES, VERSION_BYTES, LocalServer, ServerStartupError
from .execution_request import AutomationExecutionRequest
from .failure_codes import AutomationError
from .frozen_anchors import P11_FROZEN_BLOBS, P11_PACKAGE_RELATIVE, git_blob_id
from .preconditions import PrivateRoots

READINESS_SCHEMA_VERSION = "p12_server_readiness:0.1.0"
PROBE_TIMEOUT_SECONDS = 10
STATIC_SHELL_ROUTE = "/app/index.html"
STATIC_SHELL_BLOB = P11_FROZEN_BLOBS[f"{P11_PACKAGE_RELATIVE}/static/index.html"]
PROBES: Tuple[str, ...] = ("HEALTH", "VERSION", "STATIC_SHELL", "API_VIEW")


@dataclass(frozen=True)
class ReadinessReport:
    probes_ok: Tuple[str, ...]
    api_model_digest: Optional[str]
    api_matches_snapshot: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": READINESS_SCHEMA_VERSION, "bind": LOOPBACK_BIND, "probes_ok": list(self.probes_ok),
                "api_model_digest": self.api_model_digest, "api_matches_snapshot": self.api_matches_snapshot}


def _probe(port: int, method: str, route: str, body: Optional[bytes] = None) -> Tuple[int, bytes]:
    connection = http.client.HTTPConnection(LOOPBACK_BIND, port, timeout=PROBE_TIMEOUT_SECONDS)
    try:
        headers = {"Host": f"{LOOPBACK_BIND}:{port}"}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        connection.request(method, route, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def verify_server_readiness(roots: PrivateRoots, request: AutomationExecutionRequest,
                            expected_model_bytes: bytes) -> ReadinessReport:
    if not isinstance(roots, PrivateRoots) or not isinstance(request, AutomationExecutionRequest):
        raise AutomationError("SCHEMA_INVALID", "READINESS_INPUT")
    try:
        server = LocalServer.start(roots.p10_root, roots.p9_root, bind=LOOPBACK_BIND, port=0)
    except ServerStartupError as exc:
        raise AutomationError("STEP_FAILED", f"SERVER_{exc.code}") from None
    probes_ok = []
    api_digest = None
    try:
        server.start_in_thread()
        port = server.port
        if not server.url.startswith(f"http://{LOOPBACK_BIND}:"):
            raise AutomationError("STEP_FAILED", "SERVER_NOT_LOOPBACK")
        try:
            status, body = _probe(port, "GET", "/health")
            if status != 200 or body != STATUS_BYTES:
                raise AutomationError("STEP_FAILED", "HEALTH_MISMATCH")
            probes_ok.append("HEALTH")
            status, body = _probe(port, "GET", "/version")
            if status != 200 or body != VERSION_BYTES:
                raise AutomationError("STEP_FAILED", "VERSION_MISMATCH")
            probes_ok.append("VERSION")
            status, body = _probe(port, "GET", STATIC_SHELL_ROUTE)
            if status != 200 or git_blob_id(body) != STATIC_SHELL_BLOB:
                raise AutomationError("STEP_FAILED", "STATIC_SHELL_MISMATCH")
            probes_ok.append("STATIC_SHELL")
            view = (b'{"at":"' + request.scheduled_for.isoformat().encode("ascii") + b'","as_of_date":"'
                    + request.as_of_date.isoformat().encode("ascii") + b'"}')
            status, body = _probe(port, "POST", "/api/view", view)
            if status != 200:
                raise AutomationError("STEP_FAILED", "API_VIEW_REFUSED")
            api_digest = hashlib.sha256(body).hexdigest()
            if body != expected_model_bytes:
                raise AutomationError("STEP_FAILED", "API_MODEL_MISMATCH")
            probes_ok.append("API_VIEW")
        except (OSError, http.client.HTTPException):
            raise AutomationError("STEP_FAILED", "PROBE_IO") from None               # OS ・HTTP の文は出さない
    finally:
        server.shutdown()
    return ReadinessReport(probes_ok=tuple(probes_ok), api_model_digest=api_digest, api_matches_snapshot=True)


__all__ = ["PROBES", "PROBE_TIMEOUT_SECONDS", "READINESS_SCHEMA_VERSION", "STATIC_SHELL_BLOB", "STATIC_SHELL_ROUTE",
           "ReadinessReport", "verify_server_readiness"]
