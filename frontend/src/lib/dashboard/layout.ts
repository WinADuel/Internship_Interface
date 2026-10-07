export interface WidgetLayoutEntry {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  settings: Record<string, unknown>;
}

export const LAYOUT_STORAGE_KEY = "dashboard-layout-v1";

function isEntry(v: unknown): v is WidgetLayoutEntry {
  if (typeof v !== "object" || v === null) return false;
  const e = v as Record<string, unknown>;
  const num = (n: unknown) => typeof n === "number" && Number.isFinite(n);
  return (
    typeof e.id === "string" &&
    num(e.x) && num(e.y) && num(e.w) && num(e.h) &&
    typeof e.settings === "object" && e.settings !== null && !Array.isArray(e.settings)
  );
}

/** Reconciles a saved layout with the current widget set: drops unknown ids, dedupes (first wins), appends missing defaults. */
export function reconcileLayout(saved: WidgetLayoutEntry[], defaults: WidgetLayoutEntry[]): WidgetLayoutEntry[] {
  const known = new Set(defaults.map((d) => d.id));
  const seen = new Set<string>();
  const result: WidgetLayoutEntry[] = [];
  for (const e of saved) {
    if (!known.has(e.id) || seen.has(e.id)) continue;
    seen.add(e.id);
    result.push(e);
  }
  for (const d of defaults) if (!seen.has(d.id)) result.push(d);
  return result;
}

export function loadLayout(defaults: WidgetLayoutEntry[]): WidgetLayoutEntry[] {
  try {
    const raw = localStorage.getItem(LAYOUT_STORAGE_KEY);
    if (raw === null) return defaults;
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every(isEntry)) return reconcileLayout(parsed, defaults);
  } catch {
    // unavailable storage or corrupted JSON: use defaults
  }
  return defaults;
}

export function saveLayout(layout: WidgetLayoutEntry[]): void {
  try {
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // storage unavailable or full: ignore
  }
}
