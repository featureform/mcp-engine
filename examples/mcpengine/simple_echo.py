"""
MCPEngine Echo Server
"""

from mcpengine import MCPEngine

# Create server
mcp = MCPEngine("Echo Server")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text"""
    return text
