# Copyright (c) 2024 Anthropic, PBC
# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

"""
HTTP Server Transport Module

This module implements a regular HTTP transport layer for MCP servers.

Example usage:
```
```
"""
import logging
from contextlib import asynccontextmanager

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

import mcpengine.types as types
from mcpengine.server.auth.backend import AuthenticationBackend

logger = logging.getLogger(__name__)

class HttpServerTransport:
    """
    SSE server transport for MCP. This class provides _two_ ASGI applications,
    suitable to be used with a framework like Starlette and a server like Hypercorn:

        1. connect_sse() is an ASGI application which receives incoming GET requests,
           and sets up a new SSE stream to send server messages to the client.
        2. handle_post_message() is an ASGI application which receives incoming POST
           requests, which should contain client messages that link to a
           previously-established SSE session.
    """

    _auth_backend: AuthenticationBackend | None

    def __init__(
            self, auth_backend: AuthenticationBackend | None = None
    ) -> None:
        """
        Creates a new SSE server transport, which will direct the client to POST
        messages to the relative or absolute URL given.
        """

        super().__init__()
        self._auth_backend = auth_backend
        logger.debug("HTTP Transport Initialized")


    @asynccontextmanager
    async def http_server(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            logger.error("connect_sse received non-HTTP request")
            raise ValueError("connect_sse can only handle HTTP requests")

        read_stream: MemoryObjectReceiveStream[types.JSONRPCMessage | Exception]
        read_stream_writer: MemoryObjectSendStream[types.JSONRPCMessage | Exception]

        write_stream: MemoryObjectSendStream[types.JSONRPCMessage]
        write_stream_reader: MemoryObjectReceiveStream[types.JSONRPCMessage]

        read_stream_writer, read_stream = anyio.create_memory_object_stream(1)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        request = Request(scope, receive)
        body = await request.body()
        message = types.JSONRPCMessage.model_validate_json(body)

        err_response = await self.validate_auth(request, message)
        if err_response:
            await err_response(scope, receive, send)
            return

        await read_stream_writer.send(message)

        async def http_writer():
            logger.debug("Starting HTTP reader")

            response_content = []
            async with (
                write_stream_reader,
                write_stream,
                read_stream_writer,
                read_stream,
            ):
                async for message in write_stream_reader:
                    # TODO: We close read_stream_writer here because the underlying
                    # session logic ties the read_stream and write_stream together,
                    # and closes the both of them when one is closed. Thus, the way that
                    # session management is written, if we were to send the request and
                    # then close read_stream_writer in http_reader above,
                    # write_stream_reader would get prematurely closed. We have to then
                    # wait until we get a response, and then we can close it.
                    # The underlying logic should be refactored, but until that happens,
                    # this is the much easier path.
                    await read_stream_writer.aclose()

                    response_content.append(
                        message.model_dump(
                            by_alias=True, exclude_none=True,
                        )
                    )
                response = JSONResponse(status_code=200, content=response_content)
                await response(scope, receive, send)

        async with anyio.create_task_group() as tg:
            tg.start_soon(http_writer)
            yield read_stream, write_stream

    async def validate_auth(
            self,
            request: Request,
            message: types.JSONRPCMessage,
    ) -> Response | None:
        if self._auth_backend:
            logger.debug("authentication backend configured for SseServerTransport")
            try:
                await self._auth_backend.authenticate(request, message)
            except Exception as e:
                logger.error(f"Failed to authenticate: {e}")
                response = self._auth_backend.on_error(e)
                return response
