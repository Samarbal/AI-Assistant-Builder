from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, Request, status


@dataclass(frozen=True)
class OwnerContext:
    owner_id: UUID


class AuthVerifier(Protocol):
    def verify(self, authorization: str) -> OwnerContext:
        """Validate a Supabase Auth session and return its user UUID."""


class SupabaseAuthVerifier:
    """Validates bearer sessions through Supabase Auth's user endpoint."""

    def __init__(self, supabase_url: str, anon_key: str, client: httpx.Client | None = None):
        self.user_url = f"{supabase_url.rstrip('/')}/auth/v1/user"
        self.anon_key = anon_key
        self.client = client or httpx.Client(timeout=5.0)

    def verify(self, authorization: str) -> OwnerContext:
        if not authorization.lower().startswith("bearer "):
            raise ValueError("Bearer authorization required")
        response = self.client.get(
            self.user_url,
            headers={"Authorization": authorization, "apikey": self.anon_key},
        )
        if response.status_code != 200:
            raise ValueError("Supabase session rejected")
        user_id = response.json().get("id")
        return OwnerContext(owner_id=UUID(user_id))


def get_current_owner(
    request: Request,
    authorization: str | None = Header(default=None),
) -> OwnerContext:
    verifier: AuthVerifier | None = getattr(request.app.state, "auth_verifier", None)
    if verifier is None or authorization is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        return verifier.verify(authorization)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication") from exc


CurrentOwner = Depends(get_current_owner)
