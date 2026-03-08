"""Tests for embedder implementations and the Embedder protocol.

All tests use mocked external dependencies — no sentence-transformers model
is downloaded and no Ollama server is contacted.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from cerefox.embeddings.base import Embedder


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_sentence_transformers():
    """Inject a mock ``sentence_transformers`` module into sys.modules.

    Returns the mock ``SentenceTransformer`` class so tests can configure it.
    The fixture tears itself down by removing the mock from sys.modules.
    """
    mock_module = MagicMock()
    mock_cls = MagicMock()
    mock_module.SentenceTransformer = mock_cls
    with patch.dict(sys.modules, {"sentence_transformers": mock_module}):
        # If MpnetEmbedder was already imported before the patch, its cached
        # reference to the real module must also be cleared.
        sys.modules.pop("cerefox.embeddings.mpnet", None)
        yield mock_cls


@pytest.fixture()
def mpnet(mock_sentence_transformers):
    """Return an MpnetEmbedder whose underlying model is fully mocked."""
    from cerefox.embeddings.mpnet import MpnetEmbedder

    embedder = MpnetEmbedder()

    # Configure the mock model instance that _load() will return.
    mock_instance = MagicMock()
    mock_sentence_transformers.return_value = mock_instance

    # Single-embed: encode() returns something with .tolist() → 768 floats.
    single_vec = MagicMock()
    single_vec.tolist.return_value = [0.1] * 768

    # Batch-embed: encode() returns something with .tolist() → list of lists.
    batch_vecs = MagicMock()
    batch_vecs.tolist.return_value = [[0.1] * 768, [0.2] * 768]

    # By default configure for single-embed; tests that need batch can override.
    mock_instance.encode.return_value = single_vec

    return embedder, mock_instance, single_vec, batch_vecs


# ── Embedder protocol ─────────────────────────────────────────────────────────


class TestEmbedderProtocol:
    def test_mpnet_satisfies_protocol(self, mpnet) -> None:
        embedder, *_ = mpnet
        assert isinstance(embedder, Embedder)

    def test_ollama_satisfies_protocol(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        assert isinstance(OllamaEmbedder(), Embedder)

    def test_protocol_is_runtime_checkable(self) -> None:
        # A minimal duck-typed object satisfies the Protocol at runtime.
        class FakeEmbedder:
            dimensions = 768
            model_name = "fake"

            def embed(self, text: str) -> list[float]:
                return [0.0] * 768

            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [[0.0] * 768 for _ in texts]

        assert isinstance(FakeEmbedder(), Embedder)


# ── MpnetEmbedder ─────────────────────────────────────────────────────────────


class TestMpnetEmbedder:
    def test_dimensions_property(self, mpnet) -> None:
        embedder, *_ = mpnet
        assert embedder.dimensions == 768

    def test_model_name_property(self, mpnet) -> None:
        embedder, *_ = mpnet
        assert embedder.model_name == "sentence-transformers/all-mpnet-base-v2"

    def test_model_not_loaded_on_init(self, mock_sentence_transformers) -> None:
        """The model must not be instantiated until the first embed call."""
        from cerefox.embeddings.mpnet import MpnetEmbedder

        embedder = MpnetEmbedder()
        assert embedder._model is None
        mock_sentence_transformers.assert_not_called()

    def test_embed_returns_768_floats(self, mpnet) -> None:
        embedder, mock_model, single_vec, _ = mpnet
        mock_model.encode.return_value = single_vec

        result = embedder.embed("hello world")

        assert isinstance(result, list)
        assert len(result) == 768
        assert all(isinstance(v, float) for v in result)

    def test_embed_calls_encode_with_normalize(self, mpnet) -> None:
        embedder, mock_model, single_vec, _ = mpnet
        mock_model.encode.return_value = single_vec

        embedder.embed("test")

        mock_model.encode.assert_called_once_with("test", normalize_embeddings=True)

    def test_embed_batch_returns_list_of_vectors(self, mpnet) -> None:
        embedder, mock_model, _, batch_vecs = mpnet
        mock_model.encode.return_value = batch_vecs

        result = embedder.embed_batch(["one", "two"])

        assert isinstance(result, list)
        assert len(result) == 2
        for vec in result:
            assert len(vec) == 768

    def test_embed_batch_empty_list_returns_empty(self, mpnet) -> None:
        embedder, mock_model, *_ = mpnet
        result = embedder.embed_batch([])
        assert result == []
        mock_model.encode.assert_not_called()

    def test_model_loaded_lazily_on_first_embed(self, mpnet) -> None:
        embedder, mock_model, single_vec, _ = mpnet
        mock_model.encode.return_value = single_vec

        assert embedder._model is None
        embedder.embed("trigger load")
        assert embedder._model is not None

    def test_model_loaded_only_once_for_multiple_embeds(self, mpnet, mock_sentence_transformers) -> None:
        embedder, mock_model, single_vec, _ = mpnet
        mock_model.encode.return_value = single_vec

        embedder.embed("first")
        embedder.embed("second")

        mock_sentence_transformers.assert_called_once()

    def test_missing_package_raises_runtime_error(self) -> None:
        """If sentence-transformers is not installed, a clear RuntimeError is raised."""
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            sys.modules.pop("cerefox.embeddings.mpnet", None)
            from cerefox.embeddings.mpnet import MpnetEmbedder

            embedder = MpnetEmbedder()
            with pytest.raises(RuntimeError, match="sentence-transformers"):
                embedder.embed("boom")


# ── OllamaEmbedder ────────────────────────────────────────────────────────────


class TestOllamaEmbedder:
    """Tests for OllamaEmbedder.  httpx calls are mocked."""

    def test_dimensions_property(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        assert OllamaEmbedder().dimensions == 768

    def test_custom_dimensions(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        assert OllamaEmbedder(dimensions=1024).dimensions == 1024

    def test_model_name_property(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        assert OllamaEmbedder(model="nomic-embed-text").model_name == "nomic-embed-text"

    def test_embed_posts_to_correct_endpoint(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        embedder = OllamaEmbedder(base_url="http://localhost:11434", model="nomic-embed-text")
        fake_vec = [0.5] * 768
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": fake_vec}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = embedder.embed("hello")

        mock_post.assert_called_once_with(
            "http://localhost:11434/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": "hello"},
            timeout=30.0,
        )
        assert result == fake_vec

    def test_embed_returns_embedding_from_response(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        embedder = OllamaEmbedder()
        expected = [0.1] * 768
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": expected}

        with patch("httpx.post", return_value=mock_response):
            result = embedder.embed("test text")

        assert result == expected

    def test_embed_raises_runtime_error_on_http_error(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        import httpx

        embedder = OllamaEmbedder()
        with patch("httpx.post", side_effect=httpx.HTTPError("connection refused")):
            with pytest.raises(RuntimeError, match="Ollama embedding request failed"):
                embedder.embed("boom")

    def test_embed_batch_calls_embed_for_each_text(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        embedder = OllamaEmbedder()
        fake_vec = [0.0] * 768
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": fake_vec}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            results = embedder.embed_batch(["one", "two", "three"])

        assert len(results) == 3
        assert mock_post.call_count == 3

    def test_base_url_trailing_slash_stripped(self) -> None:
        from cerefox.embeddings.ollama_embed import OllamaEmbedder

        embedder = OllamaEmbedder(base_url="http://localhost:11434/")
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.0] * 768}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            embedder.embed("test")

        called_url = mock_post.call_args[0][0]
        assert not called_url.endswith("//"), "Double slash in URL"
        assert called_url == "http://localhost:11434/api/embeddings"
