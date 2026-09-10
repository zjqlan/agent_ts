from __future__ import annotations

import json
import re
from typing import Any

from zypg.config import settings
from zypg.llm import LLMError, complete_json

SIM_SYSTEM = (
    "你模拟高中生在答题卡上的真实作答。只输出 JSON。"
    "顶层 key 必须是学号。"
    "每个学生：{\"bubbles\":{item_id:\"A|B|C|D\"},\"writing\":{item_id:[\"一行\",\"一行\"]}}。"
    "三人水平必须明显不同：一名较好、一名较差、一名中等有对有错。"
    "主观题要像学生写的（可跳步、可写错、可有口头禅），禁止三人雷同，禁止整段照抄标准答案。"
    "客观题 bubbles 的 key 必须用题目 item_id。禁止人格、家庭、心理评价。"
)


async def simulate_student_answers(
    students: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payload = {
        "students": [{"student_no": s["student_no"], "name": s.get("name")} for s in students],
        "items": [
            {
                "item_id": it["item_id"],
                "kind": it.get("kind"),
                "stem": it.get("stem"),
                "options": it.get("options"),
                "answer_key": it.get("answer_key"),
                "score": it.get("score"),
            }
            for it in items
        ],
    }
    data = await complete_json(
        "根据下列题目，为每位学生生成答题卡作答：\n" + json.dumps(payload, ensure_ascii=False),
        system=SIM_SYSTEM,
        temperature=0.7,
        require=True,
    )
    if any(k in data for k in ("students", "answers", "scripts")):
        nested = data.get("students") or data.get("answers") or data.get("scripts")
        if isinstance(nested, dict):
            data = nested
        elif isinstance(nested, list):
            rebuilt: dict[str, Any] = {}
            for i, block in enumerate(nested):
                if not isinstance(block, dict):
                    continue
                no = block.get("student_no") or block.get("id")
                if not no and i < len(students):
                    no = students[i]["student_no"]
                rebuilt[str(no)] = block
            data = rebuilt
    scripts: dict[str, dict[str, Any]] = {}
    for stu in students:
        no = stu["student_no"]
        block = _block_for_student(data, stu)
        if not isinstance(block, dict):
            block = {}
        bubbles = {}
        for k, v in _remap_item_map(block.get("bubbles") or {}, items).items():
            letter = str(v).strip().upper()[:1]
            if letter in {"A", "B", "C", "D"}:
                bubbles[str(k)] = letter
        writing = {}
        for k, v in _remap_item_map(block.get("writing") or {}, items).items():
            if isinstance(v, list):
                writing[str(k)] = [str(x) for x in v if str(x).strip()]
            elif v:
                writing[str(k)] = [str(v)]
        scripts[no] = {"bubbles": bubbles, "writing": writing}
    empty = [
        s["student_no"]
        for s in students
        if not scripts[s["student_no"]]["bubbles"] and not scripts[s["student_no"]]["writing"]
    ]
    if empty:
        raise LLMError(f"大模型未给这些学号返回作答：{','.join(empty)}。已中止，不用模板。")
    return scripts


def _block_for_student(data: dict[str, Any], stu: dict[str, Any]) -> Any:
    no = stu["student_no"]
    sid = stu.get("student_id")
    for key in (no, str(no).upper(), str(no).lower(), sid):
        if key and key in data:
            return data[key]
    for k, v in data.items():
        if str(k).upper() == str(no).upper():
            return v
    return {}


def _remap_item_map(raw: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {str(it["item_id"]) for it in items}
    by_num = {str(it.get("number")): it["item_id"] for it in items if it.get("number") is not None}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        key = str(k).strip()
        if key in ids:
            out[key] = v
            continue
        if key in by_num:
            out[by_num[key]] = v
            continue
        m = re.search(r"(\d+)", key)
        if m and m.group(1) in by_num:
            out[by_num[m.group(1)]] = v
            continue
        qkey = key if key.startswith("q") else f"q{key}"
        if qkey in ids:
            out[qkey] = v
    return out


def llm_tag() -> dict[str, str]:
    return {"llm_model": settings.llm_model, "llm": "qwen"}
