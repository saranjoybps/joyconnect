"""Supabase JWT verification.

Uses the project's JWKS (asymmetric signing keys, recommended by Supabase)
unless SUPABASE_JWT_SECRET is set, in which case legacy HS256 is accepted too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings

ASYMMETRIC_ALGS = ["ES256", "RS256"]
AUDIENCE = "authenticated"


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    claims: dict[str, Any]


_jwk_clients: dict[str, jwt.PyJWKClient] = {}


def _jwk_client(settings: Settings) -> jwt.PyJWKClient:
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    if url not in _jwk_clients:
        _jwk_clients[url] = jwt.PyJWKClient(url, cache_keys=True, lifespan=600)
    return _jwk_clients[url]


def verify_supabase_jwt(token: str, settings: Settings) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise jwt.InvalidTokenError("HS256 tokens not accepted")
            return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience=AUDIENCE)
        if alg not in ASYMMETRIC_ALGS:
            raise jwt.InvalidTokenError("unsupported alg")
        key = _jwk_client(settings).get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=[alg], audience=AUDIENCE)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc


def get_current_user(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> CurrentUser:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    claims = verify_supabase_jwt(token, settings)
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return CurrentUser(id=sub, email=claims.get("email"), claims=claims)


UserDep = Annotated[CurrentUser, Depends(get_current_user)]
