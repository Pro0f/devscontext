# Plugin Development Guide

DevsContext uses a plugin architecture for adapters (data sources) and synthesis (context processing). This guide explains how to create custom plugins.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    PluginRegistry                        │
│  ┌─────────────────────┐  ┌─────────────────────────┐  │
│  │  Adapter Plugins    │  │  Synthesis Plugins      │  │
│  │  ├── JiraAdapter    │  │  ├── LLMSynthesis       │  │
│  │  ├── SlackAdapter   │  │  ├── TemplateSynthesis  │  │
│  │  ├── LocalDocs...   │  │  └── PassthroughSynth.  │  │
│  │  └── YourAdapter    │  │                         │  │
│  └─────────────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Creating an Adapter

Adapters fetch context from external sources. Each adapter must implement the `Adapter` base class.

### Step 1: Define Configuration Model

Create a Pydantic model for your adapter's configuration:

```python
from pydantic import BaseModel, Field

class MySourceConfig(BaseModel):
    """Configuration for MySource adapter."""

    api_key: str = Field(default="", description="API key for MySource")
    base_url: str = Field(default="https://api.mysource.com")
    enabled: bool = Field(default=False, description="Enable adapter")
    primary: bool = Field(default=False, description="Is primary source")
```

### Step 2: Implement Adapter Class

```python
from typing import ClassVar

from devscontext.plugins.base import Adapter, SearchResult, SourceContext
from devscontext.models import JiraTicket

class MySourceAdapter(Adapter):
    """Adapter for fetching context from MySource."""

    # Required class attributes
    name: ClassVar[str] = "my_source"
    source_type: ClassVar[str] = "custom"  # or: issue_tracker, documentation, meeting, communication, email
    config_schema: ClassVar[type[MySourceConfig]] = MySourceConfig

    def __init__(self, config: MySourceConfig) -> None:
        self._config = config
        self._client = None  # Lazy-initialize API client

    async def fetch_task_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> SourceContext:
        """Fetch context for a task.

        Args:
            task_id: Task identifier (e.g., Jira ticket ID).
            ticket: Optional Jira ticket for context-aware fetching.

        Returns:
            SourceContext with fetched data.
        """
        if not self._config.enabled:
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        # Fetch data from your source
        data = await self._fetch_from_api(task_id, ticket)

        # Format as raw text for synthesis
        raw_text = self._format_data(data)

        return SourceContext(
            source_name=self.name,
            source_type=self.source_type,
            data=data,
            raw_text=raw_text,
            metadata={"task_id": task_id, "item_count": len(data)},
        )

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search for items matching a query.

        Args:
            query: Search terms.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult items.
        """
        if not self._config.enabled:
            return []

        results = await self._search_api(query, max_results)

        return [
            SearchResult(
                source_name=self.name,
                source_type=self.source_type,
                title=item.title,
                excerpt=item.description[:300],
                url=item.url,
                metadata={"id": item.id},
            )
            for item in results
        ]

    async def health_check(self) -> bool:
        """Verify adapter is properly configured.

        Returns:
            True if healthy, False otherwise.
        """
        if not self._config.enabled:
            return True

        try:
            # Test API connection
            await self._ping_api()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Clean up resources."""
        if self._client:
            await self._client.close()
            self._client = None

    # Optional: Custom formatting for synthesis
    def format_for_synthesis(self, context: SourceContext) -> str:
        """Custom formatting for LLM synthesis.

        Override this to provide better structured output.
        """
        return context.raw_text
```

### Step 3: Register the Adapter

For built-in adapters, add to `src/devscontext/plugins/registry.py`:

```python
def register_builtin_plugins(self) -> None:
    # ... existing adapters ...
    self.register_adapter(MySourceAdapter)
```

For external packages, use entry points (see "Publishing as a Package" below).

### Step 4: Add Configuration Support

Update `src/devscontext/models.py`:

```python
class SourcesConfig(BaseModel):
    jira: JiraConfig = Field(default_factory=JiraConfig)
    # ... existing sources ...
    my_source: MySourceConfig = Field(default_factory=MySourceConfig)
```

Update config loading in `src/devscontext/plugins/registry.py` `load_from_config()` method.

---

## Adapter Interface Reference

### Required Methods

| Method | Description |
|--------|-------------|
| `fetch_task_context(task_id, ticket)` | Fetch context for a specific task |
| `search(query, max_results)` | Search the source by keywords |
| `health_check()` | Verify configuration and connectivity |

### Optional Methods

| Method | Description |
|--------|-------------|
| `close()` | Clean up resources (HTTP clients, connections) |
| `format_for_synthesis(context)` | Custom formatting for LLM synthesis |

### Class Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique identifier (e.g., `"my_source"`) |
| `source_type` | `str` | Category: `issue_tracker`, `documentation`, `meeting`, `communication`, `email`, `custom` |
| `config_schema` | `type[BaseModel]` | Pydantic config model |

---

## Creating a Synthesis Plugin

Synthesis plugins combine context from multiple sources into a structured output.

### Interface

```python
from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel
from devscontext.plugins.base import SourceContext

class MySynthesisConfig(BaseModel):
    """Configuration for MySynthesis plugin."""
    template: str = "default"

class MySynthesisPlugin(ABC):
    """Custom synthesis plugin."""

    name: ClassVar[str] = "my_synthesis"
    config_schema: ClassVar[type[MySynthesisConfig]] = MySynthesisConfig

    def __init__(self, config: MySynthesisConfig) -> None:
        self._config = config

    async def synthesize(
        self,
        task_id: str,
        source_contexts: list[SourceContext],
    ) -> str:
        """Combine source contexts into synthesized output.

        Args:
            task_id: The task identifier.
            source_contexts: Context from each adapter.

        Returns:
            Synthesized markdown string.
        """
        # Combine contexts your way
        parts = []
        for ctx in source_contexts:
            if ctx.raw_text:
                parts.append(f"## {ctx.source_name}\n\n{ctx.raw_text}")

        return "\n\n".join(parts)

    async def close(self) -> None:
        """Clean up resources."""
        pass
```

### Built-in Synthesis Plugins

| Plugin | Description |
|--------|-------------|
| `llm` | LLM-based synthesis (default). Uses Claude/GPT to intelligently combine context. |
| `template` | Jinja2 template rendering. Uses a template file to format context. |
| `passthrough` | Raw concatenation. Simply joins all context without processing. |

---

## Testing Your Plugin

### Unit Test Example

```python
import pytest
from unittest.mock import AsyncMock, patch

from my_plugin import MySourceAdapter, MySourceConfig

@pytest.fixture
def config():
    return MySourceConfig(
        api_key="test-key",
        enabled=True,
    )

@pytest.fixture
def adapter(config):
    return MySourceAdapter(config)

@pytest.mark.asyncio
async def test_fetch_task_context(adapter):
    with patch.object(adapter, '_fetch_from_api', new_callable=AsyncMock) as mock:
        mock.return_value = [{"id": 1, "title": "Test"}]

        result = await adapter.fetch_task_context("PROJ-123")

        assert result.source_name == "my_source"
        assert result.data is not None

@pytest.mark.asyncio
async def test_health_check_disabled(config):
    config.enabled = False
    adapter = MySourceAdapter(config)

    assert await adapter.health_check() is True

@pytest.mark.asyncio
async def test_search(adapter):
    with patch.object(adapter, '_search_api', new_callable=AsyncMock) as mock:
        mock.return_value = []

        results = await adapter.search("test query")

        assert results == []
```

---

## Publishing as a Package

To distribute your plugin as a pip package, use entry points.

### pyproject.toml

```toml
[project]
name = "devscontext-mysource"
version = "0.1.0"
dependencies = ["devscontext>=0.1.0"]

[project.entry-points."devscontext.adapters"]
my_source = "devscontext_mysource:MySourceAdapter"

[project.entry-points."devscontext.synthesis"]
my_synthesis = "devscontext_mysource:MySynthesisPlugin"
```

### Package Structure

```
devscontext-mysource/
├── pyproject.toml
├── src/
│   └── devscontext_mysource/
│       ├── __init__.py
│       ├── adapter.py
│       └── config.py
└── tests/
    └── test_adapter.py
```

### Installation

Users can install your plugin with:

```bash
pip install devscontext-mysource
```

DevsContext automatically discovers plugins via entry points at startup.

---

## Best Practices

1. **Graceful Degradation**: Never crash the MCP server. Catch exceptions and return empty/partial context.

2. **Async All the Way**: Use `async/await` for all I/O operations to avoid blocking.

3. **Type Hints**: Add type hints to all function signatures for better IDE support.

4. **Logging**: Use the `devscontext.logging.get_logger(__name__)` for consistent logging.

5. **Config Validation**: Use Pydantic's validation features for configuration.

6. **Health Checks**: Implement meaningful health checks that verify API connectivity.

7. **Resource Cleanup**: Always implement `close()` to clean up HTTP clients and connections.

8. **Documentation**: Include docstrings and usage examples in your plugin.
