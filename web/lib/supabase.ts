/**
 * Server-side Supabase client using the service role key.
 *
 * The service key bypasses Row Level Security (RLS) — think of it as a
 * master key that only lives on the server. It is NEVER sent to the browser.
 * All database access flows through Next.js API routes, which act as a
 * secure middle layer between the browser and Supabase.
 */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Lazy singleton — created on first use, not at module load time.
// This prevents build-time errors when env vars aren't set yet.
let _client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (_client) return _client;

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseServiceKey = process.env.SUPABASE_SERVICE_KEY;

  if (!supabaseUrl || !supabaseServiceKey) {
    throw new Error(
      "Missing Supabase environment variables. " +
        "Set NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_KEY in .env.local"
    );
  }

  _client = createClient(supabaseUrl, supabaseServiceKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  });

  return _client;
}

// Convenience export — same API as before, but lazy
export const supabase = {
  from: (...args: Parameters<SupabaseClient["from"]>) =>
    getSupabaseClient().from(...args),
};
