from __future__ import annotations

from fastapi.testclient import TestClient

from zypg.auth import seed_default_teacher
from zypg.storage import mysql


def test_homework_and_message_crud(db):
    seed_default_teacher()
    mysql.insert_class("c-chat", "对话班", "高一", "语文")
    from zypg.gateway.app import app

    client = TestClient(app)
    created = client.post("/ui/homework", json={"class_id": "c-chat", "name": "语文练习"})
    assert created.status_code == 200
    hid = created.json()["homework_id"]
    assert mysql.get_assignment(hid)["name"] == "语文练习"
    renamed = client.patch("/ui/homework", params={"homework_id": hid}, json={"name": "第一课"})
    assert renamed.status_code == 200
    assert mysql.get_assignment(hid)["name"] == "第一课"
    conv = mysql.find_conversation("c-chat", hid)
    assert conv
    mysql.insert_message(conv["conversation_id"], "user", "先改这条")
    mid = mysql.list_messages(conv["conversation_id"])[0]["id"]
    edited = client.patch(f"/ui/messages/{mid}", json={"text": "改好了"})
    assert edited.status_code == 200
    assert mysql.get_message(mid)["content"] == "改好了"
    gone = client.delete(f"/ui/messages/{mid}")
    assert gone.status_code == 200
    assert mysql.get_message(mid) is None
    deleted = client.delete("/ui/homework", params={"homework_id": hid})
    assert deleted.status_code == 200
    assert mysql.get_assignment(hid) is None
