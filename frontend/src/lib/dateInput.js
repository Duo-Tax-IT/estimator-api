// Live dd/mm/yyyy formatter: digits only, insert slashes, expand a 2-digit year
// (>=50 -> 19xx, else 20xx) once day+month+yy are in.
const expandYear = (yy) => String(+yy >= 50 ? 1900 + +yy : 2000 + +yy);

export function formatDateInput(value) {
  const n = value.replace(/\D/g, "").slice(0, 8);
  let out = n.slice(0, 2);
  if (n.length >= 3) out += "/" + n.slice(2, 4);
  if (n.length >= 5) out += "/" + (n.length === 6 ? expandYear(n.slice(4)) : n.slice(4));
  return out;
}

// dd/mm/yyyy -> yyyy-mm-dd (what the backend expects); "" until complete.
export function settlementIso(ddmmyyyy) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec((ddmmyyyy || "").trim());
  return m ? `${m[3]}-${m[2]}-${m[1]}` : "";
}
