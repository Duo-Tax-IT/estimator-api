import { create } from "zustand";
import * as api from "@/api";
import { settlementIso } from "@/lib/dateInput";

const blankSettings = { model: "", label: "", settlementDate: "", reasoningEffort: "", temperature: "", apiKey: "" };
const blankOverride = { enabled: false, beds: "", baths: "", carSpaces: "", yearBuilt: "" };

// Only non-empty fields, under rpdata's own keys, so the model sees the shape it
// would from a fetched property. Returns null when override is off/blank.
function pickOverride(o) {
  if (!o.enabled) return null;
  const property = {};
  for (const k of ["beds", "baths", "carSpaces", "yearBuilt"]) {
    const v = String(o[k]).trim();
    if (v) property[k] = v;
  }
  return Object.keys(property).length ? property : null;
}

export const useEstimator = create((set, get) => ({
  tab: "estimate",  // active top-level tab
  selected: null,   // the picked suggestion
  result: null,     // last rendered estimate
  version: "v1",    // which pipeline produced `result`
  photos: [],
  runs: [],         // saved runs for the current property
  status: "",
  error: "",
  detailRun: null,  // run shown in the details modal
  currentRunId: null, // saved run id of the shown estimate, for the chat panel
  scales: {},       // per-top-parent { on, mul } for the live ×-scale test harness
  settings: blankSettings,
  override: blankOverride,

  setSettings: (patch) => set((s) => ({ settings: { ...s.settings, ...patch } })),
  setOverride: (patch) => set((s) => ({ override: { ...s.override, ...patch } })),
  setScale: (parent, patch) => set((s) => ({ scales: { ...s.scales, [parent]: { ...s.scales[parent], ...patch } } })),
  setTab: (tab) => set({ tab }),
  openDetail: (run) => set({ detailRun: run }),
  closeDetail: () => set({ detailRun: null }),

  // The EstimateRequest body for a picked suggestion, from the current form.
  buildBody(s = get().selected) {
    const { settings } = get();
    const body = { rpId: String(s.suggestionId) };
    if (s.suggestion) body.address = s.suggestion;
    const ov = pickOverride(get().override);
    if (ov) body.property = ov;
    if (settings.model.trim()) body.model = settings.model.trim();
    if (settings.reasoningEffort) body.reasoningEffort = settings.reasoningEffort;
    if (settings.temperature.trim() !== "") body.temperature = Number(settings.temperature);
    if (settings.label.trim()) body.label = settings.label.trim();
    const iso = settlementIso(settings.settlementDate);
    if (iso) body.settlementDate = iso;
    return body;
  },

  // Pick a property: show it, load photos. Running is a separate step.
  select(s) {
    set({ selected: s, result: null, error: "", status: "", photos: [], scales: {}, currentRunId: null });
    get().loadPhotos(s.suggestionId);
  },

  async loadPhotos(rpId) {
    try { set({ photos: await api.getPhotos(rpId) }); } catch { /* non-fatal */ }
  },
  async loadRuns(rpId) {
    try { set({ runs: await api.getRuns(rpId) }); } catch { /* non-fatal */ }
  },

  async run(version) {
    const s = get().selected;
    if (!s) return;
    set({ result: null, error: "", status: "Thinking…" });
    try {
      const data = await api.estimate(version, get().buildBody(s), get().settings.apiKey);
      set({ result: data, version, status: "", scales: {}, currentRunId: data.RunId ?? null });
      get().loadRuns(s.suggestionId);
    } catch (e) {
      set({ error: e.message, status: "" });
    }
  },

  // Re-open a saved run in the estimate view — no model call.
  openSavedRun(runRow) {
    const s = { suggestion: runRow.address || `rp_id ${runRow.rp_id}`, suggestionId: runRow.rp_id };
    const result = runRow.response || {};
    set({ selected: s, result, version: result.Stages ? "v2" : "v1", error: "", status: "", detailRun: null, scales: {}, tab: "estimate", currentRunId: runRow.id });
    get().loadPhotos(runRow.rp_id);
    get().loadRuns(runRow.rp_id);
  },
}));
