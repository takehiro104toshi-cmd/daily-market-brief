"""P12-A2 — 凍結の Phase 11 の runtime の identity（anchor と 12 file の git blob）。runtime 側の宣言（test の registry は import しない）。

- `P11_FROZEN_ANCHOR` ＝ Phase 11 v1 の意味 ／ runtime の凍結 anchor。`P11_FROZEN_BLOBS` ＝ その anchor の tree の (repo 相対 path → blob id)。
- `git_blob_id(data)` ＝ git と同じ blob の id（`sha1("blob <len>\\0" + data)`）。worktree の byte から再計算し、drift を検出する。
- `p11_runtime_manifest()` ＝ anchor と blob の正準な manifest（domain 付き digest）。path は repo 相対（private な値ではない）。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Mapping

from .canonical import domain_digest

P11_FROZEN_ANCHOR = "43c0b856d41efed397de213a1a06178c5e97ab10"
P11_PACKAGE_RELATIVE = "src/intelligence/personal_ui"
P11_RUNTIME_MANIFEST_DOMAIN = "p12.p11_runtime_manifest.v1"
P11_FROZEN_BLOBS: Mapping[str, str] = {
    f"{P11_PACKAGE_RELATIVE}/__init__.py": "318b150e2b1df6e250a4ae73354a21bcbaf133d5",
    f"{P11_PACKAGE_RELATIVE}/local_server.py": "f757ee5d7ddaeff1f12389d12772be9849f4a988",
    f"{P11_PACKAGE_RELATIVE}/p10_read_adapter.py": "48ce6c989f56b1fab15ccc8e1769dcd0fa3ab67e",
    f"{P11_PACKAGE_RELATIVE}/static/.gitattributes": "fa1385d99a319b43c06f5309d1aae9fdd3adea46",
    f"{P11_PACKAGE_RELATIVE}/static/app.css": "f3db2832edcfdcc02d302a6510b2b6bbbe9d1e05",
    f"{P11_PACKAGE_RELATIVE}/static/app.js": "9bf12c66aa36d0131da81f3125715589c30b081d",
    f"{P11_PACKAGE_RELATIVE}/static/icon-192.png": "60ea4a088a2fe2c81f4602d33c4290a65d5a035a",
    f"{P11_PACKAGE_RELATIVE}/static/icon-512.png": "b37421a7d8433c8b18e3637c1b00c1bc99a7d953",
    f"{P11_PACKAGE_RELATIVE}/static/index.html": "352cfff59abce81a29765f3ce5ced01356e3cd86",
    f"{P11_PACKAGE_RELATIVE}/static/manifest.webmanifest": "65372b8dbf4e4badbd6e64f1e71948b1be1a0db5",
    f"{P11_PACKAGE_RELATIVE}/static/sw.js": "55ade163c455e3481eeac2a6ae0a6fcc7951b5fb",
    f"{P11_PACKAGE_RELATIVE}/ui_model.py": "bb436fb92a878aabed20739638333599360e8aaa",
}


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def p11_runtime_manifest() -> Dict[str, Any]:
    """凍結の P11 の runtime の正準な manifest（anchor ・file 数 ・blob ・digest）。"""
    blobs = {name: P11_FROZEN_BLOBS[name] for name in sorted(P11_FROZEN_BLOBS)}
    content = {"source_id": "P11_RUNTIME", "runtime_anchor": P11_FROZEN_ANCHOR, "file_count": len(blobs), "blobs": blobs}
    return {**content, "content_digest": domain_digest(P11_RUNTIME_MANIFEST_DOMAIN, content)}


__all__ = ["P11_FROZEN_ANCHOR", "P11_FROZEN_BLOBS", "P11_PACKAGE_RELATIVE", "P11_RUNTIME_MANIFEST_DOMAIN", "git_blob_id",
           "p11_runtime_manifest"]
