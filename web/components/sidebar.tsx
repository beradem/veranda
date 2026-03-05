"use client";

/**
 * Sidebar — Fixed left panel with brand, stats, service description, and filters.
 */

import { useEffect, useState, useCallback } from "react";
import { NEIGHBORHOOD_ZIP_CODES } from "@/lib/neighborhoods";
import { formatDate } from "@/lib/utils";
import type { StatsResponse } from "@/lib/types";

const ALL_NEIGHBORHOODS = Object.keys(NEIGHBORHOOD_ZIP_CODES);

interface SidebarProps {
  onSearch: (params: { serviceDescription: string; zipCodes: string[] }) => void;
  onReset: () => void;
  isLoading: boolean;
}

export function Sidebar({ onSearch, onReset, isLoading }: SidebarProps) {
  const [stats, setStats] = useState<StatsResponse>({ leadCount: 0, lastSync: null });
  const [serviceDescription, setServiceDescription] = useState("");
  const [selectedNeighborhoods, setSelectedNeighborhoods] = useState<Set<string>>(
    new Set()
  );
  const [neighborhoodSearch, setNeighborhoodSearch] = useState("");

  // Fetch stats on mount
  useEffect(() => {
    fetch("/api/stats")
      .then((r) => r.json())
      .then((data: StatsResponse) => setStats(data))
      .catch(console.error);
  }, []);

  const toggleNeighborhood = useCallback((name: string) => {
    setSelectedNeighborhoods((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const selectAll = () => setSelectedNeighborhoods(new Set(ALL_NEIGHBORHOODS));
  const clearAll = () => setSelectedNeighborhoods(new Set());

  const handleSearch = () => {
    const zipCodes = Array.from(selectedNeighborhoods).flatMap(
      (n) => NEIGHBORHOOD_ZIP_CODES[n] ?? []
    );
    const uniqueZips = [...new Set(zipCodes)];
    onSearch({ serviceDescription, zipCodes: uniqueZips });
  };

  const filteredNeighborhoods = ALL_NEIGHBORHOODS.filter((n) =>
    n.toLowerCase().includes(neighborhoodSearch.toLowerCase())
  );

  return (
    <aside
      className="fixed left-0 top-0 h-screen w-84 flex flex-col overflow-hidden z-10"
      style={{
        width: "21rem",
        backgroundColor: "var(--surface)",
        borderRight: "1px solid var(--border)",
      }}
    >
      {/* Brand */}
      <div className="px-6 pt-6 pb-4" style={{ borderBottom: "1px solid var(--border)" }}>
        <button
          onClick={onReset}
          className="text-2xl tracking-[0.2em] uppercase font-normal text-left transition-colors"
          style={{ fontFamily: "'Playfair Display', Georgia, serif", color: "var(--text)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--gold)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text)")}
        >
          Veranda
        </button>
        <div
          className="text-[10px] tracking-[0.25em] uppercase mt-1"
          style={{ color: "var(--text-dim)" }}
        >
          NYC Intelligence Platform
        </div>

        {/* Stats row */}
        <div className="flex items-center gap-4 mt-4">
          <div>
            <div
              className="text-xl font-light"
              style={{ color: "var(--gold)" }}
            >
              {stats.leadCount.toLocaleString()}
            </div>
            <div className="text-[9px] tracking-[0.15em] uppercase" style={{ color: "var(--text-muted)" }}>
              Leads
            </div>
          </div>
          <div
            className="h-8 w-px"
            style={{ backgroundColor: "var(--border)" }}
          />
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
        <label
          className="block text-[10px] tracking-[0.2em] uppercase mb-2"
          style={{ color: "var(--text-dim)" }}
        >
          Service Description
        </label>
        <textarea
          value={serviceDescription}
          onChange={(e) => setServiceDescription(e.target.value)}
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
          onFocus={(e) => {
            e.currentTarget.style.borderColor = "var(--gold-dim)";
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = "var(--border)";
          }}
        />
      </div>

      {/* Neighborhood filter */}
      <div className="flex-1 flex flex-col overflow-hidden px-6 py-4">
        <div className="flex items-center justify-between mb-2">
          <label
            className="text-[10px] tracking-[0.2em] uppercase"
            style={{ color: "var(--text-dim)" }}
          >
            Neighborhoods{" "}
            {selectedNeighborhoods.size > 0 && (
              <span style={{ color: "var(--gold)" }}>({selectedNeighborhoods.size})</span>
            )}
          </label>
          <div className="flex gap-2">
            <button
              onClick={selectAll}
              className="text-[9px] tracking-[0.1em] uppercase transition-colors"
              style={{ color: "var(--gold-dim)" }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "var(--gold)")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "var(--gold-dim)")}
            >
              All
            </button>
            <span style={{ color: "var(--border)" }}>·</span>
            <button
              onClick={clearAll}
              className="text-[9px] tracking-[0.1em] uppercase transition-colors"
              style={{ color: "var(--gold-dim)" }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "var(--gold)")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "var(--gold-dim)")}
            >
              Clear
            </button>
          </div>
        </div>

        {/* Neighborhood search */}
        <input
          type="text"
          value={neighborhoodSearch}
          onChange={(e) => setNeighborhoodSearch(e.target.value)}
          placeholder="Filter neighborhoods..."
          className="w-full text-xs rounded px-3 py-1.5 mb-2 outline-none"
          style={{
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            color: "var(--text)",
          }}
        />

        {/* Scrollable list */}
        <div className="flex-1 overflow-y-auto space-y-0.5">
          {filteredNeighborhoods.map((name) => (
            <label
              key={name}
              className="flex items-center gap-2.5 px-2 py-1.5 rounded cursor-pointer transition-colors"
              style={{
                backgroundColor: selectedNeighborhoods.has(name)
                  ? "var(--gold-bg)"
                  : "transparent",
              }}
              onMouseEnter={(e) => {
                if (!selectedNeighborhoods.has(name))
                  e.currentTarget.style.backgroundColor = "var(--hover)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = selectedNeighborhoods.has(name)
                  ? "var(--gold-bg)"
                  : "transparent";
              }}
            >
              <input
                type="checkbox"
                checked={selectedNeighborhoods.has(name)}
                onChange={() => toggleNeighborhood(name)}
                className="hidden"
              />
              <div
                className="w-3.5 h-3.5 rounded-sm flex items-center justify-center flex-shrink-0"
                style={{
                  border: selectedNeighborhoods.has(name)
                    ? "1px solid var(--gold)"
                    : "1px solid var(--border-strong)",
                  backgroundColor: selectedNeighborhoods.has(name)
                    ? "var(--gold)"
                    : "transparent",
                }}
              >
                {selectedNeighborhoods.has(name) && (
                  <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
                    <path
                      d="M1 3L3 5L7 1"
                      stroke="#0C0C0F"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </div>
              <span className="text-xs" style={{ color: "var(--text)" }}>
                {name}
              </span>
            </label>
          ))}
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
    </aside>
  );
}
