"use client";

/**
 * Main dashboard page — orchestrates Sidebar, LeadTable, and DetailPanel.
 *
 * On mount:
 *  - Gets the logged-in user from Supabase
 *  - Loads their saved service description (profile)
 *  - Loads their recent search history
 *
 * During use:
 *  - Auto-saves the service description to their profile (1s debounce)
 *  - Saves each search run to their history
 *  - Restoring a past search sets state + immediately runs fetchLeads
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { Sidebar } from "@/components/sidebar";
import { LeadTable } from "@/components/lead-table";
import { DetailPanel } from "@/components/detail-panel";
import { Hero } from "@/components/hero";
import { getBrowserClient } from "@/lib/supabase-browser";
import { ThemeToggle } from "@/components/theme-toggle";
import type { Lead, LeadsResponse, SavedSearch } from "@/lib/types";

const PAGE_SIZE = 100;

export default function DashboardPage() {
  // ── Auth ──────────────────────────────────────────────────────
  const [userEmail, setUserEmail] = useState<string | null>(null);

  // ── Controlled sidebar state (lifted so restoring searches works) ──
  const [serviceDescription, setServiceDescription] = useState("");
  const [selectedNeighborhoods, setSelectedNeighborhoods] = useState<Set<string>>(new Set());

  // ── Lead results ──────────────────────────────────────────────
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [currentSearch, setCurrentSearch] = useState<{
    serviceDescription: string;
    zipCodes: string[];
    neighborhoods: string[];
  } | null>(null);

  // ── Search history ────────────────────────────────────────────
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);

  // ── On mount: load user, profile, history ────────────────────
  useEffect(() => {
    const init = async () => {
      const supabase = getBrowserClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      setUserEmail(user.email ?? null);

      // Load profile and history in parallel
      const [profileRes, searchesRes] = await Promise.all([
        fetch("/api/profile"),
        fetch("/api/searches"),
      ]);

      if (profileRes.ok) {
        const { serviceDescription: saved } = await profileRes.json();
        if (saved) setServiceDescription(saved);
      }

      if (searchesRes.ok) {
        const { searches } = await searchesRes.json();
        setSavedSearches(searches ?? []);
      }
    };
    init();
  }, []);

  // ── Auto-save service description (1s debounce) ───────────────
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleServiceDescriptionChange = useCallback((value: string) => {
    setServiceDescription(value);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serviceDescription: value }),
      }).catch(console.error);
    }, 1000);
  }, []);

  // ── Core fetch ────────────────────────────────────────────────
  const fetchLeads = useCallback(
    async (
      params: { serviceDescription: string; zipCodes: string[]; neighborhoods: string[] },
      targetPage = 1,
      saveToHistory = true
    ) => {
      setIsLoading(true);
      try {
        const qs = new URLSearchParams({
          page: String(targetPage),
          pageSize: String(PAGE_SIZE),
        });
        if (params.zipCodes.length > 0) {
          qs.set("neighborhoods", params.zipCodes.join(","));
        }

        const res = await fetch(`/api/leads?${qs}`);
        const data: LeadsResponse = await res.json();
        setLeads(data.leads);
        setTotal(data.total);
        setPage(targetPage);
        setHasSearched(true);
        setSelectedLead(null);

        // Save to search history (only on page 1 = new search, not when restoring)
        if (targetPage === 1 && saveToHistory) {
          fetch("/api/searches", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              serviceDescription: params.serviceDescription,
              neighborhoods: params.neighborhoods,
              resultCount: data.total,
            }),
          })
            .then((r) => r.json())
            .then(() => fetch("/api/searches"))
            .then((r) => r.json())
            .then(({ searches }) => setSavedSearches(searches ?? []))
            .catch(console.error);
        }
      } catch (err) {
        console.error("Failed to fetch leads:", err);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  // ── Handlers ──────────────────────────────────────────────────
  const handleSearch = useCallback(
    (params: { serviceDescription: string; zipCodes: string[] }) => {
      const neighborhoods = Array.from(selectedNeighborhoods);
      const full = { ...params, neighborhoods };
      setCurrentSearch(full);
      fetchLeads(full, 1);
    },
    [fetchLeads, selectedNeighborhoods]
  );

  const handlePageChange = useCallback(
    (newPage: number) => {
      if (currentSearch) fetchLeads(currentSearch, newPage);
    },
    [currentSearch, fetchLeads]
  );

  const handleReset = useCallback(() => {
    setHasSearched(false);
    setSelectedLead(null);
    setLeads([]);
    setTotal(0);
    setCurrentSearch(null);
  }, []);

  const handleOutreachGenerated = useCallback((updatedLead: Lead) => {
    setLeads((prev) => prev.map((l) => (l.id === updatedLead.id ? updatedLead : l)));
    setSelectedLead(updatedLead);
  }, []);

  const handleClearSearches = useCallback(() => {
    fetch("/api/searches", { method: "DELETE" }).catch(console.error);
    setSavedSearches([]);
  }, []);

  // Restore a past search: set sidebar state + immediately run the search
  const handleRestoreSearch = useCallback(
    (search: SavedSearch) => {
      setServiceDescription(search.service_description);

      const neighborhoods = new Set(search.neighborhoods);
      setSelectedNeighborhoods(neighborhoods);

      // Compute zip codes from restored neighborhood names
      const { NEIGHBORHOOD_ZIP_CODES } = require("@/lib/neighborhoods");
      const zipCodes = search.neighborhoods.flatMap(
        (n: string) => NEIGHBORHOOD_ZIP_CODES[n] ?? []
      );
      const uniqueZips = [...new Set(zipCodes)] as string[];

      const params = {
        serviceDescription: search.service_description,
        zipCodes: uniqueZips,
        neighborhoods: search.neighborhoods,
      };
      setCurrentSearch(params);
      fetchLeads(params, 1, false);
    },
    [fetchLeads]
  );

  const showDetailPanel = !!selectedLead;

  return (
    <div className="flex h-screen overflow-hidden" style={{ backgroundColor: "var(--bg)" }}>
      <Sidebar
        serviceDescription={serviceDescription}
        onServiceDescriptionChange={handleServiceDescriptionChange}
        selectedNeighborhoods={selectedNeighborhoods}
        onNeighborhoodsChange={setSelectedNeighborhoods}
        onSearch={handleSearch}
        onReset={handleReset}
        isLoading={isLoading}
        userEmail={userEmail}
        savedSearches={savedSearches}
        onRestoreSearch={handleRestoreSearch}
        onClearSearches={handleClearSearches}
      />

      <main
        className="flex flex-col overflow-hidden"
        style={{
          marginLeft: "21rem",
          marginRight: showDetailPanel ? "22rem" : "0",
          flex: 1,
          transition: "margin-right 0.2s ease",
        }}
      >
        {!hasSearched ? (
          <Hero />
        ) : (
          <LeadTable
            leads={leads}
            total={total}
            selectedLead={selectedLead}
            onSelectLead={setSelectedLead}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={handlePageChange}
          />
        )}
      </main>

      <ThemeToggle elevated={hasSearched} />

      <DetailPanel
        lead={selectedLead}
        serviceDescription={serviceDescription}
        onClose={() => setSelectedLead(null)}
        onOutreachGenerated={handleOutreachGenerated}
      />
    </div>
  );
}
