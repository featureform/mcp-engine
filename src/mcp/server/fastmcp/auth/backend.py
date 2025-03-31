"""Backend authorization strategies"""
from __future__ import annotations as _annotations

import json
from typing import Optional, Tuple

import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError
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


jwks_keys = [
    {
        "kid": "pfttmB3ZK5pNOlQLKfNPB3NnGgihK89E10PhsjyZo-g",
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "x5c": [
            "MIICnTCCAYUCBgGV5NFUzzANBgkqhkiG9w0BAQsFADASMRAwDgYDVQQDDAd0ZXN0aW5nMB4XDTI1MDMzMDAyMDkzOFoXDTM1MDMzMDAyMTExOFowEjEQMA4GA1UEAwwHdGVzdGluZzCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALvLFQZ+ciQq4Ph3YQ0SG5shlzIUA+vmhUGUN5zWELclO6z7fE54ijvv3oKzdPjZCSRxDtsLBlWMbO6XkNLlLMysgBKHD54w/vTsj4wQ9emEsi1FNikDYHtv9eJCyr8wSOlsdJkmvupuVVRSJQh7HikUNBG0JAQTnXn2DtHOEntPyQ9FYmb6LObV1z/4pkaksSCKQfCeJ1LYSZuJc3MgIKqcPLHvDNuEHzePTKbSDiMRvHKtx0MYv67VeL3CgWHw3+1z1pK9mEVXTC+3Xb0d11PS82RTcbwDuJhEgJcvMtacIt0zbyrIqDg89a3lIVkzbNguhHkW3fNF6nbQa93ZxT8CAwEAATANBgkqhkiG9w0BAQsFAAOCAQEAYIe/2VMkIoFmO+0va5t4QV0MY1LstjAtGgYfUiXSxazOmxwFAATDfPodUfAmR62k0O7zGn0SkqRLizISvRjvwohluobFwTJrH8MNHCJ2Qb+S49hdHdug3muMMC+SVGY8vsPlyDmNriXlPOXMS1Y3a4E4x/Hnbh0AuvBzcAAqU5nfN/jgOW/FTPLAAlCweyzq9nnV/K98eSnK4rgqw3g53NnmxDzJ7iUsNbb+1K23LeQ0Q11B2lAOV2slBitrvBbz8KwqraRAbWCrcaMrlS9ipjkPpEl+4k9DPI+7wxH1CZXfvCpMs/sy3ubFyLoQe8+EU2xHE0B8c/ctYheSa6ZqmQ=="
        ],
        "x5t": "PjUIp2VdQG8lS-3o3k_q_k2OtVo",
        "x5t#S256": "ctp3ewSRWJgmHg8tpBriDZrraLRSMiZUggJSYUE0Pls",
        "n": "u8sVBn5yJCrg-HdhDRIbmyGXMhQD6-aFQZQ3nNYQtyU7rPt8TniKO-_egrN0-NkJJHEO2wsGVYxs7peQ0uUszKyAEocPnjD-9OyPjBD16YSyLUU2KQNge2_14kLKvzBI6Wx0mSa-6m5VVFIlCHseKRQ0EbQkBBOdefYO0c4Se0_JD0ViZvos5tXXP_imRqSxIIpB8J4nUthJm4lzcyAgqpw8se8M24QfN49MptIOIxG8cq3HQxi_rtV4vcKBYfDf7XPWkr2YRVdML7ddvR3XU9LzZFNxvAO4mESAly8y1pwi3TNvKsioODz1reUhWTNs2C6EeRbd80XqdtBr3dnFPw",
        "e": "AQAB"
    },
    {
        "kid": "HRvSPn7VJENs6l12C2Deoe7kiPvEsKKhiDkE8rcVtQQ",
        "kty": "RSA",
        "alg": "RSA-OAEP",
        "use": "enc",
        "x5c": [
            "MIICnTCCAYUCBgGV5NFVeDANBgkqhkiG9w0BAQsFADASMRAwDgYDVQQDDAd0ZXN0aW5nMB4XDTI1MDMzMDAyMDkzOVoXDTM1MDMzMDAyMTExOVowEjEQMA4GA1UEAwwHdGVzdGluZzCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALXXPSFnV8RTnRk0YuxyENVNTnyJTzYacUQ2in6ZV1Y39SFKtFi2qWgU8jPsnYpq8fpQux29hP38Jp1h9SjNPzIqdtpOOACMjpHaktxfSEDzsGE2ArVJN/BCXG74QWwb4irvfkyILWBjaMdEtE/KTjrPzrSNDnDorhf3oIX/6dbXTeZpDNqBFZXvVYnIP8bpIuUlU066nHNBDPsJkWjvKFgoZ4XbVoVqBuuLsdD+uIyIl5Epf5GxHygimaQ4Pj99BNxDNR7rI+VtMfpgn2NkhATT1XksYCH1UfH7WQJWrhmphfodIPjkJio4GUsjTzpfJYUwGJFPlkJxtiKBfM2xHV0CAwEAATANBgkqhkiG9w0BAQsFAAOCAQEAi06K3IXLnq4c8Tefz/eX/7yasyMqe5TeuCN8tZXiI/uhn5xG0z2lmgDDptcH3URgG+9gqa4PrKCOxzVNBc5nTfGzYgW/P87VPMmnDjwbbS9/KQfsfbJxXyFA0XuGTdjYj9dgQ4rLoWNwfpC3YuPTMmMXtJQEWe8cwokLc90Frnyy6oHUGcIgZIFlTgsk4pAuuif2u4utJLVTCrd8e/jKYcSgeHLCkKyXrUAgJ5yrfBoZOvs4Ow2dsQfW8FxNZeOG6NDVvlJk2knNs5phvIyQ/+nnKRU+nk4JMX3V4/Sg1LSwGGM/Sz/ug4WIRabSLIQ8KzF06nHkKsG8joE7a+M+XQ=="
        ],
        "x5t": "2F5zoD8Gyhn3L2jpZ4v7EmV71QY",
        "x5t#S256": "MCowJywGvxSo5vTfasMhDkzTWzgOvmHbFfHBKTH1tR0",
        "n": "tdc9IWdXxFOdGTRi7HIQ1U1OfIlPNhpxRDaKfplXVjf1IUq0WLapaBTyM-ydimrx-lC7Hb2E_fwmnWH1KM0_Mip22k44AIyOkdqS3F9IQPOwYTYCtUk38EJcbvhBbBviKu9-TIgtYGNox0S0T8pOOs_OtI0OcOiuF_eghf_p1tdN5mkM2oEVle9Vicg_xuki5SVTTrqcc0EM-wmRaO8oWChnhdtWhWoG64ux0P64jIiXkSl_kbEfKCKZpDg-P30E3EM1Husj5W0x-mCfY2SEBNPVeSxgIfVR8ftZAlauGamF-h0g-OQmKjgZSyNPOl8lhTAYkU-WQnG2IoF8zbEdXQ",
        "e": "AQAB"
    }
]

token = "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJwZnR0bUIzWks1cE5PbFFMS2ZOUEIzTm5HZ2loSzg5RTEwUGhzanlaby1nIn0.eyJleHAiOjE3NDM0NTYzNTksImlhdCI6MTc0MzQ1NjA1OSwiYXV0aF90aW1lIjoxNzQzNDU0NTI4LCJqdGkiOiI2YmExMzRhMS0yZGEyLTQ3YzctYjc4OS1mOTkzM2EyZTg0ZmIiLCJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvcmVhbG1zL3Rlc3RpbmciLCJhdWQiOiJhY2NvdW50Iiwic3ViIjoiMGRhMGI2NTgtNTExOC00ODEyLWIwNmUtOWU3ZmFkZjRkODQ0IiwidHlwIjoiQmVhcmVyIiwiYXpwIjoiand0LWNsaWVudCIsInNpZCI6IjI2MTRlNTFiLTVmMGMtNDE0Yy1iMzZmLTQ0Y2M0MzkxODg3ZiIsImFjciI6IjAiLCJhbGxvd2VkLW9yaWdpbnMiOlsiaHR0cDovL2xvY2FsaG9zdCJdLCJyZWFsbV9hY2Nlc3MiOnsicm9sZXMiOlsiZGVmYXVsdC1yb2xlcy10ZXN0aW5nIiwib2ZmbGluZV9hY2Nlc3MiLCJ1bWFfYXV0aG9yaXphdGlvbiJdfSwicmVzb3VyY2VfYWNjZXNzIjp7ImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjpmYWxzZSwibmFtZSI6IkthbWFsIFNhZGVrIiwicHJlZmVycmVkX3VzZXJuYW1lIjoia2FtYWwiLCJnaXZlbl9uYW1lIjoiS2FtYWwiLCJmYW1pbHlfbmFtZSI6IlNhZGVrIiwiZW1haWwiOiJrYW1hbEBlbWFpbC5jb20ifQ.Fks21M0ABFrG07zQM7hIIhvIF0EgoPRmGCivw_-QCbrdFZk_hElqH9hYDTCEfJxaEPf83Y7l7KJRzJEKPcJwbB9ep8K4VMMsmJmE15jwZiFDowwVENNa5q2oxaAYEUe9Vu0kfi7yRDnmxCN1feySi4RmHj0sen59VgTrJaiZ0EVm4HBNAblNxzrpyOuk0ruqaVnruHXPnWaxYQsVON_kNkH0jEvRSiwSt3Et0CdEIklFpykzQMUDWfFyK0Zf9kQddoKlg2GGuo4eP5a7ZgOeRkLr4ty3pg2TNz4ywgOEEaIzGAUHK-tvsYGQusiL_JQz9nMUW8x_tUMl2elumYlkdA"


def validate_token(token: str) -> None:
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
    for key in jwks_keys:
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
            algorithms=['RS256'],  # Adjust if your IdP uses a different algorithm
            options={
                'verify_signature': True,
                'verify_exp': True,
                'verify_aud': True,
                'verify_iat': True,
                'verify_iss': True,
                'require': ['exp', 'iat', 'iss', 'aud']  # Required claims
            },
            audience="account",  # Replace with your client ID
            issuer="http://localhost:8080/realms/testing"  # Replace with your IdP's issuer URL
        )
        return payload

    except ExpiredSignatureError:
        raise Exception("Token has expired")
    except InvalidTokenError as e:
        raise Exception(f"Invalid token: {str(e)}")
    except Exception as e:
        raise Exception(f"Error validating token: {str(e)}")


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
            validate_token(token)
        except Exception as err:
            raise AuthenticationError("Invalid basic auth credentials") from err


if __name__ == '__main__':
    validate_token(token)
