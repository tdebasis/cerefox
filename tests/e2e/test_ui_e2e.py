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

import pytest
from playwright.sync_api import Page, expect

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
    def test_paste_ingest_creates_document(self, page: Page):
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

        # Clean up: navigate to the document and delete via the delete form
        page.locator(f"text={title}").first.click()
        page.wait_for_timeout(1000)

        # Extract document ID from the URL and POST the delete form directly
        doc_url = page.url
        doc_id_match = re.search(r"/document/([a-f0-9-]+)", doc_url)
        if doc_id_match:
            page.on("dialog", lambda dialog: dialog.accept())
            # Use the specific delete form for this document
            delete_form = page.locator(f'form[action="/document/{doc_id_match.group(1)}/delete"]')
            if delete_form.count() > 0:
                delete_form.locator("button").click()
                page.wait_for_timeout(1000)


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
    def test_project_crud(self, page: Page):
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

        # Delete it — find the table row containing our project name
        row = page.get_by_role("row", name=re.compile(re.escape(project_name)))
        page.on("dialog", lambda dialog: dialog.accept())
        row.locator("button", has_text="Delete").click()
        page.wait_for_timeout(1000)
        # Verify it's gone
        expect(page.locator(f"text={project_name}")).not_to_be_visible()


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
