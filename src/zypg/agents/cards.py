from __future__ import annotations

from pathlib import Path
from typing import Any

from zypg.agents.base import PeerAgent
from zypg.models import A2AMessage
from zypg.protocol.mcp import call_internal
from zypg.roster.service import require_roster
from zypg.storage import mysql
from zypg.storage.files import abspath, homework_dir, relpath
from zypg.mcp_tools.omr import decode_homework


def _blank_of(tmpl: dict[str, Any]) -> Path:
    geom = tmpl.get("geometry") or {}
    bp = geom.get("blank_path")
    if not bp:
        raise ValueError("答题卡模板缺少空白对照图")
    return abspath(bp)


def _template_matching_scan(scan_path: str, homework_id: str) -> tuple[str, dict[str, Any]]:
    tmpl = mysql.get_card_template(homework_id)
    if tmpl and decode_homework(scan_path, tmpl.get("geometry") or {}):
        return homework_id, tmpl
    hw = mysql.get_assignment(homework_id)
    cid = hw.get("class_id") if hw else None
    if cid:
        for row in mysql.list_homeworks(cid):
            hid = row["homework_id"]
            other = mysql.get_card_template(hid)
            if not other:
                continue
            try:
                if decode_homework(scan_path, other.get("geometry") or {}):
                    return hid, other
            except Exception:
                continue
    if not tmpl:
        raise ValueError("尚无答题卡模板，请先出卡")
    return homework_id, tmpl


class CardsAgent(PeerAgent):
    name = "cards"
    description = "答题卡渲染与扫描批改"

    def skills(self) -> list[str]:
        return ["generate_cards", "fill_demo_scans", "grade_scans", "review_queue"]

    async def handle(self, message: A2AMessage) -> dict[str, Any]:
        p = message.payload
        if message.skill == "generate_cards":
            require_roster(p.get("class_id"))
            return await self._generate_cards(p)
        if message.skill == "fill_demo_scans":
            require_roster(p.get("class_id"))
            return await self._fill_demo_scans(p)
        if message.skill == "grade_scans":
            require_roster(_class_of(p["homework_id"]))
            return await self._grade(p)
        if message.skill == "review_queue":
            return await self._review(p)
        raise ValueError(f"unknown skill {message.skill}")

    async def _generate_cards(self, p: dict[str, Any]) -> dict[str, Any]:
        homework_id = p["homework_id"]
        class_id = p["class_id"]
        students = mysql.list_class_students(class_id)
        if not students:
            raise ValueError("请先导入班级名单")
        items = mysql.list_items(homework_id)
        if not items:
            raise ValueError("这份作业没有题目，无法出卡。请先出题或导入试卷。")
        rendered = await call_internal(
            "render_cards",
            {"homework_id": homework_id, "items": items, "students": students},
        )
        mysql.upsert_card_template(homework_id, rendered["geometry"], rendered["print_path"])
        return rendered

    async def _fill_demo_scans(self, p: dict[str, Any]) -> dict[str, Any]:
        homework_id = p["homework_id"]
        class_id = p["class_id"]
        tmpl = mysql.get_card_template(homework_id)
        if not tmpl:
            raise ValueError("尚无空白答题卡，请先出卡")
        students = mysql.list_class_students(class_id)
        if not students:
            raise ValueError("请先导入班级名单")
        items = mysql.list_items(homework_id)
        if not items:
            raise ValueError("这份作业没有题目，无法生成作答扫描件。")
        scripts = await call_internal(
            "simulate_student_answers",
            {"students": students, "items": items},
        )
        filled = await call_internal(
            "fill_student_marks",
            {
                "homework_id": homework_id,
                "geometry": tmpl["geometry"],
                "students": students,
                "items": items,
                "scripts": scripts,
            },
        )
        from zypg.config import settings

        filled["class_id"] = class_id
        filled["llm_model"] = settings.llm_model
        filled["source"] = "llm_student_answers"
        return filled

    async def _grade(self, p: dict[str, Any]) -> dict[str, Any]:
        homework_id = p["homework_id"]
        scan_paths = p.get("scan_paths") or []
        if not scan_paths:
            raise ValueError("请在对话中附上扫描 PNG，或先生成写好的答题卡再说「批改」。")
        first = abspath(scan_paths[0]) if not Path(scan_paths[0]).is_absolute() else Path(scan_paths[0])
        homework_id, tmpl = _template_matching_scan(str(first), homework_id)
        geometry = tmpl["geometry"]
        blank = _blank_of(tmpl)
        items = {it["item_id"]: it for it in mysql.list_items(homework_id)}
        progress_cb = p.get("progress_cb")
        results: list[dict[str, Any]] = []
        reviews: list[dict[str, Any]] = []
        scans: list[dict[str, Any]] = []
        total = max(len(scan_paths), 1)
        for i, sp in enumerate(scan_paths):
            if progress_cb:
                await progress_cb(
                    {
                        "done": i,
                        "total": total,
                        "skill": "grade_scans",
                        "student_id": None,
                        "message": f"正在批改第 {i + 1}/{total} 张",
                    }
                )
            path = abspath(sp) if not Path(sp).is_absolute() else Path(sp)
            one = await _grade_one(
                homework_id,
                str(path),
                geometry,
                blank,
                items,
                progress_cb=progress_cb,
                sheet_i=i,
                total=total,
            )
            scans.append(one["scan"])
            results.extend(one["results"])
            reviews.extend(one["reviews"])
            if progress_cb:
                await progress_cb(
                    {
                        "done": i + 1,
                        "total": total,
                        "student_id": one["scan"].get("student_id"),
                    }
                )
        mysql.commit_grade_batch(scans, results, reviews)
        return {
            "homework_id": homework_id,
            "scanned": len(scans),
            "results": len(results),
            "queued": len(reviews),
        }

    async def _review(self, p: dict[str, Any]) -> dict[str, Any]:
        action = p.get("action") or p.get("review_action") or "list"
        if action == "accept_all":
            items = mysql.list_open_reviews(p.get("homework_id"), p.get("class_id"))
            done = []
            for row in items:
                done.append(
                    await self._review(
                        {"action": "accepted", "review_id": row["id"], "class_id": p.get("class_id")}
                    )
                )
            return {"accepted": len(done), "status": "accepted", "items": []}
        if action == "list":
            return {"items": mysql.list_open_reviews(p.get("homework_id"), p.get("class_id"))}
        rid = int(p["review_id"])
        row = mysql.get_review(rid)
        if not row:
            raise ValueError("确认项不存在")
        if row["status"] != "open":
            return {"ok": True, "review": row}
        if action == "accepted":
            score = row.get("suggested_score")
            mysql.update_review(rid, "accepted")
            if row.get("student_id") and row.get("item_id"):
                item = next(
                    (x for x in mysql.list_items(row["homework_id"]) if x["item_id"] == row["item_id"]),
                    None,
                )
                max_s = float(item["score"] or 0) if item else None
                is_correct = None
                if score is not None and max_s is not None and max_s > 0:
                    is_correct = 1 if float(score) >= 0.6 * max_s else 0
                mysql.replace_item_result(
                    {
                        "homework_id": row["homework_id"],
                        "student_id": row["student_id"],
                        "item_id": row["item_id"],
                        "raw": {"review_id": rid, "action": "accepted"},
                        "score": score,
                        "is_correct": is_correct,
                        "source": "teacher",
                        "pending": 0,
                    }
                )
            return {"ok": True, "status": "accepted"}
        if action == "overridden":
            score = p.get("score")
            mysql.update_review(rid, "overridden")
            if row.get("student_id") and row.get("item_id"):
                item = next(
                    (x for x in mysql.list_items(row["homework_id"]) if x["item_id"] == row["item_id"]),
                    None,
                )
                max_s = float(item["score"] or 0) if item else None
                is_correct = None
                if score is not None and max_s is not None and max_s > 0:
                    is_correct = 1 if float(score) >= 0.6 * max_s else 0
                mysql.replace_item_result(
                    {
                        "homework_id": row["homework_id"],
                        "student_id": row["student_id"],
                        "item_id": row["item_id"],
                        "raw": {"review_id": rid, "action": "overridden"},
                        "score": score,
                        "is_correct": is_correct,
                        "source": "teacher",
                        "pending": 0,
                    }
                )
            return {"ok": True, "status": "overridden"}
        if action == "void":
            mysql.update_review(rid, "overridden")
            return {"ok": True, "status": "void"}
        if action == "bind":
            sid = p.get("student_id")
            if not sid:
                raise ValueError("请选择要绑定的学生")
            mysql.execute("UPDATE review_queue SET student_id = :sid WHERE id = :id", sid=sid, id=rid)
            row = mysql.get_review(rid)
            return {"ok": True, "status": "bound", "review": row}
        raise ValueError("action 必须是 list/accepted/overridden/bind/void/accept_all")


def _store_path(scan_path: str) -> str:
    p = Path(scan_path)
    if p.exists():
        return relpath(p)
    return scan_path


def _class_of(homework_id: str) -> str | None:
    hw = mysql.get_assignment(homework_id)
    return hw["class_id"] if hw else None


async def _grade_one(
    homework_id: str,
    scan_path: str,
    geometry: dict[str, Any],
    blank: Path,
    items: dict[str, Any],
    progress_cb=None,
    sheet_i: int = 0,
    total: int = 1,
) -> dict[str, Any]:
    matched = await call_internal("omr_match_homework", {"scan_path": scan_path, "geometry": geometry})
    student_no = await call_internal(
        "omr_student_no",
        {"scan_path": scan_path, "geometry": geometry, "blank_path": str(blank)},
    )
    student_no = student_no.get("student_no") if isinstance(student_no, dict) else student_no
    student = mysql.student_by_no(student_no) if student_no else None
    in_class = False
    if student:
        hw = mysql.get_assignment(homework_id)
        enrolled = {s["student_id"] for s in mysql.list_class_students(hw["class_id"])} if hw else set()
        in_class = student["student_id"] in enrolled
    if not matched.get("ok"):
        if student and in_class:
            # 线下填好的卡可能不是本作业条码（老师自行生成后导入），学号能认就按当前作业几何批。
            matched = {"ok": True}
        else:
            return {
                "scan": {
                    "homework_id": homework_id,
                    "student_id": None,
                    "file_path": _store_path(scan_path),
                    "status": "unmatched",
                },
                "results": [],
                "reviews": [
                    {
                        "homework_id": homework_id,
                        "student_id": None,
                        "item_id": None,
                        "reason": "bad_template",
                        "suggested_score": None,
                    }
                ],
            }
    if not student or not in_class:
        return {
            "scan": {
                "homework_id": homework_id,
                "student_id": None,
                "file_path": _store_path(scan_path),
                "status": "bad_id",
            },
            "results": [],
            "reviews": [
                {
                    "homework_id": homework_id,
                    "student_id": None,
                    "item_id": None,
                    "reason": "bad_id",
                    "suggested_score": None,
                }
            ],
        }
    sid = student["student_id"]
    n_pages = int(geometry.get("n_pages") or 1)
    page = 0
    grade_blank = blank
    if n_pages > 1:
        from zypg.mcp_tools.omr import decode_page

        page = decode_page(scan_path, geometry)
        blanks = geometry.get("blank_paths") or [str(blank)]
        if page < len(blanks):
            bp = blanks[page]
            grade_blank = abspath(bp) if not Path(bp).is_absolute() else Path(bp)
    from zypg.mcp_tools.card_render import _item_page

    bubbles = await call_internal(
        "omr_read",
        {"scan_path": scan_path, "blank_path": str(grade_blank), "geometry": geometry},
    )
    results: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for item_id, it in items.items():
        if it["kind"] != "objective":
            continue
        if n_pages > 1 and _item_page(geometry, item_id) != page:
            continue
        mark = bubbles.get(item_id, "empty")
        key = (it.get("answer_key") or {}).get("letter")
        if mark in {"empty", "double"}:
            reviews.append(
                {
                    "homework_id": homework_id,
                    "student_id": sid,
                    "item_id": item_id,
                    "reason": "double_mark" if mark == "double" else "blank",
                    "suggested_score": 0,
                }
            )
            results.append(
                {
                    "homework_id": homework_id,
                    "student_id": sid,
                    "item_id": item_id,
                    "raw": {"mark": mark},
                    "score": None,
                    "is_correct": None,
                    "source": "omr",
                    "pending": 1,
                }
            )
            continue
        correct = key is not None and mark == key
        max_s = float(it.get("score") or 0)
        results.append(
            {
                "homework_id": homework_id,
                "student_id": sid,
                "item_id": item_id,
                "raw": {"mark": mark, "key": key},
                "score": max_s if correct else 0,
                "is_correct": 1 if correct else 0,
                "source": "omr",
                "pending": 0,
            }
        )
    crop_dir = homework_dir(homework_id, "crops")
    subj = [
        (item_id, it)
        for item_id, it in items.items()
        if it["kind"] == "subjective"
        and not (n_pages > 1 and _item_page(geometry, item_id) != page)
    ]
    n_subj = len(subj)
    for k, (item_id, it) in enumerate(subj):
        if progress_cb:
            await progress_cb(
                {
                    "done": sheet_i,
                    "total": total,
                    "skill": "grade_scans",
                    "message": f"第 {sheet_i + 1}/{total} 张 · 识别主观题 {k + 1}/{n_subj}",
                }
            )
        dest = crop_dir / f"{sid}_{item_id}.png"
        await call_internal(
            "omr_crop",
            {
                "scan_path": scan_path,
                "geometry": geometry,
                "item_id": item_id,
                "dest": str(dest),
            },
        )
        import asyncio

        from zypg.mcp_tools.ocr import ocr_image

        ocr = await asyncio.to_thread(ocr_image, str(dest))
        text = ocr.get("text") or ""
        garbled = bool(ocr.get("garbled"))
        if progress_cb:
            await progress_cb(
                {
                    "done": sheet_i,
                    "total": total,
                    "skill": "grade_scans",
                    "message": f"第 {sheet_i + 1}/{total} 张 · 评分主观题 {k + 1}/{n_subj}",
                }
            )
        score_info = await call_internal(
            "score_subjective",
            {
                "stem": it.get("stem"),
                "rubric": it.get("rubric"),
                "answer": (it.get("answer_key") or {}).get("text"),
                "ocr_text": text,
                "max_score": it.get("score"),
                "student_id": sid,
            },
        )
        reason = "ocr_garbled" if garbled else score_info.get("reason") or "needs_confirm"
        suggested = score_info.get("suggested_score")
        results.append(
            {
                "homework_id": homework_id,
                "student_id": sid,
                "item_id": item_id,
                "raw": {"ocr": text, "llm": score_info, "garbled": garbled},
                "score": suggested,
                "is_correct": None,
                "source": "ocr_llm",
                "pending": 1,
            }
        )
        reviews.append(
            {
                "homework_id": homework_id,
                "student_id": sid,
                "item_id": item_id,
                "reason": reason,
                "suggested_score": suggested,
            }
        )
    return {
        "scan": {
            "homework_id": homework_id,
            "student_id": sid,
            "file_path": _store_path(scan_path),
            "status": "graded",
        },
        "results": results,
        "reviews": reviews,
    }
