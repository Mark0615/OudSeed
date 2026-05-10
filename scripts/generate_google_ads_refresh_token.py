"""Generate a Google Ads OAuth refresh token for local setup.

This script follows the official Google Ads Python client-library OAuth sample:
it opens a local callback server, asks Google for offline access to the
`https://www.googleapis.com/auth/adwords` scope, and prints the refresh token.

Run locally only. Do not deploy this script to Cloud Run.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import socket
import sys
from urllib.parse import unquote

from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow


GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
DEFAULT_CALLBACK_HOST = "127.0.0.1"
DEFAULT_CALLBACK_PORT = 8080


def main() -> None:
    """Run the OAuth flow and print a refresh token."""
    load_dotenv()
    args = _parse_args()
    redirect_uri = f"http://{args.callback_host}:{args.callback_port}"
    flow = _build_flow(
        client_id=args.client_id or _required_env("GOOGLE_ADS_CLIENT_ID"),
        client_secret=args.client_secret or _required_env("GOOGLE_ADS_CLIENT_SECRET"),
        redirect_uri=redirect_uri,
        client_type=args.client_type,
    )
    passthrough_state = hashlib.sha256(os.urandom(1024)).hexdigest()
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=passthrough_state,
    )

    print("Open this URL in your browser and approve Google Ads access:")
    print(authorization_url)
    print(f"\nWaiting for the OAuth callback at {redirect_uri} ...")

    code = unquote(
        _wait_for_authorization_code(
            host=args.callback_host,
            port=args.callback_port,
            expected_state=passthrough_state,
        )
    )
    flow.fetch_token(code=code)
    refresh_token = flow.credentials.refresh_token
    if not refresh_token:
        raise RuntimeError(
            "Google did not return a refresh token. Re-run with prompt=consent, "
            "or revoke the app access and try again."
        )

    print("\nGOOGLE_ADS_REFRESH_TOKEN value:")
    print(refresh_token)
    print("\nPaste this value into /Users/mark/Desktop/OudSeed/.env as:")
    print("GOOGLE_ADS_REFRESH_TOKEN=<the value above>")


def _build_flow(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    client_type: str,
) -> Flow:
    """Build an OAuth flow from environment-provided client credentials."""
    config_key = "installed" if client_type == "installed" else "web"
    client_config = {
        config_key: {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=[GOOGLE_ADS_SCOPE])
    flow.redirect_uri = redirect_uri
    return flow


def _wait_for_authorization_code(
    host: str,
    port: int,
    expected_state: str,
) -> str:
    """Receive one local OAuth callback and return the authorization code."""
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(1)
        connection, _ = sock.accept()
        with connection:
            data = connection.recv(4096)
            params = _parse_raw_query_params(data)
            message = "Authorization code was successfully retrieved."
            try:
                if not params.get("code"):
                    raise ValueError(
                        "Failed to retrieve authorization code. "
                        f"Error: {params.get('error')}"
                    )
                if params.get("state") != expected_state:
                    raise ValueError("State token does not match the expected state.")
            except ValueError as exc:
                message = str(exc)
                _send_browser_response(connection, message)
                raise

            _send_browser_response(connection, message)
            return params["code"]


def _parse_raw_query_params(data: bytes) -> dict[str, str]:
    """Parse query parameters from a raw HTTP callback request."""
    decoded = data.decode("utf-8")
    match = re.search(r"GET\s/\?(.*) ", decoded)
    if not match:
        raise ValueError("OAuth callback did not include query parameters.")

    params: dict[str, str] = {}
    for pair in match.group(1).split("&"):
        key, _, value = pair.partition("=")
        params[key] = value
    return params


def _send_browser_response(connection: socket.socket, message: str) -> None:
    response = (
        "HTTP/1.1 200 OK\n"
        "Content-Type: text/html; charset=utf-8\n\n"
        f"{message}<br>Please return to the terminal."
    )
    connection.sendall(response.encode("utf-8"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Google Ads OAuth refresh token for local setup.",
    )
    parser.add_argument("--client-id", default=None)
    parser.add_argument("--client-secret", default=None)
    parser.add_argument(
        "--client-type",
        choices=("web", "installed"),
        default="web",
        help=(
            "OAuth client type. Web clients must allow http://127.0.0.1:8080 "
            "as an authorized redirect URI."
        ),
    )
    parser.add_argument("--callback-host", default=DEFAULT_CALLBACK_HOST)
    parser.add_argument("--callback-port", type=int, default=DEFAULT_CALLBACK_PORT)
    return parser.parse_args()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
