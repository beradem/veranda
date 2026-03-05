/**
 * Server-side Supabase client scoped to the current user's session (anon key).
 * Used in API routes to identify WHO is making the request.
 *
 * Separate from lib/supabase.ts (service key) — this one respects Row Level
 * Security and only knows what the logged-in user is allowed to know.
 */

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import type { User } from "@supabase/supabase-js";

export async function getUser(): Promise<User | null> {
  const cookieStore = await cookies();

  const client = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (cookiesToSet) => {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await client.auth.getUser();
  return user;
}
