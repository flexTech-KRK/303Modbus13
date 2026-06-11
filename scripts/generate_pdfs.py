#!/usr/bin/env python3
"""Generate PDF versions of project documentation (Markdown to PDF)."""

from __future__ import annotations

import sys
from pathlib import Path

import markdown
from xhtml2pdf import pisa

ROOT = Path(__file__).resolve().parent.parent
DOCS = [
    (ROOT / "README.md", ROOT / "docs" / "README.pdf"),
    (ROOT / "docs" / "USER_GUIDE.md", ROOT / "docs" / "USER_GUIDE.pdf"),
    (ROOT / "docs" / "REGISTERS.md", ROOT / "docs" / "REGISTERS.pdf"),
]

CSS = """
@page {
    size: A4;
    margin: 2cm 1.8cm;
}
body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.45;
    color: #1e293b;
}
h1 {
    font-size: 20pt;
    color: #0f172a;
    border-bottom: 2px solid #3b82f6;
    padding-bottom: 6px;
    margin-top: 0;
}
h2 {
    font-size: 14pt;
    color: #1e40af;
    margin-top: 18px;
    page-break-after: avoid;
}
h3 {
    font-size: 11pt;
    color: #334155;
    margin-top: 14px;
    page-break-after: avoid;
}
h4 {
    font-size: 10pt;
    color: #475569;
    page-break-after: avoid;
}
p, li {
    margin: 0 0 6px 0;
}
ul, ol {
    margin: 6px 0 10px 18px;
    padding: 0;
}
code, pre {
    font-family: Courier, monospace;
    font-size: 8.5pt;
}
code {
    background: #f1f5f9;
    padding: 1px 4px;
}
pre {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    padding: 8px 10px;
    white-space: pre-wrap;
    word-wrap: break-word;
    page-break-inside: avoid;
}
blockquote {
    border-left: 3px solid #3b82f6;
    margin: 10px 0;
    padding: 4px 0 4px 12px;
    color: #475569;
    background: #f8fafc;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 14px 0;
    font-size: 9pt;
    page-break-inside: avoid;
}
th {
    background: #1e40af;
    color: #ffffff;
    font-weight: bold;
    padding: 6px 8px;
    text-align: left;
}
td {
    border: 1px solid #cbd5e1;
    padding: 5px 8px;
    vertical-align: top;
}
tr:nth-child(even) td {
    background: #f8fafc;
}
hr {
    border: none;
    border-top: 1px solid #cbd5e1;
    margin: 16px 0;
}
a {
    color: #2563eb;
    text-decoration: none;
}
.footer {
    margin-top: 24px;
    font-size: 8pt;
    color: #64748b;
    text-align: center;
}
img {
    max-width: 100%;
    height: auto;
    margin: 8px 0 12px 0;
    page-break-inside: avoid;
}
"""


def _make_link_callback(base_dir: Path):
    def link_callback(uri: str, _rel) -> str:
        if uri.startswith(("http://", "https://", "data:")):
            return uri
        path = (base_dir / uri).resolve()
        if path.is_file():
            return str(path)
        return uri

    return link_callback


def md_to_pdf(source: Path, destination: Path) -> None:
    text = source.read_text(encoding="utf-8")
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <title>{source.stem}</title>
    <style>{CSS}</style>
</head>
<body>
{body}
<p class="footer">Generated from {source.name} — Ideaflex 303Modbus13</p>
</body>
</html>"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as pdf_file:
        status = pisa.CreatePDF(
            html,
            dest=pdf_file,
            encoding="utf-8",
            link_callback=_make_link_callback(source.parent),
        )
    if status.err:
        raise RuntimeError(f"PDF generation failed: {destination}")


def main() -> int:
    print("Generating PDF documentation...")
    for src, dst in DOCS:
        if not src.exists():
            print(f"  SKIP — file not found: {src}")
            continue
        md_to_pdf(src, dst)
        print(f"  OK: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
