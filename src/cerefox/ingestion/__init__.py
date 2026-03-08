"""Ingestion pipeline: parse → chunk → embed → store."""

from cerefox.ingestion.pipeline import IngestResult, IngestionPipeline

__all__ = ["IngestionPipeline", "IngestResult"]
