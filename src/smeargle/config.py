"""Pydantic Settings with CLI > env > file > defaults precedence (spec 6)."""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseModel):
    base_url: str = ""
    model: Optional[str] = None
    auth_file: Optional[Path] = None
    api_key_env: Optional[str] = None
    timeout: float = 60.0
    retries: int = 3
    temperature: float = 0.0
    structured_output: bool = True


class JevSettings(BaseModel):
    base_url: str = ""
    model: Optional[str] = None
    auth_file: Optional[Path] = None
    api_key_env: Optional[str] = None
    timeout: float = 60.0
    retries: int = 3
    batch: bool = False
    batch_size: int = Field(default=64, ge=1, le=64)
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_len: int = Field(default=4096, ge=1)
    head_max_len: int = Field(default=512, ge=1)


class MappingSettings(BaseModel):
    extract_gate_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    mapped_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    category_high: float = Field(default=0.80, ge=0.0, le=1.0)
    category_medium: float = Field(default=0.50, ge=0.0, le=1.0)
    nomination_cap: int = Field(default=0, ge=0)


class ExecutionSettings(BaseModel):
    log_format: Literal["text", "json"] = "text"
    chunk_size: int = Field(default=2000, ge=1)
    chunk_overlap: int = Field(default=200, ge=0)
    control_chunk_chars: int = Field(default=16000, ge=1)
    run_id: Optional[str] = None
    force: bool = False
    yes: bool = False
    verbose: bool = False
    catalog_format: Literal["auto", "oscal"] = "auto"
    gaps_fatal: bool = False
    concurrency: int = Field(default=4, ge=1)


_CONFIG_FILE: ContextVar[Optional[Path]] = ContextVar("smeargle_config_file", default=None)


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SMEARGLE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    inputs: list[str] = Field(default_factory=list)
    catalogs: list[str] = Field(default_factory=list)
    output: Optional[Path] = None
    state_dir: Path = Path(".smeargle")
    llm: LlmSettings = Field(default_factory=LlmSettings)
    jev: JevSettings = Field(default_factory=JevSettings)
    mapping: MappingSettings = Field(default_factory=MappingSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        from pydantic_settings import TomlConfigSettingsSource, YamlConfigSettingsSource

        sources: list[Any] = [init_settings, env_settings]
        path = _CONFIG_FILE.get()
        if path is not None:
            suffix = path.suffix.lower()
            if suffix in {".toml", ""}:
                sources.append(TomlConfigSettingsSource(settings_cls, toml_file=path))
            elif suffix in {".yaml", ".yml"}:
                sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=path))
            else:
                raise ValueError(f"unsupported config file extension: {path.suffix}")
        sources.append(file_secret_settings)
        return tuple(sources)

    @classmethod
    def load(
        cls,
        config_file: Optional[Path] = None,
        overrides: Optional[Mapping[str, Any]] = None,
    ) -> "Settings":
        token = _CONFIG_FILE.set(Path(config_file) if config_file is not None else None)
        try:
            base = cls()
        finally:
            _CONFIG_FILE.reset(token)
        if not overrides:
            return base
        merged = _deep_merge(base.model_dump(), overrides)
        return cls.model_validate(merged)
