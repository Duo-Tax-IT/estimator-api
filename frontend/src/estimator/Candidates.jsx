import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { useEstimator } from "./store";

// Readable view of the match step's validated/rejected candidates, so a reviewer
// can audit what the model matched (and why others were dropped) without reading
// the raw Stages JSON.
export default function Candidates() {
  const result = useEstimator((s) => s.result);
  const c = result.Stages?.candidates;
  const validated = c?.validatedCandidates || [];
  const rejected = c?.rejectedCandidates || [];
  if (!validated.length && !rejected.length) return null;

  return (
    <Collapsible className="pt-2">
      <CollapsibleTrigger className="label cursor-pointer hover:text-foreground">
        Candidates ({validated.length} validated · {rejected.length} rejected)
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-3 space-y-2">
        {validated.map((v, i) => <Validated key={i} c={v} />)}
        {rejected.map((r, i) => <Rejected key={i} c={r} />)}
      </CollapsibleContent>
    </Collapsible>
  );
}

const Tag = ({ children }) => (
  <span className="text-xs text-muted-foreground bg-secondary rounded px-1.5 py-0.5">{children}</span>
);

function Validated({ c }) {
  return (
    <div className="card px-4 py-3 border-l-2 border-l-success">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium">{c.name}</span>
        <div className="flex gap-1.5 shrink-0">
          <Tag>{c.estimatedYear}</Tag><Tag>{c.roomType}</Tag><Tag>{c.confidence}</Tag>
        </div>
      </div>
      {(c.evidence || []).map((e, i) => (
        <p key={i} className="text-xs text-muted-foreground mt-1.5">
          Photo {e.photoIndex}{e.photoDate ? ` · ${e.photoDate}` : ""}: {e.visualEvidence}
        </p>
      ))}
    </div>
  );
}

function Rejected({ c }) {
  return (
    <div className="card px-4 py-3 border-l-2 border-l-destructive">
      <span className="text-sm font-medium text-muted-foreground line-through">{c.candidateName}</span>
      <p className="text-xs text-muted-foreground mt-1.5">{c.reason}</p>
    </div>
  );
}
