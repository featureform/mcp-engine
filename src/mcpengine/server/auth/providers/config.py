# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.
from typing import Any
from urllib.parse import urljoin

import httpx
from async_lru import alru_cache

OPENID_WELL_KNOWN_PATH: str = ".well-known/openid-configuration"
OAUTH_WELL_KNOWN_PATH: str = ".well-known/oauth-authorization-server"

METADATA_CACHE_TTL = 300  # in seconds


class IdpConfig:
    issuer_url: str
    token_validation_endpoint: str | None

    def __init__(self, issuer_url: str, token_validation_endpoint: str | None = None):
        super().__init__()
        self.issuer_url = issuer_url
        self.token_validation_endpoint = token_validation_endpoint

    @alru_cache(ttl=METADATA_CACHE_TTL)
    async def get_metadata(self) -> Any:
        endpoints = [OPENID_WELL_KNOWN_PATH, OAUTH_WELL_KNOWN_PATH]
        issuer_url = str(self.issuer_url).rstrip("/") + "/"

        async with httpx.AsyncClient() as client:
            for endpoint in endpoints:
                well_known_url = urljoin(issuer_url, endpoint)
                response = await client.get(well_known_url)

                if response.status_code >= 400:
                    continue

                return response.json()

    @alru_cache(ttl=METADATA_CACHE_TTL)
    async def get_jwks(self) -> Any:
        metadata = await self.get_metadata()
        async with httpx.AsyncClient() as client:
            jwks_url = metadata["jwks_uri"]
            response = await client.get(jwks_url)
            jwks_keys = response.json()["keys"]

            return jwks_keys

    async def validate_token(self, token: str) -> dict[str, Any]:
        raise NotImplementedError()
