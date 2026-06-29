import { useEffect, useState } from "react";
import { getTrainingEstimates, getTrainingEstimate, getPhotos } from "@/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import PhotoCarousel from "@/components/PhotoCarousel";
import TopBar from "@/components/TopBar";
import { parseMoney, fmtMoney } from "@/lib/money";

// RP Data links end in the property id: .../property/6951254 — also the photos key.
const rpIdFromLink = (url) => url?.match(/property\/(\d+)/)?.[1];

const STATUS_VARIANT = { ok: "default", error: "destructive", skipped: "secondary", running: "outline" };
const SUPPORT_VARIANT = { supported: "default", unsupported: "destructive", uncertain: "secondary" };

// A titled list of analysis entries; renders nothing when empty.
function Section({ title, items, render }) {
  if (!items.length) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      {items.map((it, i) => (
        <div key={i} className="text-sm border-l-2 pl-3">{render(it)}</div>
      ))}
    </div>
  );
}

// The three headline totals the v3 output carries, shown when present.
const totalsOf = (est) =>
  [["Renovations Total", est["Renovations Total"]],
   ["Current Owner Total", est["Current Owner Total"]],
   ["Previous Owner Total", est["Previous Owner Total"]]].filter(([, v]) => v != null);

function Detail({ row, photos }) {
  const [raw, setRaw] = useState(false);
  if (!row) return <p className="text-sm text-muted-foreground p-4">Select a run on the left to see its result.</p>;
  if (row.status !== "ok") {
    return (
      <div className="p-4 space-y-2">
        <Badge variant={STATUS_VARIANT[row.status]}>{row.status}</Badge>
        {row.error && <p className="text-sm text-destructive">{row.error}</p>}
      </div>
    );
  }
  const est = row.estimate || {};
  const renos = est.Renovations || [];
  const links = row.links || {};
  const era = est.Stages?.eraAnalysis?.eraAnalysis || [];
  const support = est.Stages?.renovationSupport?.renovationSupportFindings || [];
  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap gap-2">
        {links.salesforce && (
          <a href={links.salesforce} target="_blank" rel="noreferrer" className="btn-soft text-sm">Salesforce ↗</a>
        )}
        {links.caesar && (
          <a href={links.caesar} target="_blank" rel="noreferrer" className="btn-soft text-sm">Caesar ↗</a>
        )}
        {links.rp_data && (
          <a href={links.rp_data} target="_blank" rel="noreferrer" className="btn-soft text-sm">RP Data ↗</a>
        )}
      </div>
      <PhotoCarousel key={row.id} photos={photos} />
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {totalsOf(est).map(([k, v]) => (
          <span key={k}><span className="text-muted-foreground">{k}:</span> <strong>{v}</strong></span>
        ))}
      </div>
      <Table>
        <TableHeader>
          <TableRow><TableHead>Renovation</TableHead><TableHead className="text-right">Final cost</TableHead></TableRow>
        </TableHeader>
        <TableBody>
          {renos.map((r, i) => (
            <TableRow key={i}>
              <TableCell className="whitespace-normal">
                {r.Name}
                {r.Reason && <div className="text-xs text-muted-foreground mt-0.5">{r.Reason}</div>}
              </TableCell>
              <TableCell className="text-right align-top">{fmtMoney(parseMoney(r.FinalCost))}</TableCell>
            </TableRow>
          ))}
          {!renos.length && (
            <TableRow><TableCell colSpan={2} className="text-muted-foreground">No renovations detected.</TableCell></TableRow>
          )}
        </TableBody>
      </Table>
      <Section title="Renovation analysis" items={support} render={(s) => (
        <>
          <div className="font-medium">{s.observedItem}
            {s.roomType && <span className="text-muted-foreground"> · {s.roomType}</span>}</div>
          <div className="text-xs mt-0.5">
            <Badge variant={SUPPORT_VARIANT[s.supportStatus]}>{s.supportStatus}</Badge>
            <span className="text-muted-foreground"> {s.supportStrength}
              {s.estimatedRenovationYear && ` · ~${s.estimatedRenovationYear}`}</span>
          </div>
          {!!s.supportBasis?.length && (
            <ul className="text-xs text-muted-foreground list-disc ml-4 mt-1">
              {s.supportBasis.map((b, j) => <li key={j}>{b}</li>)}
            </ul>
          )}
        </>
      )} />
      <Section title="Era analysis" items={era} render={(e) => (
        <>
          <div className="font-medium">{e.element}
            {e.roomType && <span className="text-muted-foreground"> · {e.roomType}</span>}</div>
          <div className="text-xs mt-0.5">
            <strong>{e.estimatedEra}</strong>
            <span className="text-muted-foreground"> · {e.confidence}
              {e.styleMovement && ` · ${e.styleMovement}`}</span>
          </div>
          {e.analysis && <p className="text-xs text-muted-foreground mt-1">{e.analysis}</p>}
        </>
      )} />
      <button className="text-xs text-muted-foreground underline" onClick={() => setRaw(!raw)}>
        {raw ? "Hide" : "Show"} raw JSON
      </button>
      {raw && <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-96">{JSON.stringify(est, null, 2)}</pre>}
    </div>
  );
}

export default function Training() {
  const [rows, setRows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [photos, setPhotos] = useState([]);

  useEffect(() => { getTrainingEstimates().then(setRows).catch(() => {}); }, []);

  const select = (id) =>
    getTrainingEstimate(id).then((row) => {
      setSelected(row);
      setPhotos([]);
      const rpId = rpIdFromLink(row?.links?.rp_data);
      if (rpId) getPhotos(rpId).then(setPhotos).catch(() => {});
    }).catch(() => {});

  return (
    <>
      <TopBar>
        <span className="text-sm text-muted-foreground">{rows.length} runs saved by the run harness</span>
      </TopBar>

      <div className="max-w-7xl mx-auto p-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-0 overflow-auto lg:sticky lg:top-20 lg:self-start lg:max-h-[calc(100vh-6rem)]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Address</TableHead><TableHead>Pipeline</TableHead>
                <TableHead>Status</TableHead><TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id} onClick={() => select(r.id)}
                  className={`cursor-pointer ${selected?.id === r.id ? "bg-muted" : ""}`}>
                  <TableCell className="max-w-[14rem] truncate">{r.address || r.opportunity_id}</TableCell>
                  <TableCell>{r.pipeline}</TableCell>
                  <TableCell><Badge variant={STATUS_VARIANT[r.status]}>{r.status}</Badge></TableCell>
                  <TableCell className="text-muted-foreground text-xs whitespace-nowrap">{new Date(r.created_at).toLocaleString()}</TableCell>
                </TableRow>
              ))}
              {!rows.length && (
                <TableRow><TableCell colSpan={4} className="text-muted-foreground p-4">
                  No runs yet — run <code>python -m app.opportunities.runner --pipeline v3</code>
                </TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
        <Card><Detail row={selected} photos={photos} /></Card>
      </div>
      </div>
    </>
  );
}
