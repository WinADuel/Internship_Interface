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

export function loadLayout(defaults: WidgetLayoutEntry[]): WidgetLayoutEntry[] {
  try {
    const raw = localStorage.getItem(LAYOUT_STORAGE_KEY);
    if (raw === null) return defaults;
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every(isEntry)) return parsed;
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
