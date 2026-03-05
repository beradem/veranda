"use client";

/**
 * Main dashboard page — orchestrates Sidebar, LeadTable, and DetailPanel.
 *
 * Layout:
 *   [Sidebar 21rem] [Lead Table flex-1] [Detail Panel 22rem — when lead selected]
 */

import { useState, useCallback } from "react";
import { Sidebar } from "@/components/sidebar";
import { LeadTable } from "@/components/lead-table";
import { DetailPanel } from "@/components/detail-panel";
import { Hero } from "@/components/hero";
import type { Lead, LeadsResponse } from "@/lib/types";

const PAGE_SIZE = 100;

export default function DashboardPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [serviceDescription, setServiceDescription] = useState("");

  // Current search params (so pagination can re-use them)
  const [currentSearch, setCurrentSearch] = useState<{
    serviceDescription: string;
    zipCodes: string[];
  } | null>(null);

  const fetchLeads = useCallback(
    async (params: { serviceDescription: string; zipCodes: string[] }, targetPage = 1) => {
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
      } catch (err) {
        console.error("Failed to fetch leads:", err);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  const handleSearch = useCallback(
    (params: { serviceDescription: string; zipCodes: string[] }) => {
      setServiceDescription(params.serviceDescription);
      setCurrentSearch(params);
      fetchLeads(params, 1);
    },
    [fetchLeads]
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

  // When outreach is generated, update the lead in the local list
  const handleOutreachGenerated = useCallback((updatedLead: Lead) => {
    setLeads((prev) =>
      prev.map((l) => (l.id === updatedLead.id ? updatedLead : l))
    );
    setSelectedLead(updatedLead);
  }, []);

  const showDetailPanel = !!selectedLead;

  return (
    <div className="flex h-screen overflow-hidden" style={{ backgroundColor: "#0C0C0F" }}>
      {/* Sidebar */}
      <Sidebar onSearch={handleSearch} onReset={handleReset} isLoading={isLoading} />

      {/* Main content area — offset by sidebar width */}
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

      {/* Detail panel */}
      <DetailPanel
        lead={selectedLead}
        serviceDescription={serviceDescription}
        onClose={() => setSelectedLead(null)}
        onOutreachGenerated={handleOutreachGenerated}
      />
    </div>
  );
}
