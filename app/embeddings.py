"""Local CPU-only embedding service for LamaDB documents.

Uses sentence-transformers/all-MiniLM-L6-v2 (384 dims).
Model is lazy-loaded on first call to avoid blocking startup.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# Lazy-initialized model
_model = None


def _get_model():
    """Return (or create) a shared SentenceTransformer instance."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
        logger.info("Loaded local embedding model: all-MiniLM-L6-v2 (384 dims, CPU)")
    return _model


def _prepare_text(title: str | None, content: str | None) -> str:
    """Concatenate title + content, truncate to safe length for the embedding model."""
    parts = []
    if title:
        parts.append(title)
    if content:
        parts.append(content)
    text = "\n".join(parts)
    # all-MiniLM-L6-v2 has a 256 token limit (~1000 chars safely)
    return text[:1000]


async def generate_embedding(text: str) -> list[float]:
    """Generate a 384-dim embedding for a single text.

    Runs model.encode in a thread to avoid blocking the event loop.
    Never returns None — raises on model load failure.
    """
    model = _get_model()
    return (await asyncio.to_thread(model.encode, text)).tolist()


async def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts.

    Runs model.encode in one thread call.
    Returns a list of embeddings in the same order.
    """
    model = _get_model()
    embeddings = await asyncio.to_thread(model.encode, texts)
    return [emb.tolist() for emb in embeddings]


async def embed_document_async(doc_id: str, title: str | None, content: str | None) -> None:
    """Fire-and-forget: generate embedding and update the document row.

    Meant to be spawned as a background task via asyncio.create_task().
    Never raises — logs warnings on failure.
    """
    from app.db import get_pool

    text = _prepare_text(title, content)
    try:
        embedding = await generate_embedding(text)
    except Exception:
        logger.warning("Failed to generate embedding for doc %s", doc_id, exc_info=True)
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
