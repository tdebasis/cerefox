"""Cloud API embedder — OpenAI-compatible REST endpoint.

Supports any provider that implements the OpenAI embeddings API:
  - OpenAI:    base_url="https://api.openai.com/v1"
               model="text-embedding-3-small", dimensions=768
  - Fireworks: base_url="https://api.fireworks.ai/inference/v1"
               model="nomic-ai/nomic-embed-text-v1.5"

The default (OpenAI text-embedding-3-small with dimensions=768) produces
L2-normalised 768-dim vectors that match the existing VECTOR(768) schema
with no migration required.

Cost: OpenAI text-embedding-3-small ~$0.02/1M tokens ≈ $0.10–0.30/month
for a typical personal knowledge base.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

# OpenAI-compatible defaults
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSIONS = 768
_BATCH_SIZE = 96  # OpenAI allows up to 2048 inputs; 96 is safe and efficient


class CloudEmbedder:
    """Embedder backed by an OpenAI-compatible REST API.

    Args:
        api_key:    API key for the provider.
        base_url:   API base URL (default: OpenAI). Override for Fireworks, etc.
        model:      Embedding model name (default: ``text-embedding-3-small``).
        dimensions: Output vector dimensions (default: 768, must match DB schema).
                    Passed as the ``dimensions`` parameter to the API when provided.
                    Models that ignore this parameter (e.g. Fireworks nomic-embed)
                    must natively output the right dimension.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
    ) -> None:
        if not api_key:
            raise ValueError(
                "CloudEmbedder requires an API key. "
                "Set OPENAI_API_KEY (or FIREWORKS_API_KEY) in your .env file."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimensions = dimensions

    # ── Protocol properties ────────────────────────────────────────────────

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return self._model

    # ── Public interface ───────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """Embed a single string and return a normalised float vector."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings in batches.

        Returns one vector per input, in the same order.
        Empty input returns an empty list.
        """
        if not texts:
            return []

        results: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            results.extend(self._call_api(batch))
        return results

    # ── Internal ───────────────────────────────────────────────────────────

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """POST to /embeddings and return the embedding vectors in input order."""
        payload: dict = {"model": self._model, "input": texts}
        # dimensions parameter is supported by OpenAI text-embedding-3-* models.
        # Providers like Fireworks ignore unknown params, so it is safe to always send.
        if self._dimensions != 1536:  # 1536 is the native dim; only send when reducing
            payload["dimensions"] = self._dimensions

        try:
            response = httpx.post(
                f"{self._base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Embedding API error {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Embedding API request failed: {exc}") from exc

        data = response.json()["data"]
        # Sort by index to guarantee order (API may reorder for efficiency)
        data.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in data]
