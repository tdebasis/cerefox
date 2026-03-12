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

interface IngestRequest {
  title: string;
  content: string;
  project_name?: string;
  source?: string;
  metadata?: Record<string, unknown>;
  update_if_exists?: boolean;
}

interface Chunk {
  heading_path: string[];
  heading_level: number;
  title: string;
  content: string;
  char_count: number;
}

// ── Heading-aware chunker (mirrors Python logic) ───────────────────────────
//
// Design notes:
//   • Short-circuit for small documents: if the entire document fits within
//     MAX_CHUNK_CHARS, it is returned as a single chunk with no splitting.
//     Splitting small documents at heading boundaries creates fragments too
//     short to embed meaningfully (e.g. a 60-char H2 section). A single
//     chunk preserves full context and produces a better embedding.
//     Heading-aware splitting is only beneficial for large documents where
//     precision matters more than holistic context.
//   • No overlaps between chunks. Each heading section is already semantically
//     self-contained via its heading breadcrumb. Overlaps caused duplicate
//     content when chunks were concatenated for document reconstruction.
//   • Each heading section always becomes its own chunk — small sections are
//     never dropped or merged. The heading line is included in the chunk
//     content, matching Python behaviour and preserving context for search.
//   • Oversized sections (> MAX_CHUNK_CHARS) are split at paragraph boundaries
//     with no overlap.

function chunkMarkdown(text: string): Chunk[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  // Short-circuit: entire document fits in one chunk — skip heading splitting.
  if (trimmed.length <= MAX_CHUNK_CHARS) {
    return [makeChunk([], 0, trimmed)];
  }

  const lines = trimmed.split("\n");
  const chunks: Chunk[] = [];
  let currentHeadings: string[] = [];
  let currentLevel = 0;
  let buffer: string[] = [];

  function flush() {
    const body = buffer.join("\n").trim();
    buffer = [];

    // Build content including the heading line (mirrors Python behaviour).
    let content: string;
    if (currentLevel > 0) {
      const headerLine = "#".repeat(currentLevel) + " " + (currentHeadings[currentHeadings.length - 1] ?? "");
      content = body ? headerLine + "\n\n" + body : headerLine;
    } else {
      content = body; // preamble: no heading line
    }

    if (!content.trim()) return;

    if (content.length > MAX_CHUNK_CHARS) {
      // Section too large — split at paragraph boundaries (no overlap).
      // The heading prefix is prepended to the first piece only.
      const headerPrefix = currentLevel > 0
        ? "#".repeat(currentLevel) + " " + (currentHeadings[currentHeadings.length - 1] ?? "") + "\n\n"
        : "";
      const bodyToSplit = body || content;
      const paragraphs = bodyToSplit.split(/\n\n+/);
      let sub = "";
      let isFirst = true;
      for (const para of paragraphs) {
        const prefix = isFirst ? headerPrefix : "";
        if (sub.length + prefix.length + para.length + 2 > MAX_CHUNK_CHARS && sub.length > 0) {
          chunks.push(makeChunk(currentHeadings, currentLevel, sub.trim()));
          sub = para;
          isFirst = false;
        } else {
          sub = sub ? sub + "\n\n" + para : prefix + para;
          isFirst = false;
        }
      }
      if (sub.trim()) {
        chunks.push(makeChunk(currentHeadings, currentLevel, sub.trim()));
      }
    } else {
      // Every heading section always gets its own chunk, regardless of size.
      chunks.push(makeChunk(currentHeadings, currentLevel, content));
    }
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

  const { title, content, project_name, source = "agent", metadata = {}, update_if_exists = false } = body;

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

  const contentHash = await sha256hex(content);
  const headers = { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" };

  // ── Update-existing path ────────────────────────────────────────────────────
  if (update_if_exists) {
    const { data: existing } = await supabase
      .from("cerefox_documents")
      .select("id, title, content_hash")
      .eq("title", title.trim())
      .order("updated_at", { ascending: false })
      .limit(1);

    if (existing?.length) {
      const existingDoc = existing[0];

      // Content unchanged — skip re-indexing
      if (existingDoc.content_hash === contentHash) {
        return new Response(
          JSON.stringify({
            document_id: existingDoc.id,
            title: existingDoc.title,
            skipped: true,
            updated: false,
            message: "Document already up-to-date (content hash match)",
          }),
          { headers },
        );
      }

      // Content changed — re-chunk, re-embed, swap chunks
      const chunks = chunkMarkdown(content);
      if (chunks.length === 0) {
        return new Response(JSON.stringify({ error: "Content produced no chunks" }), {
          status: 422, headers,
        });
      }

      const texts = chunks.map((c) => c.content);
      let embeddings: number[][];
      try {
        embeddings = await embedBatch(texts, openaiKey);
      } catch (err) {
        return new Response(JSON.stringify({ error: String(err) }), { status: 502, headers });
      }

      const totalChars = chunks.reduce((s, c) => s + c.char_count, 0);

      // Delete old chunks
      await supabase.from("cerefox_chunks").delete().eq("document_id", existingDoc.id);

      // Update document record
      await supabase
        .from("cerefox_documents")
        .update({ content_hash: contentHash, chunk_count: chunks.length, total_chars: totalChars })
        .eq("id", existingDoc.id);

      // Insert new chunks
      const chunkRows = chunks.map((chunk, i) => ({
        document_id: existingDoc.id,
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
        return new Response(
          JSON.stringify({ error: `Failed to store updated chunks: ${chunkErr.message}` }),
          { status: 500, headers },
        );
      }

      return new Response(
        JSON.stringify({
          document_id: existingDoc.id,
          title: existingDoc.title,
          chunk_count: chunks.length,
          total_chars: totalChars,
          updated: true,
        }),
        { headers },
      );
    }
    // No match found — fall through to normal create below
  }

  // ── Hash deduplication (normal create path) ────────────────────────────────
  const { data: hashMatch } = await supabase
    .from("cerefox_documents")
    .select("id, title")
    .eq("content_hash", contentHash)
    .limit(1);

  if (hashMatch?.length) {
    return new Response(
      JSON.stringify({
        document_id: hashMatch[0].id,
        title: hashMatch[0].title,
        skipped: true,
        message: "Document already exists (content hash match)",
      }),
      { headers },
    );
  }

  // Chunk the content
  const chunks = chunkMarkdown(content);
  if (chunks.length === 0) {
    return new Response(JSON.stringify({ error: "Content produced no chunks" }), {
      status: 422,
      headers,
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
      headers,
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
      { status: 500, headers },
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
      { status: 500, headers },
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
      headers,
    },
  );
});
