import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin, urlparse

import anyio
import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

import mcpengine.types as types

logger = logging.getLogger(__name__)


def remove_request_params(url: str) -> str:
    return urljoin(url, urlparse(url).path)


@asynccontextmanager
async def http_client(
    endpoint_url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 30,
):
    """
    Client transport for HTTP.
    """
    read_stream: MemoryObjectReceiveStream[types.JSONRPCMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[types.JSONRPCMessage | Exception]

    write_stream: MemoryObjectSendStream[types.JSONRPCMessage]
    write_stream_reader: MemoryObjectReceiveStream[types.JSONRPCMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async with anyio.create_task_group() as tg:
        try:
            logger.info(
                f"Connecting to HTTP endpoint: {remove_request_params(endpoint_url)}"
            )

            async def post_writer():
                async with (
                    write_stream_reader,
                    httpx.AsyncClient(headers=headers) as client,
                ):
                    try:
                        async for message in write_stream_reader:
                            if isinstance(message.root, types.JSONRPCNotification):
                                logger.debug(
                                    f"Skipping notification message: {message}"
                                )
                                continue

                            logger.debug(f"Sending client message: {message}")
                            response = await client.post(
                                endpoint_url,
                                json=message.model_dump(
                                    by_alias=True,
                                    mode="json",
                                    exclude_none=True,
                                ),
                                timeout=timeout,
                            )
                            response.raise_for_status()
                            logger.debug(
                                "Client message sent successfully: "
                                f"{response.status_code}"
                            )
                            try:
                                message = types.JSONRPCMessage.model_validate_json(
                                    response.content
                                )
                                logger.debug(f"Received server message: {message}")
                                await read_stream_writer.send(message)
                            except Exception as exc:
                                logger.error(f"Error parsing server message: {exc}")
                                await read_stream_writer.send(exc)
                                continue
                    except Exception as exc:
                        logger.error(f"Error in post_writer: {exc}")
                    finally:
                        await write_stream.aclose()
                        await read_stream_writer.aclose()

            logger.info(f"Starting post_writer with endpoint URL: {endpoint_url}")
            tg.start_soon(post_writer)

            try:
                yield read_stream, write_stream
            finally:
                tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()
