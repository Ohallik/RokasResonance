"""
llm_client.py - LLM query client using GitHub Models (OpenAI-compatible API)

Endpoint: https://models.inference.ai.azure.com
Auth: GITHUB_TOKEN env var (fallback) or key stored in settings.json
SDK: openai with custom base_url
"""

import functools
import os
import re
import time

from ui.settings_dialog import load_settings

ENDPOINT = "https://models.github.ai/inference"
DEFAULT_MODEL = "openai/gpt-4o"
# Named, so that nothing has to know a position in the list below.  The image
# fallback in music_manager used to reach for ANTHROPIC_MODELS[1] and trust it
# to be a Sonnet, which is only true until somebody reorders the list.
CLAUDE_HAIKU  = "claude-haiku-4-5"
CLAUDE_SONNET = "claude-sonnet-5"
CLAUDE_OPUS   = "claude-opus-5"

_ENRICH_MODEL = CLAUDE_HAIKU  # always use for enrichment (cheapest)

# Cheapest first, so the top of the dropdown stays the safe default.  Model IDs
# carry no date suffix; the dated Haiku is kept at the end only because saved
# settings may still name it, and a teacher should not have her chosen model
# silently disappear from the list.
ANTHROPIC_MODELS = [
    CLAUDE_HAIKU,                  # fast, cheapest — the default
    CLAUDE_SONNET,                 # balanced
    CLAUDE_OPUS,                   # most capable
    "claude-opus-4-8",             # previous generation
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",   # legacy ID, kept so old settings still match
]

_MAX_RETRIES = 10  # high — prefer waiting over giving up


# ── Answer extraction ────────────────────────────────────────────────────────
def _answer(msg) -> str:
    """The reply text out of an Anthropic response.

    This used to be `.content[0].text`, which assumes the first block in the
    response is the answer.  On any model that thinks -- which now includes
    everything in the Opus 5 family, where thinking is on unless it is turned
    off -- the first block is a thinking block and has no .text at all, so the
    old line raised AttributeError and Reginald simply broke.  Walk the blocks
    and take the first real text one.
    """
    for block in getattr(msg, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    # Nothing to read.  Being told the answer was cut off is far more use than
    # an empty reply that looks like the model had nothing to say.
    if getattr(msg, "stop_reason", None) == "max_tokens":
        raise RuntimeError(
            "The model hit its length limit before finishing an answer. "
            "Try a shorter question, or a model that thinks less."
        )
    if getattr(msg, "stop_reason", None) == "refusal":
        raise RuntimeError("The model declined to answer that one.")
    return ""


# ── Prompt caching ───────────────────────────────────────────────────────────
# Reginald's system prompt is the whole of his knowledge -- the inventory, the
# roster, the repairs, the fees, the calendar and the entire user guide -- and
# it is rebuilt identically on every message.  Sent as a plain string it was
# re-read and re-billed in full each time, so a ten message conversation paid
# for that same ~30k tokens ten times over.
#
# Marking it cacheable means the first message writes it once and the rest of
# the conversation reads it back at about a tenth of the price, and faster,
# because the model is not re-ingesting 30k tokens before it starts answering.
#
# Caching is a prefix match: the cached text has to be byte-identical, so
# anything that varies per message must come after it.  It does -- the question
# lives in `messages`, and everything here is the system prompt.
_CACHE_MIN_CHARS = 4096  # the API will not cache a prefix under ~1k tokens


def _cacheable(system_prompt):
    """Wrap a system prompt so the API caches it, if it is worth caching."""
    if not system_prompt or len(system_prompt) < _CACHE_MIN_CHARS:
        return system_prompt          # too short to cache; send it as it is
    return [{"type": "text",
             "text": system_prompt,
             "cache_control": {"type": "ephemeral"}}]


# ── Citation markup ──────────────────────────────────────────────────────────
# A web-search answer comes back with its sources marked up in the text:
#     <cite index="4-14">A Duke Ellington classic…</cite>
# That is meant for a program that renders footnotes.  Here the text goes
# straight into a field a teacher reads and edits, so the tags have to come off
# before anything stores them.  Only the wrappers go; the words inside stay.
_CITE_PATTERNS = (
    re.compile(r"</?cite\b[^>]*>", re.I),          # <cite index="1-3">  </cite>
    re.compile(r"</?citations?\b[^>]*>", re.I),    # <citation> / <citations>
    re.compile(r"\[cite_start\]", re.I),           # marker some tooling emits
    re.compile(r"\[cite:[^\]]*\]", re.I),          # [cite: 3]
    re.compile(r"【[^】]*†[^】]*】"),                 # 【4:0†source】
)


def strip_citation_markup(text):
    """Model output with its citation tags taken off, and the spacing tidied.

    Safe to run twice, and safe on text that never had any: nothing but those
    specific tags is touched, so a piece called "Fanfare <3" survives."""
    if not text or not isinstance(text, str):
        return text
    cleaned = text
    for pattern in _CITE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    if cleaned == text:
        return text
    # Removing a tag can leave a double space, or a gap before punctuation.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+$", "", cleaned, flags=re.M)
    return cleaned.strip()


def _clean_output(fn):
    """Take citation markup off whatever this query function returns.

    Applied to every public query so a new caller cannot forget it; running it
    twice on the same string changes nothing."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return strip_citation_markup(fn(*args, **kwargs))
    return wrapper


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

# Music reference sites the web-search enrichment tool is allowed to query.
_ENRICHMENT_SEARCH_DOMAINS = [
    "windrep.org",
    "jwpepper.com",
    "sheetmusicplus.com",
    "alfred.com",
    "halleonard.com",
    "fjhmusic.com",
    "carlfischer.com",
    "worldcat.org",
    "imslp.org",
]


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


# 1024 was fine when no model thought before answering.  Thinking tokens count
# against max_tokens, so on an Opus 5 the budget could be gone before the reply
# even started and the answer came back truncated.  This is a cap, not a target
# -- output is billed on what is actually produced -- so the headroom is free.
_DEFAULT_MAX_TOKENS = 4096


def _query_anthropic(base_dir: str, model: str, user_prompt: str,
                     system_prompt: str = None, on_retry=None,
                     max_tokens: int = _DEFAULT_MAX_TOKENS) -> str:
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
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": user_prompt}],
    )
    if system_prompt:
        kwargs["system"] = _cacheable(system_prompt)  # Anthropic: system is a top-level param

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return _answer(client.messages.create(**kwargs))
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


def _query_anthropic_with_search(base_dir: str, model: str, user_prompt: str,
                                  system_prompt: str = None, on_retry=None,
                                  max_uses: int = 1) -> str:
    """Send a query via the Anthropic API with the built-in web search tool enabled.

    The web_search_20250305 tool is executed server-side by Anthropic — no tool-use
    loop required.  The response may contain multiple text blocks (reasoning, search
    results, citations, final answer); we concatenate them all.
    """
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
        max_tokens=2048,   # higher — search results consume tokens before the answer
        messages=[{"role": "user", "content": user_prompt}],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_uses,
            "allowed_domains": _ENRICHMENT_SEARCH_DOMAINS,
        }],
    )
    if system_prompt:
        kwargs["system"] = _cacheable(system_prompt)

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.messages.create(**kwargs)
            # Concatenate all text blocks (reasoning + citation text + final answer)
            return "\n".join(
                block.text for block in resp.content if hasattr(block, "text")
            )
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
        kwargs["system"] = _cacheable(system_prompt)

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            return _answer(client.messages.create(**kwargs))
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


def _is_proxy_mode(base_dir: str) -> bool:
    """True if the user has selected Claude Proxy as the backend."""
    settings = load_settings(base_dir)
    return (settings.get("llm") or {}).get("backend", "proxy") == "proxy"


def _get_proxy_endpoint(base_dir: str) -> str:
    settings = load_settings(base_dir)
    url = (settings.get("llm") or {}).get("proxy_endpoint", "").strip().rstrip("/")
    # Accept either the base URL or one that already includes the /api/chat path —
    # the request code always appends /api/chat, so strip it here if present.
    for suffix in ("/api/chat", "/api"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    return url


def _get_proxy_token(base_dir: str) -> str:
    settings = load_settings(base_dir)
    return (settings.get("llm") or {}).get("proxy_token", "").strip()


def _query_proxy(base_dir: str, user_prompt: str, system_prompt: str = None,
                 on_retry=None, images: list = None) -> str:
    """Send a query through the Claude proxy (POST /api/chat)."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError("Install the 'httpx' package: pip install httpx")

    endpoint = _get_proxy_endpoint(base_dir)
    token = _get_proxy_token(base_dir)
    if not endpoint or not token:
        raise ValueError(
            "Claude Proxy not configured. Enter the endpoint and token in Settings → LLM."
        )

    body = {"message": user_prompt}
    if system_prompt:
        body["system"] = system_prompt
    if images:
        body["images"] = images  # list of {"mime_type": ..., "data": ...}

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = httpx.post(
                f"{endpoint}/api/chat",
                json=body,
                headers={"x-proxy-token": token},
                timeout=60,
            )
            if resp.status_code == 429:
                delay = min(60 * (2 ** attempt), 300)
                last_exc = RuntimeError(resp.json().get("error", "Rate limit exceeded"))
                if attempt < _MAX_RETRIES - 1:
                    if on_retry:
                        on_retry(attempt + 1, round(delay))
                    time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()["reply"]
        except Exception as e:
            if "429" not in str(e):
                raise
            last_exc = e
    raise last_exc


def _get_model(base_dir: str) -> str:
    settings = load_settings(base_dir)
    return (settings.get("llm") or {}).get("model", DEFAULT_MODEL)


def _make_client(api_key: str):
    from openai import OpenAI
    return OpenAI(base_url=ENDPOINT, api_key=api_key)


@_clean_output
def query(base_dir: str, user_prompt: str, system_prompt: str = None, on_retry=None,
          max_tokens: int = _DEFAULT_MAX_TOKENS) -> str:
    """
    Send a single query to the LLM and return the response text.

    Automatically routes to Claude Proxy, Anthropic API, or GitHub Models
    based on settings. Retries up to _MAX_RETRIES times on rate-limit errors.
    max_tokens caps the response length (larger for big structured outputs).
    """
    if _is_proxy_mode(base_dir):
        return _query_proxy(base_dir, user_prompt, system_prompt, on_retry)

    model = _get_model(base_dir)
    if _is_anthropic_model(model):
        return _query_anthropic(base_dir, model, user_prompt, system_prompt, on_retry,
                                max_tokens=max_tokens)

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
                max_tokens=max_tokens,
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


@_clean_output
def query_with_search(base_dir: str, user_prompt: str,
                      system_prompt: str = None, on_retry=None) -> str:
    """
    Send a query with live web search capability.

    For Anthropic/Claude models: uses the built-in web_search_20250305 tool
    (server-side, domains restricted to music reference sites).
    For GitHub Models: falls back to regular query() — no web search available.
    """
    model = _get_model(base_dir)
    if _is_anthropic_model(model):
        return _query_anthropic_with_search(base_dir, model, user_prompt,
                                            system_prompt, on_retry)
    # GitHub Models don't support the Anthropic web search tool
    return query(base_dir, user_prompt, system_prompt, on_retry)


@_clean_output
def query_haiku(base_dir: str, user_prompt: str,
                system_prompt: str = None, on_retry=None) -> str:
    """Query using Haiku regardless of selected model. Cheapest text-only option.
    In proxy mode, routes through the proxy instead (model fixed to sonnet on proxy side)."""
    if _is_proxy_mode(base_dir):
        return _query_proxy(base_dir, user_prompt, system_prompt, on_retry)
    return _query_anthropic(base_dir, _ENRICH_MODEL, user_prompt, system_prompt, on_retry)


@_clean_output
def query_haiku_with_search(base_dir: str, user_prompt: str,
                             system_prompt: str = None, on_retry=None) -> str:
    """Haiku + 1 web search. Cheapest web-search option for enrichment.
    In proxy mode, falls back to plain proxy query (web search not available via proxy)."""
    if _is_proxy_mode(base_dir):
        return _query_proxy(base_dir, user_prompt, system_prompt, on_retry)
    return _query_anthropic_with_search(
        base_dir, _ENRICH_MODEL, user_prompt, system_prompt, on_retry, max_uses=1
    )


@_clean_output
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

    Routes to Claude Proxy, Anthropic API, or GitHub Models based on settings.
    """
    if _is_proxy_mode(base_dir):
        return _query_proxy(base_dir, user_prompt, system_prompt, on_retry, images=images)

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
    """Return True if the LLM backend is configured and ready to use."""
    if _is_proxy_mode(base_dir):
        return bool(_get_proxy_endpoint(base_dir) and _get_proxy_token(base_dir))
    model = _get_model(base_dir)
    if _is_anthropic_model(model):
        return bool(_get_anthropic_key(base_dir))
    return bool(_get_api_key(base_dir))
