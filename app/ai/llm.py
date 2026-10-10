import os
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import (
    GEMINI_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    LLM_MAX_RETRIES,
)


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
    max_retries: int | None = None,
    api_key: str | None = None,
) -> ChatGoogleGenerativeAI:
    """
    Factory creating a configured ChatGoogleGenerativeAI instance.

    Args:
        model: Model name (defaults to LLM_MODEL in config).
        temperature: Sampling temperature (defaults to LLM_TEMPERATURE).
        timeout: Request timeout in seconds (defaults to LLM_TIMEOUT).
        max_retries: Number of retry attempts on failure.
        api_key: API key override (defaults to GEMINI_API_KEY).

    Returns:
        ChatGoogleGenerativeAI instance.
    """
    key = api_key or GEMINI_API_KEY or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise ValueError(
            "GEMINI_API_KEY is not configured. Please set GEMINI_API_KEY in your .env file or environment."
        )

    return ChatGoogleGenerativeAI(
        model=model or LLM_MODEL,
        temperature=temperature if temperature is not None else LLM_TEMPERATURE,
        timeout=timeout or LLM_TIMEOUT,
        max_retries=max_retries if max_retries is not None else LLM_MAX_RETRIES,
        google_api_key=key,
    )


# Default module-level LLM singleton for standard use.
# Initialized safely so module imports do not crash when API key is missing (e.g., in unit tests).
try:
    llm = get_llm()
except ValueError:
    llm = None