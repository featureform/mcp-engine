"""FastMCP - A more ergonomic interface for MCP servers."""

from __future__ import annotations as _annotations

from collections.abc import Callable
from contextlib import (
    AbstractAsyncContextManager,
)
from typing import Generic, Literal

from pydantic import Field
from pydantic.networks import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.lowlevel.server import LifespanResultT

logger = get_logger(__name__)


class Settings(BaseSettings, Generic[LifespanResultT]):
    """FastMCP server settings.

    All settings can be configured via environment variables with the prefix FASTMCP_.
    For example, FASTMCP_DEBUG=true will set debug=True.
    """

    model_config = SettingsConfigDict(
        env_prefix="FASTMCP_",
        env_file=".env",
        extra="ignore",
    )

    # Server settings
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # HTTP settings
    host: str = "0.0.0.0"
    port: int = 8000
    sse_path: str = "/sse"
    message_path: str = "/messages/"

    # resource settings
    warn_on_duplicate_resources: bool = True

    # tool settings
    warn_on_duplicate_tools: bool = True

    # prompt settings
    warn_on_duplicate_prompts: bool = True

    dependencies: list[str] = Field(
        default_factory=list,
        description="List of dependencies to install in the server environment",
    )

    lifespan: (
            Callable[["FastMCP"], AbstractAsyncContextManager[LifespanResultT]] | None
    ) = Field(None, description="Lifespan context manager")

    # auth settings
    authentication_enabled: bool = Field(False,
                                         description="Enable authentication and authorization for the application")
    issuer_url: HttpUrl | None = Field(None, description="Url of the issuer, which will be used as the root url")
