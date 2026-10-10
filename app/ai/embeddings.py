import os
from google import genai
from app.config import GEMINI_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSION


def get_genai_client(api_key: str | None = None) -> genai.Client:
    key = api_key or GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
    return genai.Client(api_key=key)


def create_embedding(
    text: str,
    client: genai.Client | None = None,
    model: str | None = None,
) -> list[float]:
    """
    Generate an embedding vector for the provided text using Gemini Embeddings.

    Args:
        text: Input string to embed.
        client: Optional genai.Client instance for testing or custom configuration.
        model: Optional model name override.

    Returns:
        Vector of floats matching EMBEDDING_DIMENSION.
    """
    if not text or not text.strip():
        return [0.0] * EMBEDDING_DIMENSION

    genai_client = client or get_genai_client()
    target_model = model or EMBEDDING_MODEL

    response = genai_client.models.embed_content(
        model=target_model,
        contents=text,
    )

    return response.embeddings[0].values