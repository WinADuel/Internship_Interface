import { parseLocalDate } from "./dashboard/widgets";

const pad = (n: number): string => String(n).padStart(2, "0");

/** `<input type="datetime-local">` value (local time, no zone) -> ISO UTC string, or null if blank/invalid. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** ISO instant -> `<input type="datetime-local">` value in the viewer's local time ("" if blank/invalid). */
export function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** An ISO timestamp in the viewer's locale and time zone; unparseable text is returned as is. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** A date-only "YYYY-MM-DD" value as that local calendar day; unparseable text is returned as is. */
export function formatDate(value: string): string {
  const d = parseLocalDate(value);
  return d ? d.toLocaleDateString() : value;
}
