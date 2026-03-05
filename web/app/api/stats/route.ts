/**
 * GET /api/stats
 *
 * Returns lead count and last sync timestamp.
 * Called on sidebar mount to show current database state.
 */

import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import type { StatsResponse } from "@/lib/types";

export async function GET() {
  try {
    // Count total leads
    const { count, error: countError } = await supabase
      .from("leads")
      .select("*", { count: "exact", head: true });

    if (countError) throw countError;

    // Get last successful sync
    const { data: syncData, error: syncError } = await supabase
      .from("sync_log")
      .select("completed_at")
      .eq("status", "completed")
      .order("completed_at", { ascending: false })
      .limit(1)
      .single();

    // syncError is OK — table might be empty
    const lastSync = syncData?.completed_at ?? null;

    const response: StatsResponse = {
      leadCount: count ?? 0,
      lastSync,
    };

    return NextResponse.json(response);
  } catch (error) {
    console.error("[/api/stats]", error);
    return NextResponse.json(
      { error: "Failed to fetch stats" },
      { status: 500 }
    );
  }
}
