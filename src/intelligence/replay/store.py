"""Replay 出力 store（Phase 3.9.4）— すべて derived・再構築可能・atomic 置換。人間由来 truth は置かない。

<data_root>/compass_replay/
├── latest.json
└── runs/<run_id>/{replay_manifest.json, snapshots.jsonl, pattern_timelines.jsonl,
                  transition_events.jsonl, summary.json}
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from ..core.paths import data_root

REPLAY_ROOT_NAME = "compass_replay"
LATEST_FILE = "latest.json"
MANIFEST_FILE = "replay_manifest.json"
SNAPSHOTS_FILE = "snapshots.jsonl"
TIMELINES_FILE = "pattern_timelines.jsonl"
EVENTS_FILE = "transition_events.jsonl"
SUMMARY_FILE = "summary.json"


def replay_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / REPLAY_ROOT_NAME


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(dict(payload), ensure_ascii=False, indent=1, sort_keys=True, default=str))


def atomic_write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    lines = [json.dumps(dict(r), ensure_ascii=False, sort_keys=True, default=str) for r in rows]
    atomic_write_text(path, "".join(line + "\n" for line in lines))
    return len(lines)


class ReplayStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def write_run(self, run_id: str, *, manifest: Mapping[str, Any], snapshots: List[Mapping[str, Any]],
                  timelines: List[Mapping[str, Any]], events: List[Mapping[str, Any]],
                  summary: Mapping[str, Any]) -> Dict[str, int]:
        rd = self.run_dir(run_id)
        counts = {"snapshots": atomic_write_jsonl(rd / SNAPSHOTS_FILE, snapshots),
                  "timelines": atomic_write_jsonl(rd / TIMELINES_FILE, timelines),
                  "events": atomic_write_jsonl(rd / EVENTS_FILE, events)}
        atomic_write_json(rd / MANIFEST_FILE, manifest)
        atomic_write_json(rd / SUMMARY_FILE, summary)
        atomic_write_json(self.root / LATEST_FILE, {"run_id": run_id, "run_dir": str(rd.relative_to(self.root)),
                                                    "run_digest": summary.get("run_digest", ""),
                                                    "run_created_at": summary.get("run_created_at", "")})
        return counts

    def read_json(self, run_id: str, name: str) -> Dict[str, Any]:
        p = self.run_dir(run_id) / name
        return dict(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else {}

    def read_jsonl(self, run_id: str, name: str) -> List[Dict[str, Any]]:
        p = self.run_dir(run_id) / name
        if not p.is_file():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    def latest(self) -> Dict[str, Any]:
        p = self.root / LATEST_FILE
        return dict(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else {}

    def list_runs(self) -> List[str]:
        runs = self.root / "runs"
        return sorted(p.name for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []
