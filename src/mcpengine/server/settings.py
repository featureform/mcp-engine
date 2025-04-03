# Copyright (c) 2024 Anthropic, PBC
# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

from __future__ import annotations as _annotations

from collections.abc import Callable
from contextlib import (
    AbstractAsyncContextManager,
)
from typing import Any, Generic, Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcpengine.server.lowlevel.server import LifespanResultT


class Settings(BaseSettings, Generic[LifespanResultT]):
    """MCPEngine server settings.

    All settings can be configured via environment variables with the prefix MCPENGINE_.
    For example, MCPENGINE_DEBUG=true will set debug=True.
    """

    model_config = SettingsConfigDict(
        env_prefix="MCPENGINE_",
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

    lifespan: Callable[[Any], AbstractAsyncContextManager[LifespanResultT]] | None = (
        Field(None, description="Lifespan context manager")
    )

    # auth settings
    authentication_enabled: bool = Field(
        False, description="Enable authentication and authorization for the application"
    )
    issuer_url: HttpUrl | None = Field(
        None, description="Url of the issuer, which will be used as the root url"
    )
