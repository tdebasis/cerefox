"""Tests for cerefox.config.Settings.

All tests are unit tests — no network or file system access needed.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from cerefox.config import Settings


class TestDefaults:
    """Settings should have safe, working defaults for all optional fields."""

    def test_default_embedder(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.embedder == "mpnet"

    def test_default_vector_dimensions(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.vector_dimensions == 768

    def test_default_max_chunk_chars(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.max_chunk_chars == 4000

    def test_default_min_chunk_chars(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.min_chunk_chars == 100

    def test_default_overlap_chars(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.overlap_chars == 200

    def test_default_max_response_bytes(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.max_response_bytes == 65000

    def test_default_supabase_url_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.supabase_url == ""

    def test_default_log_level(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.log_level == "INFO"

    def test_default_ollama_url(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.ollama_url == "http://localhost:11434"

    def test_default_ollama_model(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.ollama_model == "nomic-embed-text"


class TestEnvOverrides:
    """Environment variables with CEREFOX_ prefix should override defaults."""

    def test_supabase_url_override(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_SUPABASE_URL": "https://myproject.supabase.co"}):
            s = Settings()
        assert s.supabase_url == "https://myproject.supabase.co"

    def test_embedder_ollama_override(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_EMBEDDER": "ollama"}):
            s = Settings()
        assert s.embedder == "ollama"

    def test_max_chunk_chars_override(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_MAX_CHUNK_CHARS": "2000"}):
            s = Settings()
        assert s.max_chunk_chars == 2000

    def test_max_response_bytes_override(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_MAX_RESPONSE_BYTES": "32000"}):
            s = Settings()
        assert s.max_response_bytes == 32000

    def test_log_level_override(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_LOG_LEVEL": "DEBUG"}):
            s = Settings()
        assert s.log_level == "DEBUG"


class TestValidation:
    """Settings should validate field values and reject invalid inputs."""

    def test_invalid_embedder_raises(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_EMBEDDER": "vertex"}):
            with pytest.raises(ValidationError):
                Settings()

    def test_embedder_mpnet_valid(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_EMBEDDER": "mpnet"}):
            s = Settings()
        assert s.embedder == "mpnet"

    def test_embedder_ollama_valid(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_EMBEDDER": "ollama"}):
            s = Settings()
        assert s.embedder == "ollama"

    def test_max_chunk_chars_must_be_int(self) -> None:
        with patch.dict(os.environ, {"CEREFOX_MAX_CHUNK_CHARS": "notanumber"}):
            with pytest.raises(ValidationError):
                Settings()


class TestHelperMethods:
    """is_supabase_configured() and is_db_configured() should return correct booleans."""

    def test_not_configured_when_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.is_supabase_configured() is False
        assert s.is_db_configured() is False

    def test_supabase_configured_when_both_set(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CEREFOX_SUPABASE_URL": "https://x.supabase.co",
                "CEREFOX_SUPABASE_KEY": "secret",
            },
        ):
            s = Settings()
        assert s.is_supabase_configured() is True

    def test_supabase_not_configured_with_only_url(self) -> None:
        with patch.dict(
            os.environ,
            {"CEREFOX_SUPABASE_URL": "https://x.supabase.co", "CEREFOX_SUPABASE_KEY": ""},
        ):
            s = Settings()
        assert s.is_supabase_configured() is False

    def test_db_configured_when_url_set(self) -> None:
        with patch.dict(
            os.environ,
            {"CEREFOX_DATABASE_URL": "postgresql://postgres:pass@localhost/postgres"},
        ):
            s = Settings()
        assert s.is_db_configured() is True
