"""Configuration loader for DevsContext."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class JiraConfig(BaseModel):
    """Jira adapter configuration."""

    base_url: str = ""
    email: str = ""
    api_token: str = ""
    enabled: bool = False


class FirefliesConfig(BaseModel):
    """Fireflies adapter configuration."""

    api_key: str = ""
    enabled: bool = False


class LocalDocsConfig(BaseModel):
    """Local docs adapter configuration."""

    paths: list[str] = []
    enabled: bool = True


class AdaptersConfig(BaseModel):
    """Configuration for all adapters."""

    jira: JiraConfig = JiraConfig()
    fireflies: FirefliesConfig = FirefliesConfig()
    local_docs: LocalDocsConfig = LocalDocsConfig()


class CacheConfig(BaseModel):
    """Cache configuration."""

    ttl_seconds: int = 300
    max_size: int = 100


class Config(BaseModel):
    """Root configuration for DevsContext."""

    adapters: AdaptersConfig = AdaptersConfig()
    cache: CacheConfig = CacheConfig()


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, searches for .devscontext.yaml
                    in current directory and parent directories.

    Returns:
        Loaded configuration.
    """
    if config_path is None:
        config_path = find_config_file()

    if config_path is None or not config_path.exists():
        return Config()

    with open(config_path) as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return Config.model_validate(data)


def find_config_file() -> Path | None:
    """Search for .devscontext.yaml in current and parent directories."""
    current = Path.cwd()

    for directory in [current, *current.parents]:
        config_file = directory / ".devscontext.yaml"
        if config_file.exists():
            return config_file

    return None
