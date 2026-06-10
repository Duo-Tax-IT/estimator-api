import { Button } from "@/components/ui/button";

// Choose which photos go to the AI (Observe/Era). `selected` is a Set of urls.
export default function PhotoPicker({ photos, selected, onToggle, onBulk }) {
  if (!photos.length) return null;
  return (
    <>
      <div className="flex items-center gap-2 mt-2 text-sm">
        <strong>{selected.size} / {photos.length} selected</strong>
        <Button size="sm" variant="secondary" onClick={() => onBulk("20")}>First 20</Button>
        <Button size="sm" variant="secondary" onClick={() => onBulk("all")}>All</Button>
        <Button size="sm" variant="secondary" onClick={() => onBulk("none")}>None</Button>
      </div>
      <div className="flex flex-wrap gap-2 mt-2.5">
        {photos.map((p, i) => {
          const on = selected.has(p.url);
          return (
            <label key={i} className="relative w-[110px] block cursor-pointer">
              <input type="checkbox" checked={on} onChange={() => onToggle(p.url)} className="absolute top-1 left-1 w-4 h-4 z-10" />
              <img src={p.url} loading="lazy"
                className={`w-[110px] h-20 object-cover rounded-md border-2 transition ${on ? "border-primary opacity-100" : "border-border opacity-45"}`} />
              <span className="block text-[11px] text-muted-foreground">#{i}{p.date ? " · " + p.date : ""}</span>
            </label>
          );
        })}
      </div>
    </>
  );
}
