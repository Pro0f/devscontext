"""Configuration loader for DevsContext.

This module handles loading and parsing configuration from YAML files,
with support for environment variable expansion.

Example:
    config = load_config()
    if config.adapters.jira.enabled:
        print(f"Jira URL: {config.adapters.jira.base_url}")
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from devscontext.constants import (
    CONFIG_FILE_NAME,
    DEFAULT_CACHE_MAX_SIZE,
    DEFAULT_CACHE_TTL_SECONDS,
)


class JiraConfig(BaseModel):
    """Jira adapter configuration.

    Attributes:
        base_url: The Jira instance URL (e.g., https://company.atlassian.net).
        email: Email address for Jira authentication.
        api_token: API token for Jira authentication.
        enabled: Whether the Jira adapter is enabled.
    """

    base_url: str = Field(default="", description="Jira instance URL")
    email: str = Field(default="", description="Jira authentication email")
    api_token: str = Field(default="", description="Jira API token")
    enabled: bool = Field(default=False, description="Whether adapter is enabled")


class FirefliesConfig(BaseModel):
    """Fireflies.ai adapter configuration.

    Attributes:
        api_key: API key for Fireflies.ai authentication.
        enabled: Whether the Fireflies adapter is enabled.
    """

    api_key: str = Field(default="", description="Fireflies.ai API key")
    enabled: bool = Field(default=False, description="Whether adapter is enabled")


class LocalDocsConfig(BaseModel):
    """Local documentation adapter configuration.

    Attributes:
        paths: List of directory paths to search for documentation.
        enabled: Whether the local docs adapter is enabled.
    """

    paths: list[str] = Field(default_factory=list, description="Paths to doc directories")
    enabled: bool = Field(default=True, description="Whether adapter is enabled")


class AdaptersConfig(BaseModel):
    """Configuration for all adapters.

    Attributes:
        jira: Jira adapter configuration.
        fireflies: Fireflies adapter configuration.
        local_docs: Local docs adapter configuration.
    """

    jira: JiraConfig = Field(default_factory=JiraConfig)
    fireflies: FirefliesConfig = Field(default_factory=FirefliesConfig)
    local_docs: LocalDocsConfig = Field(default_factory=LocalDocsConfig)


class CacheConfig(BaseModel):
    """Cache configuration.

    Attributes:
        ttl_seconds: Time-to-live in seconds for cache entries.
        max_size: Maximum number of entries in the cache.
    """

    ttl_seconds: int = Field(
        default=DEFAULT_CACHE_TTL_SECONDS,
        description="Cache entry TTL in seconds",
    )
    max_size: int = Field(
        default=DEFAULT_CACHE_MAX_SIZE,
        description="Maximum cache entries",
    )


class Config(BaseModel):
    """Root configuration for DevsContext.

    Attributes:
        adapters: Configuration for all adapters.
        cache: Cache configuration.
    """

    adapters: AdaptersConfig = Field(default_factory=AdaptersConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)


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
    """Search for .devscontext.yaml in current and parent directories.

    Walks up the directory tree from the current working directory,
    looking for a configuration file.

    Returns:
        Path to the config file if found, None otherwise.
    """
    current = Path.cwd()

    for directory in [current, *current.parents]:
        config_file = directory / CONFIG_FILE_NAME
        if config_file.exists():
            return config_file

    return None
