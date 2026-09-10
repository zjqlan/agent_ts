from __future__ import annotations

from typing import Any

from zypg.agents.base import PeerAgent
from zypg.config import settings
from zypg.llm import LLMError, complete_json
from zypg.models import A2AMessage
from zypg.protocol.a2a import send_peer
from zypg.roster.service import require_roster
from zypg.storage import mysql


class LessonAgent(PeerAgent):
    name = "lesson"
    description = "备课：下次重点、学期规划、回推出题建议"

    def skills(self) -> list[str]:
        return ["next_focus", "term_plan", "suggest_next_homework"]

    async def handle(self, message: A2AMessage) -> dict[str, Any]:
        p = message.payload
        require_roster(p.get("class_id"))
        pack = _read_insight(p["class_id"], p.get("homework_id"))
        if message.skill == "next_focus":
            return await _next_focus(pack, p)
        if message.skill == "term_plan":
            return await _term_plan(pack, p)
        if message.skill == "suggest_next_homework":
            return await self._suggest(pack, p)
        raise ValueError(f"unknown skill {message.skill}")

    async def _suggest(self, pack: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
        kps = _must_or_weak(pack)
        from zypg.subject import require_same_subject

        subject = require_same_subject(
            p.get("teacher_id"),
            p.get("subject") or pack.get("subject"),
            verb="生成",
        ) or p.get("subject") or pack.get("subject")
        payload = {
            "class_id": p["class_id"],
            "subject": subject,
            "knowledge_points": kps,
            "name": p.get("name") or "下一份针对性作业",
            "teacher_id": p.get("teacher_id"),
        }
        if p.get("questions"):
            payload["questions"] = p["questions"]
        if p.get("skip_llm"):
            payload["skip_llm"] = True
        result = await send_peer(
            "generate_paper",
            payload,
            agent="homework",
        )
        if isinstance(result, dict) and result.get("ok") is False:
            raise RuntimeError(result.get("error") or "作业生成失败")
        return {"suggested_knowledge_points": kps, "homework": result}


def _read_insight(class_id: str, homework_id: str | None) -> dict[str, Any]:
    snaps = mysql.latest_snapshots(class_id)
    short = next((s for s in snaps if s["scope"] == "class" and s["window"] == "short"), None)
    payload = (short or {}).get("payload") or {}
    from zypg.agents.insight_term import build_class_long

    return {
        "short": payload,
        "long": build_class_long(class_id),
        "homework_id": homework_id or payload.get("homework_id"),
        "class_id": class_id,
    }


def _must_or_weak(pack: dict[str, Any]) -> list[str]:
    short = pack.get("short") or {}
    must = list(short.get("must_teach") or [])
    if must:
        out = []
        for m in must:
            if isinstance(m, dict):
                kp = m.get("knowledge_point")
                if kp:
                    out.append(str(kp))
            else:
                out.append(str(m))
        if out:
            return out
    acc = short.get("knowledge_accuracy") or {}
    if acc:
        return [min(acc, key=acc.get)]
    top = (pack.get("long") or {}).get("term_weak_top3") or []
    if top:
        return [str(x.get("knowledge_point")) for x in top if x.get("knowledge_point")]
    heat = (pack.get("long") or {}).get("mastery_heat") or {}
    weak: dict[str, int] = {}
    for row in heat.values():
        for kp, st in row.items():
            if st == "weak":
                weak[kp] = weak.get(kp, 0) + 1
    if weak:
        return [max(weak, key=weak.get)]
    return ["复习巩固"]


async def _next_focus(pack: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    kps = _must_or_weak(pack)
    short = pack.get("short") or {}
    missing = short.get("missing_cards") or []
    weak_people = (pack.get("long") or {}).get("continuous_weak") or []
    stats = {
        "must_from_stats": kps,
        "knowledge_accuracy": short.get("knowledge_accuracy") or {},
        "missing_cards": missing,
        "continuous_weak": weak_people,
        "pending_note": short.get("pending_note"),
    }
    try:
        data = await complete_json(
            "根据班级学情写下次课讲评提纲（3到6条，可操作）：\n" + str(stats),
            system=(
                "你是备课教师。只输出 JSON {\"outline\":[str],\"must_teach\":[str]}。"
                "只谈知识点会/弱/未测与讲法。禁止人格贬义、差生、家庭、心理、高考预测。"
                "不要编造统计里没有的正确率。"
            ),
            temperature=0.3,
            require=True,
        )
        outline = [str(x) for x in (data.get("outline") or []) if str(x).strip()]
        must = [str(x) for x in (data.get("must_teach") or []) if str(x).strip()] or kps
    except LLMError as exc:
        raise LLMError(f"备课提纲需要大模型：{exc}") from exc
    if not outline:
        raise LLMError("大模型未返回备课提纲，已中止。")
    return {
        "must_teach": must,
        "talk_to": weak_people,
        "missing_cards": missing,
        "pending_note": short.get("pending_note"),
        "outline": outline,
        "class_id": p["class_id"],
        "llm_model": settings.llm_model,
        "source": "llm",
    }


async def _term_plan(pack: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    longp = pack.get("long") or {}
    top3 = list(longp.get("term_weak_top3") or [])
    consec = list(longp.get("consecutive_weak") or [])
    n_commits = int(longp.get("n_commits") or 0)
    if n_commits <= 0:
        raise ValueError("还没有长期画像。请先在学情页把已确认成绩写入长期画像。")
    stats = {
        "n_commits": n_commits,
        "can_trend": bool(longp.get("can_trend")),
        "term_weak_top3": top3,
        "consecutive_weak": [
            f"{x.get('student_no')} {x.get('knowledge_point')} 连续{x.get('streak')}次"
            if isinstance(x, dict)
            else str(x)
            for x in consec[:12]
        ],
    }
    try:
        data = await complete_json(
            "根据学期薄弱点写学期滚动规划（只补数据里的点，不要编造）：\n" + str(stats),
            system=(
                "你是备课教师。只输出 JSON {\"plan\":[str]}。"
                "学期规划依据 term_weak_top3 的平均正确率，每次只强调最弱的一块。"
                "建议单独看用学号。禁止人格标签、差生、高考预测。"
            ),
            temperature=0.3,
            require=True,
        )
        plan = [str(x) for x in (data.get("plan") or []) if str(x).strip()]
    except LLMError as exc:
        raise LLMError(f"学期规划需要大模型：{exc}") from exc
    if not plan:
        raise LLMError("大模型未返回学期规划，已中止。")
    return {
        "term_points": [x.get("knowledge_point") for x in top3 if isinstance(x, dict)],
        "term_weak_top3": top3,
        "strengthen": [x.get("knowledge_point") for x in top3 if isinstance(x, dict)],
        "plan": plan,
        "n_commits": n_commits,
        "can_trend": bool(longp.get("can_trend")),
        "class_id": p["class_id"],
        "llm_model": settings.llm_model,
        "source": "llm",
    }
