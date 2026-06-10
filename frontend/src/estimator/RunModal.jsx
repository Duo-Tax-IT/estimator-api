import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import RenovationsTable from "./RenovationsTable";
import { useEstimator } from "./store";

function Kv({ rows }) {
  return (
    <div className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm mb-4">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents"><span className="text-muted-foreground">{k}</span><span className="tabular-nums">{String(v)}</span></div>
      ))}
    </div>
  );
}

export default function RunModal() {
  const run = useEstimator((s) => s.detailRun);
  const close = useEstimator((s) => s.closeDetail);
  if (!run) return null;

  const r = run.response || {};
  const u = r.Usage;
  const meta = [
    ["When", (run.created_at || "").replace("T", " ").slice(0, 19)],
    ["Address", run.address || `rp_id ${run.rp_id}`],
    ["Property id", run.rp_id],
    ["Model", run.model || "—"],
    ["Reasoning effort", run.reasoning_effort || "—"],
    ["Temperature", run.temperature != null ? run.temperature : "—"],
    ["Label", run.label || "—"],
  ];
  const usage = u && u.total_tokens
    ? [["Tokens (prompt / completion / total)", `${u.prompt_tokens} / ${u.completion_tokens} / ${u.total_tokens}`],
       ["Cost (USD)", `$${Number(u.cost).toFixed(4)}`]]
    : [["Usage", "— (run predates token tracking)"]];
  const debug = JSON.stringify({ Property: r.Property ?? null, GFA: r.GFA ?? null }, null, 2);

  return (
    <Dialog open onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-5xl max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle>Run details</DialogTitle></DialogHeader>

        <Kv rows={meta} />
        <Kv rows={usage} />

        <div className="card flex justify-between items-center px-4 py-3 mb-3">
          <span className="label">Renovations Total</span>
          <span className="text-2xl font-semibold text-success tabular-nums">{r["Renovations Total"] || "$0.00"}</span>
        </div>

        {r["Previous Owner Total"] != null && (
          <div className="card grid grid-cols-2 gap-2 px-4 py-3 mb-3 text-sm">
            <span className="label">Previous Owner</span><span className="text-right tabular-nums">{r["Previous Owner Total"]}</span>
            <span className="label">Current Owner</span><span className="text-right tabular-nums">{r["Current Owner Total"]}</span>
          </div>
        )}

        <RenovationsTable renos={r.Renovations || []} />

        {r["Summary Description"] && (
          <div className="card px-4 py-3 mt-3 text-sm"><div className="label mb-1.5">Summary</div>{r["Summary Description"]}</div>
        )}

        <Detail label="Property & GFA" body={debug} />
        {run.prompt && <Detail label="Prompt sent to AI" body={run.prompt} />}

        {r.Disclaimer && <p className="text-xs text-muted-foreground leading-relaxed mt-3">{r.Disclaimer}</p>}
      </DialogContent>
    </Dialog>
  );
}

function Detail({ label, body }) {
  return (
    <Collapsible className="mt-3">
      <CollapsibleTrigger className="label cursor-pointer hover:text-foreground">{label}</CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-words mt-2">{body}</pre>
      </CollapsibleContent>
    </Collapsible>
  );
}
