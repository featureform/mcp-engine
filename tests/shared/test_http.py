# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

import multiprocessing
import socket
import time
from collections.abc import AsyncGenerator, Generator

import anyio
import pytest
import uvicorn
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from mcpengine.client.session import ClientSession
from mcpengine.client.transports.http import http_client
from mcpengine.server import Server
from mcpengine.server.http import HttpServerTransport
from mcpengine.server.session import InitializationState
from mcpengine.shared.exceptions import McpError
from mcpengine.types import (
    EmptyResult,
    ErrorData,
    InitializeResult,
    TextContent,
    TextResourceContents,
    Tool,
)

SERVER_NAME = "test_server_for_HTTP"


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"http://127.0.0.1:{server_port}"


# Test server implementation
class ServerTest(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

        @self.read_resource()
        async def handle_read_resource(uri: AnyUrl) -> str | bytes:
            if uri.scheme == "foobar":
                return f"Read {uri.host}"
            elif uri.scheme == "slow":
                # Simulate a slow resource
                await anyio.sleep(2.0)
                return f"Slow response from {uri.host}"

            raise McpError(
                error=ErrorData(
                    code=404, message="OOPS! no resource with that URI was found"
                )
            )

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="test_tool",
                    description="A test tool",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict) -> list[TextContent]:
            return [TextContent(type="text", text=f"Called {name}")]


# Test fixtures
def make_server_app() -> Starlette:
    """Create test Starlette app with HTTP transport"""
    http = HttpServerTransport()
    server = ServerTest()

    async def handle_post(request: Request) -> None:
        async with http.http_server(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
                InitializationState.Initialized,
            )

    app = Starlette(
        routes=[
            Route("/mcp", endpoint=handle_post, methods=["POST"]),
        ]
    )

    return app


def run_server(server_port: int) -> None:
    app = make_server_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"starting server on {server_port}")
    server.run()

    # Give server time to start
    while not server.started:
        print("waiting for server to start")
        time.sleep(0.5)


@pytest.fixture()
def server(server_port: int) -> Generator[None, None, None]:
    proc = multiprocessing.Process(
        target=run_server, kwargs={"server_port": server_port}, daemon=True
    )
    print("starting process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("waiting for server to start")
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    yield

    print("killing server")
    # Signal the server to stop
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("server process failed to terminate")


@pytest.mark.anyio
async def test_http_client_basic_connection(server: None, server_url: str) -> None:
    async with http_client(server_url + "/mcp") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME

            # Test ping
            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


@pytest.fixture
async def initialized_http_client_session(
    server, server_url: str
) -> AsyncGenerator[ClientSession, None]:
    async with http_client(server_url + "/mcp") as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session


@pytest.mark.anyio
async def test_http_client_happy_request_and_response(
    initialized_http_client_session: ClientSession,
) -> None:
    session = initialized_http_client_session
    response = await session.read_resource(uri=AnyUrl("foobar://should-work"))
    assert len(response.contents) == 1
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read should-work"


@pytest.mark.anyio
async def test_http_client_exception_handling(
    initialized_http_client_session: ClientSession,
) -> None:
    session = initialized_http_client_session
    with pytest.raises(McpError, match="OOPS! no resource with that URI was found"):
        await session.read_resource(uri=AnyUrl("xxx://will-not-work"))
