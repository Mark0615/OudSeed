"""Tests for OpenAI Responses API client."""

from unittest.mock import Mock

import pytest

from src.ai.openai_client import OpenAITextClient, extract_output_text


def test_extract_output_text_prefers_output_text() -> None:
    """SDK-like output_text payloads are supported."""
    assert extract_output_text({"output_text": " Hello "}) == "Hello"


def test_extract_output_text_reads_response_output_content() -> None:
    """Raw Responses API output arrays are supported."""
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "First"},
                    {"type": "output_text", "text": "Second"},
                ],
            }
        ]
    }

    assert extract_output_text(payload) == "First\nSecond"


def test_openai_text_client_posts_to_responses_api() -> None:
    """Client sends prompt to the Responses API and returns generated text."""
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"output_text": "Report text"}
    session = Mock()
    session.post.return_value = response

    client = OpenAITextClient(
        api_key="test-key",
        model="gpt-test",
        session=session,
    )
    text, payload = client.generate_text("Prompt", max_output_tokens=100)

    assert text == "Report text"
    assert payload == {"output_text": "Report text"}
    session.post.assert_called_once()
    request = session.post.call_args
    assert request.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert request.kwargs["json"]["model"] == "gpt-test"
    assert request.kwargs["json"]["input"] == "Prompt"
    assert request.kwargs["json"]["max_output_tokens"] == 100
    assert request.kwargs["json"]["reasoning"] == {"effort": "medium"}


def test_openai_text_client_uses_configured_reasoning_effort() -> None:
    """Client includes configured reasoning effort in Responses API payload."""
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"output_text": "Report text"}
    session = Mock()
    session.post.return_value = response
    client = OpenAITextClient(
        api_key="test-key",
        model="gpt-test",
        reasoning_effort="low",
        session=session,
    )

    client.generate_text("Prompt")

    request = session.post.call_args
    assert request.kwargs["json"]["reasoning"] == {"effort": "low"}


def test_openai_text_client_raises_for_http_error() -> None:
    """HTTP errors are surfaced with status and response body."""
    response = Mock()
    response.status_code = 401
    response.text = "bad key"
    session = Mock()
    session.post.return_value = response
    client = OpenAITextClient(api_key="test-key", session=session)

    with pytest.raises(RuntimeError, match="status 401"):
        client.generate_text("Prompt")


def test_openai_text_client_requires_api_key() -> None:
    """OpenAI API key is required."""
    with pytest.raises(ValueError, match="api_key"):
        OpenAITextClient(api_key="")
