export const parseMoney = (s) => Number(String(s ?? "").replace(/[$,]/g, "")) || 0;

export const fmtMoney = (n) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Run duration: blank when unknown (old runs), "850 ms" under a second, else "12.3 s".
export const fmtDuration = (ms) =>
  ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
