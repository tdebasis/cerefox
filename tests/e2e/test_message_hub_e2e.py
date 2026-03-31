"""E2E tests for the deployed message-hub-mcp Edge Function via MCP JSON-RPC 2.0.

Calls the live Edge Function using raw HTTP POST with JSON-RPC 2.0 payloads.

Run with: uv run pytest -m e2e tests/e2e/test_message_hub_e2e.py -v

Requires:
  - message-hub-mcp deployed to Supabase
  - CEREFOX_SUPABASE_URL and CEREFOX_SUPABASE_ANON_KEY in .env
  - hub_messages table created (migration 0010)
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest

from cerefox.config import Settings

pytestmark = pytest.mark.e2e

E2E_PREFIX = "[E2E-HUB]"


class HubMCPClient:
    """JSON-RPC 2.0 client for the message-hub-mcp Edge Function."""

    def __init__(self, base_url: str, anon_key: str) -> None:
        self._base_url = f"{base_url}/functions/v1/message-hub-mcp"
        self._http = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {anon_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._req_id = 0

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            body["params"] = params
        resp = self._http.post("", json=body)
        resp.raise_for_status()
        return resp.json()

    def tool_text(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        resp = self.call("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in resp:
            raise RuntimeError(f"MCP error: {resp['error']}")
        return resp["result"]["content"][0]["text"]

    def get_raw(self) -> httpx.Response:
        """Raw GET request (to test 405)."""
        return httpx.get(self._base_url, headers=self._http.headers)


def _resolve_anon_key(settings: Settings) -> str | None:
    from dotenv import dotenv_values
    import os

    dotenv = dotenv_values(".env")
    anon_key = os.environ.get("CEREFOX_SUPABASE_ANON_KEY", "") or dotenv.get(
        "CEREFOX_SUPABASE_ANON_KEY", ""
    )
    if not anon_key:
        main_key = settings.supabase_key
        if main_key.startswith("eyJ"):
            anon_key = main_key
    return anon_key or None


@pytest.fixture(scope="module")
def hub_client() -> HubMCPClient | None:
    settings = Settings()
    if not settings.is_supabase_configured():
        pytest.skip("Supabase not configured")
    anon_key = _resolve_anon_key(settings)
    if not anon_key:
        pytest.skip("No anon key available")
    return HubMCPClient(settings.supabase_url, anon_key)


@pytest.fixture(scope="module")
def cleanup_client() -> Any:
    """Direct Supabase client for test cleanup."""
    from supabase import create_client
    from dotenv import dotenv_values
    import os

    settings = Settings()
    dotenv = dotenv_values(".env")
    key = settings.supabase_key
    client = create_client(settings.supabase_url, key)
    yield client
    # Cleanup all E2E-HUB messages
    client.from_("hub_messages").delete().like("subject", f"{E2E_PREFIX}%").execute()


def _unique_subject(label: str) -> str:
    return f"{E2E_PREFIX} {label} {uuid.uuid4().hex[:8]}"


# ── Tests ────────────────────────────────────────────────────────────────────


def test_initialize(hub_client: HubMCPClient) -> None:
    """Initialize returns server info with message-hub-mcp name."""
    resp = hub_client.call("initialize")
    assert "result" in resp
    result = resp["result"]
    assert result["serverInfo"]["name"] == "message-hub-mcp"
    assert "tools" in result["capabilities"]


def test_tools_list(hub_client: HubMCPClient) -> None:
    """tools/list returns exactly 3 tools."""
    resp = hub_client.call("tools/list")
    tools = resp["result"]["tools"]
    names = [t["name"] for t in tools]
    assert sorted(names) == ["hub_mark_read", "hub_poll", "hub_search", "hub_send"]


def test_get_returns_405(hub_client: HubMCPClient) -> None:
    """GET request returns 405 Method Not Allowed (no SSE polling)."""
    resp = hub_client.get_raw()
    assert resp.status_code == 405


def test_send_and_poll(hub_client: HubMCPClient) -> None:
    """Send a message, then poll for it."""
    subject = _unique_subject("send-poll")

    # Send
    send_text = hub_client.tool_text("hub_send", {
        "from_conclave": "test",
        "from_agent": "artificer",
        "to_conclave": "test-target",
        "subject": subject,
        "body": "Hello from e2e test",
    })
    assert "Message sent" in send_text

    # Poll
    poll_text = hub_client.tool_text("hub_poll", {"conclave": "test-target"})
    assert subject in poll_text
    assert "Hello from e2e test" in poll_text


def test_mark_read(hub_client: HubMCPClient) -> None:
    """Send, mark read, poll again — message should not appear."""
    subject = _unique_subject("mark-read")

    # Send
    send_text = hub_client.tool_text("hub_send", {
        "from_conclave": "test",
        "from_agent": "steward",
        "to_conclave": "test-target",
        "subject": subject,
        "body": "Mark me read",
    })
    # Extract message ID from response
    msg_id = send_text.split("id: ")[1].strip(")")

    # Mark read
    mark_text = hub_client.tool_text("hub_mark_read", {
        "message_id": msg_id,
        "receiver": "test-target:archivist",
    })
    assert "marked as read" in mark_text

    # Poll — should not find it
    poll_text = hub_client.tool_text("hub_poll", {"conclave": "test-target"})
    assert subject not in poll_text


def test_poll_with_since(hub_client: HubMCPClient) -> None:
    """Poll with since filter only returns newer messages."""
    subject_old = _unique_subject("since-old")
    subject_new = _unique_subject("since-new")

    # Send first message
    hub_client.tool_text("hub_send", {
        "from_conclave": "test",
        "from_agent": "steward",
        "to_conclave": "test-since",
        "subject": subject_old,
        "body": "Old message",
    })

    # Record timestamp between messages
    time.sleep(1)
    since_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    time.sleep(1)

    # Send second message
    hub_client.tool_text("hub_send", {
        "from_conclave": "test",
        "from_agent": "steward",
        "to_conclave": "test-since",
        "subject": subject_new,
        "body": "New message",
    })

    # Poll with since — should only get the new one
    poll_text = hub_client.tool_text("hub_poll", {
        "conclave": "test-since",
        "since": since_ts,
    })
    assert subject_new in poll_text
    assert subject_old not in poll_text


def test_poll_broadcast(hub_client: HubMCPClient) -> None:
    """Messages to 'all' appear when polling with include_broadcast=true."""
    subject = _unique_subject("broadcast")

    # Send broadcast
    hub_client.tool_text("hub_send", {
        "from_conclave": "test",
        "from_agent": "steward",
        "to_conclave": "all",
        "subject": subject,
        "body": "Broadcast message",
    })

    # Poll with broadcast enabled (default)
    poll_text = hub_client.tool_text("hub_poll", {"conclave": "test-broadcast"})
    assert subject in poll_text

    # Poll with broadcast disabled
    poll_text_no_bc = hub_client.tool_text("hub_poll", {
        "conclave": "test-broadcast",
        "include_broadcast": False,
    })
    assert subject not in poll_text_no_bc


def test_search_includes_read_messages(hub_client: HubMCPClient) -> None:
    """hub_search returns messages even after they are marked read."""
    subject = _unique_subject("search-read")
    since_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Send and mark read
    send_text = hub_client.tool_text("hub_send", {
        "from_conclave": "test",
        "from_agent": "steward",
        "to_conclave": "test-search",
        "subject": subject,
        "body": "Search me after read",
    })
    msg_id = send_text.split("id: ")[1].strip(")")

    hub_client.tool_text("hub_mark_read", {
        "message_id": msg_id,
        "receiver": "test-search:archivist",
    })

    # hub_poll should NOT find it (already read)
    poll_text = hub_client.tool_text("hub_poll", {"conclave": "test-search"})
    assert subject not in poll_text

    # hub_search SHOULD find it
    search_text = hub_client.tool_text("hub_search", {
        "conclave": "test-search",
        "since": since_ts,
    })
    assert subject in search_text
    assert "read by" in search_text


def test_search_with_sender_filters(hub_client: HubMCPClient) -> None:
    """hub_search filters by from_conclave and from_agent."""
    subject_a = _unique_subject("search-filter-a")
    subject_b = _unique_subject("search-filter-b")
    since_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Send from two different senders
    hub_client.tool_text("hub_send", {
        "from_conclave": "alpha",
        "from_agent": "steward",
        "to_conclave": "test-search-filter",
        "subject": subject_a,
        "body": "From alpha",
    })
    hub_client.tool_text("hub_send", {
        "from_conclave": "beta",
        "from_agent": "archivist",
        "to_conclave": "test-search-filter",
        "subject": subject_b,
        "body": "From beta",
    })

    # Search filtered by from_conclave
    search_text = hub_client.tool_text("hub_search", {
        "conclave": "test-search-filter",
        "since": since_ts,
        "from_conclave": "alpha",
    })
    assert subject_a in search_text
    assert subject_b not in search_text

    # Search filtered by from_agent
    search_text = hub_client.tool_text("hub_search", {
        "conclave": "test-search-filter",
        "since": since_ts,
        "from_agent": "archivist",
    })
    assert subject_b in search_text
    assert subject_a not in search_text
