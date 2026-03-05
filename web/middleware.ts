/**
 * Next.js middleware — runs on every request before the page renders.
 *
 * Responsibilities:
 *  1. Refresh the Supabase session cookie if it's about to expire.
 *  2. Redirect unauthenticated users to /login.
 *  3. Redirect authenticated users away from /login back to the dashboard.
 */

import { createServerClient } from "@supabase/ssr";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  const response = NextResponse.next();

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (cookiesToSet) => {
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  // getUser() also refreshes the session if the access token has expired
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;
  const isLoginPage = pathname.startsWith("/login");
  const isCallback = pathname.startsWith("/auth/callback");

  // Let the OAuth callback through — it's the bridge between Google and our app
  if (isCallback) return response;

  // Not logged in → send to login
  if (!user && !isLoginPage) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // Already logged in → don't show login page again
  if (user && isLoginPage) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return response;
}

export const config = {
  // Run on all routes except Next.js internals and static assets
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
