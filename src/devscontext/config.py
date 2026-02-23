"""Configuration loader for DevsContext."""

import os
import re
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


# Pattern to match ${VAR_NAME} or $VAR_NAME
ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values.

    Supports both ${VAR_NAME} and $VAR_NAME syntax.
    If the env var is not set, the placeholder is left unchanged.

    Args:
        value: The value to expand (can be str, dict, list, or primitive).

    Returns:
        The value with environment variables expanded.
    """
    if isinstance(value, str):
        def replace_env_var(match: re.Match[str]) -> str:
            # Group 1 is ${VAR}, group 2 is $VAR
            var_name = match.group(1) or match.group(2)
            return os.environ.get(var_name, match.group(0))

        return ENV_VAR_PATTERN.sub(replace_env_var, value)

    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]

    else:
        return value


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Environment variables in the format ${VAR_NAME} or $VAR_NAME are expanded.

    Args:
        config_path: Path to config file. If None, searches for .devscontext.yaml
                    in current directory and parent directories.

    Returns:
        Loaded configuration with env vars expanded.
    """
    if config_path is None:
        config_path = find_config_file()

    if config_path is None or not config_path.exists():
        return Config()

    with open(config_path) as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    # Expand environment variables
    data = expand_env_vars(data)

    return Config.model_validate(data)


def find_config_file() -> Path | None:
    """Search for .devscontext.yaml in current and parent directories."""
    current = Path.cwd()

    for directory in [current, *current.parents]:
        config_file = directory / ".devscontext.yaml"
        if config_file.exists():
            return config_file

    return None
