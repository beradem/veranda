/**
 * Minerva contact enrichment — server-only.
 *
 * Minerva matches a person from their name + postal address and returns
 * their phones, emails and LinkedIn. Think of it as handing a concierge a
 * name and a street address and getting back a business card.
 *
 * Docs: https://docs.minerva.io/api-reference/enrich-v2
 *
 * The API key lives only in the server environment (MINERVA_API_KEY) and is
 * never sent to the browser. Import this file from API routes only.
 */

import type { ContactDetails, Lead } from "@/lib/types";

const MINERVA_ENRICH_URL = "https://api.minerva.io/v2/enrich";

// Only what outreach needs. Minerva can return far more (DOB, relatives,
// bankruptcies…) but storing it adds privacy risk without helping sales.
const RETURN_FIELDS = [
  "full_name",
  "personal_emails",
  "professional_emails",
  "phones",
  "linkedin_url",
  "linkedin_title",
  "linkedin_industry",
];

const MAX_PHONES = 3;
const MAX_EMAILS = 3;

interface MinervaPhone {
  phone_rank?: number;
  phone_type?: string;
  phone_number?: string;
}

interface MinervaEmail {
  email_rank?: number;
  email_address?: string;
}

export interface MinervaResult {
  record_id: string;
  is_match: boolean;
  minerva_pid?: string | null;
  match_score?: number | null;
  full_name?: string | null;
  personal_emails?: MinervaEmail[] | null;
  professional_emails?: MinervaEmail[] | null;
  phones?: MinervaPhone[] | null;
  linkedin_url?: string | null;
  linkedin_title?: string | null;
  linkedin_industry?: string | null;
  validation_errors?: unknown;
}

export class MinervaError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Why a lead can't be sent to Minerva, or null if it can. */
export function enrichmentBlocker(lead: Pick<Lead, "first_name" | "last_name" | "address" | "zip_code" | "company">): string | null {
  if (!lead.first_name?.trim() || !lead.last_name?.trim()) {
    // LLC / trust owners are stored with the entity name in last_name only
    return "Owner is a company, not a named person";
  }
  if (!lead.address?.trim() || !lead.zip_code?.trim()) {
    return "No street address on file to match against";
  }
  return null;
}

/** Shape a lead into a Minerva "name + parsed address" lookup. */
export function buildEnrichRecord(
  recordId: string,
  lead: Pick<Lead, "first_name" | "last_name" | "address" | "zip_code" | "unit_number">
): Record<string, string> {
  const record: Record<string, string> = {
    record_id: recordId,
    first_name: lead.first_name.trim(),
    last_name: lead.last_name.trim(),
    address_line_1: (lead.address ?? "").trim(),
    zipcode: (lead.zip_code ?? "").trim(),
  };
  if (lead.unit_number?.trim()) record.address_line_2 = lead.unit_number.trim();
  return record;
}

function byRank<T>(items: T[] | null | undefined, rankKey: keyof T): T[] {
  return [...(items ?? [])].sort(
    (a, b) => (Number(a[rankKey]) || 99) - (Number(b[rankKey]) || 99)
  );
}

/** Flatten a Minerva result into the contact card we store and display. */
export function toContactDetails(result: MinervaResult): ContactDetails {
  const phones = byRank(result.phones, "phone_rank")
    .filter((p) => p.phone_number)
    // Mobiles first — they're the most likely to reach the person directly
    .sort((a, b) => Number(b.phone_type === "Mobile") - Number(a.phone_type === "Mobile"))
    .slice(0, MAX_PHONES)
    .map((p) => ({ number: p.phone_number!, type: p.phone_type ?? null }));

  const personalEmails = byRank(result.personal_emails, "email_rank")
    .map((e) => e.email_address)
    .filter((e): e is string => !!e);
  const workEmails = byRank(result.professional_emails, "email_rank")
    .map((e) => e.email_address)
    .filter((e): e is string => !!e);

  return {
    phones,
    emails: [
      ...personalEmails.map((address) => ({ address, kind: "personal" as const })),
      ...workEmails.map((address) => ({ address, kind: "work" as const })),
    ].slice(0, MAX_EMAILS),
    linkedin_url: result.linkedin_url ?? null,
    linkedin_title: result.linkedin_title ?? null,
    linkedin_industry: result.linkedin_industry ?? null,
    match_score: result.match_score ?? null,
  };
}

/** Call Minerva for a single record. Throws MinervaError on API failure. */
export async function enrichOne(record: Record<string, string>): Promise<MinervaResult> {
  const apiKey = process.env.MINERVA_API_KEY;
  if (!apiKey) throw new MinervaError("Contact enrichment is not configured", 503);

  const response = await fetch(MINERVA_ENRICH_URL, {
    method: "POST",
    headers: { "x-api-key": apiKey, "Content-Type": "application/json" },
    body: JSON.stringify({ records: [record], return_fields: RETURN_FIELDS }),
  });

  if (!response.ok) {
    const detail = await response.text();
    console.error("[minerva] enrich failed", response.status, detail.slice(0, 300));
    if (response.status === 402) throw new MinervaError("Enrichment allowance used up", 402);
    if (response.status === 429) throw new MinervaError("Too many lookups — try again shortly", 429);
    if (response.status === 401 || response.status === 403) {
      throw new MinervaError("Contact enrichment is not configured", 503);
    }
    throw new MinervaError("Contact lookup failed", 502);
  }

  const data = (await response.json()) as { results?: MinervaResult[] };
  const result = data.results?.[0];
  if (!result) throw new MinervaError("Contact lookup returned no result", 502);
  if (result.validation_errors && Object.keys(result.validation_errors as object).length > 0) {
    console.warn("[minerva] validation errors", result.validation_errors);
  }
  return result;
}
