"""all-mpnet-base-v2 embedder using sentence-transformers.

The model is downloaded from HuggingFace on first use (~420 MB) and cached
in the default sentence-transformers cache directory.  Subsequent runs load
from cache instantly.

Install the extra dependency before use:

    uv sync --extra mpnet

or:

    pip install sentence-transformers
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer as _ST


class MpnetEmbedder:
    """Local embedder using ``sentence-transformers/all-mpnet-base-v2``.

    Produces 768-dimensional L2-normalised vectors.  The underlying model is
    loaded lazily on the first call to :meth:`embed` or :meth:`embed_batch`,
    so importing this module is always cheap.
    """

    MODEL_NAME: str = "sentence-transformers/all-mpnet-base-v2"
    DIMENSIONS: int = 768

    def __init__(self) -> None:
        self._model: _ST | None = None

    # ── Protocol properties ────────────────────────────────────────────────

    @property
    def dimensions(self) -> int:
        return self.DIMENSIONS

    @property
    def model_name(self) -> str:
        return self.MODEL_NAME

    # ── Public interface ───────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """Embed a single string and return a 768-dim normalised vector."""
        model = self._load()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings.  Returns an empty list for empty input."""
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    # ── Internal ───────────────────────────────────────────────────────────

    def _load(self) -> "_ST":
        """Load the model on first call; return the cached instance thereafter."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed. "
                    "Run: uv sync --extra mpnet  (or: pip install sentence-transformers)"
                ) from exc
            self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model
