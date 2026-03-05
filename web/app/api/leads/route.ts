/**
 * GET /api/leads
 *
 * Query params:
 *   search        — full-text filter across name, address, company, neighborhood
 *   neighborhoods — comma-separated zip codes to filter by
 *   page          — 1-indexed page number (default: 1)
 *   pageSize      — results per page (default: 100)
 *
 * Returns: { leads: Lead[], total: number }
 */

import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import type { LeadsResponse } from "@/lib/types";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const search = searchParams.get("search")?.trim() ?? "";
    const neighborhoods = searchParams.get("neighborhoods")?.trim() ?? "";
    const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10));
    const pageSize = Math.min(
      500,
      Math.max(1, parseInt(searchParams.get("pageSize") ?? "100", 10))
    );
    const offset = (page - 1) * pageSize;

    let query = supabase
      .from("leads")
      .select("*", { count: "exact" })
      .order("estimated_wealth", { ascending: false, nullsFirst: false });

    // Neighborhood filter (zip codes)
    if (neighborhoods) {
      const zips = neighborhoods.split(",").map((z) => z.trim()).filter(Boolean);
      if (zips.length > 0) {
        query = query.in("zip_code", zips);
      }
    }

    // Full-text search across key columns
    if (search) {
      const term = `%${search}%`;
      query = query.or(
        `first_name.ilike.${term},last_name.ilike.${term},address.ilike.${term},company.ilike.${term},professional_title.ilike.${term},city.ilike.${term},discovery_trigger.ilike.${term}`
      );
    }

    // Pagination
    query = query.range(offset, offset + pageSize - 1);

    const { data, count, error } = await query;

    if (error) throw error;

    const response: LeadsResponse = {
      leads: data ?? [],
      total: count ?? 0,
    };

    return NextResponse.json(response);
  } catch (error) {
    console.error("[/api/leads]", error);
    return NextResponse.json(
      { error: "Failed to fetch leads" },
      { status: 500 }
    );
  }
}
