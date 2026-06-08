"""Ad-platform OAuth connect clients (Meta Ads, Google Ads).

Each client exposes:
- ``authorization_url(state)`` — where to send the user to authorize, and
- ``fetch_connection(code)`` — exchange the code, then list the ad accounts the
  authorization grants, returning the long-lived secret to store plus accounts.

The network calls live in ``fetch_connection`` so tests can fake the whole step.
The returned ``secret`` is what we encrypt into ``platform_connections`` (Meta:
a long-lived user token; Google Ads: a refresh token).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx

META_API_VERSION = "v21.0"
META_AUTH_ENDPOINT = f"https://www.facebook.com/{META_API_VERSION}/dialog/oauth"
META_TOKEN_ENDPOINT = f"https://graph.facebook.com/{META_API_VERSION}/oauth/access_token"
META_ADACCOUNTS_ENDPOINT = f"https://graph.facebook.com/{META_API_VERSION}/me/adaccounts"

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
# Google Ads API versions sunset roughly yearly; calling a sunset version 404s.
# This default is the current major as of mid-2026; override via the
# GOOGLE_ADS_API_VERSION env var when Google deprecates it (no code change needed).
GOOGLE_ADS_API_VERSION = "v21"


def google_ads_list_customers_endpoint(api_version: str) -> str:
    """Build the listAccessibleCustomers REST endpoint for an API version."""
    return f"https://googleads.googleapis.com/{api_version}/customers:listAccessibleCustomers"


def google_ads_search_endpoint(api_version: str, customer_id: str) -> str:
    """Build the GAQL search endpoint for one customer and API version."""
    return f"https://googleads.googleapis.com/{api_version}/customers/{customer_id}/googleAds:search"


# GAQL to read a customer's human-readable name (for "{name} | {id}" labels).
GOOGLE_ADS_CUSTOMER_NAME_QUERY = (
    "SELECT customer.id, customer.descriptive_name FROM customer LIMIT 1"
)


def format_google_ads_account_name(customer_id: str, descriptive_name: str | None) -> str:
    """Label a Google Ads account as ``{name} | {id}``, or fall back to the id.

    Falls back to ``Google Ads {id}`` when the descriptive name is unavailable
    (e.g. the account hides it or the name lookup failed) so connect never breaks.
    """
    name = (descriptive_name or "").strip()
    return f"{name} | {customer_id}" if name else f"Google Ads {customer_id}"


META_SCOPES = ("ads_read",)
GOOGLE_ADS_SCOPES = ("https://www.googleapis.com/auth/adwords",)


def summarize_oauth_http_error(exc: httpx.HTTPStatusError) -> str:
    """Extract a short, secret-free message from a provider OAuth/API error.

    Handles the common error shapes: OAuth token endpoints
    (``{"error": "...", "error_description": "..."}``) and the Graph / Google Ads
    APIs (``{"error": {"status"/"type": ..., "message": ...}}``). Only provider
    error codes/messages are returned — never tokens or request payloads.
    """
    resp = exc.response
    try:
        data = resp.json()
    except Exception:
        return f"HTTP {resp.status_code}"
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, str):  # OAuth token endpoint
        desc = data.get("error_description")
        return f"{err}: {desc}" if desc else err
    if isinstance(err, dict):  # Graph / Google Ads API
        status = err.get("status") or err.get("type") or ""
        message = err.get("message") or ""
        joined = " — ".join(str(p) for p in (status, message) if p)
        return joined or f"HTTP {resp.status_code}"
    return f"HTTP {resp.status_code}"


@dataclass(frozen=True)
class AdAccount:
    """An ad account the authorization can access."""

    external_account_id: str
    account_name: str | None = None


@dataclass(frozen=True)
class AdConnectionResult:
    """Outcome of an ad-platform authorization."""

    secret: str  # long-lived token to encrypt and store
    accounts: list[AdAccount] = field(default_factory=list)
    scopes: str | None = None


class MetaAdsOAuthClient:
    """Meta (Facebook) Ads OAuth connect."""

    platform = "meta_ads"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
        *,
        scopes: tuple[str, ...] = META_SCOPES,
        timeout: float = 20.0,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.timeout = timeout

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": ",".join(self.scopes),
        }
        return f"{META_AUTH_ENDPOINT}?{urlencode(params)}"

    def fetch_connection(self, code: str) -> AdConnectionResult:
        short_token = self._exchange_code(code)
        long_token = self._exchange_for_long_lived(short_token)
        accounts = self._list_ad_accounts(long_token)
        return AdConnectionResult(
            secret=long_token, accounts=accounts, scopes=",".join(self.scopes)
        )

    def _exchange_code(self, code: str) -> str:
        resp = httpx.get(
            META_TOKEN_ENDPOINT,
            params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _exchange_for_long_lived(self, short_token: str) -> str:
        resp = httpx.get(
            META_TOKEN_ENDPOINT,
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": short_token,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("access_token", short_token)

    def _list_ad_accounts(self, token: str) -> list[AdAccount]:
        resp = httpx.get(
            META_ADACCOUNTS_ENDPOINT,
            params={"fields": "account_id,name", "access_token": token},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        accounts: list[AdAccount] = []
        for item in data:
            # Prefer the act_ prefixed id used by the connector.
            ext_id = item.get("id") or f"act_{item.get('account_id')}"
            accounts.append(AdAccount(external_account_id=ext_id, account_name=item.get("name")))
        return accounts


class GoogleAdsOAuthClient:
    """Google Ads OAuth connect (reuses the Google Web OAuth client)."""

    platform = "google_ads"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        developer_token: str,
        *,
        api_version: str = GOOGLE_ADS_API_VERSION,
        scopes: tuple[str, ...] = GOOGLE_ADS_SCOPES,
        timeout: float = 20.0,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.developer_token = developer_token
        self.api_version = api_version
        self.list_customers_endpoint = google_ads_list_customers_endpoint(api_version)
        self.scopes = scopes
        self.timeout = timeout

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"

    def fetch_connection(self, code: str) -> AdConnectionResult:
        tokens = self._exchange_code(code)
        refresh_token = tokens.get("refresh_token")
        access_token = tokens.get("access_token")
        if not refresh_token:
            raise ValueError(
                "Google did not return a refresh token; re-authorize with prompt=consent."
            )
        accounts = self._list_customers(access_token)
        return AdConnectionResult(
            secret=refresh_token, accounts=accounts, scopes=" ".join(self.scopes)
        )

    def _exchange_code(self, code: str) -> dict:
        resp = httpx.post(
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
        resp.raise_for_status()
        return resp.json()

    def _list_customers(self, access_token: str | None) -> list[AdAccount]:
        if not access_token:
            return []
        resp = httpx.get(
            self.list_customers_endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "developer-token": self.developer_token,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        resource_names = resp.json().get("resourceNames", [])
        accounts: list[AdAccount] = []
        for name in resource_names:
            # "customers/1234567890" -> "1234567890"
            customer_id = name.split("/")[-1]
            descriptive_name = self._fetch_customer_name(access_token, customer_id)
            accounts.append(
                AdAccount(
                    external_account_id=customer_id,
                    account_name=format_google_ads_account_name(customer_id, descriptive_name),
                )
            )
        return accounts

    def _fetch_customer_name(self, access_token: str, customer_id: str) -> str | None:
        """Return a customer's descriptive name, or None if it can't be read.

        Best-effort: a failure here (permission, manager-only account, transient
        error) must not break connect, so we swallow errors and fall back to the
        id-only label upstream.
        """
        try:
            resp = httpx.post(
                google_ads_search_endpoint(self.api_version, customer_id),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "developer-token": self.developer_token,
                    # Required when the account is reached through a manager; for a
                    # directly-accessible account this is harmless. Improves the
                    # odds the descriptive name comes back.
                    "login-customer-id": customer_id,
                },
                json={"query": GOOGLE_ADS_CUSTOMER_NAME_QUERY},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except (httpx.HTTPError, ValueError):
            return None
        if not results:
            return None
        return results[0].get("customer", {}).get("descriptiveName")
