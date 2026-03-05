/**
 * /api/searches
 *
 * GET  — Return the current user's last 20 saved searches.
 * POST — Save a new search to the history.
 */

import { getUser } from "@/lib/supabase-server-auth";
import { getSupabaseClient } from "@/lib/supabase";

export async function GET() {
  const user = await getUser();
  if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

  const db = getSupabaseClient();
  const { data } = await db
    .from("saved_searches")
    .select("*")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false })
    .limit(20);

  return Response.json({ searches: data ?? [] });
}

export async function DELETE() {
  const user = await getUser();
  if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

  const db = getSupabaseClient();
  await db.from("saved_searches").delete().eq("user_id", user.id);

  return Response.json({ ok: true });
}

export async function POST(request: Request) {
  const user = await getUser();
  if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

  const { serviceDescription, neighborhoods, resultCount } = await request.json();

  const db = getSupabaseClient();
  await db.from("saved_searches").insert({
    user_id: user.id,
    service_description: serviceDescription ?? "",
    neighborhoods: neighborhoods ?? [],
    result_count: resultCount ?? 0,
  });

  return Response.json({ ok: true });
}
