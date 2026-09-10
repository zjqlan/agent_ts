from __future__ import annotations

from zypg.models import FORBIDDEN_PROFILE_TERMS
from zypg.storage import mysql


def test_insight_two_views_short_long(db):
    mysql.insert_class("c1", "班", "高一", "数学")
    mysql.insert_student("s01", "S01", "张一")
    mysql.insert_student("s02", "S02", "李二")
    mysql.enroll("c1", "s01")
    mysql.enroll("c1", "s02")
    mysql.insert_assignment("hw1", "c1", "卷", "数学", ["等差数列"], None, {})
    mysql.insert_item(
        {
            "homework_id": "hw1",
            "item_id": "q1",
            "kind": "objective",
            "number": 1,
            "stem": "等差",
            "options": ["A", "B", "C", "D"],
            "answer_key": {"letter": "A"},
            "rubric": None,
            "knowledge_point": "等差数列",
            "score": 5,
        }
    )
    mysql.replace_item_result(
        {
            "homework_id": "hw1",
            "student_id": "s01",
            "item_id": "q1",
            "raw": {"mark": "A"},
            "score": 5,
            "is_correct": 1,
            "source": "omr",
            "pending": 0,
        }
    )
    mysql.replace_item_result(
        {
            "homework_id": "hw1",
            "student_id": "s02",
            "item_id": "q1",
            "raw": {"mark": "B"},
            "score": 0,
            "is_correct": 0,
            "source": "omr",
            "pending": 0,
        }
    )
    import asyncio

    from zypg.agents.insight import InsightAgent
    from zypg.models import A2AMessage

    agent = InsightAgent()

    async def run():
        cls = await agent.handle(A2AMessage(skill="class_insight", payload={"class_id": "c1", "homework_id": "hw1"}))
        stu = await agent.handle(
            A2AMessage(
                skill="student_insight",
                payload={"class_id": "c1", "homework_id": "hw1", "student_id": "s02"},
            )
        )
        await agent.handle(A2AMessage(skill="commit_long_term", payload={"homework_id": "hw1", "class_id": "c1"}))
        return cls, stu

    cls, stu = asyncio.run(run())
    payload = cls["class"]["payload"]
    assert cls["class"]["window"] == "short"
    assert "long" in cls
    assert "knowledge_accuracy" in payload
    assert payload["knowledge_accuracy"]["等差数列"] == 0.5
    assert "等差数列" in payload["must_teach"]
    assert payload.get("headline")
    assert payload.get("first_teach")
    assert payload.get("hard_items") is not None
    assert payload.get("item_grid")
    assert stu["scope"] == "student"
    assert stu["short"]["window"] == "short"
    assert stu["long"]["window"] == "long"
    assert "wrong_book" in stu["short"]
    assert stu["short"].get("headline")
    assert (stu["short"].get("coach") or {}).get("next_steps")
    assert stu["short"]["window"] == "short"
    assert stu["long"]["window"] == "long"
    assert "wrong_book" in stu["short"]
    blob = str(cls) + str(stu)
    for term in FORBIDDEN_PROFILE_TERMS:
        assert term not in blob
    events = mysql.list_mastery("c1")
    assert events
    assert {e["mastery"] for e in events} <= {"mastered", "weak", "untested"}
    from zypg.agents.insight_term import build_class_long

    one = build_class_long("c1")
    assert one["n_commits"] == 1
    assert one["can_trend"] is False
    assert one["term_weak_top3"]
    assert one["term_weak_top3"][0]["knowledge_point"] == "等差数列"


def test_term_trend_needs_two_commits(db):
    mysql.insert_class("c1", "班", "高一", "数学")
    mysql.insert_student("s01", "S01", "张一")
    mysql.insert_student("s02", "S02", "李二")
    mysql.enroll("c1", "s01")
    mysql.enroll("c1", "s02")
    for hid, name in (("hw1", "卷一"), ("hw2", "卷二")):
        mysql.insert_assignment(hid, "c1", name, "数学", ["等差数列"], None, {})
        mysql.insert_item(
            {
                "homework_id": hid,
                "item_id": "q1",
                "kind": "objective",
                "number": 1,
                "stem": "等差",
                "options": ["A", "B", "C", "D"],
                "answer_key": {"letter": "A"},
                "rubric": None,
                "knowledge_point": "等差数列",
                "score": 5,
            }
        )
        mysql.replace_item_result(
            {
                "homework_id": hid,
                "student_id": "s01",
                "item_id": "q1",
                "raw": {"mark": "A"},
                "score": 5,
                "is_correct": 1,
                "source": "omr",
                "pending": 0,
            }
        )
        mysql.replace_item_result(
            {
                "homework_id": hid,
                "student_id": "s02",
                "item_id": "q1",
                "raw": {"mark": "B"},
                "score": 0,
                "is_correct": 0,
                "source": "omr",
                "pending": 0,
            }
        )
    import asyncio

    from zypg.agents.insight import InsightAgent
    from zypg.agents.insight_term import build_class_long, build_student_long
    from zypg.models import A2AMessage

    agent = InsightAgent()

    async def run():
        await agent.handle(A2AMessage(skill="commit_long_term", payload={"homework_id": "hw1", "class_id": "c1"}))
        mid = build_class_long("c1")
        await agent.handle(A2AMessage(skill="commit_long_term", payload={"homework_id": "hw2", "class_id": "c1"}))
        return mid

    mid = asyncio.run(run())
    assert mid["can_trend"] is False
    longp = build_class_long("c1")
    assert longp["n_commits"] == 2
    assert longp["can_trend"] is True
    assert len(longp["kp_trend"]) >= 2
    assert longp["term_weak_top3"][0]["knowledge_point"] == "等差数列"
    nos = {x["student_no"] for x in longp["consecutive_weak"]}
    assert "S02" in nos
    stu = build_student_long("c1", "s02")
    assert stu["can_trend"] is True
    assert len(stu["score_trend"]) == 2
    assert stu["consecutive"]
    assert stu["vs_class"]["delta"] < 0
    blob = str(longp) + str(stu)
    for term in FORBIDDEN_PROFILE_TERMS:
        assert term not in blob

