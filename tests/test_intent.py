from zypg.gateway.intent import classify, extract_slots, infer_attachment_skills, resolve_intent, route_skills
from zypg.models import Intent


def test_intent_chat():
    assert classify("什么是等差数列") is Intent.chat


def test_intent_task():
    assert classify("只出卡") is Intent.task
    assert classify("看看这班学情") is Intent.task
    assert classify("导入这份卷子") is Intent.task
    assert classify("导入作业") is Intent.task
    assert route_skills("导入作业", Intent.task) == ["import_paper"]
    assert resolve_intent("（附件）", {"paper_path": "C:/x/a.docx"}) is Intent.task
    assert infer_attachment_skills({"paper_path": "C:/x/a.docx"}) == ["import_paper"]
    assert route_skills("只出卡", Intent.task) == ["generate_cards"]
    assert route_skills("看看这班学情", Intent.task) == ["class_insight"]
    assert route_skills("谁连续薄弱", Intent.task) == ["class_insight"]
    assert route_skills("学期规划", Intent.task) == ["term_plan"]
    assert route_skills("导入这份卷子", Intent.task) == ["import_paper"]
    assert route_skills("备课提纲", Intent.task) == ["next_focus"]
    assert len(route_skills("只出卡", Intent.task)) == 1
    # 点一个就只派一个，不顺着流水线往下跑
    assert classify("按等差数列出题") is Intent.task
    assert route_skills("按等差数列出题", Intent.task) == ["generate_paper"]
    assert classify("用刚出的卡当扫描批改") is Intent.task
    assert route_skills("用刚出的卡当扫描批改", Intent.task) == ["grade_scans"]
    assert classify("学生1情况") is Intent.task
    assert route_skills("学生1情况", Intent.task) == ["student_insight"]
    assert classify("S01错了什么题目") is Intent.task
    assert route_skills("S01错了什么题目", Intent.task) == ["student_insight"]
    assert extract_slots("S01错了什么题目")["student_no"] == "S01"
    assert classify("S01测完了啊") is Intent.task
    assert route_skills("S01测完了啊", Intent.task) == ["student_insight"]
    assert classify("生成3个学生的写好以后的答题卡") is Intent.task
    assert route_skills("生成3个学生的写好以后的答题卡", Intent.task) == ["fill_demo_scans"]
    assert classify("下一份作业") is Intent.task
    assert route_skills("下一份作业", Intent.task) == ["suggest_next_homework"]
    assert classify("改卡") is Intent.task
    assert route_skills("改卡", Intent.task) == ["grade_scans"]
    assert route_skills(
        r"C:\Users\Administrator\Downloads\课时练习_3_已完成答题卡 还是这个路径你再读取一遍试试",
        Intent.task,
    ) == ["grade_scans"]
    assert classify("出卡") is Intent.task
    assert classify("学情") is Intent.task
    assert extract_slots("学生1情况")["student_ordinal"] == 1
    assert "student_no" not in extract_slots("学生1情况")


def test_extract_paper_counts_and_points():
    slots = extract_slots("作业生成，按等差数列出题，出10道选择题每题3分，3道大题每题10分")
    assert slots["knowledge_points"] == ["等差数列"]
    assert slots["n_objective"] == 10
    assert slots["n_subjective"] == 3
    assert slots["objective_points"] == 3
    assert slots["subjective_points"] == 10
    rev = extract_slots("选择题10道，大题3道")
    assert rev["n_objective"] == 10
    assert rev["n_subjective"] == 3
    assert "objective_points" not in rev
    assert "subjective_points" not in rev
    spoken = extract_slots("出一份等差数列的试卷，20个选择题，3个大题")
    assert spoken["knowledge_points"] == ["等差数列"]
    assert spoken["n_objective"] == 20
    assert spoken["n_subjective"] == 3


def test_extract_paper_counts_not_confused_with_other_numbers():
    for text in (
        "按等差数列出题",
        "生成3个学生的写好以后的答题卡",
        "覆盖 5 分",
        "学生1情况",
        "第 1 条",
        "只出卡",
    ):
        slots = extract_slots(text)
        assert "n_objective" not in slots, text
        assert "n_subjective" not in slots, text
        assert "objective_points" not in slots, text
        assert "subjective_points" not in slots, text


def test_generate_from_natural_requirement():
    assert classify("出几道二次函数应用题") is Intent.task
    assert route_skills("出几道二次函数应用题", Intent.task) == ["generate_paper"]
    assert extract_slots("关于二次函数顶点式的课时作业，出题")["knowledge_points"] == ["二次函数顶点式"]
    assert resolve_intent("围绕抛物线开口方向，中等难度", {"skills": ["generate_paper"]}) is Intent.task
    assert classify("围绕抛物线开口方向，中等难度") is Intent.chat
    assert classify("生成6个选择题3个大题的语文试卷") is Intent.task
    assert route_skills("生成6个选择题3个大题的语文试卷", Intent.task) == ["generate_paper"]
    slots = extract_slots("生成6个选择题3个大题的语文试卷")
    assert slots["n_objective"] == 6 and slots["n_subjective"] == 3
    assert slots["subject"] == "语文"
    assert classify("打印出答题卡") is Intent.task
    assert route_skills("打印出答题卡", Intent.task) == ["generate_cards"]
    assert classify("出答题卡") is Intent.task
    assert classify("什么是试卷") is Intent.chat
    assert "import_roster" not in route_skills(
        "请先导入名单并出卡，再上传学生填好的答题卡批改", Intent.pipeline
    )
    assert classify("导入班级名单") is Intent.task
    assert route_skills("导入班级名单", Intent.task) == ["import_roster"]


def test_understand_uses_llm_json():
    import asyncio

    from zypg.gateway import intent as intent_mod
    from zypg.llm import set_json_backend

    async def paper(_user: str, _system: str = "") -> dict:
        return {
            "intent": "task",
            "skills": ["generate_paper"],
            "slots": {"subject": "语文", "n_objective": 6, "n_subjective": 3},
        }

    async def cards(_user: str, _system: str = "") -> dict:
        return {"intent": "task", "skills": ["generate_cards"], "slots": {}}

    set_json_backend(paper)
    try:
        out = asyncio.run(intent_mod.understand_utterance("帮我弄一份语文卷子，选择6道大题3道"))
        assert out["intent"] is Intent.task
        assert out["skills"] == ["generate_paper"]
        assert out["slots"]["n_objective"] == 6
        set_json_backend(cards)
        card = asyncio.run(intent_mod.understand_utterance("把答题卡打出来给我"))
        assert card["skills"] == ["generate_cards"]
        assert card["intent"] is Intent.task
    finally:
        set_json_backend(None)


def test_resolve_scan_source(tmp_path):
    from zypg.gateway.intent import resolve_scan_source

    imgs, err = resolve_scan_source(r"C:\Users\...\已完成答题卡")
    assert imgs == []
    assert err and "省略号" in err
    missing, err2 = resolve_scan_source(str(tmp_path / "no_such_dir"))
    assert missing == []
    assert err2 and "找不到" in err2
    folder = tmp_path / "cards"
    folder.mkdir()
    (folder / "S01_filled.png").write_bytes(b"png")
    (folder / "scores.csv").write_text("a,b\n", encoding="utf-8")
    found, err3 = resolve_scan_source(str(folder))
    assert err3 is None
    assert len(found) == 1
    assert found[0].endswith("S01_filled.png")


def test_intent_pipeline():
    assert classify("出这份作业并出卡") is Intent.pipeline
    assert classify("改完并给出讲评") is Intent.pipeline
    assert route_skills("出这份作业并出卡", Intent.pipeline) == ["generate_paper", "generate_cards"]
    assert route_skills("改完并给出讲评", Intent.pipeline) == ["grade_scans", "class_insight", "next_focus"]
    assert classify("做完以后进行质量升级，全自动") is Intent.pipeline
    assert route_skills("做完以后进行质量升级，全自动", Intent.pipeline) == [
        "grade_scans",
        "class_insight",
        "next_focus",
    ]
    # 单点名不是流水线
    assert classify("出卡") is Intent.task
    assert classify("学情") is Intent.task
