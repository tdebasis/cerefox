"""UI end-to-end tests for the Cerefox web application via Playwright.

Run with: uv run pytest -m ui
Or:       uv run pytest tests/e2e/test_ui_e2e.py -m ui

Prerequisites:
  - The Cerefox web app must be running at http://127.0.0.1:8000/
    Start it with: uv run uvicorn cerefox.api.app:app --host 127.0.0.1 --port 8000
  - Playwright browsers must be installed: uv run playwright install chromium

If the app is not running, tests will fail with a connection error — that's expected.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from cerefox.db.client import CerefoxClient

pytestmark = pytest.mark.ui

BASE_URL = "http://127.0.0.1:8000"
E2E_PREFIX = "[E2E-UI]"


def _unique_title(label: str) -> str:
    return f"{E2E_PREFIX} {label} {uuid.uuid4().hex[:8]}"


# ── Dashboard ──────────────────────────────────────────────────────────────


class TestDashboard:
    def test_loads_and_shows_stats(self, page: Page):
        page.goto(BASE_URL)
        expect(page.locator("h1")).to_contain_text("Dashboard")
        # Should show document and project counts
        expect(page.locator(".stat-label", has_text="Documents")).to_be_visible()


# ── Ingest ─────────────────────────────────────────────────────────────────


class TestIngestPaste:
    def test_paste_ingest_creates_document(self, page: Page, e2e_client: CerefoxClient):
        """Full ingest flow: paste content → verify it appears in search."""
        title = _unique_title("Playwright Test Doc")

        # Navigate to ingest page
        page.goto(f"{BASE_URL}/ingest")
        expect(page.locator("h1")).to_contain_text("Ingest")

        # Fill in the paste form
        page.fill('input[name="title"]', title)
        page.fill(
            'textarea[name="content"]',
            "# Test Document\n\nThis is a Playwright test document for e2e testing.",
        )

        # Add metadata
        add_meta_btn = page.locator("text=+ Add metadata")
        if add_meta_btn.count() > 0:
            add_meta_btn.first.click()
            page.fill('input[name="meta_key[]"]', "e2e_source")
            page.fill('input[name="meta_value[]"]', "playwright")

        # Submit
        page.click('button:has-text("Ingest")')

        # Should see success message or redirect
        page.wait_for_timeout(2000)

        # Search for the document
        page.goto(f"{BASE_URL}/search?q={title}&mode=fts")
        page.wait_for_timeout(2000)

        # Verify it appears in results
        expect(page.locator(f"text={title}")).to_be_visible(timeout=10000)

        # Clean up via REST API — more reliable than UI navigation
        docs = e2e_client.list_documents(limit=50)
        for doc in docs:
            if doc.get("title") == title:
                e2e_client.delete_document(doc["id"])
                break


# ── Search ─────────────────────────────────────────────────────────────────


class TestSearch:
    def test_search_page_loads(self, page: Page):
        page.goto(f"{BASE_URL}/search")
        expect(page.locator("h1")).to_contain_text("Knowledge")

    def test_fts_search_returns_results(self, page: Page):
        """FTS search for a term that should match existing documents."""
        page.goto(f"{BASE_URL}/search")
        page.fill('input[name="q"]', "cerefox")
        page.select_option('select[name="mode"]', "fts")
        page.click('button:has-text("Search")')
        page.wait_for_timeout(3000)
        # We don't assert specific results since content varies,
        # but the page should not show an error
        error = page.locator(".error, .alert-danger")
        if error.count() > 0:
            assert False, f"Search returned error: {error.text_content()}"


# ── Projects ───────────────────────────────────────────────────────────────


class TestProjects:
    def test_project_crud(self, page: Page, e2e_client: CerefoxClient):
        """Create → verify → delete a project via the web UI."""
        project_name = _unique_title("Test Project")

        # Navigate to projects
        page.goto(f"{BASE_URL}/projects")
        expect(page.locator("h1")).to_contain_text("Projects")

        # Create project
        page.fill('input[name="name"]', project_name)
        page.fill('textarea[name="description"], input[name="description"]', "E2E test project")
        page.click('button:has-text("Create")')
        page.wait_for_timeout(1000)

        # Verify it appears
        expect(page.locator(f"text={project_name}")).to_be_visible()

        # Delete it — two-step inline confirm (no window.confirm dialog)
        row = page.get_by_role("row", name=re.compile(re.escape(project_name)))
        row.get_by_role("button", name=re.compile(r"^Delete$")).click()
        row.get_by_role("button", name="Confirm").click()
        page.wait_for_timeout(1000)
        # Verify it's gone from UI
        expect(page.locator(f"text={project_name}")).not_to_be_visible()

        # Clean up via REST API — safety net in case UI delete silently failed
        for proj in e2e_client.list_projects():
            if proj.get("name") == project_name:
                e2e_client.delete_project(proj["id"])
                break


# ── Document detail ────────────────────────────────────────────────────────


class TestDocumentView:
    def test_document_page_loads(self, page: Page):
        """Navigate to dashboard, click first document, verify detail page loads."""
        page.goto(BASE_URL)

        # Click on the first document link if any exist
        doc_links = page.locator("a[href*='/document/']")
        if doc_links.count() == 0:
            pytest.skip("No documents in the database to test")

        doc_links.first.click()
        page.wait_for_timeout(1000)

        # Should show document detail
        expect(page.locator("text=Edit")).to_be_visible()


class TestVersioningUI:
    def test_upload_new_file_creates_version_row(
        self, page: Page, e2e_client: CerefoxClient, tmp_path: Path
    ):
        """Ingest a file via UI, upload a new version, verify Backup Versions row appears, delete."""
        title = _unique_title("Versioning UI Test")

        # ── Step 1: ingest original document via paste form ──────────────────
        page.goto(f"{BASE_URL}/ingest")
        page.fill('input[name="title"]', title)
        page.fill('textarea[name="content"]', "# Version One\n\nOriginal content for UI versioning test.")
        page.click('button:has-text("Ingest")')
        page.wait_for_timeout(2000)

        # Find the created document ID via API
        docs = e2e_client.list_documents(limit=50)
        doc = next((d for d in docs if d.get("title") == title), None)
        if doc is None:
            pytest.fail(f"Document '{title}' not found after ingest")
        doc_id = doc["id"]

        try:
            # ── Step 2: navigate to document page ────────────────────────────
            page.goto(f"{BASE_URL}/document/{doc_id}")
            page.wait_for_timeout(500)
            expect(page.locator("h1")).to_contain_text(title)

            # Backup Versions row should NOT be visible yet (no versions exist)
            expect(page.locator("text=Backup Versions")).not_to_be_visible()

            # ── Step 3: open upload section and upload a new file ────────────
            page.click('button:has-text("Upload new File")')
            page.wait_for_timeout(300)

            v2_file = tmp_path / "version-two.md"
            v2_file.write_text("# Version Two\n\nUpdated content for UI versioning test.", encoding="utf-8")

            page.set_input_files('input[name="file"]', str(v2_file))
            # Use type="submit" to avoid ambiguity with the "✕ Cancel upload" toggle button
            # which also contains "upload" (case-insensitive has-text match).
            page.click('#upload-section button[type="submit"]')
            page.wait_for_timeout(4000)  # Allow time for embedding API round-trip

            # ── Step 4: reload document page and verify version row ──────────
            page.goto(f"{BASE_URL}/document/{doc_id}")
            page.wait_for_timeout(500)

            expect(page.locator("text=Backup Versions")).to_be_visible(timeout=5000)
            expect(page.locator("text=v1")).to_be_visible()
            # Target the version-specific download link (has ?version_id= in the URL)
            expect(page.locator("a[href*='version_id']")).to_be_visible()

        finally:
            # ── Cleanup ──────────────────────────────────────────────────────
            e2e_client.delete_document(doc_id)
