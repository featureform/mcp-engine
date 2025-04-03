# Copyright (c) 2024 Anthropic, PBC
# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

"""MCPEngine - A more ergonomic interface for MCP servers."""

from __future__ import annotations as _annotations

import inspect
import json
import re
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
)
from itertools import chain
from typing import Any, Generic, Literal
from urllib.parse import urljoin

import anyio
import httpx
import pydantic_core
import uvicorn
from pydantic import BaseModel
from pydantic.networks import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from mcpengine.server.auth.backend import (
    OAUTH_WELL_KNOWN_PATH,
    OPENID_WELL_KNOWN_PATH,
    get_auth_backend,
)
from mcpengine.server.lowlevel.helper_types import ReadResourceContents
from mcpengine.server.lowlevel.server import LifespanResultT
from mcpengine.server.lowlevel.server import Server as MCPServer
from mcpengine.server.lowlevel.server import lifespan as default_lifespan
from mcpengine.server.mcpengine.exceptions import ResourceError
from mcpengine.server.mcpengine.prompts import Prompt, PromptManager
from mcpengine.server.mcpengine.resources import (
    FunctionResource,
    Resource,
    ResourceManager,
)
from mcpengine.server.mcpengine.tools import ToolManager
from mcpengine.server.mcpengine.utilities.logging import configure_logging, get_logger
from mcpengine.server.mcpengine.utilities.types import Image
from mcpengine.server.session import ServerSession, ServerSessionT
from mcpengine.server.settings import Settings
from mcpengine.server.sse import SseServerTransport
from mcpengine.server.stdio import stdio_server
from mcpengine.shared.context import LifespanContextT, RequestContext
from mcpengine.types import (
    AnyFunction,
    EmbeddedResource,
    GetPromptResult,
    ImageContent,
    TextContent,
)
from mcpengine.types import Prompt as MCPPrompt
from mcpengine.types import PromptArgument as MCPPromptArgument
from mcpengine.types import Resource as MCPResource
from mcpengine.types import ResourceTemplate as MCPResourceTemplate
from mcpengine.types import Tool as MCPTool

logger = get_logger(__name__)


def lifespan_wrapper(
    app: MCPEngine,
    lifespan: Callable[[MCPEngine], AbstractAsyncContextManager[LifespanResultT]],
) -> Callable[[MCPServer[LifespanResultT]], AbstractAsyncContextManager[object]]:
    @asynccontextmanager
    async def wrap(s: MCPServer[LifespanResultT]) -> AsyncIterator[object]:
        async with lifespan(app) as context:
            yield context

    return wrap


class MCPEngine:
    def __init__(
        self, name: str | None = None, instructions: str | None = None, **settings: Any
    ):
        self.settings = Settings(**settings)

        self._mcp_server = MCPServer(
            name=name or "MCPEngine",
            instructions=instructions,
            lifespan=lifespan_wrapper(self, self.settings.lifespan)
            if self.settings.lifespan
            else default_lifespan,
        )
        self._tool_manager = ToolManager(
            warn_on_duplicate_tools=self.settings.warn_on_duplicate_tools
        )
        self._resource_manager = ResourceManager(
            warn_on_duplicate_resources=self.settings.warn_on_duplicate_resources
        )
        self._prompt_manager = PromptManager(
            warn_on_duplicate_prompts=self.settings.warn_on_duplicate_prompts
        )
        self.dependencies = self.settings.dependencies

        # The set of required scopes.
        self.scopes = set()
        # The mapping of function to scopes required for it.
        self.scopes_mapping: dict[str, set[str]] = {}

        # Set up MCP protocol handlers
        self._setup_handlers()

        # Configure logging
        configure_logging(self.settings.log_level)

    @property
    def name(self) -> str:
        return self._mcp_server.name

    @property
    def instructions(self) -> str | None:
        return self._mcp_server.instructions

    def run(self, transport: Literal["stdio", "sse"] = "stdio") -> None:
        """Run the MCPEngine server. Note this is a synchronous function.

        Args:
            transport: Transport protocol to use ("stdio" or "sse")
        """
        TRANSPORTS = Literal["stdio", "sse"]
        if transport not in TRANSPORTS.__args__:  # type: ignore
            raise ValueError(f"Unknown transport: {transport}")

        if transport == "stdio":
            anyio.run(self.run_stdio_async)
        else:  # transport == "sse"
            anyio.run(self.run_sse_async)

    def _setup_handlers(self) -> None:
        """Set up core MCP protocol handlers."""
        self._mcp_server.list_tools()(self.list_tools)
        self._mcp_server.call_tool()(self.call_tool)
        self._mcp_server.list_resources()(self.list_resources)
        self._mcp_server.read_resource()(self.read_resource)
        self._mcp_server.list_prompts()(self.list_prompts)
        self._mcp_server.get_prompt()(self.get_prompt)
        self._mcp_server.list_resource_templates()(self.list_resource_templates)

    async def list_tools(self) -> list[MCPTool]:
        """List all available tools."""
        tools = self._tool_manager.list_tools()
        return [
            MCPTool(
                name=info.name,
                description=info.description,
                inputSchema=info.parameters,
            )
            for info in tools
        ]

    def get_context(self) -> Context[ServerSession, object]:
        """
        Returns a Context object. Note that the context will only be valid
        during a request; outside a request, most methods will error.
        """
        try:
            request_context = self._mcp_server.request_context
        except LookupError:
            request_context = None
        return Context(request_context=request_context, mcpengine=self)

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        """Call a tool by name with arguments."""
        context = self.get_context()
        result = await self._tool_manager.call_tool(name, arguments, context=context)
        converted_result = _convert_to_content(result)
        return converted_result

    async def list_resources(self) -> list[MCPResource]:
        """List all available resources."""

        resources = self._resource_manager.list_resources()
        return [
            MCPResource(
                uri=resource.uri,
                name=resource.name or "",
                description=resource.description,
                mimeType=resource.mime_type,
            )
            for resource in resources
        ]

    async def list_resource_templates(self) -> list[MCPResourceTemplate]:
        templates = self._resource_manager.list_templates()
        return [
            MCPResourceTemplate(
                uriTemplate=template.uri_template,
                name=template.name,
                description=template.description,
            )
            for template in templates
        ]

    async def read_resource(self, uri: AnyUrl | str) -> Iterable[ReadResourceContents]:
        """Read a resource by URI."""

        resource = await self._resource_manager.get_resource(uri)
        if not resource:
            raise ResourceError(f"Unknown resource: {uri}")

        try:
            content = await resource.read()
            return [ReadResourceContents(content=content, mime_type=resource.mime_type)]
        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}")
            raise ResourceError(str(e))

    def auth(
        self, scopes: Iterable[str] | None = None
    ) -> Callable[[AnyFunction], AnyFunction]:
        """Require authentication for this handler.

        Args:
            scopes: A list of scopes that the user must be authorized for.
        """
        # Check if user passed function directly instead of calling decorator
        if callable(scopes):
            raise TypeError(
                "The @authorize decorator was used incorrectly. "
                "Did you forget to call it? Use @authorize() instead of @tool"
            )

        def decorator(fn: AnyFunction) -> AnyFunction:
            nonlocal self, scopes
            self.add_application_scopes(fn.__name__, scopes)
            return fn

        return decorator

    def add_application_scopes(
        self, handler_name: str, scopes: list[str] | None
    ) -> None:
        """Add scopes to the list of all scopes required by the application.

        When we redirect the user to login, we pass all the scopes required
        by the application. This is to prevent the user having to login in
        multiple times for each unique set of scopes on a handler.

        Args:
            scopes: List of scopes to add.
        """
        if scopes is None:
            return
        self.scopes_mapping[handler_name] = set(scopes)
        self.scopes.update(scopes)

    def add_tool(
        self,
        fn: AnyFunction,
        name: str | None = None,
        description: str | None = None,
        scopes: list[str] | None = None,
    ) -> None:
        """Add a tool to the server.

        The tool function can optionally request a Context object by adding a parameter
        with the Context type annotation. See the @tool decorator for examples.

        Args:
            fn: The function to register as a tool
            name: Optional name for the tool (defaults to function name)
            description: Optional description of what the tool does
            scopes: Optional list of scopes required by the tool (defaults to None)
        """
        self._tool_manager.add_tool(
            fn, name=name, description=description, scopes=scopes
        )

    def tool(
        self,
        name: str | None = None,
        description: str | None = None,
        scopes: list[str] | None = None,
    ) -> Callable[[AnyFunction], AnyFunction]:
        """Decorator to register a tool.

        Tools can optionally request a Context object by adding a parameter with the
        Context type annotation. The context provides access to MCP capabilities like
        logging, progress reporting, and resource access.

        Args:
            name: Optional name for the tool (defaults to function name)
            description: Optional description of what the tool does
            scopes: Optional list of scopes required by the tool (defaults to None)

        Example:
            @server.tool()
            def my_tool(x: int) -> str:
                return str(x)

            @server.tool()
            def tool_with_context(x: int, ctx: Context) -> str:
                ctx.info(f"Processing {x}")
                return str(x)

            @server.tool()
            async def async_tool(x: int, context: Context) -> str:
                await context.report_progress(50, 100)
                return str(x)
        """
        # Check if user passed function directly instead of calling decorator
        if callable(name):
            raise TypeError(
                "The @tool decorator was used incorrectly. "
                "Did you forget to call it? Use @tool() instead of @tool"
            )

        def decorator(fn: AnyFunction) -> AnyFunction:
            self.add_tool(fn, name=name, description=description, scopes=scopes)
            return fn

        return decorator

    def add_resource(self, resource: Resource) -> None:
        """Add a resource to the server.

        Args:
            resource: A Resource instance to add
        """
        self._resource_manager.add_resource(resource)

    def resource(
        self,
        uri: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        scopes: list[str] | None = None,
    ) -> Callable[[AnyFunction], AnyFunction]:
        """Decorator to register a function as a resource.

        The function will be called when the resource is read to generate its content.
        The function can return:
        - str for text content
        - bytes for binary content
        - other types will be converted to JSON

        If the URI contains parameters (e.g. "resource://{param}") or the function
        has parameters, it will be registered as a template resource.

        Args:
            uri: URI for the resource (e.g. "resource://my-resource" or "resource://{param}")
            name: Optional name for the resource
            description: Optional description of the resource
            mime_type: Optional MIME type for the resource
            scopes: Optional list of scopes required by the tool (defaults to None)

        Example:
            @server.resource("resource://my-resource")
            def get_data() -> str:
                return "Hello, world!"

            @server.resource("resource://my-resource")
            async get_data() -> str:
                data = await fetch_data()
                return f"Hello, world! {data}"

            @server.resource("resource://{city}/weather")
            def get_weather(city: str) -> str:
                return f"Weather for {city}"

            @server.resource("resource://{city}/weather")
            async def get_weather(city: str) -> str:
                data = await fetch_weather(city)
                return f"Weather for {city}: {data}"
        """
        # Check if user passed function directly instead of calling decorator
        if callable(uri):
            raise TypeError(
                "The @resource decorator was used incorrectly. "
                "Did you forget to call it? Use @resource('uri') instead of @resource"
            )

        def decorator(fn: AnyFunction) -> AnyFunction:
            # Check if this should be a template
            has_uri_params = "{" in uri and "}" in uri
            has_func_params = bool(inspect.signature(fn).parameters)

            if has_uri_params or has_func_params:
                # Validate that URI params match function params
                uri_params = set(re.findall(r"{(\w+)}", uri))
                func_params = set(inspect.signature(fn).parameters.keys())

                if uri_params != func_params:
                    raise ValueError(
                        f"Mismatch between URI parameters {uri_params} "
                        f"and function parameters {func_params}"
                    )

                # Register as template
                self._resource_manager.add_template(
                    fn=fn,
                    uri_template=uri,
                    name=name,
                    description=description,
                    scopes=scopes,
                    mime_type=mime_type or "text/plain",
                )
            else:
                # Register as regular resource
                resource = FunctionResource(
                    uri=AnyUrl(uri),
                    name=name,
                    description=description,
                    scopes=scopes,
                    mime_type=mime_type or "text/plain",
                    fn=fn,
                )
                self.add_resource(resource)

            return fn

        return decorator

    def add_prompt(self, prompt: Prompt) -> None:
        """Add a prompt to the server.

        Args:
            prompt: A Prompt instance to add
        """
        self._prompt_manager.add_prompt(prompt)

    def prompt(
        self,
        name: str | None = None,
        description: str | None = None,
        scopes: list[str] | None = None,
    ) -> Callable[[AnyFunction], AnyFunction]:
        """Decorator to register a prompt.

        Args:
            name: Optional name for the prompt (defaults to function name)
            description: Optional description of what the prompt does
            scopes: Optional list of scopes required by the tool (defaults to None)

        Example:
            @server.prompt()
            def analyze_table(table_name: str) -> list[Message]:
                schema = read_table_schema(table_name)
                return [
                    {
                        "role": "user",
                        "content": f"Analyze this schema:\n{schema}"
                    }
                ]

            @server.prompt()
            async def analyze_file(path: str) -> list[Message]:
                content = await read_file(path)
                return [
                    {
                        "role": "user",
                        "content": {
                            "type": "resource",
                            "resource": {
                                "uri": f"file://{path}",
                                "text": content
                            }
                        }
                    }
                ]
        """
        # Check if user passed function directly instead of calling decorator
        if callable(name):
            raise TypeError(
                "The @prompt decorator was used incorrectly. "
                "Did you forget to call it? Use @prompt() instead of @prompt"
            )

        def decorator(func: AnyFunction) -> AnyFunction:
            prompt = Prompt.from_function(
                func, name=name, description=description, scopes=scopes
            )
            self.add_prompt(prompt)
            return func

        return decorator

    async def run_stdio_async(self) -> None:
        """Run the server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self._mcp_server.run(
                read_stream,
                write_stream,
                self._mcp_server.create_initialization_options(),
            )

    async def run_sse_async(self) -> None:
        """Run the server using SSE transport."""
        starlette_app = self.sse_app()

        config = uvicorn.Config(
            starlette_app,
            host=self.settings.host,
            port=self.settings.port,
            log_level=self.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    def sse_app(self) -> Starlette:
        """Return an instance of the SSE server app."""
        auth_backend = get_auth_backend(self.settings, self.scopes, self.scopes_mapping)

        sse = SseServerTransport(self.settings.message_path, auth_backend)

        async def handle_sse(request: Request) -> None:
            async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,  # type: ignore[reportPrivateUsage]
            ) as streams:
                await self._mcp_server.run(
                    streams[0],
                    streams[1],
                    self._mcp_server.create_initialization_options(),
                )

        async def handle_well_known(_: Request) -> Response:
            async with httpx.AsyncClient() as client:
                issuer_url = str(self.settings.issuer_url).rstrip("/") + "/"
                well_known_url = urljoin(issuer_url, OPENID_WELL_KNOWN_PATH)
                response = await client.get(well_known_url)
                return JSONResponse(response.json())

        middleware = []

        routes = [
            Route(
                f"/{OAUTH_WELL_KNOWN_PATH}",
                endpoint=handle_well_known,
                methods=["GET", "OPTIONS"],
            ),
            Route(
                f"/{OPENID_WELL_KNOWN_PATH}",
                endpoint=handle_well_known,
                methods=["GET", "OPTIONS"],
            ),
            Route(self.settings.sse_path, endpoint=handle_sse),
            Mount(self.settings.message_path, app=sse.handle_post_message),
        ]

        return Starlette(
            debug=self.settings.debug,
            middleware=middleware,
            routes=routes,
        )

    async def list_prompts(self) -> list[MCPPrompt]:
        """List all available prompts."""
        prompts = self._prompt_manager.list_prompts()
        return [
            MCPPrompt(
                name=prompt.name,
                description=prompt.description,
                arguments=[
                    MCPPromptArgument(
                        name=arg.name,
                        description=arg.description,
                        required=arg.required,
                    )
                    for arg in (prompt.arguments or [])
                ],
            )
            for prompt in prompts
        ]

    async def get_prompt(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> GetPromptResult:
        """Get a prompt by name with arguments."""
        try:
            messages = await self._prompt_manager.render_prompt(name, arguments)

            return GetPromptResult(messages=pydantic_core.to_jsonable_python(messages))
        except Exception as e:
            logger.error(f"Error getting prompt {name}: {e}")
            raise ValueError(str(e))


def _convert_to_content(
    result: Any,
) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Convert a result to a sequence of content objects."""
    if result is None:
        return []

    if isinstance(result, TextContent | ImageContent | EmbeddedResource):
        return [result]

    if isinstance(result, Image):
        return [result.to_image_content()]

    if isinstance(result, list | tuple):
        return list(chain.from_iterable(_convert_to_content(item) for item in result))  # type: ignore[reportUnknownVariableType]

    if not isinstance(result, str):
        try:
            result = json.dumps(pydantic_core.to_jsonable_python(result))
        except Exception:
            result = str(result)

    return [TextContent(type="text", text=result)]


class Context(BaseModel, Generic[ServerSessionT, LifespanContextT]):
    """Context object providing access to MCP capabilities.

    This provides a cleaner interface to MCP's RequestContext functionality.
    It gets injected into tool and resource functions that request it via type hints.

    To use context in a tool function, add a parameter with the Context type annotation:

    ```python
    @server.tool()
    def my_tool(x: int, ctx: Context) -> str:
        # Log messages to the client
        ctx.info(f"Processing {x}")
        ctx.debug("Debug info")
        ctx.warning("Warning message")
        ctx.error("Error message")

        # Report progress
        ctx.report_progress(50, 100)

        # Access resources
        data = ctx.read_resource("resource://data")

        # Get request info
        request_id = ctx.request_id
        client_id = ctx.client_id

        return str(x)
    ```

    The context parameter name can be anything as long as it's annotated with Context.
    The context is optional - tools that don't need it can omit the parameter.
    """

    _request_context: RequestContext[ServerSessionT, LifespanContextT] | None
    _mcpengine: MCPEngine | None

    def __init__(
        self,
        *,
        request_context: RequestContext[ServerSessionT, LifespanContextT] | None = None,
        mcpengine: MCPEngine | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._request_context = request_context
        self._mcpengine = mcpengine

    @property
    def mcpengine(self) -> MCPEngine:
        """Access to the MCPEngine server."""
        if self._mcpengine is None:
            raise ValueError("Context is not available outside of a request")
        return self._mcpengine

    @property
    def request_context(self) -> RequestContext[ServerSessionT, LifespanContextT]:
        """Access to the underlying request context."""
        if self._request_context is None:
            raise ValueError("Context is not available outside of a request")
        return self._request_context

    async def report_progress(
        self, progress: float, total: float | None = None
    ) -> None:
        """Report progress for the current operation.

        Args:
            progress: Current progress value e.g. 24
            total: Optional total value e.g. 100
        """

        progress_token = (
            self.request_context.meta.progressToken
            if self.request_context.meta
            else None
        )

        if progress_token is None:
            return

        await self.request_context.session.send_progress_notification(
            progress_token=progress_token, progress=progress, total=total
        )

    async def read_resource(self, uri: str | AnyUrl) -> Iterable[ReadResourceContents]:
        """Read a resource by URI.

        Args:
            uri: Resource URI to read

        Returns:
            The resource content as either text or bytes
        """
        assert self._mcpengine is not None, (
            "Context is not available outside of a request"
        )
        return await self._mcpengine.read_resource(uri)

    async def log(
        self,
        level: Literal["debug", "info", "warning", "error"],
        message: str,
        *,
        logger_name: str | None = None,
    ) -> None:
        """Send a log message to the client.

        Args:
            level: Log level (debug, info, warning, error)
            message: Log message
            logger_name: Optional logger name
            **extra: Additional structured data to include
        """
        await self.request_context.session.send_log_message(
            level=level, data=message, logger=logger_name
        )

    @property
    def client_id(self) -> str | None:
        """Get the client ID if available."""
        return (
            getattr(self.request_context.meta, "client_id", None)
            if self.request_context.meta
            else None
        )

    @property
    def request_id(self) -> str:
        """Get the unique ID for this request."""
        return str(self.request_context.request_id)

    @property
    def user_id(self) -> str:
        return str(self.request_context.user_id)

    @property
    def user_name(self) -> str:
        return str(self.request_context.user_name)

    @property
    def session(self):
        """Access to the underlying session for advanced usage."""
        return self.request_context.session

    # Convenience methods for common log levels
    async def debug(self, message: str, **extra: Any) -> None:
        """Send a debug log message."""
        await self.log("debug", message, **extra)

    async def info(self, message: str, **extra: Any) -> None:
        """Send an info log message."""
        await self.log("info", message, **extra)

    async def warning(self, message: str, **extra: Any) -> None:
        """Send a warning log message."""
        await self.log("warning", message, **extra)

    async def error(self, message: str, **extra: Any) -> None:
        """Send an error log message."""
        await self.log("error", message, **extra)
