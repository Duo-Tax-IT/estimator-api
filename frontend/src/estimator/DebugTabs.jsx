import { useState } from "react";
import { previewPrompt } from "@/api";
import { useEstimator } from "./store";

// Click a tab to show its pane; click the active tab again to hide all. The
// prompt pane lazily fetches the assembled prompt with the current settings.
export default function DebugTabs() {
  const result = useEstimator((s) => s.result);
  const version = useEstimator((s) => s.version);
  const buildBody = useEstimator((s) => s.buildBody);
  const apiKey = useEstimator((s) => s.settings.apiKey);

  const [pane, setPane] = useState(null);
  const [prompt, setPrompt] = useState("");

  const debugJson = JSON.stringify({ Property: result.Property ?? null, GFA: result.GFA ?? null }, null, 2);
  const text = pane === "property" ? debugJson : pane === "stages" ? JSON.stringify(result.Stages, null, 2) : prompt;

  async function open(p) {
    if (pane === p) return setPane(null);
    setPane(p);
    if (p === "prompt") {
      setPrompt("Loading…");
      try { setPrompt(await previewPrompt(version, buildBody(), apiKey)); }
      catch (e) { setPrompt(e.message); }
    }
  }

  const tab = (id, label) => (
    <button type="button" onClick={() => open(id)} className={`btn-soft ${pane === id ? "is-active" : ""}`}>{label}</button>
  );

  return (
    <div className="card p-3 space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {tab("property", "Property details")}
        {tab("prompt", "Prompt sent to AI")}
        {result.Stages && tab("stages", "Pipeline stages")}
      </div>
      {pane && (
        <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-words tabular-nums max-h-[420px] overflow-auto">{text}</pre>
      )}
    </div>
  );
}
