/**
 * /api/profile
 *
 * GET  — Return the current user's saved service description.
 * PUT  — Upsert (create or update) the user's service description.
 *
 * Uses the service key for DB writes (bypasses RLS) but only after
 * verifying the user's identity via the anon session.
 */

import { getUser } from "@/lib/supabase-server-auth";
import { getSupabaseClient } from "@/lib/supabase";

export async function GET() {
  const user = await getUser();
  if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

  const db = getSupabaseClient();
  const { data } = await db
    .from("user_profiles")
    .select("service_description")
    .eq("id", user.id)
    .single();

  return Response.json({ serviceDescription: data?.service_description ?? "" });
}

export async function PUT(request: Request) {
  const user = await getUser();
  if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

  const { serviceDescription } = await request.json();

  const db = getSupabaseClient();
  await db.from("user_profiles").upsert({
    id: user.id,
    service_description: serviceDescription ?? "",
    updated_at: new Date().toISOString(),
  });

  return Response.json({ ok: true });
}
