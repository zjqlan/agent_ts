from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from zypg.agents.base import PeerAgent
from zypg.models import A2AMessage, HomeworkArtifact
from zypg.protocol.mcp import call_internal
from zypg.roster.service import require_roster
from zypg.storage import faiss_index, mysql
from zypg.storage.files import abspath, homework_dir, paper_docx_url, relpath
from zypg.llm import LLMError, complete_json


class HomeworkAgent(PeerAgent):
    name = "homework"
    description = "作业生成：出题或导入试卷"

    def skills(self) -> list[str]:
        return ["generate_paper", "import_paper"]

    async def handle(self, message: A2AMessage) -> dict[str, Any]:
        p = message.payload
        require_roster(p.get("class_id"))
        if message.skill == "import_paper":
            return await self._import(p)
        if message.skill == "generate_paper":
            return await self._generate(p)
        raise ValueError(f"unknown skill {message.skill}")

    async def _generate(self, p: dict[str, Any]) -> dict[str, Any]:
        class_id = p["class_id"]
        from zypg.subject import require_same_subject

        subject = require_same_subject(p.get("teacher_id"), p.get("subject"), verb="生成") or p.get("subject") or "数学"
        grade = p.get("grade") or "高中"
        kps = p.get("knowledge_points") or ["未指定知识点"]
        if isinstance(kps, str):
            kps = [x.strip() for x in re.split(r"[,，、]+", kps) if x.strip()] or [kps]
        asked_obj = "n_objective" in p
        asked_subj = "n_subjective" in p
        n_obj = int(p["n_objective"]) if asked_obj else 2
        n_subj = int(p["n_subjective"]) if asked_subj else 1
        obj_pts = p.get("objective_points")
        subj_pts = p.get("subjective_points")
        requirement = (p.get("requirement") or p.get("text") or "").strip()
        questions: list[dict[str, Any]]
        llm_model = None
        supplied = bool(p.get("questions"))
        if p.get("questions"):
            questions = [_normalize_question(q) for q in p["questions"]]
        elif p.get("skip_llm"):
            questions = []
        else:
            from zypg.config import settings as _settings

            pts = ""
            if obj_pts is not None:
                pts += f"客观题每题{obj_pts}分。"
            if subj_pts is not None:
                pts += f"主观题每题{subj_pts}分。"
            need_block = requirement or f"围绕知识点 {kps} 出题。"
            try:
                data = await complete_json(
                    (
                        f"为{grade}{subject}出一套可批改的练习。"
                        f"老师出题需求：{need_block}\n"
                        f"作业名：{p.get('name') or '练习'}。知识点:{kps}。"
                        f"客观题{n_obj}道四选一，主观题{n_subj}道。"
                        f"必须恰好这些题，questions 里 single_choice {n_obj} 道、short_answer {n_subj} 道。"
                        "题干、情境、考点必须紧扣老师需求，不要换成无关知识点。"
                        + pts
                        + "客观题必须有唯一正确答案字母；主观题必须有参考解答和评分点 rubric。"
                    ),
                    system=(
                        "你是高中教师。只输出 JSON："
                        '{"title":str,"questions":[{"type":"single_choice"|"short_answer",'
                        '"content":str,"options":[str],"answer":str,"points":number,'
                        '"knowledge_point":str,"rubric":[str]}]}。'
                        "single_choice 的 options 恰好 4 项，answer 为 A/B/C/D。"
                        "content 必须体现老师出题需求中的知识点、难度和情境，禁止套用无关例题。"
                        "禁止人格、家庭、心理、高考预测。"
                    ),
                    temperature=0.5,
                    require=True,
                )
            except LLMError as exc:
                return {"ok": False, "error": str(exc), "gradeable": False}
            raw_qs = data.get("questions") or []
            if isinstance(raw_qs, dict):
                raw_qs = list(raw_qs.values())
            questions = [_normalize_question(q) for q in raw_qs if isinstance(q, dict)]
            llm_model = _settings.llm_model
        if not questions:
            return {
                "ok": False,
                "error": "大模型未返回题目。不会用示例卷凑数。请重试或导入试卷。",
                "gradeable": False,
            }
        if not supplied:
            mismatch = _count_mismatch(questions, n_obj, n_subj)
            if mismatch:
                return {"ok": False, "error": mismatch, "gradeable": False}
        layout = await call_internal(
            "generate_exam_paper",
            {
                "title": p.get("name") or f"{subject}练习",
                "questions": questions,
            },
        )
        items = _questions_to_items(questions, objective_points=obj_pts, subjective_points=subj_pts)
        out = _persist(class_id, p.get("name") or layout.get("title") or "练习", subject, items, layout)
        if llm_model:
            out["llm_model"] = llm_model
            out["source"] = "llm"
        return out

    async def _import(self, p: dict[str, Any]) -> dict[str, Any]:
        class_id = p["class_id"]
        raw_path = p.get("path") or p.get("paper_path")
        if not raw_path:
            raise ValueError("请在对话中附上 md/docx/pdf，或说「导入示例试卷」")
        src = Path(raw_path)
        if not src.is_file():
            src = Path(abspath(str(raw_path)))
        if not src.is_file():
            raise ValueError(f"试卷文件不存在：{raw_path}")
        parsed = await call_internal("parse_paper", {"path": str(src)})
        from zypg.subject import require_same_subject

        subject = require_same_subject(
            p.get("teacher_id"),
            parsed.get("subject") or p.get("subject"),
            verb="导入",
        ) or parsed.get("subject") or p.get("subject")
        homework_id = uuid.uuid4().hex
        dest = homework_dir(homework_id, "papers") / src.name
        dest.write_bytes(src.read_bytes())
        extra_path = relpath(dest)
        return _persist(
            class_id,
            parsed.get("name") or src.stem,
            subject,
            parsed.get("items") or [],
            {"paper_path": extra_path},
            homework_id=homework_id,
        )


_OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "true_false"}
_TYPE_ALIASES = {
    "choice": "single_choice",
    "single": "single_choice",
    "mcq": "single_choice",
    "multi": "multiple_choice",
    "tf": "true_false",
    "truefalse": "true_false",
    "fill": "fill_in_blank",
    "blank": "fill_in_blank",
    "qa": "short_answer",
    "essay": "short_answer",
    "选择题": "single_choice",
    "单选题": "single_choice",
    "多选题": "multiple_choice",
    "判断题": "true_false",
    "填空题": "fill_in_blank",
    "简答题": "short_answer",
    "解答题": "short_answer",
    "主观题": "short_answer",
    "客观题": "single_choice",
}


def _normalize_question(q: dict[str, Any]) -> dict[str, Any]:
    out = dict(q)
    raw = str(out.get("type") or "short_answer").strip().lower()
    out["type"] = _TYPE_ALIASES.get(raw, _TYPE_ALIASES.get(str(out.get("type") or "").strip(), raw))
    if out.get("content") is None and out.get("stem"):
        out["content"] = out["stem"]
    return out


def _objective_letter(q: dict[str, Any]) -> str | None:
    ans = q.get("answer")
    if ans is None or str(ans).strip() == "":
        return None
    text = str(ans).strip()
    up = text.upper()
    if up[:1] in "ABCD" and (len(up) == 1 or not up[1].isalnum()):
        return up[:1]
    options = q.get("options") or []
    for i, opt in enumerate(options):
        letter = chr(ord("A") + i)
        opt_s = str(opt).strip()
        opt_up = opt_s.upper()
        body = re.sub(r"^[A-D][\.、:：\s]+", "", opt_s, flags=re.I).strip()
        if text == opt_s or up == opt_up or text == body or up == body.upper():
            return letter
        if opt_up.startswith(up[:1] + ".") or opt_up.startswith(up[:1] + "、"):
            if up[:1] in "ABCD":
                return up[:1]
    return up[:1] if up[:1] in "ABCD" else None


def _count_mismatch(questions: list[dict[str, Any]], n_obj: int, n_subj: int) -> str | None:
    obj_got = sum(1 for q in questions if (q.get("type") or "short_answer") in _OBJECTIVE_TYPES)
    subj_got = len(questions) - obj_got
    if obj_got == n_obj and subj_got == n_subj:
        return None
    return (
        f"大模型返回题目数量不符：要客观题{n_obj}道、主观题{n_subj}道，"
        f"实际客观题{obj_got}道、主观题{subj_got}道。请重试。"
    )


def _questions_to_items(
    questions: list[dict[str, Any]],
    *,
    objective_points: int | float | None = None,
    subjective_points: int | float | None = None,
) -> list[dict[str, Any]]:
    items = []
    for i, q in enumerate(questions, 1):
        qtype = q.get("type") or "short_answer"
        objective = qtype in _OBJECTIVE_TYPES
        letter = _objective_letter(q) if objective else None
        if objective:
            score = objective_points if objective_points is not None else (q.get("points") or 5)
        else:
            score = subjective_points if subjective_points is not None else (q.get("points") or 10)
        items.append(
            {
                "number": i,
                "kind": "objective" if objective else "subjective",
                "stem": q.get("content") or "",
                "score": score,
                "knowledge_point": q.get("knowledge_point"),
                "options": q.get("options"),
                "answer_key": {"letter": letter} if letter else ({"text": q.get("answer")} if q.get("answer") else None),
                "rubric": q.get("rubric"),
            }
        )
    return items


def _persist(
    class_id: str,
    name: str,
    subject: str | None,
    items: list[dict[str, Any]],
    layout: dict[str, Any],
    homework_id: str | None = None,
) -> dict[str, Any]:
    homework_id = homework_id or uuid.uuid4().hex
    if not items:
        return {"ok": False, "error": "试卷没有题目，无法保存。", "gradeable": False}
    kps = []
    stored = []
    gradeable = True
    for it in items:
        item_id = f"q{it['number']}"
        if it["kind"] == "objective" and not (it.get("answer_key") or {}).get("letter"):
            gradeable = False
        if it["kind"] == "subjective" and not it.get("rubric"):
            gradeable = False
        if it.get("knowledge_point"):
            kps.append(it["knowledge_point"])
        row = {
            "homework_id": homework_id,
            "item_id": item_id,
            "kind": it["kind"],
            "number": it["number"],
            "stem": it.get("stem"),
            "options": it.get("options"),
            "answer_key": it.get("answer_key"),
            "rubric": it.get("rubric"),
            "knowledge_point": it.get("knowledge_point"),
            "score": it.get("score"),
        }
        stored.append(row)
    layout = dict(layout)
    docx_rel = layout.get("docx_path") or (
        layout.get("paper_path") if str(layout.get("paper_path") or "").lower().endswith(".docx") else None
    )
    if docx_rel:
        layout["download_url"] = paper_docx_url(homework_id)
    mysql.insert_assignment(
        homework_id,
        class_id,
        name,
        subject,
        list(dict.fromkeys(kps)),
        layout.get("md_path") or layout.get("docx_path") or layout.get("paper_path"),
        {"gradeable": gradeable, "layout": layout},
    )
    for row in stored:
        mysql.insert_item(row)
        try:
            faiss_index.get_index().add("item", f"{homework_id}:{row['item_id']}", row.get("stem") or "", homework_id)
        except Exception:
            pass
    art = HomeworkArtifact(
        homework_id=homework_id,
        class_id=class_id,
        name=name,
        items=stored,
        paper_path=layout.get("md_path") or layout.get("docx_path") or layout.get("paper_path"),
        gradeable=gradeable,
    )
    out = art.model_dump()
    out["layout"] = layout
    if layout.get("download_url"):
        out["download_url"] = layout["download_url"]
    if "mock" in layout:
        out["mock"] = layout["mock"]
    return out
