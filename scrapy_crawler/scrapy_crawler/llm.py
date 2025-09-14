import os
from typing import Optional


def _read_env(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        return os.getenv(key, default)
    except Exception:
        return default


def complete_text(
    prompt: str,
    *,
    provider: str = "openai",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 30.0,
    max_tokens: int = 2048,
) -> Optional[str]:
    """Run a prompt and return raw text.

    Designed for cases where the caller instructs the model to return JSON.
    Returns None on failure.
    """
    provider = (provider or "openai").lower()
    if provider != "openai":
        return None

    api_key = api_key or _read_env("OPENAI_API_KEY")
    if not api_key:
        return None

    model = model or _read_env("OPENAI_MODEL", "gpt-4o-mini")

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Return only the answer. No explanations."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return None
