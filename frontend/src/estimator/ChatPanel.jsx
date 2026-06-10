import { useState } from "react";
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { chat, getChat } from "@/api";
import { useEstimator } from "./store";

// Diagnostic chat about the current run (explain-only). Self-contained: the
// "Ask the AI" trigger + a right slide-over holding the persisted thread.
export default function ChatPanel() {
  const runId = useEstimator((s) => s.currentRunId);
  const apiKey = useEstimator((s) => s.settings.apiKey);
  const selected = useEstimator((s) => s.selected);

  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [includePhotos, setIncludePhotos] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function onOpenChange(next) {
    setOpen(next);
    if (next) getChat(runId, apiKey).then(setMessages).catch(() => {});
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput(""); setError("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const { reply } = await chat(runId, text, includePhotos, apiKey);
      setMessages((m) => [...m, { role: "assistant", content: reply }]);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger className="btn-soft whitespace-nowrap">Ask the AI</SheetTrigger>
      <SheetContent className="w-full sm:max-w-lg flex flex-col p-0 gap-0">
        <SheetHeader className="border-b border-border">
          <SheetTitle>Ask the AI</SheetTitle>
          <p className="text-xs text-muted-foreground">
            Why was something detected or missed for <span className="text-foreground">{selected?.suggestion}</span>? Explain-only.
          </p>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {!messages.length && (
            <p className="text-sm text-muted-foreground">
              Ask why an item was or wasn't picked up — e.g. "why wasn't the ensuite renovation detected?"
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} ref={i === messages.length - 1 ? (el) => el?.scrollIntoView({ block: "nearest" }) : null}
              className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
              <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap ${
                m.role === "user" ? "bg-primary text-primary-foreground" : "bg-secondary"}`}>
                {m.content}
              </div>
            </div>
          ))}
          {busy && <p className="flex items-center gap-2 text-sm text-muted-foreground"><span className="spinner" /> Thinking…</p>}
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <div className="border-t border-border p-3 space-y-2">
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
            <Checkbox checked={includePhotos} onCheckedChange={(v) => setIncludePhotos(!!v)} />
            Include photos (let the AI re-inspect the images)
          </label>
          <div className="flex gap-2 items-end">
            <Textarea rows={2} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKeyDown}
              placeholder="Ask a question…" className="resize-none" />
            <Button onClick={send} disabled={busy || !input.trim()}>Send</Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
