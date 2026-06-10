import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useEstimator } from "./store";

const FIELDS = [
  ["beds", "Bedrooms"],
  ["baths", "Bathrooms"],
  ["carSpaces", "Car Spaces"],
  ["yearBuilt", "Year Built"],
];

// Override rpdata's property details — edit after picking, before running.
export default function OverridePanel() {
  const override = useEstimator((s) => s.override);
  const setOverride = useEstimator((s) => s.setOverride);

  return (
    <div>
      <label className="flex items-center gap-2.5 cursor-pointer select-none text-sm">
        <Checkbox checked={override.enabled} onCheckedChange={(v) => setOverride({ enabled: !!v })} />
        <span>
          Override property details
          <span className="text-muted-foreground"> — use these instead of rpdata's; edit before running</span>
        </span>
      </label>

      {override.enabled && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mt-3 p-3.5 card">
          {FIELDS.map(([key, name]) => (
            <div key={key} className="flex flex-col gap-1.5 min-w-0">
              <Label className="label">{name}</Label>
              <Input type="number" min="0" inputMode="numeric" placeholder="—"
                value={override[key]} onChange={(e) => setOverride({ [key]: e.target.value })} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
