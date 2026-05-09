"""Small OpenAI Responses API client."""

from __future__ import annotations

from typing import Any

import requests


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAITextClient:
    """Generate text with OpenAI's Responses API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4 mini",
        reasoning_effort: str = "medium",
        timeout_seconds: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI api_key is required.")
        self.api_key = api_key
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def generate_text(
        self,
        prompt: str,
        max_output_tokens: int = 1800,
    ) -> tuple[str, dict[str, Any]]:
        """Generate text and return the text plus raw response payload."""
        payload = {
            "model": self.model,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}

        response = self.session.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                "OpenAI Responses API request failed "
                f"with status {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("OpenAI Responses API returned invalid JSON.") from exc

        text = extract_output_text(payload)
        if not text:
            raise RuntimeError("OpenAI Responses API returned no output text.")

        return text, payload


def extract_output_text(payload: dict[str, Any]) -> str:
    """Extract generated text from a Responses API payload."""
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    text_parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())

    return "\n".join(text_parts).strip()
