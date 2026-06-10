import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import AddressSearch from "@/components/AddressSearch";
import { useEstimator } from "./store";
import OverridePanel from "./OverridePanel";
import RunControls from "./RunControls";
import SettingsPanel from "./SettingsPanel";
import ResultMeta from "./ResultMeta";
import RenovationsTable from "./RenovationsTable";
import HistoryView from "./HistoryView";
import RunModal from "./RunModal";

export default function Estimator() {
  const select = useEstimator((s) => s.select);
  const result = useEstimator((s) => s.result);
  const tab = useEstimator((s) => s.tab);
  const setTab = useEstimator((s) => s.setTab);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border bg-background/70 backdrop-blur-xl">
        <div className="max-w-[1180px] mx-auto px-6 h-16 flex items-center justify-between">
          <span className="font-semibold tracking-tight">Renovation Estimator</span>
          <nav className="flex items-center gap-1">
            <a href="/playground" className="btn-soft">Playground</a>
            <a href="/learn" className="btn-soft">Learning</a>
          </nav>
        </div>
      </header>

      <main className="max-w-[1180px] mx-auto px-6 py-8">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="estimate">Estimate</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>

          <TabsContent value="estimate" className="mt-6 space-y-5">
            <Card className="p-6 space-y-5">
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Find a property</h2>
                <p className="text-sm text-muted-foreground mt-0.5">
                  Search an address and pick the property — we'll estimate the renovations detected in its photos.
                </p>
              </div>
              <AddressSearch onSelect={select} placeholder="Search an address, e.g. 1 Fullarton Street"
                inputClassName="h-12 text-base px-4 rounded-xl" />
              <OverridePanel />
              <RunControls />
            </Card>

            <SettingsPanel />

            {result ? (
              <div className="grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] gap-6 items-start">
                <ResultMeta />
                <div className="lg:sticky lg:top-20"><RenovationsTable interactive /></div>
              </div>
            ) : (
              <div className="card grid place-items-center text-center text-sm text-muted-foreground py-16 px-6">
                <div className="max-w-sm space-y-1">
                  <p className="text-foreground font-medium">No estimate yet</p>
                  <p>Pick a property above, then run v1 or v2 to see the detected renovations, photos and total.</p>
                </div>
              </div>
            )}
          </TabsContent>

          <TabsContent value="history" className="mt-6">
            <HistoryView />
          </TabsContent>
        </Tabs>
      </main>

      <RunModal />
    </div>
  );
}
