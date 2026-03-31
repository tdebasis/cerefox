# message-hub-mcp

MCP Streamable HTTP edge function for cross-conclave hub messaging. Deployed alongside `cerefox-mcp` on the same Supabase project.

## Why

The previous courier system stored messages as cerefox documents with metadata conventions. This required workarounds:
- `[hub-message]` tag hack for searchability
- Timestamp comments to force content hash changes on metadata updates
- Local-only read state tracking (JSON file per conclave)
- No structured API — hand-crafted documents with metadata conventions

This edge function provides a clean send/poll/mark-read API backed by a purpose-built `hub_messages` table.

## Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `hub_send` | Send a message to a conclave/agent | `from_conclave`, `from_agent`, `to_conclave`, `subject`, `body` |
| `hub_poll` | Poll for unread messages | `conclave` |
| `hub_mark_read` | Mark a message as received | `message_id`, `receiver` |

### hub_send

```json
{
  "from_conclave": "personal",
  "from_agent": "steward",
  "to_conclave": "upwork",
  "to_agent": "steward",
  "subject": "Cerefox breaking change",
  "body": "The requestor param is now required on all MCP calls."
}
```

Returns: `Message sent (id: <uuid>)`

### hub_poll

```json
{
  "conclave": "upwork",
  "since": "2026-03-30T00:00:00Z",
  "include_broadcast": true
}
```

- `since` (optional): only return messages created after this timestamp
- `include_broadcast` (optional, default: true): include messages addressed to `to_conclave: "all"`

Returns: formatted list of unread messages, or "No unread messages."

### hub_mark_read

```json
{
  "message_id": "abc123-...",
  "receiver": "upwork:archivist"
}
```

Sets `received_at` and `received_by` on the message. Marked messages no longer appear in `hub_poll` results.

## Schema

Table: `hub_messages` (migration `0010_hub_messages.sql`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `from_conclave` | text | Sender conclave |
| `from_agent` | text | Sender agent role |
| `to_conclave` | text | Target conclave (or `"all"` for broadcast) |
| `to_agent` | text | Target agent (default: `"all"`) |
| `subject` | text | Message subject |
| `body` | text | Message body |
| `created_at` | timestamptz | When the message was sent |
| `received_at` | timestamptz | When the message was read (null = unread) |
| `received_by` | text | Who processed it (`conclave:agent` format) |

## Deployment

```bash
# Apply the migration (if not already applied)
uv run python scripts/db_deploy.py

# Deploy the edge function
npx supabase functions deploy message-hub-mcp
```

## MCP Client Configuration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "message-hub": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://<your-project-ref>.supabase.co/functions/v1/message-hub-mcp",
        "--header",
        "Authorization: Bearer <your-anon-key>"
      ]
    }
  }
}
```

## SSE Polling Prevention

This function returns `405 Method Not Allowed` for GET requests, per the MCP spec (2025-03-26). This tells MCP clients that SSE notifications are not supported, preventing idle polling that would burn through Supabase Edge Function invocation quotas.

## Tests

```bash
uv run pytest -m e2e tests/e2e/test_message_hub_e2e.py -v
```

Requires `CEREFOX_SUPABASE_URL` and `CEREFOX_SUPABASE_ANON_KEY` in `.env`.
