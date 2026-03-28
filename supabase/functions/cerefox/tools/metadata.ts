import { createClient } from "jsr:@supabase/supabase-js@2";

type SupabaseClient = ReturnType<typeof createClient>;

export async function executeMetadata(
  supabase: SupabaseClient,
): Promise<unknown[]> {
  const { data, error } = await supabase.rpc("cerefox_list_metadata_keys");

  if (error) {
    throw new Error(error.message);
  }

  return data ?? [];
}
