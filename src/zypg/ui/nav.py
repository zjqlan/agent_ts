from __future__ import annotations


def goto(page: str, **updates) -> None:
    import streamlit as st

    st.session_state.page = page
    st.session_state._remembered = None
    for key, value in updates.items():
        st.session_state[key] = value
    st.rerun()
