"""
MCPEngine Desktop Example

A simple example that exposes the desktop directory as a resource.
"""

from pathlib import Path

from mcp.server.mcpengine import MCPEngine

# Create server
mcp = MCPEngine("Demo")


@mcp.resource("dir://desktop")
def desktop() -> list[str]:
    """List the files in the user's desktop"""
    desktop = Path.home() / "Desktop"
    return [str(f) for f in desktop.iterdir()]


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b
