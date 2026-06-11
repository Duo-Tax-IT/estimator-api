import { useState } from "react";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { fmtMoney } from "@/lib/money";
import { buildRows, subtreeTotals, isHidden } from "@/lib/renovations";
import { useEstimator } from "./store";

// Grouped renovations table. `interactive` wires the live ×-scale controls (top
// parents) to the store; read-only otherwise (run-details modal). Pass `renos`
// to render an arbitrary list, else it reads the current estimate.
export default function RenovationsTable({ interactive = false, renos: renosProp }) {
  const storeRenos = useEstimator((s) => s.result?.Renovations);
  const scales = useEstimator((s) => s.scales);
  const setScale = useEstimator((s) => s.setScale);
  const [collapsed, setCollapsed] = useState(() => new Set());

  const renos = renosProp ?? storeRenos ?? [];
  if (!renos.length) {
    return <div className="card text-center text-muted-foreground py-6">No depreciable renovations were detected from the property's photos.</div>;
  }

  const rows = buildRows(renos);
  const sub = subtreeTotals(renos);
  const toggle = (key) => setCollapsed((prev) => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Renovation</TableHead><TableHead>Year</TableHead><TableHead>Owner</TableHead>
          <TableHead className="text-right">Qty</TableHead><TableHead>Unit</TableHead>
          <TableHead className="text-right">Rate</TableHead><TableHead className="text-right">Cost</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, j) => {
          if (isHidden(row.anc, collapsed)) return null;
          const pad = { paddingLeft: 14 + row.depth * 20 };

          if (row.kind === "group") {
            const sc = scales[row.topParent];
            const mul = row.topParent && sc?.on ? sc.mul ?? 1 : 1;
            return (
              <TableRow key={j} className="cursor-pointer bg-secondary/60 font-semibold" onClick={() => toggle(row.key)}>
                <TableCell colSpan={6} style={pad}>
                  <span className="inline-block w-5 text-muted-foreground">{collapsed.has(row.key) ? "▸" : "▾"}</span>
                  {row.name}
                  {interactive && row.topParent && <ScaleControl parent={row.topParent} sc={sc} setScale={setScale} />}
                </TableCell>
                <TableCell className="text-right tabular-nums">{fmtMoney(sub[row.key] * mul)}</TableCell>
              </TableRow>
            );
          }

          const r = row.item;
          return (
            <TableRow key={j} className={r.needsReview ? "text-muted-foreground" : undefined}>
              <TableCell style={pad}>
                {r.Name ?? ""}
                {r.needsReview && <span className="ml-2 text-xs">needs review · not in catalog</span>}
              </TableCell>
              <TableCell>{r.Year ?? ""}</TableCell>
              <TableCell>{r.Owner ?? ""}</TableCell>
              <TableCell className="text-right tabular-nums">{r.Quantity ?? ""}</TableCell>
              <TableCell>{r.Unit ?? ""}</TableCell>
              <TableCell className="text-right tabular-nums">{r.DefaultRate ?? ""}</TableCell>
              <TableCell className="text-right tabular-nums">{r.FinalCost ?? ""}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

// Per-parent select + multiplier (TEMP scale test harness): collapse the
// subtree to its summed cost × this multiplier.
function ScaleControl({ parent, sc, setScale }) {
  const stop = (e) => e.stopPropagation();
  return (
    <label className="inline-flex items-center gap-1.5 ml-2.5 font-normal text-[13px] text-muted-foreground" onClick={stop}>
      <Checkbox checked={!!sc?.on} onCheckedChange={(v) => setScale(parent, { on: !!v })} />
      ×
      <input type="number" min="0" step="1" value={sc?.mul ?? 1}
        onChange={(e) => setScale(parent, { mul: Number(e.target.value) || 0 })}
        className="w-12 px-1.5 py-0.5 bg-secondary border border-border rounded-md text-foreground text-[13px] outline-none focus:border-primary" />
    </label>
  );
}
