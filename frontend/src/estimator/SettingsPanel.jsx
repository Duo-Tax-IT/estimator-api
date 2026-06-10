import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { formatDateInput } from "@/lib/dateInput";
import { useEstimator } from "./store";

const EFFORTS = ["minimal", "low", "medium", "high"];

function Row({ label, help, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="label">{label}{help && <span className="normal-case tracking-normal opacity-80"> — {help}</span>}</Label>
      {children}
    </div>
  );
}

export default function SettingsPanel() {
  const settings = useEstimator((s) => s.settings);
  const set = useEstimator((s) => s.setSettings);

  return (
    <Collapsible className="card p-4">
      <CollapsibleTrigger className="text-[13px] text-muted-foreground hover:text-foreground cursor-pointer">
        Model &amp; settings
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-3.5 pt-3.5">
        <Row label="Model" help="blank uses the server default">
          <Input list="modelOptions" placeholder="e.g. gemini-3.5-flash" autoComplete="off"
            value={settings.model} onChange={(e) => set({ model: e.target.value })} />
          <datalist id="modelOptions">
            <option value="gemini-3.5-flash" /><option value="gemini-2.5-flash" /><option value="gemini-flash-latest" />
          </datalist>
        </Row>

        <Row label="Version label" help="tags this run for comparison">
          <Input placeholder="e.g. v3 high effort" autoComplete="off"
            value={settings.label} onChange={(e) => set({ label: e.target.value })} />
        </Row>

        <Row label="Settlement date" help="dd/mm/yyyy; renovations before it are the previous owner's">
          <Input inputMode="numeric" placeholder="dd/mm/yyyy" maxLength={10} autoComplete="off"
            value={settings.settlementDate} onChange={(e) => set({ settlementDate: formatDateInput(e.target.value) })} />
        </Row>

        <div className="grid grid-cols-2 gap-3">
          <Row label="Reasoning effort" help="gpt-5.x / o-series">
            <Select value={settings.reasoningEffort || "default"}
              onValueChange={(v) => set({ reasoningEffort: v === "default" ? "" : v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="default">Default (low)</SelectItem>
                {EFFORTS.map((e) => <SelectItem key={e} value={e}>{e}</SelectItem>)}
              </SelectContent>
            </Select>
          </Row>
          <Row label="Temperature" help="classic models">
            <Input type="number" min="0" max="2" step="0.1" placeholder="Default (0)"
              value={settings.temperature} onChange={(e) => set({ temperature: e.target.value })} />
          </Row>
        </div>

        <Row label="Auth">
          <Input type="password" placeholder="secret-sauce header (only if the API requires one)"
            value={settings.apiKey} onChange={(e) => set({ apiKey: e.target.value })} />
        </Row>
      </CollapsibleContent>
    </Collapsible>
  );
}
