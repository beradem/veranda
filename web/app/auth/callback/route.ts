/**
 * OAuth callback handler.
 *
 * After Google authenticates the user, Supabase redirects here with a
 * one-time `code`. We exchange it for a session and write the resulting
 * cookies directly onto the redirect response so the browser receives
 * them in the same round-trip.
 */

import { createServerClient } from "@supabase/ssr";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");

  // Create the redirect response first so we can attach cookies to it
  const response = NextResponse.redirect(new URL("/", origin));

  if (code) {
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          // Read from the incoming request
          getAll: () => request.cookies.getAll(),
          // Write onto the outgoing redirect response
          setAll: (cookiesToSet) => {
            cookiesToSet.forEach(({ name, value, options }) =>
              response.cookies.set(name, value, options)
            );
          },
        },
      }
    );

    await supabase.auth.exchangeCodeForSession(code);
  }

  return response;
}
