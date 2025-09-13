import os
from typing import Optional


def _read_env(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        return os.getenv(key, default)
    except Exception:
        return default


def classify_yes_no(
    prompt: str,
    *,
    provider: str = "openai",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 20.0,
) -> Optional[bool]:
    """Return True if LLM says 'Yes', False if 'No', else None."""
    provider = (provider or "openai").lower()
    if provider != "openai":
        # Unsupported provider for now
        return None

    # Prefer explicit api_key/model then environment
    api_key = api_key or _read_env("OPENAI_API_KEY")
    if not api_key:
        return None

    model = model or _read_env("OPENAI_MODEL", "gpt-4o-mini")

    try:
        # Lazy import so the package is only required if used
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Answer strictly Yes or No."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=2,
            timeout=timeout,
        )
        text = (resp.choices[0].message.content or "").lower()
        return True if text.startswith("yes") else False if text.startswith("no") else None
    except Exception:
        return None
