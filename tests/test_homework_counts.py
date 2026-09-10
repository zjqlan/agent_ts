from __future__ import annotations

import asyncio

from zypg.agents.homework import HomeworkAgent
from zypg.config import ROOT
from zypg.models import A2AMessage
from zypg.orchestrator.engine import handle_user_task
from zypg.roster.service import import_roster
from fastapi.testclient import TestClient


def _roster():
    return import_roster(ROOT / "samples" / "roster.example.csv", class_name="验收班", grade="高一", subject="数学")


def test_generate_honors_counts_and_points(db):
    info = _roster()
    agent = HomeworkAgent()

    async def run():
        return await agent.handle(
            A2AMessage(
                skill="generate_paper",
                payload={
                    "class_id": info["class_id"],
                    "knowledge_points": ["等差数列"],
                    "n_objective": 10,
                    "n_subjective": 3,
                    "objective_points": 3,
                    "subjective_points": 10,
                },
            )
        )

    out = asyncio.run(run())
    items = out["items"]
    obj = [i for i in items if i["kind"] == "objective"]
    subj = [i for i in items if i["kind"] == "subjective"]
    assert len(items) == 13
    assert len(obj) == 10
    assert len(subj) == 3
    assert all(i["score"] == 3 for i in obj)
    assert all(i["score"] == 10 for i in subj)


def test_generate_default_counts_unchanged(db):
    info = _roster()
    agent = HomeworkAgent()

    async def run():
        return await agent.handle(
            A2AMessage(
                skill="generate_paper",
                payload={"class_id": info["class_id"], "knowledge_points": ["等差数列"]},
            )
        )

    out = asyncio.run(run())
    items = out["items"]
    obj = [i for i in items if i["kind"] == "objective"]
    subj = [i for i in items if i["kind"] == "subjective"]
    assert len(items) == 3
    assert len(obj) == 2
    assert len(subj) == 1
    assert [i["score"] for i in obj] == [5, 5]
    assert subj[0]["score"] == 10


def test_user_text_counts_reach_generate(db):
    info = _roster()
    out = asyncio.run(
        handle_user_task(
            "作业生成，按等差数列出题，出10道选择题每题3分，3道大题每题10分",
            info["class_id"],
            None,
        )
    )
    assert out.get("ok") is True
    paper = out["results"][0]["result"]
    items = paper["items"]
    obj = [i for i in items if i["kind"] == "objective"]
    subj = [i for i in items if i["kind"] == "subjective"]
    assert len(items) == 13
    assert len(obj) == 10
    assert len(subj) == 3
    assert all(i["score"] == 3 for i in obj)
    assert all(i["score"] == 10 for i in subj)
    assert "13 题" in (out.get("summary") or "")
    url = paper.get("download_url") or ""
    assert "/ui/paper.docx?homework_id=" in url
    assert paper["homework_id"] in url
    assert "example.com" not in url
    assert "tmpfile.link" not in url


def test_user_requirement_reaches_generate(db):
    from zypg.llm import set_json_backend
    from tests.conftest import canned_llm_json

    info = _roster()
    captured: dict = {}

    async def fake(user: str, system: str = "") -> dict:
        captured["user"] = user
        return canned_llm_json(user, system)

    set_json_backend(fake)
    out = asyncio.run(
        handle_user_task(
            "围绕二次函数顶点式出题，要有实际应用情境",
            info["class_id"],
            None,
            extra={
                "skills": ["generate_paper"],
                "knowledge_points": ["二次函数"],
                "requirement": "围绕二次函数顶点式，要有实际应用情境",
            },
        )
    )
    assert out.get("ok") is True
    assert "二次函数顶点式" in (captured.get("user") or "")
    assert "实际应用情境" in (captured.get("user") or "")
    items = out["results"][0]["result"]["items"]
    assert any(
        "二次函数" in (i.get("stem") or "") or "二次函数" in str(i.get("knowledge_point") or "")
        for i in items
    )


def test_paper_docx_http_download(db):
    info = _roster()
    out = asyncio.run(
        handle_user_task("按等差数列出题", info["class_id"], None)
    )
    hid = out["results"][0]["result"]["homework_id"]
    from zypg.gateway.app import app

    r = TestClient(app).get("/ui/paper.docx", params={"homework_id": hid})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
