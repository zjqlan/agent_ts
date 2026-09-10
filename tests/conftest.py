from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

# 必须在 import zypg.config 之前切到测试库，避免 pytest 清空教师正在用的 zypg 库。
os.environ["EDUPAPER_MCP_MOCK"] = "1"
os.environ["MYSQL_DATABASE"] = "zypg_test"
os.environ["ZYPG_ALLOW_WIPE"] = "1"
os.environ.setdefault("MYSQL_ROOT_PASSWORD", "zypg")


def _dotenv_redis_url() -> str:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("REDIS_URL="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("REDIS_URL") or "redis://127.0.0.1:6380/0"


def _redis_test_url(url: str) -> str:
    base, _, query = url.strip().partition("?")
    if re.search(r"/\d+$", base):
        base = re.sub(r"/\d+$", "/15", base)
    else:
        base = base.rstrip("/") + "/15"
    return f"{base}?{query}" if query else base


os.environ["REDIS_URL"] = _redis_test_url(_dotenv_redis_url())

from zypg.llm import set_json_backend
from zypg.storage import mysql, redis_store


def canned_llm_json(user: str, system: str = "") -> dict:
    if "答题卡作答" in user or "模拟高中生" in system:
        payload: dict = {}
        try:
            payload = json.loads(user[user.find("{") :])
        except Exception:
            payload = {}
        students = payload.get("students") or []
        items = payload.get("items") or []
        obj = [i for i in items if i.get("kind") == "objective"]
        subj = [i for i in items if i.get("kind") == "subjective"]
        letters = []
        for it in obj:
            ak = it.get("answer_key") or {}
            letter = ak.get("letter") if isinstance(ak, dict) else None
            letters.append((it["item_id"], str(letter or "A")[:1]))
        wrong = {"A": "B", "B": "C", "C": "D", "D": "A"}
        out: dict = {}
        for i, stu in enumerate(students):
            no = stu["student_no"]
            if i % 3 == 0:
                bubbles = {iid: let for iid, let in letters}
                writing = {it["item_id"]: [f"{no} 写出通项", "求和得到 100"] for it in subj}
            elif i % 3 == 1:
                bubbles = {iid: wrong.get(let, "B") for iid, let in letters}
                writing = {it["item_id"]: [f"{no} 不会", "随便写了 50"] for it in subj}
            else:
                bubbles = {
                    iid: (let if j == 0 else wrong.get(let, "B")) for j, (iid, let) in enumerate(letters)
                }
                writing = {it["item_id"]: [f"{no} 只写了公式", "没算完"] for it in subj}
            out[no] = {"bubbles": bubbles, "writing": writing}
        return out
    if "出一套可批改" in user or ("questions" in system and "single_choice" in system):
        return {"title": "练习", "questions": _canned_exam_questions(user)}
    if "学期滚动" in user or ('"plan"' in system and "备课" in system):
        return {"plan": ["先补弱项等差数列", "再练等比", "每次作业后更新掌握状态"]}
    if "讲评提纲" in user or "备课教师" in system:
        return {"outline": ["先讲通项", "再对比公差公比", "当堂订正错题"], "must_teach": ["等差数列"]}
    if "补知识点" in user:
        payload: dict = {}
        try:
            payload = json.loads(user[user.find("{") :])
        except Exception:
            payload = {}
        pts = {}
        for it in payload.get("items") or []:
            iid = it.get("item_id") or "q1"
            pts[iid] = "等差数列" if "等差" in str(it.get("stem") or "") else f"第{it.get('number') or iid}题考点"
        if not pts:
            pts = {"q1": "等差数列"}
        return {"points": pts}
    if "班级统计" in user or "讲评要点" in user:
        return {
            "headline": "先订正正确率未达标的知识点，再往下讲。",
            "comment": "等差数列正确率未达标，下次课先复习通项再进入应用。全班先对一遍易错题，再点需要订正的同学。",
            "first_teach": "先讲正确率低于六成的知识点，对着错题过一遍通项。",
            "watch_who": [{"student_no": "S02", "why": "本题全错，得分低于班级均分"}],
            "next_focus": "通项公式与基本运算",
            "classroom_moves": ["投影错题订正", "同桌互查选择填涂", "课末再练两道同类题"],
            "must_teach_why": ["正确率低于60%"],
        }
    if "学生学情" in user or "个人辅导" in system:
        return {
            "headline": "先把错题订正到会讲。",
            "comment": "这份作业有明确错题，对照班级均分补漏洞即可，不必扩到整章。",
            "strengths": ["已交卡，作答完整"],
            "needs": ["错题对应知识点未过关"],
            "next_steps": ["订正错题并口述步骤", "再做两道同类题"],
        }
    if "建议分" in system or "suggested_score" in system:
        return {"suggested_score": 8, "confidence": 0.82, "comment": "步骤基本完整"}
    if "allowed_skills" in system or "口令路由" in system:
        from zypg.gateway.intent import classify, detect_skills, extract_slots

        text = user
        if "老师口令：" in user:
            text = user.split("老师口令：", 1)[1].split("\n", 1)[0]
        skills = detect_skills(text)
        intent = classify(text)
        slots = extract_slots(text)
        slim = {k: slots[k] for k in slots if k in {
            "subject", "grade", "knowledge_points", "n_objective", "n_subjective",
            "objective_points", "subjective_points", "class_name", "student_no",
            "student_ordinal", "requirement",
        }}
        return {"intent": intent.value, "skills": skills, "slots": slim}
    return {"ok": True, "comment": "ok"}


_DEFAULT_EXAM_QUESTIONS = [
    {
        "type": "single_choice",
        "content": "等差数列 2,5,8,... 的第 4 项是？",
        "options": ["11", "10", "9", "12"],
        "answer": "A",
        "points": 5,
        "knowledge_point": "等差数列",
    },
    {
        "type": "single_choice",
        "content": "等比数列 3,6,12,... 的第 4 项是？",
        "options": ["18", "20", "24", "36"],
        "answer": "C",
        "points": 5,
        "knowledge_point": "等比数列",
    },
    {
        "type": "short_answer",
        "content": "求等差数列 1,3,5,...,19 的和，并写出步骤。",
        "answer": "100",
        "points": 10,
        "knowledge_point": "数列求和",
        "rubric": ["通项或项数正确", "求和公式与结果正确"],
    },
]


def _prompt_need(user: str) -> str:
    m = re.search(r"老师出题需求：([^\n]+)", user)
    if m:
        return m.group(1).strip()
    m = re.search(r"知识点:(\[[^\]]+\]|.+?)(?:。|$)", user)
    if m:
        return m.group(1).strip()
    return ""


def _canned_exam_questions(user: str) -> list[dict]:
    n_obj, n_subj = 2, 1
    m = re.search(r"客观题(\d+)道", user)
    if m:
        n_obj = int(m.group(1))
    m = re.search(r"主观题(\d+)道", user)
    if m:
        n_subj = int(m.group(1))
    obj_pts = subj_pts = None
    m = re.search(r"客观题每题(\d+(?:\.\d+)?)分", user)
    if m:
        v = float(m.group(1))
        obj_pts = int(v) if v.is_integer() else v
    m = re.search(r"主观题每题(\d+(?:\.\d+)?)分", user)
    if m:
        v = float(m.group(1))
        subj_pts = int(v) if v.is_integer() else v
    need = _prompt_need(user)
    kp = "等差数列"
    if need:
        kp = need[:40]
    elif "二次函数" in user:
        kp = "二次函数"
    if n_obj == 2 and n_subj == 1 and obj_pts is None and subj_pts is None and "二次函数" not in need and "二次函数" not in user:
        return [dict(q) for q in _DEFAULT_EXAM_QUESTIONS]
    questions: list[dict] = []
    letters = "ABCD"
    for i in range(n_obj):
        questions.append(
            {
                "type": "single_choice",
                "content": f"{kp}练习第 {i + 1} 题。",
                "options": ["11", "10", "9", "12"],
                "answer": letters[i % 4],
                "points": 5 if obj_pts is None else obj_pts,
                "knowledge_point": kp,
            }
        )
    for i in range(n_subj):
        questions.append(
            {
                "type": "short_answer",
                "content": f"根据「{kp}」作答第 {i + 1} 题，并写出步骤。",
                "answer": "100",
                "points": 10 if subj_pts is None else subj_pts,
                "knowledge_point": kp,
                "rubric": ["通项或项数正确", "求和公式与结果正确"],
            }
        )
    return questions


@pytest.fixture(autouse=True)
def stub_llm_json():
    async def fake(user: str, system: str = "") -> dict:
        return canned_llm_json(user, system)

    set_json_backend(fake)
    yield
    set_json_backend(None)


def _ensure_test_database() -> None:
    from sqlalchemy import create_engine, text

    from zypg.config import settings

    db = settings.mysql_database
    if not str(db).endswith("_test"):
        raise RuntimeError(f"测试必须使用 *_test 库，当前是 {db}")
    if not re.fullmatch(r"[A-Za-z0-9_]+", db):
        raise RuntimeError(f"非法测试库名 {db}")
    user = settings.mysql_user
    if not re.fullmatch(r"[A-Za-z0-9_]+", user):
        raise RuntimeError(f"非法 MySQL 用户 {user}")
    root_pw = os.environ.get("MYSQL_ROOT_PASSWORD") or "zypg"
    admin = create_engine(
        f"mysql+pymysql://root:{root_pw}@{settings.mysql_host}:{settings.mysql_port}/?charset=utf8mb4",
        isolation_level="AUTOCOMMIT",
        future=True,
    )
    try:
        with admin.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{db}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            conn.execute(text(f"GRANT ALL PRIVILEGES ON `{db}`.* TO '{user}'@'%'"))
            conn.execute(text("FLUSH PRIVILEGES"))
    finally:
        admin.dispose()
    mysql.reset_engine()
    redis_store.reset()


@pytest.fixture(scope="session")
def infra():
    last = None
    for _ in range(60):
        try:
            _ensure_test_database()
            mysql.apply_schema()
            mysql.ping()
            redis_store.ping()
            return True
        except Exception as exc:
            last = exc
            time.sleep(1)
    pytest.fail(f"MySQL / Redis 未就绪: {last}")


@pytest.fixture
def db(infra):
    mysql.wipe_all()
    redis_store.client().flushdb()
    yield
    mysql.wipe_all()
