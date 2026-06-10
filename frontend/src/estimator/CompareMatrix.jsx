import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";

// Items (rows) × runs (cols), with cost differences highlighted.
export default function CompareMatrix({ runs, diffOnly }) {
  const keys = [];
  const seen = {};
  const maps = runs.map((r) => {
    const m = {};
    ((r.response && r.response.Renovations) || []).forEach((it) => {
      const k = it._id || it.Name;
      m[k] = it;
      if (!seen[k]) { seen[k] = true; keys.push(k); }
    });
    return m;
  });

  const colLabel = (r) => r.label || (r.created_at || "").slice(5, 16);
  let diffs = 0;
  const rows = keys.map((k) => {
    const item = maps.find((m) => m[k])[k];
    const costs = maps.map((m) => (m[k] ? m[k].FinalCost ?? "" : null));
    const same = costs.every((c) => c === costs[0]);
    if (!same) diffs++;
    return { k, name: item.Name || k, costs, same };
  });

  return (
    <div className="mb-5">
      <div className="text-xs text-muted-foreground mb-2">
        {diffs} of {keys.length} items differ{diffOnly ? " · showing differences only" : ""}
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Item</TableHead>
            {runs.map((r, i) => <TableHead key={i} className="text-right">{colLabel(r)}</TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell className="font-semibold">Total</TableCell>
            {runs.map((r, i) => (
              <TableCell key={i} className="text-right font-semibold tabular-nums">{(r.response || {})["Renovations Total"] || ""}</TableCell>
            ))}
          </TableRow>
          {rows.filter((row) => !(diffOnly && row.same)).map((row) => (
            <TableRow key={row.k} className={row.same ? "" : "bg-secondary/60"}>
              <TableCell className={row.same ? "" : "border-l-2 border-primary font-semibold"}>{row.name}</TableCell>
              {row.costs.map((c, i) => <TableCell key={i} className="text-right tabular-nums">{c == null ? "—" : String(c)}</TableCell>)}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
