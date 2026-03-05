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
  getPaginationRowModel,
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
            <div className="text-sm font-medium" style={{ color: "#EDE8E0" }}>
              {row.original.first_name} {row.original.last_name}
            </div>
            <div className="text-xs mt-0.5 truncate max-w-xs" style={{ color: "#7A7570" }}>
              {leadSubtitle(row.original)}
            </div>
          </div>
        ),
        enableGlobalFilter: true,
      },
      {
        id: "neighborhood",
        header: "Neighborhood",
        accessorFn: (row) => zipToNeighborhood(row.zip_code),
        cell: ({ getValue }) => (
          <span className="text-xs" style={{ color: "#EDE8E0" }}>
            {getValue() as string}
          </span>
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
    getPaginationRowModel: getPaginationRowModel(),
    globalFilterFn: "includesString",
  });

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="flex flex-col h-full">
      {/* Search bar */}
      <div className="flex items-center gap-3 px-4 py-3" style={{ borderBottom: "1px solid #252530" }}>
        <div className="relative flex-1">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5"
            style={{ color: "#7A7570" }}
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
              backgroundColor: "#16161C",
              border: "1px solid #252530",
              color: "#EDE8E0",
            }}
          />
        </div>
        <span className="text-xs whitespace-nowrap" style={{ color: "#7A7570" }}>
          {total.toLocaleString()} leads
        </span>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0" style={{ backgroundColor: "#111115" }}>
            <tr>
              {table.getHeaderGroups().map((hg) =>
                hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className="text-left px-4 py-2.5 text-[10px] tracking-[0.15em] uppercase font-semibold cursor-pointer select-none"
                    style={{
                      color: "#7A7570",
                      borderBottom: "1px solid #252530",
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
                    backgroundColor: isSelected
                      ? "rgba(200,169,110,0.07)"
                      : "transparent",
                    borderLeft: isSelected
                      ? "2px solid #C8A96E"
                      : "2px solid transparent",
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.backgroundColor = "#1D1D26";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = isSelected
                      ? "rgba(200,169,110,0.07)"
                      : "transparent";
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className="px-4 py-3"
                      style={{ borderBottom: "1px solid #1A1A22" }}
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
            <span className="text-sm" style={{ color: "#4A4845" }}>
              No leads found
            </span>
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderTop: "1px solid #252530" }}
        >
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="text-xs px-3 py-1.5 rounded transition-colors"
            style={{
              backgroundColor: "#16161C",
              border: "1px solid #252530",
              color: page <= 1 ? "#4A4845" : "#EDE8E0",
              cursor: page <= 1 ? "not-allowed" : "pointer",
            }}
          >
            ← Prev
          </button>
          <span className="text-xs" style={{ color: "#7A7570" }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="text-xs px-3 py-1.5 rounded transition-colors"
            style={{
              backgroundColor: "#16161C",
              border: "1px solid #252530",
              color: page >= totalPages ? "#4A4845" : "#EDE8E0",
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
