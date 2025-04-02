"""
MCPEngine Echo Server
"""

from mcp.server.mcpengine import MCPEngine

# Create server
mcp = MCPEngine("Echo Server")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text"""
    return text
