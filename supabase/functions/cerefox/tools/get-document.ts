import { createClient } from "jsr:@supabase/supabase-js@2";

type SupabaseClient = ReturnType<typeof createClient>;

export interface GetDocumentArgs {
  document_id: string;
  version_id?: string | null;
}

export interface GetDocumentResult {
  document_id: string;
  doc_title: string;
  full_content: string;
  chunk_count: number;
  total_chars: number;
  is_archived: boolean;
  version_id: string | null;
}

export async function executeGetDocument(
  supabase: SupabaseClient,
  args: GetDocumentArgs,
): Promise<GetDocumentResult> {
  const { document_id, version_id = null } = args;

  if (!document_id) {
    throw new Error("document_id is required");
  }

  const { data, error } = await supabase.rpc("cerefox_get_document", {
    p_document_id: document_id,
    p_version_id: version_id,
  });

  if (error) {
    throw new Error(error.message);
  }

  const row = data?.[0] as {
    doc_title?: string;
    full_content?: string;
    chunk_count?: number;
    total_chars?: number;
  } | undefined;

  if (!row) {
    throw new Error("DOCUMENT_NOT_FOUND");
  }

  return {
    document_id,
    doc_title: row.doc_title ?? "Untitled",
    full_content: row.full_content ?? "",
    chunk_count: row.chunk_count ?? 0,
    total_chars: row.total_chars ?? 0,
    is_archived: version_id !== null,
    version_id,
  };
}
