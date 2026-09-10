from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "zypg"
    mysql_password: str = "zypg"
    mysql_database: str = "zypg"
    redis_url: str = "redis://127.0.0.1:6379/0"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    zypg_host: str = "127.0.0.1"
    zypg_port: int = 8765
    edupaper_mcp_url: str = ""
    edupaper_mcp_cmd: str = ""
    edupaper_mcp_args: str = "-y,--no-update-notifier,edupaper-mcp"
    edupaper_mcp_mock: bool = False
    edupaper_mcp_timeout: int = 120
    ocr_url: str = ""
    mineru_token: str = ""
    ocr_token: str = ""
    data_dir: Path = ROOT / "data"
    teacher_username: str = "teacher"
    teacher_password: str = "teacher123"
    teacher_display_name: str = "教师"

    @property
    def mysql_dsn(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )

    @property
    def public_base(self) -> str:
        return f"http://{self.zypg_host}:{self.zypg_port}"

    @property
    def mineru_key(self) -> str:
        return self.mineru_token or self.ocr_token

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.data_dir / "files",
            self.data_dir / "indexes",
            self.data_dir / "files" / "cards",
            self.data_dir / "files" / "papers",
            self.data_dir / "files" / "scans",
            self.data_dir / "files" / "charts",
            self.data_dir / "files" / "crops",
            self.data_dir / "files" / "rosters",
            self.data_dir / "files" / "lessons",
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
