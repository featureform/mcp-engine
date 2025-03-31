"""Backend authorization strategies"""
from __future__ import annotations as _annotations

from typing import Optional, Tuple

from starlette.authentication import AuthenticationError, AuthenticationBackend, AuthCredentials, BaseUser
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection
from starlette.responses import Response

from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


def on_error(_: HTTPConnection, err: AuthenticationError) -> Response:
    return Response(
        content=str(err),
        status_code=401,
    )


class BearerTokenBackend(AuthenticationBackend):
    @classmethod
    def as_middleware(cls) -> Middleware:
        return Middleware(AuthenticationMiddleware, backend=cls(), on_error=on_error)

    async def authenticate(
            self, conn: HTTPConnection
    ) -> Optional[Tuple[AuthCredentials, BaseUser]]:
        auth = conn.headers.get("Authorization", None)
        if auth is None:
            raise AuthenticationError('No valid auth header')

        try:
            scheme, token = auth.split()
            if scheme.lower() != "bearer":
                raise AuthenticationError(f'Invalid auth schema "{scheme}", must be Bearer')
            print(f'Received auth token {token}')
        except ValueError as err:
            raise AuthenticationError("Invalid basic auth credentials") from err
