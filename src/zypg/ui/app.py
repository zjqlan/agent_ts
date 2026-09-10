from __future__ import annotations

import inspect
import json
import threading
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from zypg.config import settings
from zypg.models import ROSTER_REQUIRED
from zypg.ui import client
from zypg.ui import pages as views
from zypg.ui.nav import goto
from zypg.workspace import NAV

CSS = """
<style>
html, body, [data-testid="stAppViewContainer"] { min-width: 1280px; }
[data-testid="stSidebar"] { min-width: 200px; }
.block-container { padding-top: 2.4rem !important; padding-bottom: 6rem; }
/* Streamlit 顶栏（Deploy / 汉堡）会叠在标题上，汉字看起来像糊在一起 */
header[data-testid="stHeader"],
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
.stAppDeployButton,
.stDeployButton { display: none !important; }
iframe[height="0"], div[data-testid="stHtml"] iframe { display: none !important; height: 0 !important; }
.zypg-brand { font-size: 1.2rem; font-weight: 700; line-height: 1.35; letter-spacing: 0; white-space: nowrap; }
.zypg-role { font-size: 0.85rem; font-weight: 400; color: #555; line-height: 1.4; margin-top: 0.15rem; }
.zypg-top { font-size: 0.92rem; }
[data-testid="stNumberInput"] input { pointer-events: auto; }
</style>
"""

WHEEL_GUARD = """
<script>
const doc = window.parent.document;
if (doc && !doc._zypgWheelGuard) {
  doc._zypgWheelGuard = true;
  doc.addEventListener('wheel', (e) => {
    const t = e.target;
    if (!t || !t.closest) return;
    if (t.closest('[data-testid="stNumberInput"]') || t.closest('[data-testid="stSelectbox"]') || t.closest('[data-baseweb="select"]')) {
      if (typeof t.blur === 'function') t.blur();
    }
  }, {capture: true, passive: true});
}
</script>
"""

PAGE_FN = {
    "chat": views.page_chat,
    "roster": views.page_roster,
    "paper": views.page_paper,
    "cards": views.page_cards,
    "grade": views.page_grade,
    "queue": views.page_queue,
    "insight": views.page_insight,
    "lesson": views.page_lesson,
}


def _auth_file() -> Path:
    return settings.data_dir / "ui_auth.json"


def _save_auth_file() -> None:
    token = st.session_state.get("auth_token") or ""
    path = _auth_file()
    if not token:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps({"token": token}, ensure_ascii=False), encoding="utf-8")


def _clear_auth_file() -> None:
    _auth_file().unlink(missing_ok=True)


def _restore_auth_file() -> None:
    if st.session_state.get("auth_token"):
        return
    path = _auth_file()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    token = (data or {}).get("token") or ""
    if token:
        st.session_state.auth_token = token


def _apply_teacher(teacher: dict, restore_nav: bool = False) -> None:
    if not teacher:
        return
    st.session_state.teacher = teacher
    if teacher.get("last_class_id") and not st.session_state.class_id:
        st.session_state.class_id = teacher["last_class_id"]
    if teacher.get("last_homework_id") and not st.session_state.homework_id:
        st.session_state.homework_id = teacher["last_homework_id"]
    if restore_nav and not st.session_state.get("_nav_restored") and teacher.get("last_page") in PAGE_FN:
        st.session_state.page = teacher["last_page"]
        st.session_state._nav_restored = True


def _init() -> None:
    st.session_state.setdefault("page", "chat")
    st.session_state.setdefault("class_id", "")
    st.session_state.setdefault("homework_id", "")
    st.session_state.setdefault("conversation_id", "")
    st.session_state.setdefault("sid", "")
    st.session_state.setdefault("busy", False)
    st.session_state.setdefault("progress", None)
    st.session_state.setdefault("chips", [])
    st.session_state.setdefault("auth_token", "")
    st.session_state.setdefault("teacher", None)
    st.session_state.setdefault("local_chat", [])
    st.session_state.setdefault("_nav_restored", False)
    _restore_auth_file()


def _remember() -> None:
    if not st.session_state.get("auth_token"):
        return
    snap = (
        st.session_state.class_id or None,
        st.session_state.homework_id or None,
        st.session_state.page,
    )
    if snap == st.session_state.get("_remembered"):
        return
    st.session_state._remembered = snap
    token = st.session_state.get("auth_token") or ""
    body = {
        "last_class_id": st.session_state.class_id or None,
        "last_homework_id": st.session_state.homework_id or None,
        "last_page": st.session_state.page,
    }
    api = client.base()

    def _go() -> None:
        try:
            import httpx

            httpx.patch(
                f"{api}/auth/me",
                json=body,
                headers={"Authorization": f"Bearer {token}"} if token else {},
                timeout=15.0,
            )
        except Exception:
            pass

    threading.Thread(target=_go, daemon=True).start()


def _login_page() -> None:
    from zypg.subject import SUBJECTS

    st.markdown("### 教师登录")
    st.caption("登录时必须确认任教学科。语文老师不能生成数学试卷。")
    with st.form("teacher_login"):
        user = st.text_input("账号", value="teacher")
        pw = st.text_input("密码", type="password")
        subject = st.selectbox("任教学科", list(SUBJECTS), index=0)
        submitted = st.form_submit_button("登录", type="primary")
    st.caption("本机默认账号 `teacher` / `teacher123`，可在 .env 的 TEACHER_USERNAME、TEACHER_PASSWORD 修改。")
    if not submitted:
        return
    try:
        out = client.post_json("/auth/login", {"username": user.strip(), "password": pw, "subject": subject})
    except Exception as exc:
        st.error(str(exc))
        return
    teacher = out.get("teacher") or {}
    st.session_state.auth_token = out.get("token") or ""
    _apply_teacher(teacher, restore_nav=True)
    _save_auth_file()
    st.rerun()


def _ensure_login() -> bool:
    token = st.session_state.get("auth_token") or ""
    if token:
        teacher = st.session_state.get("teacher")
        last = float(st.session_state.get("_auth_at") or 0)
        if teacher and teacher.get("subject") and time.time() - last < 60:
            return True
        try:
            me = client.get("/auth/me")
            _apply_teacher(me.get("teacher") or {}, restore_nav=not teacher)
            st.session_state._auth_at = time.time()
            _save_auth_file()
            if not (st.session_state.get("teacher") or {}).get("subject"):
                _bind_subject_page()
                return False
            return True
        except client.ApiError as exc:
            if exc.status in (401, 403):
                st.session_state.auth_token = ""
                st.session_state.teacher = None
                st.session_state._auth_at = 0
                _clear_auth_file()
            else:
                st.error(str(exc))
                return False
        except Exception as exc:
            st.error(f"网关暂时不可达，登录状态已保留：{exc}")
            return False
    _login_page()
    return False


def _bind_subject_page() -> None:
    from zypg.subject import SUBJECTS

    st.markdown("### 确认任教学科")
    st.caption("第一次使用必须选定科目。选定后不能改科。语文老师不能出数学卷。")
    with st.form("bind_subject"):
        subject = st.selectbox("任教学科", list(SUBJECTS), index=0)
        submitted = st.form_submit_button("确定", type="primary")
    if not submitted:
        return
    try:
        out = client.patch_json("/auth/me", {"subject": subject})
        _apply_teacher(out.get("teacher") or st.session_state.get("teacher") or {})
        if not (st.session_state.get("teacher") or {}).get("subject"):
            me = client.get("/auth/me")
            _apply_teacher(me.get("teacher") or {})
        st.rerun()
    except Exception as exc:
        st.error(str(exc))


def _load_state(force: bool = False) -> dict:
    key = (st.session_state.class_id or "", st.session_state.homework_id or "")
    cache = st.session_state.get("_state_cache")
    ttl = 1.5 if cache and (cache.get("state") or {}).get("active_task") else 8
    if (
        not force
        and not st.session_state.get("_pending_ask")
        and not st.session_state.get("_asking")
        and cache
        and cache.get("key") == key
        and time.time() - float(cache.get("t") or 0) < ttl
    ):
        return cache["state"]
    try:
        state = client.get(
            "/ui/state",
            class_id=st.session_state.class_id or None,
            homework_id=st.session_state.homework_id or None,
        )
    except Exception as exc:
        st.error(f"网关不可达：{exc}")
        return (cache or {}).get("state") or {}
    if state.get("class_id") and not st.session_state.class_id:
        st.session_state.class_id = state["class_id"]
    if state.get("homework_id") and not st.session_state.homework_id:
        st.session_state.homework_id = state["homework_id"]
    if state.get("conversation_id"):
        st.session_state.conversation_id = state["conversation_id"]
    ids = {c["class_id"] for c in (state.get("classes") or [])}
    if st.session_state.class_id and st.session_state.class_id not in ids:
        st.session_state.class_id = (state.get("class_id") or "") if state.get("class_id") in ids else ""
        st.session_state.homework_id = ""
        state = client.get(
            "/ui/state",
            class_id=st.session_state.class_id or None,
            homework_id=None,
        )
    hw_ids = {h["homework_id"] for h in (state.get("homeworks") or [])}
    if st.session_state.homework_id and st.session_state.homework_id not in hw_ids:
        st.session_state.homework_id = state.get("homework_id") or ""
    st.session_state._state_cache = {
        "key": (st.session_state.class_id or "", st.session_state.homework_id or ""),
        "t": time.time(),
        "state": state,
    }
    return state


def _topbar(state: dict) -> dict:
    c1, c2, c3, c4 = st.columns([1.2, 1.6, 1.6, 1.2])
    with c1:
        name = (st.session_state.get("teacher") or {}).get("display_name") or ""
        subj = (st.session_state.get("teacher") or {}).get("subject") or ""
        role_txt = f"{name} · {subj}老师" if name and subj else name
        role = f'<div class="zypg-role">{role_txt}</div>' if role_txt else ""
        st.markdown(f'<div class="zypg-brand">作业批改</div>{role}', unsafe_allow_html=True)
    classes = state.get("classes") or []
    names = {f"{c['name']}（{c['n_students']}人）": c["class_id"] for c in classes}
    with c2:
        if not names:
            if st.button("未导入名单", key="no_class"):
                goto("roster")
        else:
            cur_label = next((k for k, v in names.items() if v == st.session_state.class_id), list(names)[0])
            pick = st.selectbox("班级", list(names), index=list(names).index(cur_label), label_visibility="collapsed")
            cid = names[pick]
            if cid != st.session_state.class_id:
                st.session_state.class_id = cid
                st.session_state.homework_id = ""
                st.session_state._remembered = None
                st.session_state._state_cache = None
                _remember()
                state = _load_state(force=True)
    homeworks = state.get("homeworks") or []
    hw_names = {"（新建作业）": ""}
    used: dict[str, int] = {}
    for h in homeworks:
        base = (h.get("name") or "未命名").strip() or "未命名"
        n = used.get(base, 0) + 1
        used[base] = n
        label = base if n == 1 else f"{base}（{n}）"
        while label in hw_names:
            n += 1
            label = f"{base}（{n}）"
        hw_names[label] = h["homework_id"]
    with c3:
        labels = list(hw_names)
        cur = next((k for k, v in hw_names.items() if v == st.session_state.homework_id), labels[0])
        pick = st.selectbox("本次作业", labels, index=labels.index(cur), label_visibility="collapsed")
        hid = hw_names[pick]
        if hid != st.session_state.homework_id:
            st.session_state.homework_id = hid
            st.session_state._remembered = None
            st.session_state._state_cache = None
            st.session_state._confirm_del_hw = None
            _remember()
            state = _load_state(force=True)
        if hid:
            if st.session_state.get("_confirm_del_hw") == hid:
                yes, no = st.columns(2)
                if yes.button("确认删除", type="primary", key="top_del_ok"):
                    from zypg.ui.ops import delete_homework_ui

                    delete_homework_ui(hid, homeworks)
                if no.button("取消", key="top_del_no"):
                    st.session_state._confirm_del_hw = None
                    st.rerun()
            elif st.button("删除", key="top_del_hw"):
                st.session_state._confirm_del_hw = hid
                st.rerun()
    with c4:
        qn = int(state.get("queue_count") or 0)
        st.markdown(f"阶段：**{state.get('stage_label') or '—'}**")
        if qn:
            if st.button(f"待确认({qn})", type="primary"):
                goto("queue")
        else:
            st.caption("待确认(0)")
    return state


def _nav(state: dict) -> None:
    st.sidebar.markdown("**导航**")
    for key, label in NAV:
        lock = (state.get("locks") or {}).get(key)
        suffix = " 🔒" if lock == "lock" else (" ·" if lock == "empty" else "")
        if st.sidebar.button(label + suffix, key=f"nav_{key}", use_container_width=True):
            if st.session_state.page != key:
                st.session_state.page = key
                st.session_state._remembered = None
                st.rerun()
    teacher = st.session_state.get("teacher") or {}
    who = teacher.get("display_name") or teacher.get("username") or ""
    subj = teacher.get("subject") or ""
    st.sidebar.caption((f"{who} · {subj}老师" if subj else who) + " 已登录")
    if st.sidebar.button("退出登录", key="logout"):
        try:
            client.post_json("/auth/logout", {})
        except Exception:
            pass
        st.session_state.auth_token = ""
        st.session_state.teacher = None
        st.session_state.class_id = ""
        st.session_state.homework_id = ""
        st.session_state.conversation_id = ""
        _clear_auth_file()
        st.rerun()
    st.sidebar.caption("聊天和按钮走同一网关。名单保存在本机数据库，登录后自动回到上次班级。")


def _task_banner(task: dict, *, backend: bool = False) -> None:
    done = task.get("done")
    total = task.get("total")
    skill = task.get("skill") or task.get("agent") or "进行中"
    cols = st.columns([4, 1])
    with cols[0]:
        msg = task.get("message") or ""
        if done is not None and total:
            st.progress(
                min(float(done) / float(total), 1.0),
                text=f"{skill} {done}/{total} {msg}".strip(),
            )
        else:
            st.info(f"进行中：{skill}" + (f" · {msg}" if msg else ""))
    with cols[1]:
        tid = task.get("task_id")
        if st.button("取消"):
            if tid:
                try:
                    client.post_json(f"/ui/tasks/{tid}/cancel", {})
                except Exception:
                    pass
            st.session_state["_pending_ask"] = None
            st.session_state["_asking"] = False
            st.session_state.progress = None
            st.toast("已取消卡住的任务，可重新点批改")
            st.rerun()
    if backend:
        st.caption("任务在网关后台运行，可以切换页面，不会中断。进度约每 2 秒刷新。")


def _composer(state: dict) -> None:
    if not state.get("active_task") and not st.session_state.get("_asking"):
        st.session_state.progress = None
    task = state.get("active_task") or st.session_state.get("progress")
    if task and state.get("active_task") and hasattr(st, "fragment"):

        @st.fragment(run_every=2)
        def _live_task() -> None:
            s = _load_state(force=True)
            t = s.get("active_task")
            if t:
                _task_banner(t, backend=True)
            else:
                st.rerun()

        _live_task()
    elif task:
        _task_banner(task, backend=bool(state.get("active_task")))
    chips = st.session_state.get("chips") or []
    if chips:
        st.caption("附件：" + "，".join(chips))
    kwargs: dict = {}
    params = inspect.signature(st.chat_input).parameters
    if "accept_file" in params:
        kwargs["accept_file"] = "multiple"
    if "file_type" in params:
        kwargs["file_type"] = ["csv", "xlsx", "xls", "md", "docx", "doc", "pdf", "txt", "png", "jpg", "jpeg"]
    busy = bool(st.session_state.get("_pending_ask") or st.session_state.get("_asking"))
    if "disabled" in params:
        kwargs["disabled"] = busy
    page = st.session_state.get("page")
    pending = st.session_state.get("_pending_ask")
    if page != "chat" and pending:
        with st.chat_message("user"):
            st.write(pending.get("text") or "")
        with st.chat_message("assistant"):
            slot = st.empty()
            st.session_state["_stream_slot"] = slot
            slot.caption("正在回复…")
    prompt = st.chat_input("说或点：出题 / 导入试卷 / 出卡 / 改卡 / 学情 / 备课。可附 md/docx/pdf。", **kwargs)
    if prompt and not busy:
        text, files = _split_chat_input(prompt)
        extra: dict = {}
        if not text:
            if files:
                text = "（附件）"
            else:
                text = ""
        if not text and not files:
            return
        if not text:
            text = "（附件）"
        st.session_state.setdefault("local_chat", []).append(
            {"role": "user", "text": text, "temp": True, "kind": "text"}
        )
        st.session_state["_pending_ask"] = {"text": text, "files": files, "extra": extra}
        st.session_state.page = "chat"
        st.session_state._remembered = None
        st.rerun()


def _split_chat_input(prompt) -> tuple[str, list]:
    if isinstance(prompt, str):
        return prompt.strip(), []
    text = (getattr(prompt, "text", None) or "")
    if hasattr(prompt, "get"):
        try:
            text = text or (prompt.get("text") or "")
        except Exception:
            pass
    text = str(text).strip()
    files = list(getattr(prompt, "files", None) or [])
    if not files:
        one = getattr(prompt, "file", None)
        if one:
            files = [one]
    if not files and hasattr(prompt, "get"):
        try:
            files = list(prompt.get("files") or [])
        except Exception:
            files = files
    return text, files


def _run_ask(state: dict) -> None:
    pending = st.session_state.get("_pending_ask")
    if not pending:
        return
    st.session_state["_asking"] = True
    text = pending.get("text") or ""
    extra = dict(pending.get("extra") or {})
    files = pending.get("files") or []
    if files:
        extra.update(client.extra_from_uploads(files))
        if text in {"", "（附件）"}:
            if extra.get("paper_path"):
                text = "导入这份卷子"
            elif extra.get("roster_path"):
                text = "导入班级名单"
            elif extra.get("scan_paths"):
                text = "批改这些扫描件"
    st.session_state["_pending_ask"] = None
    box = st.session_state.get("_stream_slot")
    if box is None:
        box = st.empty()
    prog = st.empty()

    def on_token(acc: str) -> None:
        if hasattr(box, "write"):
            box.write(acc)
        else:
            st.write(acc)

    def on_progress(ev: dict) -> None:
        st.session_state.progress = ev
        d, t = ev.get("done"), ev.get("total")
        if d is not None and t:
            msg = ev.get("message") or ""
            prog.progress(
                min(float(d) / float(t), 1.0),
                text=f"{ev.get('skill') or ev.get('agent') or ''} {d}/{t} {msg}".strip(),
            )

    try:
        routed = client.understand_ask(
            text,
            extra,
            st.session_state.class_id or None,
            st.session_state.homework_id or None,
        )
        intent_name = routed.get("intent") or "chat"
        skills = routed.get("skills") or []
        extra = {**extra, "understood": routed}
        if skills:
            extra["skills"] = skills
        if intent_name != "chat":
            out = client.start_ask(
                text,
                st.session_state.class_id or None,
                st.session_state.homework_id or None,
                st.session_state.conversation_id or None,
                st.session_state.sid or None,
                extra,
            )
            if out.get("conversation_id"):
                st.session_state.conversation_id = out["conversation_id"]
            if out.get("sid"):
                st.session_state.sid = out["sid"]
            st.session_state["_asking"] = False
            st.session_state["_state_cache"] = None
            st.toast("任务已在后台运行，切换页面不会中断")
            st.rerun()
            return
        done = client.ask_stream(
            text,
            st.session_state.class_id or None,
            st.session_state.homework_id or None,
            st.session_state.conversation_id or None,
            st.session_state.sid or None,
            extra,
            on_token=on_token,
            on_progress=on_progress,
        )
    except Exception as exc:
        done = {"ok": False, "kind": "refuse", "summary": str(exc), "error": str(exc)}
    st.session_state["_asking"] = False
    st.session_state.progress = None
    st.session_state["_state_cache"] = None
    st.session_state["_stream_slot"] = None
    if done.get("class_id"):
        st.session_state.class_id = done["class_id"]
    if done.get("homework_id"):
        st.session_state.homework_id = done["homework_id"]
    if done.get("conversation_id"):
        st.session_state.conversation_id = done["conversation_id"]
    if done.get("sid"):
        st.session_state.sid = done["sid"]
    _remember()
    if done.get("kind") == "refuse" or done.get("error") == ROSTER_REQUIRED:
        st.error(done.get("summary") or ROSTER_REQUIRED)
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="作业批改", layout="wide", initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    components.html(WHEEL_GUARD, height=0)
    _init()
    if not _ensure_login():
        return
    state = _load_state()
    if not state:
        return
    if state.get("class_id"):
        st.session_state.class_id = st.session_state.class_id or state["class_id"]
    _remember()
    if not (state.get("classes") or []) and st.session_state.page not in {"roster", "chat"}:
        st.session_state.page = "roster"
        state = _load_state(force=True)
    _nav(state)
    state = _topbar(state)
    st.divider()
    page = st.session_state.page
    if page != "chat" and page != "roster" and (state.get("locks") or {}).get(page) == "lock":
        st.info("本页主操作已锁。点按钮或说话都会返回：「请先导入班级名单」。")
    PAGE_FN.get(page, views.page_chat)(state)
    st.divider()
    _composer(state)
    _run_ask(state)


if __name__ == "__main__":
    main()
