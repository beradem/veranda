"use client";

/**
 * Sidebar — Fixed left panel.
 *
 * Fully controlled: parent (page.tsx) owns serviceDescription and
 * selectedNeighborhoods so it can restore past searches without imperative hacks.
 *
 * Sections:
 *  - Brand + user avatar + logout
 *  - Stats (lead count, last sync)
 *  - Service description textarea (auto-saves to profile)
 *  - Neighborhood filter checklist
 *  - Search button
 *  - Recent searches history
 */

import { useEffect, useState, useCallback } from "react";
import { NEIGHBORHOOD_ZIP_CODES } from "@/lib/neighborhoods";
import { formatDate } from "@/lib/utils";
import { getBrowserClient } from "@/lib/supabase-browser";
import type { StatsResponse, SavedSearch } from "@/lib/types";

const ALL_NEIGHBORHOODS = Object.keys(NEIGHBORHOOD_ZIP_CODES);

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function searchLabel(search: SavedSearch): string {
  if (search.neighborhoods.length === 0) return "All NYC";
  const shown = search.neighborhoods.slice(0, 2).join(", ");
  return search.neighborhoods.length > 2
    ? `${shown} +${search.neighborhoods.length - 2}`
    : shown;
}

interface SidebarProps {
  // Controlled state — parent owns these
  serviceDescription: string;
  onServiceDescriptionChange: (value: string) => void;
  selectedNeighborhoods: Set<string>;
  onNeighborhoodsChange: (next: Set<string>) => void;
  // Actions
  onSearch: (params: { serviceDescription: string; zipCodes: string[] }) => void;
  onReset: () => void;
  isLoading: boolean;
  // Auth
  userEmail: string | null;
  // Past searches
  savedSearches: SavedSearch[];
  onRestoreSearch: (search: SavedSearch) => void;
}

export function Sidebar({
  serviceDescription,
  onServiceDescriptionChange,
  selectedNeighborhoods,
  onNeighborhoodsChange,
  onSearch,
  onReset,
  isLoading,
  userEmail,
  savedSearches,
  onRestoreSearch,
}: SidebarProps) {
  const [stats, setStats] = useState<StatsResponse>({ leadCount: 0, lastSync: null });
  const [neighborhoodSearch, setNeighborhoodSearch] = useState("");
  const [showHistory, setShowHistory] = useState(true);

  // Fetch stats on mount
  useEffect(() => {
    fetch("/api/stats")
      .then((r) => r.json())
      .then((data: StatsResponse) => setStats(data))
      .catch(console.error);
  }, []);

  const toggleNeighborhood = useCallback(
    (name: string) => {
      const next = new Set(selectedNeighborhoods);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      onNeighborhoodsChange(next);
    },
    [selectedNeighborhoods, onNeighborhoodsChange]
  );

  const selectAll = () => onNeighborhoodsChange(new Set(ALL_NEIGHBORHOODS));
  const clearAll = () => onNeighborhoodsChange(new Set());

  const handleSearch = () => {
    const zipCodes = Array.from(selectedNeighborhoods).flatMap(
      (n) => NEIGHBORHOOD_ZIP_CODES[n] ?? []
    );
    onSearch({ serviceDescription, zipCodes: [...new Set(zipCodes)] });
  };

  const handleLogout = async () => {
    const supabase = getBrowserClient();
    await supabase.auth.signOut();
    window.location.href = "/login";
  };

  const filteredNeighborhoods = ALL_NEIGHBORHOODS.filter((n) =>
    n.toLowerCase().includes(neighborhoodSearch.toLowerCase())
  );

  const userInitial = userEmail ? userEmail[0].toUpperCase() : "?";

  return (
    <aside
      className="fixed left-0 top-0 h-screen flex flex-col overflow-hidden z-10"
      style={{
        width: "21rem",
        backgroundColor: "var(--surface)",
        borderRight: "1px solid var(--border)",
      }}
    >
      {/* Brand + user */}
      <div className="px-6 pt-5 pb-4" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center justify-between mb-3">
          <button
            onClick={onReset}
            className="text-2xl tracking-[0.2em] uppercase font-normal text-left transition-colors"
            style={{
              fontFamily: "'Playfair Display', Georgia, serif",
              color: "var(--text)",
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--gold)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text)")}
          >
            Veranda
          </button>

          {/* User avatar + logout */}
          {userEmail && (
            <div className="flex items-center gap-2">
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-semibold flex-shrink-0"
                style={{ backgroundColor: "var(--gold-bg)", color: "var(--gold)", border: "1px solid var(--gold-dim)" }}
                title={userEmail}
              >
                {userInitial}
              </div>
              <button
                onClick={handleLogout}
                className="text-[10px] tracking-[0.1em] uppercase transition-colors"
                style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text-dim)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
                title="Sign out"
              >
                Sign out
              </button>
            </div>
          )}
        </div>

        <div className="text-[10px] tracking-[0.25em] uppercase" style={{ color: "var(--text-dim)" }}>
          NYC Intelligence Platform
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-4 mt-3">
          <div>
            <div className="text-xl font-light" style={{ color: "var(--gold)" }}>
              {stats.leadCount.toLocaleString()}
            </div>
            <div className="text-[9px] tracking-[0.15em] uppercase" style={{ color: "var(--text-muted)" }}>
              Leads
            </div>
          </div>
          <div className="h-8 w-px" style={{ backgroundColor: "var(--border)" }} />
          <div>
            <div className="text-xs" style={{ color: "var(--text)" }}>
              {stats.lastSync ? formatDate(stats.lastSync) : "Never"}
            </div>
            <div className="text-[9px] tracking-[0.15em] uppercase" style={{ color: "var(--text-muted)" }}>
              Last sync
            </div>
          </div>
        </div>
      </div>

      {/* Service description */}
      <div className="px-6 py-4" style={{ borderBottom: "1px solid var(--border)" }}>
        <label className="block text-[10px] tracking-[0.2em] uppercase mb-2" style={{ color: "var(--text-dim)" }}>
          Service Description
        </label>
        <textarea
          value={serviceDescription}
          onChange={(e) => onServiceDescriptionChange(e.target.value)}
          placeholder="We are a luxury interior design firm specializing in pre-war Manhattan apartments..."
          rows={4}
          className="w-full text-xs resize-none rounded px-3 py-2 outline-none transition-colors"
          style={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            color: "var(--text)",
            fontFamily: "'Inter', system-ui, sans-serif",
            lineHeight: "1.6",
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = "var(--gold-dim)")}
          onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
        />
      </div>

      {/* Neighborhood filter — flex-1 so it fills remaining space */}
      <div className="flex-1 flex flex-col overflow-hidden px-6 py-4">
        <div className="flex items-center justify-between mb-2">
          <label className="text-[10px] tracking-[0.2em] uppercase" style={{ color: "var(--text-dim)" }}>
            Neighborhoods{" "}
            {selectedNeighborhoods.size > 0 && (
              <span style={{ color: "var(--gold)" }}>({selectedNeighborhoods.size})</span>
            )}
          </label>
          <div className="flex gap-2">
            {[["All", selectAll], ["Clear", clearAll]].map(([label, fn]) => (
              <button
                key={label as string}
                onClick={fn as () => void}
                className="text-[9px] tracking-[0.1em] uppercase transition-colors"
                style={{ color: "var(--gold-dim)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--gold)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--gold-dim)")}
              >
                {label as string}
              </button>
            ))}
          </div>
        </div>

        <input
          type="text"
          value={neighborhoodSearch}
          onChange={(e) => setNeighborhoodSearch(e.target.value)}
          placeholder="Filter neighborhoods..."
          className="w-full text-xs rounded px-3 py-1.5 mb-2 outline-none"
          style={{ backgroundColor: "var(--card)", border: "1px solid var(--border)", color: "var(--text)" }}
        />

        <div className="flex-1 overflow-y-auto space-y-0.5">
          {filteredNeighborhoods.map((name) => {
            const checked = selectedNeighborhoods.has(name);
            return (
              <label
                key={name}
                className="flex items-center gap-2.5 px-2 py-1.5 rounded cursor-pointer"
                style={{ backgroundColor: checked ? "var(--gold-bg)" : "transparent" }}
                onMouseEnter={(e) => { if (!checked) e.currentTarget.style.backgroundColor = "var(--hover)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = checked ? "var(--gold-bg)" : "transparent"; }}
              >
                <input type="checkbox" checked={checked} onChange={() => toggleNeighborhood(name)} className="hidden" />
                <div
                  className="w-3.5 h-3.5 rounded-sm flex items-center justify-center flex-shrink-0"
                  style={{
                    border: checked ? "1px solid var(--gold)" : "1px solid var(--border-strong)",
                    backgroundColor: checked ? "var(--gold)" : "transparent",
                  }}
                >
                  {checked && (
                    <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
                      <path d="M1 3L3 5L7 1" stroke="#0C0C0F" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
                <span className="text-xs" style={{ color: "var(--text)" }}>{name}</span>
              </label>
            );
          })}
        </div>
      </div>

      {/* Search button */}
      <div className="px-6 py-4" style={{ borderTop: "1px solid var(--border)" }}>
        <button
          onClick={handleSearch}
          disabled={isLoading}
          className="w-full py-2.5 text-xs tracking-[0.2em] uppercase font-medium rounded transition-all"
          style={{
            backgroundColor: isLoading ? "var(--gold-dim)" : "var(--gold)",
            color: "#0C0C0F",
            opacity: isLoading ? 0.7 : 1,
            cursor: isLoading ? "not-allowed" : "pointer",
          }}
        >
          {isLoading ? "Searching…" : "Search Leads"}
        </button>
      </div>

      {/* Recent searches */}
      {savedSearches.length > 0 && (
        <div
          className="px-6 py-3"
          style={{ borderTop: "1px solid var(--border)", maxHeight: "220px", overflowY: "auto" }}
        >
          <button
            className="flex items-center justify-between w-full mb-2"
            onClick={() => setShowHistory((v) => !v)}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
          >
            <span className="text-[10px] tracking-[0.2em] uppercase" style={{ color: "var(--text-dim)" }}>
              Recent Searches
            </span>
            <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              {showHistory ? "▲" : "▼"}
            </span>
          </button>

          {showHistory && (
            <div className="space-y-1">
              {savedSearches.map((s) => (
                <button
                  key={s.id}
                  onClick={() => onRestoreSearch(s)}
                  className="w-full text-left px-2 py-1.5 rounded transition-colors"
                  style={{ background: "none", border: "none", cursor: "pointer" }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--hover)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs truncate" style={{ color: "var(--text)" }}>
                      {searchLabel(s)}
                    </span>
                    <span className="text-[10px] flex-shrink-0" style={{ color: "var(--text-muted)" }}>
                      {timeAgo(s.created_at)}
                    </span>
                  </div>
                  {s.result_count > 0 && (
                    <div className="text-[10px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                      {s.result_count.toLocaleString()} leads
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
