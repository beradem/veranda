/**
 * Shared utility functions for formatting and data transformation.
 */

import type { Lead, LeadSource } from "./types";

/** Format a dollar amount as a compact string (e.g. $2.4M, $850K) */
export function formatCurrency(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

/** Format square footage with commas (e.g. 4,200 sq ft) */
export function formatArea(sqft: number | null | undefined): string {
  if (sqft == null) return "—";
  return `${sqft.toLocaleString()} sq ft`;
}

/** Format a date string for display (e.g. "Jan 15, 2025") */
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
}

/** Compute the name_key for a lead (matches Python _make_name_key) */
export function makeNameKey(firstName: string, lastName: string): string {
  const clean = (s: string) =>
    s
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "")
      .trim();
  return `${clean(firstName)}_${clean(lastName)}`;
}

/** Human-readable label for a LeadSource */
export function sourceLabel(source: LeadSource): string {
  const labels: Record<LeadSource, string> = {
    sec_edgar: "SEC Insider",
    tax_assessor: "Real Estate",
    professional_mapping: "Professional",
    fec_campaign_finance: "FEC Donor",
    manual: "Manual",
  };
  return labels[source] ?? source;
}

/** Source badge color class */
export function sourceBadgeColor(source: LeadSource): string {
  const colors: Record<LeadSource, string> = {
    sec_edgar: "text-blue-400 bg-blue-400/10 border-blue-400/20",
    tax_assessor: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    professional_mapping: "text-purple-400 bg-purple-400/10 border-purple-400/20",
    fec_campaign_finance: "text-orange-400 bg-orange-400/10 border-orange-400/20",
    manual: "text-gray-400 bg-gray-400/10 border-gray-400/20",
  };
  return colors[source] ?? "text-gray-400 bg-gray-400/10 border-gray-400/20";
}

/** Build Google search URL for a lead */
export function googleSearchUrl(lead: Lead): string {
  const query = [lead.first_name, lead.last_name, lead.city ?? "NYC"]
    .filter(Boolean)
    .join(" ");
  return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}

/** Build LinkedIn search URL for a lead */
export function linkedinSearchUrl(lead: Lead): string {
  if (lead.linkedin_url) return lead.linkedin_url;
  const query = `${lead.first_name} ${lead.last_name} ${lead.company ?? ""}`.trim();
  return `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(query)}`;
}

/** Build Google Maps URL for a lead's address */
export function mapsUrl(address: string | null): string {
  if (!address) return "#";
  return `https://www.google.com/maps/search/${encodeURIComponent(address)}`;
}

/** Return the secondary detail line shown in the lead table */
export function leadSubtitle(lead: Lead): string {
  if (lead.source === "tax_assessor") {
    return [lead.address, lead.zip_code].filter(Boolean).join(" · ") || "—";
  }
  if (lead.source === "sec_edgar") {
    return [lead.company, lead.professional_title].filter(Boolean).join(" · ") || "—";
  }
  if (lead.source === "fec_campaign_finance") {
    return [lead.company, lead.city].filter(Boolean).join(" · ") || "—";
  }
  return [lead.professional_title, lead.company].filter(Boolean).join(" · ") || "—";
}
