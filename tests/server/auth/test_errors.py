import pytest

from mcpengine import MCPEngine, McpError
from mcpengine.errors import AuthenticationError, AuthorizationError
from mcpengine.shared.memory import (
    create_connected_server_and_client_session as client_session,
)
from mcpengine.types import AUTHENTICATION_ERROR, AUTHORIZATION_ERROR


@pytest.mark.anyio
async def test_tool_errors():
    mcp = MCPEngine()

    def authz_error():
        raise AuthorizationError

    def authn_error():
        raise AuthenticationError

    mcp.add_tool(authn_error)
    mcp.add_tool(authz_error)

    async with client_session(mcp._mcp_server, raise_exceptions=False) as client:
        with pytest.raises(McpError) as errinfo:
            await client.call_tool("authn_error")
        base_error = errinfo.value.error
        assert base_error.code == AUTHENTICATION_ERROR

    async with client_session(mcp._mcp_server, raise_exceptions=False) as client:
        with pytest.raises(McpError) as errinfo:
            await client.call_tool("authz_error")
        base_error = errinfo.value.error
        assert base_error.code == AUTHORIZATION_ERROR

