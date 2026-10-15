/**
 * POST /api/leads/[nameKey]/enrich
 *
 * Looks up a lead's phone / email / LinkedIn via Minerva when their detail
 * panel is opened. Each person is paid for at most once: results (including
 * "no match") are cached in the `contact_enrichments` table, which survives
 * the quarterly lead re-sync.
 *
 * Safeguards — this endpoint spends money and returns personal data:
 *  - Logged-in users only.
 *  - The name/address sent to Minerva come from OUR database, not the request
 *    body, so the endpoint can't be used to look up arbitrary people.
 *  - Per-user daily cap (MINERVA_DAILY_LIMIT_PER_USER, default 200).
 *
 * Returns: EnrichResponse (see lib/types.ts)
 */

import { NextRequest, NextResponse } from "next/server";
import { getSupabaseClient } from "@/lib/supabase";
import { getUser } from "@/lib/supabase-server-auth";
import {
  MinervaError,
  buildEnrichRecord,
  enrichOne,
  enrichmentBlocker,
  toContactDetails,
} from "@/lib/minerva";
import type { ContactDetails, EnrichResponse, Lead } from "@/lib/types";

const DEFAULT_DAILY_LIMIT = 200;
const MAX_NAME_KEY_LENGTH = 200;

type LeadForEnrichment = Pick<
  Lead,
  "first_name" | "last_name" | "address" | "zip_code" | "unit_number" | "company"
>;

interface CachedEnrichment {
  is_match: boolean;
  contact: ContactDetails | null;
  enriched_at: string;
}

function fromCache(row: CachedEnrichment): EnrichResponse {
  return {
    status: row.is_match ? "found" : "not_found",
    contact: row.is_match ? row.contact : null,
    cached: true,
    enrichedAt: row.enriched_at,
  };
}

function decodeNameKey(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function dailyLimit(): number {
  const configured = Number(process.env.MINERVA_DAILY_LIMIT_PER_USER);
  return Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_DAILY_LIMIT;
}

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ nameKey: string }> }
) {
  try {
    const user = await getUser();
    if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const nameKey = decodeNameKey((await params).nameKey);
    // name_key is "first_last" lowercased from raw names, so it can contain
    // spaces and punctuation; it's only ever used as a bound query parameter.
    if (!nameKey || nameKey.length > MAX_NAME_KEY_LENGTH || /[\u0000-\u001f]/.test(nameKey)) {
      return NextResponse.json({ error: "Invalid lead" }, { status: 400 });
    }

    const db = getSupabaseClient();

    // 1. Load the lead from our own database
    const { data: lead, error: leadError } = await db
      .from("leads")
      .select("first_name,last_name,address,zip_code,unit_number,company")
      .eq("name_key", nameKey)
      .limit(1)
      .maybeSingle<LeadForEnrichment>();

    if (leadError) {
      console.error("[/api/leads/enrich] lead lookup failed:", leadError);
      return NextResponse.json({ error: "Could not load lead" }, { status: 500 });
    }
    if (!lead) return NextResponse.json({ error: "Lead not found" }, { status: 404 });

    const blocker = enrichmentBlocker(lead);
    if (blocker) {
      const response: EnrichResponse = {
        status: "unavailable",
        contact: null,
        reason: blocker,
        cached: false,
        enrichedAt: null,
      };
      return NextResponse.json(response);
    }

    const zipCode = (lead.zip_code ?? "").trim();

    // 2. Already looked up? Free.
    const { data: cached } = await db
      .from("contact_enrichments")
      .select("is_match,contact,enriched_at")
      .eq("name_key", nameKey)
      .eq("zip_code", zipCode)
      .maybeSingle<CachedEnrichment>();
    if (cached) return NextResponse.json(fromCache(cached));

    // 3. Per-user daily cap
    const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const { count } = await db
      .from("contact_enrichments")
      .select("name_key", { count: "exact", head: true })
      .eq("enriched_by", user.id)
      .gte("enriched_at", since);
    if ((count ?? 0) >= dailyLimit()) {
      return NextResponse.json(
        { error: `Daily contact lookup limit (${dailyLimit()}) reached` },
        { status: 429 }
      );
    }

    // 4. Paid lookup
    const result = await enrichOne(buildEnrichRecord(nameKey, lead));
    const contact = result.is_match ? toContactDetails(result) : null;
    const enrichedAt = new Date().toISOString();

    // 5. Cache it (including "no match", so we don't pay to ask again)
    const { error: saveError } = await db.from("contact_enrichments").upsert({
      name_key: nameKey,
      zip_code: zipCode,
      provider: "minerva",
      is_match: result.is_match,
      minerva_pid: result.minerva_pid ?? null,
      contact,
      enriched_by: user.id,
      enriched_at: enrichedAt,
    });
    if (saveError) {
      // Still return the data — the user paid for it — but flag it loudly
      console.error("[/api/leads/enrich] failed to cache enrichment:", saveError);
    }

    const response: EnrichResponse = {
      status: result.is_match ? "found" : "not_found",
      contact,
      cached: false,
      enrichedAt,
    };
    return NextResponse.json(response);
  } catch (error) {
    if (error instanceof MinervaError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("[/api/leads/enrich]", error);
    return NextResponse.json({ error: "Internal server error" }, { status: 500 });
  }
}
