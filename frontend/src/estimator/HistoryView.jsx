import { Fragment, useEffect, useState } from "react";
import { getRuns, photosDownloadUrl } from "@/api";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { useEstimator } from "./store";
import CompareMatrix from "./CompareMatrix";
import RpDataLink from "@/components/RpDataLink";

const fmtRun = (r) => {
  const resp = r.response || {};
  return {
    resp,
    renos: resp.Renovations || [],
    when: (r.created_at || "").replace("T", " ").slice(0, 16),
    settings: [r.reasoning_effort, r.temperature != null ? `temp ${r.temperature}` : ""].filter(Boolean).join(" · "),
  };
};

export default function HistoryView() {
  const [runs, setRuns] = useState(null); // null = loading
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState(() => new Set());
  const [picked, setPicked] = useState(() => new Set());
  const [compare, setCompare] = useState([]);
  const [diffOnly, setDiffOnly] = useState(false);
  const openDetail = useEstimator((s) => s.openDetail);
  const openSavedRun = useEstimator((s) => s.openSavedRun);

  async function load() {
    setRuns(null);
    try { setRuns(await getRuns(filter.trim())); } catch { setRuns([]); }
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (set, setter) => (id) => setter((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });
  const toggleExpand = toggle(expanded, setExpanded);
  const togglePick = toggle(picked, setPicked);
  const stop = (e) => e.stopPropagation();

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-base font-semibold">Saved runs</h2>
        <div className="flex items-center gap-2 flex-wrap">
          <Input value={filter} onChange={(e) => setFilter(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()}
            placeholder="Filter by property id" className="w-56" />
          <label className="flex items-center gap-2 text-sm cursor-pointer px-1">
            <Checkbox checked={diffOnly} onCheckedChange={(v) => setDiffOnly(!!v)} /> Differences only
          </label>
          <Button variant="secondary" onClick={() => setCompare((runs || []).filter((r) => picked.has(r.id)))}>
            Compare{picked.size ? ` (${picked.size})` : ""}
          </Button>
          <Button variant="secondary" onClick={load}>Refresh</Button>
        </div>
      </div>

      {compare.length >= 2 && <CompareMatrix runs={compare} diffOnly={diffOnly} />}

      {runs === null ? (
        <div className="card text-center text-muted-foreground py-12">Loading…</div>
      ) : !runs.length ? (
        <div className="card text-center text-muted-foreground py-12">No saved runs yet.</div>
      ) : (
        <Card className="p-0 overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead className="w-8" />
                <TableHead>When</TableHead>
                <TableHead>Property</TableHead>
                <TableHead>Model</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Items</TableHead>
                <TableHead className="text-right pr-4">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((r) => {
                const { resp, renos, when, settings } = fmtRun(r);
                const open = expanded.has(r.id);
                return (
                  <Fragment key={r.id}>
                    <TableRow className="cursor-pointer" onClick={() => toggleExpand(r.id)}>
                      <TableCell className="text-muted-foreground text-center">{open ? "▾" : "▸"}</TableCell>
                      <TableCell onClick={stop}><Checkbox checked={picked.has(r.id)} onCheckedChange={() => togglePick(r.id)} /></TableCell>
                      <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground">{when}</TableCell>
                      <TableCell>
                        <div className="font-medium">{r.address || `rp_id ${r.rp_id}`}</div>
                        {r.label && r.label !== "—" && <div className="text-xs text-muted-foreground">{r.label}</div>}
                      </TableCell>
                      <TableCell>
                        <div>{r.model || "—"}</div>
                        {settings && <div className="text-xs text-muted-foreground">{settings}</div>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-medium">{resp["Renovations Total"] || ""}</TableCell>
                      <TableCell className="text-right tabular-nums">{renos.length}</TableCell>
                      <TableCell className="text-right whitespace-nowrap pr-2" onClick={stop}>
                        <Button size="sm" variant="ghost" onClick={() => openDetail(r)}>Details</Button>
                        <Button size="sm" variant="ghost" onClick={() => openSavedRun(r)}>Open</Button>
                        <a className="text-primary hover:underline text-[13px] px-2" href={photosDownloadUrl(r.rp_id)}>Photos</a>
                        <RpDataLink rpId={r.rp_id} className="text-[13px] px-2" />
                      </TableCell>
                    </TableRow>

                    {open && (
                      <TableRow className="bg-secondary/30 hover:bg-secondary/30">
                        <TableCell colSpan={8} className="p-4">
                          <div className="text-[13px] mb-3"><span className="text-muted-foreground">Summary:</span> {resp["Summary Description"] || "—"}</div>
                          {renos.length ? (
                            <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-6 gap-y-1 text-xs">
                              <div className="label">Item</div><div className="label text-right">Year</div>
                              <div className="label text-right">Qty</div><div className="label">Unit</div><div className="label text-right">Cost</div>
                              {renos.map((x, i) => (
                                <Fragment key={i}>
                                  <div className="truncate">{x.Name ?? ""}</div>
                                  <div className="text-right tabular-nums text-muted-foreground">{x.Year ?? ""}</div>
                                  <div className="text-right tabular-nums text-muted-foreground">{x.Quantity ?? ""}</div>
                                  <div className="text-muted-foreground">{x.Unit ?? ""}</div>
                                  <div className="text-right tabular-nums">{x.FinalCost ?? ""}</div>
                                </Fragment>
                              ))}
                            </div>
                          ) : <div className="text-xs text-muted-foreground">No items</div>}
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}
    </section>
  );
}
