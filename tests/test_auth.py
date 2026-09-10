from __future__ import annotations

import os

from fastapi.testclient import TestClient

from zypg.auth import hash_password, login, seed_default_teacher, teacher_from_token, verify_password
from zypg.config import ROOT
from zypg.roster.service import import_roster
from zypg.storage import mysql, redis_store


def test_password_hash_roundtrip():
    stored = hash_password("teacher123")
    assert verify_password("teacher123", stored)
    assert not verify_password("nope", stored)


def test_login_remembers_class(db):
    seed_default_teacher()
    mysql.insert_class("c-auth", "登录班", "高一", "数学")
    out = login("teacher", "teacher123")
    assert out and out["token"]
    me = teacher_from_token(out["token"])
    assert me and me["username"] == "teacher"
    from zypg.auth import save_context

    save_context(me["teacher_id"], "c-auth", None, "roster")
    again = login("teacher", "teacher123")
    assert again["teacher"]["last_class_id"] == "c-auth"
    assert again["teacher"]["last_page"] == "roster"


def test_roster_belongs_to_teacher_after_login(db):
    seed_default_teacher()
    teacher = mysql.get_teacher_by_username("teacher")
    assert teacher
    info = import_roster(
        ROOT / "samples" / "roster.example.csv",
        class_name="记住班",
        grade="高一",
        subject="数学",
        teacher_id=teacher["teacher_id"],
    )
    redis_store.client().flushdb()
    out = login("teacher", "teacher123")
    assert out and out["teacher"]["last_class_id"] == info["class_id"]
    classes = mysql.list_classes(teacher["teacher_id"])
    assert any(c["class_id"] == info["class_id"] for c in classes)
    assert mysql.class_enrollment_count(info["class_id"]) == 3
    me = teacher_from_token(out["token"])
    assert me and me["last_class_id"] == info["class_id"]


def test_auth_http_endpoints(db):
    seed_default_teacher()
    from zypg.gateway.app import app

    client = TestClient(app)
    bad = client.post("/auth/login", json={"username": "teacher", "password": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/auth/login", json={"username": "teacher", "password": "teacher123"})
    assert ok.status_code == 200
    token = ok.json()["token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["teacher"]["username"] == "teacher"
    patched = client.patch(
        "/auth/me",
        json={"last_class_id": "c1", "last_page": "chat"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patched.status_code == 200
    me2 = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me2.json()["teacher"]["last_class_id"] == "c1"
    client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    gone = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert gone.status_code == 401


def test_login_binds_subject_and_rejects_other(db):
    seed_default_teacher()
    out = login("teacher", "teacher123", subject="语文")
    assert out and out["teacher"]["subject"] == "语文"
    try:
        login("teacher", "teacher123", subject="数学")
        raise AssertionError("should refuse other subject")
    except ValueError as exc:
        assert "语文" in str(exc)
    again = login("teacher", "teacher123", subject="语文")
    assert again["teacher"]["subject"] == "语文"


def test_chinese_teacher_cannot_generate_math_paper(db):
    from zypg.subject import enforce_teacher_subject

    seed_default_teacher()
    login("teacher", "teacher123", subject="语文")
    teacher = mysql.get_teacher_by_username("teacher")
    mysql.insert_class("c-math", "数学班", "高一", "数学", teacher_id=teacher["teacher_id"])
    try:
        enforce_teacher_subject(
            ["generate_paper"],
            {"teacher_id": teacher["teacher_id"], "subject": "数学", "class_id": "c-math"},
        )
        raise AssertionError("should refuse math paper")
    except ValueError as exc:
        assert "语文老师" in str(exc)
        assert "数学" in str(exc)


def test_pytest_uses_isolated_test_database():
    from zypg.config import settings

    assert settings.mysql_database.endswith("_test")
    assert os.environ.get("ZYPG_ALLOW_WIPE") == "1"
    assert os.environ.get("MYSQL_DATABASE") == "zypg_test"
