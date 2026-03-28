import { createClient } from "jsr:@supabase/supabase-js@2";

type SupabaseClient = ReturnType<typeof createClient>;

export interface ListVersionsArgs {
  document_id: string;
}

export async function executeListVersions(
  supabase: SupabaseClient,
  args: ListVersionsArgs,
): Promise<unknown[]> {
  if (!args.document_id) {
    throw new Error("document_id is required");
  }

  const { data, error } = await supabase.rpc(
    "cerefox_list_document_versions",
    { p_document_id: args.document_id },
  );

  if (error) {
    throw new Error(error.message);
  }

  return data ?? [];
}
