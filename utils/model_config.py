"""
LLM provider configuration with:
- Round-robin API key rotation across multiple OpenRouter keys
- Lazy client creation (avoids import-time hangs)
- Global concurrency limiter to prevent API hammering
- guarded_llm_call() helper used by all LLM call sites
"""

import os
import threading
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# ─────────────────────────────────────────────────────────
#  Collect all available API keys from .env
# ─────────────────────────────────────────────────────────
_api_keys: list = []
_primary = os.getenv("OPENROUTER_API_KEY", "")
if _primary.strip():
    _api_keys.append(_primary.strip())

for i in range(2, 11):
    key = os.getenv(f"OPENROUTER_API_KEY_{i}", "")
    if key.strip():
        _api_keys.append(key.strip())

if not _api_keys:
    raise RuntimeError("No OPENROUTER_API_KEY found in .env")

# ─────────────────────────────────────────────────────────
#  Lazy client pool — clients created on first use, not at import
# ─────────────────────────────────────────────────────────
_client_pool: list = [None] * len(_api_keys)   # slots, filled lazily
_pool_index = 0
_pool_lock = threading.Lock()


def _create_client(api_key: str):
    """Create an OpenAI client on demand (avoids import-time hangs)."""
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL, timeout=100.0)


def get_client():
    """
    Get an OpenAI client with round-robin key rotation.
    Thread-safe. Clients are created lazily on first use.
    """
    global _pool_index
    with _pool_lock:
        idx = _pool_index % len(_api_keys)
        _pool_index += 1
        if _client_pool[idx] is None:
            _client_pool[idx] = _create_client(_api_keys[idx])
        return _client_pool[idx]


# ─────────────────────────────────────────────────────────
#  Concurrency limiter — caps in-flight LLM calls across all users
# ─────────────────────────────────────────────────────────
MAX_CONCURRENT_LLM_CALLS = int(os.getenv("MAX_CONCURRENT_LLM_CALLS", "6"))
_llm_semaphore = threading.Semaphore(MAX_CONCURRENT_LLM_CALLS)


def get_llm_semaphore():
    return _llm_semaphore


# ─────────────────────────────────────────────────────────
#  guarded_llm_call — ALL LLM calls should go through this
# ─────────────────────────────────────────────────────────
def guarded_llm_call(messages, 
                     model="openai/gpt-oss-120b",
                     temperature=0.1, 
                     max_tokens=1000, 
                     **kwargs):
    """
    Make an LLM call with:
    1. Concurrency limiting (semaphore — blocks if too many in-flight)
    2. Round-robin API key rotation (spreads rate limits across keys)
    """
    with _llm_semaphore:
        c = get_client()
        return c.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )


# ─────────────────────────────────────────────────────────
#  Pydantic-AI model (lazy import to avoid import-time delays)
# ─────────────────────────────────────────────────────────
_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from pydantic_ai.models.openai import OpenAIModel
                from pydantic_ai.providers.openai import OpenAIProvider
                provider = OpenAIProvider(
                    api_key=_api_keys[0],
                    base_url=OPENROUTER_BASE_URL
                )
                _model = OpenAIModel(
                    provider=provider,
                    model_name="openai/gpt-oss-120b"
                )
    return _model
