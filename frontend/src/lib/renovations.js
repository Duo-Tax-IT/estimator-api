import { parseMoney } from "./money";

// Full ancestor path for a row (root → immediate parent); older runs only carry
// parentName, so fall back to a single level.
export const pathOf = (r) =>
  r.groupPath && r.groupPath.length ? r.groupPath : r.parentName ? [r.parentName] : [];

export const sumCost = (renos) => renos.reduce((t, r) => t + parseMoney(r.FinalCost), 0);

// Mirror of pricing.collapse_parent: replace a parent's subtree with one row =
// subtree's summed FinalCost × multiplier.
export function collapseParent(renos, parent, multiplier = 1) {
  const inGroup = (r) => pathOf(r).includes(parent);
  const under = renos.filter(inGroup);
  if (!under.length) return renos;
  const base = sumCost(under);
  return [...renos.filter((r) => !inGroup(r)), { Name: parent, FinalCost: base * multiplier }];
}

// Subtree cost for every group, keyed by its joined path ("a › b").
export function subtreeTotals(renos) {
  const sub = {};
  for (const r of renos) {
    const p = pathOf(r), c = parseMoney(r.FinalCost);
    for (let d = 0; d < p.length; d++) {
      const k = p.slice(0, d + 1).join(" › ");
      sub[k] = (sub[k] || 0) + c;
    }
  }
  return sub;
}

// Flatten renovations into render-ready rows: group headers (opened when the
// path deepens/changes) interleaved with their item rows. Keeps the grouping
// walk out of the component.
export function buildRows(renos) {
  const rows = [];
  let last = [];
  for (const r of renos) {
    const p = pathOf(r);
    let common = 0;
    while (common < p.length && common < last.length && p[common] === last[common]) common++;
    for (let d = common; d < p.length; d++) {
      const key = p.slice(0, d + 1).join(" › ");
      rows.push({
        kind: "group",
        depth: d,
        key,
        anc: p.slice(0, d).join(" › "), // groups this header sits inside
        name: p[d],
        topParent: d === 0 ? p[0] : null, // top parents carry the ×-scale control
      });
    }
    last = p;
    rows.push({ kind: "item", depth: p.length, anc: p.join(" › "), item: r });
  }
  return rows;
}

// A row hides when any collapsed group key is one of its ancestors.
export const isHidden = (anc, collapsed) =>
  [...collapsed].some((k) => anc === k || anc.startsWith(k + " › "));

// Grand total with each checked parent's subtree collapsed × its multiplier.
export function scaledTotal(renos, scales) {
  let scaled = renos;
  for (const [parent, sc] of Object.entries(scales)) {
    if (sc.on) scaled = collapseParent(scaled, parent, sc.mul ?? 1);
  }
  return sumCost(scaled);
}
