"""
llm_client.py - LLM query client using GitHub Models (OpenAI-compatible API)

Endpoint: https://models.inference.ai.azure.com
Auth: GITHUB_TOKEN env var (fallback) or key stored in settings.json
SDK: openai with custom base_url
"""

import os
import time

from ui.settings_dialog import load_settings

ENDPOINT = "https://models.inference.ai.azure.com"
DEFAULT_MODEL = "claude-opus-4-5"

_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 2  # seconds, doubles each attempt (2, 4, 8, 16)


def _get_api_key(base_dir: str) -> str:
    """Return API key: settings file takes priority, falls back to GITHUB_TOKEN env var."""
    settings = load_settings(base_dir)
    key = (settings.get("llm") or {}).get("api_key", "").strip()
    if key:
        return key
    return os.environ.get("GITHUB_TOKEN", "")


def _get_model(base_dir: str) -> str:
    settings = load_settings(base_dir)
    return (settings.get("llm") or {}).get("model", DEFAULT_MODEL)


def _make_client(api_key: str):
    from openai import OpenAI
    return OpenAI(base_url=ENDPOINT, api_key=api_key)


def query(base_dir: str, user_prompt: str, system_prompt: str = None) -> str:
    """
    Send a single query to the LLM and return the response text.

    Retries up to _MAX_RETRIES times on rate-limit (429) errors with
    exponential back-off. Raises on all other errors.
    """
    from openai import RateLimitError, APIStatusError

    api_key = _get_api_key(base_dir)
    if not api_key:
        raise ValueError(
            "No API key available. Set the GITHUB_TOKEN environment variable "
            "or enter a key in Settings."
        )

    model = _get_model(base_dir)
    client = _make_client(api_key)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=1024,
            )
            return response.choices[0].message.content

        except RateLimitError as e:
            last_exc = e
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
            # else fall through to raise

        except APIStatusError as e:
            # Re-raise non-rate-limit API errors immediately
            raise

    raise last_exc


def query_with_images(
    base_dir: str,
    user_prompt: str,
    images: list,
    system_prompt: str = None,
) -> str:
    """
    Send a query with one or more images to the LLM (vision).

    images: list of dicts with keys:
        "mime_type"  - e.g. "image/png", "image/jpeg"
        "data"       - base64-encoded image bytes (str)

    Retries on rate-limit errors the same as query().
    Raises ValueError if no API key is available.
    """
    from openai import RateLimitError, APIStatusError

    api_key = _get_api_key(base_dir)
    if not api_key:
        raise ValueError(
            "No API key available. Set the GITHUB_TOKEN environment variable "
            "or enter a key in Settings."
        )

    model = _get_model(base_dir)
    client = _make_client(api_key)

    content = [{"type": "text", "text": user_prompt}]
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{img['mime_type']};base64,{img['data']}"
            },
        })

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=2048,
            )
            return response.choices[0].message.content

        except RateLimitError as e:
            last_exc = e
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)

        except APIStatusError:
            raise

    raise last_exc


def is_configured(base_dir: str) -> bool:
    """Return True if an API key is available (settings or env var)."""
    return bool(_get_api_key(base_dir))
