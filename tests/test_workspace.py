from __future__ import annotations

from zypg.workspace import derive_stage, page_lock


def test_stage_progression():
    assert (
        derive_stage(
            has_roster=False,
            has_homework=False,
            has_items=False,
            has_cards=False,
            n_results=0,
            n_open_reviews=0,
            has_insight=False,
            grading=False,
        )
        == "no_roster"
    )
    assert (
        derive_stage(
            has_roster=True,
            has_homework=False,
            has_items=False,
            has_cards=False,
            n_results=0,
            n_open_reviews=0,
            has_insight=False,
            grading=False,
        )
        == "no_paper"
    )
    assert (
        derive_stage(
            has_roster=True,
            has_homework=True,
            has_items=True,
            has_cards=False,
            n_results=0,
            n_open_reviews=0,
            has_insight=False,
            grading=False,
        )
        == "ready_cards"
    )
    assert (
        derive_stage(
            has_roster=True,
            has_homework=True,
            has_items=True,
            has_cards=True,
            n_results=0,
            n_open_reviews=0,
            has_insight=False,
            grading=False,
        )
        == "ready_grade"
    )
    assert (
        derive_stage(
            has_roster=True,
            has_homework=True,
            has_items=True,
            has_cards=True,
            n_results=0,
            n_open_reviews=0,
            has_insight=False,
            grading=True,
        )
        == "grading"
    )
    assert (
        derive_stage(
            has_roster=True,
            has_homework=True,
            has_items=True,
            has_cards=True,
            n_results=9,
            n_open_reviews=3,
            has_insight=False,
            grading=False,
        )
        == "review"
    )
    assert (
        derive_stage(
            has_roster=True,
            has_homework=True,
            has_items=True,
            has_cards=True,
            n_results=9,
            n_open_reviews=0,
            has_insight=True,
            grading=False,
        )
        == "insight"
    )


def test_page_lock_matches_plan():
    assert page_lock("no_roster", "chat") == "open"
    assert page_lock("no_roster", "cards") == "lock"
    assert page_lock("no_paper", "paper") == "open"
    assert page_lock("no_paper", "cards") == "lock"
    assert page_lock("ready_cards", "grade") == "lock"
    assert page_lock("grading", "insight") == "open"
    assert page_lock("review", "insight") == "open"


def test_workspace_api_and_gate_same_copy(db):
    from fastapi.testclient import TestClient

    from zypg.gateway.app import app
    from zypg.models import ROSTER_REQUIRED

    client = TestClient(app)
    ws = client.get("/ui/state").json()
    assert ws["stage"] == "no_roster"
    assert ws["stage_label"] == "未导入名单"
    r = client.post("/ask", json={"text": "帮我出卡"})
    body = r.json()
    assert body.get("kind") == "refuse" or body.get("ok") is False
    assert ROSTER_REQUIRED in (body.get("summary") or body.get("error") or "")
    r2 = client.post("/ask", json={"text": "只出卡"})
    assert ROSTER_REQUIRED in (r2.json().get("summary") or "")
