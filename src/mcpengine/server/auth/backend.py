# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

"""Backend authorization strategies"""

from __future__ import annotations as _annotations

import json
from typing import Any, Protocol

import jwt
from jwt import InvalidTokenError
from starlette.requests import Request
from starlette.responses import Response

import mcpengine
from mcpengine.server.auth.context import UserContext
from mcpengine.server.auth.errors import AuthenticationError, AuthorizationError
from mcpengine.server.auth.providers.config import IdpConfig
from mcpengine.server.mcpengine.utilities.logging import get_logger
from mcpengine.types import JSONRPCMessage

logger = get_logger(__name__)


# TODO: Not Any
def get_auth_backend(
    settings: Any, scopes: set[str], scopes_mapping: dict[str, set[str]]
) -> AuthenticationBackend:
    if not settings.idp_config:
        return NoAuthBackend()

    return BearerTokenBackend(
        idp_config=settings.idp_config,
        scopes_mapping=scopes_mapping,
        scopes=scopes,
    )


class AuthenticationBackend(Protocol):
    async def authenticate(
        self,
        request: Request,
        message: JSONRPCMessage,
    ) -> None: ...

    def on_error(self, err: Exception) -> Response: ...


class NoAuthBackend(AuthenticationBackend):
    def __init__(self):
        pass

    async def authenticate(
        self,
        request: Request,
        message: JSONRPCMessage,
    ) -> None:
        return None

    def on_error(self, err: Exception) -> Response:
        # This should never be called, since we never raise an error.
        return Response(status_code=500, content="Unexpected error")


class BearerTokenBackend(AuthenticationBackend):
    # TODO: Better way of doing this
    METHODS_CHECK: set[str] = {
        "tools/call",
        "resources/read",
        "prompts/get",
    }

    idp_config: IdpConfig
    application_scopes: set[str]
    scopes_mapping: dict[str, set[str]]

    def __init__(
        self,
        idp_config: IdpConfig,
        scopes: set[str],
        scopes_mapping: dict[str, set[str]],
    ) -> None:
        self.idp_config = idp_config
        self.application_scopes = scopes
        self.scopes_mapping = scopes_mapping

    def on_error(self, err: Exception) -> Response:
        scopes = self.application_scopes

        # It's an error to have an empty scopes parameter in an OAuth flow.
        # In the case the application doesn't request any, we include the
        # "openid" scope, which is the most minimal scope for OIDC there is
        # (and most OAuth IdPs should also support it).
        if len(scopes) == 0:
            scopes = ["openid"]
        bearer = f'Bearer scope="{" ".join(scopes)}"'

        if isinstance(err, AuthorizationError):
            status_code = 403
        else:
            status_code = 401
        return Response(
            status_code=status_code,
            content=str(err),
            headers={"WWW-Authenticate": bearer},
        )

    async def authenticate(
        self,
        request: Request,
        message: JSONRPCMessage,
    ) -> None:
        if not isinstance(message.root, mcpengine.JSONRPCRequest):
            return None
        req_message = message.root

        if req_message.method not in self.METHODS_CHECK:
            return None

        try:
            token = self._get_bearer_token(request)
            decoded_token = await self._decode_token(token)
            self._validate_scopes(req_message, decoded_token)

            # Set UserContext to be pulled into Context on the
            # handler later.
            if req_message.params is None:
                req_message.params = {}
            req_message.params["user_context"] = UserContext(
                name=decoded_token.get("name", None),
                email=decoded_token.get("email", None),
                sid=decoded_token.get("sid", None),
                token=token,
            )
        except (AuthenticationError, AuthorizationError) as e:
            raise e
        except Exception as err:
            raise AuthenticationError("Invalid credentials") from err

    async def _decode_token(self, token: str) -> Any:
        # First, try to see if it's a JWT, and decode it.
        try:
            jwks = await self.idp_config.get_jwks()
            decoded_token = self.validate_token(jwks, token)
            return decoded_token
        except Exception:
            pass

        # If not, try the token introspection endpoint (as defined by RFC 7662)
        try:
            result = await self.idp_config.validate_token(token)
            return result
        except Exception:
            pass

        raise AuthenticationError("Could not verify token")

    def _validate_scopes(self, message: mcpengine.JSONRPCRequest, decoded_token: Any):
        decoded_scopes = decoded_token.get("scope", None)
        scopes: set[str] = set()
        if decoded_scopes is not None:
            scopes = set(decoded_scopes.split(" "))

        needed_scopes: set[str] = set()
        if message.params and "name" in message.params:
            needed_scopes = self.scopes_mapping.get(message.params["name"], set())
        if needed_scopes.difference(scopes):
            raise AuthorizationError(
                f"Invalid auth scopes, needed: {needed_scopes}, received: {scopes}"
            )

    @staticmethod
    def _get_bearer_token(request: Request):
        auth = request.headers.get("Authorization", None)
        if auth is None:
            raise AuthenticationError("No valid auth header")

        scheme, token = auth.split()
        if scheme.lower() != "bearer":
            raise AuthenticationError(f'Invalid auth schema "{scheme}", must be Bearer')
        return token

    @staticmethod
    def validate_token(jwks: list[dict[str, object]], token: str) -> Any:
        try:
            header = jwt.get_unverified_header(token)
        except Exception as e:
            raise InvalidTokenError(f"Error decoding token header: {str(e)}")

        # Get the key id from header
        kid = header.get("kid")
        if not kid:
            raise InvalidTokenError("Token header missing 'kid' claim")

        # Find the matching key in the JWKS
        rsa_key = None
        for key in jwks:
            if key.get("kid") == kid:
                rsa_key = key
                break

        if not rsa_key:
            raise KeyError(f"No matching key found for kid: {kid}")

        # Needed to satisfy the type checker.
        # If this is not None (which we check above), then this field
        # will have the name of the algorithm used for the key.
        algorithm = str(rsa_key["alg"])

        # Prepare the public key for verification
        try:
            # Convert the JWK to a format PyJWT can use
            public_key = jwt.get_algorithm_by_name(algorithm).from_jwk(
                json.dumps(rsa_key)
            )
        except Exception as e:
            raise InvalidTokenError(f"Error preparing public key: {str(e)}")

        payload = jwt.decode(
            token,
            public_key,
            algorithms=algorithm,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": False,
                "verify_iat": True,
                "verify_iss": True,
                "require": ["exp", "iat", "iss"],
            },
        )
        return payload
