import { createClient } from "jsr:@supabase/supabase-js@2";

type SupabaseClient = ReturnType<typeof createClient>;

export interface AuditLogArgs {
  document_id?: string;
  author?: string;
  operation?: string;
  since?: string;
  until?: string;
  limit?: number;
}

export async function executeAuditLog(
  supabase: SupabaseClient,
  args: AuditLogArgs,
): Promise<unknown[]> {
  const params: Record<string, unknown> = {};
  if (args.document_id) params.p_document_id = args.document_id;
  if (args.author) params.p_author = args.author;
  if (args.operation) params.p_operation = args.operation;
  if (args.since) params.p_since = args.since;
  if (args.until) params.p_until = args.until;
  if (args.limit) params.p_limit = Math.min(Number(args.limit) || 50, 200);

  const { data, error } = await supabase.rpc(
    "cerefox_list_audit_entries",
    params,
  );

  if (error) {
    throw new Error(error.message);
  }

  return data ?? [];
}
