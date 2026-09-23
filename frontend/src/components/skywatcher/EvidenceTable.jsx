import React from "react";

/**
 * Shared scrollable evidence table used by the Routes page's temporal-
 * recurrence / provenance panels. Renders optional content above the table
 * (a filter row, a summary line, etc.), the table itself, and an optional
 * footnote below it — matching the markup those panels previously
 * duplicated three times.
 *
 * @param {Array<{key: string, header: React.ReactNode, render: (row, index) => React.ReactNode, cellClassName?: string}>} columns
 * @param {Array<object>} rows
 * @param {(row: object, index: number) => string} rowKey
 * @param {React.ReactNode} [footnote]
 * @param {string} [scrollClassName] - overflow/height classes for the table's scroll container.
 * @param {React.ReactNode} [children] - optional content rendered above the table (e.g. filter inputs).
 */
export default function EvidenceTable({
  columns,
  rows,
  rowKey,
  footnote,
  scrollClassName = "overflow-x-auto",
  children,
}) {
  return (
    <>
      {children}
      <div className={`mt-3 rounded border border-border ${scrollClassName}`}>
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-secondary/40 text-left">
              {columns.map((col) => (
                <th key={col.key} className="p-2">{col.header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(rows || []).map((row, index) => (
              <tr key={rowKey(row, index)} className="border-t border-border/50">
                {columns.map((col) => (
                  <td key={col.key} className={col.cellClassName || "p-2 font-mono"}>
                    {col.render(row, index)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {footnote && <p className="mt-2 text-[10px] text-muted-foreground">{footnote}</p>}
    </>
  );
}
