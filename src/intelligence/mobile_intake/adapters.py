"""Adapter 評価と SyncFolderAdapter（Phase 3.75 §3 / §5 / §6）。

Corpus core は cloud SDK に依存しない。adapter は「同期フォルダ＝ローカル filesystem」を見るだけで、
provider 固有の知識は **既定の同期 root と placeholder / 一時ファイルの見分け方** に限る。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

ICLOUD_DRIVE = "ICLOUD_DRIVE"
ONEDRIVE = "ONEDRIVE"
GOOGLE_DRIVE = "GOOGLE_DRIVE"
LOCAL_FOLDER = "LOCAL_FOLDER"
PROVIDERS = (ICLOUD_DRIVE, ONEDRIVE, GOOGLE_DRIVE, LOCAL_FOLDER)

SELECTED_PROVIDER = ICLOUD_DRIVE

#: §3 の評価（開発者都合ではなく、iPhone の share-sheet friction と Windows 同期の安定性を重視）
EVALUATION: Tuple[Dict[str, object], ...] = (
    {"provider": ICLOUD_DRIVE, "share_sheet_taps": 2,
     "share_sheet": "Shortcuts の「ファイルを保存」は iCloud Drive/Shortcuts 配下へ **確認なし** で保存できる（唯一）",
     "windows_sync": "iCloud for Windows（Microsoft Store・無料・既存 Apple ID）→ %USERPROFILE%\\iCloudDrive",
     "stable_local_fs": True, "offline": "iPhone 側でキューされ再接続時に同期",
     "duplicate": "同名は自動で ' 2' 付与（上書きしない）→ hash dedup で DUPLICATE",
     "partial_file": "同期中は size 変化 / .icloud placeholder → stable-file 検査で待つ",
     "privacy": "既存 Apple ID の private 領域。public 共有なし", "credentials_in_repo": False,
     "new_account": False, "cost": "無料（既存 5GB 内。PDF 1.5MB/日）",
     "automation": "Windows 側はローカル folder → Task Scheduler で bounded 実行",
     "verdict": "SELECTED"},
    {"provider": ONEDRIVE, "share_sheet_taps": 4,
     "share_sheet": "OneDrive app の共有拡張は保存先 folder を毎回選ぶ。Shortcuts「ファイルを保存」は確認なし保存が iCloud 限定",
     "windows_sync": "Windows 標準（%USERPROFILE%\\OneDrive）。Files On-Demand の placeholder に注意",
     "stable_local_fs": True, "offline": "可", "duplicate": "同名は ' (1)' 付与",
     "partial_file": "placeholder（0 byte / RECALL_ON_DATA_ACCESS）→ 検査で待つ",
     "privacy": "Microsoft アカウント", "credentials_in_repo": False, "new_account": False,
     "cost": "無料枠", "automation": "同上", "verdict": "FALLBACK（Windows 側の folder として利用可）"},
    {"provider": GOOGLE_DRIVE, "share_sheet_taps": 4,
     "share_sheet": "Drive app「ドライブに保存」は毎回 folder 選択・アカウント選択が入る",
     "windows_sync": "Google Drive for Desktop（別途インストール、ドライブレター mount）",
     "stable_local_fs": "mount 依存", "offline": "可", "duplicate": "同名を許容（重複ファイルが並ぶ）",
     "partial_file": ".tmp / 遅延取得", "privacy": "Google アカウント", "credentials_in_repo": False,
     "new_account": False, "cost": "無料枠", "automation": "同上",
     "verdict": "FALLBACK（folder として利用可）"},
    {"provider": LOCAL_FOLDER, "share_sheet_taps": None,
     "share_sheet": "iPhone からの経路なし（USB / AirDrop → Windows 手動）",
     "windows_sync": "不要", "stable_local_fs": True, "offline": "n/a", "duplicate": "hash dedup",
     "partial_file": "copy 中は size 変化 → 検査で待つ", "privacy": "ローカルのみ",
     "credentials_in_repo": False, "new_account": False, "cost": "無料",
     "automation": "同上", "verdict": "MANUAL FALLBACK（PDF を Inbox へ drop するだけ）"},
)

REJECTED_ALTERNATIVES = ("mobile app", "custom server", "public upload endpoint", "OAuth backend",
                         "Discord bot", "email intake")


def default_sync_root(provider: str, env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """provider の既定同期 root（Windows / macOS）。存在確認はしない。"""
    environ = os.environ if env is None else env
    provider = (provider or "").upper()
    profile = str(environ.get("USERPROFILE", "") or "")
    home = str(environ.get("HOME", "") or "")
    if provider == ICLOUD_DRIVE:
        if profile:
            return Path(profile) / "iCloudDrive"
        if home:
            return Path(home) / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        return None
    if provider == ONEDRIVE:
        one = str(environ.get("OneDrive", "") or environ.get("ONEDRIVE", "") or "")
        if one:
            return Path(one)
        return Path(profile) / "OneDrive" if profile else None
    if provider == GOOGLE_DRIVE:
        g = str(environ.get("GOOGLE_DRIVE_ROOT", "") or "")
        return Path(g) if g else None
    return None


def default_inbox_dir(provider: str, subpath: str,
                      env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    root = default_sync_root(provider, env)
    if root is None:
        return None
    return root.joinpath(*[p for p in str(subpath).replace("\\", "/").split("/") if p])


_PLACEHOLDER_SUFFIXES = (".icloud", ".tmp", ".crdownload", ".part", ".gdoc")
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_FILE_ATTRIBUTE_OFFLINE = 0x00001000


def is_placeholder(path: Path) -> Tuple[bool, str]:
    """同期クライアントの placeholder / 一時ファイルか（本体がまだローカルに無い）。"""
    name = Path(path).name
    if name.startswith(".") or name.startswith("~$"):
        return True, "HIDDEN_OR_TEMP"
    if name.lower().endswith(_PLACEHOLDER_SUFFIXES):
        return True, "SYNC_PLACEHOLDER_SUFFIX"
    try:
        st = Path(path).stat()
    except OSError:
        return True, "STAT_FAILED"
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & (_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | _FILE_ATTRIBUTE_OFFLINE):
        return True, "FILES_ON_DEMAND_PLACEHOLDER"
    if st.st_size == 0:
        return True, "ZERO_BYTES"
    return False, ""


@dataclass(frozen=True)
class SyncFolderAdapter:
    """同期フォルダ adapter: incoming file を **見つけて** processor へ渡すだけ。"""

    provider: str
    inbox_dir: Path
    status_dir_name: str = "_status"

    @property
    def name(self) -> str:
        return f"sync_folder:{self.provider.lower()}"

    def exists(self) -> bool:
        return Path(self.inbox_dir).is_dir()

    def discover(self) -> Tuple[List[Path], List[Tuple[Path, str]]]:
        """→ (候補 PDF, placeholder/一時ファイル)。status dir・サブフォルダ・非 PDF は無視。"""
        candidates: List[Path] = []
        placeholders: List[Tuple[Path, str]] = []
        if not self.exists():
            return candidates, placeholders
        for path in sorted(Path(self.inbox_dir).iterdir()):
            if path.is_dir() or path.name == self.status_dir_name:
                continue
            ph, reason = is_placeholder(path)
            if ph:
                if reason == "HIDDEN_OR_TEMP":
                    continue                                   # 隠し / 一時ファイルは無視（報告もしない）
                if path.name.lower().endswith(".icloud") or ".pdf" in path.name.lower():
                    placeholders.append((path, reason))
                continue
            if path.suffix.lower() != ".pdf":
                continue
            candidates.append(path)
        return candidates, placeholders

    def describe(self) -> Dict[str, object]:
        from .local_config import redact_path

        exists = self.exists()
        writable = exists and os.access(self.inbox_dir, os.W_OK)
        readable = exists and os.access(self.inbox_dir, os.R_OK)
        return {"adapter": self.name, "provider": self.provider,
                "inbox": redact_path(self.inbox_dir), "exists": exists,
                "readable": readable, "writable": writable}


def evaluation_table() -> List[Dict[str, object]]:
    return [dict(row) for row in EVALUATION]
