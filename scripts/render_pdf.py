"""Render the design documents to PDF.

markdown -> HTML (python-markdown, tables + fenced code) -> PDF via headless
Google Chrome. No pandoc or LaTeX needed.

Usage: python scripts/render_pdf.py            # both documents
"""

import os
import pathlib
import shutil
import subprocess
import tempfile

import markdown

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHROME_CANDIDATES = (
    os.environ.get("CHROME_BIN", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
)
DOCS = {
    "docs/part2-scale-design.md": "deliverables/WebCrawler_scaling.pdf",
    "docs/part3-poc-and-delivery.md": "deliverables/WebCrawler_poc_and_delivery.pdf",
}
CSS = """
body { font: 10pt/1.42 -apple-system, Helvetica, Arial, sans-serif; color: #111; max-width: 190mm; margin: 0 auto; }
h1 { font-size: 20pt; margin: 0 0 4mm; } h2 { font-size: 14pt; margin-top: 9mm; border-bottom: 1px solid #999; padding-bottom: 1mm; }
h3 { font-size: 11.5pt; margin-top: 6mm; }
table { border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 2.5mm 0; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #bbb; padding: 1.2mm 2mm; vertical-align: top; text-align: left; }
th { background: #eee; }
pre { font: 8.2pt/1.35 Menlo, monospace; background: #f4f4f4; border: 1px solid #ddd; padding: 2.5mm; white-space: pre-wrap; page-break-inside: avoid; }
code { font: 8.8pt Menlo, monospace; background: #f4f4f4; padding: 0 1px; }
@page { size: A4; margin: 16mm 14mm; }
"""


def chrome() -> str:
    """CHROME_BIN, the macOS app path, or a Chrome/Chromium on PATH."""
    for candidate in CHROME_CANDIDATES:
        if not candidate:
            continue
        if pathlib.Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    raise SystemExit("No Chrome/Chromium found; set CHROME_BIN to the browser binary.")


PDF_CUT = "## Appendix B"
PDF_CUT_NOTE = (
    "## Appendix B — The numbers\n\nThe full number ledger (every measured, assumed and derived "
    "value with its working) is Appendix B of `docs/part2-scale-design.md` in the repository, "
    "generated and checked by `scripts/ledger.py`. It is omitted from the PDF for length.\n"
)


def render(src: pathlib.Path, dst: pathlib.Path, browser: str) -> None:
    text = src.read_text()
    if PDF_CUT in text:
        text = text[: text.index(PDF_CUT)] + PDF_CUT_NOTE
    html_body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{CSS}</style></head><body>{html_body}</body></html>"
    )
    dst.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = pathlib.Path(tmpdir) / "page.html"
        tmp_path.write_text(page)
        subprocess.run(
            [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={dst}", tmp_path.as_uri()],
            check=True, capture_output=True,
        )
    print(f"{src.name} -> {dst.relative_to(ROOT)} ({dst.stat().st_size // 1024} KB)")


def main() -> None:
    browser = chrome()
    for src, dst in DOCS.items():
        render(ROOT / src, ROOT / dst, browser)


if __name__ == "__main__":
    main()
