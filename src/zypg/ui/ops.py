from __future__ import annotations

from zypg.ui import client


def delete_homework_ui(homework_id: str, homeworks: list[dict] | None = None) -> None:
    import streamlit as st

    if not homework_id:
        st.error("当前没有可删的作业")
        return
    name = next(
        (h.get("name") for h in (homeworks or []) if h.get("homework_id") == homework_id),
        homework_id[:8],
    )
    try:
        client.delete("/ui/homework", homework_id=homework_id)
    except Exception as exc:
        st.error(f"删不掉：{exc}")
        return
    rest = [h for h in (homeworks or []) if h.get("homework_id") != homework_id]
    st.session_state.homework_id = (rest[0]["homework_id"] if rest else "") or ""
    st.session_state.conversation_id = ""
    st.session_state.local_chat = []
    st.session_state._del_chat = False
    st.session_state._confirm_del_hw = None
    st.session_state._state_cache = None
    st.session_state._remembered = None
    st.toast(f"已删除「{name}」")
    st.rerun()
