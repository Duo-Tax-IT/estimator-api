import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import PhotoCarousel from "@/components/PhotoCarousel";
import RpDataLink from "@/components/RpDataLink";
import { fmtMoney, fmtDuration } from "@/lib/money";
import { scaledTotal } from "@/lib/renovations";
import { useEstimator } from "./store";
import DebugTabs from "./DebugTabs";
import Candidates from "./Candidates";
import ChatPanel from "./ChatPanel";

// Left-column result summary: who/which, photos, total, summary, debug, runs.
export default function ResultMeta() {
  const selected = useEstimator((s) => s.selected);
  const result = useEstimator((s) => s.result);
  const version = useEstimator((s) => s.version);
  const photos = useEstimator((s) => s.photos);
  const scales = useEstimator((s) => s.scales);
  const currentRunId = useEstimator((s) => s.currentRunId);

  const renos = result.Renovations || [];
  const total = scaledTotal(renos, scales);
  const summary = result["Summary Description"] || "";
  const disclaimer = result.Disclaimer || "";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Showing estimate for <strong className="text-foreground">{selected.suggestion}</strong>
          <span className="px-2 opacity-40">·</span>rp_id {selected.suggestionId}
          <span className="px-2 opacity-40">·</span>{version}
          {result.DurationMs != null && <><span className="px-2 opacity-40">·</span>{fmtDuration(result.DurationMs)}</>}
          <span className="px-2 opacity-40">·</span><RpDataLink rpId={selected.suggestionId} />
        </p>
        <div className="flex items-center gap-2">
          {currentRunId && <ChatPanel />}
          <a href={`/learn?rpId=${selected.suggestionId}`} className="btn-soft whitespace-nowrap">Tune in Learning →</a>
        </div>
      </div>

      <PhotoCarousel key={selected.suggestionId} photos={photos} />

      <div className="card flex justify-between items-center px-5 py-4 border-l-2 border-l-primary">
        <span className="label">Renovations Total</span>
        <span className="text-3xl font-semibold text-success tabular-nums">{fmtMoney(total)}</span>
      </div>

      {summary && (
        <div className="card px-4 py-3 text-sm">
          <div className="label mb-1.5">Summary</div>
          {summary}
        </div>
      )}

      <DebugTabs />

      <Candidates />

      {disclaimer && <p className="text-xs text-muted-foreground leading-relaxed">{disclaimer}</p>}

      <SavedRuns />
    </div>
  );
}

const cell = (r) => {
  const resp = r.response || {};
  const names = (resp.Renovations || []).map((x) => x.Name).filter(Boolean).join(", ");
  const settings = [r.reasoning_effort, r.temperature != null ? `temp ${r.temperature}` : ""].filter(Boolean).join(" · ");
  return { names, settings, when: (r.created_at || "").replace("T", " ").slice(0, 16), resp };
};

function SavedRuns() {
  const runs = useEstimator((s) => s.runs);
  const openDetail = useEstimator((s) => s.openDetail);
  if (!runs.length) return null;

  return (
    <Collapsible className="pt-2">
      <CollapsibleTrigger className="label cursor-pointer hover:text-foreground">
        Saved runs (compare versions)
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-3">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead><TableHead>Label</TableHead><TableHead>Model</TableHead>
              <TableHead>Settings</TableHead><TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Took</TableHead><TableHead>Items</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((r) => {
              const c = cell(r);
              return (
                <TableRow key={r.id} className="cursor-pointer" onClick={() => openDetail(r)}>
                  <TableCell>{c.when}</TableCell>
                  <TableCell>{r.label || "—"}</TableCell>
                  <TableCell>{r.model || ""}</TableCell>
                  <TableCell>{c.settings}</TableCell>
                  <TableCell className="text-right tabular-nums">{c.resp["Renovations Total"] || ""}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{fmtDuration(r.duration_ms)}</TableCell>
                  <TableCell>{(c.resp.Renovations || []).length}<div className="text-xs text-muted-foreground">{c.names}</div></TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CollapsibleContent>
    </Collapsible>
  );
}
