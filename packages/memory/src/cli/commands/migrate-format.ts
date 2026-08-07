/**
 * `cerefox server migrate-format` — convert legacy (content_format=1)
 * documents to the exact-partition format (content_format=2, "blind-stitch")
 * without changing their content.
 *
 * Fixes #164: `server reindex` re-embeds chunks in place — it never
 * reconstructs a document's full text and never re-runs the chunker, so it
 * cannot advance content_format despite the docs (previously) claiming it
 * does. Real ingestion is the only path that stamps content_format=2, but
 * `IngestionPipeline.updateDocument` short-circuits to a metadata-only patch
 * whenever content is unchanged (the case for every legacy document with no
 * pending edit), so re-ingesting existing content through the normal path
 * silently does nothing either.
 *
 * This command reconstructs each legacy document's full text via
 * `cerefox_get_document` (already format-aware on read), re-chunks it,
 * re-embeds it, and writes it back through `cerefox_ingest_document`
 * directly — forcing the re-chunk regardless of the content-hash
 * short-circuit, while explicitly preserving `source`, `metadata`, and
 * `review_status` (the pipeline's content-changed branch would otherwise
 * overwrite all three, which is correct for a real edit but wrong for a
 * pure format migration). These are re-read immediately before use rather
 * than trusted from the earlier candidate-listing scan — on a corpus this
 * size (`--all` waves over up to ~1400 documents), that scan can be stale
 * by the time a given document's turn comes up, and the RPC's concurrency
 * guard only covers content_hash, so a title/metadata/source-only edit in
 * the interim wouldn't trip it and the stale snapshot would silently
 * clobber the fresh edit if written back unchanged. title/source/metadata/
 * content_hash come off the SAME row as full_content (cerefox_get_document
 * groups them in one query), so those four have no staleness gap at all;
 * only review_status/source_path need a second, still-late lookup.
 *
 * Idempotent: an already-format-2 document is filtered out of the candidate
 * set, so re-running is always safe. A concurrent edit during a run is
 * treated as a skip, not a failure — either the other write already
 * advanced the format, or the next run will.
 */

import type { Command } from "commander";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import {
  c,
  notFound,
  println,
  printTable,
  resolveAuthor,
  resolveAuthorType,
  systemError,
  userError,
  warn,
} from "../../../../../_shared/cli-core/index.ts";
import { loadSettings } from "../../../../../_shared/config/index.ts";
import { fetchAllPages } from "../../../../../_shared/db-client/paginate.ts";
import { activeEmbedderName, embedBatch, resolveEmbedderKind } from "../../../../../_shared/embeddings/index.ts";
import {
  CONTENT_FORMAT_BLIND_STITCH,
  chunkMarkdown,
  contentHash,
  embeddingInputFor,
} from "../../../../../_shared/ingest/index.ts";
import { IngestionDbBridge } from "../../ingestion/client-bridge.ts";
import {
  ConcurrencyConflictError,
  ConcurrencyTokenRequiredError,
  loadPipelineSettings,
} from "../../ingestion/types.ts";

interface MigrateFormatOptions {
  all?: boolean;
  documentId?: string;
  dryRun?: boolean;
  batch?: string;
  lastWriteWins?: boolean;
  author?: string;
  authorType?: string;
}

interface Candidate {
  id: string;
  title: string;
  source: string | null;
  sourcePath: string | null;
  contentHash: string | null;
  metadata: Record<string, unknown> | null;
  reviewStatus: "approved" | "pending_review";
  chunkCount: number;
}

interface ChunkWithDocRow {
  document_id: string;
  content_format: number;
  cerefox_documents: {
    title: string;
    source: string | null;
    source_path: string | null;
    content_hash: string | null;
    metadata: Record<string, unknown> | null;
    review_status: "approved" | "pending_review";
    deleted_at: string | null;
  } | null;
}

/**
 * One paginated query with the parent document embedded via the FK
 * relationship (same pattern `reindex.ts` uses for `cerefox_documents(title)`)
 * rather than a chunk scan followed by a second `.in(id, [...])` lookup — a
 * store with 1000+ legacy documents blows PostgREST's request-URL length
 * limit on `.in()` and comes back "Bad Request" (found while testing this
 * command against our real store, 1369 legacy docs).
 *
 * A document's chunks are written atomically as a set (§ cerefox_ingest_document),
 * so `min` over one document's rows should already be uniform — taking the min
 * rather than assuming uniformity is a cheap defensive choice.
 */
async function findLegacyCandidates(
  supabase: SupabaseClient,
): Promise<Candidate[]> {
  const chunkRows = await fetchAllPages<ChunkWithDocRow>(
    (from, to) =>
      supabase
        .from("cerefox_chunks")
        .select(
          "document_id, content_format, cerefox_documents(title, source, source_path, content_hash, metadata, review_status, deleted_at)",
        )
        .is("version_id", null)
        .order("id", { ascending: true })
        .range(from, to),
    1000,
  );

  const byDoc = new Map<
    string,
    { minFormat: number; chunkCount: number; doc: ChunkWithDocRow["cerefox_documents"] }
  >();
  for (const row of chunkRows) {
    const existing = byDoc.get(row.document_id);
    if (existing) {
      existing.minFormat = Math.min(existing.minFormat, row.content_format);
      existing.chunkCount += 1;
    } else {
      byDoc.set(row.document_id, {
        minFormat: row.content_format,
        chunkCount: 1,
        doc: row.cerefox_documents,
      });
    }
  }

  // deleted_at IS NULL filter applied client-side here — matches
  // cerefox_content_format_stats()'s own filter so counts agree with what
  // `cerefox doctor` reports.
  const candidates: Candidate[] = [];
  for (const [id, entry] of byDoc) {
    if (entry.minFormat >= CONTENT_FORMAT_BLIND_STITCH) continue;
    if (!entry.doc || entry.doc.deleted_at) continue;
    candidates.push({
      id,
      title: entry.doc.title,
      source: entry.doc.source,
      sourcePath: entry.doc.source_path,
      contentHash: entry.doc.content_hash,
      metadata: entry.doc.metadata,
      reviewStatus: entry.doc.review_status,
      chunkCount: entry.chunkCount,
    });
  }
  return candidates;
}

async function migrateOne(
  bridge: IngestionDbBridge,
  supabase: SupabaseClient,
  candidate: Candidate,
  apiKey: string,
  pipelineSettings: ReturnType<typeof loadPipelineSettings>,
  author: string,
  authorType: "user" | "agent",
  lastWriteWins: boolean,
): Promise<"migrated" | "skipped"> {
  const { data: rows, error } = await supabase.rpc("cerefox_get_document", {
    p_document_id: candidate.id,
    p_version_id: null,
  });
  if (error) {
    throw new Error(`cerefox_get_document failed: ${error.message}`);
  }
  const doc = Array.isArray(rows) ? rows[0] : rows;
  if (!doc || typeof doc.full_content !== "string") {
    throw new Error("cerefox_get_document returned no content.");
  }
  const fullContent: string = doc.full_content;

  // title/source/metadata/content_hash come from the SAME query as
  // full_content (cerefox_get_document's single SELECT groups them all off
  // one row) — not a second, later, separately-stale read. Only
  // review_status/source_path/deleted_at aren't in that RPC's return shape,
  // so those still need one more lookup; the residual staleness window is
  // now just that one call's round-trip, not this whole function's.
  const freshRow = await bridge.getDocumentById(candidate.id);
  if (!freshRow || freshRow.deleted_at) {
    return "skipped";
  }
  const fresh = {
    title: doc.doc_title as string,
    source: doc.doc_source as string | null,
    metadata: doc.doc_metadata as Record<string, unknown> | null,
    contentHash: doc.content_hash as string | null,
    sourcePath: freshRow.source_path,
    reviewStatus: freshRow.review_status as "approved" | "pending_review",
  };

  const chunks = chunkMarkdown(
    fullContent,
    pipelineSettings.maxChunkChars,
    pipelineSettings.minChunkChars,
  );
  if (chunks.length === 0) {
    throw new Error("Re-chunking produced zero chunks — refusing to write an empty document.");
  }
  const texts = chunks.map((chunk) => embeddingInputFor(fresh.title, chunk));
  const embeddings = await embedBatch(texts, apiKey);
  const embedderName = activeEmbedderName();
  const chunkRows = chunks.map((chunk, i) => ({
    chunk_index: chunk.chunk_index,
    heading_path: chunk.heading_path,
    heading_level: chunk.heading_level,
    title: chunk.title,
    content: chunk.content,
    char_count: chunk.char_count,
    embedding: embeddings[i],
    embedder: embedderName,
  }));

  // The reconstructed text is not guaranteed byte-identical to the original
  // pre-chunk source (legacy \n\n-join reconstruction has known lossiness —
  // see chunker.ts's header comment), so its hash generally differs from the
  // document's stored content_hash. That is expected, and exactly what a
  // normal content-changed edit does; the old hash is not preserved.
  const newHash = contentHash(fullContent);

  try {
    await bridge.ingestDocumentRpc({
      documentId: candidate.id,
      title: fresh.title,
      source: fresh.source ?? "unknown",
      sourcePath: fresh.sourcePath,
      contentHash: newHash,
      metadata: fresh.metadata ?? {},
      reviewStatus: fresh.reviewStatus,
      chunks: chunkRows,
      contentFormat: CONTENT_FORMAT_BLIND_STITCH,
      author,
      authorType,
      sourceLabel: "migrate-format",
      retentionHours: pipelineSettings.versionRetentionHours,
      cleanupEnabled: pipelineSettings.versionCleanupEnabled,
      expectedContentHash: fresh.contentHash,
      lastWriteWins,
    });
    return "migrated";
  } catch (err) {
    if (err instanceof ConcurrencyConflictError || err instanceof ConcurrencyTokenRequiredError) {
      return "skipped";
    }
    throw err;
  }
}

async function action(options: MigrateFormatOptions): Promise<void> {
  const settings = loadSettings();
  if (!settings.supabaseUrl || !settings.supabaseKey) {
    throw userError("Supabase credentials not configured — run `cerefox init` first.");
  }
  if (!settings.openaiApiKey && resolveEmbedderKind() !== "local") {
    throw userError("OPENAI_API_KEY not set — required for embeddings.");
  }
  if (!options.all && !options.documentId) {
    throw userError(
      "Pass --all to migrate every legacy document, or -i/--document-id to migrate one.",
    );
  }

  const batchSize = Number.parseInt(options.batch ?? "5", 10);
  if (!Number.isFinite(batchSize) || batchSize < 1) {
    throw userError(`Invalid --batch: ${options.batch}`);
  }
  const dryRun = Boolean(options.dryRun);
  const lastWriteWins = Boolean(options.lastWriteWins);
  const author = resolveAuthor(options.author);
  const authorType = resolveAuthorType(options.authorType);
  if (author === "unknown") {
    warn("No --author / CEREFOX_AUTHOR_NAME set — audit log will record this write as 'unknown'.");
  }

  const supabase = createClient(settings.supabaseUrl, settings.supabaseKey, {
    auth: { persistSession: false },
  });
  const bridge = new IngestionDbBridge(supabase);
  const pipelineSettings = loadPipelineSettings();

  let candidates: Candidate[];
  if (options.documentId) {
    const doc = await bridge.getDocumentById(options.documentId);
    if (!doc) throw notFound(`Document ${options.documentId} not found.`);
    if (doc.deleted_at) {
      throw userError(`Document ${options.documentId} is soft-deleted — restore it first.`);
    }
    const { data: chunkRows, error } = await supabase
      .from("cerefox_chunks")
      .select("content_format")
      .eq("document_id", options.documentId)
      .is("version_id", null);
    if (error) throw systemError(`Failed to read chunks: ${error.message}`);
    const rows = (chunkRows ?? []) as Array<{ content_format: number }>;
    if (rows.length === 0) {
      println(c.dim("(document has zero current chunks — nothing to migrate)"));
      return;
    }
    const minFormat = rows.reduce((m, r) => Math.min(m, r.content_format), CONTENT_FORMAT_BLIND_STITCH);
    if (minFormat >= CONTENT_FORMAT_BLIND_STITCH) {
      println(c.dim("(document already on format 2 — nothing to do)"));
      return;
    }
    candidates = [
      {
        id: doc.id,
        title: doc.title,
        source: doc.source,
        sourcePath: doc.source_path,
        contentHash: doc.content_hash,
        metadata: doc.metadata,
        reviewStatus: doc.review_status as "approved" | "pending_review",
        chunkCount: rows.length,
      },
    ];
  } else {
    try {
      candidates = await findLegacyCandidates(supabase);
    } catch (err) {
      throw systemError(
        `Failed to list legacy documents: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  if (candidates.length === 0) {
    println(c.dim("(nothing to migrate)"));
    return;
  }

  if (dryRun) {
    println(c.bold(`Would migrate ${candidates.length} document(s):`));
    printTable(
      candidates.map((cand) => ({
        id: cand.id,
        title: cand.title,
        chunks: cand.chunkCount,
      })),
    );
    return;
  }

  println(
    c.bold(
      `Migrating ${candidates.length} document(s) ${options.all ? "(--all)" : "(-i)"}`,
    ),
  );

  let done = 0;
  let skipped = 0;
  let errors = 0;
  const apiKey = settings.openaiApiKey ?? "";

  for (let start = 0; start < candidates.length; start += batchSize) {
    const wave = candidates.slice(start, start + batchSize);
    const results = await Promise.allSettled(
      wave.map((cand) =>
        migrateOne(bridge, supabase, cand, apiKey, pipelineSettings, author, authorType, lastWriteWins),
      ),
    );
    for (let i = 0; i < results.length; i++) {
      const result = results[i];
      if (result.status === "fulfilled") {
        if (result.value === "migrated") done += 1;
        else {
          skipped += 1;
          println(c.dim(`  ${wave[i].title}: skipped (concurrent edit — will retry next run)`));
        }
      } else {
        errors += 1;
        const msg = result.reason instanceof Error ? result.reason.message : String(result.reason);
        warn(`${wave[i].title} (${wave[i].id}): ${msg}`);
      }
    }
    println(c.dim(`  ${done + skipped + errors}/${candidates.length}…`));
  }

  println("");
  println(
    c.bold(
      `Migrated ${done} document(s)` +
        (skipped > 0 ? ` · ${skipped} skipped (concurrent edit)` : "") +
        (errors > 0 ? c.yellow(` · ${errors} errors`) : ""),
    ),
  );
  if (errors > 0) {
    throw systemError(`${errors} document(s) failed to migrate — see warnings above.`);
  }
}

export function registerMigrateFormat(parent: Command): void {
  parent
    .command("migrate-format")
    .description(
      "Re-chunk legacy documents (content_format=1) to the exact-partition format (2), " +
        "without changing their content. Idempotent — already-migrated documents are skipped.",
    )
    .option("--all", "Migrate every legacy document.")
    .option("-i, --document-id <uuid>", "Limit migration to a single document.")
    .option("--dry-run", "List candidate documents without writing.")
    .option(
      "--batch <n>",
      "Documents processed concurrently per wave (each document's chunks embed in one call). " +
        "Keep low to respect embedding-API rate limits.",
      "5",
    )
    .option(
      "--last-write-wins",
      "Skip the optimistic-concurrency check instead of treating a race as a skip. Not needed for normal use.",
    )
    .option("-a, --author <name>", "Caller identity (audit log).")
    .option("--author-type <type>", "'user' or 'agent' (default: user).", "user")
    .action(action);
}
