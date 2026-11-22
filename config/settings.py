"""Central configuration for StudyPack AI.

All tunables come from environment variables (optionally loaded from a `.env`
file in the project root). Nothing provider- or model-specific is hardcoded
elsewhere in the code base: modules ask `get_settings()` instead.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SUPPORTED_PROVIDERS = ("ollama", "gemini")


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() != "" else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


@dataclass(frozen=True)
class Settings:
    # Provider selection
    default_provider: str = "ollama"
    fallback_provider: str = "ollama"

    # Ollama (local)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:4b-q4_K_M"
    ollama_think: bool = False
    ollama_timeout_s: int = 600
    ollama_keep_alive: str = "10m"

    # Gemini (cloud, optional)
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_s: int = 120

    # Generation
    max_concurrent_requests: int = 1
    context_length: int = 8192
    max_output_tokens: int = 3072
    temperature: float = 0.3
    max_validation_retries: int = 2

    # Ingestion
    max_upload_mb: int = 50
    ocr_enabled: bool = True
    tesseract_cmd: str = ""
    chunk_target_chars: int = 1400

    # Paths
    data_dir: Path = PROJECT_ROOT / "data"
    generated_dir: Path = PROJECT_ROOT / "generated"
    logs_dir: Path = PROJECT_ROOT / "logs"
    db_path: Path = PROJECT_ROOT / "data" / "studypack.db"
    log_level: str = "INFO"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.uploads_dir, self.generated_dir, self.logs_dir, self.db_path.parent):
            path.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        """Return human-readable configuration problems (empty list = OK)."""
        problems = []
        for label, value in (("DEFAULT_PROVIDER", self.default_provider), ("FALLBACK_PROVIDER", self.fallback_provider)):
            if value not in SUPPORTED_PROVIDERS:
                problems.append(f"{label}={value!r} is not one of {SUPPORTED_PROVIDERS}")
        if not self.ollama_model:
            problems.append("OLLAMA_MODEL is empty")
        if self.context_length < 2048:
            problems.append("DEFAULT_CONTEXT_LENGTH should be at least 2048")
        if self.max_output_tokens >= self.context_length:
            problems.append("MAX_OUTPUT_TOKENS must be smaller than DEFAULT_CONTEXT_LENGTH")
        if self.default_provider == "gemini" and not self.gemini_configured:
            problems.append("DEFAULT_PROVIDER is gemini but GEMINI_API_KEY is not set; the fallback provider will be used")
        return problems


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    return Settings(
        default_provider=_env_str("DEFAULT_PROVIDER", "ollama").lower(),
        fallback_provider=_env_str("FALLBACK_PROVIDER", "ollama").lower(),
        ollama_base_url=_env_str("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_env_str("OLLAMA_MODEL", "qwen3.5:4b-q4_K_M"),
        ollama_think=_env_bool("OLLAMA_THINK", False),
        ollama_timeout_s=_env_int("OLLAMA_TIMEOUT_S", 600),
        ollama_keep_alive=_env_str("OLLAMA_KEEP_ALIVE", "10m"),
        gemini_api_key=_env_str("GEMINI_API_KEY", ""),
        gemini_model=_env_str("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_timeout_s=_env_int("GEMINI_TIMEOUT_S", 120),
        max_concurrent_requests=max(1, _env_int("MAX_CONCURRENT_REQUESTS", 1)),
        context_length=_env_int("DEFAULT_CONTEXT_LENGTH", 8192),
        max_output_tokens=_env_int("MAX_OUTPUT_TOKENS", 3072),
        temperature=_env_float("TEMPERATURE", 0.3),
        max_validation_retries=_env_int("MAX_VALIDATION_RETRIES", 2),
        max_upload_mb=_env_int("MAX_UPLOAD_MB", 50),
        ocr_enabled=_env_bool("OCR_ENABLED", True),
        tesseract_cmd=_env_str("TESSERACT_CMD", ""),
        chunk_target_chars=_env_int("CHUNK_TARGET_CHARS", 1400),
        data_dir=_resolve_path(_env_str("DATA_DIR", "data")),
        generated_dir=_resolve_path(_env_str("GENERATED_DIR", "generated")),
        logs_dir=_resolve_path(_env_str("LOGS_DIR", "logs")),
        db_path=_resolve_path(_env_str("DB_PATH", "data/studypack.db")),
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = load_settings()
    settings.ensure_dirs()
    return settings
