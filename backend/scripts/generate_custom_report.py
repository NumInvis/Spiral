"""Generate a custom Spiral HTML report for a given free-text + rank."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.templating import Jinja2Templates
from database import SessionLocal, init_db
from models import Profile
from recommendation import build_recommendation
from services.profile_parser import parse_free_text, explain_parsing
from services.llm_service import generate_report_summary


TEXT = "湖北考生，物理类，全省排名4320名，喜欢理工科，想学计算机、电子信息、自动化或者电气工程，看重学校层次和就业，接受调剂。"
RANK = 4320
OUTPUT_NAME = "Spiral_Report_4320.html"


def main():
    init_db()
    db = SessionLocal()
    try:
        print(f"[test] text: {TEXT}")
        print(f"[test] rank: {RANK}")
        profile_data = parse_free_text(TEXT, RANK)
        print("[test] parsed:", json.dumps(profile_data.model_dump(), ensure_ascii=False))

        profile = Profile(**profile_data.model_dump())
        db.add(profile)
        db.commit()
        db.refresh(profile)

        result = build_recommendation(profile, db)
        print(f"[test] 冲/稳/保: {result['冲_count']}/{result['稳_count']}/{result['保_count']}")
        print(f"[test] warnings: {result['warnings']}")

        result["recommendations"] = [r.model_dump() for r in result["recommendations"]]
        if result.get("special_recommendations"):
            result["special_recommendations"] = [r.model_dump() for r in result["special_recommendations"]]
            for cat, items in result.get("special_by_type", {}).items():
                if items and hasattr(items[0], "model_dump"):
                    result["special_by_type"][cat] = [i.model_dump() if hasattr(i, "model_dump") else i for i in items]

        explanations = explain_parsing(profile_data, TEXT)

        summary = ""
        if os.environ.get("WINCODE_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            try:
                summary = generate_report_summary(profile_data.model_dump(), result)
                print("[test] summary:", summary)
            except Exception as e:
                print(f"[test] summary failed: {e}")

        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        templates = Jinja2Templates(directory=template_dir)

        html = templates.get_template("report.html").render(
            request=None,
            text=TEXT,
            profile=profile,
            explanations=explanations,
            result=result,
            summary=summary,
        )

        output_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            OUTPUT_NAME,
        )
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[test] report saved: {output_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
