import { useState } from "react";
import { pipelineStep } from "@/api";
import AddressSearch from "@/components/AddressSearch";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import PhotoPicker from "./PhotoPicker";
import Findings from "./Findings";

const Pre = ({ value }) => (
  <pre className="bg-secondary border border-border rounded-md p-2.5 overflow-auto max-h-[380px] mt-2.5 text-xs">
    {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
  </pre>
);

export default function Playground() {
  const [picked, setPicked] = useState(null);
  const [version, setVersion] = useState("v2"); // which pipeline's step routes to call
  const [config, setConfig] = useState("");
  const [buildYear, setBuildYear] = useState("");
  const [settlement, setSettlement] = useState("");
  const [secret, setSecret] = useState("");

  const [allPhotos, setAllPhotos] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [thumbs, setThumbs] = useState([]);

  const [status, setStatus] = useState({}); // { step: { text, err } }
  const [out, setOut] = useState({});        // { step: data }
  const [support, setSupport] = useState(null);
  const [priceTotal, setPriceTotal] = useState(null);

  // Editable intermediate inputs (auto-filled by upstream steps).
  const [inObs, setInObs] = useState('{"photoObservations": []}');
  const [inEra, setInEra] = useState('{"eraAnalysis": []}');
  const [inSupport, setInSupport] = useState('{"renovationSupportFindings": []}');
  const [inValidated, setInValidated] = useState("[]");

  // Fields every step shares; throws (readable) on bad config JSON.
  function base() {
    if (!picked) throw new Error("Pick a property first (address search above).");
    const body = { rpId: picked.rpId, address: picked.address };
    if (config.trim()) body.config = JSON.parse(config);
    if (settlement.trim()) body.settlementDate = settlement.trim();
    if (buildYear.trim()) body.buildYear = Number(buildYear);
    const sel = allPhotos.filter((p) => selected.has(p.url)).map((p) => ({ url: p.url, date: p.date ?? null }));
    if (sel.length) body.photos = sel; // dev: only send the picked subset
    return body;
  }

  async function runStep(name, runner) {
    setStatus((s) => ({ ...s, [name]: { text: "running…" } }));
    try {
      await runner();
      setStatus((s) => ({ ...s, [name]: { text: "done" } }));
    } catch (e) {
      setStatus((s) => ({ ...s, [name]: { text: e.message, err: true } }));
    }
  }

  const step = (name, body) => pipelineStep(version, name, body, secret);

  const steps = {
    context: async () => {
      const b = base();
      delete b.photos; // always fetch the FULL set to pick from
      const d = await step("context", b);
      setOut((o) => ({ ...o, context: d }));
      const photos = d.photos || [];
      setAllPhotos(photos);
      setSelected(new Set(photos.slice(0, 20).map((p) => p.url))); // default: first 20
    },
    // v3: one fused vision pass → {photoObservations, eraAnalysis, structureAnalysis}.
    analyze: async () => {
      const d = await step("analyze", base());
      const a = d.analysis || {};
      setOut((o) => ({ ...o, analyze: a }));
      setInObs(JSON.stringify({ photoObservations: a.photoObservations || [] }));
      setInEra(JSON.stringify({ eraAnalysis: a.eraAnalysis || [] }));
      setThumbs(d.photos || []);
    },
    observe: async () => {
      const d = await step("observe", base());
      setOut((o) => ({ ...o, observe: d.observations }));
      setInObs(JSON.stringify(d.observations));
      setThumbs(d.photos || []);
    },
    era: async () => {
      const d = await step("era", base());
      setOut((o) => ({ ...o, era: d.era }));
      setInEra(JSON.stringify(d.era));
    },
    support: async () => {
      const d = await step("support", { ...base(), observations: JSON.parse(inObs), era: JSON.parse(inEra) });
      setSupport(d.renovationSupport);
      setInSupport(JSON.stringify(d.renovationSupport));
    },
    match: async () => {
      const d = await step("match", { ...base(), renovationSupport: JSON.parse(inSupport) });
      setOut((o) => ({ ...o, match: d.candidates }));
      setInValidated(JSON.stringify(d.candidates.validatedCandidates || []));
    },
    price: async () => {
      const d = await step("price", { ...base(), validatedCandidates: JSON.parse(inValidated), observations: JSON.parse(inObs) });
      setPriceTotal(d["Renovations Total"] || "$0.00");
      setOut((o) => ({ ...o, price: d }));
    },
  };

  const toggle = (url) => setSelected((prev) => {
    const next = new Set(prev);
    next.has(url) ? next.delete(url) : next.add(url);
    return next;
  });
  const bulk = (mode) => setSelected(() => {
    if (mode === "all") return new Set(allPhotos.map((p) => p.url));
    if (mode === "20") return new Set(allPhotos.slice(0, 20).map((p) => p.url));
    return new Set();
  });

  return (
    <>
      <header className="sticky top-0 z-30 border-b border-border bg-background/70 backdrop-blur-xl">
        <div className="max-w-[960px] mx-auto px-6 h-16 flex items-center gap-3">
          <span className="font-semibold tracking-tight">{version} Pipeline Playground</span>
          <a href="/" className="btn-soft">← Estimator</a>
          <div className="flex gap-1">
            {["v2", "v3"].map((v) => (
              <button key={v} onClick={() => setVersion(v)}
                className={`btn-soft ${version === v ? "text-foreground font-semibold" : ""}`}>{v}</button>
            ))}
          </div>
          <span className="text-[13px] text-muted-foreground ml-auto truncate">{picked ? <><b className="text-foreground">{picked.address}</b> · rp_id {picked.rpId}</> : "No property selected"}</span>
        </div>
      </header>

      <main className="max-w-[960px] mx-auto p-5 space-y-4">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
          <div className="col-span-2">
            <Label className="label mb-1 block">Find property (address search)</Label>
            <AddressSearch onSelect={(s) => setPicked({ rpId: String(s.suggestionId), address: s.suggestion })} placeholder="Start typing an address…" />
          </div>
          <div>
            <Label className="label mb-1 block">config (JSON, optional)</Label>
            <Textarea rows={2} value={config} onChange={(e) => setConfig(e.target.value)} placeholder='{ }' />
          </div>
          <div className="space-y-2">
            <div>
              <Label className="label mb-1 block">build year (required if the property has none)</Label>
              <Input type="number" value={buildYear} onChange={(e) => setBuildYear(e.target.value)} placeholder="e.g. 1995" />
            </div>
            <div>
              <Label className="label mb-1 block">settlement date (YYYY-MM-DD, optional)</Label>
              <Input value={settlement} onChange={(e) => setSettlement(e.target.value)} placeholder="2010-01-01" />
            </div>
            <div>
              <Label className="label mb-1 block">secret-sauce header (optional)</Label>
              <Input value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="leave blank for local dev" />
            </div>
          </div>
        </div>

        <Step no="0" title="Context — upstream fetch" status={status.context} onRun={() => runStep("context", steps.context)}>
          <p className="text-xs text-muted-foreground mb-1.5">Property, GFA, photo count and trimmed catalog the pipeline starts from. Pick which photos are sent to the AI — first 20 are pre-selected.</p>
          <PhotoPicker photos={allPhotos} selected={selected} onToggle={toggle} onBulk={bulk} />
          {out.context && <Pre value={out.context} />}
        </Step>

        {version === "v3" ? (
          <Step no="1" title="Analyze — one master-JSON vision pass" status={status.analyze} onRun={() => runStep("analyze", steps.analyze)}>
            <p className="text-xs text-muted-foreground mb-1.5">Single vision pass → photoObservations + eraAnalysis + structureAnalysis. Auto-fills Support below.</p>
            <Thumbs photos={thumbs} />
            {out.analyze && <Pre value={out.analyze} />}
          </Step>
        ) : (
          <>
            <Step no="1" title="Observe — what's visible" status={status.observe} onRun={() => runStep("observe", steps.observe)}>
              <p className="text-xs text-muted-foreground mb-1.5">Vision pass → photoObservations. Auto-fills Match below.</p>
              <Thumbs photos={thumbs} />
              {out.observe && <Pre value={out.observe} />}
            </Step>

            <Step no="1b" title="Era — forensic dating" status={status.era} onRun={() => runStep("era", steps.era)}>
              <p className="text-xs text-muted-foreground mb-1.5">Vision pass → eraAnalysis (fabrication/style era per element). Auto-fills Match.</p>
              {out.era && <Pre value={out.era} />}
            </Step>
          </>
        )}

        <Step no="1.5" title="Renovation Support — does evidence support a reno?" status={status.support} onRun={() => runStep("support", steps.support)}>
          <p className="text-xs text-muted-foreground mb-1.5">Inputs auto-fill from steps 1/1b. Judges support + year against the build-year baseline — no catalog match yet.</p>
          <Field label="observations"><Textarea rows={5} value={inObs} onChange={(e) => setInObs(e.target.value)} /></Field>
          <Field label="eraAnalysis"><Textarea rows={5} value={inEra} onChange={(e) => setInEra(e.target.value)} /></Field>
          {support && <div className="mt-2.5"><Findings support={support} /></div>}
        </Step>

        <Step no="2" title="Match — ground supported findings → catalog" status={status.match} onRun={() => runStep("match", steps.match)}>
          <p className="text-xs text-muted-foreground mb-1.5">Edit renovationSupportFindings (auto-filled from 1.5), then Run. Only findings with shouldProceedToCatalogMatch are matched.</p>
          <Field label="renovationSupport"><Textarea rows={6} value={inSupport} onChange={(e) => setInSupport(e.target.value)} /></Field>
          {out.match && <Pre value={out.match} />}
        </Step>

        <Step no="3" title="Price & Format — year-guard → pricing" status={status.price} onRun={() => runStep("price", steps.price)}>
          <p className="text-xs text-muted-foreground mb-1.5">Edit validatedCandidates, then Run. Year-guard drops anything dated ≤ build year.</p>
          <Field label="validatedCandidates"><Textarea rows={5} value={inValidated} onChange={(e) => setInValidated(e.target.value)} /></Field>
          {priceTotal != null && <p className="text-[15px] font-semibold mt-2">Renovations Total: {priceTotal}</p>}
          {out.price && <Pre value={out.price} />}
        </Step>
      </main>
    </>
  );
}

function Step({ no, title, status, onRun, children }) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="flex items-center gap-2.5 px-3.5 py-2.5 border-b border-border">
        <span className="text-xs text-muted-foreground font-semibold">{no}</span>
        <h2 className="text-sm font-medium flex-1">{title}</h2>
        <span className={`text-xs ${status?.err ? "text-destructive" : "text-muted-foreground"}`}>{status?.text}</span>
        <Button size="sm" onClick={onRun}>Run</Button>
      </div>
      <div className="p-3.5">{children}</div>
    </Card>
  );
}

function Thumbs({ photos }) {
  if (!photos.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {photos.map((p, i) => (
        <figure key={i} className="w-[110px] m-0">
          <img src={p.url} loading="lazy" className="w-[110px] h-20 object-cover rounded border border-border" />
          <figcaption className="text-[11px] text-muted-foreground">#{p.photoIndex}{p.date ? " · " + p.date : ""}</figcaption>
        </figure>
      ))}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div className="mt-2">
      <Label className="label mb-1 block">{label}</Label>
      {children}
    </div>
  );
}
