"""Backend authorization strategies"""
from __future__ import annotations as _annotations

import json
from typing import Optional, Tuple
from urllib.parse import urljoin

import httpx
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
from pydantic.networks import HttpUrl
from starlette.authentication import AuthenticationError, AuthenticationBackend, AuthCredentials, BaseUser
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection
from starlette.responses import Response

from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

OPENID_WELL_KNOWN_PATH: str = ".well-known/openid-configuration"
OAUTH_WELL_KNOWN_PATH: str = ".well-known/oauth-authorization-server"


def on_error(_: HTTPConnection, err: AuthenticationError) -> Response:
    return Response(
        content=str(err),
        status_code=401,
    )


def validate_token(jwks: list, token: str) -> None:
    try:
        header = jwt.get_unverified_header(token)
    except Exception as e:
        raise Exception(f"Error decoding token header: {str(e)}")

    # Get the key id from header
    kid = header.get('kid')
    if not kid:
        raise Exception("Token header missing 'kid' claim")

    # Find the matching key in the JWKS
    rsa_key = None
    for key in jwks:
        if key.get('kid') == kid:
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
                # TODO: Re-enable once we figure out how to handle this.
                # "verify_aud": True,
                "verify_iat": True,
                # TODO: Re-enable once we figure out how to handle this.
                # "verify_iss": True,
                "require": ["exp", "iat", "iss", "aud"]  # Required claims
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


class BearerTokenBackend(AuthenticationBackend):
    issuer_url: HttpUrl

    def __init__(self, issuer_url: HttpUrl):
        self.issuer_url = issuer_url

    def as_middleware(self) -> Middleware:
        return Middleware(AuthenticationMiddleware, backend=self, on_error=on_error)

    async def authenticate(
            self, conn: HTTPConnection
    ) -> Optional[Tuple[AuthCredentials, BaseUser]]:
        auth = conn.headers.get("Authorization", None)
        if auth is None:
            raise AuthenticationError('No valid auth header')

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
                    raise AuthenticationError(f'Invalid auth schema "{scheme}", must be Bearer')
                validate_token(jwks_keys, token)
            except Exception as err:
                raise AuthenticationError("Invalid bearer auth credentials") from err
