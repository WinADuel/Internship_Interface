/** "YYYY-MM-DD" from a date input -> ISO instant at local noon (stable across time zones). */
export function dateInputToIso(value: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const d = new Date(`${value}T12:00:00`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

/** A datetime-local value -> ISO instant (with zone, as the API requires). */
export function datetimeInputToIso(value: string): string | undefined {
  if (!value) return undefined;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}
