"""iOS Shortcut「羅針盤に追加」（Phase 3.75 §7 / §8）。

この環境（Linux）からは署名済み .shortcut を生成・インストールできない（iOS は未署名 shortcut の import を
拒否する）。よって **正確な作成手順** を生成する。インストール済みとは主張しない。

MOBILE_ACTION_COUNT: PDF を開いた後の意図的操作数
    1. 共有（Share）  2.「羅針盤に追加」をタップ  → 通知「追加しました」（受動）
= 2。確認アラートを出す構成にすると 3。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .config import MobileIntakeConfig

MOBILE_ACTION_COUNT = 2
MOBILE_ACTION_COUNT_WITH_CONFIRMATION = 3
INSTRUCTIONS_FILE = "shortcut_instructions.md"

ICLOUD_SHORTCUTS_FOLDER = "Shortcuts"   # Shortcuts「ファイルを保存」が確認なしで書ける iCloud Drive 配下の folder


def shortcut_recipe(config: MobileIntakeConfig) -> Dict[str, object]:
    sub = config.inbox_subpath.replace("\\", "/")
    if sub.startswith(ICLOUD_SHORTCUTS_FOLDER + "/"):
        save_subpath = sub[len(ICLOUD_SHORTCUTS_FOLDER) + 1:]
    else:
        save_subpath = sub
    return {
        "name": config.shortcut_name,
        "show_in_share_sheet": True,
        "share_sheet_types": ["PDF", "ファイル"],
        "actions": [
            {"step": 1, "action": "ショートカットの入力を受け取る",
             "settings": {"入力の種類": "PDF, ファイル", "入力がない場合": "何も表示しない"}},
            {"step": 2, "action": "if（ショートカットの入力 のファイル拡張子 が pdf ではない）",
             "settings": {"then": "通知を表示「PDF ではありません」→ ショートカットを停止"}},
            {"step": 3, "action": "ファイルを保存",
             "settings": {"サービス": "iCloud Drive",
                          "保存先パス": f"{save_subpath}/",
                          "保存場所を尋ねる": "オフ",
                          "既存のファイルを上書き": "オフ"}},
            {"step": 4, "action": "通知を表示",
             "settings": {"本文": "羅針盤に追加しました（PC で自動処理されます）"}},
        ],
        "destination": f"iCloud Drive/{ICLOUD_SHORTCUTS_FOLDER}/{save_subpath}",
        "filename": "元のファイル名を維持（手入力なし。同名は iOS が ' 2' を付ける）",
        "mobile_action_count": MOBILE_ACTION_COUNT,
        "mobile_action_count_with_confirmation": MOBILE_ACTION_COUNT_WITH_CONFIRMATION,
        "installed_verified": False,
    }


def build_instructions_ja(config: MobileIntakeConfig) -> str:
    r = shortcut_recipe(config)
    lines: List[str] = [
        f"# iPhone ショートカット「{r['name']}」作成手順",
        "",
        "所要 2〜3 分。iOS 標準の「ショートカット」app だけで作れます（追加 app・アカウント不要）。",
        "",
        "1. ショートカット app を開く → 右上「＋」→ 上の名前を「" + str(r["name"]) + "」に変更",
        "2. 右上「ⓘ」（詳細）→「共有シートに表示」をオン → 共有シートの種類で「PDF」と「ファイル」だけ残す",
        "3. アクションを追加（検索して並べる）:",
    ]
    for a in r["actions"]:
        settings = "、".join(f"{k}: {v}" for k, v in a["settings"].items())
        lines.append(f"   {a['step']}. 「{a['action']}」— {settings}")
    lines += [
        "4. 右上「完了」",
        "",
        f"保存先は自動的に {r['destination']}/ になります（フォルダは初回保存時に自動作成）。",
        "",
        "## 使い方（PDF を開いた後の操作は 2 回）",
        "",
        "1. Safari / メール / Discord で羅針盤 PDF を開く → 共有ボタン",
        f"2. 「{r['name']}」をタップ → 通知「追加しました」→ 完了",
        "",
        "同じ PDF を二度送っても PC 側で「既に登録済み」になるだけで、Corpus は二重登録されません。",
        "",
        "## 確認",
        "",
        "iPhone の「ファイル」app → iCloud Drive → Shortcuts → CompassInbox に PDF が入っていれば送信成功。",
        "PC で処理されると同じフォルダの `_status/latest_status.txt` に結果（Corpus: 10 → 11 など）が書かれます。",
    ]
    return "\n".join(lines) + "\n"


def write_instructions(home: Path, config: MobileIntakeConfig) -> Path:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    path = home / INSTRUCTIONS_FILE
    path.write_text(build_instructions_ja(config), encoding="utf-8")
    return path
