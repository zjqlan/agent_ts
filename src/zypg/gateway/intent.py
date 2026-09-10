from __future__ import annotations

import json
import re
from typing import Any

from zypg.models import Intent

CHAT_EXAMPLES = ("什么是等差数列",)
TASK_EXAMPLES = ("只出卡", "看看这班学情", "导入这份卷子")
PIPELINE_EXAMPLES = ("出这份作业并出卡", "改完并给出讲评")

AGENT_BY_SKILL = {
    "import_roster": "名册服务",
    "generate_paper": "作业生成",
    "import_paper": "作业生成",
    "generate_cards": "答题卡与批改",
    "fill_demo_scans": "答题卡与批改",
    "grade_scans": "答题卡与批改",
    "review_queue": "答题卡与批改",
    "class_insight": "学情分析",
    "student_insight": "学情分析",
    "commit_long_term": "学情分析",
    "next_focus": "备课",
    "term_plan": "备课",
    "suggest_next_homework": "备课",
}

_CHAT = [
    re.compile(r"^什么是"),
    re.compile(r"为什么"),
    re.compile(r"解释"),
    re.compile(r"怎么理解"),
]

_SCAN_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def extract_existing_paths(text: str) -> list[str]:
    """从口令里取出本机已存在的文件或目录（Windows 盘符路径）。"""
    from pathlib import Path as _P

    found: list[str] = []
    for m in re.finditer(r"[A-Za-z]:\\[^\n\r]+", text or ""):
        raw = m.group(0).strip().strip("\"'")
        raw = re.split(r"\s+(?:还是|请|你再|试试)", raw)[0].strip().rstrip("。．，,")
        parts = raw.split()
        chosen = None
        for i in range(len(parts), 0, -1):
            p = _P(" ".join(parts[:i]))
            if p.exists():
                chosen = p
                break
        if chosen is not None:
            found.append(str(chosen))
    return found


def collect_scan_images(path: str) -> list[str]:
    from pathlib import Path as _P

    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return []
    p = _P(raw).expanduser()
    if p.is_file() and p.suffix.lower() == ".zip":
        return _images_from_zip(p)
    if p.is_file() and p.suffix.lower() in _SCAN_EXT:
        return [str(p)]
    if not p.is_dir():
        return []
    imgs: list[_P] = []
    for ext in _SCAN_EXT:
        imgs.extend(p.glob(f"*{ext}"))
        imgs.extend(p.glob(f"*{ext.upper()}"))
        imgs.extend(p.rglob(f"*{ext}"))
        imgs.extend(p.rglob(f"*{ext.upper()}"))
    skip = {"_blank.png", "scores.csv"}
    return [str(x) for x in sorted(set(imgs)) if x.name.lower() not in skip and x.suffix.lower() in _SCAN_EXT]


def resolve_scan_source(path: str) -> tuple[list[str], str | None]:
    """把老师填的文件夹/压缩包解析成图片路径；失败时返回中文原因。"""
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return [], None
    if "..." in raw or "…" in raw:
        return [], "路径不完整：请填写完整文件夹路径，不要使用省略号。"
    from pathlib import Path as _P

    p = _P(raw).expanduser()
    if not p.exists():
        return [], f"找不到路径：{raw}"
    imgs = collect_scan_images(str(p))
    if not imgs:
        return [], f"这里没有 png/jpg 答题卡：{raw}"
    return imgs, None


def _images_from_zip(zip_path) -> list[str]:
    import zipfile
    from pathlib import Path as _P

    from zypg.storage.files import file_root

    dest = file_root() / "scans" / "_unzipped" / zip_path.stem
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    return collect_scan_images(str(dest))


def detect_skills(text: str) -> list[str]:
    """从口令里点到的 skill。老师点几个就返回几个，绝不补齐 1→2→3→4。"""
    t = text or ""
    skills: list[str] = []

    def add(skill: str) -> None:
        if skill not in skills:
            skills.append(skill)

    if re.search(r"导入(?:班级)?名单|导入班级", t) and not re.search(r"请先", t):
        add("import_roster")
    if re.search(r"导入.*卷|导入试卷|导入作业|上传卷子|解析导入|导入这份", t):
        add("import_paper")
    elif re.search(
        r"作业生成|出题|出卷|生成试卷|出一套|出一份|出这份作业|出几道|来几道|课时作业|练习卷"
        r"|生成.{0,40}(?:试卷|卷子|练习)"
        r"|出.{0,20}(?:试卷|卷子)"
        r"|(?:选择题|客观题).{0,24}(?:大题|主观题|解答题)",
        t,
    ):
        add("generate_paper")

    filled_cards = bool(
        re.search(r"写好|填好|已作答|写完|填完|学生作答|模拟作答", t)
        and re.search(r"卡|扫描", t)
        and not re.search(r"批改|改完|改卡", t)
        and not extract_existing_paths(t)
    )
    from_printed_cards = bool(re.search(r"刚出的卡|出卡图|用答题卡批改", t))
    local_scans = bool(extract_existing_paths(t))
    if filled_cards:
        add("fill_demo_scans")
    else:
        if not local_scans and (
            re.search(
                r"只出卡|生成答题卡|打印答题卡|打印出答题卡|出答题卡|下载答题卡|要答题卡|给我答题卡",
                t,
            )
            or (re.search(r"(?<![已改收回])出卡", t) and not from_printed_cards)
        ):
            add("generate_cards")
        if re.search(r"批改|扫描|改完|改卡", t) or from_printed_cards or local_scans:
            add("grade_scans")
        elif re.search(r"[A-Za-z]:\\", t) and re.search(r"答题卡|扫描件", t):
            add("grade_scans")
    if re.search(r"确认队列|待确认", t) and not re.search(r"采用|接受|覆盖", t):
        add("review_queue")
    if re.search(r"采用建议|接受建议|覆盖|确认第", t):
        add("review_queue")

    # 老师明确要求「做完后质量升级 / 全自动」：批改填好的卡 → 学情 → 备课
    if re.search(r"质量升级|教学升级", t) or (re.search(r"全自动", t) and re.search(r"做完|批改|学情|备课", t)):
        if re.search(r"做完|批改|改完|扫描|全自动", t):
            add("grade_scans")
        if "class_insight" not in skills:
            add("class_insight")
        if "next_focus" not in skills:
            add("next_focus")
        return skills

    if re.search(r"学号\s*[A-Za-z0-9]+", t, re.I) or re.search(
        r"学生\s*(?:S\d+|[一二三四五六七八九十]|[0-9]+)", t, re.I
    ) or re.search(r"(?<![A-Za-z0-9])S\d{1,3}(?![0-9])", t, re.I):
        if re.search(r"学情|错题|错了|情况|成绩|得分|测完|作答|对错|分数|客观|主观", t):
            add("student_insight")
    elif re.search(r"学情|错题本|学情分析|连续薄弱|学期薄弱", t):
        add("class_insight")
    if re.search(r"长期画像|写入长期|\bcommit\b", t, re.I):
        add("commit_long_term")

    if re.search(r"下一份作业|下一次作业|建议下一|回推", t):
        add("suggest_next_homework")
    elif re.search(r"学期规划", t):
        add("term_plan")
    elif re.search(r"备课|下次重点|必讲|讲评|备课提纲", t):
        add("next_focus")

    # 规格例句「改完并给出讲评」：批改 + 学情 + 备课，仍是老师一句话点了多个
    if re.search(r"讲评", t) and "grade_scans" in skills and "class_insight" not in skills:
        # 插在备课之前，保持批改 → 学情 → 备课
        if "next_focus" in skills:
            skills.remove("next_focus")
            add("class_insight")
            add("next_focus")
        else:
            add("class_insight")

    return skills


_PAPER_EXT = {".md", ".docx", ".doc", ".pdf", ".txt"}
_ROSTER_EXT = {".csv", ".xlsx", ".xls"}


def infer_attachment_skills(extra: dict[str, Any] | None) -> list[str]:
    extra = extra or {}
    from pathlib import Path as _P

    skills: list[str] = []
    suffix = ""
    for cand in (extra.get("roster_path"), extra.get("paper_path"), extra.get("path")):
        if cand:
            suffix = _P(str(cand)).suffix.lower()
            break
    if extra.get("roster_path") or suffix in _ROSTER_EXT:
        skills.append("import_roster")
    elif extra.get("paper_path") or suffix in _PAPER_EXT:
        skills.append("import_paper")
    elif extra.get("scan_paths") or extra.get("scan_dir"):
        skills.append("grade_scans")
    return skills


def enrich_extra(text: str, extra: dict[str, Any] | None) -> dict[str, Any]:
    extra = dict(extra or {})
    inferred = infer_attachment_skills(extra)
    if inferred and not extra.get("skills"):
        extra["skills"] = inferred
    return extra


def classify(text: str) -> Intent:
    t = (text or "").strip()
    skills = detect_skills(t)
    if len(skills) >= 2:
        return Intent.pipeline
    if len(skills) == 1:
        return Intent.task
    for pat in _CHAT:
        if pat.search(t):
            return Intent.chat
    if t.endswith("？") or t.endswith("?"):
        return Intent.chat
    return Intent.chat


_ALLOWED_SKILLS = tuple(AGENT_BY_SKILL)

INTENT_SYSTEM = """你是高中作业批改系统的路由，不是出题老师。根据老师口令判断要调用哪些 skill。
只输出 JSON。老师点到几个 skill 就输出几个，禁止因为出题就自动出卡、禁止没点批改就自动学情备课。
allowed_skills:
import_roster 导入班级名单
generate_paper 生成/出一份试卷或练习（含指定选择题、大题数量）
import_paper 导入已有卷子文件
generate_cards 生成或打印空白答题卡（不是批改，不是在对话里用文字画卡）
fill_demo_scans 明确要求模拟学生填好答题卡
grade_scans 批改扫描件或已填卡
review_queue 确认队列/采用建议分
class_insight 全班学情
student_insight 某个学生的对错/成绩/学情
commit_long_term 写入长期画像
next_focus 备课提纲或讲评要点
term_plan 学期规划
suggest_next_homework 建议下一份作业

intent 只能是 chat、task、pipeline：
- chat：问概念、闲聊、解释知识，不操作系统功能
- task：只需要一个 skill
- pipeline：一句话里明确要做多件事（例如出题并出卡）

JSON 形状：
{"intent":"task","skills":["generate_paper"],"slots":{"subject":"语文","n_objective":6,"n_subjective":3,"requirement":"..."}}
chat 时 skills 为 []。slots 只放口令里出现的字段：subject,grade,knowledge_points(字符串数组),n_objective,n_subjective,objective_points,subjective_points,class_name,student_no,student_ordinal,requirement。
生成或打印答题卡必须用 generate_cards，不要当成 chat 去用文字画一张卡。
"""


def _normalize_skills(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if name in _ALLOWED_SKILLS and name not in out:
            out.append(name)
    return out


def _intent_from_skills(skills: list[str]) -> Intent:
    if len(skills) >= 2:
        return Intent.pipeline
    if len(skills) == 1:
        return Intent.task
    return Intent.chat


def _merge_slots(llm_slots: Any, text: str) -> dict[str, Any]:
    slots = dict(extract_slots(text))
    if isinstance(llm_slots, dict):
        for key, val in llm_slots.items():
            if val in (None, "", []):
                continue
            if key in {"n_objective", "n_subjective", "student_ordinal"}:
                try:
                    slots[key] = int(val)
                except (TypeError, ValueError):
                    continue
            elif key in {"objective_points", "subjective_points"}:
                try:
                    slots[key] = _score_num(str(val))
                except (TypeError, ValueError):
                    continue
            elif key == "knowledge_points":
                if isinstance(val, str):
                    slots[key] = _split_kps(val)
                elif isinstance(val, list):
                    slots[key] = [str(x).strip() for x in val if str(x).strip()]
            else:
                slots[key] = val
    if text.strip():
        slots.setdefault("requirement", text.strip())
    return slots


def attach_understood(extra: dict[str, Any] | None, understood: dict[str, Any]) -> dict[str, Any]:
    extra = dict(extra or {})
    intent = understood.get("intent")
    intent_v = intent.value if isinstance(intent, Intent) else str(intent or "chat")
    skills = _normalize_skills(understood.get("skills"))
    extra["understood"] = {
        "intent": intent_v,
        "skills": skills,
        "slots": understood.get("slots") or {},
    }
    if skills and not extra.get("skills"):
        extra["skills"] = skills
    return extra


async def understand_utterance(text: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """口令路由：能连大模型时用大模型判断；失败或无密钥时回退规则。"""
    extra = enrich_extra(text, extra)
    cached = extra.get("understood")
    if isinstance(cached, dict) and cached.get("intent"):
        skills = _normalize_skills(cached.get("skills") or extra.get("skills"))
        intent = _intent_from_skills(skills)
        try:
            intent = Intent(str(cached.get("intent")))
        except ValueError:
            pass
        if intent == Intent.chat and skills:
            intent = _intent_from_skills(skills)
        return {"intent": intent, "skills": skills, "slots": _merge_slots(cached.get("slots"), text)}

    forced = _normalize_skills(extra.get("skills") or infer_attachment_skills(extra))
    llm_out: dict[str, Any] = {}
    if not forced:
        try:
            from zypg.llm import LLMError, complete_json

            llm_out = await complete_json(
                "老师口令：" + (text or "") + "\n附件：" + json.dumps(
                    {k: extra.get(k) for k in ("path", "paper_path", "roster_path", "scan_paths", "scan_dir") if extra.get(k)},
                    ensure_ascii=False,
                ),
                system=INTENT_SYSTEM,
                temperature=0,
                require=False,
            ) or {}
        except Exception:
            llm_out = {}
    llm_skills = _normalize_skills(llm_out.get("skills"))
    skills = forced or llm_skills or detect_skills(text)
    intent: Intent | None = None
    raw_intent = str(llm_out.get("intent") or "").strip().lower()
    if forced:
        intent = _intent_from_skills(skills)
    elif raw_intent in {item.value for item in Intent}:
        intent = Intent(raw_intent)
        if intent == Intent.chat and skills:
            intent = _intent_from_skills(skills)
        elif intent != Intent.chat and not skills:
            skills = detect_skills(text)
            intent = _intent_from_skills(skills)
    else:
        intent = _intent_from_skills(skills)
    return {"intent": intent, "skills": skills, "slots": _merge_slots(llm_out.get("slots"), text)}


def resolve_intent(text: str, extra: dict[str, Any] | None = None) -> Intent:
    """同步规则路由（测试与无模型时）。线上口令请走 understand_utterance。"""
    extra = enrich_extra(text, extra)
    forced = extra.get("skills") or infer_attachment_skills(extra)
    if forced:
        return Intent.pipeline if len(forced) >= 2 else Intent.task
    return classify(text)


def route_skills(text: str, intent: Intent) -> list[str]:
    """task 只派老师点到的那一个 skill；pipeline 只派这句话里点到的那些，不自动补全。"""
    skills = detect_skills(text)
    if intent == Intent.pipeline:
        return skills
    return skills[:1]


def extract_slots(text: str) -> dict[str, Any]:
    t = text or ""
    slots: dict[str, Any] = {}
    for subj in ("数学", "语文", "英语", "物理", "化学", "生物", "历史", "地理", "政治"):
        if subj in t:
            slots["subject"] = subj
            break
    m = re.search(r"知识点[是为:：、,]?\s*([^\n。；]+)", t)
    if m:
        slots["knowledge_points"] = _split_kps(m.group(1))
    else:
        m2 = re.search(r"按([^\n]{2,40}?)(?:出题|出卷|出一套|生成)", t)
        if m2:
            slots["knowledge_points"] = _split_kps(m2.group(1))
        else:
            m3 = re.search(
                r"(?:关于|围绕|针对)\s*(.+?)(?:的(?:课时)?作业|的练习|出题)",
                t,
            )
            if m3:
                slots["knowledge_points"] = _split_kps(m3.group(1))
            else:
                m4 = re.search(r"(?:出一份|出一套|出一张)\s*(.+?)的(?:试卷|卷子|练习)", t)
                if m4:
                    slots["knowledge_points"] = _split_kps(m4.group(1))
    if t.strip():
        slots["requirement"] = t.strip()
    m = re.search(r"(?:班级(?:名称)?|班名)[是为:：]?\s*([^\s，,]+)", t)
    if m:
        slots["class_name"] = m.group(1).strip()
    m = re.search(r"学号\s*([A-Za-z0-9]+)", t, re.I)
    if m:
        slots["student_no"] = m.group(1).upper()
    else:
        m = re.search(r"学生\s*(S[A-Za-z0-9]+)", t, re.I)
        if m:
            slots["student_no"] = m.group(1).upper()
        else:
            m = re.search(r"(?<![A-Za-z0-9])(S\d{1,3})(?![0-9])", t, re.I)
            if m:
                slots["student_no"] = m.group(1).upper()
            else:
                m = re.search(r"学生\s*([一二三四五六七八九十]|[0-9]+)", t)
                if m:
                    token = m.group(1)
                    cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                    slots["student_ordinal"] = cn.get(token) or (int(token) if token.isdigit() else None)
    if re.search(r"示例名单|样例名单|例子名单", t):
        slots["use_sample_roster"] = True
    if re.search(r"示例试卷|样例试卷|最小卷|例子试卷", t):
        slots["use_sample_paper"] = True
    if re.search(r"刚出的卡|出卡图|夹具|用答题卡批改|当扫描|填好的卡|写好的卡", t):
        slots["use_card_scans"] = True
    if re.search(r"全部(接受|采用|确认)", t):
        slots["review_action"] = "accept_all"
    elif re.search(r"覆盖", t):
        slots["review_action"] = "overridden"
        m = re.search(r"(\d+(?:\.\d+)?)\s*分", t)
        if m:
            slots["score"] = float(m.group(1))
    elif re.search(r"采用|接受建议|确认", t) and re.search(r"建议|队列|第\s*\d+", t):
        slots["review_action"] = "accepted"
    m = re.search(r"第\s*(\d+)\s*条", t)
    if m:
        slots["review_index"] = int(m.group(1))
    slots.update(_extract_paper_structure(t))
    paths = extract_existing_paths(t)
    if paths:
        slots["local_paths"] = paths
        imgs: list[str] = []
        for p in paths:
            imgs.extend(collect_scan_images(p))
        if imgs:
            slots["scan_paths"] = imgs
            slots["scan_dir"] = paths[0]
    return slots


_OBJ_TYPE = r"(?:选择题|单选题|客观题)"
_SUBJ_TYPE = r"(?:解答题|简答题|主观题|大题)"
_Q_UNIT = r"(?:道|个)"
_PER_ITEM_PTS = r"(?:[，,、]?\s*每题\s*(\d+(?:\.\d+)?)\s*分)?"


def _extract_paper_structure(t: str) -> dict[str, Any]:
    """只认带题型的数量/分值，避免把「3个学生」「覆盖 5 分」当成出题规格。"""
    out: dict[str, Any] = {}
    obj = re.search(rf"(\d+)\s*{_Q_UNIT}\s*{_OBJ_TYPE}{_PER_ITEM_PTS}", t)
    if not obj:
        obj = re.search(rf"{_OBJ_TYPE}\s*(\d+)\s*{_Q_UNIT}{_PER_ITEM_PTS}", t)
    if obj:
        out["n_objective"] = int(obj.group(1))
        if obj.group(2) is not None:
            out["objective_points"] = _score_num(obj.group(2))
    subj = re.search(rf"(\d+)\s*{_Q_UNIT}\s*{_SUBJ_TYPE}{_PER_ITEM_PTS}", t)
    if not subj:
        subj = re.search(rf"{_SUBJ_TYPE}\s*(\d+)\s*{_Q_UNIT}{_PER_ITEM_PTS}", t)
    if subj:
        out["n_subjective"] = int(subj.group(1))
        if subj.group(2) is not None:
            out["subjective_points"] = _score_num(subj.group(2))
    return out


def _score_num(raw: str) -> int | float:
    v = float(raw)
    return int(v) if v.is_integer() else v


def _split_kps(raw: str) -> list[str]:
    parts = re.split(r"[、,，和及\s]+", raw.strip(" 。；;"))
    return [p for p in parts if p and p not in {"出题", "出卷", "知识点"}]


def format_task_reply(result: dict[str, Any]) -> str:
    if result.get("error") and not result.get("ok"):
        return str(result["error"])
    lines: list[str] = []
    intent = result.get("intent")
    skills = [item.get("skill") for item in result.get("results") or []]
    agents = []
    for s in skills:
        name = AGENT_BY_SKILL.get(s, s)
        if name not in agents:
            agents.append(name)
    if intent == "task" and agents:
        lines.append(f"已派给同级 Agent「{agents[0]}」（编排器不持有业务逻辑，也不会接着跑别的 Agent）。")
    elif intent == "pipeline" and agents:
        if "class_insight" in skills and "next_focus" in skills:
            lines.append("批改完成后自动质量升级（学情讲评 + 备课），按点名顺序 A2A 派发：" + " → ".join(agents))
        else:
            lines.append("这句话点了多个同级 Agent，按点名顺序 A2A 派发（不是固定流水线）：" + " → ".join(agents))
    for item in result.get("results") or []:
        skill = item.get("skill")
        r = item.get("result") or {}
        peer = AGENT_BY_SKILL.get(skill, skill)
        if skill == "import_roster":
            lines.append(f"[{peer}] 名单已导入：{r.get('name') or ''} {r.get('count')} 人。class_id={r.get('class_id')}")
        elif skill in {"import_paper", "generate_paper"}:
            if r.get("ok") is False:
                lines.append(f"[{peer}] {r.get('error') or '出题未完成，可改口令「导入示例试卷」。'}")
            else:
                n = len(r.get("items") or [])
                extra = ""
                if r.get("llm_model"):
                    extra += f"，题目来源 {r.get('llm_model')}"
                layout = r.get("layout") or {}
                if r.get("mock") or layout.get("mock"):
                    extra += "，排版为本地 mock（未连 edupaper-mcp）"
                url = r.get("download_url") or layout.get("download_url")
                if url:
                    extra += f"，DOCX {url}"
                lines.append(
                    f"[{peer}] 试卷《{r.get('name') or ''}》{n} 题，homework_id={r.get('homework_id')}，"
                    f"{'可机改' if r.get('gradeable') else '缺答案/评分点，仅可出卡'}"
                    + extra
                    + "。"
                )
        elif skill == "generate_cards":
            lines.append(
                f"[{peer}] 出卡 {r.get('count')} 张（含学号填涂与独立卡号），打印目录：{r.get('print_path')}。"
            )
        elif skill == "fill_demo_scans":
            model = r.get("llm_model") or "大模型"
            lines.append(
                f"[{peer}] 由 {model} 生成 {r.get('count')} 名学生的作答并印到扫描件（不是模板乱填）。"
                f"目录：{r.get('print_path')}。空白打印卡未改。"
            )
        elif skill == "grade_scans":
            lines.append(
                f"[{peer}] 批改完成：扫描 {r.get('scanned')} 份，结果 {r.get('results')} 条，队列 {r.get('queued')} 条。"
            )
            if r.get("queued") and r.get("results") and r.get("queued") == r.get("results"):
                lines.append("全部进了确认队列。若刚才批的是空白打印卡，请先生成写好的答题卡再「批改」。")
        elif skill == "review_queue":
            if "items" in r:
                lines.append(f"[{peer}] 待确认 {len(r.get('items') or [])} 条。可说「全部采用建议分」。")
                for i, q in enumerate(r.get("items") or [], 1):
                    lines.append(f"  {i}. #{q.get('id')} {q.get('reason')} 建议分={q.get('suggested_score')}")
            else:
                lines.append(f"[{peer}] 确认项已更新：{r.get('status') or r}")
        elif skill == "class_insight":
            payload = (r.get("class") or {}).get("payload") or {}
            must = payload.get("must_teach") or []
            acc = payload.get("knowledge_accuracy") or {}
            note = payload.get("pending_note") or ""
            lines.append(f"[{peer}] 班级学情已生成。" + (f" {note}。" if note else ""))
            if payload.get("headline"):
                lines.append(payload["headline"])
            if payload.get("llm_review"):
                lines.append(f"讲评（{payload.get('llm_model') or 'LLM'}）：{payload['llm_review']}")
            if payload.get("first_teach"):
                lines.append("全班先讲：" + payload["first_teach"])
            if payload.get("watch_who"):
                lines.append("建议单独看：" + "；".join(payload["watch_who"][:6]))
            if payload.get("next_focus"):
                lines.append("下次补：" + payload["next_focus"])
            for m in (payload.get("classroom_moves") or [])[:5]:
                lines.append("  · " + str(m))
            if acc:
                bits = [
                    f"{k} {round(v*100)}%"
                    for k, v in acc.items()
                    if str(k).strip() not in {"", "未标注"}
                ]
                if bits:
                    lines.append("知识点正确率：" + "，".join(bits))
            hard = payload.get("hard_items") or []
            if hard:
                bits = [
                    f"{h.get('label') or h.get('item_id')} {round((h.get('accuracy') or 0)*100)}%"
                    for h in hard[:6]
                ]
                lines.append("易错题：" + "，".join(bits))
            if must:
                must = [m for m in must if str(m).strip() not in {"", "未标注"}]
                if must:
                    lines.append("下次必讲：" + "、".join(must))
        elif skill == "student_insight":
            short = r.get("short") or {}
            n_res = len(short.get("results") or short.get("scores") or [])
            wrong = short.get("wrong_book") or []
            bits = [f"[{peer}] 学生 {short.get('student_no')}"]
            if short.get("total") is not None:
                bits.append(f"本卷 {round(float(short['total']),1)}/{round(float(short.get('max_total') or 0),1)}")
            if short.get("class_avg") is not None:
                bits.append(f"班均 {round(float(short['class_avg']),1)}")
            bits.append(f"{n_res} 条作答，错题 {len(wrong)} 道")
            lines.append("，".join(bits) + "。")
            if short.get("headline"):
                lines.append(short["headline"])
            if short.get("llm_review"):
                lines.append(f"辅导（{short.get('llm_model') or 'LLM'}）：{short['llm_review']}")
            for step in ((short.get("coach") or {}).get("next_steps") or [])[:4]:
                lines.append("  · " + str(step))
            scores = short.get("scores") or []
            if scores:
                bits = []
                for s in scores:
                    mark = s.get("status") or (
                        "待确认" if s.get("pending") else ("对" if s.get("is_correct") == 1 else ("错" if s.get("is_correct") == 0 else ""))
                    )
                    no = s.get("number") or s.get("item_id")
                    bits.append(f"第{no}题 {s.get('score')}/{s.get('max_score')} {mark}".strip())
                lines.append("各题：" + "；".join(bits))
            if short.get("pending_note"):
                lines.append(str(short["pending_note"]) + "（待确认分也会显示，未写入长期画像）。")
            for w in wrong[:12]:
                lines.append(f"  - {w.get('item_id')} {w.get('knowledge_point') or ''} {str(w.get('stem') or '')[:40]}")
            if n_res and not wrong:
                lines.append("按对错标记没有错题（客观全对或主观未标错）。")
            if not n_res:
                lines.append("库里还没有该生的 item_results。请到批改页确认扫描已匹配学号。")
        elif skill == "commit_long_term":
            n = r.get("n_commits")
            lines.append(f"[{peer}] 已写入长期掌握 {r.get('events')} 条（会/弱/未测）。本学期已写入 {n or 0} 次作业。")
            if not r.get("can_trend"):
                lines.append("再批改并写入一次长期画像后，才能看知识点走势。")
            top = r.get("term_weak_top3") or []
            if top:
                bits = [f"{x.get('knowledge_point')} {round(float(x.get('avg_accuracy') or 0)*100)}%" for x in top if isinstance(x, dict)]
                if bits:
                    lines.append("学期薄弱点（平均正确率）：" + "，".join(bits))
        elif skill == "next_focus":
            lines.append(f"[{peer}] 下次重点" + (f"（{r.get('llm_model')}）" if r.get("llm_model") else "") + "：")
            for x in r.get("outline") or []:
                lines.append("  - " + str(x))
        elif skill == "term_plan":
            lines.append(f"[{peer}] 学期规划" + (f"（{r.get('llm_model')}）" if r.get("llm_model") else "") + "：")
            for x in r.get("plan") or []:
                lines.append("- " + str(x))
        elif skill == "suggest_next_homework":
            kps = r.get("suggested_knowledge_points") or []
            hw = (r.get("homework") or {}) if isinstance(r.get("homework"), dict) else {}
            lines.append(f"[{peer}] 经 A2A 回推作业生成，知识点：{'、'.join(kps)}。")
            if hw.get("homework_id"):
                lines.append(f"作业生成已写出 homework_id={hw['homework_id']}。")
            elif hw.get("error"):
                lines.append(str(hw["error"]))
        else:
            lines.append(f"[{peer}] {skill} 完成。")
    return "\n".join(lines) if lines else "任务完成。"
