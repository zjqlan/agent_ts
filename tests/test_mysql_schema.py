from __future__ import annotations

from zypg.storage import mysql


def test_mysql_schema_homework_links(db):
    mysql.insert_class("c1", "班", "高一", "数学")
    mysql.insert_student("s01", "S01", "张一")
    mysql.enroll("c1", "s01")
    mysql.insert_assignment("hw1", "c1", "最小卷", "数学", ["等差数列"], "files/papers/x.md", {"gradeable": True})
    mysql.insert_item(
        {
            "homework_id": "hw1",
            "item_id": "q1",
            "kind": "objective",
            "number": 1,
            "stem": "题干",
            "options": ["A", "B", "C", "D"],
            "answer_key": {"letter": "A"},
            "rubric": None,
            "knowledge_point": "等差数列",
            "score": 5,
        }
    )
    mysql.upsert_card_template("hw1", {"width": 10}, "files/cards/hw1")
    mysql.insert_scan("hw1", "s01", "files/scans/a.png", "graded")
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
    hw = mysql.get_assignment("hw1")
    assert hw["class_id"] == "c1"
    items = mysql.list_items("hw1")
    assert items[0]["homework_id"] == "hw1"
    tmpl = mysql.get_card_template("hw1")
    assert tmpl["homework_id"] == "hw1"
    res = mysql.list_item_results("hw1")
    assert res[0]["homework_id"] == "hw1"
    scans = mysql.list_scans("hw1")
    assert scans[0]["homework_id"] == "hw1"
