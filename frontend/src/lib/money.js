export const parseMoney = (s) => Number(String(s ?? "").replace(/[$,]/g, "")) || 0;

export const fmtMoney = (n) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
