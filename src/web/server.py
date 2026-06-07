"""Server entrypoint: load .env, then build the app.

Run with: ``uvicorn src.web.server:app``. Loading .env here (rather than at
import of src.web.config) keeps environment side effects out of imports and
tests, while ensuring a real server run picks up OAuth/session/DB settings.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from src.web.app import create_app  # noqa: E402  (must follow load_dotenv)

app = create_app()
