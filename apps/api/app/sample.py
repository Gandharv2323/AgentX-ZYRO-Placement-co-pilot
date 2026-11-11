"""Sample resume -> PDF, for the one-click demo. Runs once via `python -m app.sample`.

reportlab keeps this in-process: no browser, no LibreOffice, no network.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate

SEED = Path(__file__).resolve().parent / "seed"
SEED.mkdir(exist_ok=True)

H1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=19, leading=23, spaceAfter=2)
SUB = ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, leading=13, textColor="#444444", spaceAfter=10)
H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=9.5, leading=13, spaceBefore=12, spaceAfter=3)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.2)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=10, spaceAfter=1.5)


def _bullets(items: list[str]) -> list[Paragraph]:
    # ponytail: literal bullet chars so PDF text extraction keeps them (no ListFlowable glyphs)
    return [Paragraph(f"• {i}", BULLET) for i in items]


def sections() -> list[tuple[str, list[str]]]:
    return [
        ("EDUCATION", [
            "B.Tech Computer Science, Vishwakarma Institute of Technology, Pune — CGPA 8.6/10, expected 2027",
            "Higher Secondary, Fergusson College, Pune — 92.4%",
        ]),
        ("EXPERIENCE", [
            "Data Intern, Pune Data Collective — built a churn-prediction model in Python with scikit-learn, "
            "improving recall from 0.61 to 0.74 on a 40k-row dataset",
            "Data Intern, Pune Data Collective — wrote SQL reporting queries used weekly by a 4-person team",
            "Freelance web work — delivered a FastAPI booking backend for a local studio on a single Linux VM",
        ]),
        ("PROJECTS", [
            "CampusRAG — retrieval-augmented college FAQ assistant using FastAPI, pgvector and Python; 300-student pilot",
            "TransitETA — bus arrival time-series predictor in pandas and Python, 18 percent lower error than baseline",
            "CourseCart — small React frontend with a SQLite backend for tracking electives",
        ]),
        ("SKILLS", [
            "Python, SQL, pandas, scikit-learn, numpy, FastAPI, JavaScript, React, PostgreSQL, SQLite, "
            "Docker, Git, Linux, statistics, matplotlib, Power BI, Excel, communication",
        ]),
        ("ACHIEVEMENTS", ["Smart India Hackathon finalist, 2025", "Department rank 3 in semester 5"]),
        ("LANGUAGES", ["English, Hindi, Marathi"]),
    ]


def build() -> Path:
    out = SEED / "sample_resume.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=14 * mm)
    story: list = [
        Paragraph("Aarav Mehta", H1),
        Paragraph("aarav.mehta@example.com &nbsp;·&nbsp; +91 98765 43210 &nbsp;·&nbsp; Pune, Maharashtra", SUB),
        Paragraph("SUMMARY", H2),
        Paragraph("Final-year B.Tech Computer Science student at Vishwakarma Institute of Technology, Pune, "
                  "targeting AI/ML and data roles. Built and shipped two production-facing projects.", BODY),
    ]
    for title, items in sections():
        story.append(Paragraph(title, H2))
        story.extend(_bullets(items))
    doc.build(story)
    return out


if __name__ == "__main__":
    print(build())
