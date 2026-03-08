"""Ollama-backed embedder.

Calls a local (or remote) Ollama REST API to generate embeddings.  Works with
any model that Ollama supports and produces 768-dimensional vectors (e.g.
``nomic-embed-text``).

Pull a model before use:

    ollama pull nomic-embed-text
    ollama serve          # if not already running

Install the extra dependency before use:

    uv sync --extra ollama

or:

    pip install httpx
"""

from __future__ import annotations


class OllamaEmbedder:
    """Embedder backed by an Ollama server.

    Args:
        base_url: Ollama server base URL.  Defaults to ``http://localhost:11434``.
        model: Model name recognised by Ollama (e.g. ``nomic-embed-text``).
        dimensions: Informational dimensionality of the model's output.
            Defaults to 768, which matches ``nomic-embed-text``.  Not
            enforced — the server's actual output is passed through as-is.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        dimensions: int = 768,
    ) -> None:
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
        """Embed a single string via the Ollama ``/api/embeddings`` endpoint."""
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "httpx is not installed. Run: uv sync --extra ollama  (or: pip install httpx)"
            ) from exc

        url = f"{self._base_url}/api/embeddings"
        try:
            response = httpx.post(
                url,
                json={"model": self._model, "prompt": text},
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Ollama embedding request failed for model '{self._model}': {exc}"
            ) from exc

        return response.json()["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings by calling :meth:`embed` for each.

        Ollama does not currently expose a native batch endpoint, so this
        issues one HTTP request per string.
        """
        return [self.embed(t) for t in texts]
