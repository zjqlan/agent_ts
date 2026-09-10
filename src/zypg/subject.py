from __future__ import annotations

from typing import Any

from zypg.storage import mysql

SUBJECTS = ("语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "思想政治", "信息技术")

_ALIASES = {
    "语文": "语文",
    "中文": "语文",
    "汉语": "语文",
    "语文学科": "语文",
    "数学": "数学",
    "数学课": "数学",
    "英语": "英语",
    "英文": "英语",
    "物理": "物理",
    "化学": "化学",
    "生物": "生物",
    "历史": "历史",
    "地理": "地理",
    "政治": "思想政治",
    "思政": "思想政治",
    "思想政治": "思想政治",
    "信息技术": "信息技术",
    "信息": "信息技术",
}

PAPER_SKILLS = frozenset({"generate_paper", "import_paper", "suggest_next_homework"})


def normalize_subject(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s in _ALIASES:
        return _ALIASES[s]
    key = s.replace("学科", "").replace("课", "").replace("老师", "")
    if key in _ALIASES:
        return _ALIASES[key]
    for name in SUBJECTS:
        if name in s:
            return name
    return s


def paper_defaults(subject: str | None) -> tuple[str, str]:
    subj = normalize_subject(subject) or "数学"
    hints = {
        "语文": ("现代文阅读", "围绕现代文阅读理解，中等难度，要有语言运用情境。"),
        "数学": ("二次函数", "围绕二次函数顶点式，中等难度，要有实际应用情境。"),
        "英语": ("阅读理解", "围绕阅读理解与词汇运用，中等难度。"),
        "物理": ("力学", "围绕力学基本概念，中等难度，要有实际情境。"),
        "化学": ("物质构成", "围绕本课化学知识点，中等难度。"),
        "生物": ("细胞", "围绕本课生物知识点，中等难度。"),
        "历史": ("史料实证", "围绕本课历史知识点，中等难度。"),
        "地理": ("区域认知", "围绕本课地理知识点，中等难度。"),
        "思想政治": ("价值判断", "围绕本课思政知识点，中等难度。"),
        "信息技术": ("算法与程序", "围绕本课信息技术知识点，中等难度。"),
    }
    return hints.get(subj, ("本课知识点", f"围绕{subj}本课内容出题，中等难度。"))


def teacher_subject(teacher_id: str | None) -> str | None:
    if not teacher_id:
        return None
    row = mysql.get_teacher(teacher_id)
    return normalize_subject((row or {}).get("subject"))


def mismatch_message(teacher_subj: str, asked: str, verb: str = "生成") -> str:
    return f"您是{teacher_subj}老师，不能{verb}{asked}试卷。"


def enforce_teacher_subject(skills: list[str], payload: dict[str, Any]) -> None:
    tid = payload.get("teacher_id")
    if not tid:
        return
    mine = teacher_subject(tid)
    asked = normalize_subject(payload.get("subject"))
    needs_paper = any(s in PAPER_SKILLS for s in skills)
    if "import_roster" in skills and mine:
        payload["subject"] = mine
        return
    if not needs_paper:
        return
    if not mine:
        raise ValueError("请先登录并选择任教学科。语文老师不能出数学卷。")
    if asked and asked != mine:
        raise ValueError(mismatch_message(mine, asked, "生成" if "import_paper" not in skills else "导入"))
    cid = payload.get("class_id")
    if cid and mine:
        cls = mysql.get_class(cid)
        csubj = normalize_subject((cls or {}).get("subject"))
        if csubj != mine:
            mysql.update_class_subject(cid, mine)
    payload["subject"] = mine


def require_same_subject(teacher_id: str | None, other: Any, *, verb: str = "生成") -> str | None:
    mine = teacher_subject(teacher_id)
    if not teacher_id:
        return normalize_subject(other)
    if not mine:
        raise ValueError("请先登录并选择任教学科。")
    asked = normalize_subject(other)
    if asked and asked != mine:
        raise ValueError(mismatch_message(mine, asked, verb))
    return mine
