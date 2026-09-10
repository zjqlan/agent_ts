from __future__ import annotations

from zypg.storage import mysql


def test_grade_queue_pending_until_teacher(db):
    mysql.insert_class("c1", "班", "高一", "数学")
    mysql.insert_student("stu2", "S02", "李二")
    mysql.enroll("c1", "stu2")
    mysql.insert_assignment("hw1", "c1", "卷", "数学", ["数列求和"], None, {"gradeable": True})
    mysql.insert_item(
        {
            "homework_id": "hw1",
            "item_id": "q3",
            "kind": "subjective",
            "number": 3,
            "stem": "求和",
            "options": None,
            "answer_key": {"text": "100"},
            "rubric": ["项数", "求和"],
            "knowledge_point": "数列求和",
            "score": 10,
        }
    )
    mysql.replace_item_result(
        {
            "homework_id": "hw1",
            "student_id": "stu2",
            "item_id": "q3",
            "raw": {"confidence": 0.2},
            "score": 3,
            "is_correct": None,
            "source": "ocr_llm",
            "pending": 1,
        }
    )
    mysql.insert_review("hw1", "stu2", "q3", "low_confidence", 3)
    rows = mysql.list_item_results("hw1", "stu2")
    assert rows[0]["pending"] == 1
    assert rows[0]["source"] == "ocr_llm"
    q = mysql.list_open_reviews("hw1")
    assert q and q[0]["reason"] == "low_confidence"

    from zypg.agents.cards import CardsAgent
    from zypg.models import A2AMessage
    import asyncio

    agent = CardsAgent()
    rid = q[0]["id"]
    asyncio.run(
        agent.handle(A2AMessage(skill="review_queue", payload={"action": "accepted", "review_id": rid}))
    )
    after = mysql.list_item_results("hw1", "stu2")[0]
    assert after["pending"] == 0
    assert after["source"] == "teacher"
    assert mysql.get_review(rid)["status"] == "accepted"
