"""AI compliance engine: regulation-vs-company-state gap analysis and audit-log generation.

Public contract (imported by the API layer):

    from ai_engine import analyze_compliance_gap, generate_audit_trail, LLMError

All functions are synchronous and return plain JSON-serializable Python objects.
Errors: ValueError for bad input; LLMConfigError for a missing or rejected key (its
subclass LLMSetupError for setup a key will not fix, such as an unknown model); any
other LLMError when the provider fails, cannot be reached or returns unusable output.
No other exception type escapes.

Bring your own key and model: every public function takes optional keyword-only
`api_key`, `provider` and `model`. Providers: anthropic (native Claude API) plus any
OpenAI-compatible API: openai, gemini, groq, openrouter, deepseek, mistral, xai,
together, ollama and custom (LLM_BASE_URL). With a key but no provider, the provider is
detected from the key prefix (sk-ant-, sk-, AIza, gsk_, sk-or-, xai-).

Configuration is read from the environment (or a gitignored .env) at call time, never
at import time, and keys are never logged:

    LLM_PROVIDER          optional; default "ollama" (smallest locally installed model)
    LLM_MODEL             optional; per provider: <PROVIDER>_MODEL (e.g. GEMINI_MODEL)
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY,
    DEEPSEEK_API_KEY, MISTRAL_API_KEY, XAI_API_KEY, TOGETHER_API_KEY, LLM_API_KEY (custom)
    LLM_TIMEOUT_SECONDS   optional, default 60 (per read; connecting gives up after 5 s)
    LLM_EFFORT            optional (Claude only: low | medium | high | xhigh | max), default "medium"
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Literal, NamedTuple, TypeVar

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

import demo_fixtures
import grounding
from prompts import (
    ANALYSIS_SCHEMA,
    ANALYSIS_SYSTEM_PROMPT,
    ANOMALY_ITEM_FIELDS,
    AUDIT_SYSTEM_PROMPT,
    MAX_ANOMALIES,
    build_analysis_prompt,
    build_audit_prompt,
)

__all__ = [
    "LLMError",
    "LLMConfigError",
    "LLMSetupError",
    "LLMOutputError",
    "call_llm",
    "analyze_compliance_gap",
    "analyze_compliance_report",
    "generate_audit_trail",
    "generate_audit_report",
    "build_coverage",
    "PROVIDERS",
]

logger = logging.getLogger("ai_engine")
T = TypeVar("T")

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_EFFORT = "medium"
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CONNECT_TIMEOUT_SECONDS = 5.0  # an unreachable host fails in seconds, not LLM_TIMEOUT_SECONDS
# One SDK retry rides out a transient 429, 5xx or dropped connection. More would multiply
# the worst case: each retried read timeout waits the full LLM_TIMEOUT_SECONDS again.
SDK_MAX_RETRIES = 1
# Local Ollama has no rate limits or flaky network to ride out, and retrying a read
# timeout would re-run the whole (slow) local generation, so it fails at once.
LOCAL_MAX_RETRIES = 0
MAX_ATTEMPTS = 3  # total attempts on unusable output
AUDIT_ATTEMPTS = 2  # LLM attempts for the audit log before the deterministic fallback
DEFAULT_MAX_TOKENS = 16000  # room for adaptive thinking plus up to 25 findings

MAX_REGULATION_CHARS = 100_000
MAX_STATE_CHARS = 20_000
MAX_TITLE_CHARS = 80
MAX_EXCERPT_CHARS = grounding.MAX_EXCERPT_CHARS
NOT_SPECIFIED = "Not specified in company state"

# Server-side refusal fallback: if the model declines, the API re-runs the request on
# a fallback model inside the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
OUTPUT_KEYS = ("id",) + ANOMALY_ITEM_FIELDS  # the original contract; the audit prompt sends these
# Additive per-finding fields (owner-approved): appended after OUTPUT_KEYS.
ADDITIVE_FIELDS = ("state_fields", "excerpt_match", "excerpt_score", "excerpt_span")


# --------------------------------------------------------------------------- errors


class LLMError(RuntimeError):
    """Base class for every failure of the LLM layer."""


class LLMConfigError(LLMError):
    """Missing API key or bad configuration."""


class LLMSetupError(LLMConfigError):
    """Configuration that a different API key would not fix: an unknown model, an invalid
    LLM_* environment variable, or a missing dependency. A subclass of LLMConfigError, so
    existing handlers still catch it; the API reports it as a server error, not as 401."""


class LLMOutputError(LLMError):
    """The model's output was unusable after all retries."""


# --------------------------------------------------------------------------- config


def _timeout_seconds() -> float:
    raw = os.environ.get("LLM_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise LLMSetupError("LLM_TIMEOUT_SECONDS must be a number") from None
    if value <= 0:
        raise LLMSetupError("LLM_TIMEOUT_SECONDS must be positive")
    return value


def _effort() -> str:
    raw = os.environ.get("LLM_EFFORT", "").strip().lower() or DEFAULT_EFFORT
    if raw not in VALID_EFFORTS:
        raise LLMSetupError(f"LLM_EFFORT must be one of {', '.join(VALID_EFFORTS)}")
    return raw


# --------------------------------------------------------------------------- providers

class _ProviderSpec(NamedTuple):
    base_url: str | None  # None: the SDK default (OpenAI) or LLM_BASE_URL (custom)
    key_env_vars: tuple[str, ...]
    default_model: str  # "": discovered (ollama) or required from config (custom)


# OpenAI-compatible providers. Every default model can be overridden with model=,
# <PROVIDER>_MODEL or LLM_MODEL, and every base URL with <PROVIDER>_BASE_URL.
_OPENAI_COMPATIBLE: dict[str, _ProviderSpec] = {
    "openai": _ProviderSpec(None, ("OPENAI_API_KEY",), "gpt-5-mini"),
    "gemini": _ProviderSpec(
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "gemini-2.5-flash",
    ),
    "groq": _ProviderSpec("https://api.groq.com/openai/v1", ("GROQ_API_KEY",), "llama-3.3-70b-versatile"),
    "openrouter": _ProviderSpec("https://openrouter.ai/api/v1", ("OPENROUTER_API_KEY",), "openrouter/auto"),
    "deepseek": _ProviderSpec("https://api.deepseek.com", ("DEEPSEEK_API_KEY",), "deepseek-chat"),
    "mistral": _ProviderSpec("https://api.mistral.ai/v1", ("MISTRAL_API_KEY",), "mistral-large-latest"),
    "xai": _ProviderSpec("https://api.x.ai/v1", ("XAI_API_KEY",), "grok-4"),
    "together": _ProviderSpec(
        "https://api.together.xyz/v1",
        ("TOGETHER_API_KEY",),
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ),
    "ollama": _ProviderSpec("http://localhost:11434/v1", ("OLLAMA_API_KEY",), ""),  # default: smallest installed model
    "custom": _ProviderSpec(None, ("LLM_API_KEY",), ""),  # any OpenAI-compatible server: set LLM_BASE_URL + LLM_MODEL
}
PROVIDERS: tuple[str, ...] = ("anthropic",) + tuple(_OPENAI_COMPATIBLE)
_ANTHROPIC_KEY_ENV = ("ANTHROPIC_API_KEY",)
# Key prefixes used to pick a provider when the caller passes a key but no provider.
_KEY_PREFIXES = (
    ("sk-ant-", "anthropic"),
    ("sk-or-", "openrouter"),
    ("gsk_", "groq"),
    ("xai-", "xai"),
    ("AIza", "gemini"),
    ("AQ.", "gemini"),
    ("sk-", "openai"),
)

_dotenv_loaded = False


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a .env next to this file, once, without overriding the environment.

    Runs lazily on the first LLM call, never at import time. Disable with AI_ENGINE_DOTENV=0.
    """
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    if os.environ.get("AI_ENGINE_DOTENV", "1") == "0":
        return
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if name and value and name not in os.environ:
            os.environ[name] = value


def _key_env_vars(provider: str) -> tuple[str, ...]:
    return _ANTHROPIC_KEY_ENV if provider == "anthropic" else _OPENAI_COMPATIBLE[provider].key_env_vars


def _env_key(provider: str) -> str:
    for name in _key_env_vars(provider):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


DEFAULT_PROVIDER = "ollama"  # local models by default: no key, no cost, no data leaves the machine
OLLAMA_FALLBACK_MODEL = "qwen2.5vl:3b"
OLLAMA_TAGS_TIMEOUT_SECONDS = 2.0
OLLAMA_MODEL_TTL_SECONDS = 300.0  # re-read the installed models every 5 minutes
OLLAMA_DOWN_TTL_SECONDS = 10.0  # after a failed probe, skip probing for 10 seconds
# Cached discovery result: (smallest installed model, or None if the probe failed, expiry
# on the time.monotonic() clock). None means "not probed yet".
_ollama_default: tuple[str | None, float] | None = None


def _env_provider() -> str:
    """Provider when the caller names none: LLM_PROVIDER, else DEFAULT_PROVIDER (ollama)."""
    _load_dotenv()
    configured = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if configured:
        if configured not in PROVIDERS:
            raise LLMSetupError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}")
        return configured
    return DEFAULT_PROVIDER


def _smallest_ollama_model() -> str:
    """Smallest model installed on the local Ollama server, else OLLAMA_FALLBACK_MODEL.

    The /api/tags lookup is cached: a hit for OLLAMA_MODEL_TTL_SECONDS (so newly pulled
    models are picked up), a failed probe for OLLAMA_DOWN_TTL_SECONDS (so a stopped server
    costs one probe, not one per call).
    """
    global _ollama_default
    now = time.monotonic()
    cached = _ollama_default
    if cached is not None and now < cached[1]:
        return cached[0] or OLLAMA_FALLBACK_MODEL
    found = _probe_ollama_models()
    ttl = OLLAMA_MODEL_TTL_SECONDS if found else OLLAMA_DOWN_TTL_SECONDS
    _ollama_default = (found, now + ttl)
    return found or OLLAMA_FALLBACK_MODEL


def _probe_ollama_models() -> str | None:
    """Ask the Ollama server for its installed models; the smallest one's name, or None."""
    import urllib.request

    root = str(_resolve_base_url("ollama")).rstrip("/").removesuffix("/v1")
    try:
        with urllib.request.urlopen(root + "/api/tags", timeout=OLLAMA_TAGS_TIMEOUT_SECONDS) as response:
            models = json.load(response).get("models") or []
        sized = [(int(m.get("size") or 0), str(m.get("name") or m.get("model"))) for m in models]
        sized = [m for m in sized if m[0] > 0 and m[1] and m[1] != "None"]
        return min(sized)[1] if sized else None
    except Exception:  # server down or unexpected payload: the caller uses the fallback
        logger.info("ollama model discovery failed; using %s", OLLAMA_FALLBACK_MODEL)
        return None


def _check_llm_args(api_key: Any, provider: Any = None, model: Any = None) -> None:
    """Reject malformed caller-supplied LLM options before any work is done."""
    if api_key is not None and (not isinstance(api_key, str) or not api_key.strip()):
        raise ValueError("api_key must be a non-empty string or None")
    if provider is not None:
        if not isinstance(provider, str) or provider.strip().lower() not in PROVIDERS:
            raise ValueError(f"provider must be one of {', '.join(PROVIDERS)}")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("model must be a non-empty string or None")


def _resolve_provider(provider: str | None = None, api_key: str | None = None) -> str:
    if provider is not None:
        return provider.strip().lower()
    if api_key:
        for prefix, name in _KEY_PREFIXES:
            if api_key.strip().startswith(prefix):
                return name
    return _env_provider()


def _resolve_model(provider: str, model: str | None = None) -> str:
    if model:
        return model.strip()
    _load_dotenv()
    specific = os.environ.get(f"{provider.upper()}_MODEL", "").strip()
    if specific:
        return specific
    generic = os.environ.get("LLM_MODEL", "").strip()
    if generic and (provider == _env_provider() or provider == "custom"):
        return generic
    if provider == "anthropic":
        return DEFAULT_MODEL
    if provider == "ollama":
        return _smallest_ollama_model()
    default = _OPENAI_COMPATIBLE[provider].default_model
    if not default:
        raise LLMSetupError("provider 'custom' needs a model: pass model= or set LLM_MODEL")
    return default


def _resolve_base_url(provider: str) -> str | None:
    """Base URLs come only from server config, never from the caller (no SSRF via requests)."""
    if provider == "anthropic":
        return None
    override = os.environ.get(f"{provider.upper()}_BASE_URL", "").strip()
    if provider == "custom":
        override = override or os.environ.get("LLM_BASE_URL", "").strip()
        if not override:
            raise LLMSetupError("provider 'custom' needs LLM_BASE_URL")
    return override or _OPENAI_COMPATIBLE[provider].base_url


def _model_label(api_key: str | None, provider: str | None, model: str | None) -> str:
    """The model name shown in the audit log header. Never raises: a configuration error
    surfaces from the LLM call itself, and the no-gaps log needs no LLM at all."""
    try:
        return _resolve_model(_resolve_provider(provider, api_key), model)
    except LLMConfigError:
        if model:
            return model
    try:
        return _resolve_model(_env_provider())
    except LLMConfigError:
        return DEFAULT_MODEL


# --------------------------------------------------------------------------- client

_MAX_CACHED_CLIENTS = 64
_clients: OrderedDict[tuple, Any] = OrderedDict()
_client_lock = threading.Lock()


def _get_client(api_key: str | None = None, provider: str | None = None) -> Any:
    """Lazy, cached SDK client for the caller's key, or the provider's key from the environment.

    Keys are read at call time, never at import time. One client is kept per
    (provider, base URL, key hash, timeout); plaintext keys are never used as dict keys,
    and the least recently used client is dropped beyond _MAX_CACHED_CLIENTS.
    """
    _load_dotenv()
    name = _resolve_provider(provider, api_key)
    key = (api_key if api_key is not None else _env_key(name)).strip()
    if not key and name == "ollama":
        key = "ollama"  # local server, no key needed
    if not key:
        envs = " or ".join(_key_env_vars(name))
        raise LLMConfigError(f"no API key for provider '{name}': pass api_key= or set {envs}")
    timeout = _timeout_seconds()
    base_url = _resolve_base_url(name)
    cache_key = (name, base_url, hashlib.sha256(key.encode()).hexdigest(), timeout)
    with _client_lock:
        client = _clients.get(cache_key)
        if client is not None:
            _clients.move_to_end(cache_key)
            return client
        # Per-read timeout as configured, but give up on connecting much sooner. Each SDK
        # takes its own Timeout type (they may be built on different httpx versions).
        connect = min(timeout, CONNECT_TIMEOUT_SECONDS)
        if name == "anthropic":
            client = anthropic.Anthropic(
                api_key=key, timeout=anthropic.Timeout(timeout, connect=connect), max_retries=SDK_MAX_RETRIES
            )
        else:
            try:
                import openai
            except ImportError:
                raise LLMSetupError(f"provider '{name}' needs the openai package: pip install openai") from None
            client = openai.OpenAI(
                api_key=key, base_url=base_url, timeout=openai.Timeout(timeout, connect=connect),
                max_retries=LOCAL_MAX_RETRIES if name == "ollama" else SDK_MAX_RETRIES,
            )
        _clients[cache_key] = client
        while len(_clients) > _MAX_CACHED_CLIENTS:
            _clients.popitem(last=False)
        return client


def _connection_error(provider: str, exc: Exception, timeout_type: type) -> LLMError:
    """A clear, secret-free LLMError for a provider that could not be reached or timed out.

    `timeout_type` is the SDK's APITimeoutError. A timeout while connecting (the httpx
    cause is a ConnectTimeout) is reported as "could not connect", not as a slow model.
    """
    connect_timeout = type(exc.__cause__).__name__ == "ConnectTimeout"
    if isinstance(exc, timeout_type) and not connect_timeout:
        try:
            limit = f"{_timeout_seconds():g}"
        except LLMConfigError:
            limit = "the configured"
        return LLMError(
            f"{provider} did not respond within {limit} seconds; "
            "try a smaller model or raise LLM_TIMEOUT_SECONDS"
        )
    if provider == "ollama":
        return LLMError(
            "could not connect to the local Ollama server: start it with `ollama serve` "
            "and pull a model (`ollama pull qwen2.5:3b`), or choose another provider and pass its API key"
        )
    return LLMError(f"could not connect to {provider}; check the network and try again")


def _provider_complete(
    prompt: str,
    system_message: str,
    json_mode: bool,
    schema: dict | None,
    temperature: float,
    max_tokens: int,
    *,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """The only function that touches provider SDKs. Returns the raw response text."""
    name = _resolve_provider(provider, api_key)
    model_name = _resolve_model(name, model)
    client = _get_client(api_key, name)
    if name == "anthropic":
        return _anthropic_complete(client, model_name, prompt, system_message, json_mode, schema, max_tokens)
    return _openai_compatible_complete(
        client, name, model_name, prompt, system_message, json_mode, schema, temperature, max_tokens
    )


def _anthropic_complete(
    client: Any, model_name: str, prompt: str, system_message: str, json_mode: bool,
    schema: dict | None, max_tokens: int,
) -> str:
    """Claude via the Messages API. `temperature` is not sent: current Claude models
    reject sampling parameters, and structured outputs already constrain the JSON."""
    system = system_message
    output_config: dict[str, Any] = {"effort": _effort()}
    if json_mode:
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        else:
            system = (system + "\n\n" if system else "") + (
                "Respond with a single JSON object only: no prose, no markdown fences."
            )
    kwargs: dict[str, Any] = {
        "model": model_name,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": output_config,
        "betas": [_FALLBACK_BETA],
        "fallbacks": "default",
    }
    if system:
        kwargs["system"] = system

    try:
        # Streaming keeps long generations inside the per-read timeout.
        with client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise LLMConfigError(f"the API key was rejected by the provider ({type(exc).__name__})") from exc
    except anthropic.NotFoundError as exc:
        raise LLMSetupError(f"model '{model_name}' not found") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"provider error: HTTP {exc.status_code} ({type(exc).__name__})") from exc
    except anthropic.APIConnectionError as exc:  # includes APITimeoutError
        raise _connection_error("anthropic", exc, anthropic.APITimeoutError) from exc
    except anthropic.AnthropicError as exc:
        raise LLMError(f"provider error: {type(exc).__name__}") from exc

    if message.stop_reason == "refusal":
        raise LLMOutputError("model declined the request")
    if message.stop_reason == "max_tokens":
        raise LLMOutputError("model output was truncated at max_tokens")
    text = "".join(
        getattr(block, "text", "") for block in message.content if block.type == "text"
    )
    if not text.strip():
        raise LLMOutputError("model returned no text")
    return text


# Request parameters that some OpenAI-compatible providers or models reject, and the
# simpler request to try instead. Each step is applied only if it fits the request.
_MAX_REQUESTS_PER_CALL = 5  # the original request plus up to four relaxations
_MAX_LEARNED_MODELS = 256
_learned_relaxations: dict[tuple[str, str], list[str]] = {}
_learned_lock = threading.Lock()


def _relaxation_for(kwargs: dict[str, Any], detail: str) -> str | None:
    """The relaxation that answers a BadRequestError message, or None if it is unrelated."""
    if "temperature" in kwargs and "temperature" in detail:
        return "drop_temperature"
    if "max_tokens" in kwargs and "max_tokens" in detail:
        return "use_max_completion_tokens"
    if "max_completion_tokens" in kwargs and "max_completion_tokens" in detail:
        return "use_max_tokens"
    if "response_format" in kwargs and any(w in detail for w in ("response_format", "json", "schema")):
        return "json_object" if kwargs["response_format"]["type"] == "json_schema" else "drop_response_format"
    return None


def _apply_relaxation(kwargs: dict[str, Any], step: str) -> None:
    """Simplify the request in place; a step that does not fit this request is skipped."""
    if step == "drop_temperature":
        kwargs.pop("temperature", None)
    elif step == "use_max_completion_tokens" and "max_tokens" in kwargs:
        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
    elif step == "use_max_tokens" and "max_completion_tokens" in kwargs:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
    elif step == "json_object" and kwargs.get("response_format", {}).get("type") == "json_schema":
        kwargs["response_format"] = {"type": "json_object"}
    elif step == "drop_response_format":
        kwargs.pop("response_format", None)


def _remember_relaxation(key: tuple[str, str], step: str) -> None:
    with _learned_lock:
        if key not in _learned_relaxations and len(_learned_relaxations) >= _MAX_LEARNED_MODELS:
            return
        steps = _learned_relaxations.setdefault(key, [])
        if step not in steps:
            steps.append(step)


def _openai_compatible_complete(
    client: Any, provider: str, model_name: str, prompt: str, system_message: str,
    json_mode: bool, schema: dict | None, temperature: float, max_tokens: int,
) -> str:
    """Any OpenAI-compatible chat-completions API (OpenAI, Gemini, Groq, OpenRouter, ...).

    Starts with strict JSON-schema output and degrades parameter by parameter when a
    provider or model rejects one (temperature, max_tokens, json_schema, json_object).
    The JSON hardening and pydantic validation downstream cover the weaker modes.
    """
    import openai

    system = system_message
    if json_mode:
        hint = "Respond with a single JSON object only: no prose, no markdown fences."
        if schema:
            hint += " It must match this JSON Schema:\n" + json.dumps(schema)
        system = (system + "\n\n" if system else "") + hint
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {"model": model_name, "messages": messages, "temperature": temperature}
    # OpenAI's own API wants max_completion_tokens (reasoning models reject max_tokens).
    kwargs["max_completion_tokens" if provider == "openai" else "max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = (
            {"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}}
            if schema
            else {"type": "json_object"}
        )

    # Replay what this provider and model rejected before, saving a failed round trip each.
    learned_key = (provider, model_name)
    for step in _learned_relaxations.get(learned_key, ()):
        _apply_relaxation(kwargs, step)

    response = None
    try:
        for _ in range(_MAX_REQUESTS_PER_CALL):
            try:
                response = client.chat.completions.create(**kwargs)
                break
            except openai.BadRequestError as exc:
                step = _relaxation_for(kwargs, str(exc).lower())
                if step is None:
                    raise
                _apply_relaxation(kwargs, step)
                _remember_relaxation(learned_key, step)
                logger.info("provider %s rejected a parameter; retrying with %s", provider, step)
    except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
        raise LLMConfigError(f"the API key was rejected by {provider} ({type(exc).__name__})") from exc
    except openai.NotFoundError as exc:
        hint = f": pull it with `ollama pull {model_name}` or set OLLAMA_MODEL" if provider == "ollama" else ""
        raise LLMSetupError(f"model '{model_name}' not found at {provider}{hint}") from exc
    except openai.APIStatusError as exc:
        raise LLMError(f"{provider} error: HTTP {exc.status_code} ({type(exc).__name__})") from exc
    except openai.APIConnectionError as exc:  # includes APITimeoutError
        raise _connection_error(provider, exc, openai.APITimeoutError) from exc
    except openai.OpenAIError as exc:
        raise LLMError(f"{provider} error: {type(exc).__name__}") from exc
    if response is None:
        raise LLMError(f"{provider} rejected the request parameters")

    if not response.choices:
        raise LLMOutputError("model returned no choices")
    choice = response.choices[0]
    message = choice.message
    if getattr(message, "refusal", None):
        raise LLMOutputError("model declined the request")
    if choice.finish_reason == "length":
        raise LLMOutputError("model output was truncated at max_tokens")
    if choice.finish_reason == "content_filter":
        raise LLMOutputError("model output was blocked by a content filter")
    text = message.content or ""
    if not isinstance(text, str) or not text.strip():
        raise LLMOutputError("model returned no text")
    return text


# --------------------------------------------------------------------------- JSON hardening

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?\s*```$", re.DOTALL)


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text.strip()


def _coerce_json_object(raw: Any) -> dict:
    """Turn a model response into a dict, repairing common formatting damage."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        raise LLMOutputError(f"expected a JSON object, got {type(raw).__name__}")

    text = _strip_fences(raw.strip().lstrip("﻿").strip())
    value: Any = None
    try:
        value = json.loads(text)
        if isinstance(value, str):  # double-encoded JSON
            value = json.loads(value.strip())
    except (json.JSONDecodeError, ValueError):
        value = None
    if not isinstance(value, dict):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                value = json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                value = None
    if not isinstance(value, dict):
        raise LLMOutputError("model output is not a JSON object")
    return value


# --------------------------------------------------------------------------- call_llm


def call_llm(
    prompt: str,
    system_message: str = "",
    json_mode: bool = True,
    *,
    schema: dict | None = None,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict | str:
    """Send one prompt to the LLM. JSON mode returns a dict; text mode returns a str.

    Bring your own key and model: `api_key`, `provider` (see PROVIDERS) and `model`
    override the environment for this call. With a key but no provider, the provider
    is detected from the key prefix.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if not isinstance(system_message, str):
        raise ValueError("system_message must be a string")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")
    _check_llm_args(api_key, provider, model)
    return _complete_with_retries(
        prompt, system_message, json_mode, schema, temperature, max_tokens,
        _coerce_json_object if json_mode else _require_text,
        api_key=api_key, provider=provider, model=model,
    )


def _require_text(raw: Any) -> str:
    if not isinstance(raw, str):
        raise LLMOutputError(f"expected text, got {type(raw).__name__}")
    return raw


def _complete_with_retries(
    prompt: str,
    system_message: str,
    json_mode: bool,
    schema: dict | None,
    temperature: float,
    max_tokens: int,
    parse: Callable[[Any], T],
    *,
    api_key: str | None,
    provider: str | None,
    model: str | None,
) -> T:
    """Call the provider and `parse` its output, re-asking on unusable output.

    `parse` raises LLMOutputError for output it cannot use (bad JSON, failed schema
    validation, ...). Every kind of unusable output shares one budget of MAX_ATTEMPTS
    model calls. Provider and config errors are raised at once, never retried here (the
    SDK already retries transient HTTP failures), and no other exception type escapes.
    """
    last_error: LLMOutputError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _provider_complete(
                prompt, system_message, json_mode, schema, temperature, max_tokens,
                api_key=api_key, provider=provider, model=model,
            )
            return parse(raw)
        except LLMOutputError as exc:
            last_error = exc
            logger.warning("LLM attempt %d/%d: unusable output (%s)", attempt, MAX_ATTEMPTS, exc)
        except LLMError:
            raise
        except Exception as exc:  # never let an unexpected type escape
            logger.error("LLM attempt %d: unexpected %s", attempt, type(exc).__name__)
            raise LLMError(f"unexpected error: {type(exc).__name__}") from exc
    raise LLMOutputError(f"unusable output after {MAX_ATTEMPTS} attempts: {last_error}")


# --------------------------------------------------------------------------- analysis


class _Anomaly(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str
    category: Literal[
        "data_retention", "access_control", "security", "privacy_consent",
        "reporting", "governance", "other",
    ]
    severity: Literal["low", "medium", "high", "critical"]
    gap_type: Literal["non_compliant", "insufficient_information"]
    regulation_requirement: str
    regulation_excerpt: str
    current_state: str
    gap_description: str
    recommended_remediation: str
    # Optional: older or weaker models may omit it. Checked against the real keys later.
    state_fields: list[str] = []

    @field_validator("state_fields", mode="before")
    @classmethod
    def _string_list(cls, value: Any) -> list[str]:
        """Lenient: a malformed state_fields never fails the finding, it just becomes []."""
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        return [v for v in value if isinstance(v, str) and v.strip()]

    @field_validator("category", "severity", "gap_type", mode="before")
    @classmethod
    def _normalize_enum(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower().replace("-", "_").replace(" ", "_")
        return value

    @field_validator("title", "gap_description", "regulation_requirement", "recommended_remediation")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value


class _AnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    anomalies: list[_Anomaly]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip()
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space].rstrip()
    return cut + "…"


# Excerpt grounding lives in grounding.py; these aliases keep the engine's internal names.
_truncate_verbatim = grounding.truncate_verbatim
_normalized_with_map = grounding.normalized_with_map
_RegulationIndex = grounding.RegulationIndex
_SENTENCE_SPLIT_RE = grounding.SENTENCE_SPLIT_RE
_WORD_RE = grounding.WORD_RE


_MAX_STATE_PATH_DEPTH = 4


def _state_key_paths(state: Any, prefix: str = "", depth: int = 0) -> list[str]:
    """Every key of the company state, nested keys as dotted paths ("security.encryption")."""
    if not isinstance(state, dict) or depth >= _MAX_STATE_PATH_DEPTH:
        return []
    paths: list[str] = []
    for key, value in state.items():
        path = f"{prefix}{key}"
        paths.append(path)
        paths += _state_key_paths(value, path + ".", depth + 1)
    return paths


def _resolve_state_fields(claimed: list[str], current_state: str, known: list[str]) -> list[str]:
    """The company-state keys a finding refers to, restricted to keys that really exist.

    The model's `state_fields` are kept when they name a real key (matched ignoring case);
    keys quoted in `current_state` (e.g. "data_retention_days = 30") are added, so the
    field is filled even when the model leaves it out. Order: model's first, no repeats.
    """
    by_folded = {path.casefold(): path for path in known}
    fields: list[str] = []
    for name in claimed:
        path = by_folded.get(name.strip().casefold())
        if path and path not in fields:
            fields.append(path)
    for path in known:
        if path not in fields and re.search(rf"(?<![\w.]){re.escape(path)}(?!\w|\.\w)", current_state):
            fields.append(path)
    return fields


def _finalize_anomalies(items: list[_Anomaly], regulation_text: str, state: dict) -> list[dict]:
    """Dedupe, truncate titles, ground excerpts, resolve state fields, sort by severity,
    cap at 25 and assign ids.

    Output keys: id, the ANOMALY_ITEM_FIELDS, then the additive state_fields,
    excerpt_match, excerpt_score and excerpt_span (see grounding.py).
    """
    regulation = _RegulationIndex(regulation_text)
    known_paths = _state_key_paths(state)
    seen: set[tuple[str, str]] = set()
    cleaned: list[dict] = []
    for item in items:
        record = item.model_dump()
        key = (record["title"].casefold(), record["gap_description"].casefold())
        if key in seen:
            continue
        seen.add(key)
        record["title"] = _truncate(record["title"], MAX_TITLE_CHARS)
        grounded = regulation.ground(record["regulation_excerpt"])
        record["regulation_excerpt"] = grounded.text
        record["excerpt_match"] = grounded.match
        record["excerpt_score"] = grounded.score
        record["excerpt_span"] = list(grounded.span) if grounded.span else None
        if record["gap_type"] == "insufficient_information" or not record["current_state"]:
            record["current_state"] = NOT_SPECIFIED
        # Infer keys only from a real description of the state, never from the sentinel
        # (its words, e.g. "company", could otherwise match a key).
        described = "" if record["current_state"] == NOT_SPECIFIED else record["current_state"]
        record["state_fields"] = _resolve_state_fields(record["state_fields"], described, known_paths)
        cleaned.append(record)

    cleaned.sort(key=lambda r: SEVERITY_RANK[r["severity"]])  # stable
    cleaned = cleaned[:MAX_ANOMALIES]
    return [
        {"id": f"ANOM-{i:03d}", **{k: r[k] for k in ANOMALY_ITEM_FIELDS + ADDITIVE_FIELDS}}
        for i, r in enumerate(cleaned, start=1)
    ]


def build_coverage(regulation_text: str, anomalies: list[dict]) -> list[dict]:
    """Clause-by-clause coverage of the regulation by grounded findings (see grounding.py).

    Each item: {"id": "CL-001", "text": str, "span": [start, end],
    "status": "gap" | "needs_info" | "not_flagged", "finding_ids": [str, ...]}.
    """
    if not isinstance(regulation_text, str) or not regulation_text.strip():
        raise ValueError("regulation_text must be a non-empty string")
    if not isinstance(anomalies, list):
        raise ValueError("anomalies must be a list")
    return grounding.build_coverage(regulation_text, anomalies)


def _validate_analysis_inputs(regulation_text: Any, state: Any) -> str:
    if not isinstance(regulation_text, str):
        raise ValueError("regulation_text must be a string")
    if not regulation_text.strip():
        raise ValueError("regulation_text must not be empty")
    if len(regulation_text) > MAX_REGULATION_CHARS:
        raise ValueError(f"regulation_text exceeds {MAX_REGULATION_CHARS} characters")
    if not isinstance(state, dict):
        raise ValueError("current_company_state_dict must be a dict")
    if not state:
        raise ValueError("current_company_state_dict must not be empty")
    try:
        state_json = json.dumps(state, indent=2, sort_keys=True, default=str)
    except Exception as exc:  # TypeError, ValueError, RecursionError, a failing __str__ ...
        raise ValueError(
            f"current_company_state_dict is not JSON-serializable or too deeply nested ({type(exc).__name__})"
        ) from None
    if len(state_json) > MAX_STATE_CHARS:
        raise ValueError(f"current_company_state_dict exceeds {MAX_STATE_CHARS} serialized characters")
    return state_json


def analyze_compliance_gap(
    regulation_text: str,
    current_company_state_dict: dict,
    *,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """Compare a regulation against the company's current state and list the gaps.

    Returns anomaly dicts sorted most-severe first, with ids ANOM-001, ANOM-002, ...
    An empty list means no gaps were found. `api_key`, `provider` and `model` let the end
    user run on their own key and model with any supported provider (default: environment).
    Raises ValueError on bad input and LLMError (or a subclass) when the model cannot
    produce a valid result. With AI_ENGINE_DEMO=1, recorded output is replayed offline.
    """
    report = analyze_compliance_report(
        regulation_text, current_company_state_dict, api_key=api_key, provider=provider, model=model
    )
    return report["anomalies"]


def analyze_compliance_report(
    regulation_text: str,
    current_company_state_dict: dict,
    *,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """analyze_compliance_gap plus the model that produced the findings.

    Returns {"anomalies": [...], "model": str | None}; `model` is the LLM model that was
    called (resolved the same way as for the audit log), or None in demo mode, where no
    LLM is called. Same inputs and errors as analyze_compliance_gap.
    """
    state_json = _validate_analysis_inputs(regulation_text, current_company_state_dict)
    _check_llm_args(api_key, provider, model)
    if _demo_mode():
        recorded = _demo_analysis(regulation_text, current_company_state_dict)
        return {"anomalies": _finalize_anomalies(recorded, regulation_text, current_company_state_dict), "model": None}
    prompt = build_analysis_prompt(regulation_text, state_json)
    # Bad JSON and schema-invalid JSON share one budget of MAX_ATTEMPTS model calls.
    parsed = _complete_with_retries(
        prompt, ANALYSIS_SYSTEM_PROMPT, True, ANALYSIS_SCHEMA, 0.0, DEFAULT_MAX_TOKENS,
        _parse_analysis, api_key=api_key, provider=provider, model=model,
    )
    anomalies = _finalize_anomalies(parsed.anomalies, regulation_text, current_company_state_dict)
    return {"anomalies": anomalies, "model": _model_label(api_key, provider, model)}


def _demo_mode() -> bool:
    """True when AI_ENGINE_DEMO opts in to the offline demo mode (no LLM is ever called)."""
    _load_dotenv()
    return os.environ.get("AI_ENGINE_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def _demo_analysis(regulation_text: str, state: dict) -> list[_Anomaly]:
    """Recorded findings for a bundled sample input, through the real schema validation."""
    recorded = demo_fixtures.recorded_analysis(regulation_text, state)
    if recorded is None:
        raise LLMError(
            "offline demo mode (AI_ENGINE_DEMO=1) only has recorded results for the sample regulation "
            "with the default company state; unset AI_ENGINE_DEMO and configure a model to analyze other input"
        )
    logger.warning("AI_ENGINE_DEMO is on: returning recorded sample output, no LLM was called")
    return _parse_analysis(recorded).anomalies


def _parse_analysis(raw: Any) -> _AnalysisPayload:
    """Parse and schema-validate the analysis output; LLMOutputError if it is unusable."""
    try:
        return _AnalysisPayload.model_validate(_coerce_json_object(raw))
    except ValidationError as exc:
        raise LLMOutputError(f"analysis output failed schema validation ({exc.error_count()} errors)") from None


# --------------------------------------------------------------------------- audit trail

_OWNER_BY_CATEGORY = {
    "data_retention": "Data Protection Officer",
    "access_control": "Chief Information Security Officer",
    "security": "Chief Information Security Officer",
    "privacy_consent": "Data Protection Officer",
    "reporting": "Head of Compliance",
    "governance": "Chief Compliance Officer",
    "other": "Head of Compliance",
}
_TIMEFRAME_BY_SEVERITY = {
    "critical": "within 7 days",
    "high": "within 14 days",
    "medium": "within 30 days",
    "low": "within 90 days",
}
_GAP_TYPE_LABEL = {
    "non_compliant": "Non-compliant",
    "insufficient_information": "Insufficient information",
}
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?\b")


def _normalize_audit_items(anomalies: Any) -> list[dict]:
    if not isinstance(anomalies, list):
        raise ValueError("anomalies must be a list")
    items: list[dict] = []
    for position, item in enumerate(anomalies, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"anomaly #{position} is not a dict")
        for field in ("title", "gap_description"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"anomaly #{position} has no {field}")
        record = dict(item)
        for key in OUTPUT_KEYS:
            value = record.get(key)
            record[key] = value.strip() if isinstance(value, str) else ("" if value is None else str(value))
        record["severity"] = record["severity"].lower() or "medium"
        record["category"] = record["category"].lower() or "other"
        record["gap_type"] = record["gap_type"].lower() or "non_compliant"
        record["current_state"] = record["current_state"] or NOT_SPECIFIED
        items.append(record)

    used = {r["id"] for r in items if r["id"]}
    counter = 0
    for record in items:
        if not record["id"]:
            counter += 1
            while f"ANOM-{counter:03d}" in used:
                counter += 1
            record["id"] = f"ANOM-{counter:03d}"
            used.add(record["id"])
    return items


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _audit_header(iso: str, report_id: str, model: str) -> list[str]:
    return [
        "# Compliance Audit Log",
        f"**Report ID:** {report_id}",
        f"**Generated (UTC):** {iso}",
        f"**Detected by:** AI Compliance Engine (model: {model})",
        "",
    ]


def _render_no_gaps(iso: str, report_id: str, model: str) -> str:
    lines = _audit_header(iso, report_id, model) + [
        "## 1. Executive Summary",
        "",
        "No compliance gaps detected. The automated gap analysis compared the company state "
        "against every obligation in the supplied regulation text and found no anomalies. "
        "No remediation is required at this time.",
        "",
        "## 2. Findings Summary",
        "",
        "| ID | Title | Severity | Gap Type | Status |",
        "| --- | --- | --- | --- | --- |",
        "| — | No compliance gaps detected | — | — | — |",
        "",
        "## 3. Detailed Findings",
        "",
        "No findings. The company state is compliant with the supplied regulation text.",
        "",
        "## 4. Audit Trail",
        "",
        "| Timestamp (UTC) | Event | Actor |",
        "| --- | --- | --- |",
        f"| {iso} | Compliance gap analysis completed: 0 anomalies detected | AI Compliance Engine |",
        f"| {iso} | Audit log {report_id} generated | AI Compliance Engine |",
        "",
    ]
    return "\n".join(lines)


def _remediation_steps(text: str) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return ["Define and implement a remediation plan for this gap."]
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    return parts or [text]


def _render_audit_fallback(anomalies: list[dict], iso: str, report_id: str, model: str) -> str:
    """Deterministic audit log that follows the required structure, with no LLM involved."""
    counts = {s: sum(1 for a in anomalies if a["severity"] == s) for s in SEVERITY_RANK}
    breakdown = ", ".join(f"{counts[s]} {s}" for s in SEVERITY_RANK if counts[s])
    other = len(anomalies) - sum(counts.values())
    if other:
        breakdown += (", " if breakdown else "") + f"{other} unrated"
    top = [a for a in anomalies if a["severity"] in ("critical", "high")]
    posture = (
        f"Priority attention is required for {len(top)} critical or high severity finding(s), "
        f"led by {top[0]['id']} ({top[0]['title']})."
        if top
        else "No critical or high severity findings were detected."
    )
    lines = _audit_header(iso, report_id, model) + [
        "## 1. Executive Summary",
        "",
        f"The automated compliance gap analysis detected {len(anomalies)} anomal"
        f"{'y' if len(anomalies) == 1 else 'ies'} ({breakdown}). {posture} "
        "All findings are open and each has a proposed remediation plan below.",
        "",
        "## 2. Findings Summary",
        "",
        "| ID | Title | Severity | Gap Type | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for a in anomalies:
        gap_label = _GAP_TYPE_LABEL.get(a["gap_type"], a["gap_type"] or "Unspecified")
        lines.append(
            f"| {_cell(a['id'])} | {_cell(a['title'])} | {_cell(a['severity'].capitalize())} "
            f"| {_cell(gap_label)} | Open |"
        )
    lines += ["", "## 3. Detailed Findings", ""]
    for a in anomalies:
        owner = _OWNER_BY_CATEGORY.get(a["category"], "Head of Compliance")
        timeframe = _TIMEFRAME_BY_SEVERITY.get(a["severity"], "within 30 days")
        excerpt = a["regulation_excerpt"] or "Not provided"
        lines += [
            f"### {a['id']} — {a['title']}",
            "",
            f"- **Detected at (UTC):** {iso}",
            "- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text",
            f"- **Severity:** {a['severity'].capitalize() or 'Unrated'} | **Category:** {a['category'] or 'other'}",
            f"- **Regulation requirement:** {a['regulation_requirement'] or 'Not provided'}",
            f"- **Regulation excerpt:** \"{' '.join(excerpt.split())}\"",
            f"- **Current state:** {a['current_state']}",
            f"- **Gap:** {a['gap_description']}",
            "- **Proposed remediation plan:**",
        ]
        steps = _remediation_steps(a["recommended_remediation"])
        steps.append("Verify the fix with evidence and close the finding in the compliance register.")
        lines += [f"  {n}. {step}" for n, step in enumerate(steps, start=1)]
        lines += [
            f"  - **Suggested owner:** {owner}",
            f"  - **Target timeframe:** {timeframe} of the report date",
            "- **Status:** Open",
            "",
        ]
    lines += [
        "## 4. Audit Trail",
        "",
        "| Timestamp (UTC) | Event | Actor |",
        "| --- | --- | --- |",
        f"| {iso} | Compliance gap analysis completed: {len(anomalies)} anomalies detected | AI Compliance Engine |",
    ]
    for a in anomalies:
        lines.append(f"| {iso} | {_cell(a['id'])} logged ({_cell(a['severity'] or 'unrated')}) | AI Compliance Engine |")
    lines += [f"| {iso} | Audit log {report_id} generated | AI Compliance Engine |", ""]
    return "\n".join(lines)


def _strip_markdown_fences(text: str) -> str:
    text = _strip_fences(text)
    # Drop any preamble the model wrote before the title line.
    match = re.search(r"^# Compliance Audit Log\s*$", text, re.MULTILINE)
    if match and match.start() > 0:
        text = text[match.start():]
    # A fenced block with prose around it leaves an unmatched closing fence: cut from there.
    fences = list(re.finditer(r"^\s*```[^\n]*$", text, re.MULTILINE))
    if len(fences) % 2 == 1:
        text = text[: fences[-1].start()]
    return text.strip() + "\n"


def _audit_is_valid(markdown: str, iso: str, anomalies: list[dict]) -> bool:
    """Section 5.3 checks, plus required headings and no invented dates or times."""
    if not markdown.startswith("# Compliance Audit Log"):
        return False
    if iso not in markdown:
        return False
    if any(a["id"] not in markdown for a in anomalies):
        return False
    for heading in ("## 1. Executive Summary", "## 2. Findings Summary", "## 3. Detailed Findings", "## 4. Audit Trail"):
        if heading not in markdown:
            return False
    # Dates that appear in the input anomalies may be quoted; any other date or time is invented.
    haystack = " ".join(" ".join(str(v).split()) for a in anomalies for v in a.values())
    allowed = set(_DATE_RE.findall(haystack))
    for found in _DATE_RE.findall(" ".join(markdown.replace(iso, " ").split())):
        if found not in allowed:
            return False
    return True


def _resolve_generated_at(generated_at: Any) -> datetime:
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    if not isinstance(generated_at, datetime):
        raise ValueError("generated_at must be a datetime or None")
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    try:
        return generated_at.astimezone(timezone.utc).replace(microsecond=0)
    except (OverflowError, OSError, ValueError):
        raise ValueError("generated_at is out of range") from None


def generate_audit_trail(
    anomalies: list[dict],
    generated_at: datetime | None = None,
    *,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """Turn anomalies into a formal Markdown compliance audit log.

    Always returns a Markdown string that follows the required structure. An empty list
    produces a deterministic "no gaps" log without calling the LLM. If the model's output
    fails validation twice, a deterministic renderer is used instead. `api_key`, `provider`
    and `model` select the user's own key and model (default: environment). Raises ValueError on
    bad input and LLMError if the provider cannot be reached. With AI_ENGINE_DEMO=1 the
    deterministic renderer is used and no LLM is called. Raw HTML is never emitted: every
    "<" is escaped, so untrusted regulation or company text cannot inject markup.
    """
    report = generate_audit_report(anomalies, generated_at, api_key=api_key, provider=provider, model=model)
    return report["markdown"]


def generate_audit_report(
    anomalies: list[dict],
    generated_at: datetime | None = None,
    *,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """generate_audit_trail plus how the log was produced.

    Returns {"markdown": str, "renderer": "llm" | "deterministic", "model": str | None}.
    `renderer` says who wrote the log: the LLM, or the deterministic renderer (no gaps,
    demo mode, or the LLM's log failed validation). `model` is the LLM model that was
    called for this log, or None when no LLM was called (no gaps, demo mode). Same inputs
    and errors as generate_audit_trail.
    """
    markdown, renderer, model_used = _audit_markdown(
        anomalies, generated_at, api_key=api_key, provider=provider, model=model
    )
    return {"markdown": _escape_html(markdown), "renderer": renderer, "model": model_used}


def _escape_html(markdown: str) -> str:
    """Neutralize raw HTML in the audit log; "&lt;" still renders as "<" in Markdown.

    Escaping "<" is enough: without it no tag can open, and Markdown's own syntax (tables,
    headings, "**", blockquote ">") does not need it. Applied after validation, so the
    date and structure checks see the text as written.
    """
    return markdown.replace("<", "&lt;")


def _audit_markdown(
    anomalies: Any, generated_at: datetime | None, *, api_key: str | None, provider: str | None,
    model: str | None,
) -> tuple[str, str, str | None]:
    """The audit log before HTML escaping, the renderer that wrote it, and the model called."""
    items = _normalize_audit_items(anomalies)
    _check_llm_args(api_key, provider, model)
    when = _resolve_generated_at(generated_at)
    iso = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    report_id = "AUD-" + when.strftime("%Y%m%dT%H%M%SZ")
    if _demo_mode():  # offline: the deterministic renderer, labelled as such
        model_label = demo_fixtures.DEMO_MODEL_LABEL
        if not items:
            return _render_no_gaps(iso, report_id, model_label), "deterministic", None
        return _render_audit_fallback(items, iso, report_id, model_label), "deterministic", None
    model_label = _model_label(api_key, provider, model)

    if not items:
        return _render_no_gaps(iso, report_id, model_label), "deterministic", None

    payload = [{k: r[k] for k in OUTPUT_KEYS} for r in items]
    prompt = build_audit_prompt(
        json.dumps(payload, indent=2, ensure_ascii=False), iso, report_id, model_label
    )
    for attempt in range(1, AUDIT_ATTEMPTS + 1):
        try:
            text = call_llm(
                prompt, AUDIT_SYSTEM_PROMPT, json_mode=False, api_key=api_key, provider=provider, model=model
            )
        except LLMOutputError as exc:
            logger.warning("generate_audit_trail attempt %d/%d: %s", attempt, AUDIT_ATTEMPTS, exc)
            break  # call_llm already retried; go straight to the fallback
        markdown = _strip_markdown_fences(str(text))
        if _audit_is_valid(markdown, iso, items):
            return markdown, "llm", model_label
        logger.warning("generate_audit_trail attempt %d/%d: output failed validation", attempt, AUDIT_ATTEMPTS)

    logger.warning("generate_audit_trail: using deterministic fallback renderer")
    return _render_audit_fallback(items, iso, report_id, model_label), "deterministic", model_label


# --------------------------------------------------------------------------- smoke test

_DEMO_REGULATION = demo_fixtures.SMOKE_REGULATION
_DEMO_STATE = demo_fixtures.SMOKE_STATE

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    found = analyze_compliance_gap(_DEMO_REGULATION, _DEMO_STATE)
    print(json.dumps(found, indent=2, ensure_ascii=False))
    print()
    print(generate_audit_trail(found))
