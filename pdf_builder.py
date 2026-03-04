"""
pdf_builder.py — assemble scraped page records into a single PDF using reportlab.
"""

import html
import logging

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

_BASE = dict(fontName="Helvetica", leading=14, spaceAfter=4, alignment=TA_LEFT)

STYLE_TITLE = ParagraphStyle(
    "SectionTitle", fontName="Helvetica-Bold", fontSize=18,
    leading=22, spaceAfter=4, textColor=colors.HexColor("#1a1a1a"),
)
STYLE_URL = ParagraphStyle(
    "SourceURL", fontName="Helvetica-Oblique", fontSize=8,
    leading=10, spaceAfter=8, textColor=colors.HexColor("#888888"),
)
STYLE_H1 = ParagraphStyle(
    "H1", fontName="Helvetica-Bold", fontSize=15,
    leading=19, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#111111"),
)
STYLE_H2 = ParagraphStyle(
    "H2", fontName="Helvetica-Bold", fontSize=13,
    leading=17, spaceBefore=8, spaceAfter=3, textColor=colors.HexColor("#222222"),
)
STYLE_H3 = ParagraphStyle(
    "H3", fontName="Helvetica-BoldOblique", fontSize=11,
    leading=15, spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#333333"),
)
STYLE_BODY = ParagraphStyle(
    "Body", fontName="Helvetica", fontSize=10,
    leading=14, spaceAfter=4, textColor=colors.HexColor("#1a1a1a"),
)
STYLE_BULLET = ParagraphStyle(
    "Bullet", fontName="Helvetica", fontSize=10,
    leading=14, spaceAfter=2, leftIndent=14, textColor=colors.HexColor("#1a1a1a"),
)
STYLE_QUOTE = ParagraphStyle(
    "Quote", fontName="Helvetica-Oblique", fontSize=10,
    leading=14, spaceAfter=4, leftIndent=20,
    textColor=colors.HexColor("#555555"),
    borderPadding=(4, 0, 4, 8),
)
STYLE_EMPTY = ParagraphStyle(
    "Empty", fontName="Helvetica-Oblique", fontSize=9,
    leading=12, spaceAfter=4, textColor=colors.HexColor("#aaaaaa"),
)

_KIND_TO_STYLE = {
    "h1": STYLE_H1,
    "h2": STYLE_H2,
    "h3": STYLE_H3,
    "body": STYLE_BODY,
    "bullet": STYLE_BULLET,
    "quote": STYLE_QUOTE,
}


def _safe(text: str) -> str:
    """Escape text so reportlab's XML parser doesn't choke on & < > characters."""
    return html.escape(str(text), quote=False)


# ---------------------------------------------------------------------------
# Flowable builder
# ---------------------------------------------------------------------------

def _page_flowables(record: dict) -> list:
    """Convert one page record into a list of reportlab Flowables."""
    flowables = []

    # Section header
    flowables.append(Paragraph(_safe(record["title"]), STYLE_TITLE))
    flowables.append(Paragraph(_safe(record["url"]), STYLE_URL))
    flowables.append(
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc"),
                   spaceAfter=8)
    )

    content = record.get("content", [])
    if not content:
        flowables.append(Paragraph("(No text content found on this page.)", STYLE_EMPTY))
        return flowables

    for kind, text in content:
        if kind == "divider":
            flowables.append(
                HRFlowable(width="80%", thickness=0.3, color=colors.HexColor("#dddddd"),
                           spaceBefore=4, spaceAfter=4)
            )
        else:
            style = _KIND_TO_STYLE.get(kind, STYLE_BODY)
            prefix = "• " if kind == "bullet" else ""
            try:
                flowables.append(Paragraph(prefix + _safe(text), style))
            except Exception as e:
                log.warning("Skipping unparseable paragraph (%s): %s", e, text[:80])

    return flowables


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_pdf(pages: list[dict], output_path: str) -> None:
    """Write all page records to a single PDF at output_path."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=pages[0]["title"] if pages else "Notion Export",
    )

    story = []
    for i, page in enumerate(pages):
        log.info("Adding page to PDF: %s", page["title"])
        story.extend(_page_flowables(page))
        if i < len(pages) - 1:
            story.append(PageBreak())

    doc.build(story)
    log.info("PDF saved: %s (%d pages)", output_path, len(pages))
