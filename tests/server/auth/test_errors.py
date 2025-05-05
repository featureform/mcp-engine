import pytest
from pydantic import AnyUrl
from starlette.requests import Request

from mcpengine import MCPEngine, McpError
from mcpengine.errors import AuthenticationError, AuthorizationError
from mcpengine.server.auth.backend import BearerTokenBackend
from mcpengine.server.auth.providers.config import IdpConfig
from mcpengine.server.mcpengine.resources import FunctionResource
from mcpengine.shared.memory import (
    create_connected_server_and_client_session as client_session,
)
from mcpengine.types import (
    AUTHENTICATION_ERROR,
    AUTHORIZATION_ERROR,
    JSONRPCMessage,
    JSONRPCRequest,
)


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


@pytest.mark.anyio
async def test_resource_errors():
    mcp = MCPEngine()

    def authz_error():
        raise AuthorizationError

    def authn_error():
        raise AuthenticationError

    authz_error_resource = FunctionResource(
        uri=AnyUrl("resource://authz_error"),
        name="authz_error",
        fn=authz_error,
    )
    mcp.add_resource(authz_error_resource)

    authn_error_resource = FunctionResource(
        uri=AnyUrl("resource://authn_error"),
        name="authn_error",
        fn=authn_error,
    )
    mcp.add_resource(authn_error_resource)

    async with client_session(mcp._mcp_server, raise_exceptions=False) as client:
        with pytest.raises(McpError) as errinfo:
            await client.read_resource(AnyUrl("resource://authn_error"))
        base_error = errinfo.value.error
        assert base_error.code == AUTHENTICATION_ERROR

    async with client_session(mcp._mcp_server, raise_exceptions=False) as client:
        with pytest.raises(McpError) as errinfo:
            await client.read_resource(AnyUrl("resource://authz_error"))
        base_error = errinfo.value.error
        assert base_error.code == AUTHORIZATION_ERROR


@pytest.mark.anyio
async def test_prompt_errors():
    mcp = MCPEngine()

    @mcp.prompt()
    def authn_error():
        raise AuthenticationError

    @mcp.prompt()
    def authz_error():
        raise AuthorizationError

    async with client_session(mcp._mcp_server) as client:
        with pytest.raises(McpError) as errinfo:
            await client.get_prompt("authn_error")
        base_error = errinfo.value.error
        assert base_error.code == AUTHENTICATION_ERROR

    async with client_session(mcp._mcp_server) as client:
        with pytest.raises(McpError) as errinfo:
            await client.get_prompt("authz_error")
        base_error = errinfo.value.error
        assert base_error.code == AUTHORIZATION_ERROR


@pytest.mark.anyio
async def test_allow_unauthenticated_list():
    backend = BearerTokenBackend(
        idp_config=IdpConfig(
            hostname="http://localhost:8000",
            issuer_url="http://some-issuer",
            allow_unauthenticated_list=True,
        ),
        scopes=set(),
        scopes_mapping={},
    )

    http_request = Request(
        scope={"type": "http"},
    )

    json_rpc_message = JSONRPCMessage(root=JSONRPCRequest(
        id="123",
        jsonrpc="2.0",
        method="tools/list",
        params={},
    ))

    await backend.authenticate(http_request, json_rpc_message)


    backend = BearerTokenBackend(
        idp_config=IdpConfig(
            hostname="http://localhost:8000",
            issuer_url="http://some-issuer",
            allow_unauthenticated_list=False,
        ),
        scopes=set(),
        scopes_mapping={},
    )

    with pytest.raises(AuthenticationError):
        await backend.authenticate(http_request, json_rpc_message)
