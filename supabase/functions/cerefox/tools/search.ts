import { createClient } from "jsr:@supabase/supabase-js@2";
import { embedTexts } from "../embeddings.ts";

const MAX_BYTES = 200_000;

type SupabaseClient = ReturnType<typeof createClient>;

export interface SearchArgs {
  query: string;
  project_name?: string;
  match_count?: number;
  mode?: "hybrid" | "fts" | "docs";
  alpha?: number;
  min_score?: number;
  metadata_filter?: Record<string, string> | null;
  max_bytes?: number;
}

export interface SearchResult {
  results: unknown[];
  query: string;
  mode: string;
  match_count: number;
  project_name: string | null;
  metadata_filter: Record<string, string> | null;
  truncated: boolean;
  response_bytes: number;
}

async function lookupProjectId(
  supabase: SupabaseClient,
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

function applyByteBudget(
  rows: unknown[],
  maxBytes: number,
): { accepted: unknown[]; truncated: boolean; usedBytes: number } {
  const accepted: unknown[] = [];
  let usedBytes = 0;
  let truncated = false;

  for (const row of rows) {
    const rowBytes = new TextEncoder().encode(JSON.stringify(row)).length;
    if (usedBytes + rowBytes > maxBytes) {
      truncated = true;
      break;
    }
    accepted.push(row);
    usedBytes += rowBytes;
  }

  return { accepted, truncated, usedBytes };
}

export async function executeSearch(
  supabase: SupabaseClient,
  openaiKey: string,
  args: SearchArgs,
): Promise<SearchResult> {
  const {
    query,
    project_name,
    match_count = 5,
    mode = "docs",
    alpha = 0.7,
    min_score = 0.5,
    metadata_filter = null,
    max_bytes: requested_max_bytes,
  } = args;

  const max_bytes = Math.min(requested_max_bytes ?? MAX_BYTES, MAX_BYTES);

  if (
    metadata_filter !== null &&
    metadata_filter !== undefined &&
    (typeof metadata_filter !== "object" || Array.isArray(metadata_filter))
  ) {
    throw new Error("metadata_filter must be a JSON object or null");
  }

  if (!query || typeof query !== "string" || !query.trim()) {
    throw new Error("query is required");
  }

  // Resolve project name -> UUID if provided
  let projectId: string | null = null;
  if (project_name) {
    projectId = await lookupProjectId(supabase, project_name);
    if (!projectId) {
      throw new Error(`Project not found: ${project_name}`);
    }
  }

  // FTS mode doesn't need an embedding
  let embedding: number[] | null = null;
  if (mode !== "fts") {
    const embeddings = await embedTexts(query, openaiKey);
    embedding = embeddings[0];
  }

  // Call the appropriate RPC
  let rpcName: string;
  let rpcParams: Record<string, unknown>;

  const metaFilterParam =
    metadata_filter && Object.keys(metadata_filter).length > 0
      ? { p_metadata_filter: metadata_filter }
      : {};

  if (mode === "fts") {
    rpcName = "cerefox_fts_search";
    rpcParams = {
      p_query_text: query,
      p_match_count: match_count,
      p_project_id: projectId,
      ...metaFilterParam,
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
      ...metaFilterParam,
    };
  } else {
    rpcName = "cerefox_search_docs";
    rpcParams = {
      p_query_text: query,
      p_query_embedding: embedding,
      p_match_count: match_count,
      p_alpha: alpha,
      p_project_id: projectId,
      p_min_score: min_score,
      ...metaFilterParam,
    };
  }

  const { data, error } = await supabase.rpc(rpcName, rpcParams);

  if (error) {
    throw new Error(`RPC error: ${error.message}`);
  }

  const { accepted, truncated, usedBytes } = applyByteBudget(
    data ?? [],
    max_bytes,
  );

  return {
    results: accepted,
    query,
    mode,
    match_count,
    project_name: project_name ?? null,
    metadata_filter: metadata_filter ?? null,
    truncated,
    response_bytes: usedBytes,
  };
}
