import { useEffect, useState } from "react";
import { getRuns, getSessions, getPhotos, learnAnalyze } from "@/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import TopBar from "@/components/TopBar";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import PhotoCarousel from "@/components/PhotoCarousel";

const runLabel = (r) => `#${r.id} · ${r.address || r.rp_id} · ${r.label || "—"} · ${(r.response && r.response["Renovations Total"]) || ""}`;

const hasContent = (d) =>
  d != null && d !== "" && !(Array.isArray(d) && d.length === 0) &&
  !(typeof d === "object" && !Array.isArray(d) && Object.values(d).every((v) => v == null));

// The per-stage logs the AI compares against; empty stages are skipped.
function logSections(resp) {
  const st = resp.Stages || {};
  const defs = [
    ["Renovations", { Renovations: resp.Renovations, "Renovations Total": resp["Renovations Total"] }],
    ["Summary (AI)", resp["Summary Description"]],
    ["Observe (1)", st.observations],
    ["Era (1b)", st.eraAnalysis],
    ["Support (1.5)", st.renovationSupport],
    ["Match (2)", st.candidates],
    ["Pricing (3)", { toolInput: st.toolInput, bci: st.bci, paintAssumption: st.paintAssumption }],
    ["Room hints", st.roomHints],
    ["Photos", st.photos],
    ["Property / GFA", { Property: resp.Property, GFA: resp.GFA }],
    ["Meta", resp.Meta],
  ];
  return defs.filter(([, d]) => hasContent(d));
}

export default function Learn() {
  const [runs, setRuns] = useState([]);
  const [analyzed, setAnalyzed] = useState(() => new Set());
  const [runId, setRunId] = useState("");
  const [secret, setSecret] = useState("");
  const [expert, setExpert] = useState("");
  const [analyzeStatus, setAnalyzeStatus] = useState(null);
  const [active, setActive] = useState(0);
  const [photos, setPhotos] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [sessions, setSessions] = useState([]);

  // Load saved runs + which ones were already analyzed (mount only). When opened
  // from the estimator (?rpId=…), pre-select that property's most recent run.
  useEffect(() => {
    (async () => {
      try {
        const rs = await getRuns();
        setRuns(rs);
        const ss = await getSessions();
        setAnalyzed(new Set(ss.map((s) => s.run_id)));
        const rpId = new URLSearchParams(window.location.search).get("rpId");
        if (rpId) {
          const run = rs.filter((r) => String(r.rp_id) === rpId).sort((a, b) => b.id - a.id)[0];
          if (run) selectRun(String(run.id), rs);
        }
      } catch { /* shown via empty list */ }
    })();
  }, []);

  const selectedRun = runs.find((r) => String(r.id) === runId) || null;
  const sections = selectedRun ? logSections(selectedRun.response || {}) : [];

  async function selectRun(id, list = runs) {
    setRunId(id);
    setActive(0);
    setAnalysis(null);
    const run = list.find((r) => String(r.id) === id);
    if (!run) { setPhotos([]); setSessions([]); return; }
    try { setPhotos(await getPhotos(run.rp_id, secret)); } catch { setPhotos([]); }
    loadSessions(run.id);
  }

  async function loadSessions(id) {
    try { setSessions(await getSessions(id, secret)); } catch { /* best-effort */ }
  }

  async function analyze() {
    if (!selectedRun) return;
    if (!expert.trim()) { setAnalyzeStatus({ text: "enter expert notes first" }); return; }
    setAnalyzeStatus({ text: "analyzing…" });
    try {
      setAnalysis(await learnAnalyze({ runId: selectedRun.id, expertInput: expert.trim() }, secret));
      setAnalyzeStatus({ text: "done" });
      setAnalyzed((prev) => new Set(prev).add(selectedRun.id));
      loadSessions(selectedRun.id);
    } catch (e) {
      setAnalyzeStatus({ text: e.message, err: true });
    }
  }

  return (
    <>
      <TopBar />

      <main className="max-w-[1100px] mx-auto p-5">
        <div className="grid grid-cols-[2fr_1fr] gap-x-4 gap-y-2.5 mb-4">
          <div>
            <Label className="label mb-1 block">Pick a saved run</Label>
            <Select value={runId} onValueChange={selectRun}>
              <SelectTrigger><SelectValue placeholder={runs.length ? "— pick a run —" : "Loading runs…"} /></SelectTrigger>
              <SelectContent>
                {runs.map((r) => (
                  <SelectItem key={r.id} value={String(r.id)}>{runLabel(r)}{analyzed.has(r.id) ? " · analyzed" : ""}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="label mb-1 block">secret-sauce header (optional)</Label>
            <Input value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="leave blank for local dev" />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-[18px]">
          {/* Left: expert notes + run logs */}
          <div className="space-y-[18px] min-w-0">
            <Section title="Expert ground truth" right={<span className={`text-xs ${analyzeStatus?.err ? "text-destructive" : "text-muted-foreground"}`}>{analyzeStatus?.text}</span>}
              action={<Button size="sm" disabled={!selectedRun} onClick={analyze}>Analyze</Button>}>
              <p className="text-xs text-muted-foreground mb-2">Paste the QS's assessment of what this property actually had (items, rooms, years). The photos are on the right.</p>
              <Textarea rows={12} value={expert} onChange={(e) => setExpert(e.target.value)}
                placeholder="e.g. Full bathroom renovation ~2018 (new vanity, frameless screen, floor + wall tiles). Kitchen original. Split system to living added ~2020." />
            </Section>

            <Section title="Run logs">
              {!sections.length ? (
                <p className="text-xs text-muted-foreground">Select a run above.</p>
              ) : (
                <>
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {sections.map(([label], i) => (
                      <button key={i} onClick={() => setActive(i)}
                        className={`text-xs px-2.5 py-1 rounded-full border ${i === active ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:text-foreground"}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                  <Pre value={sections[active]?.[1]} />
                </>
              )}
            </Section>
          </div>

          {/* Right: photos + analysis + sessions */}
          <div className="space-y-[18px] min-w-0">
            <Section title="Photo preview">
              {photos.length ? <PhotoCarousel key={runId} photos={photos} />
                : <p className="text-xs text-muted-foreground">Select a run to load its photos.</p>}
            </Section>

            <Section title="Tuning analysis">
              {analysis ? <Analysis a={analysis} /> : <p className="text-xs text-muted-foreground">Run an analysis to see discrepancies and tuning recommendations.</p>}
            </Section>

            <Section title="Past sessions">
              {sessions.length ? sessions.map((s) => (
                <details key={s.id} className="card px-2.5 py-1.5 mb-1.5 text-xs">
                  <summary className="cursor-pointer">#{s.id} · {s.created_at} · {(s.analysis.discrepancies || []).length} discrepancies</summary>
                  <div className="mt-1"><span className="text-muted-foreground">expert:</span> {s.expert_input}</div>
                  <Pre value={s.analysis} />
                </details>
              )) : <p className="text-xs text-muted-foreground">None yet for this run.</p>}
            </Section>
          </div>
        </div>
      </main>
    </>
  );
}

const Pre = ({ value }) => (
  <pre className="bg-secondary border border-border rounded-md p-2.5 overflow-auto max-h-[70vh] mt-2 text-xs whitespace-pre-wrap [overflow-wrap:anywhere]">
    {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
  </pre>
);

function Section({ title, right, action, children }) {
  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex items-center gap-2.5 px-3.5 py-2.5 border-b border-border">
        <h2 className="text-sm font-medium flex-1">{title}</h2>
        {right}
        {action}
      </div>
      <div className="p-3.5">{children}</div>
    </Card>
  );
}

const badge = (text, cls) => <Badge variant="outline" className={cls}>{text}</Badge>;

function Analysis({ a }) {
  return (
    <>
      <p className="text-[13px] mb-2.5">{a.accuracySummary || ""}</p>
      <Label className="label">Discrepancies</Label>
      {(a.discrepancies || []).length ? a.discrepancies.map((d, i) => (
        <div key={i} className="card p-2.5 mb-2 mt-1">
          {badge(d.issue || "issue")} {badge(d.rootCauseStage || "?", "text-primary border-primary/40")}
          <b className="text-[13px]"> {d.item || ""}</b>
          <div className="text-xs mt-1"><span className="text-muted-foreground">expert:</span> {d.expert || ""}</div>
          <div className="text-xs"><span className="text-muted-foreground">system:</span> {d.system || ""}</div>
          <div className="text-xs">{d.explanation || ""}</div>
        </div>
      )) : <p className="text-xs text-muted-foreground">No discrepancies.</p>}

      <Label className="label mt-2.5 block">Recommendations</Label>
      {(a.tuningRecommendations || []).length ? a.tuningRecommendations.map((r, i) => (
        <div key={i} className="card p-2.5 mb-2 mt-1">
          {badge(r.priority || "", r.priority === "high" ? "text-destructive border-destructive/40" : "")} {badge(r.target || "", "text-primary border-primary/40")}
          <b className="text-[13px]"> {r.change || ""}</b>
          <div className="text-xs mt-1">{r.rationale || ""}</div>
        </div>
      )) : <p className="text-xs text-muted-foreground">No recommendations.</p>}
    </>
  );
}
