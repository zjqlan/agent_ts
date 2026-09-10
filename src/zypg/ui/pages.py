from __future__ import annotations

import re

from zypg.models import ROSTER_REQUIRED
from zypg.ui import client
from zypg.ui.nav import goto


def _queue_ask(text: str, extra: dict | None = None) -> None:
    import streamlit as st

    st.session_state.setdefault("local_chat", []).append(
        {"role": "user", "text": text, "temp": True, "kind": "text"}
    )
    st.session_state["_pending_ask"] = {"text": text, "extra": extra or {}}
    st.session_state["_state_cache"] = None
    st.rerun()


def preview_image(path, caption: str = "", thumb: int = 420, key: str | None = None) -> None:
    import streamlit as st
    from pathlib import Path

    p = Path(path) if not isinstance(path, Path) else path
    if not p.exists():
        return
    url = client.file_url(p)
    st.caption(caption or p.name)
    st.markdown(
        f'<a href="{url}" target="_blank" rel="noopener">'
        f'<img src="{url}" alt="{caption or p.name}" '
        f'style="width:min(100%,{thumb}px);max-width:100%;height:auto;cursor:zoom-in;border:1px solid #ddd"/>'
        f"</a><div style='font-size:12px;color:#666'>点击图片在新标签打开原图</div>",
        unsafe_allow_html=True,
    )
    st.link_button("新窗口打开原图", url)


def _locked(state: dict, page: str) -> bool:
    return (state.get("locks") or {}).get(page) == "lock"


def _empty(state: dict, page: str) -> bool:
    return (state.get("locks") or {}).get(page) in {"lock", "empty"}


def _gate_button(label: str, page: str, state: dict, key: str) -> bool:
    import streamlit as st

    locked = _locked(state, page) or (page != "roster" and not state.get("n_students"))
    clicked = st.button(label, key=key, disabled=locked, type="primary")
    if clicked and locked:
        _queue_ask("帮我出卡" if page == "cards" else label)
        return False
    return clicked and not locked


def page_chat(state: dict) -> None:
    import streamlit as st

    st.subheader("对话")
    _chat_manage(state)
    chips = ["出一份高一语文课时作业", "导入这份卷子", "看看这班学情"]
    subj = (st.session_state.get("teacher") or {}).get("subject") or ""
    if subj and subj != "语文":
        chips = [f"出一份高一{subj}课时作业", "导入这份卷子", "看看这班学情"]
    cols = st.columns(3)
    for i, c in enumerate(chips):
        if cols[i].button(c, key=f"chip_{i}"):
            _queue_ask(c)
    msgs = client.get("/ui/messages", class_id=state.get("class_id"), homework_id=state.get("homework_id"))
    shown = _merge_chat(msgs.get("messages") or [])
    for msg in shown:
        with st.chat_message("user" if msg.get("role") == "user" else "assistant"):
            _render_bubble(msg)
    if st.session_state.get("_pending_ask") or st.session_state.get("_asking"):
        with st.chat_message("assistant"):
            slot = st.empty()
            st.session_state["_stream_slot"] = slot
            slot.caption("正在回复…")


def remove_homework(homework_id: str, homeworks: list | None = None) -> None:
    from zypg.ui.ops import delete_homework_ui

    delete_homework_ui(homework_id, homeworks)


def _chat_manage(state: dict) -> None:
    import streamlit as st

    hid = state.get("homework_id") or ""
    cid = state.get("class_id") or ""
    hw = next((h for h in (state.get("homeworks") or []) if h["homework_id"] == hid), None)
    if hid and hw:
        st.caption(f"当前对话：{hw.get('name') or hid[:8]}")
    else:
        st.caption("还没有绑定作业。点「新建对话」开一窗，或出题后自动绑定。")
    a, b, c = st.columns(3)
    if a.button("新建对话", disabled=not cid):
        try:
            out = client.post_json("/ui/homework", {"class_id": cid, "name": "新对话"})
        except Exception as exc:
            st.error(str(exc))
            return
        st.session_state.homework_id = out.get("homework_id") or ""
        st.session_state.conversation_id = ""
        st.session_state.local_chat = []
        st.session_state._state_cache = None
        st.rerun()
    if hid:
        with b.expander("重命名"):
            name = st.text_input("名称", value=(hw or {}).get("name") or "", key="chat_rename")
            if st.button("保存名称") and name.strip():
                try:
                    client.patch_json("/ui/homework", {"name": name.strip()}, homework_id=hid)
                except Exception as exc:
                    st.error(str(exc))
                    return
                st.session_state._state_cache = None
                st.rerun()
        if st.session_state.get("_confirm_del_hw") == hid:
            if c.button("确认删除", type="primary", key="chat_del_ok"):
                remove_homework(hid, state.get("homeworks") or [])
            if st.button("取消删除", key="chat_del_no"):
                st.session_state._confirm_del_hw = None
                st.rerun()
        elif c.button("删除本对话", key="chat_del"):
            st.session_state._confirm_del_hw = hid
            st.rerun()


def _merge_chat(server: list[dict]) -> list[dict]:
    import streamlit as st
    from collections import Counter

    local = list(st.session_state.get("local_chat") or [])
    counts = Counter(m.get("text") for m in server if m.get("role") == "user")
    seen: Counter[str] = Counter()
    kept: list[dict] = []
    for m in local:
        if m.get("role") == "user":
            text = m.get("text") or ""
            seen[text] += 1
            if seen[text] <= counts[text]:
                continue
        kept.append(m)
    st.session_state.local_chat = kept
    return list(server) + kept


def _render_bubble(msg: dict) -> None:
    import streamlit as st

    kind = msg.get("kind") or "text"
    intent = msg.get("intent")
    label = {"chat": "闲聊", "task": "单任务", "pipeline": "闭环"}.get(intent or "", "")
    if label:
        st.caption(label)
    if kind == "refuse":
        st.error(msg.get("text") or ROSTER_REQUIRED)
    else:
        st.write(msg.get("text") or "")
    for act in msg.get("actions") or []:
        if st.button(act.get("label") or "查看", key=f"act_{msg.get('id')}_{act.get('page')}"):
            goto(act.get("page") or "paper")


def page_roster(state: dict) -> None:
    import streamlit as st
    from zypg.config import ROOT

    first = not (state.get("classes") or [])
    if first:
        st.subheader("先导入这个班的学生，才能出卡和按人归档。")
    else:
        st.subheader("名单")
    name = st.text_input("班级名（必填）", value=(state.get("class") or {}).get("name") or "", key="roster_name")
    grade = st.text_input("年级", value=(state.get("class") or {}).get("grade") or "高一", key="roster_grade")
    teacher_subj = (st.session_state.get("teacher") or {}).get("subject") or state.get("teacher_subject") or ""
    class_subj = (state.get("class") or {}).get("subject") or teacher_subj or "数学"
    if teacher_subj:
        st.caption(f"本班科目锁定为您的任教学科：{teacher_subj}")
        subject = teacher_subj
    else:
        subject = st.text_input("科目", value=class_subj, key="roster_subject")
    sample = ROOT / "samples" / "roster.example.csv"
    if sample.exists():
        st.download_button("下载模板 CSV", data=sample.read_bytes(), file_name="roster.example.csv", mime="text/csv")
    up = st.file_uploader("上传 CSV / XLSX", type=["csv", "xlsx", "xls"], key="roster_up")
    preview = None
    if up:
        try:
            preview = client.post_file("/ui/roster/preview", up)
            st.caption(f"{preview.get('count')} 行")
            st.dataframe(preview.get("rows") or [], hide_index=True, use_container_width=True)
            if preview.get("duplicates"):
                st.error("重复学号，不可提交：" + "、".join(preview["duplicates"]))
        except Exception as exc:
            st.error(str(exc))
    c1, c2, c3 = st.columns(3)
    if c1.button("确认导入", type="primary", disabled=not (up and name.strip() and preview and preview.get("ok"))):
        dest = client.save_upload(up, "rosters")
        st.session_state.page = "chat"
        _queue_ask(
            "导入班级名单",
            {
                "skills": ["import_roster"],
                "path": dest,
                "class_name": name.strip(),
                "grade": grade,
                "subject": subject,
            },
        )
    if first and c2.button("我先问问题"):
        goto("chat")
    if not first and state.get("class_id"):
        if c2.button("追加导入") and up:
            try:
                r = client.post_file(
                    "/ui/roster/append",
                    up,
                    extra={"class_id": state["class_id"]},
                )
                if r.get("skipped"):
                    st.warning("重复学号已跳过：" + "、".join(r["skipped"]))
                st.success(f"新增 {r.get('added')} 人，现有 {r.get('count')} 人")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if c3.button("整班替换（需确认）"):
            st.session_state["_replace_roster"] = True
        if st.session_state.get("_replace_roster"):
            st.warning("替换会清空本班当前名单再导入，不会一键抹掉历史成绩。")
            if st.button("确认替换") and up:
                try:
                    client.post_file(
                        "/ui/roster/replace",
                        up,
                        extra={"class_id": state["class_id"], "confirm": "1", "class_name": name.strip()},
                    )
                    st.session_state["_replace_roster"] = False
                except Exception as exc:
                    st.error(str(exc))
        q = st.text_input("搜索学号或姓名", key="roster_q")
        data = client.get("/ui/roster", class_id=state["class_id"], q=q or None)
        st.dataframe(data.get("students") or [], hide_index=True, height=420, use_container_width=True)
        st.caption("纠正名单只改正姓名；学号错了请作废该学号并新增，避免悄悄改历史。")
        st.link_button("导出当前名单 CSV", f"{client.base()}/ui/roster/export?class_id={state['class_id']}")


def page_paper(state: dict) -> None:
    import streamlit as st

    st.subheader("试卷")
    locked = _locked(state, "paper")
    teacher_subj = (st.session_state.get("teacher") or {}).get("subject") or state.get("teacher_subject") or ""
    class_subj = (state.get("class") or {}).get("subject") or ""
    if locked:
        st.warning(ROSTER_REQUIRED)
    left, right = st.columns([1, 1.2])
    with left:
        mode = st.radio("模式", ["生成", "导入"], horizontal=True, key="paper_mode")
        if mode == "生成":
            from zypg.subject import paper_defaults

            subject = teacher_subj or class_subj or "数学"
            if teacher_subj:
                st.caption(f"按您的任教学科出题：{teacher_subj}。不能生成其他科目试卷。")
            kp_default, req_default = paper_defaults(subject)
            name = st.text_input("作业名", "课时练习", key="paper_name")
            if teacher_subj:
                st.text_input("科目", value=subject, key="paper_subject", disabled=True)
            else:
                subject = st.text_input("科目", subject, key="paper_subject")
            grade = st.text_input("年级", "高一", key="paper_grade")
            kps = st.text_input("知识点（逗号分隔）", kp_default, key="paper_kps")
            n_obj = st.number_input("客观题数量", 0, 20, 2, key="paper_nobj")
            n_subj = st.number_input("主观题数量", 0, 10, 1, key="paper_nsub")
            requirement = st.text_area(
                "出题需求（会按这段话出题）",
                req_default,
                key="paper_req",
                height=100,
            )
            need = st.checkbox("需要答案和评分点", value=True, key="paper_need")
            if not need:
                st.warning("不提供答案/评分点将标记为不可机改（gradeable=false）。")
            if not state.get("llm_configured"):
                st.info("未配置模型，请改用导入。")
            if st.button(
                "生成试卷",
                type="primary",
                disabled=locked or not state.get("llm_configured"),
            ):
                req = (requirement or "").strip() or f"按{kps}出题"
                extra = {
                    "skills": ["generate_paper"],
                    "name": name,
                    "subject": subject,
                    "grade": grade,
                    "knowledge_points": kps,
                    "n_objective": int(n_obj),
                    "n_subjective": int(n_subj),
                    "requirement": req,
                }
                ask_text = req if re.search(r"出题|出卷|生成试卷|出一套|出一份", req) else f"{req}。请按此需求出题。"
                _queue_ask(ask_text, extra)
        else:
            up = st.file_uploader("上传 md / docx / pdf", type=["md", "docx", "doc", "pdf", "txt"], key="paper_up")
            st.caption("支持本系统导出的 Markdown，或带题号（1. / 1、）和选项 A.B.C.D. 的 Word/PDF。")
            if st.button("解析导入", type="primary", disabled=locked or not up):
                dest = client.save_upload(up, "papers")
                extra = {"skills": ["import_paper"], "path": dest, "paper_path": dest}
                if teacher_subj:
                    extra["subject"] = teacher_subj
                _queue_ask("导入这份卷子", extra)
    with right:
        paper = client.get("/ui/paper", homework_id=state.get("homework_id"), class_id=state.get("class_id"))
        hw = paper.get("homework")
        if not hw:
            st.info("还没有本次作业。生成或导入后会出现题目预览。")
            return
        st.markdown(f"**{hw.get('name')}**")
        if paper.get("gradeable") is False:
            st.warning("缺答案不能机改客观题 / 缺评分点主观题全进队列")
        else:
            st.success("可出卡")
        hid = state.get("homework_id")
        dl1, dl2 = st.columns(2)
        if paper.get("download_url"):
            dl1.link_button("下载 DOCX", str(paper["download_url"]))
        elif hid:
            dl1.link_button("下载 DOCX", f"{client.base()}/ui/paper.docx?homework_id={hid}")
        if hid and paper.get("md"):
            dl2.link_button("下载 Markdown", f"{client.base()}/ui/paper.md?homework_id={hid}")
        if paper.get("download_url"):
            st.caption("本机下载地址：" + str(paper["download_url"]))
        elif paper.get("mock"):
            st.caption("排版为本地 mock（未连 edupaper-mcp）")
        for it in paper.get("items") or []:
            with st.expander(f"{it.get('number')} · {it.get('kind')} · {(it.get('stem') or '')[:40]}"):
                st.write(it.get("stem") or "")
                if it.get("options"):
                    st.write(it["options"])
                ak = it.get("answer_key") or {}
                ans = ak.get("letter") or ak.get("text") or ""
                new_ans = st.text_input("答案", ans, key=f"ans_{it['item_id']}")
                rubric = it.get("rubric") or []
                new_rub = st.text_area("评分点（每行一条）", "\n".join(str(x) for x in rubric), key=f"rub_{it['item_id']}")
                if st.button("保存到题目", key=f"save_{it['item_id']}"):
                    client.patch_json(
                        f"/ui/items/{it['item_id']}",
                        {"answer": new_ans, "rubric": [x.strip() for x in new_rub.splitlines() if x.strip()]},
                        homework_id=state["homework_id"],
                    )
                    st.success("已写入 MySQL items")
                    st.rerun()


def page_cards(state: dict) -> None:
    import streamlit as st

    st.subheader("答题卡")
    if not state.get("n_students"):
        st.warning(ROSTER_REQUIRED)
        if st.button("去名册页", type="primary"):
            goto("roster")
        return
    if not state.get("n_items"):
        st.info("还没有题目结构。请先去试卷页生成或导入。")
        if st.button("去试卷页"):
            goto("paper")
        return
    hid = state.get("homework_id")
    cid = state.get("class_id")
    data = client.get("/ui/cards", homework_id=hid, class_id=cid)
    stale = bool(data.get("stale"))
    has_cards = bool(data.get("paths"))
    if stale:
        st.warning("当前仍是旧卡（没有学号填涂和独立卡号）。点下面立刻在本页生成新卡，不必去对话。")

    def _render_now() -> None:
        with st.spinner("正在生成本班答题卡…"):
            client.post_json("/ui/cards/generate", {}, homework_id=hid, class_id=cid)
        st.session_state["_re_cards"] = False
        st.rerun()

    if stale or not has_cards:
        if st.button("立即生成新卡" if stale else "生成本班答题卡", type="primary"):
            _render_now()
    else:
        if st.button("再次出卡（覆盖旧文件）"):
            st.session_state["_re_cards"] = True
        if st.session_state.get("_re_cards"):
            st.warning("会替换本作业已生成卡，未收回的纸质卡将无法匹配新模板。")
            if st.button("确认覆盖出卡", type="primary"):
                _render_now()
    st.caption("选择题在前、解答题在后；一页不够会自动分页。每人预印学号、填涂格和卡号。空白对照卡不发学生。")
    if data.get("print_path"):
        st.text_input("打印目录（只读）", data["print_path"], disabled=True)
    students = data.get("students") or []
    paths = data.get("paths") or []
    geom = ((data.get("template") or {}).get("geometry") or {})
    student_cards = geom.get("student_cards") or {}
    if not paths and not student_cards:
        return
    labels = [s["student_no"] for s in students] or list(student_cards) or [p.split("/")[-1] for p in paths]
    pick = st.selectbox("预览学生", labels, index=0)
    page_files = student_cards.get(pick) or ([paths[labels.index(pick)]] if pick in labels and paths else paths[:1])
    if len(page_files) > 1:
        page_i = st.selectbox("预览页", list(range(len(page_files))), format_func=lambda i: f"第 {i + 1}/{len(page_files)} 页")
        img = page_files[page_i]
    else:
        img = page_files[0] if page_files else paths[0]
    p = client.abs_data(img)
    if p.exists():
        preview_image(p, caption=p.name, thumb=420)
    c1, c2 = st.columns(2)
    if p.exists():
        c1.download_button("下载这张 PNG", data=p.read_bytes(), file_name=p.name)
    c2.link_button("下载整包 zip", f"{client.base()}/ui/cards.zip?homework_id={hid}")


def page_grade(state: dict) -> None:
    import streamlit as st

    st.subheader("批改")
    if _locked(state, "grade"):
        stage = state.get("stage")
        if stage == "no_roster":
            st.warning("请先导入班级名单")
            if st.button("去名单页", type="primary"):
                goto("roster")
        elif stage == "no_paper":
            st.warning("请先生成或导入试卷，再出卡。")
            if st.button("去试卷页", type="primary"):
                goto("paper")
        else:
            st.warning("请先出卡，再收回扫描件批改。这个班已经有名单。")
            if st.button("去出卡", type="primary"):
                goto("cards")
        return
    if not state.get("has_cards"):
        st.info("尚无答题卡模板，请先出卡。")
        return
    files = st.file_uploader(
        "上传学生填好的答题卡（可多选 png / jpg）",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="grade_up",
    )
    scan_dir = st.text_input(
        "或填写本机文件夹路径",
        key="grade_dir",
        placeholder=r"C:\Users\Administrator\Downloads\语文练习_1_已作答答题卡",
        help="填完整路径，不要用省略号。也可直接填 zip。",
    )
    data = client.get("/ui/grades", homework_id=state.get("homework_id"), class_id=state.get("class_id"))
    st.caption(
        f"已收 {data.get('scanned', 0)} 张（其中已批 {data.get('graded', data.get('scanned', 0))}）"
        f" / 名单 {data.get('expected', 0)} 人。批改读取学生填卡，不会让大模型代答。"
    )
    busy = bool(state.get("active_task"))
    if st.button("开始批改", type="primary", disabled=busy):
        hid = state.get("homework_id")
        cid = state.get("class_id")
        body: dict = {}
        try:
            if files:
                with st.spinner(f"正在保存 {len(files)} 张扫描件…"):
                    extra = client.extra_from_uploads(files)
                body["scan_paths"] = extra.get("scan_paths") or []
            folder = (scan_dir or "").strip()
            if folder:
                body["scan_dir"] = folder
            if not body.get("scan_paths") and not body.get("scan_dir"):
                st.error("请先上传 png/jpg，或填写本机文件夹的完整路径。")
            else:
                with st.spinner("正在批改，请稍候（主观题识别可能较慢）…"):
                    r = client.post_json(
                        "/ui/grades/run",
                        body,
                        homework_id=hid,
                        class_id=cid,
                        timeout=1800.0,
                    )
                st.success(
                    f"已批改 {r.get('scanned', 0)} 张，结果 {r.get('results', 0)} 条，确认队列 {r.get('queued', 0)} 条。"
                )
                st.rerun()
        except Exception as exc:
            st.error(str(exc))
    rows = data.get("rows") or []
    if rows:
        st.dataframe(
            [
                {
                    "学号": r["student_no"],
                    "姓名": r["name"],
                    "客观分": r["objective_score"],
                    "主观建议分": r["subjective_suggested"],
                    "待确认": "是" if r["pending"] else "",
                    "缺卡": "是" if r["missing"] else "",
                }
                for r in rows
            ],
            hide_index=True,
            use_container_width=True,
        )
        nos = [r["student_no"] for r in rows]
        pick = st.selectbox("查看学生", nos)
        row = next(r for r in rows if r["student_no"] == pick)
        if row.get("scan_path"):
            img = client.abs_data(row["scan_path"])
            if img.exists():
                preview_image(img, caption=pick, thumb=520)
        for it in row.get("results") or []:
            st.write(f"{it.get('item_id')}  source={it.get('source')}  score={it.get('score')}  pending={it.get('pending')}")
            raw = it.get("raw") or {}
            if raw.get("ocr"):
                st.caption("OCR（仅老师）：" + str(raw["ocr"])[:400])
    unmatched = data.get("unmatched") or []
    if unmatched:
        st.subheader("无法识别")
        st.dataframe(unmatched, hide_index=True, use_container_width=True)
    if state.get("queue_count"):
        if st.button("去确认队列"):
            goto("queue")


def page_queue(state: dict) -> None:
    import streamlit as st

    st.subheader("确认队列")
    if _empty(state, "queue") and not state.get("queue_count"):
        st.info("还没批改，队列是空的。")
        return
    data = client.get("/ui/reviews", homework_id=state.get("homework_id"), class_id=state.get("class_id"))
    items = data.get("items") or []
    if not items:
        st.success("没有待确认项。")
        if st.button("写入长期画像", type="primary"):
            _queue_ask("写入长期画像", {"skills": ["commit_long_term"]})
        return
    if st.button("全部采用建议分"):
        st.session_state["_acc_all"] = True
    if st.session_state.get("_acc_all"):
        st.warning("将把当前队列全部标为老师确认的建议分，不是官方机改分。")
        if st.button("确认全部采用"):
            st.session_state["_acc_all"] = False
            _queue_ask("全部采用建议分", {"skills": ["review_queue"], "review_action": "accept_all"})
    unsub = data.get("unsubmitted") or []
    for row in items:
        cols = st.columns([1, 1, 2, 2, 2])
        cols[0].write(row.get("student_no") or "—")
        cols[1].write(row.get("item_id") or "—")
        cols[2].write(row.get("reason") or "")
        if row.get("crop"):
            img = client.abs_data(row["crop"])
            if img.exists():
                preview_image(img, caption=str(row.get("item_id") or ""), thumb=220, key=f"crop_{row['id']}")
        score = cols[4].number_input(
            "老师分",
            value=float(row.get("suggested_score") or 0),
            key=f"sc_{row['id']}",
        )
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("采用建议", key=f"acc_{row['id']}"):
            client.post_json(f"/ui/reviews/{row['id']}", {"action": "accepted"}, class_id=state.get("class_id"))
            st.rerun()
        if b2.button("改分", key=f"ov_{row['id']}"):
            client.post_json(
                f"/ui/reviews/{row['id']}",
                {"action": "overridden", "score": score},
                class_id=state.get("class_id"),
            )
            st.rerun()
        if b3.button("暂不处理", key=f"sk_{row['id']}"):
            st.info("已跳过此项，仍计为待确认。")
        if row.get("reason") == "bad_id":
            opts = {f"{s['student_no']} {s['name']}": s["student_id"] for s in unsub}
            if opts:
                pick = b4.selectbox("绑定未交卡学生", list(opts), key=f"bd_{row['id']}")
                if st.button("绑定学号", key=f"bdb_{row['id']}"):
                    client.post_json(
                        f"/ui/reviews/{row['id']}",
                        {"action": "bind", "student_id": opts[pick]},
                        class_id=state.get("class_id"),
                    )
                    st.rerun()
            if st.button("标为废卡", key=f"void_{row['id']}"):
                client.post_json(f"/ui/reviews/{row['id']}", {"action": "void"})
                st.rerun()
        st.divider()


def page_insight(state: dict) -> None:
    import streamlit as st
    st.subheader("学情")
    st.caption("给老师看：先讲什么、单独看谁、下次补哪点。数字来自已批改成绩，讲评由大模型根据这些数字写，不编造。")
    if _empty(state, "insight") and not state.get("has_insight"):
        st.info("请先收回扫描件批改。没有成绩时不会画空图。")
        return
    cols = st.columns([1, 1, 2])
    with cols[0]:
        if st.button("生成本次班级学情", type="primary"):
            _queue_ask("看看这班学情", {"skills": ["class_insight"]})
    with cols[1]:
        if not state.get("queue_count") and state.get("homework_id"):
            if st.button("写入长期画像"):
                _queue_ask("写入长期画像", {"skills": ["commit_long_term"]})
        elif state.get("queue_count"):
            st.caption("队列未清空，长期画像先不写。")
    pack = client.get("/ui/insight", class_id=state.get("class_id"), homework_id=state.get("homework_id"))
    if pack.get("pending_note"):
        st.warning("含待确认，长期画像未写入")
    tab_c, tab_s = st.tabs(["班级", "个人"])
    with tab_c:
        w1, w2 = st.tabs(["本次", "长期"])
        with w1:
            short = pack.get("short") or {}
            if not pack.get("has_data"):
                st.info("请先批改并确认。")
            else:
                if short.get("headline"):
                    st.markdown(f"**{short['headline']}**")
                m1, m2, m3, m4 = st.columns(4)
                avg = float(short.get("average") or 0)
                mx = float(short.get("max_total") or 0)
                m1.metric("班均", f"{avg:.1f}" + (f" / {mx:.0f}" if mx else ""))
                submitted = int(short.get("n_submitted") or 0)
                n_all = int(short.get("n_students") or 0)
                m2.metric("交卡 / 应到", f"{submitted}/{n_all}" if n_all else submitted)
                m3.metric("待确认", state.get("queue_count") or 0)
                m4.metric("必讲知识点", len(short.get("must_teach") or []))
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown("**全班先讲**")
                    st.write(short.get("first_teach") or ("、".join(short.get("must_teach") or []) or "正确率都在六成以上，按错题订正即可。"))
                with c2:
                    st.markdown("**建议单独看**")
                    who = short.get("watch_who") or [f"{w['student_no']}：{w.get('why')}" for w in (short.get("watch_candidates") or [])]
                    st.write("\n".join(f"- {x}" for x in who[:8]) if who else "本卷没有明显需要单独订正的人。")
                with c3:
                    st.markdown("**下次补**")
                    st.write(short.get("next_focus") or ("、".join(short.get("must_teach") or []) or "保持现有节奏。"))
                if short.get("llm_review"):
                    st.markdown("**讲评**")
                    st.write(short["llm_review"])
                    if short.get("llm_model"):
                        st.caption(f"由 {short['llm_model']} 根据上方统计撰写")
                moves = short.get("classroom_moves") or []
                if moves:
                    st.markdown("**课堂上可以马上做**")
                    for m in moves:
                        st.write(f"- {m}")
                from zypg.ui.insight_charts import render_class_short_charts

                render_class_short_charts(short)
                hard = short.get("hard_items") or []
                if hard:
                    st.markdown("**讲评优先看这些题**")
                    rows = []
                    for h in hard:
                        acc_v = h.get("accuracy")
                        rows.append(
                            {
                                "题": h.get("label") or h.get("item_id"),
                                "知识点": h.get("knowledge_point"),
                                "正确率": None if acc_v is None else f"{round(float(acc_v)*100)}%",
                                "错了几人": h.get("n_wrong"),
                                "题干": h.get("stem"),
                            }
                        )
                    st.dataframe(rows, hide_index=True, use_container_width=True)
                miss = short.get("missing_cards") or []
                if miss:
                    st.caption("未交卡：" + "、".join(str(x) for x in miss[:20]) + ("…" if len(miss) > 20 else ""))
        with w2:
            from zypg.ui.insight_charts import render_class_long

            render_class_long(pack.get("long") or {})
    with tab_s:
        students = pack.get("students") or []
        if not students:
            return
        labels = {f"{s['student_no']} {s['name']}": s["student_id"] for s in students}
        pick = st.selectbox("学生", list(labels))
        if st.button("用大模型写这份辅导"):
            no = pick.split()[0]
            _queue_ask(f"看看学号 {no} 的学情", {"skills": ["student_insight"], "student_no": no})
        one = client.get(
            "/ui/insight/student",
            class_id=state.get("class_id"),
            student_id=labels[pick],
            homework_id=state.get("homework_id"),
        )
        w1, w2 = st.tabs(["本次", "长期"])
        with w1:
            short = one.get("short") or {}
            if short.get("headline"):
                st.markdown(f"**{short['headline']}**")
            m1, m2, m3 = st.columns(3)
            tot = short.get("total")
            mx = short.get("max_total")
            m1.metric("本卷", "—" if tot is None else f"{float(tot):.1f}" + (f" / {float(mx):.0f}" if mx else ""))
            avg = short.get("class_avg")
            delta = short.get("delta")
            m2.metric("比班均", "—" if delta is None else f"{delta:+.1f}", help=f"班均 {avg:.1f}" if avg is not None else None)
            rank = short.get("rank")
            n_sub = short.get("n_submitted")
            m3.metric("交卡中的位次", "—" if not rank else f"{rank} / {n_sub}")
            if short.get("llm_review"):
                st.write(short["llm_review"])
            coach = short.get("coach") or {}
            if coach.get("next_steps") or coach.get("needs") or coach.get("strengths"):
                a, b, c = st.columns(3)
                with a:
                    st.markdown("**已经会的**")
                    st.write("\n".join(f"- {x}" for x in (coach.get("strengths") or [])) or "—")
                with b:
                    st.markdown("**要补的**")
                    st.write("\n".join(f"- {x}" for x in (coach.get("needs") or [])) or "—")
                with c:
                    st.markdown("**下一步**")
                    st.write("\n".join(f"- {x}" for x in (coach.get("next_steps") or [])) or "—")
            kp_vs = short.get("kp_vs_class") or {}
            if kp_vs:
                from zypg.ui.insight_charts import render_student_vs_class

                render_student_vs_class(kp_vs)
            scores = short.get("scores") or []
            if scores:
                st.markdown("**各题**")
                st.dataframe(
                    [
                        {
                            "题": s.get("number") or s.get("item_id"),
                            "题型": "选择" if s.get("kind") == "objective" else "大题",
                            "知识点": s.get("knowledge_point"),
                            "得分": s.get("score"),
                            "满分": s.get("max_score"),
                            "结果": s.get("status") or "",
                            "题干": s.get("stem"),
                        }
                        for s in scores
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.info("还没有该生的作答记录。若批改页已有分数，请确认学号已匹配。")
            wrong = short.get("wrong_book") or []
            if wrong:
                st.markdown("**错题 / 低分（订正用）**")
                st.dataframe(
                    [
                        {
                            "题": w.get("number") or w.get("item_id"),
                            "知识点": w.get("knowledge_point"),
                            "得分": w.get("score"),
                            "满分": w.get("max_score"),
                            "题干": _insight_stem(w.get("stem")),
                        }
                        for w in wrong
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            if short.get("pending_note"):
                st.warning(short["pending_note"])
        with w2:
            from zypg.ui.insight_charts import render_student_long

            render_student_long(one.get("long") or {})


def _insight_stem(text) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= 48 else s[:47] + "…"


def page_lesson(state: dict) -> None:
    import streamlit as st

    st.subheader("备课")
    data = client.get("/ui/lesson", class_id=state.get("class_id"), homework_id=state.get("homework_id"))
    if not data.get("has_pack"):
        st.info("还没有 InsightPack。请先去学情页生成。")
        if st.button("去学情页"):
            goto("insight")
        return
    if data.get("pending_note"):
        st.warning("学情含待确认，提纲仅供参考。")
    if data.get("headline"):
        st.markdown(f"**{data['headline']}**")
    st.markdown("**下次讲课重点**")
    st.write(data.get("first_teach") or "、".join(data.get("must_teach") or []) or "（无）")
    if data.get("classroom_moves"):
        st.markdown("**课堂上可以马上做**")
        for m in data["classroom_moves"]:
            st.write(f"- {m}")
    if st.button("生成备课提纲"):
        _queue_ask("备课提纲", {"skills": ["next_focus"]})
    st.text_area("提纲（可编辑）", "\n".join(data.get("outline") or []), key="les_out", height=160)
