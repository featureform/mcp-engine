"""MCPEngine - A more secure interface for MCP servers."""

from importlib.metadata import version

from .server import Context, MCPEngine
from .utilities.types import Image

__version__ = version("mcp")
__all__ = ["MCPEngine", "Context", "Image"]
