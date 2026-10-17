#!/usr/bin/env python3
r"""P11-A5 real Windows local validation helper.  REPO-EXTERNAL - NEVER COMMIT.  Place at D:\p11_a5_work\a5.py.

Stages (run in order; each prints REPORT lines only and stops on the first failure):
  python D:\p11_a5_work\a5.py preflight --repo <path to daily-market-brief checkout>
  python D:\p11_a5_work\a5.py read --at <ISO instant with UTC offset> --as-of-date <YYYY-MM-DD>
  python D:\p11_a5_work\a5.py server
  python D:\p11_a5_work\a5.py browser      [--headed]
  python D:\p11_a5_work\a5.py storage      [--headed]
  python D:\p11_a5_work\a5.py offline      [--headed]
  python D:\p11_a5_work\a5.py restart      [--headed]
  python D:\p11_a5_work\a5.py verify

Guarantees: D:\p9_a5_private and D:\p10_a5_private are READ ONLY for this helper (byte manifests before and after every
stage; the helper never initializes / writes / repairs / deletes / renames anything under them). The loopback server is
the real Phase 11 server from the checkout at the exact expected HEAD. Outbound network: socket / getaddrinfo / urllib /
http.client / J-Quants client classes are trapped in this process (only 127.0.0.1 is allowed); page-originated browser
traffic is intercepted and must be loopback only. JQUANTS_API_KEY is removed from this process and must be absent.
Private values (ids, notes, authority content, the model bytes, the chosen instant) stay in D:\p11_a5_work.
Paste back only REPORT lines.
"""
from __future__ import annotations

import os

_CREDENTIAL_WAS_PRESENT = os.environ.get("JQUANTS_API_KEY", "") != ""         # never read or printed
os.environ.pop("JQUANTS_API_KEY", None)

import argparse  # noqa: E402
import hashlib  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import socket  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import urllib.request  # noqa: E402
from datetime import date, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

EXPECTED_HEAD = "43c0b856d41efed397de213a1a06178c5e97ab10"
DEFAULT_P9_ROOT = r"D:\p9_a5_private"            # READ ONLY (real Phase 9 private root)
DEFAULT_P10_ROOT = r"D:\p10_a5_private"          # READ ONLY (real Phase 10 private root from P10-A5)
DEFAULT_WORK = r"D:\p11_a5_work"                 # private work directory (this helper + private state + browser profile)
STAGES = ("preflight", "read", "server", "browser", "storage", "offline", "restart", "verify")
FOCUSED_TESTS = ("tests/intelligence/test_personal_ui_boundary.py", "tests/intelligence/test_personal_ui_static.py",
                 "tests/intelligence/test_personal_ui_server.py", "tests/intelligence/test_personal_ui_adapter.py",
                 "tests/intelligence/test_personal_ui_hardening.py",
                 "tests/intelligence/test_personal_intelligence_boundary.py",
                 "tests/intelligence/test_watchlist_thesis_boundary.py",
                 "tests/intelligence/test_screener_intelligence_boundary.py",
                 "tests/intelligence/test_narrative_intelligence_boundary.py")
TOP_KEYS = {"at", "as_of_date", "active_profile_present", "review_lookahead_days", "personal_counts", "p9_counts",
            "unmatched_live_mark_count", "entries", "source_schema_versions", "schema_version", "view_class"}
ENTRY_KEYS = {"ordinal", "source_kind", "p9_status", "p9_provenance_kind", "review_due_on", "due_class", "attention",
              "excluded_by_profile", "surface_group", "linked_watch_ordinal"}
TITLE = "Personal Intelligence — private local"
OFFLINE_TEXT = "App shell available offline; private data requires the local server."
BROWSER_ARGS = ["--disable-background-networking", "--disable-component-update", "--disable-sync",
                "--disable-default-apps", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                "--disable-features=OptimizationHints,MediaRouter,Translate,InterestFeedContentSuggestions"]
P9_ROOT = Path(DEFAULT_P9_ROOT)
P10_ROOT = Path(DEFAULT_P10_ROOT)
WORK = Path(DEFAULT_WORK)


class Fail(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GuardTripped(Exception):
    pass


_HITS: list = []
_REAL_CREATE_CONNECTION = socket.create_connection
_REAL_CONNECT = socket.socket.connect
_REAL_GETADDRINFO = socket.getaddrinfo
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "", None)


def report(line: str) -> None:
    sys.stdout.write(f"REPORT: {line}\n")
    sys.stdout.flush()


# ------------------------------------------------------------------ zero network / zero J-Quants guard (this process)


def _trap(name: str):
    def trap(*_args, **_kwargs):
        _HITS.append(name)
        raise GuardTripped(name)
    return trap


def _host_of(address) -> object:
    return address[0] if isinstance(address, tuple) else address


def _guarded_create_connection(address, *args, **kwargs):
    if _host_of(address) not in LOOPBACK_HOSTS:
        _HITS.append("socket.create_connection")
        raise GuardTripped("socket.create_connection")
    return _REAL_CREATE_CONNECTION(address, *args, **kwargs)


def _guarded_connect(self, address):
    if isinstance(address, tuple) and _host_of(address) not in LOOPBACK_HOSTS:
        _HITS.append("socket.connect")
        raise GuardTripped("socket.connect")
    return _REAL_CONNECT(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host not in LOOPBACK_HOSTS and not (isinstance(host, bytes) and host.decode("ascii", "replace") in LOOPBACK_HOSTS):
        _HITS.append("socket.getaddrinfo")
        raise GuardTripped("socket.getaddrinfo")
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def install_network_guard() -> None:
    socket.create_connection = _guarded_create_connection
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _trap("socket.connect_ex")
    socket.getaddrinfo = _guarded_getaddrinfo
    http.client.HTTPSConnection.connect = _trap("https.connect")
    urllib.request.urlopen = _trap("urllib.urlopen")


def install_jquants_guard() -> int:
    trapped = 0
    for name, module in list(sys.modules.items()):
        if module is None or "jquants" not in name:
            continue
        for attr, value in list(vars(module).items()):
            if isinstance(value, type) and value.__module__ == name and ("Client" in attr or "Transport" in attr):
                value.__init__ = _trap(f"{name}.{attr}")
                trapped += 1
        if hasattr(module, "_HTTPSConnection"):
            module._HTTPSConnection = _trap(f"{name}._HTTPSConnection")
            trapped += 1
    if "requests" in sys.modules:
        sys.modules["requests"].request = _trap("requests.request")
        trapped += 1
    return trapped


install_network_guard()


# ------------------------------------------------------------------ private state (work directory only)


def load_state() -> dict:
    path = WORK / "a5_state.json"
    return json.loads(path.read_bytes().decode("utf-8")) if path.is_file() else {"done": []}


def save_state(state: dict) -> None:
    (WORK / "a5_state.json").write_bytes(json.dumps(state, sort_keys=True, indent=1).encode("utf-8"))


def require_done(state: dict, *stages: str) -> None:
    for stage in stages:
        if stage not in state["done"]:
            raise Fail(f"STAGE_NOT_READY:{stage}")


def mark_done(state: dict, stage: str) -> None:
    if stage not in state["done"]:
        state["done"].append(stage)
    save_state(state)


def private_log(text: str) -> None:
    if WORK.is_dir():
        with (WORK / "a5_private_errors.log").open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


# ------------------------------------------------------------------ root manifests (bytes only; never parsed here)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest(root: Path, code: str) -> dict:
    if not root.is_dir():
        raise Fail(f"{code}_ROOT_MISSING")
    entries = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        base = Path(dirpath)
        entries["D:" + base.relative_to(root).as_posix()] = [os.lstat(base).st_mtime_ns]
        for name in sorted(filenames):
            path = base / name
            rel = path.relative_to(root).as_posix()
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                entries["L:" + rel] = [info.st_mtime_ns]
            else:
                entries["F:" + rel] = [info.st_size, _sha256(path), info.st_mtime_ns]
    return entries


def capture_or_verify(root: Path, code: str) -> int:
    path = WORK / f"{code.lower()}_manifest.json"
    current = manifest(root, code)
    if not path.is_file():
        path.write_bytes(json.dumps(current, sort_keys=True).encode("utf-8"))
        report(f"{code}_MANIFEST_CAPTURED FILES={sum(1 for k in current if k.startswith('F:'))}")
        return len(current)
    if json.loads(path.read_bytes().decode("utf-8")) != current:
        raise Fail(f"{code}_MUTATED")
    return len(current)


def verify_roots(label: str) -> None:
    if (WORK / "p9_manifest.json").is_file():
        capture_or_verify(P9_ROOT, "P9")
    if (WORK / "p10_manifest.json").is_file():
        capture_or_verify(P10_ROOT, "P10")
    report(f"ROOTS_UNCHANGED_OK {label}")


# ------------------------------------------------------------------ repo / runtime


def git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, encoding="utf-8",
                                errors="replace", check=False)
    except OSError:
        raise Fail("GIT_UNAVAILABLE") from None
    if result.returncode != 0:
        raise Fail("GIT_FAILED")
    return result.stdout


def check_repo(repo: Path) -> None:
    if git(repo, "rev-parse", "HEAD").strip() != EXPECTED_HEAD:
        raise Fail("REPO_HEAD_MISMATCH")
    if git(repo, "status", "--porcelain").strip():
        raise Fail("REPO_NOT_CLEAN")


class Runtime:
    def __init__(self, repo: Path) -> None:
        if not (repo / "src" / "intelligence" / "personal_ui" / "local_server.py").is_file():
            raise Fail("REPO_LAYOUT_UNEXPECTED")
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from src.intelligence.personal_intelligence import p9_view
        from src.intelligence.personal_ui import local_server, p10_read_adapter, ui_model
        from tests.intelligence import phase11_runtime_registry as registry
        self.repo, self.p9_view, self.server, self.adapter, self.ui_model = repo, p9_view, local_server, p10_read_adapter, ui_model
        self.registry = registry
        self.jquants_traps = install_jquants_guard()
        if self.server.CREDENTIAL_VARIABLE in os.environ:
            raise Fail("CREDENTIAL_PRESENT")


def runtime(state: dict) -> Runtime:
    repo = Path(state["repo"])
    check_repo(repo)
    return Runtime(repo)


def check_assets(rt: Runtime) -> int:
    for asset, blob in rt.registry.P11_STATIC_BLOB_IDS.items():
        path = rt.repo / asset
        if not path.is_file() or path.is_symlink():
            raise Fail("STATIC_ASSET_MISSING")
        if git(rt.repo, "hash-object", "--", asset).strip() != blob:
            raise Fail("STATIC_ASSET_DRIFT")
    for route, (name, _ct) in rt.server.STATIC_ROUTES.items():
        if route not in rt.registry.P11_STATIC_ROUTES or rt.registry.P11_STATIC_ROUTES[route] != name:
            raise Fail("STATIC_ROUTE_DRIFT")
    return len(rt.registry.P11_STATIC_BLOB_IDS)


# ------------------------------------------------------------------ private tokens (never printed) and the governed model


def _strings(value, out: set) -> None:
    if isinstance(value, str):
        if (len(value) >= 6 and not re.fullmatch(r"[A-Z0-9_:.\-]+", value) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
                and not re.fullmatch(r"[a-z0-9_]+:\d+\.\d+\.\d+", value)):              # schema / rules versions are public shape
            out.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _strings(item, out)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _strings(item, out)
    elif hasattr(value, "__dataclass_fields__"):
        for name in value.__dataclass_fields__:
            _strings(getattr(value, name), out)


def private_tokens(rt: Runtime, state: dict) -> tuple:
    """Everything private that must never appear in REPORT / DOM / cache / console: P9 ids, issuer ids, names, notes,
    author strings, reviewed_at values, root paths. Collected in memory only."""
    tokens: set = set()
    snapshot = rt.p9_view.read_p9_private_snapshot(P9_ROOT, at=datetime.fromisoformat(state["at"]))
    _strings(snapshot, tokens)
    for row in list(snapshot.watch) + list(snapshot.thesis):
        for name in ("watch_entry_id", "thesis_id", "revision_id", "issuer_id"):
            if hasattr(row, name) and isinstance(getattr(row, name), str):
                tokens.add(getattr(row, name))
    directory = P10_ROOT / "personal_intelligence"
    for name in ("profile_authority.jsonl", "attention_authority.jsonl"):
        path = directory / name
        if path.is_file():
            for line in path.read_bytes().decode("utf-8").splitlines():
                if line.strip():
                    try:
                        _strings(json.loads(line), tokens)
                    except ValueError:
                        tokens.add(line.strip())
    tokens |= {str(P9_ROOT), str(P10_ROOT), str(WORK), "Traceback", "JQUANTS_API_KEY", "p9wat_", "p10prf_", "p10att_"}
    tokens.discard("")
    return tuple(sorted(tokens, key=len, reverse=True))


def scan(text: str, tokens: tuple, code: str) -> None:
    for token in tokens:
        if token and token in text:
            raise Fail(code)


def governed_model_bytes(rt: Runtime, state: dict) -> bytes:
    model = rt.adapter.read_ui_model(P10_ROOT, P9_ROOT, at=datetime.fromisoformat(state["at"]),
                                     as_of_date=date.fromisoformat(state["as_of_date"]))
    return rt.ui_model.ui_model_json_bytes(model)


def model_counts(payload: dict) -> dict:
    entries = payload["entries"]
    return dict(ENTRY_COUNT=len(entries), ACTIVE_PROFILE=1 if payload["active_profile_present"] else 0,
                FOCUS_COUNT=sum(1 for e in entries if e["attention"] == "FOCUS"),
                MUTE_COUNT=sum(1 for e in entries if e["attention"] == "MUTE"),
                EXCLUDED_COUNT=sum(1 for e in entries if e["excluded_by_profile"]),
                UNMATCHED_LIVE_MARKS=payload["unmatched_live_mark_count"])


def check_model_schema(payload: dict) -> None:
    if not isinstance(payload, dict) or set(payload) != TOP_KEYS:
        raise Fail("MODEL_SCHEMA_TOP_KEYS")
    if payload["schema_version"] != "p11_ui_model:0.1.0":
        raise Fail("MODEL_SCHEMA_VERSION")
    for entry in payload["entries"]:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise Fail("MODEL_SCHEMA_ENTRY_KEYS")
        for key in ("source_kind", "p9_status", "p9_provenance_kind", "due_class", "attention", "surface_group"):
            if not isinstance(entry[key], str) or not re.fullmatch(r"[A-Z0-9_]{0,80}", entry[key]):
                raise Fail("MODEL_SCHEMA_ENTRY_VALUE")


# ------------------------------------------------------------------ loopback server (in-process; the real Phase 11 server)


class Served:
    def __init__(self, rt: Runtime, port: int = 0) -> None:
        self.events: list = []
        last = None
        for _attempt in range(160):           # Linux keeps the port in TIME_WAIT for up to 60 s after a stop; Windows rebinds at once
            try:
                self.server = rt.server.LocalServer.start(P10_ROOT, P9_ROOT, port=port,
                                                          on_event=lambda *e: self.events.append(e))
                break
            except rt.server.ServerStartupError as exc:
                last = exc
                if exc.code != "BIND_FAILED" or port == 0:
                    raise Fail(f"SERVER_START_REFUSED:{exc.code}") from None
                time.sleep(0.5)
        else:
            raise Fail(f"SERVER_START_REFUSED:{last.code if last else 'BIND_FAILED'}")
        self.server.start_in_thread()
        self.port = self.server.port

    @property
    def app_url(self) -> str:
        return self.server.app_url

    def api_calls(self) -> int:
        return sum(1 for e in self.events if e[1] == "/api/view")

    def stop(self) -> None:
        self.server.shutdown()


def http_request(port: int, method: str, path: str, body=None, headers=None, host=None) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    hdrs = {"Host": host if host is not None else f"127.0.0.1:{port}"}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        hdrs.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
    hdrs.update(headers or {})
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for key, value in hdrs.items():
        conn.putheader(key, value)
    conn.endheaders(data)
    response = conn.getresponse()
    out = dict(status=response.status, headers={k.lower(): v for k, v in response.getheaders()}, body=response.read())
    conn.close()
    return out


def view_body(served: Served, state: dict) -> dict:
    return http_request(served.port, "POST", "/api/view", {"at": state["at"], "as_of_date": state["as_of_date"]},
                        headers={"Origin": f"http://127.0.0.1:{served.port}", "Sec-Fetch-Site": "same-origin"})


# ------------------------------------------------------------------ browser (Playwright if available; manual fallback)


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class Browser:
    """Fresh validation-only profile under WORK/browser_profile. Page-originated requests are intercepted: anything
    that is not the loopback server is aborted and counted. Console output is collected (never printed)."""

    def __init__(self, port: int, headed: bool) -> None:
        from playwright.sync_api import sync_playwright
        self.port = port
        self.origin = f"http://127.0.0.1:{port}"
        self.playwright = sync_playwright().start()
        self.profile = WORK / "browser_profile"
        self.profile.mkdir(exist_ok=True)
        self.label, self.context = self._launch(headed)
        self.requests: list = []
        self.foreign: list = []
        self.console: list = []
        self.dialogs: list = []
        self.context.route("**/*", self._route)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.on("console", lambda message: self.console.append(message.text))
        self.page.on("dialog", lambda dialog: (self.dialogs.append(dialog.type), dialog.dismiss()))

    def _launch(self, headed: bool):
        errors = []
        candidates = [("playwright-chromium", {}), ("msedge", {"channel": "msedge"}), ("chrome", {"channel": "chrome"})]
        explicit = os.environ.get("P11_A5_BROWSER", "")
        if explicit:
            candidates.insert(0, ("explicit", {"executable_path": explicit}))
        for label, extra in candidates:
            try:
                context = self.playwright.chromium.launch_persistent_context(
                    str(self.profile), headless=not headed, args=BROWSER_ARGS, accept_downloads=False,
                    service_workers="allow", **extra)
                return label, context
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {type(exc).__name__}")
        private_log("browser launch failed: " + "; ".join(errors))
        raise Fail("BROWSER_UNAVAILABLE")

    def _route(self, route, request) -> None:
        self.requests.append(request.url)
        if not request.url.startswith(self.origin + "/"):
            self.foreign.append(request.url)
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            self.playwright.stop()

    # ---- helpers
    def evaluate(self, script: str):
        return self.page.evaluate(script)

    def goto_app(self) -> None:
        self.page.goto(self.origin + "/app/", wait_until="load")
        if self.page.title() != TITLE:
            raise Fail("SHELL_TITLE_MISMATCH")

    def wait_ready(self) -> None:
        self.evaluate("() => navigator.serviceWorker.ready.then(() => true)")

    def cleanup_p11_only(self) -> None:
        """Remove only P11 state from the validation profile: the /app/ worker and p11-shell-* caches."""
        self.evaluate("""async () => {
            const reg = await navigator.serviceWorker.getRegistration('/app/');
            if (reg) { await reg.unregister(); }
            for (const name of await caches.keys()) { if (name.startsWith('p11-shell-')) { await caches.delete(name); } }
        }""")

    def fill_and_load(self, state: dict) -> None:
        self.page.fill("#at", state["at"])
        self.page.fill("#as-of-date", state["as_of_date"])
        self.page.click("#load")
        self.page.wait_for_function("() => !document.getElementById('review').hidden"
                                    " || !document.getElementById('message').hidden", timeout=20000)

    def rows(self) -> int:
        return self.page.locator("#review-rows tr").count()

    def wait_rows_cleared(self) -> None:
        self.page.wait_for_function("() => document.getElementById('review-rows').children.length === 0", timeout=20000)

    def storage(self) -> dict:
        return self.evaluate("""async () => {
            const caches_ = {};
            for (const name of await caches.keys()) {
                const cache = await caches.open(name);
                const entries = {};
                for (const req of await cache.keys()) {
                    entries[new URL(req.url).pathname] = await (await cache.match(req)).text();
                }
                caches_[name] = entries;
            }
            const dbs = indexedDB.databases ? (await indexedDB.databases()).map((db) => db.name) : null;
            return { localStorage: Object.keys(localStorage), sessionStorage: Object.keys(sessionStorage),
                     caches: caches_, indexedDB: dbs, cookie: document.cookie, href: location.href,
                     historyLength: history.length, historyState: history.state };
        }""")

    def dom_text(self) -> str:
        return self.evaluate("() => document.documentElement.outerHTML")


def check_storage(browser: Browser, rt: Runtime, tokens: tuple, model_bytes: bytes, state: dict, label: str) -> None:
    storage = browser.storage()
    if storage["localStorage"] or storage["sessionStorage"]:
        raise Fail(f"BROWSER_STORAGE_NOT_EMPTY:{label}")
    if storage["indexedDB"] is None:
        report(f"INDEXEDDB_ENUMERATION_UNAVAILABLE {label}")
    elif storage["indexedDB"]:
        raise Fail(f"INDEXEDDB_NOT_EMPTY:{label}")
    if storage["cookie"] != "" or browser.context.cookies():
        raise Fail(f"COOKIES_PRESENT:{label}")
    names = set(storage["caches"])
    if names != {rt.registry.P11_SHELL_CACHE_NAME}:
        raise Fail(f"CACHE_NAMESPACE_UNEXPECTED:{label}")
    entries = storage["caches"][rt.registry.P11_SHELL_CACHE_NAME]
    if set(entries) != set(rt.registry.P11_SHELL_PRECACHE):
        raise Fail(f"CACHE_ENTRIES_UNEXPECTED:{label}")
    for path, text in entries.items():
        if "/api/" in path:
            raise Fail(f"API_RESPONSE_CACHED:{label}")
        scan(text, tokens, f"PRIVATE_TOKEN_IN_CACHE:{label}")
        if model_bytes and model_bytes.decode("utf-8") in text:
            raise Fail(f"MODEL_IN_CACHE:{label}")
    href = storage["href"]
    if "?" in href or "#" in href or state["at"] in href or state["as_of_date"] in href or storage["historyState"] is not None:
        raise Fail(f"PIT_IN_URL_OR_HISTORY:{label}")
    report(f"BROWSER_STORAGE_EMPTY_OK {label}")
    report(f"CACHE_SHELL_ONLY_OK {label} ENTRIES={len(entries)}")


def check_dom_private(browser: Browser, tokens: tuple, label: str) -> None:
    html = browser.dom_text()
    scan(html, tokens, f"PRIVATE_TOKEN_IN_DOM:{label}")
    for needle in ("D:\\", "C:\\", "Traceback", "JQUANTS", "issuer", "revision_id", "author", "horizon_note",
                   "exclusion_reason"):
        if needle in html.replace("authority", ""):
            raise Fail(f"PRIVATE_SHAPE_IN_DOM:{label}")
    for message in browser.console:
        scan(message, tokens, f"PRIVATE_TOKEN_IN_CONSOLE:{label}")
        if not message.startswith("Failed to load resource"):
            raise Fail(f"CONSOLE_OUTPUT_UNEXPECTED:{label}")
    if browser.dialogs:
        raise Fail(f"BROWSER_DIALOG:{label}")


def check_network(browser: Browser, label: str) -> None:
    if browser.foreign:
        private_log("foreign page requests: " + "\n".join(browser.foreign))
        raise Fail(f"PAGE_FOREIGN_REQUEST:{label}")
    report(f"PAGE_LOOPBACK_ONLY_OK {label} REQUESTS={len(browser.requests)}")


def manual_checklist(items: tuple) -> None:
    """Fallback when browser automation is unavailable: the user answers y/n to visible checks only."""
    report("MANUAL_PATH")
    for number, (prompt, _expect) in enumerate(items, 1):
        sys.stdout.write(f"\nCHECK {number}: {prompt}\n  -> expected: {_expect}\n  OK? [y/n]: ")
        sys.stdout.flush()
        answer = sys.stdin.readline().strip().lower()
        if answer != "y":
            raise Fail(f"MANUAL_CHECK_FAILED:{number}")
        report(f"MANUAL_CHECK_{number}_OK")


# ------------------------------------------------------------------ stages


def stage_preflight(args, state: dict) -> None:
    if args.repo is None:
        raise Fail("REPO_REQUIRED")
    repo = Path(args.repo)
    if not repo.is_absolute():
        raise Fail("REPO_NOT_ABSOLUTE")
    if sys.version_info < (3, 10):
        raise Fail("PYTHON_TOO_OLD")
    report(f"PYTHON_OK {sys.version_info.major}.{sys.version_info.minor}")
    if not WORK.is_dir():
        raise Fail("WORK_DIR_MISSING")
    report("WORK_DIR_OK")
    for root, code in ((P9_ROOT, "P9"), (P10_ROOT, "P10")):
        if not root.is_dir():
            raise Fail(f"{code}_ROOT_MISSING")
        report(f"{code}_ROOT_PRESENT_OK")
    check_repo(repo)
    report("REPO_HEAD_OK")
    report("REPO_CLEAN_OK")
    rt = Runtime(repo)
    report(f"STATIC_ASSETS_OK COUNT={check_assets(rt)}")
    capture_or_verify(P9_ROOT, "P9")
    capture_or_verify(P10_ROOT, "P10")
    env = {k: v for k, v in os.environ.items() if k != "JQUANTS_API_KEY"}
    env["PYTHONUTF8"] = "1"                      # frozen P7-P9 suites decode git output via text=True: force UTF-8 (not cp932)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *FOCUSED_TESTS],
                            cwd=str(repo), env=env, capture_output=True, encoding="utf-8", errors="replace", check=False)
    (WORK / "a5_preflight_pytest.log").write_bytes((result.stdout + result.stderr).encode("utf-8", "replace"))
    if result.returncode != 0:
        for line in result.stdout.splitlines():
            if line.startswith("FAILED "):
                report("FAILED_TEST " + line.split(" ")[1])                     # repo test ids only (synthetic data)
        raise Fail("PREFLIGHT_TESTS_FAILED")
    summary = [line for line in result.stdout.splitlines() if " passed" in line]
    report("PREFLIGHT_TESTS_OK " + (summary[-1].strip("= ").split(" in ")[0] if summary else "?"))
    check_repo(repo)
    report("REPO_CLEAN_AFTER_TESTS_OK")
    report("BROWSER_AUTOMATION=" + ("playwright" if playwright_available() else "manual"))
    state["repo"] = str(repo)
    mark_done(state, "preflight")


def stage_read(args, state: dict) -> None:
    require_done(state, "preflight")
    if args.at is None or args.as_of_date is None:
        raise Fail("AT_AND_AS_OF_DATE_REQUIRED")
    try:
        instant = datetime.fromisoformat(args.at)
        as_of = date.fromisoformat(args.as_of_date)
    except ValueError:
        raise Fail("PIT_INVALID") from None
    if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise Fail("AT_NOT_AWARE")
    if state.get("at") not in (None, args.at) or state.get("as_of_date") not in (None, as_of.isoformat()):
        raise Fail("PIT_ALREADY_BOUND")
    state["at"], state["as_of_date"] = args.at, as_of.isoformat()
    rt = runtime(state)
    first = governed_model_bytes(rt, state)
    second = governed_model_bytes(rt, state)
    if first != second:
        raise Fail("MODEL_NOT_DETERMINISTIC")
    payload = json.loads(first.decode("utf-8"))
    check_model_schema(payload)
    tokens = private_tokens(rt, state)
    scan(first.decode("utf-8"), tokens, "PRIVATE_TOKEN_IN_MODEL")
    (WORK / "a5_model.bin").write_bytes(first)
    report("MODEL_OK")
    report("MODEL_DETERMINISTIC_OK")
    report("MODEL_SCHEMA_OK")
    report(f"PRIVATE_TOKENS_CHECKED={len(tokens)}")
    for key, value in model_counts(payload).items():
        report(f"{key}={value}")
    mark_done(state, "read")


def stage_server(args, state: dict) -> None:
    require_done(state, "read")
    rt = runtime(state)
    expected = (WORK / "a5_model.bin").read_bytes()
    tokens = private_tokens(rt, state)
    # 1. the CLI entry exactly as a user would start it: startup line must carry only the loopback URLs
    env = {k: v for k, v in os.environ.items() if k != "JQUANTS_API_KEY"}
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen([sys.executable, "-m", "src.intelligence.personal_ui.local_server", "--p10-root", str(P10_ROOT),
                             "--p9-root", str(P9_ROOT)], cwd=str(rt.repo), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        line = proc.stdout.readline().strip()
        if not line:
            raise Fail("CLI_NO_STARTUP_LINE")
        startup = json.loads(line)
        if startup.get("status") != "listening" or set(startup) != {"app_url", "schema_version", "status", "url"}:
            raise Fail("CLI_STARTUP_UNEXPECTED")
        scan(line, tokens, "PRIVATE_TOKEN_IN_STARTUP")
        cli_port = int(startup["url"].rsplit(":", 1)[1].rstrip("/"))
        if not startup["url"].startswith("http://127.0.0.1:") or startup["app_url"] != startup["url"] + "app/":
            raise Fail("CLI_URL_UNEXPECTED")
        health = http_request(cli_port, "GET", "/health")
        if health["status"] != 200 or json.loads(health["body"]).get("status") != "ok":
            raise Fail("CLI_HEALTH_FAILED")
        report("CLI_STARTUP_OK")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    # 2. credential refusal (fresh process; the credential value is a dummy; roots are never touched before the check)
    env_cred = dict(env, JQUANTS_API_KEY="a5-dummy-not-a-real-key")
    refused = subprocess.run([sys.executable, "-m", "src.intelligence.personal_ui.local_server", "--p10-root",
                              str(WORK / "not-a-root"), "--p9-root", str(WORK / "not-a-root")], cwd=str(rt.repo),
                             env=env_cred, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if refused.returncode != 2 or '"code":"CREDENTIAL_PRESENT"' not in refused.stdout:
        raise Fail("CREDENTIAL_REFUSAL_BROKEN")
    report("CREDENTIAL_REFUSAL_OK")
    bad_bind = subprocess.run([sys.executable, "-m", "src.intelligence.personal_ui.local_server", "--p10-root",
                               str(WORK / "not-a-root"), "--p9-root", str(WORK / "not-a-root"), "--bind", "0.0.0.0"],
                              cwd=str(rt.repo), env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    if bad_bind.returncode != 2 or '"code":"BIND_NOT_LOOPBACK"' not in bad_bind.stdout:
        raise Fail("NON_LOOPBACK_BIND_NOT_REFUSED")
    report("NON_LOOPBACK_BIND_REFUSED_OK")
    # 3. in-process server: health / version / Host policy / static bytes / API bytes
    served = Served(rt)
    try:
        port = served.port
        if json.loads(http_request(port, "GET", "/health")["body"]).get("status") != "ok":
            raise Fail("HEALTH_FAILED")
        version = json.loads(http_request(port, "GET", "/version")["body"])
        if version.get("ui_model_schema_version") != "p11_ui_model:0.1.0":
            raise Fail("VERSION_UNEXPECTED")
        report("HEALTH_VERSION_OK")
        for host in (f"localhost:{port}", "127.0.0.1", f"evil.example:{port}", f"127.0.0.1:{port}:"):
            if http_request(port, "GET", "/health", host=host)["status"] != 400:
                raise Fail("HOST_POLICY_BROKEN")
        if http_request(port, "POST", "/api/view", {"at": state["at"], "as_of_date": state["as_of_date"]},
                        headers={"Origin": "http://evil.example"})["status"] != 403:
            raise Fail("ORIGIN_POLICY_BROKEN")
        report("HOST_ORIGIN_POLICY_OK")
        # Windows: a refusal written before the body arrives must still reach the client (server drains, then closes)
        body = json.dumps({"at": state["at"], "as_of_date": state["as_of_date"]}).encode("utf-8")
        head = (f"POST /api/view HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://evil.example\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode("ascii")
        with _REAL_CREATE_CONNECTION(("127.0.0.1", port), timeout=10) as sock:
            sock.sendall(head)
            time.sleep(0.3)
            sock.sendall(body)
            split = b""
            while chunk := sock.recv(65536):
                split += chunk
        if not split.startswith(b"HTTP/1.0 403") or b'"code":"FETCH_SITE_REJECTED"' not in split:
            raise Fail("SPLIT_SEND_REFUSAL_BROKEN")
        report("SPLIT_SEND_REFUSAL_OK")
        for route, (name, content_type) in rt.server.STATIC_ROUTES.items():
            response = http_request(port, "GET", route)
            committed = (rt.repo / rt.registry.PHASE11_STATIC_DIR / name).read_bytes()
            if response["status"] != 200 or response["body"] != committed or response["headers"]["content-type"] != content_type:
                raise Fail("STATIC_SERVE_MISMATCH")
            if "content-security-policy" not in response["headers"] or "set-cookie" in response["headers"]:
                raise Fail("STATIC_HEADERS_UNEXPECTED")
        report(f"STATIC_SERVED_OK ROUTES={len(rt.server.STATIC_ROUTES)}")
        view = view_body(served, state)
        if view["status"] != 200:
            raise Fail(f"VIEW_REFUSED:{json.loads(view['body']).get('code', 'UNKNOWN')}")
        if view["body"] != expected:
            raise Fail("API_BYTES_DIFFER_FROM_A1")
        if view["headers"].get("cache-control") != "no-store" or "set-cookie" in view["headers"]:
            raise Fail("API_HEADERS_UNEXPECTED")
        report("API_EQUALS_A1_BYTES_OK")
        report("SERVER_READY")
        report(f"APP_URL={served.app_url}")
    finally:
        served.stop()
    mark_done(state, "server")


def automated_online(rt: Runtime, state: dict, headed: bool, label: str, keep_open=None):
    """Start server + fresh-profile browser, render once with the explicit PIT, run the online checks."""
    expected = json.loads((WORK / "a5_model.bin").read_bytes().decode("utf-8"))
    counts = model_counts(expected)
    tokens = private_tokens(rt, state)
    served = Served(rt)
    browser = Browser(served.port, headed)
    try:
        report(f"BROWSER_PATH={browser.label}")
        browser.goto_app()
        browser.cleanup_p11_only()                                      # P11 state only; profile is validation-only anyway
        browser.page.reload(wait_until="load")
        browser.wait_ready()
        if browser.evaluate("() => document.getElementById('at').value + document.getElementById('as-of-date').value") != "":
            raise Fail("PIT_FIELDS_NOT_EMPTY")
        if "PRIVATE" not in browser.page.text_content("#private-indicator"):
            raise Fail("PRIVATE_INDICATOR_MISSING")
        if served.api_calls() != 0:
            raise Fail("AUTOMATIC_REQUEST_DETECTED")
        report(f"SHELL_LOADED_OK {label}")
        manifest_text = browser.evaluate("async () => (await fetch('/app/manifest.webmanifest')).text()")
        manifest_json = json.loads(manifest_text)
        if manifest_json.get("start_url") != "/app/" or manifest_json.get("scope") != "/app/":
            raise Fail("MANIFEST_INVALID")
        browser.fill_and_load(state)
        if browser.rows() != counts["ENTRY_COUNT"]:
            raise Fail("UI_ENTRY_COUNT_MISMATCH")
        if served.api_calls() != 1:
            raise Fail("REQUEST_COUNT_UNEXPECTED")
        marks = browser.evaluate("() => Array.from(document.querySelectorAll('#review-rows tr')).map((tr) => tr.dataset.attention)")
        excluded = browser.evaluate("() => document.querySelectorAll('#review-rows tr[data-excluded=\"true\"]').length")
        if marks.count("MUTE") != counts["MUTE_COUNT"] or marks.count("FOCUS") != counts["FOCUS_COUNT"]:
            raise Fail("ATTENTION_MARKS_MISMATCH")
        if excluded != counts["EXCLUDED_COUNT"]:
            raise Fail("EXCLUDED_MARKS_MISMATCH")
        report(f"UI_RENDER_OK {label} ENTRIES={counts['ENTRY_COUNT']} MUTE_VISIBLE={marks.count('MUTE')} "
               f"EXCLUDED_VISIBLE={excluded}")
        check_dom_private(browser, tokens, label)
        report(f"DOM_PRIVATE_CLEAN_OK {label}")
        if not browser.evaluate("async () => !!(await navigator.serviceWorker.getRegistration('/app/'))"):
            raise Fail("SW_NOT_REGISTERED")
        report(f"SW_REGISTERED_OK {label}")
        if keep_open is not None:
            keep_open(served, browser, tokens, expected)
        check_network(browser, label)
    finally:
        try:
            browser.close()
        finally:
            served.stop()
    return tokens


MANUAL_ONLINE = (
    ("Open the APP_URL printed by `a5.py server` in Microsoft Edge or Chrome (a fresh profile / InPrivate window is fine).",
     "the page title is 'Personal Intelligence — private local' and a 'PRIVATE ・ LOCAL ・ READ-ONLY' badge is visible"),
    ("Look at the two input fields.", "both 'at' and 'as_of_date' are EMPTY; nothing loaded by itself"),
    ("Type your chosen at / as_of_date (the same values you gave `a5.py read`) and press 読み込む.",
     "a table appears; the number of rows equals ENTRY_COUNT from `a5.py read`"),
    ("Look at the 印 column and the 除外 column.", "MUTE rows (if MUTE_COUNT > 0) are visible but greyed; 除外 appears on excluded rows"),
    ("Scan the visible page once.", "no names, codes, ids, notes, file paths or JSON are visible: only counts, dates, codes like FOCUS/MUTE"),
)


def stage_browser(args, state: dict) -> None:
    require_done(state, "server")
    rt = runtime(state)
    if not playwright_available():
        served = Served(rt)
        try:
            report("SERVER_READY")
            report(f"APP_URL={served.app_url}")
            manual_checklist(MANUAL_ONLINE)
        finally:
            served.stop()
        state["browser_path"] = "manual"
    else:
        automated_online(rt, state, args.headed, "browser")
        state["browser_path"] = "playwright"
    mark_done(state, "browser")


MANUAL_STORAGE = (
    ("With the page loaded (after a successful 読み込む), press F12 → Application → Storage → Local storage → the 127.0.0.1 origin.",
     "no keys"),
    ("Application → Storage → Session storage → the 127.0.0.1 origin.", "no keys"),
    ("Application → Storage → IndexedDB.", "no databases for 127.0.0.1"),
    ("Application → Storage → Cookies.", "no cookies for 127.0.0.1"),
    ("Application → Cache storage.", "exactly one cache whose name starts with 'p11-shell-'; its entries are /app/ shell files only; NO /api/view"),
    ("Look at the address bar after loading.", "the URL is exactly the APP_URL with nothing after /app/ (no ?at=, no #)"),
)


def stage_storage(args, state: dict) -> None:
    require_done(state, "browser")
    rt = runtime(state)
    if state.get("browser_path") == "manual":
        served = Served(rt)
        try:
            report(f"APP_URL={served.app_url}")
            manual_checklist(MANUAL_STORAGE)
        finally:
            served.stop()
    else:
        def after(served, browser, tokens, expected):
            model_bytes = (WORK / "a5_model.bin").read_bytes()
            check_storage(browser, rt, tokens, model_bytes, state, "storage")
            browser.fill_and_load(state)                                       # repeated render
            check_storage(browser, rt, tokens, model_bytes, state, "storage-repeat")
            if browser.evaluate("() => history.length") != 1 and browser.evaluate("() => history.state") is not None:
                raise Fail("HISTORY_UNEXPECTED")
            report("PIT_NOT_IN_URL_OK")
        automated_online(rt, state, args.headed, "storage", keep_open=after)
    mark_done(state, "storage")


MANUAL_OFFLINE = (
    ("Load the page and press 読み込む successfully, then press Enter here: the helper STOPS the server now.", "server stopped"),
    ("Reload the page (F5).", f"the shell still appears (title unchanged); the table is EMPTY; the red message '{OFFLINE_TEXT}' or 'server: local server unavailable' is shown"),
    ("Fill at / as_of_date again and press 読み込む.", "no rows appear; a message says the local server cannot be reached; no old data is shown"),
    ("Press Enter here: the helper RESTARTS the server on the same port.", "server restarted"),
    ("Press 読み込む again.", "the table appears again with the same ENTRY_COUNT"),
)


def stage_offline(args, state: dict) -> None:
    require_done(state, "storage")
    rt = runtime(state)
    expected = json.loads((WORK / "a5_model.bin").read_bytes().decode("utf-8"))
    if state.get("browser_path") == "manual":
        served = Served(rt)
        port = served.port
        try:
            report(f"APP_URL={served.app_url}")
            report("MANUAL_PATH")
            sys.stdout.write(f"\nCHECK 1: {MANUAL_OFFLINE[0][0]}\n  OK? [y/n]: ")
            sys.stdout.flush()
            if sys.stdin.readline().strip().lower() != "y":
                raise Fail("MANUAL_CHECK_FAILED:1")
            served.stop()
            report("MANUAL_CHECK_1_OK SERVER_STOPPED")
            for number, (prompt, expect) in enumerate(MANUAL_OFFLINE[1:3], 2):
                sys.stdout.write(f"\nCHECK {number}: {prompt}\n  -> expected: {expect}\n  OK? [y/n]: ")
                sys.stdout.flush()
                if sys.stdin.readline().strip().lower() != "y":
                    raise Fail(f"MANUAL_CHECK_FAILED:{number}")
                report(f"MANUAL_CHECK_{number}_OK")
            sys.stdout.write(f"\nCHECK 4: {MANUAL_OFFLINE[3][0]}\n  OK? [y/n]: ")
            sys.stdout.flush()
            if sys.stdin.readline().strip().lower() != "y":
                raise Fail("MANUAL_CHECK_FAILED:4")
            served = Served(rt, port=port)
            report("MANUAL_CHECK_4_OK SERVER_RESTARTED")
            sys.stdout.write(f"\nCHECK 5: {MANUAL_OFFLINE[4][0]}\n  -> expected: {MANUAL_OFFLINE[4][1]}\n  OK? [y/n]: ")
            sys.stdout.flush()
            if sys.stdin.readline().strip().lower() != "y":
                raise Fail("MANUAL_CHECK_FAILED:5")
            report("MANUAL_CHECK_5_OK")
        finally:
            served.stop()
        mark_done(state, "offline")
        return
    counts = model_counts(expected)
    tokens = private_tokens(rt, state)
    model_bytes = (WORK / "a5_model.bin").read_bytes()
    served = Served(rt)
    port = served.port
    browser = Browser(port, args.headed)
    try:
        browser.goto_app()
        browser.wait_ready()
        browser.fill_and_load(state)
        if browser.rows() != counts["ENTRY_COUNT"]:
            raise Fail("UI_ENTRY_COUNT_MISMATCH")
        report("ONLINE_RENDER_OK offline-1")
        served.stop()                                                     # 2. server loss ...
        browser.context.set_offline(True)                                 # ... and the device offline
        browser.page.reload(wait_until="load")                            # 3. reload: shell from the service worker
        if browser.page.title() != TITLE:
            raise Fail("OFFLINE_SHELL_NOT_LOADED")
        if browser.rows() != 0:
            raise Fail("STALE_ROWS_AFTER_RELOAD")
        if browser.page.locator("#offline").is_hidden() or OFFLINE_TEXT not in browser.page.text_content("#offline"):
            raise Fail("OFFLINE_STATE_NOT_SHOWN")
        report("OFFLINE_SHELL_LOADED_OK")
        report("OFFLINE_PRIVATE_DATA_ABSENT_OK")
        browser.fill_and_load(state)                                      # 6. explicit attempt fails safely
        if browser.rows() != 0 or browser.page.locator("#review").is_visible():
            raise Fail("STALE_ROWS_AFTER_FAILED_LOAD")
        report("OFFLINE_LOAD_FAILS_SAFELY_OK")
        check_dom_private(browser, tokens, "offline")
        storage = browser.storage()
        for name, entries in storage["caches"].items():
            if any("/api/" in path for path in entries) or any(model_bytes.decode("utf-8") in text for text in entries.values()):
                raise Fail("API_RESPONSE_CACHED:offline")
        report("API_NOT_CACHED_OK offline")
        browser.context.set_offline(False)
        served = Served(rt, port=port)                                     # 10. restart on the same port (same origin)
        browser.fill_and_load(state)                                      # 11. load again succeeds
        if browser.rows() != counts["ENTRY_COUNT"]:
            raise Fail("RELOAD_AFTER_RESTART_FAILED")
        report("RESTART_RENDER_OK offline-2")
        # stale rows must also vanish on a refused refresh while online
        browser.page.fill("#as-of-date", "2026-02-30")
        browser.page.click("#load")
        browser.wait_rows_cleared()
        report("STALE_ROWS_CLEARED_ON_REFUSAL_OK")
        check_storage(browser, rt, tokens, model_bytes, state, "offline")
        check_network(browser, "offline")
    finally:
        try:
            browser.close()
        finally:
            served.stop()
    mark_done(state, "offline")


def stage_restart(args, state: dict) -> None:
    require_done(state, "offline")
    rt = runtime(state)
    expected = (WORK / "a5_model.bin").read_bytes()
    tokens = private_tokens(rt, state)
    counts = model_counts(json.loads(expected.decode("utf-8")))
    bodies = []
    for round_number in (1, 2):
        served = Served(rt)
        try:
            view = view_body(served, state)
            if view["status"] != 200:
                raise Fail("VIEW_REFUSED_ON_RESTART")
            bodies.append(view["body"])
            if state.get("browser_path") != "manual":
                browser = Browser(served.port, args.headed)
                try:
                    browser.goto_app()
                    browser.wait_ready()
                    browser.fill_and_load(state)
                    if browser.rows() != counts["ENTRY_COUNT"]:
                        raise Fail("UI_ENTRY_COUNT_MISMATCH")
                    check_storage(browser, rt, tokens, expected, state, f"restart-{round_number}")
                    check_network(browser, f"restart-{round_number}")
                finally:
                    browser.close()
        finally:
            served.stop()
        report(f"RESTART_{round_number}_OK")
    if bodies[0] != bodies[1] or bodies[0] != expected:
        raise Fail("RESPONSE_NOT_IDENTICAL_ACROSS_RESTART")
    report("RESPONSE_IDENTICAL_ACROSS_RESTART_OK")
    report(f"UI_ENTRY_COUNT_IDENTICAL_OK {counts['ENTRY_COUNT']}")
    mark_done(state, "restart")


def stage_verify(args, state: dict) -> None:
    require_done(state, "restart")
    rt = runtime(state)
    for root, code in ((P9_ROOT, "P9"), (P10_ROOT, "P10")):
        if json.loads((WORK / f"{code.lower()}_manifest.json").read_bytes().decode("utf-8")) != manifest(root, code):
            raise Fail(f"{code}_MUTATED")
        report(f"{code}_READ_ONLY_OK")
    check_repo(rt.repo)
    check_assets(rt)
    report("REPO_UNCHANGED_OK")
    if state.get("browser_path") != "manual":
        served = Served(rt)
        browser = Browser(served.port, args.headed)
        try:
            browser.goto_app()
            browser.wait_ready()
            check_storage(browser, rt, private_tokens(rt, state), (WORK / "a5_model.bin").read_bytes(), state, "verify")
            check_network(browser, "verify")
        finally:
            try:
                browser.close()
            finally:
                served.stop()
        report("BROWSER_PRIVATE_STORAGE_EMPTY_OK")
        report("API_NOT_CACHED_OK")
    else:
        report("BROWSER_PRIVATE_STORAGE_EMPTY_OK MANUAL")
        report("API_NOT_CACHED_OK MANUAL")
    report("OFFLINE_SHELL_ONLY_OK")
    report("ZERO_OUTBOUND_OK")
    report(f"BROWSER_PATH={state.get('browser_path', 'unknown')}")
    report("A5_PASS")
    mark_done(state, "verify")


HANDLERS = {"preflight": stage_preflight, "read": stage_read, "server": stage_server, "browser": stage_browser,
            "storage": stage_storage, "offline": stage_offline, "restart": stage_restart, "verify": stage_verify}


def main(argv=None) -> int:
    global P9_ROOT, P10_ROOT, WORK
    parser = argparse.ArgumentParser(prog="a5.py")
    parser.add_argument("command", choices=STAGES)
    parser.add_argument("--repo")
    parser.add_argument("--at")
    parser.add_argument("--as-of-date")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--p9-root", default=DEFAULT_P9_ROOT, help=argparse.SUPPRESS)      # synthetic validation only
    parser.add_argument("--p10-root", default=DEFAULT_P10_ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--work", default=DEFAULT_WORK, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    P9_ROOT, P10_ROOT, WORK = Path(args.p9_root), Path(args.p10_root), Path(args.work)
    report(f"STAGE {args.command}")
    ok = True
    try:
        if _CREDENTIAL_WAS_PRESENT:
            raise Fail("CREDENTIAL_PRESENT_UNSET_IT_AND_RERUN")
        report("CREDENTIAL_ABSENT_OK")
        if (WORK / "p9_manifest.json").is_file():
            verify_roots("before")
        state = load_state()
        HANDLERS[args.command](args, state)
    except Fail as exc:
        ok = False
        report(f"FAIL {exc.code}")
    except GuardTripped:
        ok = False
        report("FAIL NETWORK_OR_JQUANTS_ATTEMPT")
    except Exception as exc:  # noqa: BLE001 - private traceback only; safe class name / code to stdout
        ok = False
        private_log(traceback.format_exc())
        code = getattr(exc, "code", None)
        report(f"FAIL {type(exc).__name__}:{code}" if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_:]+", code)
               else f"FAIL UNEXPECTED:{type(exc).__name__}")
    if _HITS:
        ok = False
        report(f"FAIL NETWORK_OR_JQUANTS_ATTEMPTS={len(_HITS)}")
    else:
        report("ZERO_NETWORK_OK")
    if (WORK / "p9_manifest.json").is_file():
        try:
            verify_roots("after")
            report("P9_READ_ONLY_OK")
            report("P10_READ_ONLY_OK")
        except Fail as exc:
            ok = False
            report(f"FAIL {exc.code}")
    report(f"STAGE_{'PASS' if ok else 'FAIL'} {args.command}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
