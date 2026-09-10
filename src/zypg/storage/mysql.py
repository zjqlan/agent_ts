from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from zypg.config import ROOT, settings

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def dumps_row(row: Any) -> dict[str, Any]:
    data = dict(row._mapping)
    for k, v in list(data.items()):
        if isinstance(v, Decimal):
            data[k] = float(v)
        elif isinstance(v, datetime):
            data[k] = v.isoformat(sep=" ", timespec="seconds")
        elif isinstance(v, date):
            data[k] = v.isoformat()
        elif isinstance(v, (bytes, bytearray)):
            data[k] = v.decode("utf-8")
        elif isinstance(v, str) and k in {
            "knowledge_points",
            "extra",
            "options",
            "answer_key",
            "rubric",
            "geometry",
            "raw",
            "payload",
            "result",
        }:
            try:
                data[k] = json.loads(v)
            except json.JSONDecodeError:
                pass
    return data


def get_engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(
            settings.mysql_dsn,
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
        )
        _Session = sessionmaker(_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine() -> None:
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


@contextmanager
def session() -> Iterator[Session]:
    get_engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def ping() -> bool:
    with session() as s:
        s.execute(text("SELECT 1"))
    return True


def apply_schema() -> None:
    sql_path = ROOT / "sql" / "schema.sql"
    raw = sql_path.read_text(encoding="utf-8")
    statements: list[str] = []
    buf: list[str] = []
    for line in raw.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.strip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";")
            buf = []
            if stmt:
                statements.append(stmt)
    if buf and "".join(buf).strip():
        statements.append("\n".join(buf).strip().rstrip(";"))
    eng = get_engine()
    with eng.begin() as conn:
        for stmt in statements:
            if stmt.upper().startswith("SET "):
                conn.exec_driver_sql(stmt)
            else:
                conn.exec_driver_sql(stmt)
    _ensure_columns()


def _ensure_columns() -> None:
    row = fetch_one(
        """
        SELECT COUNT(*) AS n FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'assignments' AND COLUMN_NAME = 'created_at'
        """
    )
    if row and int(row["n"] or 0) == 0:
        execute("ALTER TABLE assignments ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")
    execute(
        """
        CREATE TABLE IF NOT EXISTS teachers (
          teacher_id VARCHAR(64) NOT NULL PRIMARY KEY,
          username VARCHAR(64) NOT NULL,
          password_hash VARCHAR(255) NOT NULL,
          display_name VARCHAR(255) NOT NULL,
          subject VARCHAR(32) NULL,
          last_class_id VARCHAR(64) NULL,
          last_homework_id VARCHAR(64) NULL,
          last_page VARCHAR(32) NULL,
          UNIQUE KEY uk_teachers_username (username)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    subj_col = fetch_one(
        """
        SELECT COUNT(*) AS n FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teachers' AND COLUMN_NAME = 'subject'
        """
    )
    if subj_col and int(subj_col["n"] or 0) == 0:
        execute("ALTER TABLE teachers ADD COLUMN subject VARCHAR(32) NULL")
    col = fetch_one(
        """
        SELECT COUNT(*) AS n FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'classes' AND COLUMN_NAME = 'teacher_id'
        """
    )
    if col and int(col["n"] or 0) == 0:
        execute("ALTER TABLE classes ADD COLUMN teacher_id VARCHAR(64) NULL")
        try:
            execute("ALTER TABLE classes ADD INDEX idx_classes_teacher (teacher_id)")
        except Exception:
            pass
    execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_sessions (
          token VARCHAR(128) NOT NULL PRIMARY KEY,
          teacher_id VARCHAR(64) NOT NULL,
          expires_at DATETIME NOT NULL,
          KEY idx_teacher_sessions_teacher (teacher_id),
          KEY idx_teacher_sessions_exp (expires_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    from zypg.auth import seed_default_teacher

    seed_default_teacher()


def fetch_all(sql: str, **params: Any) -> list[dict[str, Any]]:
    with session() as s:
        rows = s.execute(text(sql), params).fetchall()
        return [dumps_row(r) for r in rows]


def fetch_one(sql: str, **params: Any) -> dict[str, Any] | None:
    rows = fetch_all(sql, **params)
    return rows[0] if rows else None


def execute(sql: str, **params: Any) -> None:
    with session() as s:
        s.execute(text(sql), params)


def execute_many(sql: str, param_list: list[dict[str, Any]]) -> None:
    with session() as s:
        for p in param_list:
            s.execute(text(sql), p)


def insert_class(
    class_id: str,
    name: str,
    grade: str | None,
    subject: str | None,
    teacher_id: str | None = None,
) -> None:
    execute(
        """
        INSERT INTO classes (class_id, name, grade, subject, teacher_id)
        VALUES (:class_id, :name, :grade, :subject, :teacher_id)
        """,
        class_id=class_id,
        name=name,
        grade=grade,
        subject=subject,
        teacher_id=teacher_id,
    )


def update_class_subject(class_id: str, subject: str) -> None:
    execute(
        "UPDATE classes SET subject = :subject WHERE class_id = :id",
        id=class_id,
        subject=subject,
    )


def insert_student(student_id: str, student_no: str, name: str) -> None:
    execute(
        """
        INSERT INTO students (student_id, student_no, name)
        VALUES (:student_id, :student_no, :name)
        ON DUPLICATE KEY UPDATE name = VALUES(name), student_id = student_id
        """,
        student_id=student_id,
        student_no=student_no,
        name=name,
    )


def upsert_student(student_no: str, name: str) -> str:
    row = fetch_one("SELECT student_id FROM students WHERE student_no = :no", no=student_no)
    if row:
        execute("UPDATE students SET name = :name WHERE student_no = :no", name=name, no=student_no)
        return str(row["student_id"])
    import uuid

    sid = uuid.uuid4().hex
    insert_student(sid, student_no, name)
    return sid


def enroll(class_id: str, student_id: str) -> None:
    execute(
        """
        INSERT IGNORE INTO enrollments (class_id, student_id)
        VALUES (:class_id, :student_id)
        """,
        class_id=class_id,
        student_id=student_id,
    )


def class_enrollment_count(class_id: str) -> int:
    row = fetch_one(
        "SELECT COUNT(*) AS n FROM enrollments WHERE class_id = :class_id",
        class_id=class_id,
    )
    return int(row["n"] if row else 0)


def list_class_students(class_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT s.student_id, s.student_no, s.name
        FROM enrollments e
        JOIN students s ON s.student_id = e.student_id
        WHERE e.class_id = :class_id
        ORDER BY s.student_no
        """,
        class_id=class_id,
    )


def get_class(class_id: str) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM classes WHERE class_id = :id", id=class_id)


def insert_assignment(
    homework_id: str,
    class_id: str,
    name: str,
    subject: str | None,
    knowledge_points: list[str],
    paper_path: str | None,
    extra: dict[str, Any] | None,
) -> None:
    execute(
        """
        INSERT INTO assignments (homework_id, class_id, name, subject, knowledge_points, paper_path, extra)
        VALUES (:homework_id, :class_id, :name, :subject, :knowledge_points, :paper_path, :extra)
        """,
        homework_id=homework_id,
        class_id=class_id,
        name=name,
        subject=subject,
        knowledge_points=_jsonable(knowledge_points),
        paper_path=paper_path,
        extra=_jsonable(extra or {}),
    )


def insert_item(row: dict[str, Any]) -> None:
    execute(
        """
        INSERT INTO items (homework_id, item_id, kind, number, stem, options, answer_key, rubric, knowledge_point, score)
        VALUES (:homework_id, :item_id, :kind, :number, :stem, :options, :answer_key, :rubric, :knowledge_point, :score)
        """,
        homework_id=row["homework_id"],
        item_id=row["item_id"],
        kind=row["kind"],
        number=row["number"],
        stem=row.get("stem"),
        options=_jsonable(row.get("options")),
        answer_key=_jsonable(row.get("answer_key")),
        rubric=_jsonable(row.get("rubric")),
        knowledge_point=row.get("knowledge_point"),
        score=row.get("score"),
    )


def get_assignment(homework_id: str) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM assignments WHERE homework_id = :id", id=homework_id)


def update_assignment_name(homework_id: str, name: str) -> None:
    execute(
        "UPDATE assignments SET name = :name WHERE homework_id = :id",
        id=homework_id,
        name=name,
    )


def delete_homework(homework_id: str) -> None:
    with session() as s:
        s.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        convs = s.execute(
            text("SELECT conversation_id FROM conversations WHERE homework_id = :hw"),
            {"hw": homework_id},
        ).mappings().all()
        for row in convs:
            s.execute(text("DELETE FROM messages WHERE conversation_id = :cid"), {"cid": row["conversation_id"]})
        for sql in (
            "DELETE FROM conversations WHERE homework_id = :hw",
            "DELETE FROM a2a_tasks WHERE homework_id = :hw",
            "DELETE FROM embedding_meta WHERE homework_id = :hw",
            "DELETE FROM mastery_events WHERE homework_id = :hw",
            "DELETE FROM insight_snapshots WHERE homework_id = :hw",
            "DELETE FROM review_queue WHERE homework_id = :hw",
            "DELETE FROM item_results WHERE homework_id = :hw",
            "DELETE FROM scans WHERE homework_id = :hw",
            "DELETE FROM card_templates WHERE homework_id = :hw",
            "DELETE FROM items WHERE homework_id = :hw",
            "DELETE FROM assignments WHERE homework_id = :hw",
            "UPDATE teachers SET last_homework_id = NULL WHERE last_homework_id = :hw",
        ):
            s.execute(text(sql), {"hw": homework_id})
        s.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def get_message(message_id: int) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM messages WHERE id = :id", id=message_id)


def update_message_content(message_id: int, content: str) -> None:
    execute("UPDATE messages SET content = :c WHERE id = :id", id=message_id, c=content)


def delete_message(message_id: int) -> None:
    execute("DELETE FROM messages WHERE id = :id", id=message_id)


def list_items(homework_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT * FROM items WHERE homework_id = :id ORDER BY number",
        id=homework_id,
    )


def upsert_card_template(homework_id: str, geometry: dict[str, Any], print_path: str) -> None:
    execute(
        """
        INSERT INTO card_templates (homework_id, geometry, print_path)
        VALUES (:homework_id, :geometry, :print_path)
        ON DUPLICATE KEY UPDATE geometry = VALUES(geometry), print_path = VALUES(print_path)
        """,
        homework_id=homework_id,
        geometry=_jsonable(geometry),
        print_path=print_path,
    )


def get_card_template(homework_id: str) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM card_templates WHERE homework_id = :id", id=homework_id)


def insert_scan(homework_id: str, student_id: str | None, file_path: str, status: str) -> int:
    with session() as s:
        s.execute(
            text(
                """
                INSERT INTO scans (homework_id, student_id, file_path, status)
                VALUES (:homework_id, :student_id, :file_path, :status)
                """
            ),
            {
                "homework_id": homework_id,
                "student_id": student_id,
                "file_path": file_path,
                "status": status,
            },
        )
        row = s.execute(text("SELECT LAST_INSERT_ID() AS id")).one()
        return int(row._mapping["id"])


def replace_item_result(row: dict[str, Any]) -> None:
    execute(
        """
        INSERT INTO item_results
          (homework_id, student_id, item_id, raw, score, is_correct, source, pending)
        VALUES
          (:homework_id, :student_id, :item_id, :raw, :score, :is_correct, :source, :pending)
        ON DUPLICATE KEY UPDATE
          raw = VALUES(raw), score = VALUES(score), is_correct = VALUES(is_correct),
          source = VALUES(source), pending = VALUES(pending)
        """,
        homework_id=row["homework_id"],
        student_id=row["student_id"],
        item_id=row["item_id"],
        raw=_jsonable(row.get("raw")),
        score=row.get("score"),
        is_correct=row.get("is_correct"),
        source=row["source"],
        pending=int(row.get("pending", 1)),
    )


def insert_review(
    homework_id: str,
    student_id: str | None,
    item_id: str | None,
    reason: str,
    suggested_score: float | None,
) -> None:
    execute(
        """
        INSERT INTO review_queue (homework_id, student_id, item_id, reason, suggested_score, status)
        VALUES (:homework_id, :student_id, :item_id, :reason, :suggested_score, 'open')
        """,
        homework_id=homework_id,
        student_id=student_id,
        item_id=item_id,
        reason=reason,
        suggested_score=suggested_score,
    )


def list_open_reviews(homework_id: str | None = None, class_id: str | None = None) -> list[dict[str, Any]]:
    if homework_id:
        return fetch_all(
            "SELECT * FROM review_queue WHERE homework_id = :hw AND status = 'open' ORDER BY id",
            hw=homework_id,
        )
    if class_id:
        return fetch_all(
            """
            SELECT r.* FROM review_queue r
            JOIN assignments a ON a.homework_id = r.homework_id
            WHERE a.class_id = :cid AND r.status = 'open'
            ORDER BY r.id
            """,
            cid=class_id,
        )
    return fetch_all("SELECT * FROM review_queue WHERE status = 'open' ORDER BY id")


def get_review(review_id: int) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM review_queue WHERE id = :id", id=review_id)


def update_review(review_id: int, status: str) -> None:
    execute("UPDATE review_queue SET status = :st WHERE id = :id", st=status, id=review_id)


def list_item_results(homework_id: str, student_id: str | None = None) -> list[dict[str, Any]]:
    if student_id:
        return fetch_all(
            """
            SELECT * FROM item_results
            WHERE homework_id = :hw AND student_id = :sid
            """,
            hw=homework_id,
            sid=student_id,
        )
    return fetch_all("SELECT * FROM item_results WHERE homework_id = :hw", hw=homework_id)


def list_classes(teacher_id: str | None = None) -> list[dict[str, Any]]:
    where = ""
    params: dict[str, Any] = {}
    if teacher_id:
        where = "WHERE (c.teacher_id = :tid OR c.teacher_id IS NULL OR c.teacher_id = '')"
        params["tid"] = teacher_id
    return fetch_all(
        f"""
        SELECT c.class_id, c.name, c.grade, c.subject, c.teacher_id, COUNT(e.student_id) AS n_students
        FROM classes c
        LEFT JOIN enrollments e ON e.class_id = c.class_id
        {where}
        GROUP BY c.class_id, c.name, c.grade, c.subject, c.teacher_id
        ORDER BY c.name
        """,
        **params,
    )


def bind_class_teacher(class_id: str, teacher_id: str) -> None:
    execute(
        """
        UPDATE classes
        SET teacher_id = :tid
        WHERE class_id = :cid AND (teacher_id IS NULL OR teacher_id = '' OR teacher_id = :tid)
        """,
        cid=class_id,
        tid=teacher_id,
    )


def claim_orphan_classes(teacher_id: str) -> None:
    execute(
        """
        UPDATE classes
        SET teacher_id = :tid
        WHERE teacher_id IS NULL OR teacher_id = ''
        """,
        tid=teacher_id,
    )


def list_homeworks(class_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM assignments
        WHERE class_id = :cid
        ORDER BY created_at DESC, homework_id DESC
        """,
        cid=class_id,
    )


def insert_snapshot(
    homework_id: str | None,
    class_id: str,
    scope: str,
    window: str,
    student_id: str | None,
    payload: dict[str, Any],
) -> None:
    execute(
        """
        INSERT INTO insight_snapshots (homework_id, class_id, scope, `window`, student_id, payload)
        VALUES (:homework_id, :class_id, :scope, :window, :student_id, :payload)
        """,
        homework_id=homework_id,
        class_id=class_id,
        scope=scope,
        window=window,
        student_id=student_id,
        payload=_jsonable(payload),
    )


def latest_snapshots(class_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM insight_snapshots
        WHERE class_id = :cid
        ORDER BY id DESC
        LIMIT 40
        """,
        cid=class_id,
    )


def insert_mastery(student_id: str, homework_id: str, knowledge_point: str, mastery: str) -> None:
    execute(
        """
        INSERT INTO mastery_events (student_id, homework_id, knowledge_point, mastery)
        VALUES (:student_id, :homework_id, :knowledge_point, :mastery)
        """,
        student_id=student_id,
        homework_id=homework_id,
        knowledge_point=knowledge_point,
        mastery=mastery,
    )


def delete_mastery_for_homework(homework_id: str) -> None:
    execute("DELETE FROM mastery_events WHERE homework_id = :hw", hw=homework_id)


def list_mastery(class_id: str, student_id: str | None = None) -> list[dict[str, Any]]:
    if student_id:
        return fetch_all(
            """
            SELECT m.* FROM mastery_events m
            JOIN assignments a ON a.homework_id = m.homework_id
            WHERE a.class_id = :cid AND m.student_id = :sid
            ORDER BY m.id
            """,
            cid=class_id,
            sid=student_id,
        )
    return fetch_all(
        """
        SELECT m.* FROM mastery_events m
        JOIN assignments a ON a.homework_id = m.homework_id
        WHERE a.class_id = :cid
        ORDER BY m.id
        """,
        cid=class_id,
    )


def insert_conversation(conversation_id: str, homework_id: str | None, class_id: str | None) -> None:
    execute(
        """
        INSERT IGNORE INTO conversations (conversation_id, homework_id, class_id)
        VALUES (:conversation_id, :homework_id, :class_id)
        """,
        conversation_id=conversation_id,
        homework_id=homework_id,
        class_id=class_id,
    )


def insert_message(conversation_id: str, role: str, content: str) -> None:
    execute(
        """
        INSERT INTO messages (conversation_id, role, content)
        VALUES (:conversation_id, :role, :content)
        """,
        conversation_id=conversation_id,
        role=role,
        content=content,
    )


def list_messages(conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM (
          SELECT * FROM messages WHERE conversation_id = :cid ORDER BY id DESC LIMIT :lim
        ) t ORDER BY id
        """,
        cid=conversation_id,
        lim=limit,
    )


def upsert_a2a_task(
    task_id: str,
    homework_id: str | None,
    skill: str,
    status: str,
    payload: dict[str, Any] | None,
    result: dict[str, Any] | None,
) -> None:
    execute(
        """
        INSERT INTO a2a_tasks (task_id, homework_id, skill, status, payload, result)
        VALUES (:task_id, :homework_id, :skill, :status, :payload, :result)
        ON DUPLICATE KEY UPDATE
          status = VALUES(status), result = VALUES(result), payload = VALUES(payload)
        """,
        task_id=task_id,
        homework_id=homework_id,
        skill=skill,
        status=status,
        payload=_jsonable(payload),
        result=_jsonable(result),
    )


def fail_working_tasks(reason: str = "interrupted") -> int:
    rows = fetch_all("SELECT task_id FROM a2a_tasks WHERE status = 'working'")
    for row in rows:
        execute(
            """
            UPDATE a2a_tasks
            SET status = 'failed', result = :result
            WHERE task_id = :id AND status = 'working'
            """,
            id=row["task_id"],
            result=_jsonable({"error": reason}),
        )
    return len(rows)


def get_a2a_task(task_id: str) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM a2a_tasks WHERE task_id = :id", id=task_id)


def next_faiss_id() -> int:
    row = fetch_one("SELECT COALESCE(MAX(faiss_id), -1) AS m FROM embedding_meta")
    return int(row["m"] if row else -1) + 1


def insert_embedding_meta(
    faiss_id: int,
    kind: str,
    ref_id: str,
    homework_id: str | None,
    text_hash: str,
) -> None:
    execute(
        """
        INSERT INTO embedding_meta (faiss_id, kind, ref_id, homework_id, text_hash)
        VALUES (:faiss_id, :kind, :ref_id, :homework_id, :text_hash)
        """,
        faiss_id=faiss_id,
        kind=kind,
        ref_id=ref_id,
        homework_id=homework_id,
        text_hash=text_hash,
    )


def list_embedding_meta() -> list[dict[str, Any]]:
    return fetch_all("SELECT * FROM embedding_meta ORDER BY faiss_id")


def student_by_no(student_no: str) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM students WHERE student_no = :no", no=student_no)


def student_by_id(student_id: str) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM students WHERE student_id = :id", id=student_id)


def list_scans(homework_id: str) -> list[dict[str, Any]]:
    return fetch_all("SELECT * FROM scans WHERE homework_id = :hw", hw=homework_id)


def commit_grade_batch(
    scans: list[dict[str, Any]],
    results: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> None:
    with session() as s:
        for sc in scans:
            s.execute(
                text(
                    """
                    INSERT INTO scans (homework_id, student_id, file_path, status)
                    VALUES (:homework_id, :student_id, :file_path, :status)
                    """
                ),
                sc,
            )
        for row in results:
            s.execute(
                text(
                    """
                    INSERT INTO item_results
                      (homework_id, student_id, item_id, raw, score, is_correct, source, pending)
                    VALUES
                      (:homework_id, :student_id, :item_id, :raw, :score, :is_correct, :source, :pending)
                    ON DUPLICATE KEY UPDATE
                      raw = VALUES(raw), score = VALUES(score), is_correct = VALUES(is_correct),
                      source = VALUES(source), pending = VALUES(pending)
                    """
                ),
                {
                    **row,
                    "raw": _jsonable(row.get("raw")),
                    "pending": int(row.get("pending", 1)),
                },
            )
        for q in reviews:
            s.execute(
                text(
                    """
                    INSERT INTO review_queue
                      (homework_id, student_id, item_id, reason, suggested_score, status)
                    VALUES
                      (:homework_id, :student_id, :item_id, :reason, :suggested_score, 'open')
                    """
                ),
                q,
            )


def update_item_fields(
    homework_id: str,
    item_id: str,
    answer_key: Any = None,
    rubric: Any = None,
    stem: str | None = None,
    knowledge_point: str | None = None,
    score: float | None = None,
) -> None:
    row = fetch_one(
        "SELECT * FROM items WHERE homework_id = :hw AND item_id = :iid",
        hw=homework_id,
        iid=item_id,
    )
    if not row:
        raise KeyError(item_id)
    execute(
        """
        UPDATE items SET
          answer_key = :answer_key,
          rubric = :rubric,
          stem = :stem,
          knowledge_point = :knowledge_point,
          score = :score
        WHERE homework_id = :hw AND item_id = :iid
        """,
        hw=homework_id,
        iid=item_id,
        answer_key=_jsonable(answer_key if answer_key is not None else row.get("answer_key")),
        rubric=_jsonable(rubric if rubric is not None else row.get("rubric")),
        stem=stem if stem is not None else row.get("stem"),
        knowledge_point=knowledge_point if knowledge_point is not None else row.get("knowledge_point"),
        score=score if score is not None else row.get("score"),
    )


def clear_enrollments(class_id: str) -> None:
    execute("DELETE FROM enrollments WHERE class_id = :cid", cid=class_id)


def unenroll(class_id: str, student_id: str) -> None:
    execute(
        "DELETE FROM enrollments WHERE class_id = :cid AND student_id = :sid",
        cid=class_id,
        sid=student_id,
    )


def find_conversation(class_id: str | None, homework_id: str | None) -> dict[str, Any] | None:
    if homework_id:
        return fetch_one(
            "SELECT * FROM conversations WHERE homework_id = :hw LIMIT 1",
            hw=homework_id,
        )
    if class_id:
        return fetch_one(
            """
            SELECT * FROM conversations
            WHERE class_id = :cid AND (homework_id IS NULL OR homework_id = '')
            LIMIT 1
            """,
            cid=class_id,
        )
    return fetch_one(
        """
        SELECT * FROM conversations
        WHERE (class_id IS NULL OR class_id = '') AND (homework_id IS NULL OR homework_id = '')
        LIMIT 1
        """
    )


def bind_conversation(conversation_id: str, homework_id: str | None, class_id: str | None) -> None:
    execute(
        """
        UPDATE conversations
        SET homework_id = COALESCE(:hw, homework_id), class_id = COALESCE(:cid, class_id)
        WHERE conversation_id = :id
        """,
        id=conversation_id,
        hw=homework_id,
        cid=class_id,
    )


def list_working_tasks(homework_id: str | None = None, class_id: str | None = None) -> list[dict[str, Any]]:
    if homework_id:
        return fetch_all(
            "SELECT * FROM a2a_tasks WHERE status = 'working' AND homework_id = :hw",
            hw=homework_id,
        )
    if class_id:
        return fetch_all(
            """
            SELECT t.* FROM a2a_tasks t
            LEFT JOIN assignments a ON a.homework_id = t.homework_id
            WHERE t.status = 'working' AND (a.class_id = :cid OR t.homework_id IS NULL)
            """,
            cid=class_id,
        )
    return fetch_all("SELECT * FROM a2a_tasks WHERE status = 'working'")


def count_open_reviews(homework_id: str | None = None, class_id: str | None = None) -> int:
    return len(list_open_reviews(homework_id=homework_id, class_id=class_id))


def has_class_insight(class_id: str, homework_id: str | None) -> bool:
    if homework_id:
        row = fetch_one(
            """
            SELECT id FROM insight_snapshots
            WHERE class_id = :cid AND homework_id = :hw AND scope = 'class' AND `window` = 'short'
            LIMIT 1
            """,
            cid=class_id,
            hw=homework_id,
        )
        return bool(row)
    row = fetch_one(
        """
        SELECT id FROM insight_snapshots
        WHERE class_id = :cid AND scope = 'class' AND `window` = 'short'
        LIMIT 1
        """,
        cid=class_id,
    )
    return bool(row)


def latest_class_snapshot(class_id: str, window: str = "short") -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT * FROM insight_snapshots
        WHERE class_id = :cid AND scope = 'class' AND `window` = :win
        ORDER BY id DESC LIMIT 1
        """,
        cid=class_id,
        win=window,
    )


def latest_student_snapshot(class_id: str, student_id: str, window: str = "short") -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT * FROM insight_snapshots
        WHERE class_id = :cid AND student_id = :sid AND scope = 'student' AND `window` = :win
        ORDER BY id DESC LIMIT 1
        """,
        cid=class_id,
        sid=student_id,
        win=window,
    )


def wipe_all() -> None:
    db = str(settings.mysql_database or "")
    allow = os.environ.get("ZYPG_ALLOW_WIPE", "").strip().lower() in {"1", "true", "yes"}
    if not allow or not db.endswith("_test"):
        raise RuntimeError(
            f"拒绝清空业务库 {db!r}。pytest 必须使用 MYSQL_DATABASE=zypg_test 且 ZYPG_ALLOW_WIPE=1"
        )
    tables = [
        "messages",
        "conversations",
        "embedding_meta",
        "a2a_tasks",
        "mastery_events",
        "insight_snapshots",
        "review_queue",
        "item_results",
        "scans",
        "card_templates",
        "items",
        "assignments",
        "enrollments",
        "students",
        "classes",
        "teacher_sessions",
        "teachers",
    ]
    with session() as s:
        s.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for t in tables:
            s.execute(text(f"TRUNCATE TABLE {t}"))
        s.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def insert_teacher(
    teacher_id: str,
    username: str,
    password_hash: str,
    display_name: str,
    subject: str | None = None,
) -> None:
    execute(
        """
        INSERT INTO teachers (teacher_id, username, password_hash, display_name, subject)
        VALUES (:teacher_id, :username, :password_hash, :display_name, :subject)
        """,
        teacher_id=teacher_id,
        username=username,
        password_hash=password_hash,
        display_name=display_name,
        subject=subject or None,
    )


def update_teacher_subject(teacher_id: str, subject: str) -> None:
    execute(
        "UPDATE teachers SET subject = :subject WHERE teacher_id = :id",
        id=teacher_id,
        subject=subject,
    )


def get_teacher(teacher_id: str) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM teachers WHERE teacher_id = :id", id=teacher_id)


def get_teacher_by_username(username: str) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM teachers WHERE username = :u", u=username)


def update_teacher_context(
    teacher_id: str,
    class_id: str | None,
    homework_id: str | None,
    page: str | None,
) -> None:
    execute(
        """
        UPDATE teachers
        SET last_class_id = :cid, last_homework_id = :hw, last_page = :page
        WHERE teacher_id = :id
        """,
        id=teacher_id,
        cid=class_id or None,
        hw=homework_id or None,
        page=page or None,
    )


def insert_teacher_session(token: str, teacher_id: str, ttl_seconds: int) -> None:
    execute(
        """
        INSERT INTO teacher_sessions (token, teacher_id, expires_at)
        VALUES (:token, :teacher_id, DATE_ADD(NOW(), INTERVAL :ttl SECOND))
        ON DUPLICATE KEY UPDATE teacher_id = VALUES(teacher_id), expires_at = VALUES(expires_at)
        """,
        token=token,
        teacher_id=teacher_id,
        ttl=int(ttl_seconds),
    )


def get_teacher_session(token: str) -> str | None:
    row = fetch_one(
        """
        SELECT teacher_id FROM teacher_sessions
        WHERE token = :token AND expires_at > NOW()
        """,
        token=token,
    )
    return str(row["teacher_id"]) if row else None


def delete_teacher_session(token: str) -> None:
    execute("DELETE FROM teacher_sessions WHERE token = :token", token=token)


def touch_teacher_session(token: str, ttl_seconds: int) -> None:
    execute(
        """
        UPDATE teacher_sessions
        SET expires_at = DATE_ADD(NOW(), INTERVAL :ttl SECOND)
        WHERE token = :token
        """,
        token=token,
        ttl=int(ttl_seconds),
    )
