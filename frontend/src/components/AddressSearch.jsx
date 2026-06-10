import { useEffect, useRef, useState } from "react";
import { searchAddress } from "@/api";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

// Debounced address search with a suggestions dropdown. `onSelect(suggestion)`
// fires on pick. Reused by the estimator and the playground.
export default function AddressSearch({ onSelect, placeholder = "Search an address…", inputClassName }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState(null); // null = dropdown closed
  const [searching, setSearching] = useState(false);
  const timer = useRef();
  const active = useRef("");
  const box = useRef();

  // Dismiss the dropdown when clicking outside the search box.
  useEffect(() => {
    const onDoc = (e) => { if (box.current && !box.current.contains(e.target)) setItems(null); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function onChange(e) {
    const v = e.target.value;
    setQ(v);
    const query = v.trim();
    active.current = query;
    clearTimeout(timer.current);
    if (query.length < 3) { setSearching(false); setItems(null); return; }
    setSearching(true);
    setItems(null);
    timer.current = setTimeout(() => run(query), 300);
  }

  async function run(query) {
    try {
      const suggestions = await searchAddress(query);
      if (query !== active.current) return; // a newer keystroke won
      setItems(suggestions);
    } catch {
      setItems([]);
    } finally {
      if (query === active.current) setSearching(false);
    }
  }

  function pick(s) {
    setItems(null);
    setQ(s.suggestion);
    active.current = s.suggestion;
    onSelect(s);
  }

  return (
    <div ref={box} className="relative">
      <Input value={q} onChange={onChange} placeholder={placeholder} autoComplete="off" className={inputClassName} />
      {searching && <span className="spinner absolute right-3 top-1/2 -translate-y-1/2" />}

      {items !== null && (
        <div className="absolute z-20 top-[calc(100%+6px)] inset-x-0 bg-popover border border-border rounded-xl overflow-hidden shadow-2xl">
          {items.length === 0 ? (
            <div className="px-4 py-3 text-sm text-muted-foreground">No matching addresses.</div>
          ) : (
            items.map((s, j) => (
              <button key={j} type="button" onClick={() => pick(s)}
                className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left text-sm border-b border-border last:border-0 hover:bg-accent transition-colors">
                <span className="flex-1">{s.suggestion}</span>
                <Badge variant="secondary">{s.isUnit ? "Unit" : s.suggestionType || "address"}</Badge>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
