from __future__ import annotations

import asyncio

import pytest

from zypg.agents.cards import CardsAgent
from zypg.agents.homework import HomeworkAgent
from zypg.config import ROOT
from zypg.mcp_tools.student_sim import _remap_item_map
from zypg.models import A2AMessage
from zypg.orchestrator.engine import handle_user_task
from zypg.roster.service import import_roster
from zypg.storage import mysql
from zypg.storage.files import homework_dir


def _roster():
    return import_roster(ROOT / "samples" / "roster.example.csv", class_name="验收班", grade="高一", subject="数学")


def test_generate_normalizes_chinese_type_and_option_text_answer(db):
    info = _roster()
    agent = HomeworkAgent()
    out = asyncio.run(
        agent.handle(
            A2AMessage(
                skill="generate_paper",
                payload={
                    "class_id": info["class_id"],
                    "questions": [
                        {
                            "type": "选择题",
                            "content": "2+2=?",
                            "options": ["4", "3", "2", "1"],
                            "answer": "4",
                            "points": 5,
                            "knowledge_point": "算术",
                        },
                        {
                            "type": "解答题",
                            "content": "简述",
                            "answer": "略",
                            "rubric": ["要点"],
                            "points": 10,
                            "knowledge_point": "算术",
                        },
                    ],
                },
            )
        )
    )
    obj = [i for i in out["items"] if i["kind"] == "objective"]
    assert len(obj) == 1
    assert obj[0]["answer_key"]["letter"] == "A"
    assert out["gradeable"] is True


def test_import_paper_path_alias_and_per_homework_copy(db):
    info = _roster()
    agent = HomeworkAgent()
    src = ROOT / "samples" / "paper.example.md"
    out = asyncio.run(
        agent.handle(
            A2AMessage(
                skill="import_paper",
                payload={"class_id": info["class_id"], "paper_path": str(src)},
            )
        )
    )
    dest = homework_dir(out["homework_id"], "papers") / src.name
    assert dest.is_file()
    assert dest.read_bytes() == src.read_bytes()
    assert out["paper_path"]


def test_import_paper_from_attachment_chat_text(db):
    info = _roster()
    src = ROOT / "samples" / "paper.example.md"
    out = asyncio.run(
        handle_user_task(
            "（附件）",
            info["class_id"],
            None,
            extra={"paper_path": str(src), "path": str(src)},
        )
    )
    assert out.get("ok") is True
    paper = out["results"][0]["result"]
    assert len(paper["items"]) == 3
    assert paper["gradeable"] is True


def test_parse_loose_exam_questions():
    from zypg.mcp_tools.edupaper import _parse_loose_exam, parse_paper_file
    from tempfile import NamedTemporaryFile

    text = """练习卷
1. 等差数列 2,5,8 的下一项是？
A. 9
B. 11
C. 10
D. 12
答案：B

2、求 1 到 100 的和。
答案：5050
"""
    items = _parse_loose_exam(text)
    assert len(items) == 2
    assert items[0]["kind"] == "objective"
    assert items[0]["answer_key"]["letter"] == "B"
    assert items[1]["kind"] == "subjective"
    with NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(text)
        path = f.name
    parsed = parse_paper_file(path)
    assert len(parsed["items"]) >= 2


def test_pipeline_stops_when_generate_fails(db):
    info = _roster()
    out = asyncio.run(
        handle_user_task(
            "按等差数列出题并出卡",
            info["class_id"],
            None,
            extra={
                "skills": ["generate_paper", "generate_cards"],
                "skip_llm": True,
            },
        )
    )
    assert out.get("ok") is False
    assert "题目" in (out.get("error") or out.get("summary") or "")
    skills = [x["skill"] for x in out.get("results") or []]
    assert "generate_cards" not in skills


def test_grade_does_not_call_llm_to_answer_for_students(db):
    info = _roster()
    src = ROOT / "samples" / "paper.example.md"
    paper = asyncio.run(
        HomeworkAgent().handle(
            A2AMessage(skill="import_paper", payload={"class_id": info["class_id"], "path": str(src)})
        )
    )
    hid = paper["homework_id"]
    asyncio.run(
        CardsAgent().handle(
            A2AMessage(skill="generate_cards", payload={"class_id": info["class_id"], "homework_id": hid})
        )
    )
    out = asyncio.run(handle_user_task("批改", info["class_id"], hid))
    assert out.get("ok") is False
    msg = out.get("error") or out.get("summary") or ""
    assert "大模型未给这些学号" not in msg
    assert "替学生作答" in msg or "上传" in msg
    assert not any(x.get("skill") == "fill_demo_scans" for x in out.get("results") or [])
    info = _roster()
    mysql.insert_assignment("hw_empty", info["class_id"], "卷", "数学", [], None, {})
    mysql.upsert_card_template("hw_empty", {"blank_path": "x", "bubbles": {}}, "cards/hw_empty")
    agent = CardsAgent()
    with pytest.raises(ValueError, match="扫描"):
        asyncio.run(
            agent.handle(
                A2AMessage(
                    skill="grade_scans",
                    payload={"homework_id": "hw_empty", "class_id": info["class_id"], "scan_paths": []},
                )
            )
        )


def test_generate_cards_rejects_empty_items(db):
    info = _roster()
    mysql.insert_assignment("hw_no_items", info["class_id"], "空卷", "数学", [], None, {})
    agent = CardsAgent()
    with pytest.raises(ValueError, match="没有题目"):
        asyncio.run(
            agent.handle(
                A2AMessage(
                    skill="generate_cards",
                    payload={"class_id": info["class_id"], "homework_id": "hw_no_items"},
                )
            )
        )


def test_remap_sim_keys_to_item_id():
    items = [
        {"item_id": "q1", "number": 1, "kind": "objective"},
        {"item_id": "q3", "number": 3, "kind": "subjective"},
    ]
    mapped = _remap_item_map({"1": "A", "第3题": ["步骤"]}, items)
    assert mapped["q1"] == "A"
    assert mapped["q3"] == ["步骤"]
