"""
Generate a sample Spiral HTML report without running the HTTP server.
Useful for design verification and as a deliverable artifact.

Usage:
    set WINCODE_API_KEY=sk-... && python scripts/generate_sample_report.py
"""

import os
import sys

# Make backend modules importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.templating import Jinja2Templates

from database import SessionLocal, init_db
from models import Profile
from recommendation import build_recommendation
from services.profile_parser import parse_free_text, explain_parsing
from services.llm_service import generate_report_summary


SAMPLE_TEXT = (
    "我是湖北考生，物理类，全省排名25000名左右，分数大概580。"
    "想读计算机或者电子信息，以后想留武汉或者在长三角就业。"
    "比较看重专业和学校层次，可以接受调剂。"
)
SAMPLE_RANK = 25000


def main():
    print("[gen] initializing db...")
    init_db()
    print("[gen] db ready")
    db = SessionLocal()
    try:
        print("[gen] parsing text...")
        profile_data = parse_free_text(SAMPLE_TEXT, SAMPLE_RANK)
        print("[gen] parsed profile:", profile_data.model_dump())

        profile = Profile(**profile_data.model_dump())
        db.add(profile)
        db.commit()
        db.refresh(profile)

        print("[gen] building recommendation...")
        result = build_recommendation(profile, db)
        print(f"[gen] got {result['total_groups']} recommendations")

        # Convert Pydantic RecommendationItem objects to plain dicts for JSON serialization in template
        result["recommendations"] = [r.model_dump() for r in result["recommendations"]]

        explanations = explain_parsing(profile_data, SAMPLE_TEXT)

        summary = ""
        if os.environ.get("WINCODE_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            print("[gen] generating LLM summary...")
            try:
                summary = generate_report_summary(profile_data.model_dump(), result)
                print("[gen] summary generated")
            except Exception as e:
                print(f"[gen] summary generation failed: {e}")

        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        templates = Jinja2Templates(directory=template_dir)

        html = templates.get_template("report.html").render(
            request=None,
            text=SAMPLE_TEXT,
            profile=profile,
            explanations=explanations,
            result=result,
            summary=summary,
        )

        output_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "Spiral_Report.html",
        )
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"Report generated: {output_path}")
        print(f"Total recommendations: {result['total_groups']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
