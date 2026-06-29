import { useEffect, useState } from "react";
import { getSessions, getApplied, markApplied } from "@/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import TopBar from "@/components/TopBar";

const PRIORITY = { high: 0, medium: 1, low: 2 };

// Flatten every session's recommendations; key = session:index (stable id for the
// applied flag). Grouped by target prompt, high→low priority.
function recsByTarget(sessions) {
  const recs = sessions.flatMap((s) =>
    (s.analysis.tuningRecommendations || []).map((r, i) => ({ ...r, runId: s.run_id, key: `${s.id}:${i}` })));
  recs.sort((a, b) => (PRIORITY[a.priority] ?? 9) - (PRIORITY[b.priority] ?? 9));
  const groups = {};
  for (const r of recs) (groups[r.target || "other"] ||= []).push(r);
  return Object.entries(groups);
}

// Markdown of the unapplied recs, ready to paste to Claude.
function toText(groups, applied) {
  let out = "Apply these tuning recommendations to the estimator prompts:\n";
  for (const [target, list] of groups) {
    const pending = list.filter((r) => !applied.has(r.key));
    if (!pending.length) continue;
    out += `\n## ${target}\n`;
    for (const r of pending) out += `- [${r.priority || "?"}] (run #${r.runId}) ${r.change}\n  rationale: ${r.rationale || ""}\n`;
  }
  return out;
}

export default function Suggestions() {
  const [sessions, setSessions] = useState([]);
  const [applied, setApplied] = useState(() => new Set());
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getSessions().then(setSessions).catch(() => {});
    getApplied().then((a) => setApplied(new Set(a))).catch(() => {});
  }, []);

  function toggle(key) {
    const [sid, idx] = key.split(":").map(Number);
    const next = new Set(applied);
    const nowApplied = !next.has(key);
    nowApplied ? next.add(key) : next.delete(key);
    setApplied(next);
    markApplied(sid, idx, nowApplied).catch(() => {});
  }

  const groups = recsByTarget(sessions);
  const total = groups.reduce((n, [, l]) => n + l.length, 0);

  async function copyAll() {
    await navigator.clipboard.writeText(toText(groups, applied));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <>
      <TopBar />

      <main className="max-w-[900px] mx-auto p-5 space-y-4">
        <div className="flex items-center gap-3">
          <p className="text-sm text-muted-foreground flex-1">{total} recommendations · {applied.size} applied</p>
          <Button size="sm" disabled={!total} onClick={copyAll}>{copied ? "Copied ✓" : "Copy unapplied for Claude"}</Button>
        </div>

        {!total ? <p className="text-sm text-muted-foreground">No recommendations yet. Analyze a run on the Learning page.</p>
          : groups.map(([target, list]) => (
          <Card key={target} className="p-4">
            <h2 className="text-sm font-medium mb-2">{target} · {list.length}</h2>
            {list.map((r) => {
              const done = applied.has(r.key);
              return (
                <div key={r.key} className={`card p-2.5 mb-2 ${done ? "opacity-50" : ""}`}>
                  <Badge variant="outline" className={r.priority === "high" ? "text-destructive border-destructive/40" : ""}>{r.priority || ""}</Badge>
                  <a href={`/run/${r.runId}`} className="text-xs text-primary hover:underline ml-1">run #{r.runId}</a>
                  <b className={`text-[13px] block mt-1 ${done ? "line-through" : ""}`}>{r.change || ""}</b>
                  <div className="text-xs mt-1 text-muted-foreground">{r.rationale || ""}</div>
                  <button onClick={() => toggle(r.key)} className="text-xs text-primary hover:underline mt-1">{done ? "mark not applied" : "mark applied"}</button>
                </div>
              );
            })}
          </Card>
        ))}
      </main>
    </>
  );
}
