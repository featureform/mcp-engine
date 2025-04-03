import pytest

from mcpengine.client.session import ClientSession
from mcpengine.shared.context import RequestContext
from mcpengine.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
from mcpengine.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    SamplingMessage,
    TextContent,
)


@pytest.mark.anyio
async def test_sampling_callback():
    from mcpengine.server.mcpengine import MCPEngine

    server = MCPEngine("test")

    callback_return = CreateMessageResult(
        role="assistant",
        content=TextContent(
            type="text", text="This is a response from the sampling callback"
        ),
        model="test-model",
        stopReason="endTurn",
    )

    async def sampling_callback(
        context: RequestContext[ClientSession, None],
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        return callback_return

    @server.tool("test_sampling")
    async def test_sampling_tool(message: str):
        value = await server.get_context().session.create_message(
            messages=[
                SamplingMessage(
                    role="user", content=TextContent(type="text", text=message)
                )
            ],
            max_tokens=100,
        )
        assert value == callback_return
        return True

    # Test with sampling callback
    async with create_session(
        server._mcp_server, sampling_callback=sampling_callback
    ) as client_session:
        # Make a request to trigger sampling callback
        result = await client_session.call_tool(
            "test_sampling", {"message": "Test message for sampling"}
        )
        assert result.isError is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

    # Test without sampling callback
    async with create_session(server._mcp_server) as client_session:
        # Make a request to trigger sampling callback
        result = await client_session.call_tool(
            "test_sampling", {"message": "Test message for sampling"}
        )
        assert result.isError is True
        assert isinstance(result.content[0], TextContent)
        assert (
            result.content[0].text
            == "Error executing tool test_sampling: Sampling not supported"
        )
