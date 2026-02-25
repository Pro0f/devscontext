"""Plugin system for DevsContext.

This package provides the plugin architecture for extensible sources and synthesis.
Third-party packages can implement Adapter or SynthesisPlugin to add new
data sources or synthesis strategies without modifying core code.

Plugin Interfaces:
    - Adapter: Base class for data sources (Jira, Slack, Gmail, etc.)
    - SynthesisPlugin: Base class for synthesis strategies (LLM, template, etc.)

Data Models:
    - SourceContext: Container for data returned by an adapter
    - SearchResult: A single search result from a source

Registry:
    - PluginRegistry: Central registry for discovering and managing plugins

Example:
    from devscontext.plugins import Adapter, SourceContext, PluginRegistry

    class SlackAdapter(Adapter):
        name = "slack"
        source_type = "communication"
        config_schema = SlackConfig

        async def fetch_task_context(self, task_id, ticket=None):
            # Fetch relevant Slack messages...
            return SourceContext(...)

    # Register the adapter
    registry = PluginRegistry()
    registry.register_adapter(SlackAdapter)
"""

from devscontext.plugins.base import (
    Adapter,
    SearchResult,
    SourceContext,
    SynthesisPlugin,
)
from devscontext.plugins.registry import PluginRegistry

__all__ = [
    "Adapter",
    "PluginRegistry",
    "SearchResult",
    "SourceContext",
    "SynthesisPlugin",
]
