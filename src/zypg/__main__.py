from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="zypg", description="作业批改多智能体")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "ui", "mcp"])
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    from zypg.config import settings

    host = args.host or settings.zypg_host
    port = args.port or settings.zypg_port

    if args.command == "ui":
        import subprocess
        import sys

        ui = os.path.join(os.path.dirname(__file__), "ui", "app.py")
        os.environ.setdefault("ZYPG_API", f"http://{host}:{port}")
        os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
        raise SystemExit(
            subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    ui,
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    "8501",
                    "--server.headless",
                    "true",
                    "--server.fileWatcherType",
                    "poll",
                    "--browser.gatherUsageStats",
                    "false",
                ]
            )
        )

    if args.command == "mcp":
        from zypg.protocol.mcp import stdio_loop

        stdio_loop()
        return

    import uvicorn

    uvicorn.run(
        "zypg.gateway.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
