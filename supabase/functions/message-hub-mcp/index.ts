import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

/**
 * message-hub-mcp — Supabase Edge Function
 *
 * MCP Streamable HTTP server for cross-conclave hub messaging.
 * Provides send, poll, and mark-read operations against the hub_messages table.
 *
 * Returns 405 on GET to prevent SSE polling overhead.
 */

const MCP_VERSION = "2025-03-26";
const SERVER_NAME = "message-hub-mcp";
const SERVER_VERSION = "0.1.0";

// ── CORS ────────────────────────────────────────────────────────────────────

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id",
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeSupabaseClient() {
  const url = Deno.env.get("SUPABASE_URL")!;
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  return createClient(url, key);
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}

function errorResponse(id: unknown, code: number, message: string): Response {
  return jsonResponse({
    jsonrpc: "2.0",
    id: id ?? null,
    error: { code, message },
  }, 200);
}

function notificationResponse(): Response {
  return new Response(null, { status: 202, headers: CORS_HEADERS });
}

// ── Tool definitions ────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "hub_send",
    description: "Send a message to another conclave or agent via the hub.",
    inputSchema: {
      type: "object",
      required: ["from_conclave", "from_agent", "to_conclave", "subject", "body"],
      properties: {
        from_conclave: { type: "string", description: "Sender conclave name (e.g., 'personal')" },
        from_agent: { type: "string", description: "Sender agent role (e.g., 'steward')" },
        to_conclave: { type: "string", description: "Target conclave name (e.g., 'upwork'). Use 'all' for broadcast." },
        to_agent: { type: "string", description: "Target agent role (default: 'all')" },
        subject: { type: "string", description: "Message subject line" },
        body: { type: "string", description: "Message body" },
      },
    },
  },
  {
    name: "hub_poll",
    description: "Poll for unread hub messages addressed to a conclave.",
    inputSchema: {
      type: "object",
      required: ["conclave"],
      properties: {
        conclave: { type: "string", description: "Conclave name to poll for (e.g., 'personal')" },
        since: { type: "string", description: "ISO timestamp — only return messages created after this time (optional)" },
        include_broadcast: { type: "boolean", description: "Also return messages addressed to 'all' (default: true)" },
      },
    },
  },
  {
    name: "hub_search",
    description: "Search hub message history (read and unread).",
    inputSchema: {
      type: "object",
      required: ["conclave", "since"],
      properties: {
        conclave: { type: "string", description: "Conclave name to search (e.g., 'personal')" },
        since: { type: "string", description: "Date or datetime — return messages after this (e.g., '2026-03-25' or '2026-03-25T14:00:00Z')" },
        from_conclave: { type: "string", description: "Filter by sender conclave (optional)" },
        from_agent: { type: "string", description: "Filter by sender agent (optional)" },
        include_broadcast: { type: "boolean", description: "Include messages addressed to 'all' (default: true)" },
      },
    },
  },
  {
    name: "hub_mark_read",
    description: "Mark a hub message as received/processed.",
    inputSchema: {
      type: "object",
      required: ["message_id", "receiver"],
      properties: {
        message_id: { type: "string", description: "UUID of the message to mark as read" },
        receiver: { type: "string", description: "Who processed it, in conclave:agent format (e.g., 'personal:archivist')" },
      },
    },
  },
];

// ── Tool handlers ───────────────────────────────────────────────────────────

async function handleSend(args: Record<string, unknown>): Promise<string> {
  const supabase = makeSupabaseClient();

  const { data, error } = await supabase.from("hub_messages").insert({
    from_conclave: args.from_conclave,
    from_agent: args.from_agent,
    to_conclave: args.to_conclave,
    to_agent: (args.to_agent as string) || "all",
    subject: args.subject,
    body: args.body,
  }).select("id").single();

  if (error) throw new Error(`Insert error: ${error.message}`);

  return `Message sent (id: ${data.id})`;
}

async function handlePoll(args: Record<string, unknown>): Promise<string> {
  const supabase = makeSupabaseClient();
  const conclave = args.conclave as string;
  const since = args.since as string | undefined;
  const includeBroadcast = args.include_broadcast !== false;

  let query = supabase
    .from("hub_messages")
    .select("*")
    .is("received_at", null)
    .order("created_at", { ascending: true });

  if (includeBroadcast) {
    query = query.or(`to_conclave.eq.${conclave},to_conclave.eq.all`);
  } else {
    query = query.eq("to_conclave", conclave);
  }

  if (since) {
    query = query.gt("created_at", since);
  }

  const { data, error } = await query;

  if (error) throw new Error(`Query error: ${error.message}`);

  const messages = data ?? [];

  if (messages.length === 0) {
    return "No unread messages.";
  }

  const lines = messages.map((m: Record<string, unknown>) =>
    `## ${m.subject}\n` +
    `**From:** ${m.from_conclave}:${m.from_agent} | **To:** ${m.to_conclave}:${m.to_agent} | **ID:** ${m.id}\n` +
    `**Sent:** ${m.created_at}\n\n` +
    `${m.body}`
  );

  return `${messages.length} unread message(s):\n\n${lines.join("\n\n---\n\n")}`;
}

async function handleSearch(args: Record<string, unknown>): Promise<string> {
  const supabase = makeSupabaseClient();
  const conclave = args.conclave as string;
  const since = args.since as string;
  const fromConclave = args.from_conclave as string | undefined;
  const fromAgent = args.from_agent as string | undefined;
  const includeBroadcast = args.include_broadcast !== false;

  let query = supabase
    .from("hub_messages")
    .select("*")
    .gt("created_at", since)
    .order("created_at", { ascending: false });

  if (includeBroadcast) {
    query = query.or(`to_conclave.eq.${conclave},to_conclave.eq.all`);
  } else {
    query = query.eq("to_conclave", conclave);
  }

  if (fromConclave) {
    query = query.eq("from_conclave", fromConclave);
  }
  if (fromAgent) {
    query = query.eq("from_agent", fromAgent);
  }

  const { data, error } = await query;

  if (error) throw new Error(`Query error: ${error.message}`);

  const messages = data ?? [];

  if (messages.length === 0) {
    return "No messages found.";
  }

  const lines = messages.map((m: Record<string, unknown>) => {
    const status = m.received_at ? `read by ${m.received_by} at ${m.received_at}` : "unread";
    return (
      `## ${m.subject}\n` +
      `**From:** ${m.from_conclave}:${m.from_agent} | **To:** ${m.to_conclave}:${m.to_agent} | **ID:** ${m.id}\n` +
      `**Sent:** ${m.created_at} | **Status:** ${status}\n\n` +
      `${m.body}`
    );
  });

  return `${messages.length} message(s):\n\n${lines.join("\n\n---\n\n")}`;
}

async function handleMarkRead(args: Record<string, unknown>): Promise<string> {
  const supabase = makeSupabaseClient();

  const { error } = await supabase
    .from("hub_messages")
    .update({
      received_at: new Date().toISOString(),
      received_by: args.receiver,
    })
    .eq("id", args.message_id);

  if (error) throw new Error(`Update error: ${error.message}`);

  return `Message ${args.message_id} marked as read by ${args.receiver}.`;
}

// ── Tool dispatch ───────────────────────────────────────────────────────────

async function dispatchTool(name: string, args: Record<string, unknown>): Promise<string> {
  switch (name) {
    case "hub_send": return await handleSend(args);
    case "hub_poll": return await handlePoll(args);
    case "hub_search": return await handleSearch(args);
    case "hub_mark_read": return await handleMarkRead(args);
    default: throw new Error(`Unknown tool: ${name}`);
  }
}

async function handleToolsCall(
  id: unknown,
  params: { name?: string; arguments?: Record<string, unknown> } | undefined,
): Promise<Response> {
  const toolName = params?.name;
  const args = params?.arguments ?? {};

  if (!toolName) {
    return errorResponse(id, -32602, "Invalid params: missing tool name");
  }

  const knownTools = TOOLS.map((t) => t.name);
  if (!knownTools.includes(toolName)) {
    return errorResponse(id, -32602, `Unknown tool: ${toolName}`);
  }

  try {
    const result = await dispatchTool(toolName, args);
    return jsonResponse({
      jsonrpc: "2.0",
      id,
      result: {
        content: [{ type: "text", text: result }],
      },
    });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return errorResponse(id, -32603, msg);
  }
}

// ── Main handler ────────────────────────────────────────────────────────────

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: CORS_HEADERS });
  }

  // 405 on GET — this server does not support SSE notifications.
  if (req.method === "GET") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: CORS_HEADERS,
    });
  }

  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405, headers: CORS_HEADERS });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return errorResponse(null, -32700, "Parse error: invalid JSON");
  }

  const { jsonrpc, id, method, params } = body as {
    jsonrpc?: string;
    id?: unknown;
    method?: string;
    params?: unknown;
  };

  if (jsonrpc !== "2.0") {
    return errorResponse(id ?? null, -32600, "Invalid Request: jsonrpc must be '2.0'");
  }

  if (!method) {
    return errorResponse(id ?? null, -32600, "Invalid Request: missing method");
  }

  switch (method) {
    case "initialize":
      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: MCP_VERSION,
          capabilities: { tools: {} },
          serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
        },
      });

    case "initialized":
    case "notifications/initialized":
      return notificationResponse();

    case "ping":
      return jsonResponse({ jsonrpc: "2.0", id, result: {} });

    case "tools/list":
      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result: { tools: TOOLS },
      });

    case "tools/call":
      return await handleToolsCall(id, params as { name?: string; arguments?: Record<string, unknown> } | undefined);

    default:
      return errorResponse(id, -32601, `Method not found: ${method}`);
  }
});
