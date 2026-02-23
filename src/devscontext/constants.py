"""Constants and configuration defaults for DevsContext.

This module contains all magic values, default configurations, and constants
used throughout the application. Import from here instead of hardcoding values.
"""

from typing import Final

# =============================================================================
# VERSION
# =============================================================================
VERSION: Final[str] = "0.1.0"

# =============================================================================
# CACHE DEFAULTS
# =============================================================================
DEFAULT_CACHE_TTL_SECONDS: Final[int] = 900  # 15 minutes
DEFAULT_CACHE_MAX_SIZE: Final[int] = 100

# =============================================================================
# HTTP CLIENT DEFAULTS
# =============================================================================
DEFAULT_HTTP_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_HTTP_MAX_RETRIES: Final[int] = 3

# =============================================================================
# JIRA API
# =============================================================================
JIRA_API_VERSION: Final[str] = "3"
JIRA_API_BASE_PATH: Final[str] = f"/rest/api/{JIRA_API_VERSION}"
JIRA_MAX_COMMENTS: Final[int] = 50
JIRA_TICKET_FIELDS: Final[str] = (
    "summary,description,status,priority,assignee,reporter,labels,issuetype,created,updated"
)

# =============================================================================
# FIREFLIES API
# =============================================================================
FIREFLIES_API_URL: Final[str] = "https://api.fireflies.ai/graphql"
FIREFLIES_MAX_TRANSCRIPTS: Final[int] = 10
FIREFLIES_SEARCH_LIMIT: Final[int] = 5

# =============================================================================
# LOCAL DOCS
# =============================================================================
SUPPORTED_DOC_EXTENSIONS: Final[tuple[str, ...]] = (".md", ".markdown", ".txt", ".rst")
MAX_DOC_FILE_SIZE_BYTES: Final[int] = 1_000_000  # 1MB
MAX_DOCS_TO_SEARCH: Final[int] = 100

# =============================================================================
# SYNTHESIS / LLM
# =============================================================================
DEFAULT_LLM_MODEL: Final[str] = "claude-3-haiku-20240307"
MAX_CONTEXT_LENGTH_CHARS: Final[int] = 100_000
MAX_SYNTHESIS_INPUT_CHARS: Final[int] = 50_000

# =============================================================================
# MCP SERVER
# =============================================================================
MCP_SERVER_NAME: Final[str] = "devscontext"

# =============================================================================
# CONFIG FILE
# =============================================================================
CONFIG_FILE_NAME: Final[str] = ".devscontext.yaml"
CONFIG_EXAMPLE_FILE_NAME: Final[str] = ".devscontext.yaml.example"

# =============================================================================
# LOGGING
# =============================================================================
LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

# =============================================================================
# ADAPTER NAMES (for consistent referencing)
# =============================================================================
ADAPTER_JIRA: Final[str] = "jira"
ADAPTER_FIREFLIES: Final[str] = "fireflies"
ADAPTER_LOCAL_DOCS: Final[str] = "local_docs"

# =============================================================================
# SOURCE TYPES
# =============================================================================
SOURCE_TYPE_ISSUE_TRACKER: Final[str] = "issue_tracker"
SOURCE_TYPE_MEETING: Final[str] = "meeting"
SOURCE_TYPE_DOCUMENTATION: Final[str] = "documentation"
