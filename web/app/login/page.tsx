"use client";

/**
 * Login page — shown to unauthenticated users.
 * Triggers Google OAuth via Supabase.
 */

import { useState } from "react";
import { getBrowserClient } from "@/lib/supabase-browser";

export default function LoginPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGoogleLogin = async () => {
    setIsLoading(true);
    setError(null);

    const supabase = getBrowserClient();
    const { data, error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: "https://tryveranda.com/auth/callback",
        skipBrowserRedirect: true,
      },
    });

    if (error || !data?.url) {
      setError("Something went wrong. Please try again.");
      setIsLoading(false);
      return;
    }

    window.location.href = data.url;
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center"
      style={{ backgroundColor: "var(--bg)" }}
    >
      <div
        className="w-full max-w-sm mx-4 p-10 rounded-lg flex flex-col items-center"
        style={{
          backgroundColor: "var(--surface)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Favicon-style V mark */}
        <div className="mb-6">
          <svg width="40" height="40" viewBox="0 0 32 32">
            <rect width="32" height="32" rx="7" fill="var(--card)" />
            <path
              d="M8 9 L16 23 L24 9"
              stroke="var(--gold)"
              strokeWidth="2.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </svg>
        </div>

        {/* Wordmark */}
        <h1
          className="text-3xl font-normal tracking-[0.2em] uppercase mb-1"
          style={{
            fontFamily: "'Playfair Display', Georgia, serif",
            color: "var(--text)",
          }}
        >
          Veranda
        </h1>
        <p
          className="text-[10px] tracking-[0.25em] uppercase mb-8"
          style={{ color: "var(--text-dim)" }}
        >
          NYC Intelligence Platform
        </p>

        <div className="gold-rule w-32 mb-8" />

        {/* Google button */}
        <button
          onClick={handleGoogleLogin}
          disabled={isLoading}
          className="w-full flex items-center justify-center gap-3 py-3 px-4 rounded text-sm font-medium transition-all"
          style={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            color: "var(--text)",
            cursor: isLoading ? "not-allowed" : "pointer",
            opacity: isLoading ? 0.7 : 1,
          }}
          onMouseEnter={(e) => {
            if (!isLoading) e.currentTarget.style.borderColor = "var(--gold-dim)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "var(--border)";
          }}
        >
          {/* Google logo */}
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path
              d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"
              fill="#4285F4"
            />
            <path
              d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"
              fill="#34A853"
            />
            <path
              d="M3.964 10.707A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.039l3.007-2.332z"
              fill="#FBBC05"
            />
            <path
              d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.961L3.964 7.293C4.672 5.163 6.656 3.58 9 3.58z"
              fill="#EA4335"
            />
          </svg>
          {isLoading ? "Redirecting…" : "Continue with Google"}
        </button>

        {error && (
          <p className="mt-4 text-xs text-center" style={{ color: "#ef4444" }}>
            {error}
          </p>
        )}

        <p className="mt-8 text-[10px] text-center" style={{ color: "var(--text-muted)" }}>
          By signing in you agree to access this platform<br />under your authorized account only.
        </p>
      </div>
    </div>
  );
}
