from __future__ import annotations

import asyncio
from pathlib import Path

from zypg.config import ROOT
from zypg.mcp_tools.card_render import fill_bubble, wipe_student_id
from zypg.mcp_tools.ocr import set_backend as set_ocr
from zypg.mcp_tools.score_llm import set_backend as set_score
from zypg.models import A2AMessage, FORBIDDEN_PROFILE_TERMS
from zypg.roster.service import import_roster
from zypg.storage import mysql
from zypg.storage.files import abspath


def test_miniloop_three_students(db):
    set_ocr(lambda path: {"text": "和为100", "garbled": False, "reason": ""})

    def score_backend(payload):
        stu = mysql.student_by_id(payload["student_id"])
        if stu and stu["student_no"] == "S02":
            return {
                "suggested_score": 2,
                "confidence": 0.15,
                "comment": "把握低",
                "queued": True,
                "reason": "low_confidence",
            }
        return {
            "suggested_score": 9,
            "confidence": 0.9,
            "comment": "步骤完整",
            "queued": False,
            "reason": "needs_confirm",
        }

    set_score(score_backend)
    try:
        info = import_roster(ROOT / "samples" / "roster.example.csv", class_name="验收班", grade="高一", subject="数学")
        from zypg.agents.cards import CardsAgent
        from zypg.agents.homework import HomeworkAgent
        from zypg.agents.insight import InsightAgent
        from zypg.agents.lesson import LessonAgent

        hw_agent = HomeworkAgent()
        cards = CardsAgent()
        insight = InsightAgent()
        lesson = LessonAgent()

        async def run():
            paper = await hw_agent.handle(
                A2AMessage(
                    skill="import_paper",
                    payload={"class_id": info["class_id"], "path": str(ROOT / "samples" / "paper.example.md")},
                )
            )
            hid = paper["homework_id"]
            rendered = await cards.handle(
                A2AMessage(skill="generate_cards", payload={"class_id": info["class_id"], "homework_id": hid})
            )
            assert rendered["count"] == 3
            geom = rendered["geometry"]
            paths = {Path(p).name: abspath(p) for p in rendered["paths"]}
            fill_bubble(paths["S01.png"], geom, "q1", "A")
            fill_bubble(paths["S01.png"], geom, "q2", "C")
            fill_bubble(paths["S02.png"], geom, "q1", "B")
            fill_bubble(paths["S02.png"], geom, "q2", "D")
            wipe_student_id(paths["S03.png"], geom)
            graded = await cards.handle(
                A2AMessage(
                    skill="grade_scans",
                    payload={
                        "homework_id": hid,
                        "scan_paths": [str(paths["S01.png"]), str(paths["S02.png"]), str(paths["S03.png"])],
                    },
                )
            )
            pack = await insight.handle(
                A2AMessage(skill="class_insight", payload={"class_id": info["class_id"], "homework_id": hid})
            )
            focus = await lesson.handle(
                A2AMessage(skill="next_focus", payload={"class_id": info["class_id"], "homework_id": hid})
            )
            return hid, graded, pack, focus

        hid, graded, pack, focus = asyncio.run(run())
        reviews = mysql.list_open_reviews(hid)
        reasons = {r["reason"] for r in reviews}
        assert "bad_id" in reasons
        s02 = mysql.student_by_no("S02")
        subj = [r for r in mysql.list_item_results(hid, s02["student_id"]) if r["item_id"] == "q3"]
        assert subj and subj[0]["pending"] == 1
        payload = pack["class"]["payload"]
        assert payload["knowledge_accuracy"]
        assert payload["must_teach"] or focus["must_teach"]
        blob = str(pack) + str(focus)
        for term in FORBIDDEN_PROFILE_TERMS:
            assert term not in blob
        assert graded["scanned"] == 3
    finally:
        set_ocr(None)
        set_score(None)
