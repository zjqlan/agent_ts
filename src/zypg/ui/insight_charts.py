from __future__ import annotations

from typing import Any

_DUMMY = {"", "未标注", "未指定知识点"}


def _dummy(k: Any) -> bool:
    return str(k or "").strip() in _DUMMY


def _wrap_label(text: str, width: int = 8) -> str:
    s = str(text or "").strip()
    if len(s) <= width:
        return s
    return "\n".join(s[i : i + width] for i in range(0, min(len(s), width * 3), width))


def render_class_short_charts(short: dict[str, Any]) -> None:
    import pandas as pd
    import streamlit as st

    acc = {k: float(v) for k, v in (short.get("knowledge_accuracy") or {}).items() if not _dummy(k)}
    item_like = bool(acc) and all(str(k).startswith("第") and str(k).endswith("题") for k in acc)
    if acc and not item_like:
        st.markdown("**本班各知识点正确率（按题次，已确认）**")
        st.caption("红虚线 = 必讲线 60%。红柱低于六成该先讲，蓝柱过线。")
        from zypg.mcp_tools.charts import figure_kp_bars, figure_kp_radar

        fig_a = figure_kp_bars(acc)
        if fig_a is not None:
            st.pyplot(fig_a, use_container_width=True)
            import matplotlib.pyplot as plt

            plt.close(fig_a)
        rows = []
        for k, v in sorted(acc.items(), key=lambda kv: kv[1]):
            pct = round(v * 100)
            delta = pct - 60
            rows.append(
                {
                    "知识点": k,
                    "正确率": f"{pct}%",
                    "相对六成": "刚好过线" if delta == 0 else (f"低 {abs(delta)} 个百分点，该讲" if delta < 0 else f"高 {delta} 个百分点"),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        fig_r = figure_kp_radar(acc)
        if fig_r is not None:
            st.caption("雷达：红圈仍是六成，红点该讲。")
            st.pyplot(fig_r, use_container_width=True)
            import matplotlib.pyplot as plt

            plt.close(fig_r)

    mx = float(short.get("max_total") or 0)
    avg = float(short.get("average") or 0)
    bands = short.get("score_bands") or {}
    low = int(bands.get("未到六成") or 0)
    mid = int(bands.get("六到八成") or 0)
    high = int(bands.get("八成以上") or 0)
    n = low + mid + high
    if n or mx:
        line = 0.6 * mx if mx else None
        st.markdown("**过没过六成（按总分）**")
        if line is not None:
            st.write(
                f"这张卷满分 **{mx:.0f}**，六成线是 **{line:.1f} 分**。"
                f"班均 {avg:.1f} 分。"
                + (f"交卡 {n} 人里，**{low} 人没到六成**，{mid} 人在六到八成，{high} 人八成以上。" if n else "")
            )
        else:
            st.write(f"班均 {avg:.1f}。")

    grid = short.get("item_grid") or []
    if grid:
        cols = [c for c in grid[0].keys() if c != "学号"]
        pending_cols = [c for c in cols if any(r.get(c) == "待" for r in grid)]
        shown = [c for c in cols if c not in pending_cols]
        if pending_cols:
            st.caption("大题还在确认队列，热力只画已经能判对错的题，避免整片黄块。")
        if shown:
            st.markdown("**哪一题全班错得最多**")
            st.caption("红格=这人这题错了。竖着看：哪一列红点最多，课上就先订正哪题。")
            recs = []
            wrong_n = {c: 0 for c in shown}
            total_n = {c: 0 for c in shown}
            for row in grid:
                no = str(row.get("学号") or "")
                for c in shown:
                    v = row.get(c)
                    if v in {"对", "错"}:
                        recs.append({"学号": no, "题": c, "结果": v})
                        total_n[c] += 1
                        if v == "错":
                            wrong_n[c] += 1
            summary = [
                {"题": c, "错了几人": wrong_n[c], "已判定": total_n[c], "说明": "先讲这题" if total_n[c] and wrong_n[c] / total_n[c] >= 0.4 else ""}
                for c in shown
            ]
            summary.sort(key=lambda x: -x["错了几人"])
            st.dataframe(pd.DataFrame(summary), hide_index=True, use_container_width=True)
            try:
                import altair as alt

                df = pd.DataFrame(recs)
                if not df.empty:
                    chart = (
                        alt.Chart(df)
                        .mark_rect(stroke="white", strokeWidth=2, cornerRadius=3)
                        .encode(
                            x=alt.X("题:N", sort=shown, title="题"),
                            y=alt.Y("学号:N", title="学号"),
                            color=alt.Color(
                                "结果:N",
                                scale=alt.Scale(domain=["对", "错"], range=["#86efac", "#f87171"]),
                                legend=alt.Legend(title=""),
                            ),
                            tooltip=["学号", "题", "结果"],
                        )
                        .properties(height=min(420, 14 * df["学号"].nunique() + 48))
                    )
                    st.altair_chart(chart, use_container_width=True)
            except Exception:
                pass


def render_class_long_heat(heat: dict[str, Any]) -> None:
    render_class_long({"mastery_heat": heat})


def render_class_long(longp: dict[str, Any]) -> None:
    import pandas as pd
    import streamlit as st

    n = int(longp.get("n_commits") or 0)
    if n <= 0:
        st.info("还没有写入长期画像。队列清空后可点「写入长期画像」。")
        return
    if not longp.get("can_trend"):
        st.info("至少再批改并写入一次长期画像后，才能看趋势。下面是已写入的这一场掌握，不是走势。")

    trend = longp.get("kp_trend") or []
    show = set(longp.get("trend_kps") or [])
    rows = [t for t in trend if not show or t.get("knowledge_point") in show]
    if longp.get("can_trend") and rows:
        st.markdown("**知识点正确率走势（已写入长期的作业）**")
        st.caption("纵轴正确率。红虚线是必讲线 60%。默认只画曾经低于六成和最近最弱的点。")
        try:
            import altair as alt

            df = pd.DataFrame(
                {
                    "作业": [r["homework_name"] for r in rows],
                    "知识点": [r["knowledge_point"] for r in rows],
                    "正确率": [float(r["accuracy"]) * 100 for r in rows],
                }
            )
            line = (
                alt.Chart(df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("作业:N", sort=None, title="作业"),
                    y=alt.Y("正确率:Q", scale=alt.Scale(domain=[0, 100]), title="正确率 %"),
                    color=alt.Color("知识点:N"),
                    tooltip=["作业", "知识点", "正确率"],
                )
            )
            rule = alt.Chart(pd.DataFrame({"y": [60]})).mark_rule(color="#dc2626", strokeDash=[6, 4]).encode(y="y:Q")
            st.altair_chart(line + rule, use_container_width=True)
        except Exception:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    top3 = longp.get("term_weak_top3") or []
    st.markdown("**学期薄弱点（各次班级正确率平均，升序 Top 3）**")
    if top3:
        st.dataframe(
            [
                {
                    "知识点": x.get("knowledge_point"),
                    "学期平均正确率": f"{round(float(x.get('avg_accuracy') or 0)*100)}%",
                    "写入次数": x.get("n_hw"),
                }
                for x in top3
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("还没有可平均的知识点。")

    consec = longp.get("consecutive_weak") or []
    st.markdown("**连续薄弱**")
    st.caption("上一场该点已是弱、这一场仍是弱。标题只用学号，不是排名。")
    if consec:
        st.dataframe(
            [
                {
                    "学号": x.get("student_no") if isinstance(x, dict) else x,
                    "知识点": x.get("knowledge_point") if isinstance(x, dict) else "",
                    "连续弱次数": x.get("streak") if isinstance(x, dict) else "",
                    "最近作业": x.get("last_homework") if isinstance(x, dict) else "",
                }
                for x in consec
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.write("目前没有连续两场同点为弱的人。")

    heat = longp.get("mastery_heat") or {}
    if heat:
        st.markdown("**最近一次写入后的掌握一览**")
        zh = {"mastered": "会", "weak": "弱", "untested": "未测"}
        cols = sorted({kp for row in heat.values() for kp in row if not _dummy(kp)})
        if cols:
            table = []
            for no, kps in heat.items():
                row = {"学号": no}
                for c in cols:
                    row[c] = zh.get((kps or {}).get(c, "untested"), (kps or {}).get(c) or "未测")
                table.append(row)
            st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)


def render_student_long(longp: dict[str, Any]) -> None:
    import pandas as pd
    import streamlit as st

    n = int(longp.get("n_commits") or 0)
    if n <= 0:
        st.info("该生还没有长期掌握。班级写入长期画像后会出现。")
        return
    zh = {"mastered": "会", "weak": "弱", "untested": "未测"}
    trend = longp.get("score_trend") or []
    if longp.get("can_trend") and len(trend) >= 2:
        st.markdown("**本学期得分率**")
        try:
            import altair as alt

            df = pd.DataFrame({"作业": [t["homework_name"] for t in trend], "得分率": [float(t["rate"]) * 100 for t in trend]})
            chart = (
                alt.Chart(df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("作业:N", sort=None),
                    y=alt.Y("得分率:Q", scale=alt.Scale(domain=[0, 100])),
                    tooltip=["作业", "得分率"],
                )
            )
            st.altair_chart(chart, use_container_width=True)
        except Exception:
            st.dataframe(pd.DataFrame(trend), hide_index=True, use_container_width=True)
    else:
        st.info("长期不足 2 次写入，不画折线。下面是已有场次的掌握表。")

    grid = longp.get("mastery_grid") or []
    if grid:
        st.markdown("**各知识点随作业怎么变**")
        st.dataframe(
            [
                {
                    "作业": g.get("homework_name"),
                    "知识点": g.get("knowledge_point"),
                    "掌握": zh.get(g.get("mastery"), g.get("mastery")),
                }
                for g in grid
            ],
            hide_index=True,
            use_container_width=True,
        )
    consec = longp.get("consecutive") or []
    st.markdown("**连续弱**")
    if consec:
        st.dataframe(
            [{"知识点": c.get("knowledge_point"), "连续几次": c.get("streak"), "从哪次作业": c.get("since_homework")} for c in consec],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.write("该生没有连续两场同点为弱。")
    vs = longp.get("vs_class") or {}
    if vs:
        d = float(vs.get("delta") or 0)
        direction = "持平" if abs(d) < 0.005 else ("高于班级" if d > 0 else "低于班级")
        st.write(
            f"近 {vs.get('n')} 次已测：该生得分率 {round(float(vs['student_rate'])*100)}%，"
            f"班级 {round(float(vs['class_rate'])*100)}%，{direction} {abs(round(d*100))} 个百分点。"
        )



def render_student_vs_class(kp_vs: dict[str, Any]) -> None:
    import pandas as pd
    import streamlit as st

    rows = []
    for k, v in kp_vs.items():
        if _dummy(k):
            continue
        mine = v.get("student")
        cls = v.get("class")
        if mine is None and cls is None:
            continue
        d = None
        if mine is not None and cls is not None:
            d = round((mine - cls) * 100)
        rows.append(
            {
                "知识点": k,
                "该生": None if mine is None else f"{round(mine * 100)}%",
                "全班": None if cls is None else f"{round(cls * 100)}%",
                "和班上比": "—" if d is None else ("持平" if d == 0 else (f"高 {d} 个百分点" if d > 0 else f"低 {abs(d)} 个百分点")),
            }
        )
    if not rows:
        return
    st.markdown("**该生和全班差在哪**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
