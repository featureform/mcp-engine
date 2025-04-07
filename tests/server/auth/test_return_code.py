from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import HttpUrl

from mcpengine.server.auth.backend import BearerTokenBackend
from mcpengine.server.sse import SseServerTransport
from mcpengine.types import JSONRPCRequest


@pytest.fixture
def mock_bearer_token_backend():
    def _create_mock(application_scopes, scopes_mapping, token):
        backend = BearerTokenBackend(
            issuer_url=HttpUrl("http://some-issuer"),
            scopes=application_scopes,
            scopes_mapping=scopes_mapping,
        )

        backend._get_jwks = AsyncMock(return_value=None)

        validate_token_mock = MagicMock()
        validate_token_mock.return_value = token
        backend.validate_token = validate_token_mock

        return backend

    return _create_mock


@pytest.mark.anyio
async def test_unauthenticated_return_code(mock_bearer_token_backend):
    backend = mock_bearer_token_backend(
        application_scopes=[],
        scopes_mapping={},
        token=None,
    )
    transport = SseServerTransport(
        "",
        backend,
    )

    request = MagicMock()
    request.headers = {}

    message = MagicMock()
    message.root = JSONRPCRequest(
        jsonrpc="2.0",
        id="",
        method="tools/call",
        params={},
    )

    response = await transport.validate_auth(request, message)
    assert response.status_code == 401


@pytest.mark.anyio
async def test_unauthorized_return_code(mock_bearer_token_backend):
    backend = mock_bearer_token_backend(
        application_scopes=["example-scope"],
        scopes_mapping={
            "required-scope": {"example-scope"},
            "no-scopes-required": set(),
        },
        token={
            "scope": "",
        },
    )
    transport = SseServerTransport(
        "",
        backend,
    )

    request = MagicMock()
    request.headers = {"Authorization": 'Bearer "hello_world"'}

    message = MagicMock()
    message.root = JSONRPCRequest(
        jsonrpc="2.0",
        id="",
        method="tools/call",
        params={"name": "no-scopes-required"},
    )

    response = await transport.validate_auth(request, message)
    assert response is None

    message = MagicMock()
    message.root = JSONRPCRequest(
        jsonrpc="2.0",
        id="",
        method="tools/call",
        params={"name": "required-scope"},
    )
    response = await transport.validate_auth(request, message)
    assert response.status_code == 403
