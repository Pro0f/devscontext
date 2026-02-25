"""Tests for the plugin registry."""

from __future__ import annotations

import pytest

from devscontext.models import (
    DevsContextConfig,
    DocsConfig,
    FirefliesConfig,
    JiraConfig,
    SourcesConfig,
    SynthesisConfig,
)
from devscontext.plugins.registry import PluginRegistry


class TestPluginRegistryBuiltins:
    """Tests for built-in plugin registration."""

    def test_register_builtin_plugins(self) -> None:
        """Test that built-in plugins are registered correctly."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        # Check adapters
        assert "jira" in registry.list_adapters()
        assert "fireflies" in registry.list_adapters()
        assert "local_docs" in registry.list_adapters()

        # Check synthesis plugins
        assert "llm" in registry.list_synthesis_plugins()
        assert "template" in registry.list_synthesis_plugins()
        assert "passthrough" in registry.list_synthesis_plugins()

    def test_register_builtin_plugins_idempotent(self) -> None:
        """Test that calling register_builtin_plugins twice doesn't error."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()
        registry.register_builtin_plugins()  # Should not raise

        assert len(registry.list_adapters()) == 3
        # 3 synthesis plugins: llm, template, passthrough
        assert len(registry.list_synthesis_plugins()) == 3


class TestPluginRegistryLoadFromConfig:
    """Tests for config-driven plugin loading."""

    def test_load_jira_adapter_when_enabled(self) -> None:
        """Test that Jira adapter is loaded when enabled with valid config."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(
                jira=JiraConfig(
                    base_url="https://test.atlassian.net",
                    email="test@example.com",
                    api_token="test-token",
                    enabled=True,
                ),
                fireflies=FirefliesConfig(enabled=False),
                docs=DocsConfig(enabled=False),
            ),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)

        assert registry.get_adapter("jira") is not None
        assert registry.get_adapter("fireflies") is None
        assert registry.get_adapter("local_docs") is None

    def test_load_skips_disabled_adapters(self) -> None:
        """Test that disabled adapters are not loaded."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(
                jira=JiraConfig(
                    base_url="https://test.atlassian.net",
                    email="test@example.com",
                    api_token="test-token",
                    enabled=False,  # Disabled
                ),
            ),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)

        assert registry.get_adapter("jira") is None

    def test_load_skips_jira_without_required_fields(self) -> None:
        """Test that Jira adapter is skipped without base_url or email."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(
                jira=JiraConfig(
                    base_url="",  # Missing
                    email="test@example.com",
                    enabled=True,
                ),
            ),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)

        assert registry.get_adapter("jira") is None

    def test_load_local_docs_adapter(self) -> None:
        """Test that local docs adapter is loaded when enabled."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(
                jira=JiraConfig(enabled=False),
                fireflies=FirefliesConfig(enabled=False),
                docs=DocsConfig(enabled=True, paths=["./docs/"]),
            ),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)

        assert registry.get_adapter("local_docs") is not None

    def test_load_synthesis_plugin(self) -> None:
        """Test that synthesis plugin is loaded from config."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)

        assert registry.get_synthesis() is not None
        assert registry.get_synthesis().name == "llm"


class TestPluginRegistryPrimarySecondary:
    """Tests for primary/secondary adapter classification."""

    def test_get_primary_adapters(self) -> None:
        """Test getting primary adapters."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(
                jira=JiraConfig(
                    base_url="https://test.atlassian.net",
                    email="test@example.com",
                    api_token="test-token",
                    enabled=True,
                    primary=True,
                ),
                docs=DocsConfig(enabled=True, primary=False),
            ),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)

        primary = registry.get_primary_adapters()
        secondary = registry.get_secondary_adapters()

        assert "jira" in primary
        assert "local_docs" in secondary
        assert "jira" not in secondary
        assert "local_docs" not in primary

    def test_get_secondary_adapters_default(self) -> None:
        """Test that adapters without primary field are secondary."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(
                docs=DocsConfig(enabled=True),  # primary defaults to False
            ),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)

        secondary = registry.get_secondary_adapters()
        assert "local_docs" in secondary


class TestSynthesisPluginSelection:
    """Tests for selecting different synthesis plugins."""

    def test_load_passthrough_plugin(self) -> None:
        """Test loading passthrough synthesis plugin."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(),
            synthesis=SynthesisConfig(plugin="passthrough"),
        )

        registry.load_from_config(config)

        assert registry.get_synthesis() is not None
        assert registry.get_synthesis().name == "passthrough"

    def test_load_template_plugin(self) -> None:
        """Test loading template synthesis plugin."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(),
            synthesis=SynthesisConfig(plugin="template", template_path="./template.j2"),
        )

        registry.load_from_config(config)

        assert registry.get_synthesis() is not None
        assert registry.get_synthesis().name == "template"


class TestPluginRegistryLifecycle:
    """Tests for plugin lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_all(self) -> None:
        """Test closing all plugins."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(
                docs=DocsConfig(enabled=True),
            ),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)
        assert registry.get_adapter("local_docs") is not None

        await registry.close_all()

        # Instances should be cleared
        assert registry.get_adapter("local_docs") is None
        assert registry.get_synthesis() is None

    @pytest.mark.asyncio
    async def test_health_check_all(self) -> None:
        """Test health checking all adapters."""
        registry = PluginRegistry()
        registry.register_builtin_plugins()

        config = DevsContextConfig(
            sources=SourcesConfig(
                docs=DocsConfig(enabled=True, paths=["./docs/"]),
            ),
            synthesis=SynthesisConfig(plugin="llm", api_key="test-key"),
        )

        registry.load_from_config(config)

        results = await registry.health_check_all()

        # Local docs should be healthy (paths can exist or not)
        assert "local_docs" in results
