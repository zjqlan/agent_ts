from __future__ import annotations

from fastapi.testclient import TestClient

from zypg.config import ROOT
from zypg.models import ROSTER_REQUIRED
from zypg.roster.service import import_roster
from zypg.storage import mysql


def test_roster_gate_blocks_without_roster(db):
    from zypg.gateway.app import app

    client = TestClient(app)
    r = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "skill": "generate_cards",
                "payload": {"class_id": "no-such-class", "homework_id": "hw-x"},
            },
        },
    )
    body = r.json()
    assert "error" in body
    assert ROSTER_REQUIRED in body["error"]["message"]

    r2 = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "message/send",
            "params": {
                "skill": "grade_scans",
                "payload": {"homework_id": "hw-x", "scan_paths": []},
            },
        },
    )
    assert ROSTER_REQUIRED in r2.json()["error"]["message"]


def test_roster_gate_allows_after_import(db):
    sample = ROOT / "samples" / "roster.example.csv"
    info = import_roster(sample, class_name="验收班", grade="高一", subject="数学")
    assert info["count"] == 3
    mysql.insert_assignment("missing-hw", info["class_id"], "空卷", "数学", [], None, {})
    from zypg.gateway.app import app

    client = TestClient(app)
    r = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "skill": "generate_cards",
                "payload": {"class_id": info["class_id"], "homework_id": "missing-hw"},
            },
        },
    )
    body = r.json()
    assert "error" not in body or ROSTER_REQUIRED not in body.get("error", {}).get("message", "")
    # 有名单后不再因门禁拒绝；缺试卷只是空题出卡
    if "result" in body:
        assert body["result"]["count"] == 3
