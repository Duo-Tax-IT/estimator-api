import { useEffect } from "react";

// Fullscreen photo viewer over a dark transparent backdrop. Controlled: the
// parent owns `index` (so the small carousel stays in sync). Close on backdrop
// click, the × button, or Esc; navigate with the arrows or ← → keys.
export default function Lightbox({ photos, index, onIndex, onClose }) {
  const n = photos.length;

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") onIndex((index - 1 + n) % n);
      else if (e.key === "ArrowRight") onIndex((index + 1) % n);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [index, n, onIndex, onClose]);

  const p = photos[index];
  const multi = n > 1;
  const move = (d, e) => { e.stopPropagation(); onIndex((index + d + n) % n); };
  const arrow = "grid place-items-center w-8 h-8 rounded-full hover:bg-white/15 text-2xl leading-none";

  return (
    <div onClick={onClose} className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-6">
      <button onClick={onClose} aria-label="Close" className="absolute top-4 right-5 text-white/70 hover:text-white text-3xl leading-none">×</button>

      <img src={p.url} alt="Property photo" onClick={(e) => e.stopPropagation()}
        className="max-h-[82vh] max-w-[92vw] object-contain rounded-lg shadow-2xl" />

      {/* Arrows + counter clustered at bottom-centre so navigation stays in reach. */}
      <div onClick={(e) => e.stopPropagation()}
        className="absolute bottom-5 left-1/2 -translate-x-1/2 flex items-center gap-3 pl-2 pr-3 py-1.5 rounded-full bg-white/10 backdrop-blur text-white">
        {multi && <button onClick={(e) => move(-1, e)} aria-label="Previous" className={arrow}>‹</button>}
        <span className="text-sm tabular-nums whitespace-nowrap">{index + 1} / {n}{p?.date ? ` · ${p.date}` : ""}</span>
        {multi && <button onClick={(e) => move(1, e)} aria-label="Next" className={arrow}>›</button>}
      </div>
    </div>
  );
}
