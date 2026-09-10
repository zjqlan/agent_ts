from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from zypg.mcp_tools.edupaper import (
    extract_download_url,
    generate_exam_paper,
    normalize_exam_questions,
)
from zypg.mcp_tools.mcp_stdio import call_mcp_stdio
from zypg.storage.files import abspath


def test_extract_download_url():
    text = (
        'Successfully generated exam paper: "数列练习"\n\n'
        "Download Link: https://tmpfile.link/dl/abc.docx\n"
        "File Size: 12 bytes"
    )
    assert extract_download_url(text) == "https://tmpfile.link/dl/abc.docx"


def test_normalize_exam_questions_maps_aliases():
    qs = normalize_exam_questions(
        [{"type": "choice", "content": "1+1", "options": ["2", "3"], "answer": "A", "score": 5}]
    )
    assert qs[0]["type"] == "single_choice"
    assert qs[0]["points"] == 5.0


def test_generate_exam_paper_uses_mock_in_pytest():
    out = asyncio.run(
        generate_exam_paper(
            {
                "title": "mock卷",
                "questions": [
                    {
                        "type": "single_choice",
                        "content": "1+1=?",
                        "options": ["2", "3", "4", "5"],
                        "answer": "A",
                        "points": 5,
                    }
                ],
            }
        )
    )
    assert out["mock"] is True
    assert Path(abspath(out["docx_path"])).exists()
    assert Path(abspath(out["md_path"])).exists()


def test_stdio_mcp_client_against_fake_server(monkeypatch):
    fake = Path(__file__).resolve().parent / "fake_edupaper_mcp.py"
    result = call_mcp_stdio(
        [sys.executable, str(fake)],
        "generate_exam_paper",
        {"title": "数列练习", "questions": []},
        timeout=15,
    )
    text = result["content"][0]["text"]
    assert "Download Link: https://tmpfile.link/dl/fake-paper.docx" in text

    monkeypatch.setattr(
        "zypg.mcp_tools.edupaper._download_docx",
        lambda url, dest: dest.write_bytes(b"PK" + b"\x00" * 64),
    )
    monkeypatch.setattr("zypg.mcp_tools.edupaper.use_edupaper_mock", lambda: False)
    monkeypatch.setattr(
        "zypg.mcp_tools.edupaper._edupaper_command",
        lambda: [sys.executable, str(fake)],
    )
    old = os.environ.get("EDUPAPER_MCP_MOCK")
    os.environ["EDUPAPER_MCP_MOCK"] = "0"
    try:
        out = asyncio.run(
            generate_exam_paper(
                {
                    "title": "stdio卷",
                    "questions": [{"type": "short_answer", "content": "求和", "answer": "100", "points": 10}],
                }
            )
        )
    finally:
        if old is None:
            os.environ.pop("EDUPAPER_MCP_MOCK", None)
        else:
            os.environ["EDUPAPER_MCP_MOCK"] = old
    assert out["mock"] is False
    assert out["remote_url"] == "https://tmpfile.link/dl/fake-paper.docx"
    assert Path(abspath(out["docx_path"])).exists()


def test_placeholder_url_detected():
    from zypg.storage.files import is_placeholder_url, paper_docx_url

    assert is_placeholder_url("https://example.com/assign_abc.docx")
    assert not is_placeholder_url("https://tmpfile.link/dl/abc.docx")
    assert "/ui/paper.docx?homework_id=abc" in paper_docx_url("abc")


def test_mcp_failure_falls_back_to_local(monkeypatch):
    monkeypatch.setattr("zypg.mcp_tools.edupaper.use_edupaper_mock", lambda: False)
    monkeypatch.setattr(
        "zypg.mcp_tools.edupaper.call_mcp_stdio",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tmpfile 404")),
    )
    old = os.environ.get("EDUPAPER_MCP_MOCK")
    os.environ["EDUPAPER_MCP_MOCK"] = "0"
    try:
        out = asyncio.run(
            generate_exam_paper(
                {
                    "title": "fallback卷",
                    "questions": [{"type": "short_answer", "content": "求和", "answer": "100", "points": 10}],
                }
            )
        )
    finally:
        if old is None:
            os.environ.pop("EDUPAPER_MCP_MOCK", None)
        else:
            os.environ["EDUPAPER_MCP_MOCK"] = old
    assert out["mock"] is True
    assert out.get("mcp_fallback") is True
    assert Path(abspath(out["docx_path"])).exists()
