"""Markdownレポートを将来PDF化するための変換フック。

現時点ではPDF化は必須要件ではないため重量級の依存ライブラリは requirements.txt に
含めていない。pandoc（https://pandoc.org/）がインストール済みの環境であれば
そのまま `python -m src.report.pdf output/2026-07-01_market_brief.md` で
同名の .pdf を生成できる。pandoc が無い環境では分かりやすいエラーを出す。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


class PdfConversionError(RuntimeError):
    pass


def convert_to_pdf(markdown_path: str | Path, pdf_path: str | Path | None = None) -> Path:
    md_path = Path(markdown_path)
    if not md_path.exists():
        raise FileNotFoundError(md_path)

    out_path = Path(pdf_path) if pdf_path else md_path.with_suffix(".pdf")

    if shutil.which("pandoc") is None:
        raise PdfConversionError(
            "pandoc が見つかりません。PDF化するには `pandoc` をインストールしてください "
            "(例: apt-get install pandoc / brew install pandoc)。"
        )

    subprocess.run(
        ["pandoc", str(md_path), "-o", str(out_path)],
        check=True,
    )
    return out_path


def main() -> None:
    if len(sys.argv) < 2:
        print("使い方: python -m src.report.pdf <markdownファイル> [出力先pdf]")
        raise SystemExit(1)
    md_path = sys.argv[1]
    pdf_path = sys.argv[2] if len(sys.argv) > 2 else None
    result = convert_to_pdf(md_path, pdf_path)
    print(f"PDFを出力しました: {result}")


if __name__ == "__main__":
    main()
