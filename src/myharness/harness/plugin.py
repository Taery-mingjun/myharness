"""Dynamic plugin loading and lifecycle management.

Supports loading, unloading, and reloading plugins that extend the
system's capabilities at runtime.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import structlog

from myharness.core.exceptions import HarnessError

logger = structlog.get_logger(__name__)


class PluginManager:
    """Dynamic plugin loading and lifecycle management.

    Plugins are Python modules that can be loaded at runtime to extend
    the system's capabilities. Each plugin must have a register()
    function that accepts the harness supervisor and registers its
    components.
    """

    def __init__(self, supervisor: Any = None) -> None:
        """Initialize the plugin manager.

        Args:
            supervisor: The harness supervisor for plugin registration.
        """
        self._supervisor = supervisor
        self._plugins: dict[str, Any] = {}
        logger.info("plugin_manager_initialized")

    async def load_plugin(self, plugin_path: str) -> None:
        """Load a plugin from a file path or module name.

        Args:
            plugin_path: Path to the plugin Python file or dotted module name.

        Raises:
            HarnessError: If the plugin cannot be loaded.
        """
        plugin_path_obj = Path(plugin_path)
        plugin_name: str

        if plugin_path_obj.exists() and plugin_path_obj.is_file():
            # Load from file path
            plugin_name = plugin_path_obj.stem
            spec = importlib.util.spec_from_file_location(
                plugin_name, str(plugin_path_obj)
            )
            if spec is None or spec.loader is None:
                raise HarnessError(
                    f"Could not load plugin from path: {plugin_path}",
                    code="PLUGIN_LOAD_ERROR",
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[plugin_name] = module
            spec.loader.exec_module(module)
        else:
            # Load as module name
            plugin_name = plugin_path
            module = importlib.import_module(plugin_path)

        # Call register if available
        if hasattr(module, "register") and self._supervisor is not None:
            if callable(module.register):
                result = module.register(self._supervisor)
                if hasattr(result, "__await__"):
                    await result

        self._plugins[plugin_name] = module
        logger.info("plugin_loaded", plugin_name=plugin_name)

    async def unload_plugin(self, plugin_name: str) -> None:
        """Unload a previously loaded plugin.

        Args:
            plugin_name: The name of the plugin to unload.
        """
        if plugin_name not in self._plugins:
            logger.warning(
                "plugin_not_loaded",
                plugin_name=plugin_name,
            )
            return

        module = self._plugins.pop(plugin_name)

        # Call unregister if available
        if hasattr(module, "unregister"):
            if callable(module.unregister):
                result = module.unregister()
                if hasattr(result, "__await__"):
                    await result

        # Remove from sys.modules
        sys.modules.pop(plugin_name, None)

        logger.info("plugin_unloaded", plugin_name=plugin_name)

    async def list_plugins(self) -> list[str]:
        """List all loaded plugins.

        Returns:
            A list of loaded plugin names.
        """
        return sorted(self._plugins.keys())

    async def reload_plugin(self, plugin_name: str) -> None:
        """Reload a plugin by unloading and loading it again.

        Args:
            plugin_name: The name of the plugin to reload.

        Raises:
            HarnessError: If the plugin is not currently loaded.
        """
        if plugin_name not in self._plugins:
            raise HarnessError(
                f"Plugin not loaded: {plugin_name}",
                code="PLUGIN_NOT_FOUND",
            )

        module = self._plugins[plugin_name]
        source_file = getattr(module, "__file__", None)

        await self.unload_plugin(plugin_name)

        if source_file:
            await self.load_plugin(source_file)
        else:
            await self.load_plugin(plugin_name)

        logger.info("plugin_reloaded", plugin_name=plugin_name)
