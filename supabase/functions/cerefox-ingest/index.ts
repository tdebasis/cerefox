import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

/**
 * cerefox-ingest — Supabase Edge Function
 *
 * Quick-capture endpoint: accepts a markdown note, chunks it by headings,
 * embeds each chunk with OpenAI, and stores everything in the knowledge base.
 *
 * This is the agent write path — use it for short notes captured during a
 * conversation. For large batch ingestion (directories, PDFs, etc.) use the
 * Python CLI: `cerefox ingest file.md`.
 *
 * Request body (JSON):
 *   title        string   required  Document title
 *   content      string   required  Markdown content
 *   project_name string   optional  Project to assign to (looked up by name, created if absent)
 *   source       string   optional  Origin label (default: "agent")
 *   metadata     object   optional  Arbitrary JSONB metadata
 *
 * Response: { document_id, title, chunk_count, project_id? }
 */

const OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings";
const OPENAI_MODEL = "text-embedding-3-small";
const EMBEDDING_DIMENSIONS = 768;

const MAX_CHUNK_CHARS = 4000;
const MIN_CHUNK_CHARS = 100;
const OVERLAP_CHARS = 200;

interface IngestRequest {
  title: string;
  content: string;
  project_name?: string;
  source?: string;
  metadata?: Record<string, unknown>;
}

interface Chunk {
  heading_path: string[];
  heading_level: number;
  title: string;
  content: string;
  char_count: number;
}

// ── Simple heading-aware chunker (mirrors Python logic) ────────────────────

function chunkMarkdown(text: string): Chunk[] {
  const lines = text.split("\n");
  const chunks: Chunk[] = [];
  let currentHeadings: string[] = [];
  let currentLevel = 0;
  let buffer: string[] = [];

  function flush() {
    const content = buffer.join("\n").trim();
    if (content.length >= MIN_CHUNK_CHARS) {
      // If chunk is oversized, split on blank lines
      if (content.length > MAX_CHUNK_CHARS) {
        const paragraphs = content.split(/\n\n+/);
        let sub = "";
        for (const para of paragraphs) {
          if (sub.length + para.length + 2 > MAX_CHUNK_CHARS && sub.length >= MIN_CHUNK_CHARS) {
            chunks.push(makeChunk(currentHeadings, currentLevel, sub.trim()));
            sub = para;
          } else {
            sub = sub ? sub + "\n\n" + para : para;
          }
        }
        if (sub.trim().length >= MIN_CHUNK_CHARS) {
          chunks.push(makeChunk(currentHeadings, currentLevel, sub.trim()));
        }
      } else {
        chunks.push(makeChunk(currentHeadings, currentLevel, content));
      }
    }
    buffer = [];
  }

  for (const line of lines) {
    const h1 = line.match(/^# (.+)/);
    const h2 = line.match(/^## (.+)/);
    const h3 = line.match(/^### (.+)/);

    if (h1) {
      flush();
      currentHeadings = [h1[1].trim()];
      currentLevel = 1;
    } else if (h2) {
      flush();
      currentHeadings = [currentHeadings[0] ?? "", h2[1].trim()].filter(Boolean);
      currentLevel = 2;
    } else if (h3) {
      flush();
      currentHeadings = [
        currentHeadings[0] ?? "",
        currentHeadings[1] ?? "",
        h3[1].trim(),
      ].filter(Boolean);
      currentLevel = 3;
    } else {
      buffer.push(line);
    }
  }
  flush();

  // Add overlap: prepend last OVERLAP_CHARS of previous chunk to next chunk
  for (let i = 1; i < chunks.length; i++) {
    const prev = chunks[i - 1].content;
    const overlap = prev.slice(-OVERLAP_CHARS);
    if (overlap && !chunks[i].content.startsWith(overlap)) {
      chunks[i] = {
        ...chunks[i],
        content: overlap + "\n\n" + chunks[i].content,
        char_count: overlap.length + 2 + chunks[i].char_count,
      };
    }
  }

  return chunks;
}

function makeChunk(headings: string[], level: number, content: string): Chunk {
  const title = headings[headings.length - 1] ?? "";
  return { heading_path: [...headings], heading_level: level, title, content, char_count: content.length };
}

// ── Embedding ──────────────────────────────────────────────────────────────

async function embedBatch(texts: string[], apiKey: string): Promise<number[][]> {
  const response = await fetch(OPENAI_EMBEDDING_URL, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: OPENAI_MODEL,
      input: texts,
      dimensions: EMBEDDING_DIMENSIONS,
    }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`OpenAI embedding error ${response.status}: ${err}`);
  }

  const data = await response.json();
  const sorted = data.data.sort((a: { index: number }, b: { index: number }) => a.index - b.index);
  return sorted.map((d: { embedding: number[] }) => d.embedding);
}

// ── Content hash (SHA-256 hex) ─────────────────────────────────────────────

async function sha256hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// ── Main handler ───────────────────────────────────────────────────────────

Deno.serve(async (req: Request) => {
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

  let body: IngestRequest;
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON body" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const { title, content, project_name, source = "agent", metadata = {} } = body;

  if (!title?.trim() || !content?.trim()) {
    return new Response(JSON.stringify({ error: "title and content are required" }), {
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

  // Deduplication check
  const contentHash = await sha256hex(content);
  const { data: existing } = await supabase
    .from("cerefox_documents")
    .select("id, title")
    .eq("content_hash", contentHash)
    .limit(1);

  if (existing?.length) {
    return new Response(
      JSON.stringify({
        document_id: existing[0].id,
        title: existing[0].title,
        skipped: true,
        message: "Document already exists (content hash match)",
      }),
      { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" } },
    );
  }

  // Chunk the content
  const chunks = chunkMarkdown(content);
  if (chunks.length === 0) {
    return new Response(JSON.stringify({ error: "Content produced no chunks" }), {
      status: 422,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Embed all chunks
  const texts = chunks.map((c) => c.content);
  let embeddings: number[][];
  try {
    embeddings = await embedBatch(texts, openaiKey);
  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  const totalChars = chunks.reduce((s, c) => s + c.char_count, 0);

  // Insert document record
  const { data: docRows, error: docErr } = await supabase
    .from("cerefox_documents")
    .insert({
      title: title.trim(),
      source,
      content_hash: contentHash,
      metadata,
      chunk_count: chunks.length,
      total_chars: totalChars,
    })
    .select("id");

  if (docErr || !docRows?.length) {
    return new Response(
      JSON.stringify({ error: `Failed to create document: ${docErr?.message ?? "no data"}` }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }

  const documentId = docRows[0].id;

  // Resolve / create project if requested
  let projectId: string | null = null;
  if (project_name) {
    const { data: proj } = await supabase
      .from("cerefox_projects")
      .select("id")
      .ilike("name", project_name)
      .limit(1);

    if (proj?.length) {
      projectId = proj[0].id;
    } else {
      const { data: newProj } = await supabase
        .from("cerefox_projects")
        .insert({ name: project_name })
        .select("id");
      projectId = newProj?.[0]?.id ?? null;
    }

    if (projectId) {
      await supabase
        .from("cerefox_document_projects")
        .insert({ document_id: documentId, project_id: projectId });
    }
  }

  // Insert chunks with embeddings
  const chunkRows = chunks.map((chunk, i) => ({
    document_id: documentId,
    chunk_index: i,
    heading_path: chunk.heading_path,
    heading_level: chunk.heading_level,
    title: chunk.title,
    content: chunk.content,
    char_count: chunk.char_count,
    embedding_primary: embeddings[i],
    embedder_primary: OPENAI_MODEL,
  }));

  const { error: chunkErr } = await supabase.from("cerefox_chunks").insert(chunkRows);

  if (chunkErr) {
    // Clean up the document on chunk insert failure
    await supabase.from("cerefox_documents").delete().eq("id", documentId);
    return new Response(
      JSON.stringify({ error: `Failed to store chunks: ${chunkErr.message}` }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }

  return new Response(
    JSON.stringify({
      document_id: documentId,
      title: title.trim(),
      chunk_count: chunks.length,
      total_chars: totalChars,
      project_id: projectId,
      project_name: project_name ?? null,
    }),
    {
      status: 201,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    },
  );
});
