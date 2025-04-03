# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

"""Backend authorization strategies"""

from __future__ import annotations as _annotations

import json
from typing import Any, Protocol
from urllib.parse import urljoin

import httpx
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from pydantic.networks import HttpUrl
from starlette.authentication import (
    AuthCredentials,
    AuthenticationError,
    BaseUser,
    SimpleUser,
)
from starlette.responses import Response

import mcpengine
from mcpengine.server.auth.context import UserContext
from mcpengine.server.mcpengine.utilities.logging import get_logger
from mcpengine.types import JSONRPCMessage, Request

logger = get_logger(__name__)

OPENID_WELL_KNOWN_PATH: str = ".well-known/openid-configuration"
OAUTH_WELL_KNOWN_PATH: str = ".well-known/oauth-authorization-server"


# TODO: Not Any
def get_auth_backend(
    settings: Any, scopes: set[str], scopes_mapping: dict[str, set(str)]
) -> AuthenticationBackend:
    if not settings.authentication_enabled:
        return NoAuthBackend()

    return BearerTokenBackend(
        issuer_url=settings.issuer_url,
        scopes_mapping=scopes_mapping,
        scopes=scopes,
    )


def validate_token(jwks: list, token: str) -> Any:
    try:
        header = jwt.get_unverified_header(token)
    except Exception as e:
        raise Exception(f"Error decoding token header: {str(e)}")

    # Get the key id from header
    kid = header.get("kid")
    if not kid:
        raise Exception("Token header missing 'kid' claim")

    # Find the matching key in the JWKS
    rsa_key = None
    for key in jwks:
        if key.get("kid") == kid:
            rsa_key = key
            break

    if not rsa_key:
        raise Exception(f"No matching key found for kid: {kid}")

    # Prepare the public key for verification
    try:
        # Convert the JWK to a format PyJWT can use
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(rsa_key))
    except Exception as e:
        raise Exception(f"Error preparing public key: {str(e)}")

    # Verify and decode the token
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],  # Adjust if your IdP uses a different algorithm
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": False,
                "verify_iat": True,
                "verify_iss": True,
                "require": ["exp", "iat", "iss"],  # , "aud"]  # Required claims
            },
            # audience="",  # Replace with your client ID
            # issuer=""  # Replace with your IdP's issuer URL
        )
        return payload

    except ExpiredSignatureError:
        raise Exception("Token has expired")
    except InvalidTokenError as e:
        raise Exception(f"Invalid token: {str(e)}")
    except Exception as e:
        raise Exception(f"Error validating token: {str(e)}")


class AuthenticationBackend(Protocol):
    async def authenticate(
        self,
        request: Request,
        message: JSONRPCMessage,
    ) -> AuthCredentials | BaseUser | None: ...

    def on_error(self, err: Exception) -> Response: ...


class NoAuthBackend(AuthenticationBackend):
    def __init__(self):
        pass

    async def authenticate(
        self,
        request: Request,
        message: JSONRPCMessage,
    ) -> AuthCredentials | BaseUser | None:
        pass

    def on_error(self, err: Exception) -> Response:
        # This should never be called, since we never raise an error.
        pass


class BearerTokenBackend(AuthenticationBackend):
    # TODO: Better way of doing this
    METHODS_CHECK: set[str] = {
        "tools/call",
        "resources/read",
        "prompts/get",
    }

    issuer_url: HttpUrl
    application_scopes: set[str]
    scopes_mapping: dict[str, set[str]]

    def __init__(
        self, issuer_url: HttpUrl, scopes: set[str], scopes_mapping: dict[str, set[str]]
    ) -> None:
        self.issuer_url = issuer_url
        self.application_scopes = scopes
        self.scopes_mapping = scopes_mapping

    def on_error(self, err: Exception) -> Response:
        bearer = f'Bearer scope="{" ".join(self.application_scopes)}"'
        return Response(
            status_code=401,
            content=str(err),
            headers={"WWW-Authenticate": bearer},
        )

    async def authenticate(
        self,
        request: Request,
        message: JSONRPCMessage,
    ) -> AuthCredentials | BaseUser | None:
        if not isinstance(message.root, mcpengine.JSONRPCRequest):
            pass
        message = message.root

        if message.method not in self.METHODS_CHECK:
            return None

        auth = request.headers.get("Authorization", None)
        if auth is None:
            raise AuthenticationError("No valid auth header")

        # TODO: Cache this stuff
        async with httpx.AsyncClient() as client:
            issuer_url = str(self.issuer_url).rstrip("/") + "/"
            well_known_url = urljoin(issuer_url, OAUTH_WELL_KNOWN_PATH)
            response = await client.get(well_known_url)

            jwks_url = response.json()["jwks_uri"]
            response = await client.get(jwks_url)
            jwks_keys = response.json()["keys"]
            try:
                scheme, token = auth.split()
                if scheme.lower() != "bearer":
                    raise AuthenticationError(
                        f'Invalid auth schema "{scheme}", must be Bearer'
                    )
                decoded_token = validate_token(jwks_keys, token)

                scopes = decoded_token.get("scope", set())
                if scopes != "":
                    scopes = set(scopes.split(" "))

                needed_scopes = self.scopes_mapping.get(message.params["name"], set())
                if needed_scopes.difference(scopes):
                    raise AuthenticationError(
                        f"Invalid auth scopes, needed: {needed_scopes}, "
                        f"received: {scopes}"
                    )

                message.params["user_context"] = UserContext(
                    name=decoded_token.get("name", None),
                    email=decoded_token.get("email", None),
                    sid=decoded_token.get("sid", None),
                )

                sub = decoded_token["sub"]
                return (
                    AuthCredentials(list(scopes)),
                    SimpleUser(sub),
                )
            except Exception as err:
                raise AuthenticationError("Invalid credentials") from err
