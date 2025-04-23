# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.
from typing import Any

import httpx

from mcpengine.server.auth.providers.config import IdpConfig

ISSUER_URL = "https://accounts.google.com"
TOKEN_VALIDATION_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"


class GoogleIdpConfig(IdpConfig):
    def __init__(self):
        super().__init__(ISSUER_URL)

    async def validate_token(self, token: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                str(TOKEN_VALIDATION_ENDPOINT), params={"access_token": token}
            )
            return response.json()
