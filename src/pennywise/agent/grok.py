"""Grok (xAI) client and LLM settings, shared by the agent loop and the narrator.

xAI's API is OpenAI-compatible, so this uses the `openai` SDK pointed at api.x.ai.
Settings come from the environment / .env (read-only to code), like payments/config.py:

  GROK_API_KEY   required for any LLM call
  GROK_MODEL     model name, e.g. grok-4 (check docs.x.ai for current names)
  AGENT_MODE     "llm" = Grok runs the cycle; anything else = deterministic cycle.py (fail safe)

Run `uv run python -m pennywise.agent.grok` to check the key and model with one tiny call.
"""

from openai import OpenAI

from pennywise.payments.config import ConfigError, env

XAI_BASE_URL = "https://api.x.ai/v1"


def agent_mode() -> str:
    """'llm' only when explicitly set; otherwise the deterministic rule-based cycle."""
    return "llm" if (env("AGENT_MODE") or "").lower() == "llm" else "rule"


def model() -> str:
    name = env("GROK_MODEL")
    if name is None:
        raise ConfigError("GROK_MODEL is not set")
    return name


def client() -> OpenAI:
    """An OpenAI-SDK client for xAI. Never print or log the key."""
    key = env("GROK_API_KEY")
    if key is None:
        raise ConfigError("GROK_API_KEY is not set")
    return OpenAI(api_key=key, base_url=XAI_BASE_URL, timeout=60.0, max_retries=2)


def ping() -> str:
    """One tiny call to confirm the key and model work."""
    reply = client().chat.completions.create(
        model=model(),
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        max_tokens=10,
    )
    return reply.choices[0].message.content or ""


if __name__ == "__main__":
    print(f"agent mode: {agent_mode()}  model: {model()}")
    print(f"grok says: {ping()!r}")
