from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd

from zypg.models import ROSTER_REQUIRED
from zypg.storage import mysql, redis_store
from zypg.storage.files import file_root


class RosterDenied(Exception):
    def __init__(self, message: str = ROSTER_REQUIRED) -> None:
        super().__init__(message)


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError("仅支持 CSV / XLSX")


def import_roster(
    path: str | Path,
    class_name: str = "未命名班级",
    grade: str | None = None,
    subject: str | None = None,
    class_id: str | None = None,
    teacher_id: str | None = None,
) -> dict:
    preview = preview_roster(path)
    if preview["duplicates"]:
        raise ValueError("学号重复，不可提交：" + "、".join(preview["duplicates"]))
    cid = class_id or uuid.uuid4().hex
    if not mysql.get_class(cid):
        mysql.insert_class(cid, class_name, grade, subject, teacher_id=teacher_id)
    elif teacher_id:
        mysql.bind_class_teacher(cid, teacher_id)
    n = 0
    for row in preview["rows"]:
        sid = mysql.upsert_student(row["student_no"], row["name"])
        mysql.enroll(cid, sid)
        n += 1
    redis_store.set_roster_gate(cid, n > 0)
    if teacher_id:
        from zypg.auth import save_context

        save_context(teacher_id, cid, None, "roster")
    return {"class_id": cid, "count": n, "name": class_name}


def preview_roster(path: str | Path) -> dict:
    path = Path(path)
    df = _read_table(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "student_no" not in df.columns or "name" not in df.columns:
        raise ValueError("必需列：student_no, name")
    rows: list[dict] = []
    seen: dict[str, int] = {}
    for _, row in df.iterrows():
        no = str(row["student_no"]).strip()
        name = str(row["name"]).strip()
        if not no or no.lower() == "nan":
            continue
        seen[no] = seen.get(no, 0) + 1
        rows.append({"student_no": no, "name": name})
    duplicates = sorted(no for no, n in seen.items() if n > 1)
    return {"rows": rows, "count": len(rows), "duplicates": duplicates, "ok": not duplicates}


def append_roster(class_id: str, path: str | Path) -> dict:
    preview = preview_roster(path)
    if preview["duplicates"]:
        raise ValueError("文件内学号重复：" + "、".join(preview["duplicates"]))
    existing = {s["student_no"]: s for s in mysql.list_class_students(class_id)}
    added = 0
    skipped: list[str] = []
    for row in preview["rows"]:
        if row["student_no"] in existing:
            skipped.append(row["student_no"])
            continue
        sid = mysql.upsert_student(row["student_no"], row["name"])
        mysql.enroll(class_id, sid)
        added += 1
    n = mysql.class_enrollment_count(class_id)
    redis_store.set_roster_gate(class_id, n > 0)
    cls = mysql.get_class(class_id)
    return {"class_id": class_id, "added": added, "skipped": skipped, "count": n, "name": (cls or {}).get("name")}


def replace_roster(class_id: str, path: str | Path, class_name: str | None = None) -> dict:
    preview = preview_roster(path)
    if preview["duplicates"]:
        raise ValueError("文件内学号重复：" + "、".join(preview["duplicates"]))
    mysql.clear_enrollments(class_id)
    if class_name:
        execute_name = mysql.get_class(class_id)
        if execute_name:
            mysql.execute(
                "UPDATE classes SET name = :name WHERE class_id = :id",
                name=class_name,
                id=class_id,
            )
    for row in preview["rows"]:
        sid = mysql.upsert_student(row["student_no"], row["name"])
        mysql.enroll(class_id, sid)
    n = mysql.class_enrollment_count(class_id)
    redis_store.set_roster_gate(class_id, n > 0)
    cls = mysql.get_class(class_id)
    return {"class_id": class_id, "count": n, "name": (cls or {}).get("name"), "replaced": True}


def export_roster_csv(class_id: str) -> str:
    students = mysql.list_class_students(class_id)
    dest = file_root() / "rosters"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{class_id}.csv"
    pd.DataFrame(students)[["student_no", "name"]].to_csv(path, index=False, encoding="utf-8-sig")
    return str(path)


def has_roster(class_id: str | None) -> bool:
    if not class_id:
        return False
    ok = mysql.class_enrollment_count(class_id) > 0
    try:
        redis_store.set_roster_gate(class_id, ok)
    except Exception:
        pass
    return ok


def require_roster(class_id: str | None) -> None:
    if not has_roster(class_id):
        raise RosterDenied()
