"""MCPEngine - A more ergonomic interface for MCP servers."""

from importlib.metadata import version

from .server import Context, MCPEngine
from .utilities.types import Image

__version__ = version("mcpengine")
__all__ = ["MCPEngine", "Context", "Image"]
