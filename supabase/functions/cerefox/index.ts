import "jsr:@supabase/functions-js/edge-runtime.d.ts";

import {
  CORS_HEADERS,
  createServiceClient,
  errorResponse,
  getOpenAIKey,
  jsonResponse,
  notificationResponse,
} from "./shared.ts";
import { executeSearch } from "./tools/search.ts";
import { executeIngest } from "./tools/ingest.ts";
import { executeGetDocument } from "./tools/get-document.ts";
import { executeListVersions } from "./tools/list-versions.ts";
import { executeAuditLog } from "./tools/audit-log.ts";
import { executeMetadata } from "./tools/metadata.ts";

/**
 * cerefox — Consolidated Supabase Edge Function
 *
 * MCP Streamable HTTP server (spec 2025-03-26). All business logic runs
 * inline — no internal fetch() delegation to other edge functions.
 * One MCP call = one edge function invocation.
 *
 * This is a consolidated version of cerefox-mcp that eliminates the
 * gateway-to-worker hop that doubled Supabase invocation counts.
 *
 * Supported clients:
 *   Claude Code    — claude mcp add --transport http cerefox <url> --header "Authorization: Bearer <anon-key>"
 *   Cursor         — url + headers.Authorization in mcp.json
 *   Claude Desktop — npx supergateway --streamableHttp <url> --header "Authorization: Bearer <anon-key>"
 */

const MCP_VERSION = "2025-03-26";
const SERVER_NAME = "cerefox";
const SERVER_VERSION = "0.2.0";

// ── Tool definitions ────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "cerefox_search",
    description:
      "Search the Cerefox personal knowledge base. Returns complete documents ranked by hybrid (FTS + semantic) relevance.",
    inputSchema: {
      type: "object",
      required: ["query"],
      properties: {
        query: {
          type: "string",
          description: "Natural-language search query",
        },
        match_count: {
          type: "integer",
          description: "Maximum number of documents to return (default: 5)",
        },
        project_name: {
          type: "string",
          description:
            "Filter results to a specific project by name (optional)",
        },
        metadata_filter: {
          type: "object",
          description:
            'Optional JSONB containment filter. Only documents whose metadata contains ALL specified key-value pairs are returned. Example: {"type": "decision", "status": "active"}. Call cerefox_list_metadata_keys first to discover available keys and values. Omit to search all documents.',
          additionalProperties: { type: "string" },
        },
        max_bytes: {
          type: "integer",
          description:
            "Optional response size budget in bytes. Results are dropped whole until the budget is satisfied; a truncated flag is set when results are dropped. Defaults to the server maximum (200000). Pass a smaller value if your context window is limited. Values above the server maximum are silently capped.",
        },
      },
    },
  },
  {
    name: "cerefox_ingest",
    description: "Save a note or document to the Cerefox knowledge base.",
    inputSchema: {
      type: "object",
      required: ["title", "content"],
      properties: {
        title: {
          type: "string",
          description: "Document title",
        },
        content: {
          type: "string",
          description: "Markdown content",
        },
        project_name: {
          type: "string",
          description: "Project to assign to (created if absent, optional)",
        },
        source: {
          type: "string",
          description: 'Origin label (default: "agent")',
        },
        update_if_exists: {
          type: "boolean",
          description:
            "When true, update an existing document with the same title instead of creating a new one (default: false)",
        },
        metadata: {
          type: "object",
          description: "Arbitrary JSON metadata (optional)",
        },
        author: {
          type: "string",
          description:
            'Name of the agent or tool performing the ingestion (e.g., "Claude Code", "Cursor"). Recorded in the audit log for attribution. Defaults to "mcp-agent" if not provided.',
        },
      },
    },
  },
  {
    name: "cerefox_list_metadata_keys",
    description:
      "List all metadata keys currently in use across documents in the Cerefox knowledge base. Returns each key with its document count and up to 5 example values.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
  {
    name: "cerefox_get_document",
    description:
      "Retrieve the full reconstructed content of a document. Pass version_id to retrieve an archived version; omit it (or pass null) for the current version. Version UUIDs are returned by cerefox_list_versions.",
    inputSchema: {
      type: "object",
      required: ["document_id"],
      properties: {
        document_id: {
          type: "string",
          description: "UUID of the document to retrieve",
        },
        version_id: {
          type: "string",
          description:
            "UUID of a specific archived version to retrieve (optional)",
        },
      },
    },
  },
  {
    name: "cerefox_list_versions",
    description:
      "List all archived versions of a document, newest first. Returns version_id (use with cerefox_get_document), version_number, source, chunk_count, total_chars, and created_at.",
    inputSchema: {
      type: "object",
      required: ["document_id"],
      properties: {
        document_id: {
          type: "string",
          description:
            "UUID of the document whose version history to list",
        },
      },
    },
  },
  {
    name: "cerefox_get_audit_log",
    description:
      "Retrieve audit log entries showing who changed what and when. Supports filtering by document, author, operation type, and time range. Returns entries with document titles, author attribution, size changes, and descriptions.",
    inputSchema: {
      type: "object",
      properties: {
        document_id: {
          type: "string",
          description: "Filter by document UUID (optional)",
        },
        author: {
          type: "string",
          description: "Filter by author name (optional)",
        },
        operation: {
          type: "string",
          description:
            "Filter by operation type: create, update-content, update-metadata, delete, status-change, archive, unarchive (optional)",
        },
        since: {
          type: "string",
          description:
            "ISO timestamp lower bound for temporal queries (optional)",
        },
        limit: {
          type: "integer",
          description:
            "Maximum number of entries to return (default: 50, max: 200)",
        },
      },
    },
  },
];

// ── Method handlers ──────────────────────────────────────────────────────────

function handleInitialize(id: unknown): Response {
  return jsonResponse({
    jsonrpc: "2.0",
    id,
    result: {
      protocolVersion: MCP_VERSION,
      capabilities: {
        tools: {},
      },
      serverInfo: {
        name: SERVER_NAME,
        version: SERVER_VERSION,
      },
    },
  });
}

function handleToolsList(id: unknown): Response {
  return jsonResponse({
    jsonrpc: "2.0",
    id,
    result: { tools: TOOLS },
  });
}

async function handleToolCall(
  name: string,
  args: Record<string, unknown>,
): Promise<string> {
  const supabase = createServiceClient();

  if (name === "cerefox_search") {
    const openaiKey = getOpenAIKey();
    const result = await executeSearch(supabase, openaiKey, {
      query: args.query as string,
      match_count: (args.match_count as number) ?? 5,
      project_name: args.project_name as string | undefined,
      metadata_filter: (args.metadata_filter as Record<string, string>) ?? null,
      ...(args.max_bytes != null ? { max_bytes: args.max_bytes as number } : {}),
    });

    if (result.results.length === 0) {
      return "No results found.";
    }

    const rows = result.results as Array<{
      document_id?: string;
      doc_title?: string;
      full_content?: string;
      best_score?: number;
      is_partial?: boolean;
      chunk_count?: number;
      total_chars?: number;
    }>;

    const parts: string[] = rows.map((row) => {
      const title = row.doc_title ?? "Untitled";
      const docId = row.document_id ? ` [id: ${row.document_id}]` : "";
      const score =
        row.best_score != null
          ? ` (score: ${row.best_score.toFixed(3)})`
          : "";
      const partial = row.is_partial
        ? ` -- partial (${row.chunk_count} of ${(row.total_chars ?? 0).toLocaleString()} chars)`
        : "";
      return `## ${title}${docId}${score}${partial}\n\n${row.full_content ?? ""}`;
    });

    let output = parts.join("\n\n---\n\n");

    if (result.truncated) {
      output += `\n\n[Results truncated at ${result.response_bytes} bytes. Use a more specific query or a smaller match_count to see more.]`;
    }

    return output;
  }

  if (name === "cerefox_ingest") {
    const openaiKey = getOpenAIKey();
    const result = await executeIngest(supabase, openaiKey, {
      title: args.title as string,
      content: args.content as string,
      project_name: args.project_name as string | undefined,
      source: (args.source as string) ?? "agent",
      update_if_exists: (args.update_if_exists as boolean) ?? false,
      metadata: (args.metadata as Record<string, unknown>) ?? {},
      author: (args.author as string) ?? "mcp-agent",
      author_type: "agent",
    });

    if (result.skipped) {
      return `Document already up-to-date: "${result.title}" (id: ${result.document_id}). ${result.message ?? ""}`.trim();
    }

    if (result.updated) {
      return `Document updated: "${result.title}" (id: ${result.document_id}), ${result.chunk_count} chunk(s), ${result.total_chars} chars.`;
    }

    const projectInfo = result.project_name
      ? `, project: "${result.project_name}"`
      : "";
    return `Document saved: "${result.title}" (id: ${result.document_id}), ${result.chunk_count} chunk(s), ${result.total_chars} chars${projectInfo}.`;
  }

  if (name === "cerefox_list_metadata_keys") {
    const keys = await executeMetadata(supabase);

    if ((keys as unknown[]).length === 0) {
      return "No metadata keys found across documents.";
    }

    return JSON.stringify(keys, null, 2);
  }

  if (name === "cerefox_get_document") {
    try {
      const result = await executeGetDocument(supabase, {
        document_id: args.document_id as string,
        version_id: (args.version_id as string) ?? null,
      });

      const label = result.is_archived
        ? " (archived version)"
        : " (current)";
      return `# ${result.doc_title}${label}\n\n${result.full_content}`;
    } catch (err) {
      if (
        err instanceof Error &&
        err.message === "DOCUMENT_NOT_FOUND"
      ) {
        return "Document not found.";
      }
      throw err;
    }
  }

  if (name === "cerefox_list_versions") {
    const versions = (await executeListVersions(supabase, {
      document_id: args.document_id as string,
    })) as Array<{
      version_id: string;
      version_number: number;
      source: string;
      chunk_count: number;
      total_chars: number;
      created_at: string;
    }>;

    if (!versions?.length) {
      return "No archived versions found for this document.";
    }

    const lines = versions.map(
      (v) =>
        `v${v.version_number} | ${v.created_at.slice(0, 10)} | ${v.source} | ${v.chunk_count} chunks / ${v.total_chars.toLocaleString()} chars | id: ${v.version_id}`,
    );
    return `Archived versions (newest first):\n\n${lines.join("\n")}`;
  }

  if (name === "cerefox_get_audit_log") {
    const entries = (await executeAuditLog(supabase, {
      document_id: (args.document_id as string) ?? undefined,
      author: (args.author as string) ?? undefined,
      operation: (args.operation as string) ?? undefined,
      since: (args.since as string) ?? undefined,
      limit: (args.limit as number) ?? 50,
    })) as Array<{
      id: string;
      document_id: string | null;
      doc_title: string | null;
      operation: string;
      author: string;
      author_type: string;
      size_before: number | null;
      size_after: number | null;
      description: string;
      created_at: string;
    }>;

    if (!entries?.length) return "No audit log entries found.";

    const lines = entries.map((e) => {
      const docLabel =
        e.doc_title ??
        (e.document_id ? e.document_id.slice(0, 8) + "..." : "(deleted)");
      const sizeInfo =
        e.size_before != null && e.size_after != null
          ? ` | ${e.size_before} -> ${e.size_after} chars`
          : e.size_after != null
            ? ` | ${e.size_after} chars`
            : "";
      return `${e.created_at.slice(0, 19)} | ${e.operation} | ${e.author} (${e.author_type}) | ${docLabel}${sizeInfo} | ${e.description}`;
    });

    return `Audit log (${entries.length} entries, newest first):\n\n${lines.join("\n")}`;
  }

  throw new Error(`Unknown tool: ${name}`);
}

async function handleToolsCall(
  id: unknown,
  params:
    | { name?: string; arguments?: Record<string, unknown> }
    | undefined,
): Promise<Response> {
  const toolName = params?.name;
  const args = params?.arguments ?? {};

  if (!toolName) {
    return errorResponse(id, -32602, "Invalid params: missing tool name");
  }

  const knownTools = [
    "cerefox_search",
    "cerefox_ingest",
    "cerefox_list_metadata_keys",
    "cerefox_get_document",
    "cerefox_list_versions",
    "cerefox_get_audit_log",
  ];
  if (!knownTools.includes(toolName)) {
    return errorResponse(id, -32602, `Unknown tool: ${toolName}`);
  }

  try {
    const text = await handleToolCall(toolName, args);
    return jsonResponse({
      jsonrpc: "2.0",
      id,
      result: {
        content: [{ type: "text", text }],
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return errorResponse(id, -32603, message);
  }
}

// ── Main handler ─────────────────────────────────────────────────────────────

Deno.serve(async (req: Request): Promise<Response> => {
  // CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: CORS_HEADERS });
  }

  // GET — health check for MCP clients that probe before connecting.
  if (req.method === "GET") {
    return jsonResponse({
      name: SERVER_NAME,
      version: SERVER_VERSION,
      protocol: "mcp",
      protocolVersion: MCP_VERSION,
      status: "ok",
    });
  }

  if (req.method !== "POST") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: CORS_HEADERS,
    });
  }

  // ── Parse JSON-RPC body ───────────────────────────────────────────────────
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
    return errorResponse(
      id ?? null,
      -32600,
      "Invalid Request: jsonrpc must be '2.0'",
    );
  }

  if (!method) {
    return errorResponse(
      id ?? null,
      -32600,
      "Invalid Request: missing method",
    );
  }

  // ── Method dispatch ───────────────────────────────────────────────────────
  switch (method) {
    case "initialize":
      return handleInitialize(id);

    case "initialized":
    case "notifications/initialized":
      return notificationResponse();

    case "ping":
      return jsonResponse({ jsonrpc: "2.0", id, result: {} });

    case "tools/list":
      return handleToolsList(id);

    case "tools/call":
      return await handleToolsCall(
        id,
        params as
          | { name?: string; arguments?: Record<string, unknown> }
          | undefined,
      );

    default:
      return errorResponse(
        id ?? null,
        -32601,
        `Method not found: ${method}`,
      );
  }
});
