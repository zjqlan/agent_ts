from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from zypg.config import settings

_PLACEHOLDER_HOSTS = {"example.com", "www.example.com", "example.org", "example.net"}


def file_root() -> Path:
    settings.ensure_dirs()
    return settings.data_dir / "files"


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(settings.data_dir.resolve()))
    except ValueError:
        return str(path)


def abspath(stored: str) -> Path:
    p = Path(stored)
    if p.is_absolute():
        return p
    return (settings.data_dir / p).resolve()


def homework_dir(homework_id: str, kind: str) -> Path:
    d = file_root() / kind / homework_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_placeholder_url(url: str | None) -> bool:
    if not url or not str(url).startswith("http"):
        return True
    host = (urlparse(url).hostname or "").lower()
    return host in _PLACEHOLDER_HOSTS or host.endswith(".example.com")


def paper_docx_url(homework_id: str) -> str:
    host = settings.zypg_host
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.zypg_port}/ui/paper.docx?homework_id={homework_id}"


def assignment_rel_file(hw: dict, suffix: str) -> str | None:
    extra = hw.get("extra") or {}
    layout = extra.get("layout") if isinstance(extra, dict) else {}
    layout = layout or {}
    suffix = suffix.lower()
    for cand in (layout.get("docx_path"), layout.get("md_path"), layout.get("paper_path"), hw.get("paper_path")):
        if cand and str(cand).lower().endswith(suffix):
            path = abspath(str(cand))
            if path.is_file():
                return str(cand)
    return None
