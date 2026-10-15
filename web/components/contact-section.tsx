"use client";

/**
 * ContactSection — looks up a lead's phone / email / LinkedIn (Minerva) as
 * soon as the detail panel opens, and renders the result.
 *
 * The server caches every lookup, so re-opening a lead is free; we also keep
 * a per-session cache here so flipping between leads doesn't re-request.
 */

import { useCallback, useEffect, useState } from "react";
import type { ContactDetails, EnrichResponse, Lead } from "@/lib/types";

type State =
  | { kind: "loading" }
  | { kind: "done"; response: EnrichResponse }
  | { kind: "error"; message: string };

const sessionCache = new Map<string, EnrichResponse>();

function formatPhone(raw: string): string {
  const digits = raw.replace(/\D/g, "").replace(/^1(?=\d{10}$)/, "");
  if (digits.length !== 10) return raw;
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] tracking-[0.2em] uppercase mb-3" style={{ color: "var(--text-dim)" }}>
      {children}
    </div>
  );
}

function ContactRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-2" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
      <span
        className="text-[10px] tracking-[0.1em] uppercase flex-shrink-0 w-24 pt-0.5"
        style={{ color: "var(--text-dim)" }}
      >
        {label}
      </span>
      <span className="text-xs min-w-0 break-words" style={{ color: "var(--text)" }}>
        {children}
      </span>
    </div>
  );
}

function ContactCard({ contact }: { contact: ContactDetails }) {
  const hasAnything = contact.phones.length > 0 || contact.emails.length > 0 || contact.linkedin_url;
  if (!hasAnything) {
    return (
      <p className="text-xs" style={{ color: "var(--text-dim)" }}>
        Matched this person, but no phone, email or LinkedIn is on file.
      </p>
    );
  }
  const hasMobile = contact.phones.some((p) => p.type === "Mobile");
  return (
    <div>
      {contact.phones.map((phone) => (
        <ContactRow key={phone.number} label={phone.type === "Mobile" ? "Mobile" : "Phone"}>
          <a href={`tel:${phone.number}`} style={{ color: "var(--gold)" }}>
            {formatPhone(phone.number)}
          </a>
        </ContactRow>
      ))}
      {contact.emails.map((email) => (
        <ContactRow key={email.address} label={email.kind === "work" ? "Work email" : "Email"}>
          <a href={`mailto:${email.address}`} style={{ color: "var(--gold)" }}>
            {email.address}
          </a>
        </ContactRow>
      ))}
      {contact.linkedin_url && (
        <ContactRow label="LinkedIn">
          <a
            href={contact.linkedin_url.startsWith("http") ? contact.linkedin_url : `https://${contact.linkedin_url}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--gold)" }}
          >
            {contact.linkedin_title || "View profile"} ↗
          </a>
        </ContactRow>
      )}
      {hasMobile && (
        <p className="text-[10px] mt-2" style={{ color: "var(--text-dim)" }}>
          Check the Do Not Call registry before calling or texting mobile numbers.
        </p>
      )}
    </div>
  );
}

export function ContactSection({ lead }: { lead: Lead }) {
  const nameKey = lead.name_key;
  const [state, setState] = useState<State>(() => {
    const cached = sessionCache.get(nameKey);
    return cached ? { kind: "done", response: cached } : { kind: "loading" };
  });

  const lookUp = useCallback(
    async (signal?: AbortSignal) => {
      setState({ kind: "loading" });
      try {
        const res = await fetch(`/api/leads/${encodeURIComponent(nameKey)}/enrich`, {
          method: "POST",
          signal,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "Contact lookup failed");
        sessionCache.set(nameKey, data as EnrichResponse);
        setState({ kind: "done", response: data as EnrichResponse });
      } catch (err) {
        if (signal?.aborted) return;
        setState({ kind: "error", message: err instanceof Error ? err.message : "Contact lookup failed" });
      }
    },
    [nameKey]
  );

  useEffect(() => {
    if (sessionCache.has(nameKey)) return;
    const controller = new AbortController();
    lookUp(controller.signal);
    return () => controller.abort();
  }, [nameKey, lookUp]);

  return (
    <section className="mb-6">
      <SectionLabel>Contact</SectionLabel>

      {state.kind === "loading" && (
        <div className="space-y-2" aria-busy="true">
          <p className="text-xs" style={{ color: "var(--text-dim)" }}>
            Looking up contact details…
          </p>
          {[0, 1].map((i) => (
            <div key={i} className="h-3 rounded animate-pulse" style={{ backgroundColor: "var(--card)" }} />
          ))}
        </div>
      )}

      {state.kind === "error" && (
        <div>
          <p className="text-xs" style={{ color: "#ef4444" }}>
            {state.message}
          </p>
          <button
            onClick={() => lookUp()}
            className="mt-2 text-[10px] tracking-[0.1em] uppercase"
            style={{ color: "var(--gold-dim)" }}
          >
            ↺ Try again
          </button>
        </div>
      )}

      {state.kind === "done" && state.response.status === "found" && state.response.contact && (
        <ContactCard contact={state.response.contact} />
      )}

      {state.kind === "done" && state.response.status === "not_found" && (
        <p className="text-xs" style={{ color: "var(--text-dim)" }}>
          No confident contact match for this person.
        </p>
      )}

      {state.kind === "done" && state.response.status === "unavailable" && (
        <p className="text-xs" style={{ color: "var(--text-dim)" }}>
          {state.response.reason ?? "Contact lookup isn't available for this lead."}
        </p>
      )}

      {/* Contact details already on the lead (e.g. from an earlier email reveal) */}
      {state.kind === "done" && state.response.status !== "found" && (lead.email || lead.phone) && (
        <div className="mt-2">
          {lead.phone && <ContactRow label="Phone">{lead.phone}</ContactRow>}
          {lead.email && <ContactRow label="Email">{lead.email}</ContactRow>}
        </div>
      )}
    </section>
  );
}
