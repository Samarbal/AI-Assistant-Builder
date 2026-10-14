from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


@dataclass(frozen=True)
class OwnerContext:
    owner_id: UUID


class AuthVerifier(Protocol):
    def verify(self, authorization: str) -> OwnerContext:
        """Validate a Supabase Auth session and return its user UUID."""


class InvalidAuthentication(Exception):
    pass


class AuthenticationUnavailable(Exception):
    pass


class SupabaseAuthVerifier:
    """Validates bearer sessions through Supabase Auth's user endpoint."""

    def __init__(self, supabase_url: str, anon_key: str, client: httpx.Client | None = None):
        self.user_url = f"{supabase_url.rstrip('/')}/auth/v1/user"
        self.anon_key = anon_key
        self.client = client or httpx.Client(timeout=5.0)

    def verify(self, authorization: str) -> OwnerContext:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise InvalidAuthentication()
        try:
            response = self.client.get(
                self.user_url,
                headers={"Authorization": f"Bearer {parts[1]}", "apikey": self.anon_key},
            )
        except httpx.RequestError as exc:
            raise AuthenticationUnavailable() from exc
        if response.status_code in (401, 403):
            raise InvalidAuthentication()
        if response.status_code != 200:
            raise AuthenticationUnavailable()
        try:
            return OwnerContext(owner_id=UUID(response.json()["id"]))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AuthenticationUnavailable() from exc


def get_current_owner(
    request: Request,
    authorization: str | None = Header(default=None, include_in_schema=False),
    swagger_bearer: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
) -> OwnerContext:
    verifier: AuthVerifier | None = getattr(request.app.state, "auth_verifier", None)
    if authorization is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    if verifier is None:
        raise HTTPException(503, "Authentication service unavailable")
    try:
        return verifier.verify(authorization)
    except InvalidAuthentication as exc:
        raise HTTPException(401, "Invalid authentication", headers={"WWW-Authenticate": "Bearer"}) from exc
    except AuthenticationUnavailable as exc:
        raise HTTPException(503, "Authentication service unavailable") from exc


CurrentOwner = Depends(get_current_owner)
