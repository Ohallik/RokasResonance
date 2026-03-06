"""
llm_client.py - LLM query client using GitHub Models (OpenAI-compatible API)

Endpoint: https://models.inference.ai.azure.com
Auth: GITHUB_TOKEN env var (fallback) or key stored in settings.json
SDK: openai with custom base_url
"""

import os
import time

from ui.settings_dialog import load_settings

ENDPOINT = "https://models.github.ai/inference"
DEFAULT_MODEL = "openai/gpt-4o"

ANTHROPIC_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
]

_MAX_RETRIES = 10  # high — prefer waiting over giving up

# Fallback base delay (seconds) per model family when no Retry-After header is present.
# Actual delay = base * 2^attempt  (attempt 0..5 → 1×, 2×, 4×, 8×, 16×, 32×)
# "high" tier ≈ 10 RPM → 6 s base; "low" tier ≈ 15 RPM → 4 s base
_MODEL_BASE_DELAYS: dict[str, int] = {
    # OpenAI — high tier
    "openai/gpt-4o": 6,
    "openai/gpt-4.1": 6,
    "openai/gpt-5": 6,
    # OpenAI — low tier
    "openai/gpt-4o-mini": 4,
    "openai/gpt-4.1-mini": 4,
    "openai/gpt-4.1-nano": 4,
    # OpenAI — custom (very restricted)
    "openai/o1": 20,
    "openai/o3": 20,
    "openai/o4-mini": 15,
    # Anthropic — high tier (text-only on this endpoint)
    "anthropic/claude-opus": 6,
    "anthropic/claude-sonnet": 5,
    "anthropic/claude-haiku": 4,
    # Meta Llama — high tier
    "meta/llama-3.2-90b": 6,
    "meta/llama-3.3-70b": 6,
    "meta/llama-4": 6,
    "meta/meta-llama-3.1-405b": 6,
    # Meta Llama — low tier
    "meta/llama-3.2-11b": 4,
    "meta/meta-llama-3.1-8b": 4,
    # Mistral — low tier
    "mistral-ai/": 4,
    # Microsoft Phi — low tier
    "microsoft/phi": 4,
    # xAI / DeepSeek — custom
    "xai/grok": 15,
    "deepseek/": 15,
    # Anthropic direct API (claude-* IDs)
    "claude-opus": 6,
    "claude-sonnet": 5,
    "claude-haiku": 4,
    # Legacy unprefixed names (old endpoint)
    "gpt-4o": 6,
    "gpt-4o-mini": 4,
}
_DEFAULT_BASE_DELAY = 6  # conservative fallback for unknown models


def _retry_delay(exc, attempt: int, model: str) -> float:
    """
    Return seconds to wait before the next attempt.

    Priority:
      1. Retry-After header returned by the server (most accurate)
      2. Model-specific exponential back-off
    """
    # 1. Try server-supplied wait time.
    # Only use Retry-After (the actual "wait this long" directive).
    # x-ratelimit-reset-requests is informational (when the window resets),
    # not a per-request wait time — using it causes 85s waits on every retry.
    try:
        headers = exc.response.headers
        for h in ("retry-after", "x-ms-retry-after-ms"):
            val = headers.get(h)
            if not val:
                continue
            secs = float(val)
            if h == "x-ms-retry-after-ms":
                secs /= 1000.0
            if 1 <= secs <= 300:          # sanity bounds
                return secs + 2           # +2 s buffer
    except Exception:
        pass

    # 2. Model-specific base with exponential back-off
    # Match on prefix so "gpt-4o-mini-2024-07-18" → "gpt-4o-mini" etc.
    base = _DEFAULT_BASE_DELAY
    for prefix, delay in _MODEL_BASE_DELAYS.items():
        if model.startswith(prefix):
            base = delay
            break
    return base * (2 ** attempt)


def _is_anthropic_model(model: str) -> bool:
    """True if the model should be queried via the Anthropic API."""
    return model.startswith("claude-")


def _get_api_key(base_dir: str) -> str:
    """Return API key: settings file takes priority, falls back to GITHUB_TOKEN env var."""
    settings = load_settings(base_dir)
    key = (settings.get("llm") or {}).get("api_key", "").strip()
    if key:
        return key
    return os.environ.get("GITHUB_TOKEN", "")


def _get_anthropic_key(base_dir: str) -> str:
    """Return Anthropic API key from settings."""
    settings = load_settings(base_dir)
    return (settings.get("llm") or {}).get("anthropic_api_key", "").strip()


def _query_anthropic(base_dir: str, model: str, user_prompt: str,
                     system_prompt: str = None, on_retry=None) -> str:
    """Send a text-only query via the Anthropic API."""
    try:
        from anthropic import Anthropic, RateLimitError, APIStatusError
    except ImportError:
        raise RuntimeError("Install the 'anthropic' package: pip install anthropic")

    api_key = _get_anthropic_key(base_dir)
    if not api_key:
        raise ValueError(
            "No Anthropic API key. Enter one in Settings → LLM (Anthropic API Key field)."
        )

    client = Anthropic(api_key=api_key)
    kwargs = dict(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": user_prompt}],
    )
    if system_prompt:
        kwargs["system"] = system_prompt  # Anthropic: system is a top-level param

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return client.messages.create(**kwargs).content[0].text
        except RateLimitError as e:
            last_exc = e
            delay = _retry_delay(e, attempt, model)
            if delay > 300:
                raise RuntimeError(
                    f"Rate limit for '{model}' — retry-after {int(delay)}s. "
                    "Try later or switch to a different model in Settings."
                ) from e
            if attempt < _MAX_RETRIES - 1:
                if on_retry:
                    on_retry(attempt + 1, round(delay))
                time.sleep(delay)
        except APIStatusError:
            raise
    raise last_exc


def _query_with_images_anthropic(base_dir: str, model: str, user_prompt: str,
                                  images: list, system_prompt: str = None,
                                  on_retry=None, max_tokens: int = 2048) -> str:
    """Send a vision query via the Anthropic API."""
    try:
        from anthropic import Anthropic, RateLimitError, APIStatusError
    except ImportError:
        raise RuntimeError("Install the 'anthropic' package: pip install anthropic")

    api_key = _get_anthropic_key(base_dir)
    if not api_key:
        raise ValueError(
            "No Anthropic API key. Enter one in Settings → LLM (Anthropic API Key field)."
        )

    client = Anthropic(api_key=api_key)

    # Anthropic vision format: source.base64 (not OpenAI's image_url data URI)
    content = [{"type": "text", "text": user_prompt}]
    for img in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["mime_type"],
                "data": img["data"],
            },
        })

    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    if system_prompt:
        kwargs["system"] = system_prompt

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return client.messages.create(**kwargs).content[0].text
        except RateLimitError as e:
            last_exc = e
            delay = _retry_delay(e, attempt, model)
            if delay > 300:
                raise RuntimeError(
                    f"Rate limit for '{model}' — retry-after {int(delay)}s. "
                    "Try later or switch to a different model in Settings."
                ) from e
            if attempt < _MAX_RETRIES - 1:
                if on_retry:
                    on_retry(attempt + 1, round(delay))
                time.sleep(delay)
        except APIStatusError:
            raise
    raise last_exc


def _get_model(base_dir: str) -> str:
    settings = load_settings(base_dir)
    return (settings.get("llm") or {}).get("model", DEFAULT_MODEL)


def _make_client(api_key: str):
    from openai import OpenAI
    return OpenAI(base_url=ENDPOINT, api_key=api_key)


def query(base_dir: str, user_prompt: str, system_prompt: str = None, on_retry=None) -> str:
    """
    Send a single query to the LLM and return the response text.

    Automatically routes to Anthropic API for claude-* models, GitHub Models for all others.
    Retries up to _MAX_RETRIES times on rate-limit (429) errors.
    """
    model = _get_model(base_dir)
    if _is_anthropic_model(model):
        return _query_anthropic(base_dir, model, user_prompt, system_prompt, on_retry)

    from openai import RateLimitError, APIStatusError

    api_key = _get_api_key(base_dir)
    if not api_key:
        raise ValueError(
            "No API key available. Set the GITHUB_TOKEN environment variable "
            "or enter a key in Settings."
        )

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
            # Daily/weekly limits won't recover with retries — fail fast
            limit_type = ""
            try:
                limit_type = e.response.headers.get("x-ratelimit-type", "")
            except Exception:
                pass
            if "day" in limit_type.lower() or "week" in limit_type.lower():
                raise RuntimeError(
                    f"Daily rate limit reached for model '{model}'. "
                    "Try a different model in Settings or wait until tomorrow."
                ) from e
            if attempt < _MAX_RETRIES - 1:
                delay = _retry_delay(e, attempt, model)
                if on_retry:
                    on_retry(attempt + 1, round(delay))
                time.sleep(delay)
            # else fall through to raise

        except APIStatusError:
            raise

    raise last_exc


def query_with_images(
    base_dir: str,
    user_prompt: str,
    images: list,
    system_prompt: str = None,
    on_retry=None,
    max_tokens: int = 2048,
) -> str:
    """
    Send a query with one or more images to the LLM (vision).

    images: list of dicts with keys:
        "mime_type"  - e.g. "image/png", "image/jpeg"
        "data"       - base64-encoded image bytes (str)

    Automatically routes to Anthropic API for claude-* models, GitHub Models for all others.
    """
    model = _get_model(base_dir)
    if _is_anthropic_model(model):
        return _query_with_images_anthropic(base_dir, model, user_prompt, images, system_prompt, on_retry, max_tokens)

    from openai import RateLimitError, APIStatusError

    api_key = _get_api_key(base_dir)
    if not api_key:
        raise ValueError(
            "No API key available. Set the GITHUB_TOKEN environment variable "
            "or enter a key in Settings."
        )

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
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content

        except RateLimitError as e:
            last_exc = e
            limit_type = ""
            try:
                limit_type = e.response.headers.get("x-ratelimit-type", "")
            except Exception:
                pass
            if "day" in limit_type.lower() or "week" in limit_type.lower():
                raise RuntimeError(
                    f"Daily rate limit reached for model '{model}'. "
                    "Try a different model in Settings or wait until tomorrow."
                ) from e
            if attempt < _MAX_RETRIES - 1:
                delay = _retry_delay(e, attempt, model)
                if on_retry:
                    on_retry(attempt + 1, round(delay))
                time.sleep(delay)

        except APIStatusError:
            raise

    raise last_exc


def is_configured(base_dir: str) -> bool:
    """Return True if an API key is available for the currently selected model."""
    model = _get_model(base_dir)
    if _is_anthropic_model(model):
        return bool(_get_anthropic_key(base_dir))
    return bool(_get_api_key(base_dir))
