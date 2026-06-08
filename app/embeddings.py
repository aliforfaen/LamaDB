"""OpenAI embedding service for LamaDB documents.

Uses text-embedding-3-small (1536 dims) via the openai Python package.
Falls back gracefully when no API key is configured.
"""
import logging
from app.config import settings

logger = logging.getLogger(__name__)

# Lazy-initialized async client
_client = None


def _get_client():
    """Return (or create) a shared AsyncOpenAI client."""
    global _client
    if _client is None and settings.openai_api_key:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _prepare_text(title: str | None, content: str | None) -> str:
    """Concatenate title + content, truncate to safe length for the embedding model."""
    parts = []
    if title:
        parts.append(title)
    if content:
        parts.append(content)
    text = "\n".join(parts)
    # text-embedding-3-small has an 8191 token limit (~32K chars safely)
    return text[:8000]


async def generate_embedding(text: str) -> list[float] | None:
    """Generate a 1536-dim embedding for a single text.

    Returns None if OpenAI is not configured or the request fails.
    """
    client = _get_client()
    if client is None:
        return None

    try:
        resp = await client.embeddings.create(
            model=settings.embedding_model,
            input=text,
        )
        return resp.data[0].embedding
    except Exception:
        logger.warning("OpenAI embedding failed for text len=%d", len(text), exc_info=True)
        return None


async def generate_embeddings_batch(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for a batch of texts.

    OpenAI supports up to 2048 inputs per batch request.
    Returns a list of embeddings (or None per-text on failure).
    """
    client = _get_client()
    if client is None:
        return [None] * len(texts)

    try:
        resp = await client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
        )
        # Response data is ordered the same as input
        return [item.embedding for item in resp.data]
    except Exception:
        logger.warning(
            "OpenAI batch embedding failed for %d texts", len(texts), exc_info=True
        )
        return [None] * len(texts)


async def embed_document_async(doc_id: str, title: str | None, content: str | None) -> None:
    """Fire-and-forget: generate embedding and update the document row.

    Meant to be spawned as a background task via asyncio.create_task().
    Never raises — logs warnings on failure.
    """
    from app.db import get_pool

    text = _prepare_text(title, content)
    embedding = await generate_embedding(text)
    if embedding is None:
        return

    embedding_str = f"[{','.join(str(v) for v in embedding)}]"
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE documents SET embedding = $1::vector WHERE id = $2",
                embedding_str,
                doc_id,
            )
    except Exception:
        logger.warning(
            "Failed to store embedding for doc %s", doc_id, exc_info=True
        )
