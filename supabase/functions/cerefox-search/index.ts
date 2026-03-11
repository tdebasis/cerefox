import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

/**
 * cerefox-search — Supabase Edge Function
 *
 * Accepts a plain-text query, embeds it server-side using the OpenAI API,
 * then calls the appropriate Cerefox search RPC and returns the results.
 *
 * Agents call this via the Supabase MCP "invoke edge function" tool — no
 * SQL required, no local embedding model needed.
 *
 * Request body (JSON):
 *   query        string   required  Natural-language search query
 *   project_name string   optional  Project to filter by (looked up by name)
 *   match_count  number   optional  Max results (default: 5)
 *   mode         string   optional  "hybrid" | "fts" | "docs" (default: "docs")
 *   alpha        number   optional  Semantic weight for hybrid search (default: 0.7)
 *   min_score    number   optional  Min cosine similarity (default: 0.5)
 *
 * Response: { results: [...], query, mode, match_count, project_name? }
 *
 * Example agent prompt:
 *   "Invoke the cerefox-search edge function with query='knowledge management'
 *    and project_name='Personal'. Summarize the results."
 */

const OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings";
const OPENAI_MODEL = "text-embedding-3-small";
const EMBEDDING_DIMENSIONS = 768;

interface SearchRequest {
  query: string;
  project_name?: string;
  match_count?: number;
  mode?: "hybrid" | "fts" | "docs";
  alpha?: number;
  min_score?: number;
}

async function getEmbedding(text: string, apiKey: string): Promise<number[]> {
  const response = await fetch(OPENAI_EMBEDDING_URL, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: OPENAI_MODEL,
      input: text,
      dimensions: EMBEDDING_DIMENSIONS,
    }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`OpenAI embedding error ${response.status}: ${err}`);
  }

  const data = await response.json();
  return data.data[0].embedding;
}

async function lookupProjectId(
  supabase: ReturnType<typeof createClient>,
  projectName: string,
): Promise<string | null> {
  const { data, error } = await supabase
    .from("cerefox_projects")
    .select("id")
    .ilike("name", projectName)
    .limit(1);

  if (error || !data?.length) return null;
  return data[0].id;
}

Deno.serve(async (req: Request) => {
  // CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, {
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
      },
    });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "POST required" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  let body: SearchRequest;
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON body" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const { query, project_name, match_count = 5, mode = "docs", alpha = 0.7, min_score = 0.5 } =
    body;

  if (!query || typeof query !== "string" || !query.trim()) {
    return new Response(JSON.stringify({ error: "query is required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const openaiKey = Deno.env.get("OPENAI_API_KEY");
  if (!openaiKey) {
    return new Response(
      JSON.stringify({ error: "OPENAI_API_KEY secret not set on this project" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const supabase = createClient(supabaseUrl, supabaseKey);

  // Resolve project name → UUID if provided
  let projectId: string | null = null;
  if (project_name) {
    projectId = await lookupProjectId(supabase, project_name);
    if (!projectId) {
      return new Response(
        JSON.stringify({ error: `Project not found: ${project_name}` }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      );
    }
  }

  // FTS mode doesn't need an embedding
  let embedding: number[] | null = null;
  if (mode !== "fts") {
    try {
      embedding = await getEmbedding(query, openaiKey);
    } catch (err) {
      return new Response(JSON.stringify({ error: String(err) }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  // Call the appropriate RPC
  let rpcName: string;
  let rpcParams: Record<string, unknown>;

  if (mode === "fts") {
    rpcName = "cerefox_fts_search";
    rpcParams = {
      p_query_text: query,
      p_match_count: match_count,
      p_project_id: projectId,
    };
  } else if (mode === "hybrid") {
    rpcName = "cerefox_hybrid_search";
    rpcParams = {
      p_query_text: query,
      p_query_embedding: embedding,
      p_match_count: match_count,
      p_alpha: alpha,
      p_use_upgrade: false,
      p_project_id: projectId,
      p_min_score: min_score,
    };
  } else {
    // "docs" — document-level hybrid search (recommended default)
    rpcName = "cerefox_search_docs";
    rpcParams = {
      p_query_text: query,
      p_query_embedding: embedding,
      p_match_count: match_count,
      p_alpha: alpha,
      p_project_id: projectId,
      p_min_score: min_score,
    };
  }

  const { data, error } = await supabase.rpc(rpcName, rpcParams);

  if (error) {
    return new Response(JSON.stringify({ error: `RPC error: ${error.message}` }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(
    JSON.stringify({
      results: data ?? [],
      query,
      mode,
      match_count,
      project_name: project_name ?? null,
    }),
    {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    },
  );
});
