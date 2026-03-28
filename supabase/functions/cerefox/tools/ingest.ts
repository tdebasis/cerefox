import { createClient } from "jsr:@supabase/supabase-js@2";
import { embedTexts, OPENAI_MODEL } from "../embeddings.ts";

const MAX_CHUNK_CHARS = 4000;

type SupabaseClient = ReturnType<typeof createClient>;

export interface IngestArgs {
  title: string;
  content: string;
  project_name?: string;
  source?: string;
  metadata?: Record<string, unknown>;
  update_if_exists?: boolean;
  author?: string;
  author_type?: string;
}

export interface IngestResult {
  document_id: string;
  title: string;
  chunk_count?: number;
  total_chars?: number;
  skipped?: boolean;
  updated?: boolean;
  message?: string;
  project_id?: string | null;
  project_name?: string | null;
}

// ── Heading-aware chunker ────────────────────────────────────────────────

interface Chunk {
  heading_path: string[];
  heading_level: number;
  title: string;
  content: string;
  char_count: number;
}

interface Section {
  level: number;
  headings: string[];
  heading: string;
  content: string;
  body: string;
}

function parseSections(text: string): Section[] {
  const lines = text.split("\n");
  const sections: Section[] = [];
  let currentHeadings: string[] = [];
  let currentLevel = 0;
  let bodyLines: string[] = [];

  function collectSection() {
    const body = bodyLines.join("\n").trim();
    bodyLines = [];
    let content: string;
    if (currentLevel > 0) {
      const headerLine =
        "#".repeat(currentLevel) +
        " " +
        (currentHeadings[currentHeadings.length - 1] ?? "");
      content = body ? headerLine + "\n\n" + body : headerLine;
    } else {
      content = body;
    }
    if (!content.trim()) return;
    sections.push({
      level: currentLevel,
      headings: [...currentHeadings],
      heading: currentHeadings[currentHeadings.length - 1] ?? "",
      content,
      body,
    });
  }

  for (const line of lines) {
    const h1 = line.match(/^# (.+)/);
    const h2 = line.match(/^## (.+)/);
    const h3 = line.match(/^### (.+)/);

    if (h1) {
      collectSection();
      currentHeadings = [h1[1].trim()];
      currentLevel = 1;
    } else if (h2) {
      collectSection();
      currentHeadings = [currentHeadings[0] ?? "", h2[1].trim()].filter(
        Boolean,
      );
      currentLevel = 2;
    } else if (h3) {
      collectSection();
      currentHeadings = [
        currentHeadings[0] ?? "",
        currentHeadings[1] ?? "",
        h3[1].trim(),
      ].filter(Boolean);
      currentLevel = 3;
    } else {
      bodyLines.push(line);
    }
  }
  collectSection();
  return sections;
}

function makeChunk(
  headings: string[],
  level: number,
  content: string,
): Chunk {
  const title = headings[headings.length - 1] ?? "";
  return {
    heading_path: [...headings],
    heading_level: level,
    title,
    content,
    char_count: content.length,
  };
}

function chunkMarkdown(text: string): Chunk[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  if (trimmed.length <= MAX_CHUNK_CHARS) {
    return [makeChunk([], 0, trimmed)];
  }

  const sections = parseSections(trimmed);
  const chunks: Chunk[] = [];

  let bufParts: string[] = [];
  let bufHeadings: string[] = [];
  let bufLevel = 0;
  let bufChars = 0;

  function flushBuf() {
    if (bufParts.length === 0) return;
    chunks.push(makeChunk(bufHeadings, bufLevel, bufParts.join("\n\n")));
    bufParts = [];
    bufHeadings = [];
    bufLevel = 0;
    bufChars = 0;
  }

  for (const section of sections) {
    const { level, headings, heading, content, body } = section;

    if (content.length > MAX_CHUNK_CHARS) {
      flushBuf();
      const headerPrefix =
        level > 0 ? "#".repeat(level) + " " + heading + "\n\n" : "";
      const bodyToSplit = body || content;
      const paragraphs = bodyToSplit.split(/\n\n+/);
      let sub = "";
      let isFirst = true;
      for (const para of paragraphs) {
        const prefix = isFirst ? headerPrefix : "";
        if (
          sub.length + prefix.length + para.length + 2 > MAX_CHUNK_CHARS &&
          sub.length > 0
        ) {
          chunks.push(makeChunk(headings, level, sub.trim()));
          sub = para;
          isFirst = false;
        } else {
          sub = sub ? sub + "\n\n" + para : prefix + para;
          isFirst = false;
        }
      }
      if (sub.trim()) chunks.push(makeChunk(headings, level, sub.trim()));
      continue;
    }

    const addition = content.length + (bufParts.length > 0 ? 2 : 0);

    if (bufChars + addition <= MAX_CHUNK_CHARS) {
      if (bufParts.length === 0) {
        bufHeadings = headings;
        bufLevel = level;
      }
      bufParts.push(content);
      bufChars += addition;
    } else {
      flushBuf();
      bufParts = [content];
      bufHeadings = headings;
      bufLevel = level;
      bufChars = content.length;
    }
  }

  flushBuf();
  return chunks;
}

// ── Content normalisation + hash ─────────────────────────────────────────
// Must stay in sync with pipeline.py::_normalize / _hash.

function normalizeContent(text: string): string {
  return text
    .trim()
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/\n{3,}/g, "\n\n");
}

async function sha256hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// ── Main execute function ────────────────────────────────────────────────

export async function executeIngest(
  supabase: SupabaseClient,
  openaiKey: string,
  args: IngestArgs,
): Promise<IngestResult> {
  const {
    title,
    content,
    project_name,
    source = "agent",
    metadata = {},
    update_if_exists = false,
    author = "agent",
    author_type = "agent",
  } = args;

  if (!title?.trim() || !content?.trim()) {
    throw new Error("title and content are required");
  }

  const contentHash = await sha256hex(normalizeContent(content));

  // ── Update-existing path ─────────────────────────────────────────────
  if (update_if_exists) {
    const { data: existing } = await supabase
      .from("cerefox_documents")
      .select("id, title, content_hash")
      .eq("title", title.trim())
      .order("updated_at", { ascending: false })
      .limit(1);

    if (existing?.length) {
      const existingDoc = existing[0];

      if (existingDoc.content_hash === contentHash) {
        return {
          document_id: existingDoc.id,
          title: existingDoc.title,
          skipped: true,
          updated: false,
          message: "Document already up-to-date (content hash match)",
        };
      }

      const chunks = chunkMarkdown(content);
      if (chunks.length === 0) {
        throw new Error("Content produced no chunks");
      }

      const texts = chunks.map((c) => c.content);
      const embeddings = await embedTexts(texts, openaiKey);

      const totalChars = chunks.reduce((s, c) => s + c.char_count, 0);
      const reviewStatus =
        author_type === "agent" ? "pending_review" : "approved";

      const chunkData = chunks.map((chunk, i) => ({
        chunk_index: i,
        heading_path: chunk.heading_path,
        heading_level: chunk.heading_level,
        title: chunk.title,
        content: chunk.content,
        char_count: chunk.char_count,
        embedding: embeddings[i],
        embedder: OPENAI_MODEL,
      }));

      const { error: ingestErr } = await supabase.rpc(
        "cerefox_ingest_document",
        {
          p_document_id: existingDoc.id,
          p_title: existingDoc.title,
          p_source: source,
          p_content_hash: contentHash,
          p_metadata: metadata,
          p_review_status: reviewStatus,
          p_chunks: chunkData,
          p_author: author,
          p_author_type: author_type,
          p_source_label: source,
        },
      );

      if (ingestErr) {
        throw new Error(`Ingest RPC failed: ${ingestErr.message}`);
      }

      return {
        document_id: existingDoc.id,
        title: existingDoc.title,
        chunk_count: chunks.length,
        total_chars: totalChars,
        updated: true,
      };
    }
    // No match found -- fall through to normal create below
  }

  // ── Hash deduplication (normal create path) ────────────────────────────
  const { data: hashMatch } = await supabase
    .from("cerefox_documents")
    .select("id, title")
    .eq("content_hash", contentHash)
    .limit(1);

  if (hashMatch?.length) {
    return {
      document_id: hashMatch[0].id,
      title: hashMatch[0].title,
      skipped: true,
      message: "Document already exists (content hash match)",
    };
  }

  // Chunk the content
  const chunks = chunkMarkdown(content);
  if (chunks.length === 0) {
    throw new Error("Content produced no chunks");
  }

  // Embed all chunks
  const texts = chunks.map((c) => c.content);
  const embeddings = await embedTexts(texts, openaiKey);

  const totalChars = chunks.reduce((s, c) => s + c.char_count, 0);
  const reviewStatus = author_type === "agent" ? "pending_review" : "approved";

  const chunkData = chunks.map((chunk, i) => ({
    chunk_index: i,
    heading_path: chunk.heading_path,
    heading_level: chunk.heading_level,
    title: chunk.title,
    content: chunk.content,
    char_count: chunk.char_count,
    embedding: embeddings[i],
    embedder: OPENAI_MODEL,
  }));

  const { data: ingestResult, error: ingestErr } = await supabase.rpc(
    "cerefox_ingest_document",
    {
      p_document_id: null,
      p_title: title.trim(),
      p_source: source,
      p_content_hash: contentHash,
      p_metadata: metadata,
      p_review_status: reviewStatus,
      p_chunks: chunkData,
      p_author: author,
      p_author_type: author_type,
    },
  );

  if (ingestErr || !ingestResult?.length) {
    throw new Error(
      `Ingest RPC failed: ${ingestErr?.message ?? "no data returned"}`,
    );
  }

  const documentId = ingestResult[0].document_id;

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

  return {
    document_id: documentId,
    title: title.trim(),
    chunk_count: chunks.length,
    total_chars: totalChars,
    project_id: projectId,
    project_name: project_name ?? null,
  };
}
