#!/usr/bin/env python3
"""Minimal MCP stdio server for tests. Speaks newline-delimited JSON-RPC (MCP SDK 1.x)."""
from __future__ import annotations

import json
import sys


def _read() -> dict:
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(0)
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
            while True:
                header = sys.stdin.buffer.readline()
                if header in (b"\r\n", b"\n", b""):
                    break
            body = sys.stdin.buffer.read(length)
            return json.loads(body.decode("utf-8"))
        return json.loads(stripped.decode("utf-8"))


def _write(obj: dict) -> None:
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main() -> None:
    while True:
        msg = _read()
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-edupaper", "version": "0"},
                    },
                }
            )
            continue
        if method == "notifications/initialized":
            continue
        if method == "tools/call":
            params = msg.get("params") or {}
            args = params.get("arguments") or {}
            title = args.get("title") or "试卷"
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f'Successfully generated exam paper: "{title}"\n\n'
                                    "Download Link: https://tmpfile.link/dl/fake-paper.docx\n"
                                    "File Size: 1234 bytes\n\n"
                                    "(Note: This link is valid for 7 days)"
                                ),
                            }
                        ]
                    },
                }
            )
            continue
        if req_id is not None:
            _write({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": method}})


if __name__ == "__main__":
    main()
