"use client";

/**
 * DetailPanel — Fixed right panel showing lead details, wealth signals,
 * and outreach generation. Slides in when a lead is selected.
 */

import { useState } from "react";
import type { Lead } from "@/lib/types";
import {
  formatCurrency,
  formatArea,
  formatDate,
  sourceLabel,
  sourceBadgeColor,
  googleSearchUrl,
  linkedinSearchUrl,
  mapsUrl,
} from "@/lib/utils";
import { zipToNeighborhood } from "@/lib/neighborhoods";

interface DetailPanelProps {
  lead: Lead | null;
  serviceDescription: string;
  onClose: () => void;
  onOutreachGenerated: (lead: Lead) => void;
}

function DataRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex items-start gap-3 py-2" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
      <span
        className="text-[10px] tracking-[0.1em] uppercase flex-shrink-0 w-24 pt-0.5"
        style={{ color: "var(--text-dim)" }}
      >
        {label}
      </span>
      <span className="text-xs" style={{ color: "var(--text)" }}>
        {value}
      </span>
    </div>
  );
}

export function DetailPanel({
  lead,
  serviceDescription,
  onClose,
  onOutreachGenerated,
}: DetailPanelProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync draft from lead when it changes
  const currentDraft = draft ?? lead?.outreach_draft ?? null;

  const generateOutreach = async () => {
    if (!lead) return;
    if (!serviceDescription.trim()) {
      setError("Please enter a service description in the sidebar first.");
      return;
    }
    setIsGenerating(true);
    setError(null);
    try {
      const res = await fetch(`/api/leads/${lead.name_key}/outreach`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serviceDescription, lead }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Generation failed");
      setDraft(data.draft);
      onOutreachGenerated({ ...lead, outreach_draft: data.draft, outreach_status: "draft_ready" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setIsGenerating(false);
    }
  };

  if (!lead) {
    return null;
  }

  const neighborhood = zipToNeighborhood(lead.zip_code);

  return (
    <div
      className="fixed right-0 top-0 h-screen flex flex-col overflow-hidden"
      style={{
        width: "22rem",
        backgroundColor: "var(--surface)",
        borderLeft: "1px solid var(--border)",
      }}
    >
      {/* Header */}
      <div className="px-5 pt-5 pb-4" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <h2
              className="text-xl font-normal leading-tight"
              style={{
                fontFamily: "'Playfair Display', Georgia, serif",
                color: "var(--text)",
              }}
            >
              {lead.first_name} {lead.last_name}
            </h2>
            <p
              className="text-xs mt-1 truncate"
              style={{ color: "var(--gold)" }}
              title={lead.discovery_trigger}
            >
              {lead.discovery_trigger}
            </p>
          </div>
          <button
            onClick={onClose}
            className="ml-3 flex-shrink-0 w-7 h-7 flex items-center justify-center rounded transition-colors"
            style={{ color: "var(--text-dim)" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-dim)")}
          >
            ✕
          </button>
        </div>

        {/* Source + wealth */}
        <div className="flex items-center gap-2 mt-3">
          <span
            className={`text-[10px] tracking-[0.1em] uppercase px-2 py-0.5 rounded border ${sourceBadgeColor(lead.source)}`}
          >
            {sourceLabel(lead.source)}
          </span>
          {lead.estimated_wealth && (
            <span className="text-xs font-medium" style={{ color: "var(--gold)" }}>
              {formatCurrency(lead.estimated_wealth)}
            </span>
          )}
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {/* Location & property */}
        <section className="mb-6">
          <div
            className="text-[10px] tracking-[0.2em] uppercase mb-3"
            style={{ color: "var(--text-dim)" }}
          >
            Property Details
          </div>
          <DataRow label="Neighborhood" value={neighborhood !== "NYC" ? neighborhood : null} />
          <DataRow label="Address" value={lead.address} />
          <DataRow label="City" value={lead.city} />
          <DataRow label="ZIP" value={lead.zip_code} />
          <DataRow label="Unit" value={lead.unit_number} />
          <DataRow label="Built" value={lead.year_built?.toString()} />
          <DataRow label="Building" value={lead.building_type} />
          <DataRow label="Floors" value={lead.num_floors?.toString()} />
          <DataRow label="Size" value={formatArea(lead.building_area)} />
          <DataRow label="Lot" value={formatArea(lead.lot_area)} />
          <DataRow label="Sale Price" value={formatCurrency(lead.deed_sale_amount)} />
          <DataRow label="Sale Date" value={formatDate(lead.deed_date)} />
        </section>

        {/* Professional */}
        {(lead.professional_title || lead.company) && (
          <section className="mb-6">
            <div
              className="text-[10px] tracking-[0.2em] uppercase mb-3"
              style={{ color: "var(--text-dim)" }}
            >
              Professional
            </div>
            <DataRow label="Title" value={lead.professional_title} />
            <DataRow label="Company" value={lead.company} />
          </section>
        )}

        {/* Contact */}
        {(lead.email || lead.phone) && (
          <section className="mb-6">
            <div
              className="text-[10px] tracking-[0.2em] uppercase mb-3"
              style={{ color: "var(--text-dim)" }}
            >
              Contact
            </div>
            <DataRow label="Email" value={lead.email} />
            <DataRow label="Phone" value={lead.phone} />
          </section>
        )}

        {/* Search links */}
        <section className="mb-6">
          <div
            className="text-[10px] tracking-[0.2em] uppercase mb-3"
            style={{ color: "var(--text-dim)" }}
          >
            Research
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              { label: "Google", href: googleSearchUrl(lead) },
              { label: "LinkedIn", href: linkedinSearchUrl(lead) },
              ...(lead.address
                ? [{ label: "Maps", href: mapsUrl(lead.address) }]
                : []),
            ].map(({ label, href }) => (
              <a
                key={label}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[10px] tracking-[0.1em] uppercase px-3 py-1.5 rounded transition-colors"
                style={{
                  backgroundColor: "var(--card)",
                  border: "1px solid var(--border)",
                  color: "var(--text-dim)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--gold-dim)";
                  e.currentTarget.style.color = "var(--gold)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--border)";
                  e.currentTarget.style.color = "var(--text-dim)";
                }}
              >
                {label} ↗
              </a>
            ))}
          </div>
        </section>

        {/* Outreach */}
        <section>
          <div
            className="text-[10px] tracking-[0.2em] uppercase mb-3"
            style={{ color: "var(--text-dim)" }}
          >
            Outreach Draft
          </div>

          {currentDraft ? (
            <div>
              <textarea
                value={currentDraft}
                onChange={(e) => setDraft(e.target.value)}
                rows={6}
                className="w-full text-xs rounded px-3 py-2.5 resize-none outline-none"
                style={{
                  backgroundColor: "var(--card)",
                  border: "1px solid var(--gold-dim)",
                  color: "var(--text)",
                  lineHeight: "1.7",
                }}
              />
              <button
                onClick={generateOutreach}
                disabled={isGenerating}
                className="mt-2 text-[10px] tracking-[0.1em] uppercase px-3 py-1.5 rounded transition-colors"
                style={{ color: "var(--gold-dim)", cursor: "pointer" }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--gold)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--gold-dim)")}
              >
                {isGenerating ? "Regenerating…" : "↺ Regenerate"}
              </button>
            </div>
          ) : (
            <button
              onClick={generateOutreach}
              disabled={isGenerating}
              className="w-full py-2.5 text-xs tracking-[0.15em] uppercase rounded transition-all"
              style={{
                border: "1px solid var(--gold-dim)",
                color: isGenerating ? "var(--gold-dim)" : "var(--gold)",
                cursor: isGenerating ? "not-allowed" : "pointer",
                backgroundColor: "transparent",
              }}
              onMouseEnter={(e) => {
                if (!isGenerating) {
                  e.currentTarget.style.backgroundColor = "var(--gold-bg)";
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              {isGenerating ? "Writing…" : "✦ Write Outreach"}
            </button>
          )}

          {error && (
            <p className="mt-2 text-xs" style={{ color: "#ef4444" }}>
              {error}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
