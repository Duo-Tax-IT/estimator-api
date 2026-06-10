import { useState } from "react";
import Lightbox from "./Lightbox";

// Sliding image + prev/next + thumbs + counter/date. Photos are { url, date? }.
// Clicking the main image opens a fullscreen Lightbox (shared index). Parent
// should pass a `key` (e.g. the rp_id) so a new property resets to slide 0.
export default function PhotoCarousel({ photos = [] }) {
  const [i, setI] = useState(0);
  const [zoom, setZoom] = useState(false);
  if (!photos.length) return null;

  const n = photos.length;
  const multi = n > 1;
  const idx = Math.min(i, n - 1);
  const move = (d) => setI((x) => (x + d + n) % n);
  const nav = "absolute top-1/2 -translate-y-1/2 grid place-items-center w-10 h-10 rounded-full " +
    "border border-border bg-background/65 backdrop-blur text-2xl leading-none hover:bg-background/95";

  return (
    <div className="relative">
      <div onClick={() => setZoom(true)} title="Click to enlarge"
           className="overflow-hidden rounded-xl border border-border bg-secondary aspect-video cursor-zoom-in">
        <div className="flex h-full transition-transform duration-300"
             style={{ transform: `translateX(-${idx * 100}%)` }}>
          {photos.map((p, j) => (
            <div key={j} className="min-w-full h-full">
              <img loading="lazy" alt="Property photo" src={p.url} className="w-full h-full object-cover" />
            </div>
          ))}
        </div>
      </div>

      {multi && (
        <>
          <button type="button" aria-label="Previous photo" onClick={() => move(-1)} className={`${nav} left-2.5`}>‹</button>
          <button type="button" aria-label="Next photo" onClick={() => move(1)} className={`${nav} right-2.5`}>›</button>
        </>
      )}

      <div className="flex justify-between mt-2 text-xs text-muted-foreground tabular-nums">
        <span>{idx + 1} / {n}</span>
        <span>{photos[idx]?.date || ""}</span>
      </div>

      {multi && (
        <div className="flex gap-2 mt-2.5 overflow-x-auto pb-1">
          {photos.map((p, j) => (
            <img key={j} loading="lazy" alt={`Photo ${j + 1}`} src={p.url} onClick={() => setI(j)}
                 className={`flex-none w-[68px] h-[50px] object-cover rounded-lg border-2 cursor-pointer transition ${
                   j === idx ? "border-primary opacity-100" : "border-transparent opacity-55 hover:opacity-85"}`} />
          ))}
        </div>
      )}

      {zoom && <Lightbox photos={photos} index={idx} onIndex={setI} onClose={() => setZoom(false)} />}
    </div>
  );
}
