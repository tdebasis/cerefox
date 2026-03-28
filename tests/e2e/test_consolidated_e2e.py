"""E2E tests for the consolidated cerefox edge function (MCP JSON-RPC 2.0).

These tests target the consolidated /functions/v1/cerefox endpoint which handles
all tool logic inline (no internal fetch delegation). All data seeding is done
via MCP ingest (server-side embeddings) so no local OpenAI key is needed.

Run with: uv run pytest tests/e2e/test_consolidated_e2e.py -m e2e -v
"""

from __future__ import annotations

import re
import time

import pytest

from cerefox.db.client import CerefoxClient

from .conftest import E2ECleanup, McpEdgeFunctionClient

pytestmark = pytest.mark.e2e


def _extract_doc_id(text: str) -> str:
    """Extract document_id from MCP ingest response text."""
    match = re.search(r"\(id:\s*([0-9a-f-]+)\)", text)
    assert match, f"Could not extract document_id from: {text}"
    return match.group(1)


def _ingest_via_mcp(
    mcp: McpEdgeFunctionClient,
    title: str,
    content: str,
    metadata: dict | None = None,
    update_if_exists: bool = False,
) -> tuple[str, str]:
    """Ingest a document via MCP and return (doc_id, response_text)."""
    args: dict = {"title": title, "content": content}
    if metadata:
        args["metadata"] = metadata
    if update_if_exists:
        args["update_if_exists"] = True
    text = mcp.get_text("cerefox_ingest", args)
    doc_id = _extract_doc_id(text)
    return doc_id, text


# ── 1. Ingest tests ──────────────────────────────────────────────────────────


class TestConsolidatedIngest:
    """Ingest, dedup, and update via the consolidated MCP endpoint."""

    def test_ingest_and_dedup(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
        e2e_client: CerefoxClient,
        cleanup: E2ECleanup,
        unique_title,
    ):
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        title = unique_title("MCP Ingest Test")
        content = "# MCP Ingest\n\nThis document was ingested via the consolidated MCP function."
        metadata = {"source_test": "e2e-mcp", "layer": "consolidated"}

        # Ingest via MCP
        doc_id, text = _ingest_via_mcp(e2e_mcp_edge, title, content, metadata)
        cleanup.track_document(doc_id)
        assert "Document saved:" in text, f"Unexpected response: {text}"

        # Verify doc exists in DB
        doc = e2e_client.get_document_by_id(doc_id)
        assert doc is not None
        assert doc["title"] == title
        assert doc["metadata"]["source_test"] == "e2e-mcp"

        # Dedup — same content, different title
        text2 = e2e_mcp_edge.get_text("cerefox_ingest", {
            "title": unique_title("MCP Ingest Dedup"),
            "content": content,
        })
        assert "already" in text2.lower(), f"Expected dedup skip, got: {text2}"

        # Update — different content, same title, update_if_exists=true
        updated_content = content + "\n\n## Update\n\nAdded by MCP e2e test."
        text3 = e2e_mcp_edge.get_text("cerefox_ingest", {
            "title": title,
            "content": updated_content,
            "update_if_exists": True,
        })
        assert "updated" in text3.lower() or "Document updated:" in text3, (
            f"Expected update confirmation, got: {text3}"
        )


# ── 2. Search tests ──────────────────────────────────────────────────────────


class TestConsolidatedSearch:
    """Search via the consolidated MCP endpoint. Data seeded via MCP ingest."""

    def test_search(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
        cleanup: E2ECleanup,
        unique_title,
    ):
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        title = unique_title("MCP Search Target")
        content = (
            "# Quantum Harmonic Oscillator\n\n"
            "The quantum harmonic oscillator describes vibrational modes "
            "of diatomic molecules and crystal lattice phonons."
        )

        # Seed data via MCP ingest (server-side embeddings)
        doc_id, _ = _ingest_via_mcp(e2e_mcp_edge, title, content)
        cleanup.track_document(doc_id)

        time.sleep(1)

        # Search via MCP
        text = e2e_mcp_edge.get_text("cerefox_search", {
            "query": "quantum harmonic oscillator",
            "match_count": 10,
        })
        assert "No results found" not in text, f"Search returned no results: {text}"
        assert "Quantum Harmonic Oscillator" in text, (
            f"Expected to find ingested doc in results: {text[:500]}"
        )


# ── 3. Metadata tests ────────────────────────────────────────────────────────


class TestConsolidatedMetadata:
    """Metadata listing via the consolidated MCP endpoint."""

    def test_list_metadata_keys(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
        cleanup: E2ECleanup,
        unique_title,
    ):
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        # Seed data via MCP ingest
        title = unique_title("MCP Metadata Test")
        doc_id, _ = _ingest_via_mcp(
            e2e_mcp_edge, title,
            "# Metadata Test\n\nDocument for testing MCP metadata key discovery.",
            metadata={"e2e_mcp_tag": "mcp-metadata-test"},
        )
        cleanup.track_document(doc_id)

        # List metadata keys via MCP
        text = e2e_mcp_edge.get_text("cerefox_list_metadata_keys", {})
        assert "e2e_mcp_tag" in text, f"Expected 'e2e_mcp_tag' in metadata keys: {text[:500]}"


# ── 4. Metadata-filtered search ──────────────────────────────────────────────


class TestConsolidatedMetadataFilter:
    """Metadata filter via the consolidated MCP endpoint."""

    def test_metadata_filter(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
        cleanup: E2ECleanup,
        unique_title,
    ):
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        title_a = unique_title("MCP MetaFilter A")
        title_b = unique_title("MCP MetaFilter B")

        # Seed both docs via MCP ingest
        doc_id_a, _ = _ingest_via_mcp(
            e2e_mcp_edge, title_a,
            "# MCP Filter A\n\nDecision document for consolidated function filter test.",
            metadata={"e2e_mcp_type": "decision"},
        )
        doc_id_b, _ = _ingest_via_mcp(
            e2e_mcp_edge, title_b,
            "# MCP Filter B\n\nNote document for consolidated function filter test.",
            metadata={"e2e_mcp_type": "note"},
        )
        cleanup.track_document(doc_id_a)
        cleanup.track_document(doc_id_b)
        time.sleep(2)

        # Search with metadata filter via MCP
        text = e2e_mcp_edge.get_text("cerefox_search", {
            "query": "consolidated function filter test",
            "match_count": 10,
            "metadata_filter": {"e2e_mcp_type": "decision"},
        })
        assert "MCP Filter A" in text, f"Decision doc should appear in filtered results: {text[:500]}"
        assert "MCP Filter B" not in text, f"Note doc should be excluded by filter: {text[:500]}"


# ── 5. Get document test ─────────────────────────────────────────────────────


class TestConsolidatedGetDocument:
    """Get document via the consolidated MCP endpoint."""

    def test_get_document(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
        cleanup: E2ECleanup,
        unique_title,
    ):
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        title = unique_title("MCP GetDoc Test")
        content = "# Get Document Test\n\nContent for testing document retrieval via MCP."

        # Seed via MCP ingest
        doc_id, _ = _ingest_via_mcp(e2e_mcp_edge, title, content)
        cleanup.track_document(doc_id)

        # Retrieve via MCP
        text = e2e_mcp_edge.get_text("cerefox_get_document", {
            "document_id": doc_id,
        })
        assert title in text, f"Expected title in retrieved document: {text[:500]}"
        assert "Get Document Test" in text, f"Expected heading in content: {text[:500]}"
        assert "(current)" in text, f"Expected (current) label: {text[:200]}"

    def test_get_document_not_found(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
    ):
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        text = e2e_mcp_edge.get_text("cerefox_get_document", {
            "document_id": "00000000-0000-0000-0000-000000000000",
        })
        assert "not found" in text.lower(), f"Expected 'not found', got: {text}"


# ── 6. MCP protocol tests ────────────────────────────────────────────────────


class TestConsolidatedMcpProtocol:
    """Verify the MCP protocol layer of the consolidated function."""

    def test_initialize(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
    ):
        """The initialize method should return protocol version and capabilities."""
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        e2e_mcp_edge._id_counter += 1
        resp = e2e_mcp_edge._http.post("/cerefox", json={
            "jsonrpc": "2.0",
            "id": e2e_mcp_edge._id_counter,
            "method": "initialize",
            "params": {},
        })
        resp.raise_for_status()
        data = resp.json()
        assert data["result"]["protocolVersion"] == "2025-03-26"
        assert data["result"]["serverInfo"]["name"] == "cerefox"
        assert "tools" in data["result"]["capabilities"]

    def test_tools_list(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
    ):
        """The tools/list method should return all 6 tool definitions."""
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        e2e_mcp_edge._id_counter += 1
        resp = e2e_mcp_edge._http.post("/cerefox", json={
            "jsonrpc": "2.0",
            "id": e2e_mcp_edge._id_counter,
            "method": "tools/list",
            "params": {},
        })
        resp.raise_for_status()
        data = resp.json()
        tools = data["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        expected = {
            "cerefox_search",
            "cerefox_ingest",
            "cerefox_list_metadata_keys",
            "cerefox_get_document",
            "cerefox_list_versions",
            "cerefox_get_audit_log",
        }
        assert tool_names == expected, f"Expected {expected}, got {tool_names}"

    def test_unknown_tool_returns_error(
        self,
        e2e_mcp_edge: McpEdgeFunctionClient | None,
    ):
        """Calling an unknown tool should return a JSON-RPC error, not crash."""
        if e2e_mcp_edge is None:
            pytest.skip("No JWT key for MCP Edge Function (set CEREFOX_SUPABASE_ANON_KEY)")

        e2e_mcp_edge._id_counter += 1
        resp = e2e_mcp_edge._http.post("/cerefox", json={
            "jsonrpc": "2.0",
            "id": e2e_mcp_edge._id_counter,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        })
        resp.raise_for_status()
        data = resp.json()
        assert "error" in data, f"Expected error for unknown tool, got: {data}"
