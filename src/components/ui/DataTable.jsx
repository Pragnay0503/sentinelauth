import React, { useState, useMemo } from 'react';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

/**
 * SentinelAuth Design System: DataTable
 * - Sortable columns on desktop & tablet
 * - Responsive transformation: Degrades to stacked card list on mobile (<640px)
 *   with label: value pairs instead of a horizontally-scrolling table.
 */
export function DataTable({
  columns = [],
  data = [],
  keyField = 'id',
  isLoading = false,
  emptyMessage = 'No records found.',
  onRowClick = null,
  className = '',
}) {
  const [sortKey, setSortKey] = useState(null);
  const [sortDirection, setSortDirection] = useState('asc'); // 'asc' | 'desc'

  const handleSort = (key, sortable) => {
    if (!sortable) return;
    if (sortKey === key) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDirection('asc');
    }
  };

  const sortedData = useMemo(() => {
    if (!sortKey) return data;
    const sorted = [...data].sort((a, b) => {
      const valA = a[sortKey];
      const valB = b[sortKey];
      if (valA === valB) return 0;
      if (valA === null || valA === undefined) return 1;
      if (valB === null || valB === undefined) return -1;
      if (typeof valA === 'number' && typeof valB === 'number') {
        return sortDirection === 'asc' ? valA - valB : valB - valA;
      }
      return sortDirection === 'asc'
        ? String(valA).localeCompare(String(valB))
        : String(valB).localeCompare(String(valA));
    });
    return sorted;
  }, [data, sortKey, sortDirection]);

  return (
    <div className={`w-full ${className}`}>
      {/* 1. Desktop & Tablet Table (>640px) */}
      <div className="hidden sm:block border border-[#232B38] bg-[#141A22] rounded-none overflow-hidden">
        <table className="w-full text-left text-xs border-collapse">
          <thead className="bg-[#10151C] border-b border-[#232B38] text-[#8A93A3] font-mono text-[11px] uppercase tracking-wider">
            <tr>
              {columns.map((col) => {
                const isSorted = sortKey === col.key;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={
                      isSorted
                        ? sortDirection === 'asc'
                          ? 'ascending'
                          : 'descending'
                        : undefined
                    }
                    onClick={() => handleSort(col.key, col.sortable)}
                    className={`px-4 py-3 font-semibold ${
                      col.align === 'right' ? 'text-right' : 'text-left'
                    } ${
                      col.sortable
                        ? 'cursor-pointer select-none hover:text-[#E4E7EB] transition-colors'
                        : ''
                    } ${col.headerClassName || ''}`}
                  >
                    <div
                      className={`inline-flex items-center gap-1.5 ${
                        col.align === 'right' ? 'justify-end' : 'justify-start'
                      }`}
                    >
                      <span>{col.label}</span>
                      {col.sortable && (
                        <span className="text-[#8A93A3] shrink-0">
                          {isSorted ? (
                            sortDirection === 'asc' ? (
                              <ArrowUp className="w-3.5 h-3.5 text-[#D9A441]" />
                            ) : (
                              <ArrowDown className="w-3.5 h-3.5 text-[#D9A441]" />
                            )
                          ) : (
                            <ArrowUpDown className="w-3 h-3 opacity-40 hover:opacity-100" />
                          )}
                        </span>
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#232B38] font-sans">
            {isLoading ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-12 text-center text-[#8A93A3] font-mono"
                >
                  Loading database records...
                </td>
              </tr>
            ) : sortedData.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-12 text-center text-[#8A93A3] font-mono"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              sortedData.map((row, rowIdx) => (
                <tr
                  key={row[keyField] || rowIdx}
                  onClick={() => onRowClick && onRowClick(row)}
                  className={`transition-colors ${
                    onRowClick
                      ? 'hover:bg-[#1B222D] cursor-pointer'
                      : 'hover:bg-[#1B222D]/50'
                  }`}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-3 text-xs ${
                        col.align === 'right' ? 'text-right' : 'text-left'
                      } ${col.className || ''}`}
                    >
                      {col.render ? col.render(row[col.key], row) : row[col.key]}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 2. Mobile Stacked Card View (<640px) */}
      <div className="sm:hidden space-y-3">
        {isLoading ? (
          <div className="border border-[#232B38] bg-[#141A22] p-6 text-center text-xs font-mono text-[#8A93A3]">
            Loading database records...
          </div>
        ) : sortedData.length === 0 ? (
          <div className="border border-[#232B38] bg-[#141A22] p-6 text-center text-xs font-mono text-[#8A93A3]">
            {emptyMessage}
          </div>
        ) : (
          sortedData.map((row, rowIdx) => (
            <div
              key={row[keyField] || rowIdx}
              onClick={() => onRowClick && onRowClick(row)}
              className={`border border-[#232B38] bg-[#141A22] p-4 space-y-2.5 transition-colors ${
                onRowClick ? 'active:bg-[#1B222D] cursor-pointer' : ''
              }`}
            >
              {columns.map((col) => (
                <div
                  key={col.key}
                  className="flex items-start justify-between gap-3 text-xs border-b border-[#232B38]/50 pb-2 last:border-b-0 last:pb-0"
                >
                  <span className="font-mono text-[11px] uppercase tracking-wider text-[#8A93A3] shrink-0">
                    {col.label}:
                  </span>
                  <span className="font-medium text-[#E4E7EB] text-right break-words">
                    {col.render ? col.render(row[col.key], row) : row[col.key]}
                  </span>
                </div>
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default DataTable;
