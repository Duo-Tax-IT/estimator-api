import { Badge } from "@/components/ui/badge";

// Step 1.5 renovationSupportFindings as organised cards (not a JSON dump).
export default function Findings({ support }) {
  const findings = support?.renovationSupportFindings || [];
  if (!findings.length) return <p className="text-sm text-muted-foreground">No findings.</p>;

  return (
    <div className="flex flex-col gap-2">
      {findings.map((f, i) => {
        const statusCls = f.supportStatus === "supported" ? "text-success border-success/40"
          : f.supportStatus === "unsupported" ? "text-destructive border-destructive/40" : "";
        return (
          <div key={i} className="card p-2.5">
            <div className="flex flex-wrap gap-1.5 items-center mb-1">
              <Badge variant="outline" className="capitalize">{f.roomType || "?"}</Badge>
              <Badge variant="outline" className={`capitalize ${statusCls}`}>{f.supportStatus || ""}</Badge>
              <Badge variant="outline">{f.supportStrength || ""}</Badge>
              <Badge variant="outline">{f.estimatedRenovationYear || "—"}</Badge>
              <span className={`ml-auto text-[11px] ${f.shouldProceedToCatalogMatch ? "text-primary" : "text-muted-foreground"}`}>
                {f.shouldProceedToCatalogMatch ? "→ match" : "gated"}
              </span>
            </div>
            <div className="font-semibold text-[13px]">{f.observedItem || ""}</div>
            {!!(f.supportBasis || []).length && (
              <ul className="list-disc pl-5 mt-1 text-xs text-muted-foreground">
                {f.supportBasis.map((b, j) => <li key={j}>{b}</li>)}
              </ul>
            )}
            {!!(f.limitations || []).length && (
              <div className="mt-1.5 text-xs text-amber-500/90">
                <span className="text-muted-foreground">Limitations:</span> {f.limitations.join("; ")}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
