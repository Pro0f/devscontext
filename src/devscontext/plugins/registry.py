"""Plugin registry for discovering and managing plugins.

This module provides the PluginRegistry class that handles:
- Registration of adapters and synthesis plugins
- Discovery of plugins via Python entry points
- Plugin instantiation with configuration
- Lifecycle management (initialization, cleanup)

Entry Points:
    Third-party packages can register plugins via entry points in pyproject.toml:

    [project.entry-points."devscontext.adapters"]
    slack = "mypackage.slack:SlackAdapter"
    gmail = "mypackage.gmail:GmailAdapter"

    [project.entry-points."devscontext.synthesis"]
    custom = "mypackage.synthesis:CustomSynthesis"

Example Usage:
    # Create registry and discover plugins
    registry = PluginRegistry()
    registry.discover_plugins()

    # Register built-in adapters
    registry.register_adapter(JiraAdapter)
    registry.register_synthesis(LLMSynthesisPlugin)

    # Instantiate plugins with config
    jira = registry.create_adapter("jira", jira_config)
    synthesis = registry.create_synthesis("llm", synthesis_config)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from devscontext.logging import get_logger
from devscontext.plugins.base import Adapter, SynthesisPlugin  # noqa: TC001 - used at runtime

if TYPE_CHECKING:
    from pydantic import BaseModel

    from devscontext.models import DevsContextConfig

logger = get_logger(__name__)

# Entry point group names
ADAPTER_ENTRY_POINT = "devscontext.adapters"
SYNTHESIS_ENTRY_POINT = "devscontext.synthesis"


class PluginRegistry:
    """Central registry for discovering and managing plugins.

    The registry maintains mappings of plugin names to their classes,
    handles discovery via entry points, and manages plugin instantiation.

    Attributes:
        adapter_classes: Mapping of adapter names to classes.
        synthesis_classes: Mapping of synthesis plugin names to classes.
        _adapter_instances: Active adapter instances.
        _synthesis_instance: Active synthesis plugin instance.
    """

    def __init__(self) -> None:
        """Initialize an empty plugin registry."""
        # Plugin class registrations
        self._adapter_classes: dict[str, type[Adapter]] = {}
        self._synthesis_classes: dict[str, type[SynthesisPlugin]] = {}

        # Active plugin instances
        self._adapter_instances: dict[str, Adapter] = {}
        self._synthesis_instance: SynthesisPlugin | None = None

    # =========================================================================
    # BUILT-IN REGISTRATION
    # =========================================================================

    def register_builtin_plugins(self) -> None:
        """Register all built-in adapters and synthesis plugins.

        This registers:
        - JiraAdapter
        - FirefliesAdapter
        - LocalDocsAdapter
        - SlackAdapter
        - GmailAdapter
        - LLMSynthesisPlugin

        Call this before load_from_config() to ensure built-in plugins
        are available for instantiation.
        """
        # Import here to avoid circular imports
        from devscontext.adapters.fireflies import FirefliesAdapter
        from devscontext.adapters.gmail import GmailAdapter
        from devscontext.adapters.jira import JiraAdapter
        from devscontext.adapters.local_docs import LocalDocsAdapter
        from devscontext.adapters.slack import SlackAdapter
        from devscontext.synthesis import (
            LLMSynthesisPlugin,
            PassthroughSynthesisPlugin,
            TemplateSynthesisPlugin,
        )

        # Register adapters
        self.register_adapter(JiraAdapter)
        self.register_adapter(FirefliesAdapter)
        self.register_adapter(LocalDocsAdapter)
        self.register_adapter(SlackAdapter)
        self.register_adapter(GmailAdapter)

        # Register synthesis plugins
        self.register_synthesis(LLMSynthesisPlugin)
        self.register_synthesis(TemplateSynthesisPlugin)
        self.register_synthesis(PassthroughSynthesisPlugin)

        logger.debug("Registered all built-in plugins")

    def load_from_config(self, config: DevsContextConfig) -> None:
        """Initialize adapters and synthesis from configuration.

        Reads the config and creates instances for each enabled source.
        Sources with missing required config or disabled are skipped.

        Args:
            config: The full DevsContext configuration.

        Plugin loading flow:
        1. Read sources section from config
        2. For each source, check if enabled
        3. Look up in built-in plugins first, then entry points
        4. Initialize with source-specific config
        5. Skip sources with missing or invalid config
        """
        sources = config.sources

        # Load Jira adapter if enabled
        if sources.jira.enabled:
            if sources.jira.base_url and sources.jira.email:
                try:
                    self.create_adapter("jira", sources.jira)
                    logger.info("Loaded Jira adapter")
                except Exception as e:
                    logger.warning(f"Failed to load Jira adapter: {e}")
            else:
                logger.debug("Jira adapter skipped: missing base_url or email")

        # Load Fireflies adapter if enabled
        if sources.fireflies.enabled:
            if sources.fireflies.api_key:
                try:
                    self.create_adapter("fireflies", sources.fireflies)
                    logger.info("Loaded Fireflies adapter")
                except Exception as e:
                    logger.warning(f"Failed to load Fireflies adapter: {e}")
            else:
                logger.debug("Fireflies adapter skipped: missing api_key")

        # Load local docs adapter if enabled
        if sources.docs.enabled:
            try:
                self.create_adapter("local_docs", sources.docs)
                logger.info("Loaded LocalDocs adapter")
            except Exception as e:
                logger.warning(f"Failed to load LocalDocs adapter: {e}")

        # Load Slack adapter if enabled
        if sources.slack.enabled:
            if sources.slack.bot_token:
                try:
                    self.create_adapter("slack", sources.slack)
                    logger.info("Loaded Slack adapter")
                except Exception as e:
                    logger.warning(f"Failed to load Slack adapter: {e}")
            else:
                logger.debug("Slack adapter skipped: missing bot_token")

        # Load Gmail adapter if enabled
        if sources.gmail.enabled:
            if sources.gmail.credentials_path:
                try:
                    self.create_adapter("gmail", sources.gmail)
                    logger.info("Loaded Gmail adapter")
                except Exception as e:
                    logger.warning(f"Failed to load Gmail adapter: {e}")
            else:
                logger.debug("Gmail adapter skipped: missing credentials_path")

        # Load synthesis plugin
        synthesis_config = config.synthesis
        plugin_name = synthesis_config.plugin

        if plugin_name in self._synthesis_classes:
            try:
                self.create_synthesis(plugin_name, synthesis_config)
                logger.info(f"Loaded synthesis plugin: {plugin_name}")
            except Exception as e:
                logger.warning(f"Failed to load synthesis plugin '{plugin_name}': {e}")
        else:
            logger.warning(
                f"Unknown synthesis plugin '{plugin_name}', "
                f"available: {list(self._synthesis_classes.keys())}"
            )

    def get_primary_adapters(self) -> dict[str, Adapter]:
        """Get all active primary adapters.

        Primary adapters are fetched first and their context is shared
        with secondary adapters.

        Returns:
            Dict mapping adapter names to primary adapter instances.
        """
        primary: dict[str, Adapter] = {}
        for name, adapter in self._adapter_instances.items():
            # Check if adapter config has primary=True
            config = getattr(adapter, "_config", None)
            if config is not None and getattr(config, "primary", False):
                primary[name] = adapter
        return primary

    def get_secondary_adapters(self) -> dict[str, Adapter]:
        """Get all active secondary adapters.

        Secondary adapters are fetched after primary adapters and
        can use primary context for better matching.

        Returns:
            Dict mapping adapter names to secondary adapter instances.
        """
        secondary: dict[str, Adapter] = {}
        for name, adapter in self._adapter_instances.items():
            # Check if adapter config has primary=False or not set
            config = getattr(adapter, "_config", None)
            if config is None or not getattr(config, "primary", False):
                secondary[name] = adapter
        return secondary

    # =========================================================================
    # REGISTRATION
    # =========================================================================

    def register_adapter(self, adapter_class: type[Adapter]) -> None:
        """Register an adapter class.

        Args:
            adapter_class: The Adapter subclass to register.

        Raises:
            ValueError: If adapter name conflicts with existing registration.
        """
        name = adapter_class.name
        if name in self._adapter_classes:
            existing = self._adapter_classes[name]
            if existing is not adapter_class:
                raise ValueError(f"Adapter '{name}' already registered by {existing.__module__}")
            return  # Already registered same class

        self._adapter_classes[name] = adapter_class
        logger.debug(f"Registered adapter: {name} ({adapter_class.__module__})")

    def register_synthesis(self, plugin_class: type[SynthesisPlugin]) -> None:
        """Register a synthesis plugin class.

        Args:
            plugin_class: The SynthesisPlugin subclass to register.

        Raises:
            ValueError: If plugin name conflicts with existing registration.
        """
        name = plugin_class.name
        if name in self._synthesis_classes:
            existing = self._synthesis_classes[name]
            if existing is not plugin_class:
                raise ValueError(
                    f"Synthesis plugin '{name}' already registered by {existing.__module__}"
                )
            return  # Already registered same class

        self._synthesis_classes[name] = plugin_class
        logger.debug(f"Registered synthesis plugin: {name} ({plugin_class.__module__})")

    # =========================================================================
    # DISCOVERY
    # =========================================================================

    def discover_plugins(self) -> None:
        """Discover and register plugins from entry points.

        Scans for plugins registered via:
        - devscontext.adapters - adapter plugins
        - devscontext.synthesis - synthesis plugins

        Errors during discovery are logged but don't stop the process.
        """
        self._discover_entry_points(ADAPTER_ENTRY_POINT, self.register_adapter)
        self._discover_entry_points(SYNTHESIS_ENTRY_POINT, self.register_synthesis)

    def _discover_entry_points(
        self,
        group: str,
        register_fn: Any,
    ) -> None:
        """Discover plugins from a specific entry point group.

        Args:
            group: Entry point group name.
            register_fn: Function to call for each discovered plugin.
        """
        from importlib.metadata import entry_points

        eps = entry_points(group=group)

        for ep in eps:
            try:
                plugin_class = ep.load()
                register_fn(plugin_class)
                logger.info(f"Discovered plugin via entry point: {ep.name}")
            except Exception as e:
                logger.warning(
                    f"Failed to load plugin from entry point {ep.name}: {e}",
                    extra={"entry_point": ep.name, "group": group},
                )

    # =========================================================================
    # INSTANTIATION
    # =========================================================================

    def create_adapter(
        self,
        name: str,
        config: BaseModel,
    ) -> Adapter:
        """Create and return an adapter instance.

        If an instance already exists for this name, returns the existing one.

        Args:
            name: The adapter name (e.g., "jira").
            config: Configuration for the adapter (must match adapter's config_schema).

        Returns:
            The adapter instance.

        Raises:
            KeyError: If no adapter is registered with this name.
            TypeError: If config doesn't match the adapter's config_schema.
        """
        if name in self._adapter_instances:
            return self._adapter_instances[name]

        if name not in self._adapter_classes:
            raise KeyError(f"No adapter registered with name '{name}'")

        adapter_class = self._adapter_classes[name]

        # Validate config type
        expected_schema = adapter_class.config_schema
        if not isinstance(config, expected_schema):
            raise TypeError(
                f"Adapter '{name}' expects config of type {expected_schema.__name__}, "
                f"got {type(config).__name__}"
            )

        instance = adapter_class(config)  # type: ignore[call-arg]
        self._adapter_instances[name] = instance
        logger.debug(f"Created adapter instance: {name}")

        return instance

    def create_synthesis(
        self,
        name: str,
        config: BaseModel,
    ) -> SynthesisPlugin:
        """Create and return a synthesis plugin instance.

        Only one synthesis plugin can be active at a time.

        Args:
            name: The plugin name (e.g., "llm").
            config: Configuration for the plugin.

        Returns:
            The plugin instance.

        Raises:
            KeyError: If no plugin is registered with this name.
            TypeError: If config doesn't match the plugin's config_schema.
        """
        if self._synthesis_instance is not None:
            # Check if it's the same type
            if self._synthesis_instance.name == name:
                return self._synthesis_instance
            # Close existing before creating new
            logger.debug(f"Replacing synthesis plugin: {self._synthesis_instance.name} -> {name}")

        if name not in self._synthesis_classes:
            raise KeyError(f"No synthesis plugin registered with name '{name}'")

        plugin_class = self._synthesis_classes[name]

        # Validate config type
        expected_schema = plugin_class.config_schema
        if not isinstance(config, expected_schema):
            raise TypeError(
                f"Plugin '{name}' expects config of type {expected_schema.__name__}, "
                f"got {type(config).__name__}"
            )

        instance = plugin_class(config)  # type: ignore[call-arg]
        self._synthesis_instance = instance
        logger.debug(f"Created synthesis plugin instance: {name}")

        return instance

    # =========================================================================
    # INSTANCE ACCESS
    # =========================================================================

    def get_adapter(self, name: str) -> Adapter | None:
        """Get an existing adapter instance.

        Args:
            name: The adapter name.

        Returns:
            The adapter instance, or None if not instantiated.
        """
        return self._adapter_instances.get(name)

    def get_synthesis(self) -> SynthesisPlugin | None:
        """Get the active synthesis plugin instance.

        Returns:
            The synthesis plugin, or None if not instantiated.
        """
        return self._synthesis_instance

    def get_active_adapters(self) -> dict[str, Adapter]:
        """Get all active adapter instances.

        Returns:
            Dict mapping adapter names to instances.
        """
        return dict(self._adapter_instances)

    # =========================================================================
    # INTROSPECTION
    # =========================================================================

    def list_adapters(self) -> list[str]:
        """List all registered adapter names.

        Returns:
            List of adapter names.
        """
        return list(self._adapter_classes.keys())

    def list_synthesis_plugins(self) -> list[str]:
        """List all registered synthesis plugin names.

        Returns:
            List of plugin names.
        """
        return list(self._synthesis_classes.keys())

    def get_adapter_config_schema(self, name: str) -> type[BaseModel]:
        """Get the configuration schema for an adapter.

        Args:
            name: The adapter name.

        Returns:
            The Pydantic model class for the adapter's config.

        Raises:
            KeyError: If no adapter is registered with this name.
        """
        if name not in self._adapter_classes:
            raise KeyError(f"No adapter registered with name '{name}'")
        return self._adapter_classes[name].config_schema

    def get_synthesis_config_schema(self, name: str) -> type[BaseModel]:
        """Get the configuration schema for a synthesis plugin.

        Args:
            name: The plugin name.

        Returns:
            The Pydantic model class for the plugin's config.

        Raises:
            KeyError: If no plugin is registered with this name.
        """
        if name not in self._synthesis_classes:
            raise KeyError(f"No synthesis plugin registered with name '{name}'")
        return self._synthesis_classes[name].config_schema

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    async def close_all(self) -> None:
        """Close all plugin instances and clean up resources.

        Should be called during shutdown to properly release resources.
        """
        # Close adapters
        for name, adapter in list(self._adapter_instances.items()):
            try:
                await adapter.close()
                logger.debug(f"Closed adapter: {name}")
            except Exception as e:
                logger.warning(f"Error closing adapter {name}: {e}")

        self._adapter_instances.clear()

        # Close synthesis plugin
        if self._synthesis_instance is not None:
            try:
                await self._synthesis_instance.close()
                logger.debug(f"Closed synthesis plugin: {self._synthesis_instance.name}")
            except Exception as e:
                logger.warning(f"Error closing synthesis plugin: {e}")

            self._synthesis_instance = None

    async def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all active adapters.

        Returns:
            Dict mapping adapter names to health status.
        """
        results: dict[str, bool] = {}

        for name, adapter in self._adapter_instances.items():
            try:
                results[name] = await adapter.health_check()
            except Exception as e:
                logger.warning(f"Health check failed for {name}: {e}")
                results[name] = False

        return results
