"""P12-A6 — Windows real-machine automation validation helper (repo-external; Python standard library only).

Validates the Phase 12 automation runtime (P12-A1 .. A5.1) on a real Windows machine with the real Task Scheduler:
authority (schedule / calendar / runtime pin) written through the real CLI, one manual scheduled-run, task install,
one run started by Task Scheduler, duplicate invocations (process layer and scheduler layer), the unattended
RECOVERY_REQUIRED policy against synthetic evidence (and the human recovery commands afterwards), the semantic
skips (MISSED / NON_BUSINESS_DAY / NOT_DUE / DISABLED), removal of only the A6-owned tasks, and a final verification.

    python D:\\p12_a6_work\\a6.py validate                 # everything (stages 0..9), stops on the first failure
    python D:\\p12_a6_work\\a6.py validate --resume        # continue after the last completed stage
    python D:\\p12_a6_work\\a6.py validate --full-suite    # also run the whole pytest suite at the very end (optional)
    python D:\\p12_a6_work\\a6.py status                   # which stages are done
    python D:\\p12_a6_work\\a6.py archive-previous         # move a previous D:\\p12_a6_private (and state) into the archive
    python D:\\p12_a6_work\\a6.py diagnose                 # preflight-only process-probe / lock-classification diagnostics (v2)

Everything written to the screen starts with "REPORT: " and contains only codes, counts, digests, slot ids and task
names. No path, pid, date, time, user name, private value or exception text is printed. Private details stay in
D:\\p12_a6_work (never pasted).

Safety: the real P9 / P10 roots are READ ONLY (manifested before and after every stage). No network (in-process trap
plus the runtime's own guard). No credentials (JQUANTS_* is removed from this process before anything else and never
read). No J-Quants. The repository must be at the accepted HEAD and clean; it is never pulled, fetched, checked out,
reset, cleaned or stashed. Evidence is never deleted; on PASS the validation root is moved (not deleted) into the
archive under D:\\p12_a6_work. Only tasks under \\Compass\\P12\\a6-validation\\ are ever registered or removed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_CREDENTIAL_VARIABLES_REMOVED = sorted(name for name in os.environ if name.startswith("JQUANTS_"))
for _name in _CREDENTIAL_VARIABLES_REMOVED:
    os.environ.pop(_name, None)                                                           # value never read, never printed

# ------------------------------------------------------------------ fixed contract (A6 gate)

EXPECTED_HEAD = "e390cddff9101541d16ba308a15d9ad1df3ca7b7"
P11_FROZEN_ANCHOR = "43c0b856d41efed397de213a1a06178c5e97ab10"
DEFAULT_REPO = Path(r"D:\daily-market-brief\daily-market-brief")
DEFAULT_P9_ROOT = Path(r"D:\p9_a5_private")
DEFAULT_P10_ROOT = Path(r"D:\p10_a5_private")
DEFAULT_P12_ROOT = Path(r"D:\p12_a6_private")
DEFAULT_WORK = Path(r"D:\p12_a6_work")
SCHEDULE_ID = "a6-validation"
CALENDAR_ID = "a6-calendar"
TASK_NAMESPACE = "\\Compass\\P12"
TASK_PREFIX = f"{TASK_NAMESPACE}\\{SCHEDULE_ID}\\"
TASK_FOLDERS = ("\\Compass", "\\Compass\\P12", f"{TASK_NAMESPACE}\\{SCHEDULE_ID}")
REQUIRED_TIMEZONE = "Tokyo Standard Time"
TOKYO = timezone(timedelta(hours=9), "Asia/Tokyo")
STAGES = ("preflight", "authority", "manual", "install", "taskrun", "duplicate", "recovery", "skips", "remove", "verify")
ELIGIBLE_LATE_WINDOW = 21600                                                                # 6 h: the whole validation fits inside
PREFLIGHT_TESTS = ("tests/intelligence/test_automation_boundary.py", "tests/intelligence/test_automation_models.py",
                   "tests/intelligence/test_automation_ledger.py", "tests/intelligence/test_automation_preconditions.py",
                   "tests/intelligence/test_automation_executor.py", "tests/intelligence/test_automation_ledger_store.py",
                   "tests/intelligence/test_automation_transaction.py", "tests/intelligence/test_automation_locks.py",
                   "tests/intelligence/test_automation_recovery.py", "tests/intelligence/test_automation_scheduler.py",
                   "tests/intelligence/test_screener_intelligence_boundary.py", "tests/intelligence/test_watchlist_thesis_boundary.py",
                   "tests/intelligence/test_personal_intelligence_boundary.py", "tests/intelligence/test_personal_ui_boundary.py")
CLI_MODULE = "src.intelligence.automation.run_cli"
TASK_RUN_TIMEOUT_SECONDS = 300
CHILD_TIMEOUT_SECONDS = 900
XML_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
SYSTEM_SIDS = ("S-1-5-18", "S-1-5-19", "S-1-5-20")
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_REPORT_FORBIDDEN = re.compile(r"(?i)\b[a-z]:\\|/|\d{4}-\d{2}-\d{2}")                    # drive paths, posix paths, dates never in reports


class Fail(Exception):
    """Safe failure code (never a path, value or exception text)."""


class GuardTripped(Exception):
    pass


# ------------------------------------------------------------------ report stream (stdout + work copy)


class Reporter:
    def __init__(self) -> None:
        self.copy = None
        self.lines = []

    def attach(self, work: Path) -> None:
        if work.is_dir():
            self.copy = work / "a6_report.txt"

    def __call__(self, line: str) -> None:
        body = line.split(" ", 1)
        head = body[0]
        tail = body[1] if len(body) > 1 else ""
        if _REPORT_FORBIDDEN.search(tail.replace(TASK_PREFIX, "").replace(TASK_NAMESPACE, "")):
            tail = "<redacted>"                                                             # defensive: never print a path or a date
        text = f"REPORT: {head} {tail}".rstrip()
        self.lines.append(text)
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
        if self.copy is not None:
            with self.copy.open("a", encoding="utf-8") as handle:
                handle.write(text + "\n")


report = Reporter()

# ------------------------------------------------------------------ in-process zero-network trap (loopback allowed)

_HITS = []
LOOPBACK = ("127.0.0.1", "localhost", "::1", "", None)


def _loopback(address) -> bool:
    host = address[0] if isinstance(address, (tuple, list)) and address else address
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    return host in LOOPBACK or (isinstance(host, str) and host.split("%", 1)[0] in LOOPBACK)


def install_network_trap() -> None:
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_create, real_getaddrinfo = socket.create_connection, socket.getaddrinfo

    def connect(sock, address):
        if not _loopback(address):
            _HITS.append("connect")
            raise GuardTripped()
        return real_connect(sock, address)

    def connect_ex(sock, address):
        if not _loopback(address):
            _HITS.append("connect_ex")
            raise GuardTripped()
        return real_connect_ex(sock, address)

    def create_connection(address, *args, **kwargs):
        if not _loopback(address):
            _HITS.append("create_connection")
            raise GuardTripped()
        return real_create(address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        if not _loopback(host):
            _HITS.append("getaddrinfo")
            raise GuardTripped()
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    socket.create_connection, socket.getaddrinfo = create_connection, getaddrinfo


# ------------------------------------------------------------------ configuration (fixed roots; overrides exist only for the Linux self-test)


class Config:
    def __init__(self, repo: Path, p9: Path, p10: Path, p12: Path, work: Path) -> None:
        self.repo, self.p9, self.p10, self.p12, self.work = repo, p9, p10, p12, work
        self.interpreter = sys.executable

    @property
    def private_dir(self) -> Path:
        return self.work / "private"

    @property
    def evidence_dir(self) -> Path:
        return self.work / "evidence"


CFG = Config(DEFAULT_REPO, DEFAULT_P9_ROOT, DEFAULT_P10_ROOT, DEFAULT_P12_ROOT, DEFAULT_WORK)
IS_WINDOWS = sys.platform == "win32"


def private_log(text: str) -> None:
    if CFG.work.is_dir():
        with (CFG.work / "a6_private.log").open("a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")


def save_evidence(stage: str, data: dict) -> None:
    CFG.evidence_dir.mkdir(parents=True, exist_ok=True)
    (CFG.evidence_dir / f"{stage}.json").write_bytes(json.dumps(data, sort_keys=True, indent=1, default=str).encode("utf-8"))


# ------------------------------------------------------------------ state (work directory only)


def state_file() -> Path:
    return CFG.work / "a6_state.json"


def load_state() -> dict:
    path = state_file()
    return json.loads(path.read_bytes().decode("utf-8")) if path.is_file() else {"done": [], "failed": None}


def save_state(state: dict) -> None:
    state_file().write_bytes(json.dumps(state, sort_keys=True, indent=1).encode("utf-8"))


def mark_done(state: dict, stage: str) -> None:
    if stage not in state["done"]:
        state["done"].append(stage)
    save_state(state)


# ------------------------------------------------------------------ root manifests (bytes + mtimes; P9 / P10 are READ ONLY)


def _sha256_file(path: Path) -> str:
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
            info = os.lstat(path)
            key = path.relative_to(root).as_posix()
            entries[("L:" if stat.S_ISLNK(info.st_mode) else "F:") + key] = (
                [info.st_mtime_ns] if stat.S_ISLNK(info.st_mode) else [info.st_size, _sha256_file(path), info.st_mtime_ns])
    return entries


def capture_or_verify(root: Path, code: str) -> None:
    path = CFG.private_dir / f"{code.lower()}_manifest.json"
    current = manifest(root, code)
    if not path.is_file():
        CFG.private_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(current, sort_keys=True).encode("utf-8"))
        report(f"{code}_MANIFEST_CAPTURED FILES={sum(1 for k in current if k.startswith('F:'))}")
        return
    if json.loads(path.read_bytes().decode("utf-8")) != current:
        raise Fail(f"{code}_MUTATED")


def verify_roots(label: str) -> None:
    capture_or_verify(CFG.p9, "P9")
    capture_or_verify(CFG.p10, "P10")
    report(f"ROOTS_UNCHANGED_OK {label}")


def tree_bytes(root: Path) -> dict:
    """Byte snapshot of every regular file under root (evidence must be byte-identical after a refusal)."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            out[path.relative_to(root).as_posix()] = _sha256_file(path)
    return out


# ------------------------------------------------------------------ child processes (clean environment; UTF-8)


def child_environment() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JQUANTS_")}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_command(argv, *, cwd=None, timeout=CHILD_TIMEOUT_SECONDS, input_bytes=None):
    try:
        completed = subprocess.run(list(argv), cwd=None if cwd is None else str(cwd), env=child_environment(), capture_output=True,
                                   check=False, timeout=timeout, input=input_bytes)
    except (OSError, subprocess.SubprocessError):
        return None, b"", b""
    return completed.returncode, completed.stdout, completed.stderr


def decode_console(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        import locale
        return data.decode(locale.getpreferredencoding(False) or "cp1252", "replace")


def git(*args: str) -> str:
    code, out, err = run_command(["git", "-C", str(CFG.repo), *args], timeout=120)
    if code is None:
        raise Fail("GIT_UNAVAILABLE")
    if code != 0:
        private_log(f"git {' '.join(args)} rc={code}\n{decode_console(err)}")
        raise Fail("GIT_FAILED")
    return out.decode("utf-8", "replace")


def check_repo() -> None:
    if git("rev-parse", "--verify", "HEAD").strip() != EXPECTED_HEAD:
        raise Fail("REPO_HEAD_MISMATCH")
    if git("status", "--porcelain", "--untracked-files=all").strip():
        raise Fail("REPO_NOT_CLEAN")


def cli(*args: str, timeout: int = CHILD_TIMEOUT_SECONDS):
    """Run the real P12 CLI as a child process (cwd = repo). Returns (exit code, REPORT lines)."""
    code, out, err = run_command([CFG.interpreter, "-m", CLI_MODULE, *args], cwd=CFG.repo, timeout=timeout)
    text = out.decode("utf-8", "replace")
    private_log(f"cli {args[0]} rc={code}\n{text}{err.decode('utf-8', 'replace')}")
    if code is None:
        raise Fail("CLI_CHILD_UNAVAILABLE")
    lines = [line[len("REPORT: "):] for line in text.splitlines() if line.startswith("REPORT: ")]
    if any(not line.startswith("REPORT: ") for line in text.splitlines() if line.strip()):
        raise Fail("CLI_STDOUT_NOT_REPORT_ONLY")
    return code, lines


def cli_scheduler(*args: str):
    """scheduler-install / -remove / -status through the real CLI (seam for the non-Windows self-test)."""
    return cli(*args)


def roots_args():
    return ["--private-root", str(CFG.p12), "--p9-root", str(CFG.p9), "--p10-root", str(CFG.p10), "--repo-root", str(CFG.repo),
            "--runtime-root", str(CFG.repo)]


def report_value(lines, key: str, default=None):
    for line in lines:
        for token in line.split(" "):
            if token.startswith(key + "="):
                return token[len(key) + 1:]
    return default


def first_token(lines, prefix: str):
    for line in lines:
        if line.startswith(prefix):
            return line
    return None


# ------------------------------------------------------------------ Windows operations (schtasks / tzutil / PowerShell) — seams for the self-test


def schtasks(*args: str):
    code, out, err = run_command(["schtasks", *args], timeout=120)
    private_log(f"schtasks {' '.join(args)} rc={code}\n{decode_console(out)}{decode_console(err)}")
    return code, decode_console(out)


def system_timezone():
    code, out, _ = run_command(["tzutil", "/g"], timeout=60)
    if code != 0:
        return None
    text = decode_console(out).strip()
    return text if 0 < len(text) < 80 and text.isprintable() else None


def powershell(script: str):
    code, out, err = run_command(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=120)
    private_log(f"powershell rc={code}\n{decode_console(out)}{decode_console(err)}")
    return code, decode_console(out)


def task_folder_present(folder: str):
    """True / False / None (unknown) via the Task Scheduler COM API (empty folders are invisible to schtasks)."""
    code, out = powershell("$s = New-Object -ComObject Schedule.Service; $s.Connect(); "
                           f"try {{ $null = $s.GetFolder('{folder}'); 'PRESENT' }} catch {{ 'ABSENT' }}")
    if code != 0:
        return None
    text = out.strip().splitlines()[-1].strip() if out.strip() else ""
    return True if text == "PRESENT" else False if text == "ABSENT" else None


def delete_empty_task_folder(folder: str) -> bool:
    parent, _, name = folder.rpartition("\\")
    parent = parent or "\\"
    code, out = powershell("$s = New-Object -ComObject Schedule.Service; $s.Connect(); "
                           f"$f = $s.GetFolder('{folder}'); if ($f.GetTasks(1).Count -eq 0 -and $f.GetFolders(0).Count -eq 0) "
                           f"{{ $s.GetFolder('{parent}').DeleteFolder('{name}', 0); 'DELETED' }} else {{ 'NOT_EMPTY' }}")
    return code == 0 and out.strip().endswith("DELETED")


def all_task_names() -> set:
    code, out = schtasks("/Query", "/FO", "CSV", "/NH")
    if code != 0:
        raise Fail("SCHTASKS_QUERY_FAILED")
    names = set()
    for row in csv.reader(io.StringIO(out)):
        if row and row[0].startswith("\\"):
            names.add(row[0])
    return names


def task_query_verbose(name: str):
    """(present, columns dict or None). Column names are English only on English Windows; the ledger is the authority anyway."""
    code, out = schtasks("/Query", "/TN", name, "/FO", "CSV", "/V")
    if code != 0:
        return False, None
    rows = list(csv.DictReader(io.StringIO(out)))
    return True, (rows[-1] if rows else None)


def task_xml_text(name: str):
    code, out = schtasks("/Query", "/TN", name, "/XML")
    return out if code == 0 else None


# ------------------------------------------------------------------ runtime import (the checkout itself; read-only)


class Runtime:
    def __init__(self) -> None:
        repo = CFG.repo
        if not (repo / "src" / "intelligence" / "automation" / "run_cli.py").is_file():
            raise Fail("REPO_LAYOUT_UNEXPECTED")
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from src.intelligence.automation import (execution_request, frozen_anchors, head_checkpoint, holiday_calendar, ledger_commit,
                                                 ledger_store, operational_lock, preconditions, process_probe, run_cli, run_identity,
                                                 schedule_model, status_store, task_definition)
        from tests.intelligence import phase12_runtime_registry as registry
        self.execution_request, self.frozen_anchors, self.head_checkpoint = execution_request, frozen_anchors, head_checkpoint
        self.holiday_calendar, self.ledger_commit, self.ledger_store = holiday_calendar, ledger_commit, ledger_store
        self.operational_lock, self.preconditions, self.process_probe = operational_lock, preconditions, process_probe
        self.run_cli, self.run_identity, self.schedule_model = run_cli, run_identity, schedule_model
        self.status_store, self.task_definition, self.registry = status_store, task_definition, registry
        if self.frozen_anchors.P11_FROZEN_ANCHOR != P11_FROZEN_ANCHOR:
            raise Fail("P11_ANCHOR_DECLARATION_MISMATCH")
        self.probe = process_probe.ProcessProbe()

    def clock(self):
        return datetime.now(timezone.utc).replace(microsecond=0)

    def ledger_state(self, *, strict: bool):
        """Verified ledger state read under the ledger lock (exactly what the runtime does)."""
        ledger = self.ledger_commit.LockedLedger(CFG.p12, probe=self.probe, clock=self.clock)
        return ledger.read_verified("0" * 64, allow_stale_checkpoint=not strict)

    def ledger_state_unlocked_retry(self):
        """Read-only poll while another process may be committing (transient states are retried)."""
        last = None
        for _ in range(5):
            try:
                return self.ledger_store.LedgerStore(CFG.p12).open_verified(allow_stale_checkpoint=True)
            except Exception as exc:  # noqa: BLE001 - transient while a child commits
                last = exc
                time.sleep(0.3)
        raise Fail("LEDGER_READ_UNSTABLE") from last


RT = None


def runtime() -> Runtime:
    global RT
    if RT is None:
        RT = Runtime()
    return RT


# ------------------------------------------------------------------ synthetic validation schedule (non-production; bound once)


def tokyo_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(TOKYO).replace(second=0, microsecond=0)


def hhmm(instant: datetime) -> str:
    return f"{instant.hour:02d}:{instant.minute:02d}"


def build_plan(start_local: datetime) -> dict:
    """Slot times relative to the start instant. Stored privately (dates / times are never printed)."""
    minus = lambda minutes: hhmm(start_local - timedelta(minutes=minutes))                    # noqa: E731
    today = start_local.date()
    saturday = today
    while saturday.weekday() != 5:
        saturday -= timedelta(days=1)
    holiday = today - timedelta(days=10)
    while holiday.weekday() >= 5:
        holiday -= timedelta(days=1)
    all_days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    slots = {
        "disabled": dict(local_time=minus(1), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=False),
        "dup": dict(local_time=minus(1), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=True),
        "manual": dict(local_time=minus(2), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=True),
        "missed": dict(local_time=minus(3), late=60, readiness=True, enabled=True),
        "nbd": dict(local_time="09:00", late=3600, readiness=False, enabled=True),
        "notdue": dict(local_time="23:59", late=0, readiness=True, enabled=True),
        "rec1": dict(local_time=minus(1), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=True),
        "rec2": dict(local_time=minus(1), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=True),
        "rec3": dict(local_time=minus(1), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=True),
        "rec4": dict(local_time=minus(1), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=True),
        "rec5": dict(local_time=minus(1), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=True),
        "sched": dict(local_time=minus(1), late=ELIGIBLE_LATE_WINDOW, readiness=True, enabled=True),
    }
    for slot in slots.values():
        slot["weekday_mask"] = all_days
    return {"start_local": start_local.isoformat(), "today": today.isoformat(), "saturday": saturday.isoformat(),
            "holiday": holiday.isoformat(), "slots": slots}


def schedule_documents(rt: Runtime, plan: dict, created_at: str):
    sm, hc = rt.schedule_model, rt.holiday_calendar
    calendar = hc.HolidayCalendar(calendar_id=CALENDAR_ID, version=1, dates=(plan["holiday"],))
    slots = tuple(sm.ScheduleSlot(slot_id=slot_id, local_time=spec["local_time"], weekday_mask=tuple(spec["weekday_mask"]),
                                  late_window_seconds=spec["late"], readiness_on_non_business_day=spec["readiness"], enabled=spec["enabled"])
                  for slot_id, spec in sorted(plan["slots"].items()))
    schedule = sm.AutomationSchedule(schedule_id=SCHEDULE_ID, version=1, timezone=sm.TIMEZONE_V1, enabled=True, slots=slots,
                                     holiday_calendar_ref=calendar.reference(), created_at=created_at, supersedes=None)
    return schedule, calendar


def scheduled_for_of(plan: dict, slot_id: str, day: date = None) -> datetime:
    spec = plan["slots"][slot_id]
    local_day = date.fromisoformat(plan["today"]) if day is None else day
    hour, minute = int(spec["local_time"][:2]), int(spec["local_time"][3:])
    return datetime(local_day.year, local_day.month, local_day.day, hour, minute, tzinfo=TOKYO)


def utc_z(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_of(rt: Runtime, plan: dict, slot_id: str, attempt: int = 1) -> str:
    identity = rt.run_identity.RunIdentity(schedule_id=SCHEDULE_ID, slot_id=slot_id, scheduled_for=scheduled_for_of(plan, slot_id),
                                           runtime_anchor=EXPECTED_HEAD, attempt=attempt)
    return identity.run_id


def request_of(rt: Runtime, plan: dict, slot_id: str):
    schedule, calendar = schedule_documents(rt, plan, plan["created_at"])
    scheduled_for = scheduled_for_of(plan, slot_id)
    as_of = scheduled_for.date()
    session = calendar.last_business_day_on_or_before(as_of) or as_of
    return rt.execution_request.AutomationExecutionRequest(schedule_id=SCHEDULE_ID, slot_id=slot_id, scheduled_for=scheduled_for,
                                                           as_of_date=as_of, session_date=session, runtime_anchor=EXPECTED_HEAD, attempt=1,
                                                           operator="scheduler", schedule_digest=schedule.content_digest,
                                                           readiness_only=not calendar.is_business_day(as_of))


def task_name(slot_id: str) -> str:
    return TASK_PREFIX + slot_id


# ------------------------------------------------------------------ ledger helpers


def records_of(state, run_id: str):
    return [r for r in state.records if r.run_id == run_id]


def state_counts(state) -> dict:
    counts = {}
    for run_state in state.run_states.values():
        counts[run_state.value] = counts.get(run_state.value, 0) + 1
    return counts


def expect_scheduled(lines, slot_id: str, outcome: str, code: str, exit_code: int, actual_exit: int, label: str) -> None:
    head = first_token(lines, "SCHEDULED_RUN ")
    expected = f"SCHEDULED_RUN SLOT={slot_id} OUTCOME={outcome} CODE={code}"
    if head != expected or actual_exit != exit_code or first_token(lines, "EXIT=") != f"EXIT={exit_code}":
        report(f"{label}_UNEXPECTED {head or 'NO_REPORT'} RC={actual_exit}")
        raise Fail(f"{label}_FAILED")


def scheduled_run(slot_id: str, *, selection_clock_at: str = None):
    args = ["scheduled-run", "--slot-id", slot_id, *roots_args()]
    if selection_clock_at is not None:
        args += ["--selection-clock-at", selection_clock_at]
    return cli(*args)


# ------------------------------------------------------------------ stage 0: preflight


def stage_preflight(state: dict) -> None:
    evidence = {}
    if sys.version_info < (3, 9):
        raise Fail("PYTHON_TOO_OLD")
    report(f"PYTHON_OK {sys.version_info.major}.{sys.version_info.minor}")
    if IS_WINDOWS:
        report("WINDOWS_OK")
    else:
        report("WINDOWS_OK PLATFORM=SELFTEST")                                               # only the Linux self-test reaches here
    report(f"CREDENTIAL_ENV_CLEAN_OK REMOVED={len(_CREDENTIAL_VARIABLES_REMOVED)}")
    zone = system_timezone()
    if zone != REQUIRED_TIMEZONE:
        raise Fail("TIMEZONE_NOT_TOKYO")
    offset = datetime.now().astimezone().utcoffset()
    if offset != timedelta(hours=9):
        raise Fail("LOCAL_OFFSET_NOT_PLUS_9")
    report("TIMEZONE_OK")
    local = tokyo_now()
    if (local.hour == 23 and local.minute >= 40) or (local.hour == 0 and local.minute < 20):
        raise Fail("REFUSED_NEAR_MIDNIGHT_RETRY_LATER")
    if not CFG.work.is_dir():
        raise Fail("WORK_DIR_MISSING")
    CFG.private_dir.mkdir(parents=True, exist_ok=True)
    CFG.evidence_dir.mkdir(parents=True, exist_ok=True)
    report("WORK_DIR_OK")
    for root, code in ((CFG.p9, "P9"), (CFG.p10, "P10")):
        if not root.is_dir():
            raise Fail(f"{code}_ROOT_MISSING")
    if CFG.p12.exists() and any(CFG.p12.iterdir()):
        raise Fail("P12_ROOT_NOT_EMPTY_USE_ARCHIVE_PREVIOUS")
    if not CFG.p12.parent.is_dir():
        raise Fail("P12_ROOT_PARENT_MISSING")
    report("P12_ROOT_FRESH_OK")
    if not CFG.repo.is_dir():
        raise Fail("REPO_MISSING")
    check_repo()
    report("REPO_HEAD_OK")
    report("REPO_CLEAN_OK")
    rt = runtime()
    report(f"INTERPRETER_VENV={'YES' if sys.prefix != sys.base_prefix else 'NO'}")
    if rt.preconditions.frozen_p11_drift(CFG.repo):
        raise Fail("P11_FROZEN_DRIFT")
    report("P11_ANCHOR_OK FILES=12")
    check_p12_pins(rt)
    capture_or_verify(CFG.p9, "P9")
    capture_or_verify(CFG.p10, "P10")
    report("ROOTS_UNCHANGED_OK before")
    probe_checks(rt, evidence)
    tests_ok = run_preflight_tests()
    evidence["preflight_tests"] = tests_ok
    check_repo()
    report("REPO_CLEAN_AFTER_TESTS_OK")
    verify_roots("preflight")
    save_evidence("preflight", evidence)
    mark_done(state, "preflight")


def check_p12_pins(rt: Runtime) -> None:
    reg = rt.registry
    reopened_a4 = set(reg.PHASE12_A4_REOPENED_IN_A5) | set(getattr(reg, "PHASE12_A4_REOPENED_IN_A6", ()))   # A6 remediation: lock writer
    groups = ((reg.P12_A1, reg.PHASE12_A1_RUNTIME), (reg.P12_A2, reg.PHASE12_A2_RUNTIME),
              (reg.P12_A3, tuple(p for p in reg.PHASE12_A3_RUNTIME if p not in reg.PHASE12_A3_REOPENED_IN_A4)),
              (reg.P12_A4, tuple(p for p in reg.PHASE12_A4_RUNTIME + reg.PHASE12_A3_REOPENED_IN_A4 if p not in reopened_a4)))
    checked = 0
    for pin, files in groups:
        for relative in files:
            expected = git("rev-parse", f"{pin}:{relative}").strip()
            actual = git("hash-object", "--", relative).strip()
            if expected != actual:
                raise Fail("P12_PIN_DRIFT")
            checked += 1
    report(f"P12_PINS_OK FILES={checked}")


PROBE_TIMINGS = {"alive_ms": [], "identity_ms": [], "alive_none": 0, "identity_none": 0}


def timed_alive(probe, pid: int):
    started = time.monotonic()
    value = probe.is_alive(pid)
    PROBE_TIMINGS["alive_ms"].append(int((time.monotonic() - started) * 1000))
    PROBE_TIMINGS["alive_none"] += 1 if value is None else 0
    return value


def timed_identity(probe, pid: int):
    started = time.monotonic()
    value = probe.identity(pid)
    PROBE_TIMINGS["identity_ms"].append(int((time.monotonic() - started) * 1000))
    PROBE_TIMINGS["identity_none"] += 1 if value is None else 0
    return value


def report_probe_timings(label: str) -> None:
    alive_ms, identity_ms = PROBE_TIMINGS["alive_ms"], PROBE_TIMINGS["identity_ms"]
    report(f"PROBE_TIMING_MS {label} ALIVE_CALLS={len(alive_ms)} ALIVE_MAX={max(alive_ms) if alive_ms else 0} "
           f"IDENTITY_CALLS={len(identity_ms)} IDENTITY_MAX={max(identity_ms) if identity_ms else 0} "
           f"ALIVE_NONE={PROBE_TIMINGS['alive_none']} IDENTITY_NONE={PROBE_TIMINGS['identity_none']} RUNTIME_TIMEOUT_S=15")


def lock_live_facts(rt: Runtime, target: Path, classification: dict) -> str:
    """Safe facts behind one classification of a lock held by THIS process (no pid, path, digest or raw probe text)."""
    ol, probe = rt.operational_lock, rt.probe
    try:
        record = ol.read_lock(target)
    except Exception:  # noqa: BLE001 - malformed is itself a fact
        return "RECORD=MALFORMED"
    if record is None:
        return "RECORD=ABSENT"
    alive = timed_alive(probe, record.pid)
    identity_now = timed_identity(probe, record.pid)
    boot_now = probe.boot_marker()
    match = "NA" if record.process_identity is None or identity_now is None else ("YES" if identity_now == record.process_identity else "NO")
    return (f"CLASS={classification['lock_class']} PID_IS_SELF={'YES' if record.pid == os.getpid() else 'NO'} "
            f"RECORD_IDENTITY={'YES' if record.process_identity else 'NO'} RECORD_BOOT={'YES' if record.boot_marker else 'NO'} "
            f"ALIVE_NOW={alive} IDENTITY_NOW={'YES' if identity_now else 'NO'} BOOT_NOW={'YES' if boot_now else 'NO'} IDENTITY_MATCH={match}")


def probe_checks(rt: Runtime, evidence: dict) -> None:
    """Helper-owned child processes: liveness / identity / lock semantics on this machine."""
    probe = rt.probe
    child = subprocess.Popen([CFG.interpreter, "-c", "import time; time.sleep(600)"], env=child_environment(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        alive = timed_alive(probe, child.pid)
        alive_self = timed_alive(probe, os.getpid())
        identity_child = timed_identity(probe, child.pid)
        identity_self = timed_identity(probe, os.getpid())
        boot = probe.boot_marker()
        report(f"PROBE_FACTS CHILD_ALIVE={alive} SELF_ALIVE={alive_self} CHILD_IDENTITY={'YES' if identity_child else 'NO'} "
               f"SELF_IDENTITY={'YES' if identity_self else 'NO'}")
        if alive is not True:
            raise Fail("PROBE_LIVE_CHILD_NOT_ALIVE")
        if alive_self is not True:
            raise Fail("PROBE_SELF_NOT_ALIVE")
        if identity_child is None or identity_self is None or not _HEX64.match(identity_child) or not _HEX64.match(identity_self):
            raise Fail("PROBE_IDENTITY_UNAVAILABLE")
        if identity_child == identity_self:
            raise Fail("PROBE_IDENTITY_NOT_DISTINCT")
        if timed_identity(probe, os.getpid()) != identity_self:
            raise Fail("PROBE_IDENTITY_NOT_STABLE")
        report(f"BOOT_MARKER={'PRESENT' if boot else 'ABSENT'}")
        dead_pid = child.pid
    finally:
        child.kill()
        child.wait(timeout=60)
    time.sleep(1.0)
    if timed_alive(probe, dead_pid) is not False:
        raise Fail("PROBE_DEAD_CHILD_STILL_ALIVE")
    report("PROCESS_PROBE_OK")
    lock_root = CFG.private_dir / "probe_root" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")   # fresh per invocation: a failed
    lock_root.mkdir(parents=True, exist_ok=False)                                             # run's lock stays as evidence, never reused
    ol = rt.operational_lock
    run_id = "a" * 64
    held = ol.acquire_lock(lock_root, "RUN", run_id, probe=probe, clock_instant=rt.clock())
    target = ol.run_lock_file(lock_root, run_id)
    if not target.is_file():
        raise Fail("LOCK_FILE_NOT_CREATED")
    try:
        ol.acquire_lock(lock_root, "RUN", run_id, probe=probe, clock_instant=rt.clock())
        raise Fail("LOCK_NOT_EXCLUSIVE")
    except ol.LockHeld:
        pass
    live = ol.classify_lock(target, probe=probe)
    report(f"LOCK_LIVE_ACTUAL={live['lock_class']}")
    report("LOCK_LIVE_FACTS " + lock_live_facts(rt, target, live))
    if live["lock_class"] != "LOCK_LIVE":
        for attempt in range(3):                                                             # intermittent? classify again
            again = ol.classify_lock(target, probe=probe)
            report(f"LOCK_LIVE_RETRY {attempt + 1} CLASS={again['lock_class']}")
        report_probe_timings("at_failure")
        raise Fail("LOCK_LIVE_NOT_CLASSIFIED")
    # open-file semantics: a child holding the lock file open (Windows refuses unlink; POSIX allows it) — observation only
    holder = subprocess.Popen([CFG.interpreter, "-c", "import sys, time; h = open(sys.argv[1], 'rb'); time.sleep(600)", str(target)],
                              env=child_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        try:
            os.unlink(target)
            unlink_while_open = "ALLOWED"
        except OSError:
            unlink_while_open = "REFUSED"
    finally:
        holder.kill()
        holder.wait(timeout=60)
    report(f"OPEN_FILE_UNLINK={unlink_while_open}")
    if target.exists():
        held.release()
    if target.exists():
        raise Fail("LOCK_RELEASE_FAILED")
    me = os.getpid()
    cases = (("LOCK_STALE_DEAD", ol.LockRecord("RUN", run_id, dead_pid, "b" * 64, None, "2000-01-01T00:00:00Z", None, 1)),
             ("LOCK_STALE_PID_REUSED", ol.LockRecord("RUN", run_id, me, "c" * 64, None, "2000-01-01T00:00:00Z", None, 1)),
             ("LOCK_UNKNOWN_PROVENANCE", ol.LockRecord("RUN", run_id, me, None, None, "2000-01-01T00:00:00Z", None, 1)),
             ("LOCK_MALFORMED", None))
    for expected, record in cases:
        target.write_bytes(record.to_bytes() if record is not None else b"{not json\n")
        got = ol.classify_lock(target, probe=probe)["lock_class"]
        if got != expected:
            report(f"LOCK_CLASS_MISMATCH EXPECTED={expected} GOT={got}")
            raise Fail("LOCK_CLASSIFICATION_FAILED")
        target.unlink()
    # O_EXCL atomicity: two children race for the same lock path, repeatedly; exactly one must win each round
    racer = ("import os, sys\n"
             "try:\n    fd = os.open(sys.argv[1], os.O_CREAT | os.O_EXCL | os.O_WRONLY)\n    os.close(fd)\n    print('WON')\n"
             "except FileExistsError:\n    print('LOST')\n")
    rounds, wins = 10, 0
    for i in range(rounds):
        path = lock_root / f"race.{i}.lock"
        children = [subprocess.Popen([CFG.interpreter, "-c", racer, str(path)], env=child_environment(), stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL) for _ in range(2)]
        outputs = [c.communicate(timeout=120)[0].decode("ascii", "replace").strip() for c in children]
        if sorted(outputs) != ["LOST", "WON"]:
            raise Fail("O_EXCL_NOT_ATOMIC")
        wins += 1
        path.unlink()
    report(f"O_EXCL_ATOMIC_OK ROUNDS={wins}")
    report("LOCK_PORTABILITY_OK")
    report_probe_timings("preflight")
    evidence.update(boot_marker_present=bool(boot), unlink_while_open=unlink_while_open)


def run_preflight_tests() -> dict:
    code, out, err = run_command([CFG.interpreter, "-m", "pytest", "-q", "-p", "no:cacheprovider", *PREFLIGHT_TESTS], cwd=CFG.repo,
                                 timeout=3600)
    text = out.decode("utf-8", "replace") + err.decode("utf-8", "replace")
    (CFG.private_dir / "a6_preflight_pytest.log").write_bytes(text.encode("utf-8", "replace"))
    if code != 0:
        for line in text.splitlines():
            if line.startswith("FAILED ") or line.startswith("ERROR "):
                report("FAILED_TEST " + line.split(" ")[1].split("::")[-1])                   # test ids only (synthetic data)
        raise Fail("PREFLIGHT_TESTS_FAILED")
    summary = [line for line in text.splitlines() if " passed" in line]
    tail = summary[-1].strip("= ").split(" in ")[0] if summary else "?"
    report("PREFLIGHT_TESTS_OK " + tail)
    return {"summary": tail}


# ------------------------------------------------------------------ stage 1: authority (real CLI; synthetic non-production schedule)


def stage_authority(state: dict) -> None:
    rt = runtime()
    verify_roots("authority before")
    start = tokyo_now()
    plan = build_plan(start)
    plan["created_at"] = utc_z(datetime.now(timezone.utc).replace(microsecond=0))
    schedule, calendar = schedule_documents(rt, plan, plan["created_at"])
    (CFG.private_dir / "schedule.json").write_bytes((schedule.to_json() + "\n").encode("utf-8"))
    (CFG.private_dir / "holiday_calendar.json").write_bytes((calendar.to_json() + "\n").encode("utf-8"))
    code, lines = cli("write-schedule", "--file", str(CFG.private_dir / "schedule.json"), "--private-root", str(CFG.p12))
    digest = report_value(lines, "DIGEST")
    if code != 0 or digest != schedule.content_digest:
        raise Fail("SCHEDULE_AUTHORITY_WRITE_FAILED")
    report(f"SCHEDULE_AUTHORITY_OK SLOTS={len(schedule.slots)} DIGEST={digest[:16]}")
    code, lines = cli("write-calendar", "--file", str(CFG.private_dir / "holiday_calendar.json"), "--private-root", str(CFG.p12))
    if code != 0 or report_value(lines, "DIGEST") != calendar.content_digest:
        raise Fail("CALENDAR_AUTHORITY_WRITE_FAILED")
    report("CALENDAR_AUTHORITY_OK HOLIDAYS=1")
    code, lines = cli("pin-runtime", "--private-root", str(CFG.p12), "--repo-root", str(CFG.repo))
    if code != 0 or report_value(lines, "ANCHOR") != EXPECTED_HEAD:
        raise Fail("RUNTIME_PIN_FAILED")
    report("RUNTIME_PIN_OK")
    if rt.run_cli.main(["scheduled-run", "--slot-id", "no-such-slot", *roots_args()], stdout=io.StringIO(), environment={}) != 7:
        raise Fail("UNKNOWN_SLOT_NOT_REFUSED")
    report("AUTHORITY_OK")
    state["plan"] = plan
    state["schedule_digest"] = schedule.content_digest
    save_state(state)
    verify_roots("authority after")
    save_evidence("authority", {"slots": sorted(plan["slots"]), "schedule_digest": schedule.content_digest,
                               "calendar_digest": calendar.content_digest})
    mark_done(state, "authority")


# ------------------------------------------------------------------ stage 2: manual run (in-process real CLI entry, under the network trap)


def stage_manual(state: dict) -> None:
    rt = runtime()
    plan = state["plan"]
    verify_roots("manual before")
    out = io.StringIO()
    environment = {k: v for k, v in os.environ.items()}
    code = rt.run_cli.main(["scheduled-run", "--slot-id", "manual", *roots_args()], stdout=out, environment=environment)
    lines = [line[len("REPORT: "):] for line in out.getvalue().splitlines()]
    private_log("manual in-process\n" + out.getvalue())
    expect_scheduled(lines, "manual", "SUCCEEDED", "RUN_SUCCEEDED", 0, code, "MANUAL_RUN")
    run_id = run_id_of(rt, plan, "manual")
    if first_token(lines, "RUN_ID=") != f"RUN_ID={run_id}":
        raise Fail("MANUAL_RUN_ID_MISMATCH")
    steps = [line for line in lines if line.startswith("STEP ")]
    if len(steps) != 5 or any(" OK" not in s for s in steps):
        raise Fail("MANUAL_STEPS_NOT_OK")
    ledger = rt.ledger_state(strict=True)
    mine = records_of(ledger, run_id)
    if [r.transition_to.value for r in mine] != ["PLANNED", "RUNNING", "SUCCEEDED"] or ledger.summary.record_count != 3:
        raise Fail("MANUAL_LEDGER_SHAPE")
    final = CFG.p12 / "runs" / run_id
    artifacts = sorted(p.name for p in final.iterdir()) if final.is_dir() else []
    if artifacts != ["digests.json", "evidence.json", "manifests.json", "readiness.json", "request.json", "snapshot.json",
                     "snapshot_metadata.json"]:
        raise Fail("MANUAL_ARTIFACTS_MISSING")
    if rt.status_store.classify_status(CFG.p12, ledger) != "STATUS_OK":
        raise Fail("MANUAL_STATUS_STALE")
    if list((CFG.p12 / "locks").glob("*.lock")):
        raise Fail("MANUAL_LOCK_LEFT_BEHIND")
    metadata = json.loads((final / "snapshot_metadata.json").read_bytes().decode("utf-8"))
    readiness = json.loads((final / "readiness.json").read_bytes().decode("utf-8"))
    if readiness.get("bind") != "127.0.0.1" or not readiness.get("api_matches_snapshot"):
        raise Fail("MANUAL_READINESS_UNEXPECTED")
    report(f"MANUAL_RUN_OK ENTRIES={metadata['entry_count']} FOCUS={metadata['focus_count']} MUTE={metadata['mute_count']} "
           f"EXCLUDED={metadata['excluded_count']} UNMATCHED={metadata['unmatched_live_marks']}")
    report(f"LEDGER_OK RECORDS={ledger.summary.record_count}")
    report("STATUS_OK")
    report(f"IN_PROCESS_NETWORK_TRAPS={len(_HITS)}")
    if _HITS:
        raise Fail("NETWORK_ATTEMPTED")
    state["manual_counts"] = {k: metadata[k] for k in ("entry_count", "focus_count", "mute_count", "excluded_count", "unmatched_live_marks")}
    save_state(state)
    verify_roots("manual after")
    save_evidence("manual", {"run_id": run_id, "report": lines, "counts": state["manual_counts"]})
    mark_done(state, "manual")


# ------------------------------------------------------------------ stage 3: scheduler install (real schtasks; XML validation)


def xml_clauses(xml_text: str, slot_id: str) -> dict:
    ns = {"t": XML_NAMESPACE}
    root = ET.fromstring(xml_text.lstrip("\ufeff"))
    if root.tag != f"{{{XML_NAMESPACE}}}Task":
        raise Fail("TASK_XML_NAMESPACE")

    def text(path: str):
        node = root.find(path, ns)
        return None if node is None else (node.text or "").strip()

    exec_args = text("t:Actions/t:Exec/t:Arguments") or ""
    user_name = os.environ.get("USERNAME", "")
    checks = {
        "LOGON_INTERACTIVE": text("t:Principals/t:Principal/t:LogonType") == "InteractiveToken",
        "LEAST_PRIVILEGE": text("t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege",
        "NOT_SYSTEM": (text("t:Principals/t:Principal/t:UserId") or "") not in SYSTEM_SIDS,
        "IGNORE_NEW": text("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew",
        "START_WHEN_AVAILABLE": text("t:Settings/t:StartWhenAvailable") == "true",
        "WAKE_TO_RUN_FALSE": text("t:Settings/t:WakeToRun") == "false",
        "EXECUTION_TIME_LIMIT": text("t:Settings/t:ExecutionTimeLimit") == "PT30M",
        "NETWORK_NOT_REQUIRED": text("t:Settings/t:RunOnlyIfNetworkAvailable") == "false",
        "INTERPRETER": text("t:Actions/t:Exec/t:Command") == CFG.interpreter,
        "WORKING_DIR": text("t:Actions/t:Exec/t:WorkingDirectory") == str(CFG.repo),
        "SLOT_ARGUMENT": f"scheduled-run --slot-id {slot_id} " in exec_args + " ",
        "NO_SECRET": "JQUANTS" not in xml_text.upper() and root.find(".//t:Password", ns) is None,
        "NO_USERNAME": user_name == "" or user_name.lower() not in xml_text.lower(),
        "OWNER_MARKER": "P12_OWNED" in xml_text and text("t:RegistrationInfo/t:Author") == "P12",
        "URI": text("t:RegistrationInfo/t:URI") == task_name(slot_id),
    }
    return checks


def stage_install(state: dict) -> None:
    rt = runtime()
    plan = state["plan"]
    verify_roots("install before")
    before = all_task_names()
    if any(name.startswith(TASK_PREFIX) for name in before):
        raise Fail("A6_TASKS_ALREADY_PRESENT")
    folders_before = {folder: task_folder_present(folder) for folder in TASK_FOLDERS}
    state["tasks_before"] = sorted(before)
    state["folders_before"] = folders_before
    save_state(state)
    report("TASK_NAMESPACE_FREE_OK")
    code, lines = cli_scheduler("scheduler-install", *roots_args(), "--interpreter", CFG.interpreter)
    planned = [line for line in lines if line.startswith("SCHEDULER_TASK ")]
    if code != 0 or len(planned) != len(plan["slots"]) or first_token(lines, "SCHEDULER_PLAN ") != f"SCHEDULER_PLAN TASKS={len(planned)} APPLIED=NO":
        raise Fail("SCHEDULER_PLAN_FAILED")
    digests = {report_value([line], "SLOT"): report_value([line], "XML_DIGEST") for line in planned}
    if any(n.startswith(TASK_PREFIX) for n in all_task_names()):
        raise Fail("SCHEDULER_PLAN_REGISTERED_TASKS")
    report(f"SCHEDULER_PLAN_OK TASKS={len(planned)}")
    code, lines = cli_scheduler("scheduler-install", *roots_args(), "--interpreter", CFG.interpreter, "--apply")
    if code != 0 or first_token(lines, "SCHEDULER_INSTALLED ") != f"SCHEDULER_INSTALLED TASKS={len(planned)}":
        raise Fail("SCHEDULER_INSTALL_FAILED")
    state["installed"] = True
    save_state(state)
    after = all_task_names()
    added = after - before
    if added != {task_name(slot_id) for slot_id in plan["slots"]} or (before - after):
        report(f"TASK_SET_DELTA ADDED={len(added)} REMOVED={len(before - after)}")
        raise Fail("SCHEDULER_INSTALL_TASK_SET_MISMATCH")
    report(f"SCHEDULER_INSTALL_OK TASKS={len(added)}")
    clause_failures, locale_en = [], None
    for slot_id in sorted(plan["slots"]):
        on_disk = CFG.p12 / "scheduler" / f"{SCHEDULE_ID}.{slot_id}.xml"
        if not on_disk.is_file() or hashlib.sha256(on_disk.read_bytes()).hexdigest() != digests.get(slot_id):
            raise Fail("TASK_XML_ON_DISK_DIGEST_MISMATCH")
        raw = on_disk.read_bytes()
        if raw[:2] not in (b"\xff\xfe", b"\xfe\xff") or "\r\n" not in raw.decode("utf-16"):
            raise Fail("TASK_XML_NOT_UTF16_CRLF")
        xml_text = task_xml_text(task_name(slot_id))
        if xml_text is None:
            raise Fail("TASK_XML_QUERY_FAILED")
        checks = xml_clauses(xml_text, slot_id)
        clause_failures.extend(f"{slot_id}:{k}" for k, v in checks.items() if not v)
        present, columns = task_query_verbose(task_name(slot_id))
        if not present:
            raise Fail("TASK_VERBOSE_QUERY_FAILED")
        if locale_en is None:
            locale_en = columns is not None and "Last Result" in columns and "Scheduled Task State" in columns
    if clause_failures:
        for item in clause_failures:
            report(f"TASK_XML_CLAUSE_FAILED {item}")
        raise Fail("TASK_XML_CLAUSES_FAILED")
    report(f"TASK_XML_CLAUSES_OK TASKS={len(plan['slots'])} CLAUSES=15")
    report(f"SCHTASKS_CSV_LOCALE={'EN' if locale_en else 'NON_EN'}")
    state["csv_locale_en"] = bool(locale_en)
    code, lines = cli_scheduler("scheduler-status", "--private-root", str(CFG.p12))
    status_line = first_token(lines, "SCHEDULER_STATUS ") or ""
    expected_tasks = len(plan["slots"])
    if code != 0 or f"SCHEDULER_INSTALLED=True" not in status_line or f"INSTALLED_TASK_COUNT={expected_tasks}" not in status_line \
            or "NOT_OWNED_COUNT=0" not in status_line or "RECOVERY_REQUIRED=False" not in status_line:
        report(f"SCHEDULER_STATUS_UNEXPECTED {status_line}")
        raise Fail("SCHEDULER_STATUS_FAILED")
    enabled = report_value(lines, "ENABLED_TASK_COUNT")
    report(f"SCHEDULER_STATUS_OK INSTALLED={expected_tasks} ENABLED_TASKS={enabled} ENABLED_SLOTS={report_value(lines, 'ENABLED_SLOT_COUNT')}")
    save_state(state)
    verify_roots("install after")
    save_evidence("install", {"added": sorted(added), "folders_before": folders_before, "csv_locale_en": bool(locale_en),
                              "status_line": status_line})
    mark_done(state, "install")


# ------------------------------------------------------------------ stage 4: run started by Task Scheduler


def wait_for_terminal(rt: Runtime, run_id: str, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = rt.ledger_state_unlocked_retry()
        except Fail:
            state = None
        if state is not None:
            run_state = state.run_states.get(run_id)
            if run_state is not None and run_state.value not in ("PLANNED", "RUNNING"):
                return run_state.value
        time.sleep(2.0)
    return None


def wait_for_no_locks(timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not list((CFG.p12 / "locks").glob("*.lock")):
            return True
        time.sleep(1.0)
    return False


def task_last_result(slot_id: str):
    present, columns = task_query_verbose(task_name(slot_id))
    if not present or columns is None:
        return None
    raw = (columns.get("Last Result") or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else None


def stage_taskrun(state: dict) -> None:
    rt = runtime()
    plan = state["plan"]
    verify_roots("taskrun before")
    run_id = run_id_of(rt, plan, "sched")
    before = rt.ledger_state(strict=True).summary.record_count
    code, _ = schtasks("/Run", "/TN", task_name("sched"))
    if code != 0:
        raise Fail("TASK_RUN_START_FAILED")
    report("TASK_RUN_STARTED")
    terminal = wait_for_terminal(rt, run_id, TASK_RUN_TIMEOUT_SECONDS)
    if terminal is None:
        last = task_last_result("sched")
        report(f"TASK_RUN_NO_LEDGER_EVIDENCE LAST_RESULT={'UNKNOWN' if last is None else last}")
        code, lines = scheduled_run("sched")                                                  # diagnostic: same command, direct child
        report(f"DIRECT_RERUN {first_token(lines, 'SCHEDULED_RUN ') or 'NO_REPORT'} RC={code}")
        raise Fail("TASK_RUN_TIMEOUT")
    if not wait_for_no_locks():
        raise Fail("TASK_RUN_LOCK_LEFT_BEHIND")
    ledger = rt.ledger_state(strict=True)
    mine = records_of(ledger, run_id)
    if terminal != "SUCCEEDED":
        failure = mine[-1].failure_code if mine else None
        report(f"TASK_RUN_FAILED STATE={terminal} CODE={failure}")
        raise Fail("TASK_RUN_NOT_SUCCEEDED")
    if [r.transition_to.value for r in mine] != ["PLANNED", "RUNNING", "SUCCEEDED"] or ledger.summary.record_count != before + 3:
        raise Fail("TASK_RUN_LEDGER_SHAPE")
    if any(r.operator != "scheduler" for r in mine):
        raise Fail("TASK_RUN_OPERATOR")
    last = task_last_result("sched")
    report(f"TASK_RUN_OK LAST_RESULT={'UNKNOWN' if last is None else last}")
    if last not in (None, 0):
        raise Fail("TASK_LAST_RESULT_NOT_ZERO")
    final = CFG.p12 / "runs" / run_id
    metadata = json.loads((final / "snapshot_metadata.json").read_bytes().decode("utf-8"))
    counts_match = all(metadata[k] == v for k, v in state["manual_counts"].items())
    report(f"SCHED_VS_MANUAL_COUNTS_MATCH={'YES' if counts_match else 'NO'}")
    if not counts_match:
        raise Fail("TASK_RUN_SNAPSHOT_COUNTS_DIFFER")
    if ledger.checkpoint_class != "CHECKPOINT_OK":
        raise Fail("CHECKPOINT_NOT_OK")
    if rt.status_store.classify_status(CFG.p12, ledger) != "STATUS_OK":
        raise Fail("TASK_RUN_STATUS_STALE")
    report(f"LEDGER_OK RECORDS={ledger.summary.record_count}")
    report("CHECKPOINT_OK")
    report("STATUS_OK")
    verify_roots("taskrun after")
    save_evidence("taskrun", {"run_id": run_id, "last_result": last, "records": ledger.summary.record_count})
    mark_done(state, "taskrun")


# ------------------------------------------------------------------ stage 5: duplicate invocation (process layer + scheduler layer)


def stage_duplicate(state: dict) -> None:
    rt = runtime()
    plan = state["plan"]
    verify_roots("duplicate before")
    run_id = run_id_of(rt, plan, "dup")
    before = rt.ledger_state(strict=True).summary.record_count
    argv = [CFG.interpreter, "-m", CLI_MODULE, "scheduled-run", "--slot-id", "dup", *roots_args()]
    children = [subprocess.Popen(argv, cwd=str(CFG.repo), env=child_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for _ in range(2)]
    outputs = [c.communicate(timeout=CHILD_TIMEOUT_SECONDS) for c in children]
    codes = [c.returncode for c in children]
    heads = []
    for (out, err), code in zip(outputs, codes):
        text = out.decode("utf-8", "replace")
        private_log(f"dup child rc={code}\n{text}{err.decode('utf-8', 'replace')}")
        heads.append((first_token([l[len('REPORT: '):] for l in text.splitlines() if l.startswith('REPORT: ')], "SCHEDULED_RUN ") or "NONE", code))
    winners = [h for h in heads if h[0] == "SCHEDULED_RUN SLOT=dup OUTCOME=SUCCEEDED CODE=RUN_SUCCEEDED" and h[1] == 0]
    others = [h for h in heads if h not in winners]
    allowed = {("SCHEDULED_RUN SLOT=dup OUTCOME=SKIPPED CODE=ALREADY_SUCCEEDED", 0),
               ("SCHEDULED_RUN SLOT=dup OUTCOME=DUPLICATE_ACTIVE CODE=DUPLICATE_INVOCATION:RUN_ACTIVE", 6),
               ("SCHEDULED_RUN SLOT=dup OUTCOME=DUPLICATE_ACTIVE CODE=DUPLICATE_INVOCATION:LEDGER_LOCKED", 6)}
    for head, code in heads:
        report(f"DUP_CHILD {head} RC={code}")
    if len(winners) != 1 or len(others) != 1 or others[0] not in allowed:
        raise Fail("DUPLICATE_PROCESS_POLICY_FAILED")
    ledger = rt.ledger_state(strict=True)
    mine = records_of(ledger, run_id)
    if [r.transition_to.value for r in mine] != ["PLANNED", "RUNNING", "SUCCEEDED"] or ledger.summary.record_count != before + 3:
        raise Fail("DUPLICATE_LEDGER_SHAPE")
    runs = [p for p in (CFG.p12 / "runs").iterdir() if p.name.startswith(run_id)]
    if len(runs) != 1 or list((CFG.p12 / "locks").glob("*.lock")):
        raise Fail("DUPLICATE_EVIDENCE_SHAPE")
    report("DUPLICATE_PROCESS_LAYER_OK COMMITS=1")
    # scheduler layer: the already-succeeded task is started again by Task Scheduler → ALREADY_SUCCEEDED, no ledger growth
    sched_run_id = run_id_of(rt, plan, "sched")
    count_before = ledger.summary.record_count
    code, _ = schtasks("/Run", "/TN", task_name("sched"))
    if code != 0:
        raise Fail("TASK_RERUN_START_FAILED")
    time.sleep(20.0)
    if not wait_for_no_locks():
        raise Fail("TASK_RERUN_LOCK_LEFT_BEHIND")
    after = rt.ledger_state(strict=True)
    if after.summary.record_count != count_before or len(records_of(after, sched_run_id)) != 3:
        raise Fail("TASK_RERUN_CHANGED_LEDGER")
    last = task_last_result("sched")
    if last not in (None, 0):
        raise Fail("TASK_RERUN_LAST_RESULT_NOT_ZERO")
    report(f"DUPLICATE_SCHEDULER_LAYER_OK LEDGER_UNCHANGED=YES LAST_RESULT={'UNKNOWN' if last is None else last}")
    report("DUPLICATE_POLICY_OK")
    verify_roots("duplicate after")
    save_evidence("duplicate", {"heads": heads, "records": after.summary.record_count})
    mark_done(state, "duplicate")


# ------------------------------------------------------------------ stage 6: RECOVERY_REQUIRED policy (synthetic evidence) + human recovery


def refusal(rt: Runtime, slot_id: str, code: str, label: str) -> None:
    before = tree_bytes(CFG.p12)
    rc, lines = scheduled_run(slot_id)
    expect_scheduled(lines, slot_id, "RECOVERY_REQUIRED", code, 5, rc, label)
    if tree_bytes(CFG.p12) != before:
        raise Fail(f"{label}_EVIDENCE_MUTATED")
    report(f"{label}_OK CODE={code} EVIDENCE_IDENTICAL=YES")


def succeed(rt: Runtime, slot_id: str, label: str) -> None:
    rc, lines = scheduled_run(slot_id)
    expect_scheduled(lines, slot_id, "SUCCEEDED", "RUN_SUCCEEDED", 0, rc, label)
    report(f"{label}_OK")


def stage_recovery(state: dict) -> None:
    rt = runtime()
    plan = state["plan"]
    ol = rt.operational_lock
    verify_roots("recovery before")
    probe_child = subprocess.Popen([CFG.interpreter, "-c", "import time; time.sleep(5)"], env=child_environment(),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dead_pid = probe_child.pid
    probe_child.wait(timeout=60)
    time.sleep(1.0)
    # rec1: stale lock of a dead process → refused, evidence intact → human release-lock → runs
    rec1 = run_id_of(rt, plan, "rec1")
    target = ol.run_lock_file(CFG.p12, rec1)
    target.write_bytes(ol.LockRecord("RUN", rec1, dead_pid, "d" * 64, None, "2000-01-01T00:00:00Z", utc_z(scheduled_for_of(plan, "rec1")), 1).to_bytes())
    refusal(rt, "rec1", "DUPLICATE_INVOCATION:LOCK_STALE", "STALE_LOCK_REFUSAL")
    rc, lines = cli("classify", "--run-id", rec1, "--private-root", str(CFG.p12))
    if rc != 0 or first_token(lines, "RUN_CLASSIFICATION ") != f"RUN_CLASSIFICATION RUN_ID={rec1} CLASS=NOT_STARTED":
        raise Fail("STALE_LOCK_CLASSIFY_FAILED")
    rc, lines = cli("release-lock", "--private-root", str(CFG.p12), "--run-id", rec1)
    if rc != 0 or first_token(lines, "LOCK ") != "LOCK LOCK_STALE_DEAD RELEASED=YES" or target.exists():
        raise Fail("STALE_LOCK_RELEASE_FAILED")
    if len(list((CFG.p12 / "locks" / "stale").iterdir())) != 1:
        raise Fail("STALE_LOCK_EVIDENCE_MISSING")
    report("STALE_LOCK_HUMAN_RELEASE_OK")
    succeed(rt, "rec1", "STALE_LOCK_AFTER_RELEASE_RUN")
    # rec2: lock whose provenance cannot be proven (alive pid, no identity) → refused; release-lock refuses too; lock preserved
    rec2 = run_id_of(rt, plan, "rec2")
    target2 = ol.run_lock_file(CFG.p12, rec2)
    target2.write_bytes(ol.LockRecord("RUN", rec2, os.getpid(), None, None, "2000-01-01T00:00:00Z", utc_z(scheduled_for_of(plan, "rec2")), 1).to_bytes())
    refusal(rt, "rec2", "DUPLICATE_INVOCATION:LOCK_UNKNOWN_PROVENANCE", "UNKNOWN_LOCK_REFUSAL")
    rc, lines = cli("release-lock", "--private-root", str(CFG.p12), "--run-id", rec2)
    if rc != 1 or first_token(lines, "RUN_FAILED ") != "RUN_FAILED CODE=DUPLICATE_INVOCATION:LOCK_UNKNOWN_PROVENANCE" or not target2.exists():
        raise Fail("UNKNOWN_LOCK_RELEASE_NOT_REFUSED")
    report("UNKNOWN_LOCK_RELEASE_REFUSED_OK LOCK_PRESERVED=YES")
    # rec3: a child dies right after finalization (orphaned final directory, RUNNING in the ledger, dead lock)
    rec3 = run_id_of(rt, plan, "rec3")
    request = request_of(rt, plan, "rec3")
    request_path = CFG.private_dir / "rec3_request.json"
    request_path.write_bytes(request.to_bytes())
    crash_code = ("import json, os, sys\nfrom datetime import datetime, timezone\nsys.path.insert(0, sys.argv[1])\n"
                  "from src.intelligence.automation.execution_request import AutomationExecutionRequest\n"
                  "from src.intelligence.automation.injection import RaisingInjection\n"
                  "from src.intelligence.automation.preconditions import PrivateRoots\n"
                  "from src.intelligence.automation.run_transaction import commit_run\n"
                  "request = AutomationExecutionRequest.from_dict(json.loads(open(sys.argv[2], 'rb').read().decode('utf-8')))\n"
                  "roots = PrivateRoots(sys.argv[3], sys.argv[4], sys.argv[5])\n"
                  "commit_run(request, roots, repo_root=sys.argv[1], runtime_root=sys.argv[1], environment={},\n"
                  "           clock=lambda: datetime.now(timezone.utc).replace(microsecond=0),\n"
                  "           injection=RaisingInjection({'AFTER_FINALIZATION': lambda: os._exit(3)}))\n")
    code, out, err = run_command([CFG.interpreter, "-c", crash_code, str(CFG.repo), str(request_path), str(CFG.p9), str(CFG.p10), str(CFG.p12)],
                                 cwd=CFG.repo)
    private_log(f"rec3 crash child rc={code}\n{out.decode('utf-8', 'replace')}{err.decode('utf-8', 'replace')}")
    if code != 3 or not (CFG.p12 / "runs" / rec3).is_dir() or not ol.run_lock_file(CFG.p12, rec3).exists():
        raise Fail("ORPHAN_SETUP_FAILED")
    ledger = rt.ledger_state(strict=True)
    if ledger.run_states.get(rec3) is None or ledger.run_states[rec3].value != "RUNNING":
        raise Fail("ORPHAN_SETUP_LEDGER")
    report("ORPHAN_CRASH_SIMULATED_OK")
    refusal(rt, "rec3", "DUPLICATE_INVOCATION:PRIOR_ATTEMPT_EXISTS", "ORPHAN_REFUSAL")
    rc, lines = cli("classify", "--run-id", rec3, "--private-root", str(CFG.p12))
    if rc != 0 or first_token(lines, "RUN_CLASSIFICATION ") != f"RUN_CLASSIFICATION RUN_ID={rec3} CLASS=ORPHANED_FINALIZATION":
        raise Fail("ORPHAN_CLASSIFY_FAILED")
    rc, lines = cli("recover-orphan", "--run-id", rec3, "--private-root", str(CFG.p12))
    if rc != 0 or first_token(lines, "RECOVERY ") != f"RECOVERY ORPHAN_RECORDED RUN_ID={rec3}" \
            or "LOCK=LOCK_STALE_DEAD" not in (first_token(lines, "RUN_CLASSIFICATION ") or ""):
        raise Fail("ORPHAN_RECOVERY_FAILED")
    rc, lines = cli("release-lock", "--private-root", str(CFG.p12), "--run-id", rec3)
    if rc != 0 or first_token(lines, "LOCK ") != "LOCK LOCK_STALE_TERMINAL RELEASED=YES":
        raise Fail("ORPHAN_LOCK_RELEASE_FAILED")
    report("ORPHAN_HUMAN_RECOVERY_OK")
    refusal(rt, "rec3", "DUPLICATE_INVOCATION:PRIOR_ATTEMPT_EXISTS", "UNATTENDED_NO_RETRY")
    rc, lines = cli("retry", "--run-id", rec3, *roots_args())
    rec3_retry = run_id_of(rt, plan, "rec3", attempt=2)
    if rc != 0 or first_token(lines, "RETRY_OF=") != f"RETRY_OF={rec3} ATTEMPT=2" or first_token(lines, "RUN_ID=") != f"RUN_ID={rec3_retry}" \
            or "RUN_SUCCEEDED" not in lines:
        raise Fail("HUMAN_RETRY_FAILED")
    report("HUMAN_RETRY_OK ATTEMPT=2")
    rc, lines = scheduled_run("rec3")
    expect_scheduled(lines, "rec3", "SKIPPED", "ALREADY_SUCCEEDED", 0, rc, "RETRIED_INSTANCE_ALREADY_SUCCEEDED")
    report("RETRIED_INSTANCE_ALREADY_SUCCEEDED_OK")
    # rec4: stale head checkpoint (ledger has a valid longer tail) → refused; repair restores the exact checkpoint bytes
    store = rt.ledger_store.LedgerStore(CFG.p12)
    original_head = store.checkpoint_file.read_bytes()
    ledger = rt.ledger_state(strict=True)
    store.checkpoint_file.write_bytes(rt.head_checkpoint.HeadCheckpoint.of(ledger.records[:1]).to_bytes())
    ledger_bytes = store.ledger_file.read_bytes()
    refusal(rt, "rec4", "LEDGER_INVALID:CHECKPOINT_STALE", "STALE_CHECKPOINT_REFUSAL")
    rc, lines = cli("repair-checkpoint", "--private-root", str(CFG.p12))
    if rc != 0 or not (first_token(lines, "RECOVERY ") or "").startswith("RECOVERY CHECKPOINT_REPAIRED "):
        raise Fail("CHECKPOINT_REPAIR_FAILED")
    if store.checkpoint_file.read_bytes() != original_head or store.ledger_file.read_bytes() != ledger_bytes:
        raise Fail("CHECKPOINT_REPAIR_NOT_EXACT")
    report("CHECKPOINT_REPAIR_EXACT_OK")
    succeed(rt, "rec4", "STALE_CHECKPOINT_AFTER_REPAIR_RUN")
    # rec5: a .partial directory → refused, directory intact → recover-partial preserves it as .crashed → runs
    rec5 = run_id_of(rt, plan, "rec5")
    partial = CFG.p12 / "runs" / f"{rec5}.partial"
    partial.mkdir(parents=True)
    (partial / "fragment.json").write_bytes(b"{}\n")
    refusal(rt, "rec5", "DUPLICATE_INVOCATION:PARTIAL_EXISTS", "PARTIAL_REFUSAL")
    rc, lines = cli("recover-partial", "--run-id", rec5, "--private-root", str(CFG.p12))
    crashed = CFG.p12 / "runs" / f"{rec5}.crashed"
    if rc != 0 or first_token(lines, "RECOVERY ") != f"RECOVERY PARTIAL_PRESERVED RUN_ID={rec5}" or partial.exists() \
            or not (crashed / "fragment.json").is_file():
        raise Fail("PARTIAL_RECOVERY_FAILED")
    report("PARTIAL_HUMAN_RECOVERY_OK PRESERVED=YES")
    succeed(rt, "rec5", "PARTIAL_AFTER_RECOVERY_RUN")
    ledger = rt.ledger_state(strict=True)
    if rt.status_store.classify_status(CFG.p12, ledger) != "STATUS_OK":
        raise Fail("RECOVERY_STATUS_STALE")
    remaining = sorted(p.name for p in (CFG.p12 / "locks").glob("*.lock"))
    if remaining != [f"run.{rec2}.lock"]:
        raise Fail("RECOVERY_LOCKS_UNEXPECTED")
    report("RECOVERY_REQUIRED_POLICY_OK")
    report("HUMAN_RECOVERY_OK")
    report(f"LEDGER_OK RECORDS={ledger.summary.record_count}")
    verify_roots("recovery after")
    save_evidence("recovery", {"rec1": rec1, "rec2": rec2, "rec3": rec3, "rec3_retry": rec3_retry, "records": ledger.summary.record_count,
                               "states": state_counts(ledger)})
    mark_done(state, "recovery")


# ------------------------------------------------------------------ stage 7: semantic skips


def stage_skips(state: dict) -> None:
    rt = runtime()
    plan = state["plan"]
    verify_roots("skips before")
    ledger = rt.ledger_state(strict=True)
    count = ledger.summary.record_count
    # MISSED (real clock: the 60 s late window closed minutes ago) → PLANNED → SKIPPED, exit 4; repeat → ALREADY_SKIPPED, no growth
    missed = run_id_of(rt, plan, "missed")
    rc, lines = scheduled_run("missed")
    expect_scheduled(lines, "missed", "MISSED", "OUTSIDE_WINDOW:MISSED", 4, rc, "MISSED_SKIP")
    ledger = rt.ledger_state(strict=True)
    mine = records_of(ledger, missed)
    if [r.transition_to.value for r in mine] != ["PLANNED", "SKIPPED"] or mine[-1].failure_code != "OUTSIDE_WINDOW:MISSED" \
            or ledger.summary.record_count != count + 2 or (CFG.p12 / "runs" / missed).exists():
        raise Fail("MISSED_LEDGER_SHAPE")
    count += 2
    rc, lines = scheduled_run("missed")
    expect_scheduled(lines, "missed", "MISSED", "ALREADY_SKIPPED:OUTSIDE_WINDOW:MISSED", 4, rc, "MISSED_REPEAT")
    if rt.ledger_state(strict=True).summary.record_count != count:
        raise Fail("MISSED_REPEAT_APPENDED")
    report("MISSED_SKIP_OK LEDGER_RECORDS=2 REPEAT=ALREADY_SKIPPED")
    # NON_BUSINESS_DAY: weekend and synthetic holiday instances of the readiness-refusing slot (explicit selection clocks)
    for label, day_key, detail in (("WEEKEND", "saturday", "WEEKEND"), ("HOLIDAY", "holiday", "HOLIDAY")):
        instant = scheduled_for_of(plan, "nbd", date.fromisoformat(plan[day_key])) + timedelta(seconds=30)
        rc, lines = scheduled_run("nbd", selection_clock_at=utc_z(instant))
        expect_scheduled(lines, "nbd", "SKIPPED", f"NON_BUSINESS_DAY:{detail}", 0, rc, f"NON_BUSINESS_{label}")
        ledger = rt.ledger_state(strict=True)
        if ledger.summary.record_count != count + 2:
            raise Fail(f"NON_BUSINESS_{label}_LEDGER_SHAPE")
        last = ledger.records[-1]
        if last.transition_to.value != "SKIPPED" or last.failure_code != f"NON_BUSINESS_DAY:{detail}" or last.slot_id != "nbd":
            raise Fail(f"NON_BUSINESS_{label}_RECORD")
        count += 2
        rc, lines = scheduled_run("nbd", selection_clock_at=utc_z(instant))
        expect_scheduled(lines, "nbd", "SKIPPED", f"ALREADY_SKIPPED:NON_BUSINESS_DAY:{detail}", 0, rc, f"NON_BUSINESS_{label}_REPEAT")
        if rt.ledger_state(strict=True).summary.record_count != count:
            raise Fail(f"NON_BUSINESS_{label}_REPEAT_APPENDED")
    report("NON_BUSINESS_SKIP_OK WEEKEND=1 HOLIDAY=1 REPEAT=ALREADY_SKIPPED")
    # NOT_DUE (real clock; today's 23:59 instance is not yet due and the window never crosses midnight) → nothing written
    before = tree_bytes(CFG.p12)
    rc, lines = scheduled_run("notdue")
    expect_scheduled(lines, "notdue", "SKIPPED", "OUTSIDE_WINDOW:NOT_DUE", 0, rc, "NOT_DUE")
    if tree_bytes(CFG.p12) != before:
        raise Fail("NOT_DUE_WROTE_EVIDENCE")
    report("NOT_DUE_NO_LEDGER_OK")
    rc, lines = scheduled_run("disabled")
    expect_scheduled(lines, "disabled", "SKIPPED", "DISABLED:SLOT_DISABLED", 0, rc, "DISABLED")
    if tree_bytes(CFG.p12) != before:
        raise Fail("DISABLED_WROTE_EVIDENCE")
    report("DISABLED_NO_LEDGER_OK")
    ledger = rt.ledger_state(strict=True)
    if rt.status_store.classify_status(CFG.p12, ledger) != "STATUS_OK":
        raise Fail("SKIPS_STATUS_STALE")
    report(f"LEDGER_OK RECORDS={ledger.summary.record_count}")
    verify_roots("skips after")
    save_evidence("skips", {"records": ledger.summary.record_count, "states": state_counts(ledger)})
    mark_done(state, "skips")


# ------------------------------------------------------------------ stage 8: remove only the A6-owned tasks


def stage_remove(state: dict) -> None:
    plan = state["plan"]
    verify_roots("remove before")
    before = all_task_names()
    owned = {task_name(slot_id) for slot_id in plan["slots"]}
    code, lines = cli_scheduler("scheduler-remove", "--private-root", str(CFG.p12))
    if code != 0 or first_token(lines, "SCHEDULER_REMOVE ") != f"SCHEDULER_REMOVE APPLIED=NO REMOVED={len(owned)} ABSENT=0 NOT_OWNED=0":
        raise Fail("SCHEDULER_REMOVE_PLAN_FAILED")
    if all_task_names() != before:
        raise Fail("SCHEDULER_REMOVE_PLAN_CHANGED_TASKS")
    report(f"SCHEDULER_REMOVE_PLAN_OK TASKS={len(owned)}")
    code, lines = cli_scheduler("scheduler-remove", "--private-root", str(CFG.p12), "--apply")
    if code != 0 or first_token(lines, "SCHEDULER_REMOVE ") != f"SCHEDULER_REMOVE APPLIED=YES REMOVED={len(owned)} ABSENT=0 NOT_OWNED=0":
        raise Fail("SCHEDULER_REMOVE_FAILED")
    after = all_task_names()
    if before - after != owned or after - before:
        report(f"TASK_SET_DELTA REMOVED={len(before - after)} ADDED={len(after - before)}")
        raise Fail("SCHEDULER_REMOVE_TASK_SET_MISMATCH")
    if after != set(state["tasks_before"]):
        raise Fail("TASK_SET_NOT_RESTORED")
    state["installed"] = False
    save_state(state)
    report(f"SCHEDULER_REMOVE_OK REMOVED={len(owned)} FOREIGN_TASKS_UNTOUCHED={len(after)}")
    code, lines = cli_scheduler("scheduler-remove", "--private-root", str(CFG.p12), "--apply")
    if code != 0 or first_token(lines, "SCHEDULER_REMOVE ") != f"SCHEDULER_REMOVE APPLIED=YES REMOVED=0 ABSENT={len(owned)} NOT_OWNED=0":
        raise Fail("SCHEDULER_REMOVE_NOT_IDEMPOTENT")
    report("SCHEDULER_REMOVE_IDEMPOTENT_OK")
    removed_folders, cleanup = 0, "DONE"
    for folder in reversed(TASK_FOLDERS):
        was_present = state.get("folders_before", {}).get(folder)
        if was_present is False:
            if delete_empty_task_folder(folder):
                removed_folders += 1
            else:
                cleanup = "PARTIAL"
        elif was_present is None:
            cleanup = "UNAVAILABLE"
    report(f"TASK_FOLDER_CLEANUP={cleanup} REMOVED={removed_folders}")
    code, lines = cli_scheduler("scheduler-status", "--private-root", str(CFG.p12))
    status_line = first_token(lines, "SCHEDULER_STATUS ") or ""
    if code != 0 or "SCHEDULER_INSTALLED=False" not in status_line or "INSTALLED_TASK_COUNT=0" not in status_line:
        report(f"SCHEDULER_STATUS_UNEXPECTED {status_line}")
        raise Fail("SCHEDULER_STATUS_AFTER_REMOVE_FAILED")
    report("SCHEDULER_STATUS_AFTER_REMOVE_OK")
    verify_roots("remove after")
    save_evidence("remove", {"removed": sorted(owned), "folders_removed": removed_folders, "cleanup": cleanup})
    mark_done(state, "remove")


# ------------------------------------------------------------------ stage 9: verify + archive


def stage_verify(state: dict, *, full_suite: bool) -> None:
    rt = runtime()
    plan = state["plan"]
    verify_roots("verify before")
    check_repo()
    report("REPO_HEAD_OK")
    report("REPO_CLEAN_OK")
    if rt.preconditions.frozen_p11_drift(CFG.repo):
        raise Fail("P11_FROZEN_DRIFT")
    report("P11_ANCHOR_OK FILES=12")
    ledger = rt.ledger_state(strict=True)
    counts = state_counts(ledger)
    expected = {"SUCCEEDED": 7, "SKIPPED": 3, "ORPHANED_FINALIZATION": 1}
    if counts != expected or ledger.summary.record_count != 30:
        report("RUN_STATES " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())) + f" RECORDS={ledger.summary.record_count}")
        raise Fail("FINAL_LEDGER_SHAPE")
    report(f"LEDGER_OK RECORDS={ledger.summary.record_count} SUCCEEDED=7 SKIPPED=3 ORPHANED_FINALIZATION=1")
    report("CHECKPOINT_OK")
    if rt.status_store.classify_status(CFG.p12, ledger) != "STATUS_OK":
        raise Fail("FINAL_STATUS_STALE")
    status = rt.status_store.read_status(CFG.p12)
    report(f"STATUS_OK HEALTH={status['projection']['health_code']}")
    run_dirs = sorted(p.name for p in (CFG.p12 / "runs").iterdir())
    finals = [n for n in run_dirs if len(n) == 64]
    if len(finals) != 8 or [n for n in run_dirs if n.endswith(".crashed")] != [f"{run_id_of(rt, plan, 'rec5')}.crashed"] \
            or any(n.endswith(".partial") for n in run_dirs):
        raise Fail("FINAL_RUN_DIRECTORIES")
    report(f"RUN_DIRECTORIES_OK FINAL={len(finals)} CRASHED=1 PARTIAL=0")
    locks = sorted(p.name for p in (CFG.p12 / "locks").glob("*.lock"))
    if locks != [f"run.{run_id_of(rt, plan, 'rec2')}.lock"]:
        raise Fail("FINAL_LOCKS_UNEXPECTED")
    report("LOCKS_REMAINING=1 EXPECTED=1 KIND=UNKNOWN_PROVENANCE_PRESERVED")
    if any(n.startswith(TASK_PREFIX) for n in all_task_names()):
        raise Fail("A6_TASKS_STILL_PRESENT")
    report("SCHEDULER_REMOVE_OK VERIFIED=YES")
    report(f"IN_PROCESS_NETWORK_TRAPS={len(_HITS)}")
    if _HITS:
        raise Fail("NETWORK_ATTEMPTED")
    report("ZERO_NETWORK_OK SCOPE=IN_PROCESS_PLUS_RUNTIME_GUARD")
    verify_roots("after")
    archive = CFG.work / "archive" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive.mkdir(parents=True, exist_ok=False)
    shutil.move(str(CFG.p12), str(archive / CFG.p12.name))
    state["archived"] = True
    save_state(state)
    report("VALIDATION_ROOT_ARCHIVED=YES")
    save_evidence("verify", {"records": ledger.summary.record_count, "states": counts, "archived": True})
    report("A6_PASS")
    mark_done(state, "verify")
    if full_suite:
        run_full_suite()


def run_full_suite() -> None:
    code, out, err = run_command([CFG.interpreter, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=CFG.repo, timeout=7200)
    text = out.decode("utf-8", "replace") + err.decode("utf-8", "replace")
    (CFG.private_dir / "a6_full_pytest.log").write_bytes(text.encode("utf-8", "replace"))
    summary = [line for line in text.splitlines() if " passed" in line or " failed" in line]
    tail = summary[-1].strip("= ").split(" in ")[0] if summary else "?"
    report(f"FULL_SUITE RC={code} {tail}")
    dirty = [line for line in git("status", "--porcelain", "--untracked-files=all").splitlines() if line.strip()]
    report(f"REPO_DIRTY_AFTER_FULL_SUITE FILES={len(dirty)}")                                 # see RUNBOOK: the known journal file


# ------------------------------------------------------------------ failsafe + commands


def failsafe_remove(state: dict) -> None:
    """After a failure: remove only the A6-owned tasks (never evidence). Best effort; reported."""
    if not state.get("installed"):
        return
    try:
        code, lines = cli_scheduler("scheduler-remove", "--private-root", str(CFG.p12), "--apply")
        report(f"FAILSAFE_REMOVE RC={code} {first_token(lines, 'SCHEDULER_REMOVE ') or 'NO_REPORT'}")
        if code == 0:
            state["installed"] = False
            save_state(state)
    except Fail as exc:
        report(f"FAILSAFE_REMOVE_FAILED {exc}")


def run_validate(args) -> int:
    report.attach(CFG.work)
    state = load_state()
    if state["done"] and not args.resume:
        report("FAIL STATE_PRESENT_USE_RESUME_OR_ARCHIVE_PREVIOUS")
        return 1
    if state.get("archived"):
        report("FAIL ALREADY_COMPLETE_USE_ARCHIVE_PREVIOUS")
        return 1
    handlers = {"preflight": stage_preflight, "authority": stage_authority, "manual": stage_manual, "install": stage_install,
                "taskrun": stage_taskrun, "duplicate": stage_duplicate, "recovery": stage_recovery, "skips": stage_skips,
                "remove": stage_remove, "verify": lambda s: stage_verify(s, full_suite=args.full_suite)}
    for index, stage in enumerate(STAGES):
        if stage in state["done"]:
            continue
        report(f"STAGE_START {stage} {index}")
        try:
            handlers[stage](state)
        except Fail as exc:
            report(f"FAIL {exc}")
            report(f"STAGE_FAIL {stage}")
            state["failed"] = {"stage": stage, "code": str(exc)}
            save_state(state)
            failsafe_remove(state)
            return 1
        except GuardTripped:
            report("FAIL NETWORK_ATTEMPTED")
            report(f"STAGE_FAIL {stage}")
            failsafe_remove(state)
            return 1
        except Exception as exc:  # noqa: BLE001 - unexpected: type only on screen, text in the private log
            import traceback
            private_log(traceback.format_exc())
            report(f"FAIL UNEXPECTED {type(exc).__name__}")
            report(f"STAGE_FAIL {stage}")
            state["failed"] = {"stage": stage, "code": f"UNEXPECTED:{type(exc).__name__}"}
            save_state(state)
            failsafe_remove(state)
            return 1
        report(f"STAGE_PASS {stage}")
    return 0


def run_diagnose(_args) -> int:
    """Preflight-only diagnostics of the Windows process probe and lock classification. Writes only under the work directory."""
    report.attach(CFG.work)
    if not CFG.work.is_dir():
        report("FAIL WORK_DIR_MISSING")
        return 1
    CFG.private_dir.mkdir(parents=True, exist_ok=True)
    try:
        report(f"PYTHON_OK {sys.version_info.major}.{sys.version_info.minor}")
        report("WINDOWS_OK" if IS_WINDOWS else "WINDOWS_OK PLATFORM=SELFTEST")
        check_repo()
        report("REPO_HEAD_OK")
        rt = runtime()
        probe = rt.probe
        me = os.getpid()
        for _ in range(5):                                                                   # repeated: catches intermittent None / slow calls
            timed_alive(probe, me)
            timed_identity(probe, me)
        identities = {timed_identity(probe, me) for _ in range(3)}
        report(f"SELF_IDENTITY_DISTINCT_VALUES={len(identities)} NONE={'YES' if None in identities else 'NO'}")
        report_probe_timings("repeat")
        probe_checks(rt, {})
        report("DIAGNOSE_DONE RESULT=PASS")
        return 0
    except Fail as exc:
        report(f"FAIL {exc}")
        report("DIAGNOSE_DONE RESULT=FAIL")
        return 1
    except Exception as exc:  # noqa: BLE001
        import traceback
        private_log(traceback.format_exc())
        report(f"FAIL UNEXPECTED {type(exc).__name__}")
        report("DIAGNOSE_DONE RESULT=FAIL")
        return 1


def run_status(_args) -> int:
    report.attach(CFG.work)
    state = load_state()
    report("STAGES_DONE " + (",".join(state["done"]) or "NONE"))
    report(f"FAILED {state.get('failed') and state['failed']['code'] or 'NONE'}")
    report(f"TASKS_INSTALLED={'YES' if state.get('installed') else 'NO'} ARCHIVED={'YES' if state.get('archived') else 'NO'}")
    return 0


def run_archive_previous(_args) -> int:
    report.attach(CFG.work)
    state = load_state()
    if state.get("installed"):
        report("FAIL TASKS_STILL_INSTALLED_RUN_VALIDATE_RESUME_OR_REPORT")
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = CFG.work / "archive" / stamp
    archive.mkdir(parents=True, exist_ok=False)
    moved = 0
    if CFG.p12.exists():
        shutil.move(str(CFG.p12), str(archive / CFG.p12.name))
        moved += 1
    for name in ("a6_state.json", "a6_report.txt", "a6_private.log"):
        if (CFG.work / name).is_file():
            shutil.move(str(CFG.work / name), str(archive / name))
            moved += 1
    for name in ("private", "evidence"):
        if (CFG.work / name).is_dir():
            shutil.move(str(CFG.work / name), str(archive / name))
            moved += 1
    report.copy = None
    report(f"ARCHIVED_PREVIOUS ITEMS={moved}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a6", description="P12-A6 Windows real-machine automation validation")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--resume", action="store_true")
    validate.add_argument("--full-suite", action="store_true")
    sub.add_parser("status")
    sub.add_parser("archive-previous")
    sub.add_parser("diagnose")
    for p in (validate, *[sub.choices[k] for k in ("status", "archive-previous", "diagnose")]):
        for name in ("--repo", "--p9-root", "--p10-root", "--p12-root", "--work"):       # self-test overrides only (not for operators)
            p.add_argument(name, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    for attribute, option in (("repo", "repo"), ("p9", "p9_root"), ("p10", "p10_root"), ("p12", "p12_root"), ("work", "work")):
        value = getattr(args, option)
        if value is not None:
            setattr(CFG, attribute, Path(value))
    install_network_trap()
    return {"validate": run_validate, "status": run_status, "archive-previous": run_archive_previous, "diagnose": run_diagnose}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
