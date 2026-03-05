"use client";

/**
 * LeadTable — Filterable, paginated lead table with single-row selection.
 * Uses TanStack Table for sorting and filtering.
 */

import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import type { Lead } from "@/lib/types";
import { leadSubtitle } from "@/lib/utils";
import { zipToNeighborhood } from "@/lib/neighborhoods";

interface LeadTableProps {
  leads: Lead[];
  total: number;
  selectedLead: Lead | null;
  onSelectLead: (lead: Lead) => void;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export function LeadTable({
  leads,
  total,
  selectedLead,
  onSelectLead,
  page,
  pageSize,
  onPageChange,
}: LeadTableProps) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns = useMemo<ColumnDef<Lead>[]>(
    () => [
      {
        id: "name",
        header: "Name",
        accessorFn: (row) => `${row.first_name} ${row.last_name}`,
        cell: ({ row }) => (
          <div>
            <div className="text-sm font-medium" style={{ color: "var(--text)" }}>
              {row.original.first_name} {row.original.last_name}
            </div>
            <div className="text-xs mt-0.5 truncate max-w-xs" style={{ color: "var(--text-muted)" }}>
              {leadSubtitle(row.original)}
            </div>
          </div>
        ),
        enableGlobalFilter: true,
      },
      {
        id: "details",
        header: "Details",
        accessorFn: (row) => `${row.address ?? ""} ${row.building_type ?? ""}`,
        cell: ({ row }) => (
          <div>
            <div className="text-xs" style={{ color: "var(--text)" }}>
              {zipToNeighborhood(row.original.zip_code)}
            </div>
            <div className="text-xs mt-0.5" style={{ color: "var(--text-dim)" }}>
              {row.original.address ?? ""}
            </div>
          </div>
        ),
        enableGlobalFilter: false,
      },
    ],
    []
  );

  const table = useReactTable({
    data: leads,
    columns,
    state: { globalFilter, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    globalFilterFn: "includesString",
  });

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="flex flex-col h-full">
      {/* Search bar */}
      <div className="flex items-center gap-3 px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="relative flex-1">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5"
            style={{ color: "var(--text-dim)" }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder="Filter by name, address, company…"
            className="w-full text-xs pl-9 pr-3 py-1.5 rounded outline-none"
            style={{
              backgroundColor: "var(--card)",
              border: "1px solid var(--border)",
              color: "var(--text)",
            }}
          />
        </div>
        <span className="text-xs whitespace-nowrap" style={{ color: "var(--text-dim)" }}>
          {total.toLocaleString()} leads
        </span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0" style={{ backgroundColor: "var(--surface)" }}>
            <tr>
              {table.getHeaderGroups().map((hg) =>
                hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className="text-left px-4 py-2.5 text-[10px] tracking-[0.15em] uppercase font-semibold cursor-pointer select-none"
                    style={{
                      color: "var(--text-dim)",
                      borderBottom: "1px solid var(--border)",
                      whiteSpace: "nowrap",
                    }}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() === "asc" && " ↑"}
                    {header.column.getIsSorted() === "desc" && " ↓"}
                  </th>
                ))
              )}
            </tr>
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const isSelected = selectedLead?.id === row.original.id;
              return (
                <tr
                  key={row.id}
                  onClick={() => onSelectLead(row.original)}
                  className="cursor-pointer transition-colors"
                  style={{
                    backgroundColor: isSelected ? "var(--gold-bg)" : "transparent",
                    borderLeft: isSelected
                      ? "2px solid var(--gold)"
                      : "2px solid transparent",
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.backgroundColor = "var(--hover)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = isSelected
                      ? "var(--gold-bg)"
                      : "transparent";
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className="px-4 py-3"
                      style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>

        {leads.length === 0 && (
          <div className="flex items-center justify-center h-48">
            <span className="text-sm" style={{ color: "var(--text-muted)" }}>
              No leads found
            </span>
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="text-xs px-3 py-1.5 rounded transition-colors"
            style={{
              backgroundColor: "var(--card)",
              border: "1px solid var(--border)",
              color: page <= 1 ? "var(--text-muted)" : "var(--text)",
              cursor: page <= 1 ? "not-allowed" : "pointer",
            }}
          >
            ← Prev
          </button>
          <span className="text-xs" style={{ color: "var(--text-dim)" }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="text-xs px-3 py-1.5 rounded transition-colors"
            style={{
              backgroundColor: "var(--card)",
              border: "1px solid var(--border)",
              color: page >= totalPages ? "var(--text-muted)" : "var(--text)",
              cursor: page >= totalPages ? "not-allowed" : "pointer",
            }}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
