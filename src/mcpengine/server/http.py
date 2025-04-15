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
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

import mcpengine.types as types

logger = logging.getLogger(__name__)

@asynccontextmanager
async def http_server(scope: Scope, receive: Receive, send: Send):
    if scope["type"] != "http":
        logger.error("connect_sse received non-HTTP request")
        raise ValueError("connect_sse can only handle HTTP requests")

    read_stream: MemoryObjectReceiveStream[types.JSONRPCMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[types.JSONRPCMessage | Exception]

    write_stream: MemoryObjectSendStream[types.JSONRPCMessage]
    write_stream_reader: MemoryObjectReceiveStream[types.JSONRPCMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(10)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(10)


    async def http_reader():
        logger.debug("Starting HTTP writer")

        request = Request(scope, receive)
        body = await request.body()
        message = types.JSONRPCMessage.model_validate_json(body)
        await read_stream_writer.send(message)

    async def http_writer():
        logger.debug("Starting HTTP reader")

        response_content = []
        async with write_stream_reader:
            async for message in write_stream_reader:
                # TODO: We close read_stream_writer here because the underlying
                # session logic ties the read_stream and write_stream together,
                # and closes the both of them when one is closed. Thus, the way that
                # session management is written, if we were to send the request and
                # then close read_stream_writer in http_reader above,
                # write_stream_reader would get prematurely closed. We have to then
                # wait until we get a response, and then we can close it without
                # losing any messages.
                read_stream_writer.close()
                response_content.append(
                    message.model_dump(
                        by_alias=True, exclude_none=True,
                    )
                )
        response = JSONResponse(status_code=200, content=response_content)
        await response(scope, receive, send)

    #err_response = await validate_auth(request, message)
    #if err_response:
    #    await err_response(scope, receive, send)
    #    return

    async with anyio.create_task_group() as tg:
        tg.start_soon(http_reader)
        tg.start_soon(http_writer)
        yield read_stream, write_stream