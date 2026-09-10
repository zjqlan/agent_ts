from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from typing import Any, BinaryIO


def default_npx_command(package: str) -> list[str]:
    local = _local_package_entry(package)
    if local:
        return local
    npx = shutil.which("npx.cmd") if sys.platform == "win32" else shutil.which("npx")
    if not npx and sys.platform == "win32":
        npx = shutil.which("npx")
    if not npx:
        raise RuntimeError(
            "未找到 npx。作业排版要对接待 mcpworld 上的 edupaper-mcp"
            "（npx -y edupaper-mcp），请先安装 Node.js。"
        )
    if sys.platform == "win32":
        return ["cmd.exe", "/d", "/s", "/c", npx, "-y", "--no-update-notifier", package]
    return [npx, "-y", "--no-update-notifier", package]


def _local_package_entry(package: str) -> list[str] | None:
    node = shutil.which("node")
    if not node:
        return None
    from zypg.config import ROOT

    candidates = [
        ROOT / "tools" / "edupaper-mcp" / "node_modules" / package / "dist" / "index.js",
        ROOT / "node_modules" / package / "dist" / "index.js",
    ]
    for entry in candidates:
        if entry.is_file():
            return [node, str(entry)]
    return None


def call_mcp_stdio(
    command: list[str],
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float = 120.0,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("NPM_CONFIG_UPDATE_NOTIFIER", "false")
    env.setdefault("npm_config_loglevel", "error")
    env.setdefault("NPM_CONFIG_LOGLEVEL", "error")
    env.setdefault("npm_config_yes", "true")
    popen_kw: dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
        "bufsize": 0,
    }
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(command, **popen_kw)
    err_chunks: list[bytes] = []
    messages: queue.Queue[Any] = queue.Queue()

    def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        while True:
            chunk = proc.stderr.read(4096)
            if not chunk:
                break
            err_chunks.append(chunk)

    def _read_loop() -> None:
        try:
            if proc.stdout is None:
                messages.put(RuntimeError("无法打开 MCP stdout"))
                return
            while True:
                messages.put(_read_message(proc.stdout))
        except Exception as exc:
            messages.put(exc)

    threading.Thread(target=_drain_stderr, daemon=True).start()
    threading.Thread(target=_read_loop, daemon=True).start()
    try:
        if proc.stdin is None:
            raise RuntimeError("无法打开 MCP 进程管道")
        _write_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "zypg", "version": "0.1.0"},
                },
            },
        )
        init = _wait_id(messages, 1, timeout=timeout)
        if "error" in init:
            raise RuntimeError(f"edupaper-mcp initialize 失败: {init['error']}")
        _write_message(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _write_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        called = _wait_id(messages, 2, timeout=timeout)
        if "error" in called:
            raise RuntimeError(f"edupaper-mcp tools/call 失败: {called['error']}")
        result = called.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"edupaper-mcp 返回异常: {called}")
        if result.get("isError"):
            raise RuntimeError(_content_text(result) or "edupaper-mcp 返回 isError")
        return result
    except Exception:
        stderr = b"".join(err_chunks).decode("utf-8", errors="replace").strip()
        if stderr:
            raise RuntimeError(f"{sys.exc_info()[1]}\n--- edupaper-mcp stderr ---\n{stderr}") from None
        raise
    finally:
        _stop(proc)


def _wait_id(messages: queue.Queue[Any], want_id: int, timeout: float) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"等待 edupaper-mcp 响应超时（{timeout:.0f}s，id={want_id}）")
        try:
            item = messages.get(timeout=remaining)
        except queue.Empty:
            raise RuntimeError(f"等待 edupaper-mcp 响应超时（{timeout:.0f}s，id={want_id}）") from None
        if isinstance(item, Exception):
            raise item
        if item.get("id") == want_id:
            return item


def _content_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts).strip()


def _write_message(stdin: BinaryIO, obj: dict[str, Any]) -> None:
    # MCP TypeScript SDK >=1.x stdio is newline-delimited JSON, not Content-Length.
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
    stdin.write(body)
    stdin.flush()


def _read_message(stdout: BinaryIO) -> dict[str, Any]:
    while True:
        line = stdout.readline()
        if not line:
            raise RuntimeError("edupaper-mcp stdout 已关闭")
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if low.startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
            while True:
                header = stdout.readline()
                if header in (b"\r\n", b"\n", b""):
                    break
            body = _read_exact(stdout, length)
            return json.loads(body.decode("utf-8"))
        try:
            return json.loads(stripped.decode("utf-8"))
        except json.JSONDecodeError:
            continue


def _read_exact(stream: BinaryIO, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise RuntimeError("edupaper-mcp 报文不完整")
        buf += chunk
    return buf


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
