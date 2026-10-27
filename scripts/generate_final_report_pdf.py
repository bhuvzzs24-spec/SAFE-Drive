"""Generate the printable SAFE-Drive report from its Markdown source."""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/SAFE_DRIVE_FINAL_REPORT.md"
OUTPUT = ROOT / "output/pdf/SAFE_DRIVE_FINAL_REPORT.pdf"
NAVY = colors.HexColor("#172a3a")
TEAL = colors.HexColor("#137c78")
PALE = colors.HexColor("#edf4f4")
INK = colors.HexColor("#263746")


class Architecture(Flowable):
    def __init__(self):
        super().__init__()
        self.width, self.height = 170 * mm, 56 * mm

    def draw(self):
        boxes = [("Video file", 7, 37), ("Flask API", 40, 37),
                 ("YOLO detector", 73, 37), ("DeepSORT tracker", 106, 37),
                 ("SQLite records", 139, 37),
                 ("Calibration + speed rules", 40, 8),
                 ("Optional helmet adapter", 91, 8)]
        c = self.canv
        for label, x, y in boxes:
            c.setFillColor(PALE)
            c.setStrokeColor(TEAL)
            c.roundRect(x * mm, y * mm, 27 * mm, 12 * mm, 2 * mm, fill=1, stroke=1)
            c.setFillColor(INK)
            c.setFont("Helvetica", 7)
            c.drawCentredString((x + 13.5) * mm, (y + 7) * mm, label)
        c.setStrokeColor(TEAL)
        c.setLineWidth(1.3)
        for x1, x2 in [(34, 40), (67, 73), (100, 106), (133, 139)]:
            c.line(x1 * mm, 43 * mm, x2 * mm, 43 * mm)
            c.line((x2 - 2) * mm, 44.2 * mm, x2 * mm, 43 * mm)
            c.line((x2 - 2) * mm, 41.8 * mm, x2 * mm, 43 * mm)
        c.line(52 * mm, 37 * mm, 52 * mm, 20 * mm)
        c.line(52 * mm, 20 * mm, 53 * mm, 20 * mm)
        c.line(86.5 * mm, 37 * mm, 86.5 * mm, 20 * mm)
        c.line(86.5 * mm, 20 * mm, 91 * mm, 20 * mm)
        c.setFont("Helvetica-Oblique", 7)
        c.setFillColor(INK)
        c.drawString(40 * mm, 2 * mm,
                     "Annotated results and review data are presented by the web interface.")


def build():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle(name="ReportTitle", parent=base["Title"],
              fontName="Helvetica-Bold", fontSize=23, leading=28,
              textColor=NAVY, alignment=TA_CENTER, spaceAfter=8))
    base.add(ParagraphStyle(name="Deck", parent=base["Normal"], fontSize=10,
              leading=15, textColor=TEAL, alignment=TA_CENTER, spaceAfter=18))
    base.add(ParagraphStyle(name="H1x", parent=base["Heading1"], fontSize=16,
              leading=20, textColor=NAVY, spaceBefore=13, spaceAfter=7, keepWithNext=True))
    base.add(ParagraphStyle(name="H2x", parent=base["Heading2"], fontSize=12,
              leading=15, textColor=TEAL, spaceBefore=9, spaceAfter=4, keepWithNext=True))
    base.add(ParagraphStyle(name="Bodyx", parent=base["BodyText"], fontSize=9,
              leading=13, textColor=INK, spaceAfter=6))
    story, first, in_fence = [], True, False
    for line in SOURCE.read_text().splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s:
            continue
        if s.startswith("# "):
            if first:
                story.extend([Spacer(1, 18 * mm), Paragraph(escape(s[2:]), base["ReportTitle"]),
                              Paragraph("AI-Assisted Traffic Monitoring and Road-Safety Review | Final report | 28 October 2026", base["Deck"])])
                first = False
            continue
        if s.startswith("## "):
            heading = s[3:]
            story.append(Paragraph(escape(heading), base["H1x"]))
            if heading == "Architecture and data flow":
                story.extend([Architecture(), Spacer(1, 4 * mm)])
            continue
        if s.startswith("### "):
            story.append(Paragraph(escape(s[4:]), base["H2x"]))
            continue
        if s.startswith("- "):
            story.append(Paragraph("&bull;&nbsp; " + escape(s[2:]), base["Bodyx"]))
            continue
        if len(s) > 2 and s[0].isdigit() and s[1:3] == ". ":
            story.append(Paragraph(escape(s), base["Bodyx"]))
            continue
        s = s.replace("**", "").replace("`", "")
        if s.startswith("Repository: "):
            story.append(Paragraph('Repository: <link href="https://github.com/bhuvzzs24-spec/SAFE-Drive" color="#137c78">github.com/bhuvzzs24-spec/SAFE-Drive</link>', base["Bodyx"]))
        else:
            story.append(Paragraph(escape(s), base["Bodyx"]))

    def footer(canvas, doc):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(colors.HexColor("#d9e3e7"))
        canvas.line(20 * mm, 15 * mm, width - 20 * mm, 15 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#607482"))
        canvas.drawString(20 * mm, 10 * mm, "SAFE-Drive | Implementation and verification report")
        canvas.drawRightString(width - 20 * mm, 10 * mm, str(doc.page))
        canvas.restoreState()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=20 * mm,
            leftMargin=20 * mm, topMargin=18 * mm, bottomMargin=21 * mm,
            title="SAFE-Drive Final Report", author="SAFE-Drive Project")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    build()
