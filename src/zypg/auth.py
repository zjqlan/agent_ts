from __future__ import annotations

import hashlib
import secrets
from typing import Any

from zypg.config import settings
from zypg.storage import mysql, redis_store

SESSION_TTL = 7 * 24 * 3600
_PBKDF2_ROUNDS = 120_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, dk = stored.split("$", 1)
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS).hex()
    return secrets.compare_digest(check, dk)


def public_teacher(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "teacher_id": row["teacher_id"],
        "username": row["username"],
        "display_name": row.get("display_name") or row["username"],
        "subject": row.get("subject") or "",
        "last_class_id": row.get("last_class_id") or "",
        "last_homework_id": row.get("last_homework_id") or "",
        "last_page": row.get("last_page") or "",
    }


def seed_default_teacher() -> None:
    username = (settings.teacher_username or "teacher").strip()
    if not username:
        return
    if mysql.get_teacher_by_username(username):
        return
    mysql.insert_teacher(
        secrets.token_hex(16),
        username,
        hash_password(settings.teacher_password or "teacher123"),
        settings.teacher_display_name or "教师",
    )


def bind_subject(teacher_id: str, subject: str) -> dict[str, Any]:
    from zypg.subject import normalize_subject

    chosen = normalize_subject(subject)
    if not chosen:
        raise ValueError("请选择任教学科")
    row = mysql.get_teacher(teacher_id)
    if not row:
        raise ValueError("教师不存在")
    stored = normalize_subject(row.get("subject"))
    if stored and stored != chosen:
        raise ValueError(f"该账号已绑定{stored}，不能改成{chosen}。")
    if not stored:
        mysql.update_teacher_subject(teacher_id, chosen)
        row = mysql.get_teacher(teacher_id) or row
    return public_teacher(row)


def login(username: str, password: str, subject: str | None = None) -> dict[str, Any] | None:
    from zypg.subject import normalize_subject

    row = mysql.get_teacher_by_username((username or "").strip())
    if not row or not verify_password(password or "", row["password_hash"]):
        return None
    chosen = normalize_subject(subject)
    stored = normalize_subject(row.get("subject"))
    if stored and chosen and stored != chosen:
        raise ValueError(f"该账号是{stored}老师，请选择{stored}登录。")
    if chosen and not stored:
        mysql.update_teacher_subject(row["teacher_id"], chosen)
        row = mysql.get_teacher(row["teacher_id"]) or row
    token = secrets.token_urlsafe(32)
    redis_store.set_teacher_session(token, row["teacher_id"], ttl=SESSION_TTL)
    mysql.insert_teacher_session(token, row["teacher_id"], SESSION_TTL)
    mysql.claim_orphan_classes(row["teacher_id"])
    classes = mysql.list_classes(row["teacher_id"])
    last_class = row.get("last_class_id") or ""
    if last_class and last_class not in {c["class_id"] for c in classes}:
        last_class = classes[0]["class_id"] if classes else ""
        mysql.update_teacher_context(row["teacher_id"], last_class or None, row.get("last_homework_id"), row.get("last_page"))
        row = mysql.get_teacher(row["teacher_id"]) or row
    elif not last_class and classes:
        last_class = classes[0]["class_id"]
        mysql.update_teacher_context(row["teacher_id"], last_class, row.get("last_homework_id"), row.get("last_page") or "chat")
        row = mysql.get_teacher(row["teacher_id"]) or row
    teacher = public_teacher(row)
    teacher["n_classes"] = len(classes)
    return {"token": token, "teacher": teacher}


def logout(token: str | None) -> None:
    if token:
        redis_store.delete_teacher_session(token)
        mysql.delete_teacher_session(token)


def teacher_from_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    tid = redis_store.get_teacher_session(token)
    if not tid:
        tid = mysql.get_teacher_session(token)
        if tid:
            redis_store.set_teacher_session(token, tid, ttl=SESSION_TTL)
            mysql.touch_teacher_session(token, SESSION_TTL)
    if not tid:
        return None
    row = mysql.get_teacher(tid)
    return public_teacher(row) if row else None


def save_context(teacher_id: str, class_id: str | None, homework_id: str | None, page: str | None) -> None:
    mysql.update_teacher_context(teacher_id, class_id, homework_id, page)
