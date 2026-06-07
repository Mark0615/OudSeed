"""Minimal, testable Google OAuth client for sign-in.

Hand-rolled (no heavy OAuth lib) so the network calls sit behind small methods
that tests can fake. Used for the product's own login; ad-platform connect
(Meta / Google Ads) is added in later slices.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

# Scopes for signing in to the product (identity only).
GOOGLE_SIGNIN_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)


@dataclass(frozen=True)
class GoogleUser:
    """Identity returned by Google's userinfo endpoint."""

    sub: str
    email: str
    name: str | None = None


class GoogleOAuthClient:
    """Builds the auth URL and exchanges codes for Google identity."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        scopes: tuple[str, ...] = GOOGLE_SIGNIN_SCOPES,
        timeout: float = 15.0,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.timeout = timeout

    def authorization_url(self, state: str) -> str:
        """Return the Google consent URL to redirect the user to."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }
        return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Exchange an authorization code for tokens."""
        response = httpx.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch_userinfo(self, access_token: str) -> GoogleUser:
        """Fetch the signed-in user's identity from Google."""
        response = httpx.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        sub = data.get("sub")
        email = data.get("email")
        if not sub or not email:
            raise ValueError("Google userinfo missing 'sub' or 'email'.")
        return GoogleUser(sub=sub, email=email, name=data.get("name"))
