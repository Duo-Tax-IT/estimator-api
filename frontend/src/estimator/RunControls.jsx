import { Button } from "@/components/ui/button";
import { useEstimator } from "./store";

// Picked-property line, the Run v1 / Run v2 buttons, and status / error.
export default function RunControls() {
  const selected = useEstimator((s) => s.selected);
  const status = useEstimator((s) => s.status);
  const error = useEstimator((s) => s.error);
  const run = useEstimator((s) => s.run);

  return (
    <div className="space-y-3">
      {selected && (
        <p className="text-sm text-muted-foreground">
          Selected <strong className="text-foreground">{selected.suggestion}</strong>
          <span className="px-2 opacity-40">·</span>
          rp_id {selected.suggestionId} — choose a version to run
        </p>
      )}

      <div className="flex gap-2.5">
        <Button disabled={!selected || !!status} onClick={() => run("v1")}>Run v1</Button>
        <Button disabled={!selected || !!status} onClick={() => run("v2")}>Run v2</Button>
      </div>

      {status && (
        <p className="flex items-center gap-2.5 text-sm text-muted-foreground">
          <span className="spinner" /> {status}
        </p>
      )}
      {error && (
        <p className="px-4 py-3 rounded-xl text-sm text-destructive bg-destructive/10 border border-destructive/30">
          {error}
        </p>
      )}
    </div>
  );
}
