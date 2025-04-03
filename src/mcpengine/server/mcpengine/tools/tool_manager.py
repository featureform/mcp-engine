# Copyright (c) 2024 Anthropic, PBC
# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

from __future__ import annotations as _annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcpengine.server.mcpengine.exceptions import ToolError
from mcpengine.server.mcpengine.tools.base import Tool
from mcpengine.server.mcpengine.utilities.logging import get_logger
from mcpengine.shared.context import LifespanContextT

if TYPE_CHECKING:
    from mcpengine.server.mcpengine.server import Context
    from mcpengine.server.session import ServerSessionT

logger = get_logger(__name__)


class ToolManager:
    """Manages MCPEngine tools."""

    def __init__(self, warn_on_duplicate_tools: bool = True):
        self._tools: dict[str, Tool] = {}
        self.warn_on_duplicate_tools = warn_on_duplicate_tools

    def get_tool(self, name: str) -> Tool | None:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        scopes: list[str] | None = None,
    ) -> Tool:
        """Add a tool to the server."""
        tool = Tool.from_function(fn, name=name, description=description, scopes=scopes)
        existing = self._tools.get(tool.name)
        if existing:
            if self.warn_on_duplicate_tools:
                logger.warning(f"Tool already exists: {tool.name}")
            return existing
        self._tools[tool.name] = tool
        return tool

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT] | None = None,
    ) -> Any:
        """Call a tool by name with arguments."""
        tool = self.get_tool(name)
        if not tool:
            raise ToolError(f"Unknown tool: {name}")

        return await tool.run(arguments, context=context)
